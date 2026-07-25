"""T5-Link v1 frame builder and parser (canonical wire format)."""

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


# ---------------------------------------------------------------------------
# Canonical dataclasses for parsed responses / events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HelloInfo:
    peer_role: int
    protocol_major: int
    protocol_minor: int
    boot_id: int
    max_payload: int
    capabilities: int
    software_version: str


@dataclass(frozen=True)
class HeartbeatStatus:
    """Canonical HEARTBEAT response payload: `<HIII>`, exactly 14 bytes."""

    status: int
    t5_uptime_ms: int
    applied_revision: int
    error_flags: int


@dataclass(frozen=True)
class GetInfoResponse:
    status: int
    protocol_major: int
    protocol_minor: int
    max_payload: int
    capabilities: int
    display_width: int
    display_height: int
    color_bits: int
    max_tasks: int
    firmware_version: str
    board_name: str


@dataclass(frozen=True)
class PageEventPayload:
    page_id: int
    event: int
    object_id: int


# ---------------------------------------------------------------------------
# Encoders (OPI -> T5)
# ---------------------------------------------------------------------------


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
        "<BBBIHH",
        peer_role,
        protocol_major,
        protocol_minor,
        boot_id,
        max_payload,
        capabilities,
    ) + _encode_string(software_version)


def encode_heartbeat(uptime_ms: int, state_revision: int) -> bytes:
    return struct.pack("<II", uptime_ms, state_revision)


def encode_heartbeat_response(
    status: int,
    t5_uptime_ms: int,
    applied_revision: int,
    error_flags: int,
) -> bytes:
    return struct.pack(
        "<HIII",
        status & 0xFFFF,
        t5_uptime_ms & 0xFFFFFFFF,
        applied_revision & 0xFFFFFFFF,
        error_flags & 0xFFFFFFFF,
    )


def encode_state_sync_begin(revision: int, reason: int) -> bytes:
    return struct.pack("<IB", revision, reason)


def encode_state_sync_end(revision: int, snapshot_crc32: int) -> bytes:
    return struct.pack("<II", revision, snapshot_crc32)


