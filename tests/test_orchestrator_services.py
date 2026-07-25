"""Tests for orchestrator UI action routing with real services."""

import struct

import pytest

from nightshift.domain.commands import (
    ACTION_CONFIRM,
    ACTION_DISMISS_NOTICE,
    ACTION_REJECT,
    ACTION_RETRY,
    ATTENTION_SET,
    DASHBOARD_SET,
    MODE_SET,
    NOT_FOUND,
    NOT_READY,
    NOTICE_SHOW,
    OBJ_NOTICE,
    OBJ_TASK,
    OK,
    STATE_SYNC_BEGIN,
    STATE_SYNC_END,
    TASK_ITEM,
    TASK_LIST_BEGIN,
    TASK_LIST_END,
    WORK_STATE_SET,
)
from nightshift.domain.events import UiAction
from nightshift.domain.models import AttentionFlag
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.persistence.database import Database
from nightshift.services.orchestrator import NightshiftOrchestrator
from nightshift.services.task_service import TaskState


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def orchestrator(db):
    pressure = MockPressureSource()
    config = UartConfig(device="/dev/null", baudrate=460800)
    orch = NightshiftOrchestrator(pressure, config, db=db)
    return orch


def _ui_action(action, object_type=0, object_id=0):
    return UiAction(action=action, object_type=object_type, object_id=object_id, value=0, text="")


async def test_confirm_task_returns_ok(orchestrator, db):
    task_svc = orchestrator._task_service
    task = await task_svc.create(quadrant=0, title="Test", now_ms=1000)
    event = _ui_action(ACTION_CONFIRM, OBJ_TASK, task.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == OK
    updated = await task_svc.get(task.id)
    assert updated.state == TaskState.ACTIVE


async def test_confirm_updates_confirmation_count(orchestrator, db):
    task_svc = orchestrator._task_service
    await task_svc.create(quadrant=0, title="A", now_ms=1000)
    t2 = await task_svc.create(quadrant=0, title="B", now_ms=2000)
    event = _ui_action(ACTION_CONFIRM, OBJ_TASK, t2.id)
    await orchestrator._handle_ui_action(event)
    assert orchestrator.state.confirmation_count == 1
    assert AttentionFlag.NEED_CONFIRM in orchestrator.state.attention


async def test_confirm_clears_need_confirm_when_all_resolved(orchestrator, db):
    task_svc = orchestrator._task_service
    t1 = await task_svc.create(quadrant=0, title="Only", now_ms=1000)
    event = _ui_action(ACTION_CONFIRM, OBJ_TASK, t1.id)
    await orchestrator._handle_ui_action(event)
    assert orchestrator.state.confirmation_count == 0
    assert AttentionFlag.NEED_CONFIRM not in orchestrator.state.attention


async def test_reject_task_returns_ok(orchestrator, db):
    task_svc = orchestrator._task_service
    task = await task_svc.create(quadrant=0, title="Test", now_ms=1000)
    event = _ui_action(ACTION_REJECT, OBJ_TASK, task.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == OK


async def test_confirm_nonexistent_returns_not_found(orchestrator):
    event = _ui_action(ACTION_CONFIRM, OBJ_TASK, 999)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == NOT_FOUND


async def test_retry_failed_task_returns_ok(orchestrator, db):
    task_svc = orchestrator._task_service
    task = await task_svc.create(quadrant=0, title="Test", now_ms=1000)
    await task_svc.confirm(task.id, now_ms=2000)
    await task_svc.fail(task.id, now_ms=3000)
    event = _ui_action(ACTION_RETRY, OBJ_TASK, task.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == OK
    updated = await task_svc.get(task.id)
    assert updated.state == TaskState.PENDING


async def test_retry_non_failed_returns_not_found(orchestrator, db):
    task_svc = orchestrator._task_service
    task = await task_svc.create(quadrant=0, title="Test", now_ms=1000)
    event = _ui_action(ACTION_RETRY, OBJ_TASK, task.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == NOT_FOUND


async def test_dismiss_notice_returns_ok(orchestrator, db):
    notice_svc = orchestrator._notice_service
    notice = await notice_svc.create(title="Alert", now_ms=1000)
    event = _ui_action(ACTION_DISMISS_NOTICE, OBJ_NOTICE, notice.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == OK
    updated = await notice_svc.get(notice.id)
    assert updated.dismissed_at_ms is not None


async def test_dismiss_already_dismissed_returns_not_found(orchestrator, db):
    notice_svc = orchestrator._notice_service
    notice = await notice_svc.create(title="Alert", now_ms=1000)
    await notice_svc.dismiss(notice.id, now_ms=2000)
    event = _ui_action(ACTION_DISMISS_NOTICE, OBJ_NOTICE, notice.id)
    status, _ = await orchestrator._handle_ui_action(event)
    assert status == NOT_FOUND


async def test_no_db_returns_not_ready():
    pressure = MockPressureSource()
    config = UartConfig(device="/dev/null", baudrate=460800)
    orch = NightshiftOrchestrator(pressure, config)
    event = _ui_action(ACTION_CONFIRM, OBJ_TASK, 1)
    status, _ = await orch._handle_ui_action(event)
    assert status == NOT_READY


async def test_full_sync_sends_database_snapshot(orchestrator, db):
    task_svc = orchestrator._task_service
    notice_svc = orchestrator._notice_service
    await task_svc.create(quadrant=2, title="Approve", source="test", now_ms=1000)
    await notice_svc.create(title="Heads up", body="Review", now_ms=2000)
    sent = []

    async def capture(command, payload=b"", **kwargs):
        sent.append((command, payload))
        return b""

    orchestrator._uart.send = capture
    await orchestrator._full_sync()

    assert [command for command, _ in sent] == [
        STATE_SYNC_BEGIN,
        MODE_SET,
        ATTENTION_SET,
        WORK_STATE_SET,
        DASHBOARD_SET,
        NOTICE_SHOW,
        TASK_LIST_BEGIN,
        TASK_ITEM,
        TASK_LIST_END,
        STATE_SYNC_END,
    ]
    assert orchestrator.dashboard.urgent_confirm == 1


async def test_full_sync_explicitly_clears_notice(orchestrator):
    sent = []

    async def capture(command, payload=b"", **kwargs):
        sent.append((command, payload))
        return b""

    orchestrator._uart.send = capture
    await orchestrator._full_sync()

    notice_payload = next(payload for command, payload in sent if command == NOTICE_SHOW)
    revision, notice_id, severity, flags, expires_at_ms = struct.unpack(
        "<IIBBQ", notice_payload[:18]
    )
    assert revision == orchestrator.state.revision
    assert notice_id == 0
    assert severity == 0
    assert flags == 0
    assert expires_at_ms == 0
    assert notice_payload[18:] == b"\x00\x00\x00\x00"


async def test_full_sync_does_not_commit_partial_snapshot(orchestrator):
    sent = []

    async def fail_on_attention(command, payload=b"", **kwargs):
        sent.append(command)
        if command == ATTENTION_SET:
            raise OSError("link lost")
        return b""

    orchestrator._uart.send = fail_on_attention
    await orchestrator._full_sync()

    assert sent == [STATE_SYNC_BEGIN, MODE_SET, ATTENTION_SET]
    assert STATE_SYNC_END not in sent
