"""Real ESP32 pressure MQTT adapter.

Subscribes to:
  nightshift/v1/sensor/pressure/pressure-01/availability
  nightshift/v1/sensor/pressure/pressure-01/state
  nightshift/v1/sensor/pressure/pressure-01/telemetry

Implements strict validation per frozen ESP32 pressure contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from nightshift.domain.pressure import PressureSource, PressureSample, PressureState
from nightshift.domain.pressure_codec import PressureDecodeError, decode_pressure_state

log = logging.getLogger(__name__)

AVAILABILITY_SCHEMA = "nightshift.sensor-availability.v1"


@dataclass(frozen=True)
class PressureAdapterConfig:
    device_id: str = "pressure-01"
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = "nightshift/v1/sensor/pressure"
    stale_ms: int = 10_000
    keepalive: int = 30


@dataclass
class PressureMqttAdapter(PressureSource):
    """Production pressure source that subscribes to ESP32 MQTT topics."""

    config: PressureAdapterConfig
    on_updated: Callable[[], Coroutine[Any, Any, None]] | None = None

    _state: PressureState = field(default_factory=PressureState.empty)
    _last_boot_id: str | None = field(default=None, init=False)
    _last_seq: int = field(default=-1, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def snapshot(self) -> PressureState:
        return self._state

    async def start(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        log.info(
            "pressure_adapter: started, device=%s, broker=%s:%d",
            self.config.device_id,
            self.config.broker_host,
            self.config.broker_port,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("pressure_adapter: stopped")

    def _topic_availability(self) -> str:
        return f"{self.config.base_topic}/{self.config.device_id}/availability"

    def _topic_state(self) -> str:
        return f"{self.config.base_topic}/{self.config.device_id}/state"

    def _topic_telemetry(self) -> str:
        return f"{self.config.base_topic}/{self.config.device_id}/telemetry"

    async def _run_loop(self) -> None:
        import aiomqtt

        backoff = 1.0
        max_backoff = 30.0

        while not self._stop_event.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self.config.broker_host,
                    port=self.config.broker_port,
                    username=self.config.username or None,
                    password=self.config.password or None,
                    identifier=f"nightshift-pressure-sub-{self.config.device_id}",
                    keepalive=self.config.keepalive,
                ) as client:
                    await client.subscribe(self._topic_availability(), qos=1)
                    await client.subscribe(self._topic_state(), qos=1)
                    await client.subscribe(self._topic_telemetry(), qos=0)
                    log.info("pressure_adapter: subscribed to topics")
                    backoff = 1.0

                    async for message in client.messages:
                        if self._stop_event.is_set():
                            break
                        await self._handle_message(message)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "pressure_adapter: connection error, reconnect in %.1fs: %s",
                    backoff,
                    exc,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    return
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)

    async def _handle_message(self, message: Any) -> None:
        topic = str(message.topic)
        payload = message.payload

        if topic == self._topic_availability():
            await self._handle_availability(payload)
        elif topic == self._topic_state():
            await self._handle_state(payload)
        # Telemetry is diagnostic only, not authoritative state

    async def _handle_availability(self, raw: bytes) -> None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("pressure_adapter: invalid availability JSON: %s", exc)
            return

        if not isinstance(data, dict):
            log.warning("pressure_adapter: availability not a JSON object")
            return

        if data.get("schema") != AVAILABILITY_SCHEMA:
            log.warning("pressure_adapter: unexpected availability schema: %r", data.get("schema"))
            return

        device_id = data.get("device_id")
        if device_id != self.config.device_id:
            log.warning(
                "pressure_adapter: device_id mismatch: expected %r, got %r",
                self.config.device_id,
                device_id,
            )
            return

        online = data.get("online")
        if not isinstance(online, bool):
            log.warning("pressure_adapter: 'online' must be bool")
            return

        now_ms = int(time.monotonic() * 1000)

        if not online:
            self._state = PressureState(
                online=False,
                last_sample=self._state.last_sample,
                updated_at_ms=now_ms,
            )
            log.info("pressure_adapter: device offline")
        else:
            boot_id = data.get("boot_id")
            if isinstance(boot_id, str) and boot_id != self._last_boot_id:
                self._last_boot_id = boot_id
                self._last_seq = -1
                log.info("pressure_adapter: new boot_id=%s", boot_id)

            self._state = PressureState(
                online=True,
                last_sample=self._state.last_sample,
                updated_at_ms=now_ms,
            )
            log.info("pressure_adapter: device online, boot_id=%s", boot_id)

        if self.on_updated:
            await self.on_updated()

    async def _handle_state(self, raw: bytes) -> None:
        now_ms = int(time.monotonic() * 1000)

        try:
            sample = decode_pressure_state(raw, received_at_ms=now_ms)
        except PressureDecodeError as exc:
            log.warning("pressure_adapter: decode error (logged, not offline): %s", exc)
            return

        if sample.device_id != self.config.device_id:
            log.warning(
                "pressure_adapter: state device_id mismatch: %r != %r",
                sample.device_id,
                self.config.device_id,
            )
            return

        if sample.boot_id != self._last_boot_id:
            self._last_boot_id = sample.boot_id
            self._last_seq = -1
            log.info("pressure_adapter: boot_id from state: %s", sample.boot_id)

        if sample.seq <= self._last_seq:
            log.debug(
                "pressure_adapter: duplicate/reordered seq=%d <= last=%d, dropping",
                sample.seq,
                self._last_seq,
            )
            return

        self._last_seq = sample.seq
        self._state = PressureState(
            online=self._state.online,
            last_sample=sample,
            updated_at_ms=now_ms,
        )

        if self.on_updated:
            await self.on_updated()
