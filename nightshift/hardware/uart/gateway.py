"""Asynchronous UART gateway to the T5 panel with session management."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from nightshift.domain import commands as cmd
from nightshift.domain.events import (
    HeartbeatFailed,
    HeartbeatReceived,
    PageEvent,
    PanelConnectivityChanged,
    UiAction,
)
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame, unstuff_frame
from nightshift.hardware.uart.session import (
    DedupKey,
    DedupResult,
    Disposition,
    UartSession,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UartConfig:
    device: str
    baudrate: int = 460800
    heartbeat_seconds: float = 2.0
    command_timeout_ms: float = 200.0
    max_retries: int = 3
    reconnect_delay_ms: float = 1000.0
    max_reconnect_delay_ms: float = 30000.0


UiActionHandler = Callable[[UiAction], Coroutine[Any, Any, tuple[int, bytes]]]


class UartGateway:
    """Manages the T5 UART connection, framing, session, and command lifecycle."""

    def __init__(
        self,
        config: UartConfig,
        on_event: Callable[[Any], None] | None = None,
        on_panel_hello: Callable[[], Any] | None = None,
        on_peer_boot_id_change: Callable[[int | None, int], None] | None = None,
        ui_action_handler: UiActionHandler | None = None,
    ) -> None:
        self._config = config
        self._on_event = on_event
        self._on_panel_hello = on_panel_hello
        self._on_peer_boot_id_change = on_peer_boot_id_change
        self._ui_action_handler = ui_action_handler
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence = 0
        self._boot_id = int(time.monotonic() * 1000) & 0xFFFFFFFF
        self._session = UartSession()
        self._pending: dict[int, asyncio.Future[proto.Frame]] = {}
        self._last_applied_revision = 0
        self._panel_online = False
        self._read_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._connected = False
        self._running = False

    @property
    def peer_boot_id(self) -> int | None:
        return self._session.boot_id

    @property
    def last_applied_revision(self) -> int:
        return self._last_applied_revision

    @property
    def session(self) -> UartSession:
        return self._session

    async def start(self) -> None:
        self._running = True
        self._read_task = asyncio.create_task(self._connection_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._read_task:
            self._read_task.cancel()
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        await self._disconnect()
        self._panel_online = False

    async def _connect(self) -> bool:
        try:
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
            self._connected = True
            logger.info("uart_connected", device=self._config.device)
            return True
        except Exception as exc:
            logger.warning("uart_connect_failed", error=str(exc))
            self._connected = False
            return False

    async def _disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._connected = False

    async def _connection_loop(self) -> None:
        delay = self._config.reconnect_delay_ms
        while self._running:
            if not self._connected:
                if await self._connect():
                    delay = self._config.reconnect_delay_ms
                    asyncio.create_task(self._read_loop())
                    try:
                        await self._handshake()
                    except Exception:
                        logger.warning("handshake_failed_after_connect")
                else:
                    await asyncio.sleep(delay / 1000.0)
                    delay = min(delay * 2, self._config.max_reconnect_delay_ms)
            else:
                await asyncio.sleep(1.0)

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
        if not self._connected or self._writer is None:
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
            except Exception as exc:
                last_error = exc
                break
            finally:
                self._pending.pop(seq, None)

        raise TimeoutError(
            f"command {command:04x} seq {seq} timed out after {self._config.max_retries} retries"
        ) from last_error

    async def send_no_wait(self, command: int, payload: bytes = b"", flags: int = 0) -> None:
        if not self._connected or self._writer is None:
            return
        seq = self._next_sequence()
        frame = proto.Frame.request(seq, command, payload, flags)
        self._writer.write(stuff_frame(frame.raw))

    async def _read_loop(self) -> None:
        buffer = bytearray()
        while self._running and self._connected:
            try:
                if self._reader is None:
                    break
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
                        pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("read_loop_error", error=str(exc))
                self._connected = False
                if self._panel_online:
                    self._panel_online = False
                    if self._on_event:
                        self._on_event(PanelConnectivityChanged(online=False))
                break

    async def _dispatch(self, frame: proto.Frame) -> None:
        if frame.flags & cmd.FLAG_RESPONSE:
            fut = self._pending.get(frame.sequence)
            if fut and not fut.done():
                fut.set_result(frame)
            return

        if frame.command == cmd.HELLO:
            try:
                hello = proto.parse_hello(frame.payload)
            except proto.ProtocolError:
                logger.warning("malformed HELLO payload, rejecting")
                await self._send_ack(frame, cmd.INVALID_ARGUMENT)
                return

            await self._send_ack(frame, cmd.OK)
            previous_boot_id = self._session.boot_id
            if previous_boot_id != hello.boot_id:
                self._session.reset(hello.boot_id)
                if self._on_peer_boot_id_change:
                    try:
                        self._on_peer_boot_id_change(previous_boot_id, hello.boot_id)
                    except Exception:
                        logger.exception("on_peer_boot_id_change failed")
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
            await self._handle_ui_action(frame)
            return

        if frame.command == cmd.PAGE_EVENT:
            try:
                page = proto.parse_page_event(frame.payload)
                if self._on_event:
                    self._on_event(
                        PageEvent(
                            page_id=page.page_id,
                            event=page.event,
                            object_id=page.object_id,
                            occurred_at_ms=int(time.monotonic() * 1000),
                        )
                    )
            except proto.ProtocolError:
                logger.warning("failed to parse PAGE_EVENT payload")
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, cmd.OK)
            return

        if frame.flags & cmd.FLAG_ACK_REQ:
            await self._send_ack(frame, cmd.OK)

    async def _handle_ui_action(self, frame: proto.Frame) -> None:
        try:
            action, object_type, object_id, value, text = proto.parse_ui_action(
                frame.payload
            )
        except proto.ProtocolError:
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, cmd.INVALID_LENGTH)
            return

        event = UiAction(
            action=action,
            object_type=object_type,
            object_id=object_id,
            value=value,
            text=text,
        )

        if not self._session.is_active():
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, cmd.NOT_READY)
            return

        dedup = self._session.check_action(
            boot_id=self._session.boot_id,
            sequence=frame.sequence,
            command=frame.command,
            payload=frame.payload,
        )

        if dedup.disposition == Disposition.REPLAY:
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, dedup.cached_status, dedup.cached_reply or b"")
            return

        if dedup.disposition == Disposition.CONFLICT:
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, cmd.STATE_CONFLICT)
            return

        if dedup.disposition == Disposition.IN_FLIGHT:
            if frame.flags & cmd.FLAG_ACK_REQ:
                await self._send_ack(frame, cmd.BUSY)
            return

        # disposition == EXECUTE
        if self._on_event:
            self._on_event(event)

        status = cmd.NOT_READY
        reply_data = b""

        if self._ui_action_handler:
            try:
                status, reply_data = await self._ui_action_handler(event)
            except Exception as exc:
                logger.warning("ui_action_handler_failed", error=str(exc))
                status = cmd.INTERNAL_ERROR
        else:
            status = cmd.NOT_READY

        self._session.record_result(
            key=dedup.dedup_key,
            digest=dedup.digest,
            status=status,
            reply_data=reply_data,
        )

        if frame.flags & cmd.FLAG_ACK_REQ:
            await self._send_ack(frame, status, reply_data)

    async def _send_ack(
        self,
        frame: proto.Frame,
        status: int,
        data: bytes = b"",
    ) -> None:
        if self._writer is None:
            return
        ack = proto.Frame(
            version=frame.version,
            flags=cmd.FLAG_RESPONSE,
            sequence=frame.sequence,
            command=frame.command,
            payload=status.to_bytes(2, "little") + data,
        )
        self._writer.write(stuff_frame(ack.raw))

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._config.heartbeat_seconds)
                if not self._connected:
                    continue
                uptime = int(time.monotonic() * 1000) % 0xFFFFFFFF
                payload = proto.encode_heartbeat(uptime, self._last_applied_revision)
                try:
                    resp = await self.send(cmd.HEARTBEAT, payload, timeout_ms=200)
                    hb = proto.parse_heartbeat_response(resp.payload)
                    received_at_ms = int(time.monotonic() * 1000)
                    if hb.status == cmd.OK:
                        self._last_applied_revision = hb.applied_revision
                        if not self._panel_online:
                            self._panel_online = True
                            if self._on_event:
                                self._on_event(PanelConnectivityChanged(online=True))
                        if self._on_event:
                            self._on_event(
                                HeartbeatReceived(
                                    status=hb.status,
                                    t5_uptime_ms=hb.t5_uptime_ms,
                                    applied_revision=hb.applied_revision,
                                    error_flags=hb.error_flags,
                                    received_at_ms=received_at_ms,
                                )
                            )
                    else:
                        logger.warning(
                            "heartbeat non-ok: status=0x%04x error_flags=0x%08x",
                            hb.status,
                            hb.error_flags,
                        )
                        if self._on_event:
                            self._on_event(
                                HeartbeatFailed(
                                    status=hb.status,
                                    error_flags=hb.error_flags,
                                    occurred_at_ms=int(time.monotonic() * 1000),
                                )
                            )
                except (TimeoutError, RuntimeError):
                    if self._panel_online:
                        self._panel_online = False
                        if self._on_event:
                            self._on_event(PanelConnectivityChanged(online=False))
                except proto.ProtocolError as exc:
                    logger.warning("heartbeat_parse_error", error=str(exc))
                except Exception as exc:
                    logger.warning("heartbeat_unexpected_error", error=str(exc))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("heartbeat_loop_error", error=str(exc))

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
