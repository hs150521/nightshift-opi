"""Monitor/debug tool: show light sensor + MQTT status on the T5 screen.

Reads the configured GPIO light sensor and pushes a short status message to the
T5 panel via UART using ATTENTION_SET. Also publishes the same status to the
local MQTT broker when NIGHTSHIFT_MQTT_ENABLED=true.

Run as root for GPIO access:
    sudo .venv/bin/python tools/t5_display_monitor.py
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import aiomqtt
import serial_asyncio
from dotenv import load_dotenv

from nightshift.domain import commands as cmd
from nightshift.domain.models import AttentionFlag, EnvironmentState
from nightshift.hardware.gpio.adapter import GpioAdapter
from nightshift.hardware.gpio.config import GpioConfig, InputConfig
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.codec import stuff_frame
from nightshift.hardware.uart.gateway import UartConfig

load_dotenv(Path(__file__).parent.parent / ".env")


def _getenv(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _build_attention_frame(sequence: int, message: str) -> bytes:
    """Build a framed ATTENTION_SET command carrying *message*."""
    payload = proto.encode_attention_set(
        revision=sequence,
        attention=AttentionFlag.NONE,
        confirmation_count=0,
        short_message=message,
    )
    frame = proto.Frame.request(sequence, cmd.ATTENTION_SET, payload, cmd.FLAG_ACK_REQ)
    return stuff_frame(frame.raw)


async def _mqtt_publish_status(
    host: str,
    port: int,
    username: str,
    password: str,
    message: str,
) -> None:
    """Publish a short status message to the local MQTT broker."""
    try:
        async with aiomqtt.Client(
            hostname=host,
            port=port,
            username=username or None,
            password=password or None,
            keepalive=30,
        ) as client:
            await client.publish("nightshift/v1/debug/display", message, qos=0)
    except Exception as exc:
        print(f"MQTT publish skipped: {exc}")


def _make_gpio_config() -> GpioConfig:
    """Build a GpioConfig from environment variables."""
    chip = _getenv("NIGHTSHIFT_GPIO_LIGHT_CHIP", "gpiochip4")
    if not chip.startswith("/dev/"):
        chip = f"/dev/{chip}"
    return GpioConfig(
        light=InputConfig(
            enabled=True,
            chip=chip,
            line=int(_getenv("NIGHTSHIFT_GPIO_LIGHT_LINE", "4")),
            active_low=_getenv("NIGHTSHIFT_GPIO_LIGHT_ACTIVE_LOW", "false").lower() == "true",
            rising_debounce_ms=50,
            falling_debounce_ms=50,
        ),
        sit=InputConfig(
            enabled=False,
            chip="gpiochip0",
            line=0,
            active_low=False,
            rising_debounce_ms=150,
            falling_debounce_ms=300,
        ),
        stabilization_ms=0,
    )


async def main() -> None:
    uart_device = _getenv("NIGHTSHIFT_UART_DEVICE", "/dev/ttyS3")
    uart_baud = int(_getenv("NIGHTSHIFT_UART_BAUDRATE", "460800"))
    refresh_seconds = float(_getenv("NIGHTSHIFT_DISPLAY_REFRESH_SECONDS", "2.0"))

    mqtt_enabled = _getenv("NIGHTSHIFT_MQTT_ENABLED", "false").lower() == "true"
    mqtt_host = _getenv("NIGHTSHIFT_MQTT_HOST", "127.0.0.1")
    mqtt_port = int(_getenv("NIGHTSHIFT_MQTT_PORT", "1883"))
    mqtt_user = _getenv("NIGHTSHIFT_MQTT_USERNAME", "")
    mqtt_pass = _getenv("NIGHTSHIFT_MQTT_PASSWORD", "")

    print(f"UART: {uart_device} @ {uart_baud}")
    print(f"MQTT: enabled={mqtt_enabled} {mqtt_host}:{mqtt_port}")
    print("Press Ctrl+C to stop\n")

    gpio = GpioAdapter(_make_gpio_config())
    gpio.open()

    uart_cfg = UartConfig(device=uart_device, baudrate=uart_baud)
    reader, writer = await serial_asyncio.open_serial_connection(
        url=uart_cfg.device,
        baudrate=uart_cfg.baudrate,
        bytesize=8,
        parity="N",
        stopbits=1,
        rtscts=False,
        dsrdtr=False,
    )

    sequence = 0
    try:
        while True:
            env: EnvironmentState = gpio.poll()
            light_text = "ON" if env.light else "OFF"
            mqtt_text = "UP" if mqtt_enabled else "OFF"
            sit_text = "--"  # placeholder for pressure sensor

            message = f"L:{light_text} P:{sit_text} M:{mqtt_text}"

            frame = _build_attention_frame(sequence, message)
            writer.write(frame)
            await writer.drain()

            print(f"[{time.strftime('%H:%M:%S')}] {message}")

            if mqtt_enabled:
                await _mqtt_publish_status(
                    mqtt_host, mqtt_port, mqtt_user, mqtt_pass, message
                )

            sequence = (sequence + 1) % 65535
            await asyncio.sleep(refresh_seconds)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        gpio.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
