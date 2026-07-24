"""Asynchronous UART gateway to the T5 panel."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nightshift.domain import commands as cmd
from nightshift.domain.events import HeartbeatReceived, PanelConnectivityChanged, UiAction
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame, unstuff_frame


@dataclass(frozen=True)
class UartConfig:
    device: str
    baudrate: int = 460800
    heartbeat_seconds: float = 2.0
    command_timeout_ms: float = 200.0
    max_retries: int = 3


class UartGateway:
    """Manages the T5 UART connection, framing and command lifecycle."""

    def __init__(
        self,
        config: UartConfig,
        on_event: Callable[[Any], None] | None = None,
        on_panel_hello: Callable[[], Any] | None = None,
    ) -> None:
        self._config = config
        self._on_event = on_event
        self._on_panel_hello = on_panel_hello
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence = 0
        self._boot_id = int(time.monotonic() * 1000) & 0xFFFFFFFF
        self._pending: dict[int, asyncio.Future[proto.Frame]] = {}
        self._event_status: dict[tuple[int, int], int] = {}
        self._event_order: deque[tuple[int, int]] = deque()
        self._last_applied_revision = 0
        self._panel_online = False
        self._read_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._connect()
        self._read_task = asyncio.create_task(self._read_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        await self._handshake()

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._read_task:
            self._read_task.cancel()
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._panel_online = False

    async def _connect(self) -> None:
        import serial_asyncio

        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._config.device,
            baudrate=self._config.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            rtscts=False,
            dsrdtr=False,
        )

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence % 65535) + 1
        return self._sequence

    async def send(
        self,
        command: int,
        payload: bytes = b"",
        flags: int = cmd.FLAG_ACK_REQ,
        timeout_ms: float | None = None,
    ) -> proto.Frame:
        if self._writer is None:
            raise RuntimeError("UART not connected")

        seq = self._next_sequence()
        frame = proto.Frame.request(seq, command, payload, flags)
        data = stuff_frame(frame.raw)
        timeout = (timeout_ms or self._config.command_timeout_ms) / 1000.0
        last_error: Exception | None = None

        for _attempt in range(self._config.max_retries + 1):
            fut: asyncio.Future[proto.Frame] = asyncio.get_running_loop().create_future()
            self._pending[seq] = fut
            try:
                self._writer.write(data)
                await asyncio.wait_for(fut, timeout=timeout)
                return fut.result()
            except TimeoutError as exc:
                last_error = exc
            finally:
                self._pending.pop(seq, None)

        raise TimeoutError(
            f"command {command:04x} seq {seq} timed out after {self._config.max_retries} retries"
        ) from last_error

    async def send_no_wait(self, command: int, payload: bytes = b"", flags: int = 0) -> None:
        if self._writer is None:
            return
        seq = self._next_sequence()
        frame = proto.Frame.request(seq, command, payload, flags)
        self._writer.write(stuff_frame(frame.raw))

    async def _read_loop(self) -> None:
        buffer = bytearray()
        while True:
            try:
                if self._reader is None:
                    await asyncio.sleep(0.5)
                    continue
                chunk = await self._reader.read(256)
                if not chunk:
                    await asyncio.sleep(0.1)
                    continue
                buffer.extend(chunk)
                while b"\x00" in buffer:
                    delim = buffer.index(b"\x00")
                    frame_bytes = bytes(buffer[: delim + 1])
                    buffer = buffer[delim + 1 :]
                    try:
                        raw = unstuff_frame(frame_bytes)
                        frame = proto.Frame.parse(raw)
                        await self._dispatch(frame)
                    except Exception:
                        # Bad frames are silently dropped per protocol spec.
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)

    async def _dispatch(self, frame: proto.Frame) -> None:
        if frame.flags & cmd.FLAG_RESPONSE:
            fut = self._pending.get(frame.sequence)
            if fut and not fut.done():
                fut.set_result(frame)
            return

        if frame.command == cmd.HELLO:
            # Panel-initiated handshake (reboot/reconnect). ACK first with the
            # original sequence, then trigger a snapshot resync.
            await self._send_ack(frame, cmd.OK)
            if self._on_panel_hello:
                try:
                    result = self._on_panel_hello()
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:
                    pass
            if not self._panel_online:
                self._panel_online = True
                if self._on_event:
                    self._on_event(PanelConnectivityChanged(online=True))
            return

        if frame.command == cmd.UI_ACTION:
            key = (frame.sequence, frame.command)
            cached_status = self._event_status.get(key)
            if cached_status is not None:
                if frame.flags & cmd.FLAG_ACK_REQ:
                    await self._send_ack(frame, cached_status)
                return

            try:
                action, object_type, object_id, value, text = proto.parse_ui_action(frame.payload)
            except (ValueError, proto.ProtocolError):
                status = cmd.INVALID_LENGTH
                self._cache_event_status(key, status)
            else:
                # Cache before calling application code. If that code raises
                # after a partial side effect, a retry still cannot execute it
                # a second time.
                status = cmd.OK
                self._cache_event_status(key, status)
                if self._on_event:
                    try:
                        self._on_event(
                            UiAction(
                                action=action,
                                object_type=object_type,
                                object_id=object_id,
                                value=value,
                                text=text,
                            )
                        )
                    except Exception:
                        status = cmd.INTERNAL_ERROR
                        self._event_status[key] = status
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, status)
            return

        # Unknown events are acknowledged (preserving sequence) but ignored.
        if frame.flags & cmd.FLAG_ACK_REQ:
            await self._send_ack(frame, cmd.OK)

    async def _send_ack(self, frame: proto.Frame, status: int) -> None:
        if self._writer is None:
            return
        ack = proto.Frame(
            version=frame.version,
            flags=cmd.FLAG_RESPONSE,
            sequence=frame.sequence,
            command=frame.command,
            payload=status.to_bytes(2, "little"),
        )
        self._writer.write(stuff_frame(ack.raw))

    def _cache_event_status(self, key: tuple[int, int], status: int) -> None:
        if key in self._event_status:
            self._event_status[key] = status
            return
        if len(self._event_order) >= 32:
            oldest = self._event_order.popleft()
            self._event_status.pop(oldest, None)
        self._event_order.append(key)
        self._event_status[key] = status

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._config.heartbeat_seconds)
                uptime = int(time.monotonic() * 1000) % 0xFFFFFFFF
                payload = proto.encode_heartbeat(uptime, self._last_applied_revision)
                try:
                    resp = await self.send(cmd.HEARTBEAT, payload, timeout_ms=200)
                    info = proto.parse_heartbeat_response(resp.payload)
                    if info["status"] != cmd.OK:
                        raise proto.ProtocolError(
                            f"heartbeat rejected with status {info['status']}"
                        )
                    self._last_applied_revision = info["applied_revision"]
                    if not self._panel_online:
                        self._panel_online = True
                        if self._on_event:
                            self._on_event(PanelConnectivityChanged(online=True))
                    if self._on_event:
                        self._on_event(
                            HeartbeatReceived(
                                status=info["status"],
                                t5_uptime_ms=info["t5_uptime_ms"],
                                applied_revision=info["applied_revision"],
                                error_flags=info["error_flags"],
                            )
                        )
                except TimeoutError:
                    if self._panel_online:
                        self._panel_online = False
                        if self._on_event:
                            self._on_event(PanelConnectivityChanged(online=False))
            except asyncio.CancelledError:
                break

    async def _handshake(self) -> None:
        payload = proto.encode_hello(
            peer_role=0x01,
            protocol_major=1,
            protocol_minor=0,
            boot_id=self._boot_id,
            max_payload=proto.MAX_PAYLOAD,
            capabilities=0,
            software_version="nightshift-opi/0.1.0",
        )
        await self.send(cmd.HELLO, payload)
