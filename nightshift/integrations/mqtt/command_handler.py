"""MQTT command handler with validation, dispatch, and idempotency."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nightshift.domain.models import SystemState, WorkState
from nightshift.integrations.mqtt.schemas import (
    CommandEnvelope,
    ReplyMessage,
    SchemaError,
    parse_command,
)
from nightshift.integrations.mqtt.topics import TopicBuilder

if TYPE_CHECKING:
    from nightshift.services.orchestrator import NightshiftOrchestrator

log = logging.getLogger(__name__)

CommandDispatcher = Callable[
    [CommandEnvelope, SystemState],
    Coroutine[Any, Any, tuple[bool, str, dict[str, Any]]],
]

_CACHE_RETRY_WINDOW_MS = 60_000


@dataclass
class _CachedReply:
    digest: str
    reply: ReplyMessage
    expires_at_ms: int


class MqttCommandHandler:
    def __init__(
        self,
        *,
        topics: TopicBuilder,
        orchestrator: NightshiftOrchestrator,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._topics = topics
        self._orchestrator = orchestrator
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, _CachedReply] = {}

    async def handle(self, payload: bytes | str) -> tuple[str, ReplyMessage] | None:
        try:
            envelope = parse_command(payload)
        except SchemaError as exc:
            log.warning("mqtt: command rejected: %s: %s", exc.code, exc)
            return None

        if not self._topics.validate_reply_to(envelope.reply_to, envelope.client_id):
            log.warning(
                "mqtt: command rejected: reply_to %r does not match client_id %r",
                envelope.reply_to,
                envelope.client_id,
            )
            return None

        now = self._now_ms()
        if now > envelope.sent_at_ms + envelope.ttl_ms:
            reply = self._make_reply(
                envelope,
                ok=False,
                code="expired",
                message="command has expired",
            )
            return envelope.reply_to, reply

        digest = self._command_digest(envelope)
        cached = self._cache.get(envelope.request_id)
        if cached is not None:
            if now <= cached.expires_at_ms:
                if cached.digest != digest:
                    reply = self._make_reply(
                        envelope,
                        ok=False,
                        code="state_conflict",
                        message="request_id was already used for a different command",
                    )
                    return envelope.reply_to, reply
                log.info(
                    "mqtt: returning cached reply for request_id=%s",
                    envelope.request_id,
                )
                return envelope.reply_to, cached.reply

        self._evict_cache(now)

        ok, code, message, data = await self._dispatch(envelope)

        reply = ReplyMessage(
            request_id=envelope.request_id,
            ok=ok,
            code=code,
            message=message,
            revision=self._orchestrator.state.revision,
            replied_at_ms=self._now_ms(),
            data=data,
        )

        self._cache[envelope.request_id] = _CachedReply(
            digest=digest,
            reply=reply,
            expires_at_ms=(
                envelope.sent_at_ms
                + envelope.ttl_ms
                + _CACHE_RETRY_WINDOW_MS
            ),
        )

        return envelope.reply_to, reply

    async def _dispatch(
        self, envelope: CommandEnvelope
    ) -> tuple[bool, str, str, dict[str, Any]]:
        state = self._orchestrator.state

        if envelope.command == "executor.pause":
            if state.work_state == WorkState.RUNNING:
                await self._orchestrator.pause_executor()
                return True, "ok", "executor paused", {}
            return False, "state_conflict", "executor is not running", {}

        if envelope.command == "executor.resume":
            if state.work_state == WorkState.PAUSED:
                await self._orchestrator.resume_executor()
                return True, "ok", "executor resumed", {}
            return False, "state_conflict", "executor is not paused", {}

        if envelope.command == "system.resync_panel":
            await self._orchestrator.resync_panel()
            return True, "ok", "panel resync triggered", {}

        if envelope.command == "task.confirm":
            return await self._handle_task_confirm(envelope)

        if envelope.command == "task.reject":
            return await self._handle_task_reject(envelope)

        if envelope.command == "task.retry":
            return await self._handle_task_retry(envelope)

        if envelope.command == "notice.dismiss":
            return await self._handle_notice_dismiss(envelope)

        return False, "invalid_argument", f"unhandled command: {envelope.command}", {}

    async def _handle_task_confirm(
        self, envelope: CommandEnvelope
    ) -> tuple[bool, str, str, dict[str, Any]]:
        svc = self._orchestrator._confirmation_service
        if svc is None:
            return False, "not_ready", "services not initialized", {}
        task_id = envelope.args.get("task_id")
        if type(task_id) is not int:
            return False, "invalid_argument", "task_id must be an integer", {}
        from nightshift.domain.commands import OBJ_TASK
        from nightshift.services.confirmation_service import ConfirmationError

        now_ms = self._now_ms()
        try:
            result = await svc.confirm(OBJ_TASK, task_id, now_ms=now_ms)
        except ConfirmationError as exc:
            return False, "not_found", str(exc), {}
        await self._orchestrator._update_confirmation_count(
            result.pending_count, now_ms
        )
        return True, "ok", "task confirmed", {"pending_count": result.pending_count}

    async def _handle_task_reject(
        self, envelope: CommandEnvelope
    ) -> tuple[bool, str, str, dict[str, Any]]:
        svc = self._orchestrator._confirmation_service
        if svc is None:
            return False, "not_ready", "services not initialized", {}
        task_id = envelope.args.get("task_id")
        if type(task_id) is not int:
            return False, "invalid_argument", "task_id must be an integer", {}
        from nightshift.domain.commands import OBJ_TASK
        from nightshift.services.confirmation_service import ConfirmationError

        now_ms = self._now_ms()
        try:
            result = await svc.reject(OBJ_TASK, task_id, now_ms=now_ms)
        except ConfirmationError as exc:
            return False, "not_found", str(exc), {}
        await self._orchestrator._update_confirmation_count(
            result.pending_count, now_ms
        )
        return True, "ok", "task rejected", {"pending_count": result.pending_count}

    async def _handle_task_retry(
        self, envelope: CommandEnvelope
    ) -> tuple[bool, str, str, dict[str, Any]]:
        task_svc = self._orchestrator._task_service
        if task_svc is None:
            return False, "not_ready", "services not initialized", {}
        task_id = envelope.args.get("task_id")
        if type(task_id) is not int:
            return False, "invalid_argument", "task_id must be an integer", {}
        now_ms = self._now_ms()
        task = await task_svc.retry(task_id, now_ms=now_ms)
        if task is None:
            return False, "not_found", f"task {task_id} not in failed state", {}
        pending_count = await task_svc.count_pending()
        await self._orchestrator._update_confirmation_count(
            pending_count, now_ms
        )
        return True, "ok", "task retried", {
            "task_id": task.id,
            "pending_count": pending_count,
        }

    async def _handle_notice_dismiss(
        self, envelope: CommandEnvelope
    ) -> tuple[bool, str, str, dict[str, Any]]:
        if self._orchestrator._notice_service is None:
            return False, "not_ready", "services not initialized", {}
        notice_id = envelope.args.get("notice_id")
        if type(notice_id) is not int:
            return False, "invalid_argument", "notice_id must be an integer", {}
        now_ms = self._now_ms()
        if not await self._orchestrator.dismiss_notice(notice_id, now_ms=now_ms):
            return False, "not_found", f"notice {notice_id} not active", {}
        return True, "ok", "notice dismissed", {"notice_id": notice_id}

    def _make_reply(
        self,
        envelope: CommandEnvelope,
        *,
        ok: bool,
        code: str,
        message: str,
    ) -> ReplyMessage:
        return ReplyMessage(
            request_id=envelope.request_id,
            ok=ok,
            code=code,
            message=message,
            revision=self._orchestrator.state.revision,
            replied_at_ms=self._now_ms(),
        )

    def _evict_cache(self, now_ms: int) -> None:
        expired = [
            rid for rid, entry in self._cache.items() if now_ms > entry.expires_at_ms
        ]
        for rid in expired:
            del self._cache[rid]

    @staticmethod
    def _command_digest(envelope: CommandEnvelope) -> str:
        normalized = json.dumps(
            {
                "client_id": envelope.client_id,
                "reply_to": envelope.reply_to,
                "sent_at_ms": envelope.sent_at_ms,
                "ttl_ms": envelope.ttl_ms,
                "command": envelope.command,
                "args": envelope.args,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()