def encode_mode_set(revision: int, mode: SystemMode, changed_at_ms: int, reason: int = 0) -> bytes:
    return struct.pack(
        "<IBBQ",
        revision,
        cmd.MODE_TO_BYTE[mode.value],
        reason & 0xFF,
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
            "<IBHHIIII",
            revision,
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


# --- Frozen T5-Link v1 extension encoders ---------------------------------


def encode_get_info_request() -> bytes:
    return b""


def encode_get_info_response(
    status: int,
    protocol_major: int,
    protocol_minor: int,
    max_payload: int,
    capabilities: int,
    display_width: int,
    display_height: int,
    color_bits: int,
    max_tasks: int,
    firmware_version: str,
    board_name: str,
) -> bytes:
    return (
        struct.pack(
            "<HBBHIHHBB",
            status & 0xFFFF,
            protocol_major & 0xFF,
            protocol_minor & 0xFF,
            max_payload & 0xFFFF,
            capabilities & 0xFFFFFFFF,
            display_width & 0xFFFF,
            display_height & 0xFFFF,
            color_bits & 0xFF,
            max_tasks & 0xFF,
        )
        + _encode_string(firmware_version)
        + _encode_string(board_name)
    )


def encode_time_sync(now_ms: int, tz_offset_minutes: int) -> bytes:
    return struct.pack("<Qh", now_ms & 0xFFFFFFFFFFFFFFFF, tz_offset_minutes)


def encode_notice_show(
    revision: int,
    notice_id: int,
    severity: int,
    flags: int,
    expires_at_ms: int,
    title: str,
    body: str,
) -> bytes:
    return (
        struct.pack(
            "<IIBBQ",
            revision & 0xFFFFFFFF,
            notice_id & 0xFFFFFFFF,
            severity & 0xFF,
            flags & 0xFF,
            expires_at_ms & 0xFFFFFFFFFFFFFFFF,
        )
        + _encode_string(title)
        + _encode_string(body)
    )


def encode_task_list_begin(revision: int, list_type: int, item_count: int) -> bytes:
    return struct.pack(
        "<IBH",
        revision & 0xFFFFFFFF,
        list_type & 0xFF,
        item_count & 0xFFFF,
    )


def encode_task_item(
    revision: int,
    task_id: int,
    quadrant: int,
    task_state: int,
    flags: int,
    title: str,
    source: str,
) -> bytes:
    return (
        struct.pack(
            "<IIBBB",
            revision & 0xFFFFFFFF,
            task_id & 0xFFFFFFFF,
            quadrant & 0xFF,
            task_state & 0xFF,
            flags & 0xFF,
        )
        + _encode_string(title)
        + _encode_string(source)
    )


def encode_task_list_end(revision: int, list_crc32: int) -> bytes:
    return struct.pack(
        "<II",
        revision & 0xFFFFFFFF,
        list_crc32 & 0xFFFFFFFF,
    )


def encode_led_override(
    active: int,
    mode: int,
    period_ms: int,
) -> bytes:
    return struct.pack(
        "<BBH",
        active & 0xFF,
        mode & 0xFF,
        period_ms & 0xFFFF,
    )


def encode_backlight_set(percent: int) -> bytes:
    return struct.pack("<B", percent & 0xFF)


def encode_page_event(page_id: int, event: int, object_id: int) -> bytes:
    return struct.pack(
        "<BBI",
        page_id & 0xFF,
        event & 0xFF,
        object_id & 0xFFFFFFFF,
    )


# ---------------------------------------------------------------------------
# Parsers (T5 -> OPI)
# ---------------------------------------------------------------------------


def parse_hello(payload: bytes) -> HelloInfo:
    if len(payload) < 11:
        raise ProtocolError("hello payload too short")
    peer_role, major, minor, boot_id, max_payload, capabilities = struct.unpack(
        "<BBBIHH", payload[:11]
    )
    version = _decode_string(payload[11:])
    return HelloInfo(
        peer_role=peer_role,
        protocol_major=major,
        protocol_minor=minor,
        boot_id=boot_id,
        max_payload=max_payload,
        capabilities=capabilities,
        software_version=version,
    )


def parse_heartbeat_response(payload: bytes) -> HeartbeatStatus:
    if len(payload) < 14:
        raise ProtocolError("heartbeat response too short")
    status, t5_uptime_ms, applied_revision, error_flags = struct.unpack(
        "<HIII", payload[:14]
    )
    return HeartbeatStatus(
        status=status,
        t5_uptime_ms=t5_uptime_ms,
        applied_revision=applied_revision,
        error_flags=error_flags,
    )


def parse_get_info_response(payload: bytes) -> GetInfoResponse:
    if len(payload) < 14:
        raise ProtocolError("get_info response too short")
    (
        status,
        protocol_major,
        protocol_minor,
        max_payload,
        capabilities,
        display_width,
        display_height,
        color_bits,
        max_tasks,
    ) = struct.unpack("<HBBHIHHBB", payload[:14])
    offset = 14
    firmware_version = _decode_string(payload[offset:])
    str_len = int.from_bytes(payload[offset : offset + 2], "little") if len(payload) > offset + 1 else 0
    offset += 2 + str_len
    board_name = _decode_string(payload[offset:])
    return GetInfoResponse(
        status=status,
        protocol_major=protocol_major,
        protocol_minor=protocol_minor,
        max_payload=max_payload,
        capabilities=capabilities,
        display_width=display_width,
        display_height=display_height,
        color_bits=color_bits,
        max_tasks=max_tasks,
        firmware_version=firmware_version,
        board_name=board_name,
    )


def parse_ui_action(payload: bytes) -> tuple[int, int, int, int, str]:
    if len(payload) < 11:
        raise ProtocolError("ui_action payload too short")
    action, object_type, object_id, value = struct.unpack("<HBIi", payload[:11])
    text = _decode_string(payload[11:])
    return action, object_type, object_id, value, text


def parse_page_event(payload: bytes) -> PageEventPayload:
    if len(payload) < 6:
        raise ProtocolError("page_event payload too short")
    page_id, event, object_id = struct.unpack("<BBI", payload[:6])
    return PageEventPayload(page_id=page_id, event=event, object_id=object_id)


# ---------------------------------------------------------------------------
# String helpers (2-byte little-endian length prefix + utf-8)
# ---------------------------------------------------------------------------


def _encode_string(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return len(encoded).to_bytes(2, "little") + encoded


def _decode_string(data: bytes) -> str:
    if len(data) < 2:
        return ""
    length = int.from_bytes(data[:2], "little")
    return data[2 : 2 + length].decode("utf-8", errors="replace")
