"""Centralized MQTT topic generation."""

from __future__ import annotations

import re

_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class TopicBuilder:
    def __init__(self, base_topic: str, node_id: str) -> None:
        if base_topic.endswith("/"):
            raise ValueError("base_topic must not end with /")
        self._root = f"{base_topic}/opi/{node_id}"

    @property
    def root(self) -> str:
        return self._root

    def availability(self) -> str:
        return f"{self._root}/availability"

    def state(self) -> str:
        return f"{self._root}/state"

    def event(self) -> str:
        return f"{self._root}/event"

    def telemetry(self) -> str:
        return f"{self._root}/telemetry"

    def command(self) -> str:
        return f"{self._root}/command"

    def reply(self, client_id: str) -> str:
        if not _CLIENT_ID_RE.match(client_id):
            raise ValueError(f"invalid client_id: {client_id!r}")
        return f"{self._root}/reply/{client_id}"

    def validate_reply_to(self, reply_to: str, client_id: str) -> bool:
        expected = self.reply(client_id)
        if reply_to != expected:
            return False
        if "+" in reply_to or "#" in reply_to:
            return False
        return True
