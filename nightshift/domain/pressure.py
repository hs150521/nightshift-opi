"""Pressure sensor domain model and interfaces.

This module owns the OPI-side representation of the ESP32 pressure sensor
(`pressure-01`). The wire schema is `nightshift.pressure-state.v1` and lives
in docs/gap-analysis-v2.md §1.5. Semantics:

- cushion = gpio4 OR gpio5
- footrest = gpio6 OR gpio7
- present = cushion OR footrest
- ESP32 publishes on every logical change AND every 3 seconds as heartbeat.
- OPI marks state as invalid if it is older than STALE_MS (10 s) or missing.

The 3 s all-released dwell (`NIGHT_EXEC`) is enforced on OPI, not ESP32.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

STALE_MS = 10_000
NIGHT_DWELL_MS = 3_000
PRESSURE_SCHEMA_V1 = "nightshift.pressure-state.v1"


@dataclass(frozen=True)
class PressureSample:
    """A single pressure sample decoded from the ESP32 state topic.

    `received_at_ms` is the OPI-side monotonic timestamp at receipt. It is
    what the staleness check uses; the ESP32-reported `uptime_ms` is stored
    for observability only.
    """

    device_id: str
    boot_id: str
    seq: int
    cushion: bool
    footrest: bool
    present: bool
    uptime_ms: int
    received_at_ms: int


@dataclass(frozen=True)
class PressureState:
    """Rolling pressure state consumed by the state machine.

    `online` is derived from the retained MQTT availability topic. `valid`
    means we have a fresh sample from the current boot. Callers must
    recompute `valid` against a current clock via `is_valid`.
    """

    online: bool
    last_sample: PressureSample | None
    updated_at_ms: int

    @classmethod
    def empty(cls) -> PressureState:
        return cls(online=False, last_sample=None, updated_at_ms=0)

    def is_valid(self, now_ms: int, *, stale_ms: int = STALE_MS) -> bool:
        if not self.online or self.last_sample is None:
            return False
        return (now_ms - self.last_sample.received_at_ms) <= stale_ms

    @property
    def cushion(self) -> bool:
        return self.last_sample.cushion if self.last_sample else False

    @property
    def footrest(self) -> bool:
        return self.last_sample.footrest if self.last_sample else False


class PressureSource(Protocol):
    """Read-only accessor consumed by the state machine and orchestrator.

    Implementations: MqttPressureSensorAdapter (real broker), MockPressureSource
    (tests, offline dev).
    """

    def snapshot(self) -> PressureState: ...
