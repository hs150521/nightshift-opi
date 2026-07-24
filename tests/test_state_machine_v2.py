"""Tests for the v2 state machine (pressure + 3 s all-released dwell)."""

from __future__ import annotations

from nightshift.domain.models import AttentionFlag, SystemMode
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.domain.state_machine_v2 import StateMachineV2


def test_idle_when_pressure_offline() -> None:
    src = MockPressureSource()
    src.go_offline()
    sm = StateMachineV2()

    decision = sm.evaluate(src.snapshot(), now_ms=0)

    assert decision.mode is SystemMode.IDLE
    assert decision.reason == "pressure_offline"
    assert decision.attention & AttentionFlag.SENSOR_ERROR


def test_idle_when_pressure_online_but_no_sample_yet() -> None:
    src = MockPressureSource()
    src.go_online()
    sm = StateMachineV2()

    decision = sm.evaluate(src.snapshot(), now_ms=0)

    assert decision.mode is SystemMode.IDLE
    assert decision.attention & AttentionFlag.SENSOR_ERROR


def test_idle_when_pressure_stale() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=True, footrest=False)
    sm = StateMachineV2()

    # 10 s later, no new sample: sample age > STALE_MS.
    decision = sm.evaluate(src.snapshot(), now_ms=10_001)

    assert decision.mode is SystemMode.IDLE
    assert decision.reason == "pressure_stale"
    assert decision.attention & AttentionFlag.SENSOR_ERROR


def test_cushion_maps_to_day_work() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=True, footrest=False)
    sm = StateMachineV2()

    decision = sm.evaluate(src.snapshot(), now_ms=0)

    assert decision.mode is SystemMode.DAY_WORK
    assert decision.reason == "cushion_pressed"
    assert decision.attention == AttentionFlag.NONE


def test_footrest_only_maps_to_day_work() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=True)
    sm = StateMachineV2()

    decision = sm.evaluate(src.snapshot(), now_ms=0)

    assert decision.mode is SystemMode.DAY_WORK
    assert decision.reason == "footrest_pressed"


def test_all_released_below_dwell_stays_idle() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()

    # First evaluation: start dwell timer.
    d1 = sm.evaluate(src.snapshot(), now_ms=0)
    # After 2.9 s: still IDLE.
    d2 = sm.evaluate(src.snapshot(), now_ms=2_900)

    assert d1.mode is SystemMode.IDLE
    assert d1.reason == "all_released_pending_dwell"
    assert d2.mode is SystemMode.IDLE
    assert d2.reason == "all_released_pending_dwell"


def test_all_released_after_dwell_enters_night_exec() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()

    sm.evaluate(src.snapshot(), now_ms=0)
    decision = sm.evaluate(src.snapshot(), now_ms=3_000)

    assert decision.mode is SystemMode.NIGHT_EXEC
    assert decision.reason == "all_released_dwell"


def test_pressure_during_dwell_cancels_night_exec() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()
    sm.evaluate(src.snapshot(), now_ms=0)

    # 1.5 s in, user sits back down.
    src.push(now_ms=1_500, cushion=True, footrest=False)
    d_sit = sm.evaluate(src.snapshot(), now_ms=1_500)

    # User releases again at 2 s. Dwell must restart.
    src.push(now_ms=2_000, cushion=False, footrest=False)
    d_release = sm.evaluate(src.snapshot(), now_ms=2_000)
    d_early = sm.evaluate(src.snapshot(), now_ms=4_500)  # 2.5 s after new release
    d_final = sm.evaluate(src.snapshot(), now_ms=5_000)  # 3 s after new release

    assert d_sit.mode is SystemMode.DAY_WORK
    assert d_release.mode is SystemMode.IDLE
    assert d_early.mode is SystemMode.IDLE
    assert d_final.mode is SystemMode.NIGHT_EXEC


def test_offline_never_maps_to_night_exec() -> None:
    """Frozen rule: never map 'offline' to 'all released'."""
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()
    sm.evaluate(src.snapshot(), now_ms=0)

    src.go_offline()
    decision = sm.evaluate(src.snapshot(), now_ms=5_000)

    assert decision.mode is SystemMode.IDLE
    assert decision.reason == "pressure_offline"


def test_stale_resets_dwell() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()
    sm.evaluate(src.snapshot(), now_ms=0)

    # Sample goes stale at 10 001 ms — no new sample arrives.
    stale = sm.evaluate(src.snapshot(), now_ms=10_001)
    # New all-released sample: dwell must restart from now, not from 0.
    src.push(now_ms=10_500, cushion=False, footrest=False)
    resumed = sm.evaluate(src.snapshot(), now_ms=10_500)
    still_pending = sm.evaluate(src.snapshot(), now_ms=13_000)
    completes = sm.evaluate(src.snapshot(), now_ms=13_500)

    assert stale.mode is SystemMode.IDLE
    assert resumed.mode is SystemMode.IDLE
    assert resumed.reason == "all_released_pending_dwell"
    assert still_pending.mode is SystemMode.IDLE
    assert completes.mode is SystemMode.NIGHT_EXEC


def test_night_exec_to_day_work_is_immediate() -> None:
    src = MockPressureSource()
    src.push(now_ms=0, cushion=False, footrest=False)
    sm = StateMachineV2()
    sm.evaluate(src.snapshot(), now_ms=0)
    assert sm.evaluate(src.snapshot(), now_ms=3_500).mode is SystemMode.NIGHT_EXEC

    # User sits down at 4 s — must flip to DAY_WORK immediately.
    src.push(now_ms=4_000, cushion=True, footrest=False)
    decision = sm.evaluate(src.snapshot(), now_ms=4_000)

    assert decision.mode is SystemMode.DAY_WORK
    assert decision.reason == "cushion_pressed"
