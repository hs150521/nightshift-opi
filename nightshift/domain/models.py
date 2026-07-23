"""Core domain models for Nightshift Orange Pi."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum


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
class EnvironmentState:
    ready: bool
    sit: bool
    light: bool
    changed_at_ms: int


@dataclass(frozen=True)
class SystemState:
    revision: int
    mode: SystemMode
    attention: AttentionFlag
    work_state: WorkState
    environment: EnvironmentState
    panel_online: bool
    confirmation_count: int
    token_input: int
    token_output: int
    updated_at_ms: int

    def evolve(
        self,
        *,
        mode: SystemMode | None = None,
        attention: AttentionFlag | None = None,
        work_state: WorkState | None = None,
        environment: EnvironmentState | None = None,
        panel_online: bool | None = None,
        confirmation_count: int | None = None,
        token_input: int | None = None,
        token_output: int | None = None,
        updated_at_ms: int | None = None,
    ) -> SystemState:
        return SystemState(
            revision=self.revision + 1,
            mode=mode if mode is not None else self.mode,
            attention=attention if attention is not None else self.attention,
            work_state=work_state if work_state is not None else self.work_state,
            environment=environment if environment is not None else self.environment,
            panel_online=panel_online if panel_online is not None else self.panel_online,
            confirmation_count=(
                confirmation_count if confirmation_count is not None else self.confirmation_count
            ),
            token_input=token_input if token_input is not None else self.token_input,
            token_output=token_output if token_output is not None else self.token_output,
            updated_at_ms=updated_at_ms if updated_at_ms is not None else self.updated_at_ms,
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


@dataclass(frozen=True)
class UptimeState:
    opi_ms: int
    t5_ms: int
    applied_revision: int
    error_flags: int
