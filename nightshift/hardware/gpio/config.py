"""GPIO configuration for Nightshift Orange Pi 3B 2G."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class InputConfig:
    enabled: bool
    chip: str
    line: int
    active_low: bool
    rising_debounce_ms: int
    falling_debounce_ms: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InputConfig:
        return cls(
            enabled=data.get("enabled", True),
            chip=data.get("chip", "gpiochip0"),
            line=int(data["line"]),
            active_low=bool(data.get("active_low", False)),
            rising_debounce_ms=int(data.get("rising_debounce_ms", 100)),
            falling_debounce_ms=int(data.get("falling_debounce_ms", 100)),
        )


@dataclass(frozen=True)
class GpioConfig:
    sit: InputConfig
    light: InputConfig
    stabilization_ms: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GpioConfig:
        return cls(
            sit=InputConfig.from_dict(data.get("sit", {"enabled": False, "line": 0})),
            light=InputConfig.from_dict(data["light"]),
            stabilization_ms=int(data.get("stabilization_ms", 2000)),
        )

    @classmethod
    def from_yaml(cls, path: str) -> GpioConfig:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data.get("gpio", {}))
