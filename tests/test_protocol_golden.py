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
    payload = struct.pack("<BBIII", 1, 1, 1, 100, 200)
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
    assert parsed == {
        "state": 1,
        "mode": 1,
        "revision": 1,
        "tokens_in": 100,
        "tokens_out": 200,
    }


def test_mode_set_reason_is_u8(golden: dict[str, dict]) -> None:
    payload = proto.encode_mode_set(
        revision=1,
        mode=SystemMode.NIGHT_EXEC,
        changed_at_ms=1_700_000_000_000,
        reason=2,
    )
    # revision(u32) + mode(u8) + reason(u8) + changed_at_ms(u64) = 14 bytes
    assert len(payload) == 14
    frame = proto.Frame.request(3, cmd.MODE_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["mode_set_night_exec"]["raw_hex"]


def test_attention_set_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_attention_set(
        revision=1,
        attention=AttentionFlag.NEED_CONFIRM,
        confirmation_count=2,
        short_message="check",
    )
    frame = proto.Frame.request(4, cmd.ATTENTION_SET, payload, cmd.FLAG_ACK_REQ)
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
    # First 4 bytes must be revision u32
    assert struct.unpack("<I", payload[:4])[0] == 1
    frame = proto.Frame.request(5, cmd.WORK_STATE_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["work_state_set_running"]["raw_hex"]


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
    frame = proto.Frame.request(6, cmd.DASHBOARD_SET, payload, cmd.FLAG_ACK_REQ)
    assert _wire(frame).hex() == golden["dashboard_set"]["raw_hex"]


def test_ui_action_confirm_matches_golden(golden: dict[str, dict]) -> None:
    payload = proto.encode_ui_action(
        action=cmd.ACTION_CONFIRM,
        object_type=1,
        object_id=50,
        value=0,
        text="",
    )
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT,
        sequence=7,
        command=cmd.UI_ACTION,
        payload=payload,
    )
    assert _wire(frame).hex() == golden["ui_action_confirm"]["raw_hex"]


def test_roundtrip_all_golden_frames(golden: dict[str, dict]) -> None:
    for name, entry in golden.items():
        raw = bytes.fromhex(entry["raw_hex"])
        # Every wire image must survive COBS unstuff + frame parse + re-stuff.
        decoded = unstuff_frame(raw)
        parsed = proto.Frame.parse(decoded)
        rebuilt = stuff_frame(parsed.raw)
        assert rebuilt.hex() == entry["raw_hex"], f"roundtrip failed for {name}"
