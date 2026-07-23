"""MQTT message schemas and validation."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from nightshift.domain.models import (
    AttentionFlag,
    DashboardState,
    SystemState,
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

COMMAND_WHITELIST: dict[str, set[str]] = {
    "task.confirm": {"task_id"},
    "task.reject": {"task_id"},
    "task.retry": {"task_id"},
    "executor.pause": set(),
    "executor.resume": set(),
    "notice.dismiss": {"notice_id"},
    "system.resync_panel": set(),
}


class SchemaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandEnvelope:
    schema: str
    request_id: str
    client_id: str
    reply_to: str
    sent_at_ms: int
    ttl_ms: int
    command: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ReplyMessage:
    request_id: str
    ok: bool
    code: str
    message: str
    revision: int
    replied_at_ms: int
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": "nightshift.reply.v1",
                "request_id": self.request_id,
                "ok": self.ok,
                "code": self.code,
                "message": self.message,
                "revision": self.revision,
                "replied_at_ms": self.replied_at_ms,
                "data": self.data,
            }
        )


def parse_command(payload: bytes | str) -> CommandEnvelope:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("invalid_schema", "payload is not valid UTF-8") from exc
    else:
        text = payload

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError("invalid_schema", "payload is not valid JSON") from exc

    if not isinstance(obj, dict):
        raise SchemaError("invalid_schema", "payload must be a JSON object")

    schema = obj.get("schema")
    if schema != "nightshift.command.v1":
        raise SchemaError("invalid_schema", f"unknown schema: {schema!r}")

    request_id = obj.get("request_id", "")
    if not isinstance(request_id, str) or not _UUID_RE.match(request_id):
        raise SchemaError("invalid_argument", "request_id must be a UUID string")

    client_id = obj.get("client_id", "")
    if not isinstance(client_id, str) or not _CLIENT_ID_RE.match(client_id):
        raise SchemaError("invalid_argument", "client_id is invalid")

    reply_to = obj.get("reply_to", "")
    if not isinstance(reply_to, str) or not reply_to:
        raise SchemaError("invalid_argument", "reply_to is required")

    sent_at_ms = obj.get("sent_at_ms")
    if not isinstance(sent_at_ms, int):
        raise SchemaError("invalid_argument", "sent_at_ms must be an integer")

    ttl_ms = obj.get("ttl_ms")
    if not isinstance(ttl_ms, int) or ttl_ms <= 0:
        raise SchemaError("invalid_argument", "ttl_ms must be a positive integer")

    command = obj.get("command", "")
    if not isinstance(command, str) or command not in COMMAND_WHITELIST:
        raise SchemaError(
            "invalid_argument",
            f"unknown or forbidden command: {command!r}",
        )

    args = obj.get("args", {})
    if not isinstance(args, dict):
        raise SchemaError("invalid_argument", "args must be an object")

    expected_keys = COMMAND_WHITELIST[command]
    extra = set(args.keys()) - expected_keys
    if extra:
        raise SchemaError(
            "invalid_argument",
            f"unexpected args keys for {command}: {extra}",
        )

    return CommandEnvelope(
        schema=schema,
        request_id=request_id,
        client_id=client_id,
        reply_to=reply_to,
        sent_at_ms=sent_at_ms,
        ttl_ms=ttl_ms,
        command=command,
        args=args,
    )


def build_availability(
    *,
    online: bool,
    node_id: str,
    boot_id: str | None = None,
    version: str | None = None,
    started_at_ms: int | None = None,
) -> str:
    msg: dict[str, Any] = {
        "schema": "nightshift.availability.v1",
        "online": online,
        "node_id": node_id,
    }
    if online:
        if boot_id is not None:
            msg["boot_id"] = boot_id
        if version is not None:
            msg["version"] = version
        if started_at_ms is not None:
            msg["started_at_ms"] = started_at_ms
    return json.dumps(msg)


def build_state(
    *,
    state: SystemState,
    node_id: str,
    dashboard: DashboardState | None = None,
) -> str:
    attention = []
    for flag in AttentionFlag:
        if flag in state.attention and flag != AttentionFlag.NONE and flag.name:
            attention.append(flag.name.lower())

    env = state.environment
    panel: dict[str, Any] = {"online": state.panel_online}

    dash = dashboard or DashboardState(
        revision=state.revision,
        urgent_auto=0,
        normal_auto=0,
        urgent_confirm=0,
        normal_confirm=0,
        completed_today=0,
        failed_today=0,
    )

    return json.dumps(
        {
            "schema": "nightshift.system-state.v1",
            "revision": state.revision,
            "node_id": node_id,
            "mode": state.mode,
            "attention": attention,
            "work_state": state.work_state,
            "environment": {
                "ready": env.ready,
                "sit": env.sit,
                "light": env.light,
            },
            "panel": panel,
            "tasks": {
                "urgent_auto": dash.urgent_auto,
                "normal_auto": dash.normal_auto,
                "urgent_confirm": dash.urgent_confirm,
                "normal_confirm": dash.normal_confirm,
                "completed_today": dash.completed_today,
                "failed_today": dash.failed_today,
            },
            "confirmation_count": state.confirmation_count,
            "tokens": {
                "input": state.token_input,
                "output": state.token_output,
            },
            "updated_at_ms": state.updated_at_ms,
        }
    )


def build_event(
    *,
    event_type: str,
    event_id: str,
    revision: int,
    occurred_at_ms: int,
    data: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "schema": "nightshift.event.v1",
            "event_id": event_id,
            "type": event_type,
            "revision": revision,
            "occurred_at_ms": occurred_at_ms,
            "data": data,
        }
    )


def build_lwt(node_id: str) -> str:
    return build_availability(online=False, node_id=node_id)


def new_event_id() -> str:
    return str(uuid.uuid4())
