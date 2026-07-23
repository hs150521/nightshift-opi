"""Application configuration loader."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from nightshift.hardware.gpio.config import GpioConfig
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.integrations.mqtt.config import MqttConfig


@dataclass(frozen=True)
class AppConfig:
    node_id: str
    gpio: GpioConfig
    uart: UartConfig
    mqtt: MqttConfig


def load_config(env_path: str | None = None) -> AppConfig:
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    gpio_cfg = GpioConfig.from_dict(
        {
            "stabilization_ms": int(os.getenv("NIGHTSHIFT_GPIO_STABILIZATION_MS", "2000")),
            "light": {
                "chip": os.getenv("NIGHTSHIFT_GPIO_LIGHT_CHIP", "gpiochip4"),
                "line": int(os.getenv("NIGHTSHIFT_GPIO_LIGHT_LINE", "4")),
                "active_low": os.getenv("NIGHTSHIFT_GPIO_LIGHT_ACTIVE_LOW", "false").lower()
                == "true",
                "rising_debounce_ms": int(os.getenv("NIGHTSHIFT_GPIO_LIGHT_RISING_MS", "1000")),
                "falling_debounce_ms": int(
                    os.getenv("NIGHTSHIFT_GPIO_LIGHT_FALLING_MS", "1000")
                ),
            },
            "sit": {
                "enabled": os.getenv("NIGHTSHIFT_GPIO_SIT_ENABLED", "false").lower() == "true",
                "chip": os.getenv("NIGHTSHIFT_GPIO_SIT_CHIP", "gpiochip0"),
                "line": int(os.getenv("NIGHTSHIFT_GPIO_SIT_LINE", "0")),
                "active_low": os.getenv("NIGHTSHIFT_GPIO_SIT_ACTIVE_LOW", "false").lower()
                == "true",
                "rising_debounce_ms": int(os.getenv("NIGHTSHIFT_GPIO_SIT_RISING_MS", "150")),
                "falling_debounce_ms": int(os.getenv("NIGHTSHIFT_GPIO_SIT_FALLING_MS", "300")),
            },
        }
    )

    uart_cfg = UartConfig(
        device=os.getenv("NIGHTSHIFT_UART_DEVICE", "/dev/ttyS7"),
        baudrate=int(os.getenv("NIGHTSHIFT_UART_BAUDRATE", "460800")),
        heartbeat_seconds=float(os.getenv("NIGHTSHIFT_UART_HEARTBEAT_SECONDS", "2.0")),
    )

    node_id = os.getenv("NIGHTSHIFT_NODE_ID", "opi3b01")

    mqtt_cfg = MqttConfig.from_env(node_id)

    return AppConfig(
        node_id=node_id,
        gpio=gpio_cfg,
        uart=uart_cfg,
        mqtt=mqtt_cfg,
    )
