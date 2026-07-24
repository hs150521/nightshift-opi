"""Domain events emitted by the Nightshift system."""

from __future__ import annotations

from dataclasses import dataclass

from nightshift.domain.models import SystemMode, WorkState
from nightshift.domain.pressure import PressureState


@dataclass(frozen=True)
class PressureChanged:
    pressure: PressureState
    revision: int = 0
    occurred_at_ms: int = 0


@dataclass(frozen=True)
class ModeChanged:
    previous: SystemMode
    current: SystemMode
    reason: str
    revision: int = 0
    occurred_at_ms: int = 0

    @property
    def from_mode(self) -> SystemMode:
        return self.previous

    @property
    def to_mode(self) -> SystemMode:
        return self.current


@dataclass(frozen=True)
class WorkStateChanged:
    previous: WorkState
    current: WorkState


@dataclass(frozen=True)
class AttentionChanged:
    flags: int
    confirmation_count: int


@dataclass(frozen=True)
class PanelConnectivityChanged:
    online: bool


@dataclass(frozen=True)
class UiAction:
    action: int
    object_type: int
    object_id: int
    value: int
    text: str


@dataclass(frozen=True)
class HeartbeatReceived:
    status: int
    t5_uptime_ms: int
    applied_revision: int
    error_flags: int


DomainEvent = (
    PressureChanged
    | ModeChanged
    | WorkStateChanged
    | AttentionChanged
    | PanelConnectivityChanged
    | UiAction
    | HeartbeatReceived
)
