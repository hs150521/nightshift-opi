"""Nightshift Orange Pi 3B 2G backend entry point."""

from __future__ import annotations

import asyncio
import signal

import structlog

from nightshift.config import load_config
from nightshift.domain.events import ModeChanged
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.integrations.mqtt.client import MqttClient
from nightshift.services.orchestrator import NightshiftOrchestrator

logger = structlog.get_logger()


async def main() -> None:
    config = load_config()

    # TODO(pressure-adapter): swap for the real MQTT-backed PressureSource once
    # the adapter lands. Until then the mock source keeps the backend runnable
    # end-to-end but reports "offline", so the state machine parks in IDLE with
    # SENSOR_ERROR (which is the correct behaviour before hardware ingest).
    pressure_source = MockPressureSource()

    orchestrator = NightshiftOrchestrator(
        pressure_source=pressure_source,
        uart_config=config.uart,
        dwell_ms=config.pressure.dwell_ms,
        stale_ms=config.pressure.stale_ms,
    )

    mqtt_client: MqttClient | None = None
    if config.mqtt.enabled:
        mqtt_client = MqttClient(config.mqtt, orchestrator)
        orchestrator.register_state_listener(mqtt_client.on_state_changed)
        orchestrator.register_event_listener(
            lambda event: mqtt_client.on_mode_changed(event)
            if isinstance(event, ModeChanged)
            else asyncio.sleep(0)
        )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await orchestrator.start()

    if mqtt_client is not None:
        await mqtt_client.start()

    logger.info(
        "service_running",
        node_id=config.node_id,
        uart=config.uart.device,
        baudrate=config.uart.baudrate,
        pressure_client_id=config.pressure.client_id,
        pressure_stale_ms=config.pressure.stale_ms,
        pressure_dwell_ms=config.pressure.dwell_ms,
        mqtt_enabled=config.mqtt.enabled,
    )

    await stop_event.wait()

    if mqtt_client is not None:
        await mqtt_client.stop()
    await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
