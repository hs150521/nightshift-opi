"""MQTT command handler with validation, dispatch, and idempotency."""

from __future__ import annotations

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

_CACHE_TTL_MS = 60_000


@dataclass
class _CachedReply:
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

        cached = self._cache.get(envelope.request_id)
        if cached is not None:
            if now <= cached.expires_at_ms:
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
            reply=reply,
            expires_at_ms=self._now_ms() + _CACHE_TTL_MS,
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

        if envelope.command in ("task.confirm", "task.reject", "task.retry"):
            return (
                False,
                "not_found",
                "task service is not yet implemented",
                {},
            )

        if envelope.command == "notice.dismiss":
            return (
                False,
                "not_found",
                "notice service is not yet implemented",
                {},
            )

        return False, "invalid_argument", f"unhandled command: {envelope.command}", {}

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
