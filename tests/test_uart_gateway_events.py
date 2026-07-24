"""Inbound T5 event ACK and duplicate replay behavior."""

from __future__ import annotations

import pytest

from nightshift.domain import commands as cmd
from nightshift.domain.events import UiAction
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import unstuff_frame
from nightshift.hardware.uart.gateway import UartConfig, UartGateway


class FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)


@pytest.mark.asyncio
async def test_ui_action_duplicate_is_acked_without_repeating_side_effect() -> None:
    events: list[object] = []
    gateway = UartGateway(UartConfig("loop://"), events.append)
    writer = FakeWriter()
    gateway._writer = writer  # type: ignore[assignment]
    event = proto.Frame(
        proto.VERSION,
        cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        55,
        cmd.UI_ACTION,
        proto.encode_ui_action(
            cmd.ACTION_RETRY, cmd.OBJECT_TASK, 42, 0, ""
        ),
    )

    await gateway._dispatch(event)
    await gateway._dispatch(event)

    assert events == [
        UiAction(
            action=cmd.ACTION_RETRY,
            object_type=cmd.OBJECT_TASK,
            object_id=42,
            value=0,
            text="",
        )
    ]
    assert len(writer.writes) == 2
    assert writer.writes[0] == writer.writes[1]
    ack = proto.Frame.parse(unstuff_frame(writer.writes[0]))
    assert (ack.flags, ack.sequence, ack.command) == (
        cmd.FLAG_RESPONSE, 55, cmd.UI_ACTION
    )
    assert int.from_bytes(ack.payload, "little") == cmd.OK


@pytest.mark.asyncio
async def test_malformed_ui_action_gets_invalid_length_ack() -> None:
    gateway = UartGateway(UartConfig("loop://"))
    writer = FakeWriter()
    gateway._writer = writer  # type: ignore[assignment]
    event = proto.Frame(
        proto.VERSION,
        cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        56,
        cmd.UI_ACTION,
        b"\x00" * 10,
    )

    await gateway._dispatch(event)

    ack = proto.Frame.parse(unstuff_frame(writer.writes[0]))
    assert int.from_bytes(ack.payload, "little") == cmd.INVALID_LENGTH


@pytest.mark.asyncio
async def test_ui_action_handler_failure_is_cached_before_retry() -> None:
    calls = 0

    def failing_handler(_event: object) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("backend rejected event")

    gateway = UartGateway(UartConfig("loop://"), failing_handler)
    writer = FakeWriter()
    gateway._writer = writer  # type: ignore[assignment]
    event = proto.Frame(
        proto.VERSION,
        cmd.FLAG_EVENT | cmd.FLAG_ACK_REQ,
        57,
        cmd.UI_ACTION,
        proto.encode_ui_action(
            cmd.ACTION_CONFIRM, cmd.OBJECT_TASK, 42, 0, ""
        ),
    )

    await gateway._dispatch(event)
    await gateway._dispatch(event)

    assert calls == 1
    assert len(writer.writes) == 2
    assert writer.writes[0] == writer.writes[1]
    ack = proto.Frame.parse(unstuff_frame(writer.writes[0]))
    assert int.from_bytes(ack.payload, "little") == cmd.INTERNAL_ERROR
