"""End-to-end integration test: full system wiring without real hardware.

Verifies that the orchestrator, database, services, pressure adapter, and
MQTT command handler all wire together correctly and produce correct state
transitions through the full lifecycle.
"""

import time

import pytest

from nightshift.domain.commands import (
    ACTION_CONFIRM,
    ACTION_DISMISS_NOTICE,
    ACTION_PAUSE_EXECUTION,
    ACTION_REJECT,
    ACTION_REQUEST_RESYNC,
    ACTION_RESUME_EXECUTION,
    ACTION_RETRY,
    NOT_FOUND,
    OBJ_NOTICE,
    OBJ_TASK,
    OK,
)
from nightshift.domain.events import DomainEvent, ModeChanged, UiAction
from nightshift.domain.models import AttentionFlag, SystemMode, WorkState
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.persistence.database import Database
from nightshift.services.orchestrator import NightshiftOrchestrator


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "nightshift.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def pressure():
    return MockPressureSource()


@pytest.fixture
def orchestrator(pressure, db):
    config = UartConfig(device="/dev/null", baudrate=460800)
    return NightshiftOrchestrator(
        pressure_source=pressure,
        uart_config=config,
        db=db,
        dwell_ms=100,
        stale_ms=500,
    )


def _ui(action, obj_type=0, obj_id=0):
    return UiAction(action=action, object_type=obj_type, object_id=obj_id, value=0, text="")


async def test_full_lifecycle_pressure_to_mode(orchestrator, pressure):
    """Pressure mock → state machine → mode transitions."""
    assert orchestrator.state.mode == SystemMode.IDLE
    assert AttentionFlag.SENSOR_ERROR in orchestrator.state.attention

    now_ms = int(time.monotonic() * 1000)
    pressure.go_online()
    pressure.push(now_ms=now_ms, cushion=True, footrest=False)
    await orchestrator.on_pressure_updated()
    assert orchestrator.state.mode == SystemMode.DAY_WORK
    assert AttentionFlag.SENSOR_ERROR not in orchestrator.state.attention

    now_ms = int(time.monotonic() * 1000)
    pressure.push(now_ms=now_ms, cushion=False, footrest=False)
    await orchestrator.on_pressure_updated()
    assert orchestrator.state.mode == SystemMode.IDLE


async def test_task_confirm_reject_lifecycle(orchestrator):
    """Create tasks, confirm one, reject another, check counts."""
    task_svc = orchestrator._task_service

    t1 = await task_svc.create(quadrant=0, title="Task 1", now_ms=1000)
    t2 = await task_svc.create(quadrant=1, title="Task 2", now_ms=2000)

    status, _ = await orchestrator._handle_ui_action(
        _ui(ACTION_CONFIRM, OBJ_TASK, t1.id)
    )
    assert status == OK
    assert orchestrator.state.confirmation_count == 1
    assert AttentionFlag.NEED_CONFIRM in orchestrator.state.attention

    status, _ = await orchestrator._handle_ui_action(
        _ui(ACTION_REJECT, OBJ_TASK, t2.id)
    )
    assert status == OK
    assert orchestrator.state.confirmation_count == 0
    assert AttentionFlag.NEED_CONFIRM not in orchestrator.state.attention


async def test_task_retry_lifecycle(orchestrator):
    """Failed task can be retried, returning to pending."""
    task_svc = orchestrator._task_service
    t = await task_svc.create(quadrant=0, title="Flaky", now_ms=1000)
    await task_svc.confirm(t.id, now_ms=2000)
    await task_svc.fail(t.id, now_ms=3000)

    status, _ = await orchestrator._handle_ui_action(
        _ui(ACTION_RETRY, OBJ_TASK, t.id)
    )
    assert status == OK
    assert orchestrator.state.confirmation_count == 1


async def test_notice_dismiss_lifecycle(orchestrator):
    """Create and dismiss a notice via UI action."""
    notice_svc = orchestrator._notice_service
    n = await notice_svc.create(title="Heads up", now_ms=1000)

    status, _ = await orchestrator._handle_ui_action(
        _ui(ACTION_DISMISS_NOTICE, OBJ_NOTICE, n.id)
    )
    assert status == OK

    status, _ = await orchestrator._handle_ui_action(
        _ui(ACTION_DISMISS_NOTICE, OBJ_NOTICE, n.id)
    )
    assert status == NOT_FOUND


async def test_executor_pause_resume(orchestrator):
    """Executor transitions require valid starting state."""
    orchestrator._executor_service.start()
    orchestrator._executor_service.mark_running()
    orchestrator._state = orchestrator._state.evolve(
        work_state=WorkState.RUNNING,
        updated_at_ms=1000,
    )

    await orchestrator.pause_executor()
    assert orchestrator.state.work_state == WorkState.PAUSED

    await orchestrator.resume_executor()
    assert orchestrator.state.work_state == WorkState.RUNNING


async def test_executor_invalid_pause_from_stopped(orchestrator):
    """Pause from STOPPED does nothing (invalid transition)."""
    assert orchestrator.state.work_state == WorkState.STOPPED
    await orchestrator.pause_executor()
    assert orchestrator.state.work_state == WorkState.STOPPED


async def test_event_listener_receives_mode_change(orchestrator, pressure):
    """Event listeners receive ModeChanged events."""
    events: list[DomainEvent] = []

    async def capture(event: DomainEvent) -> None:
        events.append(event)

    orchestrator.register_event_listener(capture)

    now_ms = int(time.monotonic() * 1000)
    pressure.go_online()
    pressure.push(now_ms=now_ms, cushion=True, footrest=False)
    await orchestrator.on_pressure_updated()

    mode_events = [e for e in events if isinstance(e, ModeChanged)]
    assert len(mode_events) == 1
    assert mode_events[0].current == SystemMode.DAY_WORK


async def test_database_survives_restart(tmp_path, pressure):
    """Tasks persist across orchestrator restarts."""
    config = UartConfig(device="/dev/null", baudrate=460800)

    db1 = Database(tmp_path / "nightshift.db")
    await db1.open()
    orch1 = NightshiftOrchestrator(pressure, config, db=db1)
    await orch1._task_service.create(quadrant=0, title="Persistent", now_ms=1000)
    await db1.close()

    db2 = Database(tmp_path / "nightshift.db")
    await db2.open()
    orch2 = NightshiftOrchestrator(pressure, config, db=db2)
    task = await orch2._task_service.get(1)
    assert task is not None
    assert task.title == "Persistent"
    await db2.close()


async def test_revision_increments_on_confirmation(orchestrator):
    """Each confirmation action bumps revision exactly once."""
    task_svc = orchestrator._task_service
    t = await task_svc.create(quadrant=0, title="X", now_ms=1000)
    rev_before = orchestrator.state.revision
    await orchestrator._handle_ui_action(_ui(ACTION_CONFIRM, OBJ_TASK, t.id))
    assert orchestrator.state.revision == rev_before + 1
