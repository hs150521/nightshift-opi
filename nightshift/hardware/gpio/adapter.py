"""GPIO adapter for Orange Pi 3B 2G using libgpiod."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

try:
    import gpiod
    from gpiod.line import Bias, Direction, Edge, Value

    HAS_GPIOD = True
except Exception:  # pragma: no cover - libgpiod may be absent on dev machines
    gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False

from nightshift.domain.models import EnvironmentState
from nightshift.hardware.gpio.config import GpioConfig, InputConfig
from nightshift.hardware.gpio.debounce import Debouncer


@dataclass
class _TrackedInput:
    config: InputConfig
    debouncer: Debouncer
    request: Any = None
    last_value: bool = False


class GpioAdapter:
    """Reads and debounces digital inputs, producing EnvironmentState snapshots."""

    def __init__(
        self,
        config: GpioConfig,
        callback: Callable[[EnvironmentState], None] | None = None,
    ) -> None:
        self._config = config
        self._callback = callback
        self._started_at_ms = int(time.monotonic() * 1000)
        self._inputs: dict[str, _TrackedInput] = {}
        self._ready = False

    def open(self) -> None:
        self._inputs["light"] = _TrackedInput(
            config=self._config.light,
            debouncer=Debouncer(
                rising_ms=self._config.light.rising_debounce_ms,
                falling_ms=self._config.light.falling_debounce_ms,
            ),
        )
        if self._config.sit.enabled:
            self._inputs["sit"] = _TrackedInput(
                config=self._config.sit,
                debouncer=Debouncer(
                    rising_ms=self._config.sit.rising_debounce_ms,
                    falling_ms=self._config.sit.falling_debounce_ms,
                ),
            )
        if HAS_GPIOD:
            for tracked in self._inputs.values():
                tracked.request = self._open_line(tracked.config)

    def _open_line(self, cfg: InputConfig) -> Any:
        if gpiod is None:
            return None
        # Keep inactive state stable when no external drive is present.
        bias = Bias.PULL_DOWN if not cfg.active_low else Bias.PULL_UP
        return gpiod.request_lines(
            cfg.chip,
            consumer="nightshift",
            config={
                cfg.line: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.BOTH,
                    bias=bias,
                    active_low=cfg.active_low,
                )
            },
        )

    def close(self) -> None:
        for tracked in self._inputs.values():
            if tracked.request is not None:
                try:
                    tracked.request.release()
                except Exception:
                    pass
        self._inputs.clear()

    def _read(self, tracked: _TrackedInput) -> bool:
        if tracked.request is not None:
            value = tracked.request.get_value(tracked.config.line)
            return bool(value == Value.ACTIVE)
        return False

    def poll(self, now_ms: int | None = None) -> EnvironmentState:
        """Read all inputs, apply debouncing and emit an EnvironmentState."""
        if now_ms is None:
            now_ms = int(time.monotonic() * 1000)

        light_value = False
        sit_value = False
        all_settled = True

        for name, tracked in self._inputs.items():
            raw = self._read(tracked)
            stable, _changed = tracked.debouncer.update(raw, now_ms)
            tracked.last_value = stable
            if name == "light":
                light_value = stable
            elif name == "sit":
                sit_value = stable
            if not tracked.debouncer.settled:
                all_settled = False

        elapsed = now_ms - self._started_at_ms
        self._ready = all_settled and elapsed >= self._config.stabilization_ms

        env = EnvironmentState(
            ready=self._ready,
            sit=sit_value,
            light=light_value,
            changed_at_ms=now_ms,
        )
        if self._callback is not None:
            self._callback(env)
        return env
