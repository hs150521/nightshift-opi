"""Golden-vector round-trip tests for T5-Link v1 frames.

Every entry in contracts/uart/golden_vectors.json must match the current
encoder output byte-for-byte. Any drift means either the code or the contract
has changed without the other — both must be updated atomically together with
T5 firmware.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, DashboardState, SystemMode, WorkState
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame, unstuff_frame

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "uart" / "golden_vectors.json"


def _wire(frame: proto.Frame) -> bytes:
    return stuff_frame(frame.raw)


@pytest.fixture(scope="module")
def golden() -> dict[str, dict]:
    data = json.loads(CONTRACT.read_text())
    return {v["name"]: v for v in data["golden_vectors"]}


def test_hello_request_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0x12345678,
        max_payload=1024,
        capabilities=0x0001,
        software_version="nightshift/0.1.0",
    )
    frame = proto.Frame.request(1, cmd.HELLO, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["hello_request"]["raw_hex"]


def test_heartbeat_request_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_heartbeat(uptime_ms=5000, state_revision=1)
    frame = proto.Frame.request(2, cmd.HEARTBEAT, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["heartbeat_request"]["raw_hex"]


def test_heartbeat_response_is_exactly_14_bytes(golden: dict[str, dict]) -> None:
    payload = proto.encode_heartbeat_response(
        status=cmd.OK,
        t5_uptime_ms=123_456,
        applied_revision=1,
        error_flags=0,
    )
    assert len(payload) == 14
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_RESPONSE,
        sequence=2,
        command=cmd.HEARTBEAT,
        payload=payload,
    )
    assert _wire(frame).hex() == golden["heartbeat_response"]["raw_hex"]

    parsed = proto.parse_heartbeat_response(payload)
    assert parsed.status == cmd.OK
    assert parsed.t5_uptime_ms == 123_456
    assert parsed.applied_revision == 1
    assert parsed.error_flags == 0


def test_mode_set_reason_is_u8(golden: dict[str, dict]) -> None:
    payload = proto.encode_mode_set(
        revision=1,
        mode=SystemMode.NIGHT_EXEC,
        changed_at_ms=1_700_000_000_000,
        reason=2,
    )
    assert len(payload) == 14
    frame = proto.Frame.request(5, cmd.MODE_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["mode_set_night_exec"]["raw_hex"]


def test_attention_set_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_attention_set(
        revision=1,
        attention=AttentionFlag.NEED_CONFIRM,
        confirmation_count=2,
        short_message="check",
    )
    frame = proto.Frame.request(6, cmd.ATTENTION_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["attention_set_need_confirm"]["raw_hex"]


def test_work_state_set_has_revision_prefix(golden: dict[str, dict]) -> None:
    payload = proto.encode_work_state_set(
        revision=1,
        work_state=WorkState.RUNNING,
        progress_permille=500,
        token_input=100,
        token_output=50,
        elapsed_seconds=60,
        current_task_id=7,
        current_task_title="demo",
    )
    assert struct.unpack("<I", payload[:4])[0] == 1
    frame = proto.Frame.request(7, cmd.WORK_STATE_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["work_state_set_running"]["raw_hex"]


def test_work_state_set_minimum_27_bytes() -> None:
    payload = proto.encode_work_state_set(
        revision=1,
        work_state=WorkState.STOPPED,
    )
    # <IBHHIIII> = 4+1+2+2+4+4+4+4 = 25 bytes fixed + 2 byte string length = 27 minimum
    assert len(payload) >= 27


def test_dashboard_set_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_dashboard_set(
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
    frame = proto.Frame.request(8, cmd.DASHBOARD_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["dashboard_set"]["raw_hex"]


def test_ui_action_confirm_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_ui_action(
        action=cmd.ACTION_CONFIRM,
        object_type=cmd.OBJ_TASK,
        object_id=50,
        value=0,
        text="",
    )
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        sequence=13,
        command=cmd.UI_ACTION,
        payload=payload,
    )
    assert _wire(frame).hex() == golden["ui_action_confirm"]["raw_hex"]


def test_ui_action_request_resync_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_ui_action(
        action=cmd.ACTION_REQUEST_RESYNC,
        object_type=cmd.OBJ_NONE,
        object_id=0,
        value=0,
        text="",
    )
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        sequence=14,
        command=cmd.UI_ACTION,
        payload=payload,
    )
    assert _wire(frame).hex() == golden["ui_action_request_resync"]["raw_hex"]


def test_notice_show_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_notice_show(
        revision=1, notice_id=42, severity=1, flags=0, expires_at_ms=5000, title="hi", body="body"
    )
    frame = proto.Frame.request(9, cmd.NOTICE_SHOW, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["notice_show"]["raw_hex"]


def test_task_list_frames_match_golden(golden: dict[str, dict]) -> None:
    begin = proto.encode_task_list_begin(revision=1, list_type=0, item_count=2)
    frame = proto.Frame.request(10, cmd.TASK_LIST_BEGIN, begin, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["task_list_begin"]["raw_hex"]

    item = proto.encode_task_item(
        revision=1,
        task_id=101,
        quadrant=1,
        task_state=cmd.WORK_RUNNING,
        flags=0,
        title="first",
        source="user",
    )
    frame = proto.Frame.request(11, cmd.TASK_ITEM, item, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["task_item"]["raw_hex"]

    end = proto.encode_task_list_end(revision=1, list_crc32=0xDEADBEEF)
    frame = proto.Frame.request(12, cmd.TASK_LIST_END, end, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["task_list_end"]["raw_hex"]


def test_page_event_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_page_event(page_id=3, event=1, object_id=0)
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT,
        sequence=15,
        command=cmd.PAGE_EVENT,
        payload=payload,
    )
    assert _wire(frame).hex() == golden["page_event"]["raw_hex"]


def test_get_info_frames_match_golden(golden: dict[str, dict]) -> None:
    req = proto.encode_get_info_request()
    frame = proto.Frame.request(16, cmd.GET_INFO, req, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["get_info_request"]["raw_hex"]

    resp = proto.encode_get_info_response(
        status=cmd.OK,
        protocol_major=1,
        protocol_minor=0,
        max_payload=1024,
        capabilities=cmd.CAP_LCD | cmd.CAP_TOUCH,
        display_width=960,
        display_height=540,
        color_bits=16,
        max_tasks=20,
        firmware_version="t5/0.1.0",
        board_name="T5-E-Paper",
    )
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_RESPONSE,
        sequence=16,
        command=cmd.GET_INFO,
        payload=resp,
    )
    assert _wire(frame).hex() == golden["get_info_response"]["raw_hex"]


def test_time_sync_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_time_sync(now_ms=1_700_000_000_000, tz_offset_minutes=480)
    frame = proto.Frame.request(17, cmd.TIME_SYNC, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["time_sync"]["raw_hex"]


def test_led_and_backlight_match_golden(golden: dict[str, dict]) -> None:
    led = proto.encode_led_override(active=1, mode=2, period_ms=1000)
    frame = proto.Frame.request(18, cmd.LED_OVERRIDE, led, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["led_override"]["raw_hex"]

    backlight = proto.encode_backlight_set(percent=75)
    frame = proto.Frame.request(19, cmd.BACKLIGHT_SET, backlight, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["backlight_set"]["raw_hex"]


def test_state_sync_frames_match_golden(golden: dict[str, dict]) -> None:
    begin = proto.encode_state_sync_begin(revision=1, reason=0)
    frame = proto.Frame.request(3, cmd.STATE_SYNC_BEGIN, begin, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["state_sync_begin"]["raw_hex"]

    end = proto.encode_state_sync_end(revision=1, snapshot_crc32=0)
    frame = proto.Frame.request(4, cmd.STATE_SYNC_END, end, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["state_sync_end"]["raw_hex"]


def test_roundtrip_all_golden_frames(golden: dict[str, dict]) -> None:
    for name, entry in golden.items():
        raw = bytes.fromhex(entry["raw_hex"])
        decoded = unstuff_frame(raw)
        parsed = proto.Frame.parse(decoded)
        rebuilt = stuff_frame(parsed.raw)
        assert rebuilt.hex() == entry["raw_hex"], f"roundtrip failed for {name}"
