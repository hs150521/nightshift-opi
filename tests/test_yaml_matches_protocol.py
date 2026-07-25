"""Guarantee that commands.yaml payload schemas match protocol.py encoders.

This test protects against silent drift: if you add a payload schema in
`commands.yaml` you MUST also provide encoder/decoder support in
`nightshift.hardware.uart.protocol`, and vice versa.

The check is deliberately narrow — it verifies fixed-width sums for scalar
schemas and validates that encoders exist for every YAML-declared payload.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, DashboardState, SystemMode, WorkState
from nightshift.hardware.uart import protocol as proto

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "uart" / "commands.yaml"

# Widths for scalar YAML types (in bytes).
SCALAR_WIDTHS = {
    "u8": 1,
    "i8": 1,
    "u16": 2,
    "i16": 2,
    "u32": 4,
    "i32": 4,
    "u64": 8,
    "i64": 8,
}

# Canonical example payloads produced by the encoders. Every schema in
# `payloads` MUST have exactly one representative here so we can assert the
# encoder honours the YAML layout width.
ENCODER_EXAMPLES: dict[str, dict[str, bytes]] = {
    "HELLO": {
        "request": proto.encode_hello(
            peer_role=1,
            protocol_major=1,
            protocol_minor=0,
            boot_id=0x11223344,
            max_payload=1024,
            capabilities=0,
            software_version="x",
        ),
    },
    "HEARTBEAT": {
        "request": proto.encode_heartbeat(uptime_ms=1, state_revision=1),
        "response": proto.encode_heartbeat_response(
            status=cmd.OK, t5_uptime_ms=1, applied_revision=1, error_flags=0
        ),
    },
    "GET_INFO": {
        "request": proto.encode_get_info_request(),
        "response": proto.encode_get_info_response(
            status=cmd.OK, hardware_id=1, uptime_ms=1, capability_flags=0, firmware_version="x"
        ),
    },
    "TIME_SYNC": {
        "request": proto.encode_time_sync(now_ms=1, tz_offset_minutes=0),
    },
    "STATE_SYNC_BEGIN": {
        "request": proto.encode_state_sync_begin(revision=1, reason=0),
    },
    "STATE_SYNC_END": {
        "request": proto.encode_state_sync_end(revision=1, snapshot_crc32=0),
    },
    "MODE_SET": {
        "request": proto.encode_mode_set(
            revision=1, mode=SystemMode.IDLE, changed_at_ms=1, reason=0
        ),
    },
    "ATTENTION_SET": {
        "request": proto.encode_attention_set(
            revision=1, attention=AttentionFlag.NONE, confirmation_count=0, short_message="x"
        ),
    },
    "WORK_STATE_SET": {
        "request": proto.encode_work_state_set(
            revision=1,
            work_state=WorkState.STOPPED,
            current_task_title="x",
        ),
    },
    "DASHBOARD_SET": {
        "request": proto.encode_dashboard_set(revision=1, dashboard=DashboardState(revision=1)),
    },
    "NOTICE_SHOW": {
        "request": proto.encode_notice_show(
            revision=1, notice_id=1, severity=1, ttl_ms=1, title="a", body="b"
        ),
    },
    "TASK_LIST_BEGIN": {
        "request": proto.encode_task_list_begin(revision=1, total=1, reason=0),
    },
    "TASK_ITEM": {
        "request": proto.encode_task_item(
            revision=1,
            index=0,
            task_id=1,
            status=0,
            priority=0,
            progress_permille=0,
            requires_confirmation=0,
            title="t",
        ),
    },
    "TASK_LIST_END": {
        "request": proto.encode_task_list_end(revision=1, snapshot_crc32=0),
    },
    "UI_ACTION": {
        "event": proto.encode_ui_action(
            action=cmd.ACTION_CONFIRM, object_type=0, object_id=1, value=0, text="t"
        ),
    },
    "PAGE_EVENT": {
        "event": proto.encode_page_event(page_id=1, action=0, param=0),
    },
    "LED_OVERRIDE": {
        "request": proto.encode_led_override(pattern=1, color_rgb=0, duration_ms=0, priority=0),
    },
    "BACKLIGHT_SET": {
        "request": proto.encode_backlight_set(brightness_pct=50, duration_ms=100),
    },
}


def _expected_width(fields: list[dict]) -> tuple[int, int]:
    """Return (fixed_width, number_of_strings) for the schema fields."""
    fixed = 0
    strings = 0
    for field in fields:
        ftype = field["type"]
        if ftype == "string":
            strings += 1
            continue
        if ftype not in SCALAR_WIDTHS:
            raise AssertionError(f"unknown YAML scalar type: {ftype}")
        fixed += SCALAR_WIDTHS[ftype]
    return fixed, strings


def test_every_yaml_payload_has_matching_encoder() -> None:
    data = yaml.safe_load(CONTRACT.read_text())
    payloads = data["t5_link_v1"]["payloads"]
    missing: list[str] = []
    for name, roles in payloads.items():
        for role in roles:
            if name not in ENCODER_EXAMPLES or role not in ENCODER_EXAMPLES[name]:
                missing.append(f"{name}.{role}")
    assert not missing, f"YAML payloads without encoder examples: {missing}"


def test_encoder_widths_match_yaml_schema() -> None:
    data = yaml.safe_load(CONTRACT.read_text())
    payloads = data["t5_link_v1"]["payloads"]
    for name, roles in payloads.items():
        for role, fields in roles.items():
            example = ENCODER_EXAMPLES[name][role]
            fixed, strings = _expected_width(fields)
            # Each YAML string contributes: 2-byte length prefix + payload bytes.
            actual = len(example)
            assert actual >= fixed + 2 * strings, (
                f"{name}.{role}: encoder produced {actual} bytes, "
                f"YAML schema requires at least fixed={fixed} + strings*(2)={2 * strings}"
            )
            # The minimum-content sanity check: the fixed prefix must match exactly.
            assert actual - _strings_content_bytes(example, fixed, strings) == fixed + 2 * strings, (
                f"{name}.{role}: encoder width does not match YAML layout"
            )


def _strings_content_bytes(payload: bytes, fixed: int, strings: int) -> int:
    """Return total UTF-8 body length across all string fields in the payload."""
    offset = fixed
    total = 0
    for _ in range(strings):
        if offset + 2 > len(payload):
            raise AssertionError("payload truncated at string length prefix")
        length = int.from_bytes(payload[offset : offset + 2], "little")
        offset += 2 + length
        total += length
    if offset != len(payload):
        raise AssertionError(f"trailing bytes after last string: {payload[offset:]!r}")
    return total
