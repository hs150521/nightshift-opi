"""Tests for strict HELLO validation in the UART gateway.

Malformed HELLO must return non-OK and cause no state or session transition.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nightshift.domain import commands as cmd
from nightshift.domain.events import PanelConnectivityChanged
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame
from nightshift.hardware.uart.gateway import UartConfig, UartGateway


@pytest.fixture
def gateway() -> UartGateway:
    events: list = []
    hello_calls: list = []

    gw = UartGateway(
        config=UartConfig(device="/dev/null"),
        on_event=lambda e: events.append(e),
        on_panel_hello=lambda: hello_calls.append(1),
    )
    gw._events = events
    gw._hello_calls = hello_calls
    gw._writer = MagicMock()
    gw._writer.write = MagicMock()
    return gw


def _make_hello_frame(payload: bytes, seq: int = 1) -> proto.Frame:
    return proto.Frame(
        version=proto.VERSION,
        flags=cmd.FLAG_ACK_REQ,
        sequence=seq,
        command=cmd.HELLO,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_valid_hello_triggers_session(gateway: UartGateway) -> None:
    payload = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0xAABBCCDD,
        max_payload=1024,
        capabilities=0x0003,
        software_version="t5/1.0.0",
    )
    frame = _make_hello_frame(payload)
    await gateway._dispatch(frame)

    assert gateway._panel_online is True
    assert gateway._peer_boot_id == 0xAABBCCDD
    assert len(gateway._hello_calls) == 1
    assert any(
        isinstance(e, PanelConnectivityChanged) and e.online
        for e in gateway._events
    )

    # Verify OK was sent
    written = gateway._writer.write.call_args_list
    assert len(written) >= 1
    ack_data = written[0][0][0]
    raw = proto.Frame.parse(
        __import__("nightshift.hardware.uart.codec", fromlist=["unstuff_frame"]).unstuff_frame(ack_data)
    )
    assert raw.command == cmd.HELLO
    assert raw.flags == cmd.FLAG_RESPONSE
    status = int.from_bytes(raw.payload[:2], "little")
    assert status == cmd.OK


@pytest.mark.asyncio
async def test_malformed_hello_too_short(gateway: UartGateway) -> None:
    frame = _make_hello_frame(b"\x01\x01")  # Too short
    await gateway._dispatch(frame)

    assert gateway._panel_online is False
    assert gateway._peer_boot_id is None
    assert len(gateway._hello_calls) == 0
    assert len(gateway._events) == 0

    # Verify INVALID_ARGUMENT was sent
    written = gateway._writer.write.call_args_list
    assert len(written) >= 1


@pytest.mark.asyncio
async def test_malformed_hello_empty_payload(gateway: UartGateway) -> None:
    frame = _make_hello_frame(b"")
    await gateway._dispatch(frame)

    assert gateway._panel_online is False
    assert gateway._peer_boot_id is None
    assert len(gateway._hello_calls) == 0


@pytest.mark.asyncio
async def test_malformed_hello_does_not_change_existing_session(
    gateway: UartGateway,
) -> None:
    # First: valid hello
    valid_payload = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0x11111111,
        max_payload=1024,
        capabilities=0,
        software_version="t5/1.0",
    )
    await gateway._dispatch(_make_hello_frame(valid_payload, seq=1))
    assert gateway._peer_boot_id == 0x11111111
    assert gateway._panel_online is True

    # Then: malformed hello
    await gateway._dispatch(_make_hello_frame(b"\xFF", seq=2))

    # Session unchanged
    assert gateway._peer_boot_id == 0x11111111
    assert gateway._panel_online is True


@pytest.mark.asyncio
async def test_new_boot_id_updates_session(gateway: UartGateway) -> None:
    payload1 = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0xAAAAAAAA,
        max_payload=1024,
        capabilities=0,
        software_version="t5/1.0",
    )
    await gateway._dispatch(_make_hello_frame(payload1, seq=1))
    assert gateway._peer_boot_id == 0xAAAAAAAA

    payload2 = proto.encode_hello(
        peer_role=0x01,
        protocol_major=1,
        protocol_minor=0,
        boot_id=0xBBBBBBBB,
        max_payload=1024,
        capabilities=0,
        software_version="t5/1.0",
    )
    await gateway._dispatch(_make_hello_frame(payload2, seq=2))
    assert gateway._peer_boot_id == 0xBBBBBBBB
    assert len(gateway._hello_calls) == 2
