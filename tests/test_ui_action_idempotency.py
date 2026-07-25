"""Tests for gateway UI action handling with session-aware idempotency."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from nightshift.domain import commands as cmd
from nightshift.domain.events import PanelConnectivityChanged, UiAction
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.gateway import UartConfig, UartGateway


@pytest.fixture
def gateway() -> UartGateway:
    events: list = []

    async def action_handler(event: UiAction) -> tuple[int, bytes]:
        if event.action == cmd.ACTION_PAUSE_EXECUTION:
            return cmd.OK, b""
        elif event.action == cmd.ACTION_CONFIRM:
            return cmd.NOT_READY, b""
        return cmd.OK, b""

    gw = UartGateway(
        config=UartConfig(device="/dev/null"),
        on_event=lambda e: events.append(e),
        ui_action_handler=action_handler,
    )
    gw._events = events
    gw._writer = MagicMock()
    gw._writer.write = MagicMock()
    gw._connected = True
    return gw


async def _setup_session(gw: UartGateway, boot_id: int = 0xAABBCCDD) -> None:
    """Send a valid HELLO to establish session."""
    payload = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=boot_id,
        max_payload=1024,
        capabilities=0,
        software_version="t5/test",
    )
    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_ACK_REQ,
        sequence=1,
        command=cmd.HELLO,
        payload=payload,
    )
    await gw._dispatch(frame)


def _ui_action_frame(action: int, seq: int, object_id: int = 0) -> proto.Frame:
    payload = proto.encode_ui_action(
        action=action,
        object_type=cmd.OBJ_TASK if action in (cmd.ACTION_CONFIRM, cmd.ACTION_REJECT) else cmd.OBJ_NONE,
        object_id=object_id,
        value=0,
        text="",
    )
    return proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        sequence=seq,
        command=cmd.UI_ACTION,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_ui_action_without_session_returns_not_ready(gateway: UartGateway) -> None:
    frame = _ui_action_frame(cmd.ACTION_CONFIRM, seq=10)
    await gateway._dispatch(frame)

    written = gateway._writer.write.call_args_list
    assert len(written) >= 1
    # Parse the response
    from nightshift.hardware.uart.codec import unstuff_frame

    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.NOT_READY


@pytest.mark.asyncio
async def test_ui_action_executes_once(gateway: UartGateway) -> None:
    await _setup_session(gateway)

    frame = _ui_action_frame(cmd.ACTION_PAUSE_EXECUTION, seq=10)
    gateway._writer.write.reset_mock()
    await gateway._dispatch(frame)

    from nightshift.hardware.uart.codec import unstuff_frame

    written = gateway._writer.write.call_args_list
    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.OK


@pytest.mark.asyncio
async def test_duplicate_action_replays_without_side_effect(gateway: UartGateway) -> None:
    await _setup_session(gateway)

    frame = _ui_action_frame(cmd.ACTION_PAUSE_EXECUTION, seq=10)
    await gateway._dispatch(frame)

    # Count events emitted
    event_count = len([e for e in gateway._events if isinstance(e, UiAction)])

    # Send same frame again
    await gateway._dispatch(frame)

    # Should not have emitted another UiAction event
    new_event_count = len([e for e in gateway._events if isinstance(e, UiAction)])
    assert new_event_count == event_count


@pytest.mark.asyncio
async def test_same_seq_different_payload_conflicts(gateway: UartGateway) -> None:
    await _setup_session(gateway)

    frame1 = _ui_action_frame(cmd.ACTION_PAUSE_EXECUTION, seq=10)
    await gateway._dispatch(frame1)

    # Same seq but different action
    frame2 = _ui_action_frame(cmd.ACTION_RESUME_EXECUTION, seq=10)
    gateway._writer.write.reset_mock()
    await gateway._dispatch(frame2)

    from nightshift.hardware.uart.codec import unstuff_frame

    written = gateway._writer.write.call_args_list
    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.STATE_CONFLICT


@pytest.mark.asyncio
async def test_new_boot_id_resets_dedup(gateway: UartGateway) -> None:
    await _setup_session(gateway, boot_id=0x11111111)

    frame = _ui_action_frame(cmd.ACTION_PAUSE_EXECUTION, seq=5)
    await gateway._dispatch(frame)

    # New T5 reboot with same sequence
    await _setup_session(gateway, boot_id=0x22222222)
    gateway._writer.write.reset_mock()
    await gateway._dispatch(frame)  # Same seq=5

    from nightshift.hardware.uart.codec import unstuff_frame

    written = gateway._writer.write.call_args_list
    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.OK  # Executes fresh after new session


@pytest.mark.asyncio
async def test_service_failure_never_returns_ok(gateway: UartGateway) -> None:
    await _setup_session(gateway)

    # ACTION_CONFIRM returns NOT_READY from our handler
    frame = _ui_action_frame(cmd.ACTION_CONFIRM, seq=20, object_id=99)
    gateway._writer.write.reset_mock()
    await gateway._dispatch(frame)

    from nightshift.hardware.uart.codec import unstuff_frame

    written = gateway._writer.write.call_args_list
    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.NOT_READY


@pytest.mark.asyncio
async def test_malformed_ui_action_returns_invalid_length(gateway: UartGateway) -> None:
    await _setup_session(gateway)

    frame = proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        sequence=30,
        command=cmd.UI_ACTION,
        payload=b"\x01\x02",  # Too short
    )
    gateway._writer.write.reset_mock()
    await gateway._dispatch(frame)

    from nightshift.hardware.uart.codec import unstuff_frame

    written = gateway._writer.write.call_args_list
    ack_raw = unstuff_frame(written[-1][0][0])
    ack = proto.Frame.parse(ack_raw)
    status = int.from_bytes(ack.payload[:2], "little")
    assert status == cmd.INVALID_LENGTH
