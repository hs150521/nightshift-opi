"""Regenerate contracts/uart/golden_vectors.json from encode helpers.

Run: python tools/regenerate_golden_vectors.py

The vectors here are the canonical wire images for T5-Link v1. They must
match the frozen contract in contracts/uart/commands.yaml exactly. Any change
here MUST be released atomically with T5 firmware.
"""

from __future__ import annotations

import json
from pathlib import Path

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, DashboardState, SystemMode, WorkState
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame


def _wire(frame: proto.Frame) -> tuple[str, list[int]]:
    data = stuff_frame(frame.raw)
    return data.hex(), list(data)


def build_vectors() -> list[dict]:
    vectors: list[dict] = []

    hello_payload = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0x12345678,
        max_payload=1024,
        capabilities=0x0001,
        software_version="nightshift/0.1.0",
    )
    hello = proto.Frame.request(
        sequence=1, command=cmd.HELLO, payload=hello_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(hello)
    vectors.append({
        "name": "hello_request",
        "sequence": 1,
        "command": cmd.HELLO,
        "command_name": "HELLO",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    hb_payload = proto.encode_heartbeat(uptime_ms=5000, state_revision=1)
    hb = proto.Frame.request(
        sequence=2, command=cmd.HEARTBEAT, payload=hb_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(hb)
    vectors.append({
        "name": "heartbeat_request",
        "sequence": 2,
        "command": cmd.HEARTBEAT,
        "command_name": "HEARTBEAT",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    # Heartbeat response: state=RUNNING(1) mode=DAY_WORK(1) revision=1 tokens_in=100 tokens_out=200
    import struct
    hb_resp_payload = struct.pack("<BBIII", 1, 1, 1, 100, 200)
    hb_resp = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_RESPONSE,
        sequence=2,
        command=cmd.HEARTBEAT,
        payload=hb_resp_payload,
    )
    raw_hex, raw_bytes = _wire(hb_resp)
    vectors.append({
        "name": "heartbeat_response",
        "sequence": 2,
        "command": cmd.HEARTBEAT,
        "command_name": "HEARTBEAT",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    mode_payload = proto.encode_mode_set(
        revision=1, mode=SystemMode.NIGHT_EXEC, changed_at_ms=1_700_000_000_000, reason=2
    )
    mode = proto.Frame.request(
        sequence=3, command=cmd.MODE_SET, payload=mode_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(mode)
    vectors.append({
        "name": "mode_set_night_exec",
        "sequence": 3,
        "command": cmd.MODE_SET,
        "command_name": "MODE_SET",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    att_payload = proto.encode_attention_set(
        revision=1,
        attention=AttentionFlag.NEED_CONFIRM,
        confirmation_count=2,
        short_message="check",
    )
    att = proto.Frame.request(
        sequence=4, command=cmd.ATTENTION_SET, payload=att_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(att)
    vectors.append({
        "name": "attention_set_need_confirm",
        "sequence": 4,
        "command": cmd.ATTENTION_SET,
        "command_name": "ATTENTION_SET",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    ws_payload = proto.encode_work_state_set(
        revision=1,
        work_state=WorkState.RUNNING,
        progress_permille=500,
        token_input=100,
        token_output=50,
        elapsed_seconds=60,
        current_task_id=7,
        current_task_title="demo",
    )
    ws = proto.Frame.request(
        sequence=5, command=cmd.WORK_STATE_SET, payload=ws_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(ws)
    vectors.append({
        "name": "work_state_set_running",
        "sequence": 5,
        "command": cmd.WORK_STATE_SET,
        "command_name": "WORK_STATE_SET",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    dash_payload = proto.encode_dashboard_set(
        revision=1,
        dashboard=DashboardState(
            revision=1,
            urgent_auto=1,
            normal_auto=2,
            urgent_confirm=3,
            normal_confirm=4,
            completed_today=5,
            failed_today=6,
        ),
    )
    dash = proto.Frame.request(
        sequence=6, command=cmd.DASHBOARD_SET, payload=dash_payload, flags=cmd.FLAG_ACK_REQ
    )
    raw_hex, raw_bytes = _wire(dash)
    vectors.append({
        "name": "dashboard_set",
        "sequence": 6,
        "command": cmd.DASHBOARD_SET,
        "command_name": "DASHBOARD_SET",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    ui_payload = proto.encode_ui_action(
        action=cmd.ACTION_CONFIRM,
        object_type=1,
        object_id=50,
        value=0,
        text="",
    )
    ui = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT,
        sequence=7,
        command=cmd.UI_ACTION,
        payload=ui_payload,
    )
    raw_hex, raw_bytes = _wire(ui)
    vectors.append({
        "name": "ui_action_confirm",
        "sequence": 7,
        "command": cmd.UI_ACTION,
        "command_name": "UI_ACTION",
        "raw_hex": raw_hex,
        "raw_bytes": raw_bytes,
    })

    return vectors


def main() -> None:
    out_path = Path(__file__).parent.parent / "contracts" / "uart" / "golden_vectors.json"
    vectors = build_vectors()
    payload = {"golden_vectors": vectors}
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(vectors)} vectors to {out_path}")


if __name__ == "__main__":
    main()
