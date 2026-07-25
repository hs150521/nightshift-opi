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
    """T5 heartbeat response payload (canonical `<HIII>` layout).

    `status` is a T5-Link status code. `applied_revision` is the last
    OPI-authored `SystemState.revision` that T5 has committed to its
    display. `t5_uptime_ms` and `error_flags` are diagnostic-only.
    """

    status: int
    t5_uptime_ms: int
    applied_revision: int
    error_flags: int
    received_at_ms: int = 0


@dataclass(frozen=True)
class HeartbeatFailed:
    """Heartbeat completed but T5 returned a non-OK status."""

    status: int
    error_flags: int
    occurred_at_ms: int = 0


@dataclass(frozen=True)
class PageEvent:
    """T5 emits this when the user changes page or triggers a page-scoped hook."""

    page_id: int
    event: int
    object_id: int
    occurred_at_ms: int = 0


DomainEvent = (
    PressureChanged
    | ModeChanged
    | WorkStateChanged
    | AttentionChanged
    | PanelConnectivityChanged
    | UiAction
    | HeartbeatReceived
    | HeartbeatFailed
    | PageEvent
)
