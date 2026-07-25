"""Core domain models for Nightshift Orange Pi."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum

from nightshift.domain.pressure import PressureState


class SystemMode(StrEnum):
    IDLE = "idle"
    DAY_WORK = "day_work"
    NIGHT_EXEC = "night_exec"


class WorkState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class AttentionFlag(IntFlag):
    NONE = 0
    NEED_CONFIRM = 1 << 0
    SENSOR_ERROR = 1 << 1
    PANEL_OFFLINE = 1 << 2
    BACKEND_ERROR = 1 << 3
    STORAGE_WARNING = 1 << 4
    AGENT_FAILED = 1 << 5
    NETWORK_OFFLINE = 1 << 6


@dataclass(frozen=True)
class PanelTelemetry:
    """Transport-only stats reported by T5 heartbeats.

    Never carried in T5-visible sync payloads; used for diagnostics /
    MQTT telemetry publishing. Updating these fields does NOT bump
    `SystemState.revision`.
    """

    t5_uptime_ms: int = 0
    error_flags: int = 0
    applied_revision: int = 0
    last_heartbeat_at_ms: int = 0


@dataclass(frozen=True)
class SystemState:
    revision: int
    mode: SystemMode
    attention: AttentionFlag
    work_state: WorkState
    pressure: PressureState
    panel_online: bool
    confirmation_count: int
    token_input: int
    token_output: int
    updated_at_ms: int
    panel_telemetry: PanelTelemetry = PanelTelemetry()

    def evolve(
        self,
        *,
        mode: SystemMode | None = None,
        attention: AttentionFlag | None = None,
        work_state: WorkState | None = None,
        pressure: PressureState | None = None,
        panel_online: bool | None = None,
        confirmation_count: int | None = None,
        token_input: int | None = None,
        token_output: int | None = None,
        updated_at_ms: int | None = None,
        panel_telemetry: PanelTelemetry | None = None,
        bump_revision: bool = True,
    ) -> SystemState:
        """Return a new SystemState with the given fields replaced.

        When `bump_revision=True` (default), `revision` advances by one — use
        for authoritative state changes visible to T5. When
        `bump_revision=False`, `revision` is preserved — use for transport
        telemetry (panel_online, panel_telemetry) that must not force T5 to
        re-render.
        """
        return SystemState(
            revision=self.revision + 1 if bump_revision else self.revision,
            mode=mode if mode is not None else self.mode,
            attention=attention if attention is not None else self.attention,
            work_state=work_state if work_state is not None else self.work_state,
            pressure=pressure if pressure is not None else self.pressure,
            panel_online=panel_online if panel_online is not None else self.panel_online,
            confirmation_count=(
                confirmation_count if confirmation_count is not None else self.confirmation_count
            ),
            token_input=token_input if token_input is not None else self.token_input,
            token_output=token_output if token_output is not None else self.token_output,
            updated_at_ms=updated_at_ms if updated_at_ms is not None else self.updated_at_ms,
            panel_telemetry=(
                panel_telemetry if panel_telemetry is not None else self.panel_telemetry
            ),
        )


@dataclass(frozen=True)
class DashboardState:
    revision: int
    urgent_auto: int = 0
    normal_auto: int = 0
    urgent_confirm: int = 0
    normal_confirm: int = 0
    completed_today: int = 0
    failed_today: int = 0
