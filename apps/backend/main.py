"""Nightshift Orange Pi 3B 2G backend entry point."""

from __future__ import annotations

import asyncio
import os
import signal

import structlog

from nightshift.config import load_config
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.integrations.mqtt.client import MqttClient
from nightshift.integrations.mqtt.pressure_adapter import PressureMqttAdapter
from nightshift.persistence.database import Database
from nightshift.services.orchestrator import NightshiftOrchestrator

logger = structlog.get_logger()

_DEFAULT_DB_PATH = "/var/lib/nightshift/nightshift.db"


async def main() -> None:
    config = load_config()

    db_path = os.getenv("NIGHTSHIFT_DB_PATH", _DEFAULT_DB_PATH)
    db = Database(db_path)
    await db.open()

    if config.mqtt.enabled:
        pressure_source = PressureMqttAdapter(
            device_id=config.pressure.client_id,
        )
    else:
        pressure_source = MockPressureSource()

    orchestrator = NightshiftOrchestrator(
        pressure_source=pressure_source,
        uart_config=config.uart,
        db=db,
        dwell_ms=config.pressure.dwell_ms,
        stale_ms=config.pressure.stale_ms,
    )

    if isinstance(pressure_source, PressureMqttAdapter):
        pressure_source.on_updated = orchestrator.on_pressure_updated

    mqtt_client: MqttClient | None = None
    if config.mqtt.enabled:
        mqtt_client = MqttClient(config.mqtt, orchestrator)
        orchestrator.register_state_listener(mqtt_client.on_state_changed)
        orchestrator.register_event_listener(mqtt_client.on_domain_event)

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
        db_path=db_path,
    )

    await stop_event.wait()

    if mqtt_client is not None:
        await mqtt_client.stop()
    await orchestrator.stop()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
