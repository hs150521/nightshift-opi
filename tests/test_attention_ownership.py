"""Tests for attention ownership: the pressure state machine owns only SENSOR_ERROR."""

from __future__ import annotations

from nightshift.domain.models import AttentionFlag, SystemMode, SystemState, WorkState
from nightshift.domain.pressure import PressureState
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.domain.state_machine import StateMachineV2


def _make_state(attention: AttentionFlag) -> SystemState:
    return SystemState(
        revision=1,
        mode=SystemMode.IDLE,
        attention=attention,
        work_state=WorkState.STOPPED,
        pressure=PressureState.empty(),
        panel_online=False,
        confirmation_count=0,
        token_input=0,
        token_output=0,
        updated_at_ms=0,
    )


def _merge_attention(
    current_attention: AttentionFlag,
    from_state_machine: AttentionFlag,
) -> AttentionFlag:
    """Replicate the orchestrator's _merge_attention logic."""
    preserved = current_attention & ~AttentionFlag.SENSOR_ERROR
    sensor = from_state_machine & AttentionFlag.SENSOR_ERROR
    return preserved | sensor


def test_sensor_error_set_when_machine_says_so() -> None:
    result = _merge_attention(AttentionFlag.NONE, AttentionFlag.SENSOR_ERROR)
    assert result == AttentionFlag.SENSOR_ERROR


def test_sensor_error_cleared_when_machine_clears_it() -> None:
    result = _merge_attention(AttentionFlag.SENSOR_ERROR, AttentionFlag.NONE)
    assert result == AttentionFlag.NONE


def test_need_confirm_preserved_when_sensor_error_set() -> None:
    result = _merge_attention(
        AttentionFlag.NEED_CONFIRM, AttentionFlag.SENSOR_ERROR
    )
    assert result == AttentionFlag.NEED_CONFIRM | AttentionFlag.SENSOR_ERROR


def test_need_confirm_preserved_when_sensor_error_cleared() -> None:
    result = _merge_attention(
        AttentionFlag.NEED_CONFIRM | AttentionFlag.SENSOR_ERROR,
        AttentionFlag.NONE,
    )
    assert result == AttentionFlag.NEED_CONFIRM


def test_panel_offline_preserved_regardless_of_machine() -> None:
    result = _merge_attention(
        AttentionFlag.PANEL_OFFLINE | AttentionFlag.SENSOR_ERROR,
        AttentionFlag.NONE,
    )
    assert result == AttentionFlag.PANEL_OFFLINE


def test_all_non_sensor_bits_preserved() -> None:
    all_others = (
        AttentionFlag.NEED_CONFIRM
        | AttentionFlag.PANEL_OFFLINE
        | AttentionFlag.BACKEND_ERROR
        | AttentionFlag.STORAGE_WARNING
        | AttentionFlag.AGENT_FAILED
        | AttentionFlag.NETWORK_OFFLINE
    )
    result = _merge_attention(all_others, AttentionFlag.SENSOR_ERROR)
    assert result == all_others | AttentionFlag.SENSOR_ERROR

    result2 = _merge_attention(all_others | AttentionFlag.SENSOR_ERROR, AttentionFlag.NONE)
    assert result2 == all_others


def test_state_machine_only_produces_sensor_error_or_none() -> None:
    sm = StateMachineV2()
    src = MockPressureSource()

    src.go_offline()
    d = sm.evaluate(src.snapshot(), now_ms=0)
    assert d.attention in (AttentionFlag.SENSOR_ERROR, AttentionFlag.NONE)

    src.push(now_ms=100, cushion=True, footrest=False)
    d = sm.evaluate(src.snapshot(), now_ms=100)
    assert d.attention in (AttentionFlag.SENSOR_ERROR, AttentionFlag.NONE)

    src.push(now_ms=200, cushion=False, footrest=False)
    d = sm.evaluate(src.snapshot(), now_ms=200)
    assert d.attention in (AttentionFlag.SENSOR_ERROR, AttentionFlag.NONE)
