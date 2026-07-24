"""Nightshift state machine (pressure-driven, per docs/gap-analysis-v2.md §1.6).

| Input                                                    | Mode        | Attention          |
|----------------------------------------------------------|-------------|--------------------|
| No valid pressure, offline, or state older than 10 s     | IDLE        | SENSOR_ERROR       |
| cushion=true (any footrest)                              | DAY_WORK    | none               |
| cushion=false and footrest=true                          | DAY_WORK    | none               |
| cushion=false and footrest=false for 3 s continuously    | NIGHT_EXEC  | none               |

The 3 s all-released dwell is enforced here, not on the ESP32. Any
triggered input during the dwell cancels it (no debounce carry-over into
DAY_WORK; NIGHT_EXEC->DAY_WORK is immediate).

The old light-sensor `derive_mode` is intentionally gone. The orchestrator
instantiates a single `StateMachineV2` and calls `evaluate` from both the
pressure adapter callback and a low-rate tick loop that pumps the dwell.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nightshift.domain.models import AttentionFlag, SystemMode
from nightshift.domain.pressure import NIGHT_DWELL_MS, STALE_MS, PressureState


@dataclass(frozen=True)
class ModeDecision:
    mode: SystemMode
    reason: str
    attention: AttentionFlag


@dataclass
class StateMachineV2:
    """Stateful evaluator that owns the all-released dwell timer.

    Instances are cheap; tests create a fresh one per case. `now_ms` is
    always injected so behaviour is deterministic without a real clock.
    """

    dwell_ms: int = NIGHT_DWELL_MS
    stale_ms: int = STALE_MS
    _all_released_since_ms: int | None = field(default=None, init=False)

    def evaluate(self, pressure: PressureState, *, now_ms: int) -> ModeDecision:
        if not pressure.is_valid(now_ms, stale_ms=self.stale_ms):
            self._all_released_since_ms = None
            reason = "pressure_offline" if not pressure.online else "pressure_stale"
            return ModeDecision(
                mode=SystemMode.IDLE,
                reason=reason,
                attention=AttentionFlag.SENSOR_ERROR,
            )

        assert pressure.last_sample is not None  # narrowed by is_valid
        cushion = pressure.last_sample.cushion
        footrest = pressure.last_sample.footrest

        if cushion:
            self._all_released_since_ms = None
            return ModeDecision(
                mode=SystemMode.DAY_WORK,
                reason="cushion_pressed",
                attention=AttentionFlag.NONE,
            )
        if footrest:
            self._all_released_since_ms = None
            return ModeDecision(
                mode=SystemMode.DAY_WORK,
                reason="footrest_pressed",
                attention=AttentionFlag.NONE,
            )

        # All released — start or continue the dwell.
        if self._all_released_since_ms is None:
            self._all_released_since_ms = now_ms

        held_ms = now_ms - self._all_released_since_ms
        if held_ms >= self.dwell_ms:
            return ModeDecision(
                mode=SystemMode.NIGHT_EXEC,
                reason="all_released_dwell",
                attention=AttentionFlag.NONE,
            )
        return ModeDecision(
            mode=SystemMode.IDLE,
            reason="all_released_pending_dwell",
            attention=AttentionFlag.NONE,
        )

    def reset(self) -> None:
        self._all_released_since_ms = None
