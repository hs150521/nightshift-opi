"""Frozen T5-Link v1 schema and canonical wire-vector tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, DashboardState, SystemMode, WorkState
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame, unstuff_frame

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "uart" / "golden_vectors.json"


@pytest.fixture(scope="module")
def golden() -> dict[str, dict]:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["golden_vectors"]}


def _wire(frame: proto.Frame) -> bytes:
    return stuff_frame(frame.raw)


def _assert_golden(golden: dict[str, dict], name: str, frame: proto.Frame) -> None:
    assert _wire(frame).hex() == golden[name]["raw_hex"]


def test_hello_request_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_hello(1, 1, 0, 0x12345678, 1024, 0x0003, "nightshift/1.0.0")
    _assert_golden(golden, "hello_request", proto.Frame.request(1, cmd.HELLO, payload))


def test_heartbeat_response_is_frozen_hiii(golden: dict[str, dict]) -> None:
    request = proto.encode_heartbeat(5000, 7)
    _assert_golden(
        golden,
        "heartbeat_request",
        proto.Frame.request(2, cmd.HEARTBEAT, request),
    )

    payload = struct.pack("<HIII", cmd.OK, 6000, 7, 0)
    assert len(payload) == 14
    parsed = proto.parse_heartbeat_response(payload)
    assert parsed == {
        "status": cmd.OK,
        "t5_uptime_ms": 6000,
        "applied_revision": 7,
        "error_flags": 0,
    }
    _assert_golden(
        golden,
        "heartbeat_response",
        proto.Frame(proto.VERSION, cmd.FLAG_RESPONSE, 2, cmd.HEARTBEAT, payload),
    )
    with pytest.raises(proto.ProtocolError):
        proto.parse_heartbeat_response(payload + b"\x00")


def test_mode_reason_is_u8_and_work_has_revision(golden: dict[str, dict]) -> None:
    mode = proto.encode_mode_set(7, SystemMode.NIGHT_EXEC, 1_700_000_000_000, reason=2)
    assert len(mode) == 14
    assert struct.unpack("<IBBQ", mode) == (7, 2, 2, 1_700_000_000_000)
    _assert_golden(
        golden,
        "mode_set_night_exec",
        proto.Frame.request(6, cmd.MODE_SET, mode),
    )

    work = proto.encode_work_state_set(
        7, WorkState.RUNNING, 500, 100, 50, 60, 42, "demo"
    )
    assert struct.unpack("<IBHHIIII", work[:25]) == (7, 2, 500, 0, 100, 50, 60, 42)
    _assert_golden(
        golden,
        "work_state_set_running",
        proto.Frame.request(8, cmd.WORK_STATE_SET, work),
    )


def test_state_payload_encoders_match_golden(golden: dict[str, dict]) -> None:
    attention = proto.encode_attention_set(7, AttentionFlag.NEED_CONFIRM, 2, "check")
    _assert_golden(
        golden,
        "attention_set_need_confirm",
        proto.Frame.request(7, cmd.ATTENTION_SET, attention),
    )
    dashboard = proto.encode_dashboard_set(
        7,
        DashboardState(
            revision=7,
            urgent_auto=1,
            normal_auto=2,
            urgent_confirm=3,
            normal_confirm=4,
            completed_today=5,
            failed_today=6,
        ),
    )
    _assert_golden(
        golden,
        "dashboard_set",
        proto.Frame.request(9, cmd.DASHBOARD_SET, dashboard),
    )
    notice = proto.encode_notice_show(
        7, 44, 1, 1, 1_700_000_060_000,
        "Warning", "Pressure input unavailable",
    )
    _assert_golden(
        golden,
        "notice_show",
        proto.Frame.request(10, cmd.NOTICE_SHOW, notice),
    )


def test_formal_control_and_event_payloads(golden: dict[str, dict]) -> None:
    ui = proto.encode_ui_action(cmd.ACTION_CONFIRM, cmd.OBJECT_TASK, 42, 0, "")
    assert proto.parse_ui_action(ui) == (cmd.ACTION_CONFIRM, cmd.OBJECT_TASK, 42, 0, "")
    _assert_golden(
        golden,
        "ui_action_confirm",
        proto.Frame(
            proto.VERSION,
            cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
            15,
            cmd.UI_ACTION,
            ui,
        ),
    )
    with pytest.raises(proto.ProtocolError):
        proto.parse_ui_action(ui[:10])

    _assert_golden(
        golden,
        "page_event",
        proto.Frame(
            proto.VERSION,
            cmd.FLAG_EVENT,
            16,
            cmd.PAGE_EVENT,
            proto.encode_page_event(1, 3, 4),
        ),
    )
    _assert_golden(
        golden,
        "led_override",
        proto.Frame.request(17, cmd.LED_OVERRIDE, proto.encode_led_override(1, 1, 500)),
    )
    _assert_golden(
        golden,
        "backlight_set",
        proto.Frame.request(18, cmd.BACKLIGHT_SET, proto.encode_backlight_set(80)),
    )


def test_all_21_vectors_roundtrip_and_metadata_match(golden: dict[str, dict]) -> None:
    assert len(golden) == 21
    for name, entry in golden.items():
        wire = bytes.fromhex(entry["raw_hex"])
        parsed = proto.Frame.parse(unstuff_frame(wire))
        assert parsed.sequence == entry["sequence"], name
        assert parsed.command == entry["command"], name
        assert parsed.flags == entry["flags"], name
        assert parsed.payload.hex() == entry["payload_hex"], name
        assert stuff_frame(parsed.raw) == wire, name
