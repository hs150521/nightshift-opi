"""Regenerate contracts/uart/golden_vectors.json from encode helpers.

Run: python tools/regenerate_golden_vectors.py

The vectors here are the canonical wire images for T5-Link v1. They are
built exclusively from `nightshift.hardware.uart.protocol` encoders, so
they can never encode a layout that disagrees with the source of truth.
Any change here MUST be released atomically with T5 firmware.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, DashboardState, SystemMode, WorkState
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame


@dataclass
class VectorSpec:
    name: str
    sequence: int
    command: int
    command_name: str
    flags: int
    payload_factory: Callable[[], bytes]


def _wire(frame: proto.Frame) -> tuple[str, list[int]]:
    data = stuff_frame(frame.raw)
    return data.hex(), list(data)


def _dashboard_example() -> DashboardState:
    return DashboardState(
        revision=1,
        urgent_auto=1,
        normal_auto=2,
        urgent_confirm=3,
        normal_confirm=4,
        completed_today=5,
        failed_today=6,
    )


SPECS: list[VectorSpec] = [
    VectorSpec(
        name="hello_request",
        sequence=1,
        command=cmd.HELLO,
        command_name="HELLO",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_hello(
            peer_role=0x01,
            protocol_major=1,
            protocol_minor=0,
            boot_id=0x12345678,
            max_payload=1024,
            capabilities=0x0001,
            software_version="nightshift/0.1.0",
        ),
    ),
    VectorSpec(
        name="heartbeat_request",
        sequence=2,
        command=cmd.HEARTBEAT,
        command_name="HEARTBEAT",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_heartbeat(uptime_ms=5000, state_revision=1),
    ),
    VectorSpec(
        name="heartbeat_response",
        sequence=2,
        command=cmd.HEARTBEAT,
        command_name="HEARTBEAT",
        flags=cmd.FLAG_RESPONSE,
        payload_factory=lambda: proto.encode_heartbeat_response(
            status=cmd.OK,
            t5_uptime_ms=123_456,
            applied_revision=1,
            error_flags=0,
        ),
    ),
    VectorSpec(
        name="state_sync_begin",
        sequence=3,
        command=cmd.STATE_SYNC_BEGIN,
        command_name="STATE_SYNC_BEGIN",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_state_sync_begin(revision=1, reason=0),
    ),
    VectorSpec(
        name="state_sync_end",
        sequence=4,
        command=cmd.STATE_SYNC_END,
        command_name="STATE_SYNC_END",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_state_sync_end(revision=1, snapshot_crc32=0),
    ),
    VectorSpec(
        name="mode_set_night_exec",
        sequence=5,
        command=cmd.MODE_SET,
        command_name="MODE_SET",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_mode_set(
            revision=1,
            mode=SystemMode.NIGHT_EXEC,
            changed_at_ms=1_700_000_000_000,
            reason=2,
        ),
    ),
    VectorSpec(
        name="attention_set_need_confirm",
        sequence=6,
        command=cmd.ATTENTION_SET,
        command_name="ATTENTION_SET",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_attention_set(
            revision=1,
            attention=AttentionFlag.NEED_CONFIRM,
            confirmation_count=2,
            short_message="check",
        ),
    ),
    VectorSpec(
        name="work_state_set_running",
        sequence=7,
        command=cmd.WORK_STATE_SET,
        command_name="WORK_STATE_SET",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_work_state_set(
            revision=1,
            work_state=WorkState.RUNNING,
            progress_permille=500,
            token_input=100,
            token_output=50,
            elapsed_seconds=60,
            current_task_id=7,
            current_task_title="demo",
        ),
    ),
    VectorSpec(
        name="dashboard_set",
        sequence=8,
        command=cmd.DASHBOARD_SET,
        command_name="DASHBOARD_SET",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_dashboard_set(
            revision=1, dashboard=_dashboard_example()
        ),
    ),
    VectorSpec(
        name="notice_show",
        sequence=9,
        command=cmd.NOTICE_SHOW,
        command_name="NOTICE_SHOW",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_notice_show(
            revision=1,
            notice_id=42,
            severity=1,
            ttl_ms=5000,
            title="hi",
            body="body",
        ),
    ),
    VectorSpec(
        name="task_list_begin",
        sequence=10,
        command=cmd.TASK_LIST_BEGIN,
        command_name="TASK_LIST_BEGIN",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_task_list_begin(revision=1, total=2, reason=0),
    ),
    VectorSpec(
        name="task_item",
        sequence=11,
        command=cmd.TASK_ITEM,
        command_name="TASK_ITEM",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_task_item(
            revision=1,
            index=0,
            task_id=101,
            status=cmd.WORK_RUNNING,
            priority=1,
            progress_permille=250,
            requires_confirmation=0,
            title="first",
        ),
    ),
    VectorSpec(
        name="task_list_end",
        sequence=12,
        command=cmd.TASK_LIST_END,
        command_name="TASK_LIST_END",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_task_list_end(revision=1, snapshot_crc32=0xDEADBEEF),
    ),
    VectorSpec(
        name="ui_action_confirm",
        sequence=13,
        command=cmd.UI_ACTION,
        command_name="UI_ACTION",
        flags=cmd.FLAG_EVENT,
        payload_factory=lambda: proto.encode_ui_action(
            action=cmd.ACTION_CONFIRM,
            object_type=1,
            object_id=50,
            value=0,
            text="",
        ),
    ),
    VectorSpec(
        name="ui_action_request_resync",
        sequence=14,
        command=cmd.UI_ACTION,
        command_name="UI_ACTION",
        flags=cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_ui_action(
            action=cmd.ACTION_REQUEST_RESYNC,
            object_type=0,
            object_id=0,
            value=0,
            text="",
        ),
    ),
    VectorSpec(
        name="page_event",
        sequence=15,
        command=cmd.PAGE_EVENT,
        command_name="PAGE_EVENT",
        flags=cmd.FLAG_EVENT,
        payload_factory=lambda: proto.encode_page_event(page_id=3, action=1, param=0),
    ),
    VectorSpec(
        name="get_info_request",
        sequence=16,
        command=cmd.GET_INFO,
        command_name="GET_INFO",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_get_info_request(),
    ),
    VectorSpec(
        name="get_info_response",
        sequence=16,
        command=cmd.GET_INFO,
        command_name="GET_INFO",
        flags=cmd.FLAG_RESPONSE,
        payload_factory=lambda: proto.encode_get_info_response(
            status=cmd.OK,
            hardware_id=0xAB01CD02,
            uptime_ms=99_000,
            capability_flags=cmd.CAP_LCD | cmd.CAP_TOUCH,
            firmware_version="t5/0.1.0",
        ),
    ),
    VectorSpec(
        name="time_sync",
        sequence=17,
        command=cmd.TIME_SYNC,
        command_name="TIME_SYNC",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_time_sync(
            now_ms=1_700_000_000_000, tz_offset_minutes=480
        ),
    ),
    VectorSpec(
        name="led_override",
        sequence=18,
        command=cmd.LED_OVERRIDE,
        command_name="LED_OVERRIDE",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_led_override(
            pattern=2, color_rgb=0x00FF00, duration_ms=1000, priority=1
        ),
    ),
    VectorSpec(
        name="backlight_set",
        sequence=19,
        command=cmd.BACKLIGHT_SET,
        command_name="BACKLIGHT_SET",
        flags=cmd.FLAG_ACK_REQ,
        payload_factory=lambda: proto.encode_backlight_set(
            brightness_pct=75, duration_ms=500
        ),
    ),
]


def build_vectors() -> list[dict]:
    vectors: list[dict] = []
    for spec in SPECS:
        payload = spec.payload_factory()
        frame = proto.Frame(
            version=proto.VERSION,
            flags=spec.flags,
            sequence=spec.sequence,
            command=spec.command,
            payload=payload,
        )
        raw_hex, raw_bytes = _wire(frame)
        vectors.append(
            {
                "name": spec.name,
                "sequence": spec.sequence,
                "command": spec.command,
                "command_name": spec.command_name,
                "flags": spec.flags,
                "payload_hex": payload.hex(),
                "payload_length": len(payload),
                "raw_hex": raw_hex,
                "raw_bytes": raw_bytes,
            }
        )
    return vectors


def main() -> None:
    out_path = Path(__file__).parent.parent / "contracts" / "uart" / "golden_vectors.json"
    vectors = build_vectors()
    payload = {"golden_vectors": vectors}
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(vectors)} vectors to {out_path}")


if __name__ == "__main__":
    main()
