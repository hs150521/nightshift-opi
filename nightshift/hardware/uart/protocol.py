"""T5-Link v1 frame builder and parser."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from nightshift.domain import commands as cmd
from nightshift.domain.models import (
    AttentionFlag,
    DashboardState,
    SystemMode,
    WorkState,
)

MAGIC = b"\x54\x35"
VERSION = 0x01
MAX_PAYLOAD = 1024


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class Frame:
    version: int
    flags: int
    sequence: int
    command: int
    payload: bytes

    @property
    def raw(self) -> bytes:
        length = len(self.payload)
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"payload {length} exceeds max {MAX_PAYLOAD}")
        return struct.pack(
            "<2sBBHHH",
            MAGIC,
            self.version,
            self.flags,
            self.sequence,
            self.command,
            length,
        ) + self.payload

    @classmethod
    def parse(cls, raw: bytes) -> Frame:
        if len(raw) < 10:
            raise ProtocolError("frame too short")
        magic, version, flags, sequence, command, length = struct.unpack("<2sBBHHH", raw[:10])
        if magic != MAGIC:
            raise ProtocolError("bad magic")
        if version != VERSION:
            raise ProtocolError("unsupported version")
        if len(raw) < 10 + length:
            raise ProtocolError("frame truncated")
        payload = raw[10 : 10 + length]
        return cls(
            version=version,
            flags=flags,
            sequence=sequence,
            command=command,
            payload=payload,
        )

    def response(self, status: int, data: bytes = b"") -> Frame:
        return Frame(
            version=self.version,
            flags=cmd.FLAG_RESPONSE,
            sequence=self.sequence,
            command=self.command,
            payload=status.to_bytes(2, "little") + data,
        )

    @classmethod
    def request(
        cls,
        sequence: int,
        command: int,
        payload: bytes = b"",
        flags: int = cmd.FLAG_ACK_REQ,
    ) -> Frame:
        return cls(
            version=VERSION,
            flags=flags,
            sequence=sequence,
            command=command,
            payload=payload,
        )


# Payload builders


def encode_hello(
    peer_role: int,
    protocol_major: int,
    protocol_minor: int,
    boot_id: int,
    max_payload: int,
    capabilities: int,
    software_version: str,
) -> bytes:
    return struct.pack(
        "<BBBIIH",
        peer_role,
        protocol_major,
        protocol_minor,
        boot_id,
        max_payload,
        capabilities,
    ) + _encode_string(software_version)


def encode_heartbeat(uptime_ms: int, state_revision: int) -> bytes:
    return struct.pack("<II", uptime_ms, state_revision)


def encode_state_sync_begin(revision: int, reason: int) -> bytes:
    return struct.pack("<IB", revision, reason)


def encode_state_sync_end(revision: int, snapshot_crc32: int) -> bytes:
    return struct.pack("<II", revision, snapshot_crc32)


def encode_mode_set(revision: int, mode: SystemMode, changed_at_ms: int, reason: int = 0) -> bytes:
    return struct.pack(
        "<IBIQ",
        revision,
        cmd.MODE_TO_BYTE[mode.value],
        reason,
        changed_at_ms,
    )


def encode_attention_set(
    revision: int,
    attention: AttentionFlag,
    confirmation_count: int,
    short_message: str = "",
) -> bytes:
    return (
        struct.pack(
            "<IIH",
            revision,
            int(attention),
            confirmation_count,
        )
        + _encode_string(short_message)
    )


def encode_work_state_set(
    revision: int,
    work_state: WorkState,
    progress_permille: int = 0,
    token_input: int = 0,
    token_output: int = 0,
    elapsed_seconds: int = 0,
    current_task_id: int = 0,
    current_task_title: str = "",
) -> bytes:
    return (
        struct.pack(
            "<BHHIIII",
            cmd.WORK_STATE_TO_BYTE[work_state.value],
            progress_permille,
            0,  # reserved
            token_input,
            token_output,
            elapsed_seconds,
            current_task_id,
        )
        + _encode_string(current_task_title)
    )


def encode_dashboard_set(revision: int, dashboard: DashboardState) -> bytes:
    return struct.pack(
        "<IHHHHHH",
        revision,
        dashboard.urgent_auto,
        dashboard.normal_auto,
        dashboard.urgent_confirm,
        dashboard.normal_confirm,
        dashboard.completed_today,
        dashboard.failed_today,
    )


def encode_ui_action(
    action: int,
    object_type: int,
    object_id: int,
    value: int,
    text: str,
) -> bytes:
    return struct.pack(
        "<HBIi",
        action,
        object_type,
        object_id,
        value,
    ) + _encode_string(text)


def parse_heartbeat_response(payload: bytes) -> dict[str, int]:
    if len(payload) < 10:
        raise ProtocolError("heartbeat response too short")
    status = int.from_bytes(payload[:2], "little")
    t5_uptime_ms, applied_revision, error_flags = struct.unpack("<III", payload[2:14])
    return {
        "status": status,
        "t5_uptime_ms": t5_uptime_ms,
        "applied_revision": applied_revision,
        "error_flags": error_flags,
    }


def parse_ui_action(payload: bytes) -> tuple[int, int, int, int, str]:
    if len(payload) < 10:
        raise ProtocolError("ui_action payload too short")
    action, object_type, object_id, value = struct.unpack("<HBIi", payload[:10])
    text = _decode_string(payload[10:])
    return action, object_type, object_id, value, text


def _encode_string(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return len(encoded).to_bytes(2, "little") + encoded


def _decode_string(data: bytes) -> str:
    if len(data) < 2:
        return ""
    length = int.from_bytes(data[:2], "little")
    return data[2 : 2 + length].decode("utf-8", errors="replace")
