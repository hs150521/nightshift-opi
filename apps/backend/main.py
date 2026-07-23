"""Nightshift Orange Pi 5B backend entry point."""

from __future__ import annotations

import asyncio
import signal

import structlog

from nightshift.config import load_config
from nightshift.services.orchestrator import NightshiftOrchestrator

logger = structlog.get_logger()


async def main() -> None:
    config = load_config()
    orchestrator = NightshiftOrchestrator(
        gpio_config=config.gpio,
        uart_config=config.uart,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await orchestrator.start()
    logger.info(
        "service_running",
        node_id=config.node_id,
        uart=config.uart.device,
        baudrate=config.uart.baudrate,
        light_chip=config.gpio.light.chip,
        light_line=config.gpio.light.line,
    )

    await stop_event.wait()
    await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
