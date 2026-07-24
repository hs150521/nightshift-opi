"""Application configuration loader."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from nightshift.domain.pressure import NIGHT_DWELL_MS, STALE_MS
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.integrations.mqtt.config import MqttConfig


@dataclass(frozen=True)
class PressureConfig:
    client_id: str
    stale_ms: int
    dwell_ms: int


@dataclass(frozen=True)
class AppConfig:
    node_id: str
    pressure: PressureConfig
    uart: UartConfig
    mqtt: MqttConfig


def load_config(env_path: str | None = None) -> AppConfig:
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    node_id = os.getenv("NIGHTSHIFT_NODE_ID", "opi3b01")

    pressure_cfg = PressureConfig(
        client_id=os.getenv("NIGHTSHIFT_PRESSURE_CLIENT_ID", "pressure-01"),
        stale_ms=int(os.getenv("NIGHTSHIFT_PRESSURE_STALE_MS", str(STALE_MS))),
        dwell_ms=int(os.getenv("NIGHTSHIFT_PRESSURE_DWELL_MS", str(NIGHT_DWELL_MS))),
    )

    uart_cfg = UartConfig(
        device=os.getenv("NIGHTSHIFT_UART_DEVICE", "/dev/ttyS3"),
        baudrate=int(os.getenv("NIGHTSHIFT_UART_BAUDRATE", "460800")),
        heartbeat_seconds=float(os.getenv("NIGHTSHIFT_UART_HEARTBEAT_SECONDS", "2.0")),
    )

    mqtt_cfg = MqttConfig.from_env(node_id)

    return AppConfig(
        node_id=node_id,
        pressure=pressure_cfg,
        uart=uart_cfg,
        mqtt=mqtt_cfg,
    )
