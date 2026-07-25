"""Regression coverage for last-known pressure outputs."""

from __future__ import annotations

import json

from nightshift.domain.models import (
    AttentionFlag,
    SystemMode,
    SystemState,
    WorkState,
)
from nightshift.domain.pressure import PressureSample, PressureState
from nightshift.integrations.mqtt.schemas import build_state


def _system_state(pressure: PressureState) -> SystemState:
    return SystemState(
        revision=7,
        mode=SystemMode.IDLE,
        attention=AttentionFlag.SENSOR_ERROR,
        work_state=WorkState.STOPPED,
        pressure=pressure,
        panel_online=True,
        confirmation_count=0,
        token_input=0,
        token_output=0,
        updated_at_ms=20_000,
    )


def _last_sample() -> PressureSample:
    return PressureSample(
        device_id="pressure-01",
        boot_id="boot-1",
        seq=42,
        cushion=True,
        footrest=False,
        present=True,
        uptime_ms=12_000,
        received_at_ms=1_000,
    )


def test_offline_state_serializes_last_known_outputs_as_invalid() -> None:
    pressure = PressureState(
        online=False,
        last_sample=_last_sample(),
        updated_at_ms=20_000,
    )

    payload = json.loads(
        build_state(
            state=_system_state(pressure),
            node_id="opi3b01",
            now_ms=20_000,
            stale_ms=10_000,
        )
    )

    assert payload["pressure"] == {
        "online": False,
        "valid": False,
        "cushion": True,
        "footrest": False,
        "updated_at_ms": 20_000,
        "device_id": "pressure-01",
        "boot_id": "boot-1",
        "seq": 42,
    }


def test_stale_state_serializes_last_known_outputs_as_invalid() -> None:
    pressure = PressureState(
        online=True,
        last_sample=_last_sample(),
        updated_at_ms=1_000,
    )

    payload = json.loads(
        build_state(
            state=_system_state(pressure),
            node_id="opi3b01",
            now_ms=20_000,
            stale_ms=10_000,
        )
    )

    assert payload["pressure"]["online"] is True
    assert payload["pressure"]["valid"] is False
    assert payload["pressure"]["cushion"] is True
    assert payload["pressure"]["footrest"] is False
    assert payload["pressure"]["seq"] == 42
