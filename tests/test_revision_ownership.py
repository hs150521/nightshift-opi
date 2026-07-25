"""Tests for revision ownership rules.

Revision must increment exactly once for meaningful authoritative snapshot changes.
Must NOT increment for telemetry-only changes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nightshift.domain.events import HeartbeatReceived, PanelConnectivityChanged
from nightshift.domain.models import (
    AttentionFlag,
    PanelTelemetry,
    SystemMode,
    SystemState,
    WorkState,
)
from nightshift.domain.pressure import PressureState


def _base_state(
    revision: int = 5,
    panel_online: bool = True,
    attention: AttentionFlag = AttentionFlag.NONE,
) -> SystemState:
    return SystemState(
        revision=revision,
        mode=SystemMode.DAY_WORK,
        attention=attention,
        work_state=WorkState.RUNNING,
        pressure=PressureState.empty(),
        panel_online=panel_online,
        confirmation_count=0,
        token_input=0,
        token_output=0,
        updated_at_ms=1000,
    )


def test_telemetry_heartbeat_does_not_bump_revision() -> None:
    state = _base_state(revision=5, panel_online=True)
    new_state = state.evolve(
        panel_telemetry=PanelTelemetry(
            t5_uptime_ms=99999,
            error_flags=0,
            applied_revision=5,
            last_heartbeat_at_ms=2000,
        ),
        bump_revision=False,
    )
    assert new_state.revision == 5


def test_panel_offline_edge_bumps_revision() -> None:
    state = _base_state(revision=5, panel_online=True, attention=AttentionFlag.NONE)
    attention = state.attention | AttentionFlag.PANEL_OFFLINE
    attention_changed = attention != state.attention
    new_state = state.evolve(
        panel_online=False,
        attention=attention,
        bump_revision=attention_changed,
    )
    assert new_state.revision == 6
    assert new_state.attention & AttentionFlag.PANEL_OFFLINE


def test_panel_online_edge_bumps_revision() -> None:
    state = _base_state(
        revision=5,
        panel_online=False,
        attention=AttentionFlag.PANEL_OFFLINE,
    )
    attention = state.attention & ~AttentionFlag.PANEL_OFFLINE
    attention_changed = attention != state.attention
    new_state = state.evolve(
        panel_online=True,
        attention=attention,
        bump_revision=attention_changed,
    )
    assert new_state.revision == 6
    assert not (new_state.attention & AttentionFlag.PANEL_OFFLINE)


def test_repeated_panel_online_does_not_bump_revision() -> None:
    state = _base_state(revision=5, panel_online=True, attention=AttentionFlag.NONE)
    attention = state.attention & ~AttentionFlag.PANEL_OFFLINE
    attention_changed = attention != state.attention
    new_state = state.evolve(
        panel_online=True,
        attention=attention,
        bump_revision=attention_changed,
    )
    assert new_state.revision == 5


def test_mode_change_bumps_revision() -> None:
    state = _base_state(revision=5)
    new_state = state.evolve(mode=SystemMode.NIGHT_EXEC, bump_revision=True)
    assert new_state.revision == 6


def test_attention_content_change_bumps_revision() -> None:
    state = _base_state(revision=5, attention=AttentionFlag.NONE)
    new_state = state.evolve(
        attention=AttentionFlag.NEED_CONFIRM,
        bump_revision=True,
    )
    assert new_state.revision == 6


def test_one_revision_per_snapshot_change() -> None:
    state = _base_state(revision=5)
    new_state = state.evolve(
        mode=SystemMode.NIGHT_EXEC,
        attention=AttentionFlag.NONE,
        bump_revision=True,
    )
    assert new_state.revision == 6
