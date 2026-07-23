"""Nightshift Orange Pi 3B 2G backend entry point."""

from __future__ import annotations

import asyncio
import signal

import structlog

from nightshift.config import load_config
from nightshift.domain.events import ModeChanged
from nightshift.integrations.mqtt.client import MqttClient
from nightshift.services.orchestrator import NightshiftOrchestrator

logger = structlog.get_logger()


async def main() -> None:
    config = load_config()
    orchestrator = NightshiftOrchestrator(
        gpio_config=config.gpio,
        uart_config=config.uart,
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
        light_chip=config.gpio.light.chip,
        light_line=config.gpio.light.line,
        mqtt_enabled=config.mqtt.enabled,
    )

    await stop_event.wait()

    if mqtt_client is not None:
        await mqtt_client.stop()
    await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
