"""Tests for confirmation service."""

import pytest

from nightshift.domain.commands import OBJ_NOTICE, OBJ_TASK
from nightshift.persistence.database import Database
from nightshift.services.confirmation_service import ConfirmationError, ConfirmationService
from nightshift.services.notice_service import NoticeService
from nightshift.services.task_service import TaskService, TaskState


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def task_svc(db):
    return TaskService(db)


@pytest.fixture
def notice_svc(db):
    return NoticeService(db)


@pytest.fixture
def svc(db, task_svc, notice_svc):
    return ConfirmationService(db, task_svc, notice_svc)


async def test_confirm_task_transitions_and_records(svc, task_svc):
    task = await task_svc.create(quadrant=0, title="X", now_ms=1000)
    result = await svc.confirm(OBJ_TASK, task.id, now_ms=2000)
    assert result.decision == "confirmed"
    assert result.pending_count == 0
    updated = await task_svc.get(task.id)
    assert updated.state == TaskState.ACTIVE


async def test_reject_task_transitions_and_records(svc, task_svc):
    task = await task_svc.create(quadrant=0, title="X", now_ms=1000)
    result = await svc.reject(OBJ_TASK, task.id, now_ms=2000)
    assert result.decision == "rejected"
    updated = await task_svc.get(task.id)
    assert updated.state == TaskState.COMPLETED


async def test_confirm_nonexistent_task_raises(svc):
    with pytest.raises(ConfirmationError):
        await svc.confirm(OBJ_TASK, 999, now_ms=1000)


async def test_confirm_notice_dismisses_it(svc, notice_svc):
    notice = await notice_svc.create(title="Alert", now_ms=1000)
    result = await svc.confirm(OBJ_NOTICE, notice.id, now_ms=2000)
    assert result.decision == "confirmed"
    updated = await notice_svc.get(notice.id)
    assert updated.dismissed_at_ms == 2000


async def test_reject_notice_dismisses_it(svc, notice_svc):
    notice = await notice_svc.create(title="Alert", now_ms=1000)
    result = await svc.reject(OBJ_NOTICE, notice.id, now_ms=2000)
    assert result.decision == "rejected"


async def test_unsupported_object_type_raises(svc):
    with pytest.raises(ConfirmationError, match="unsupported"):
        await svc.confirm(99, 1, now_ms=1000)


async def test_pending_count_reflects_remaining(svc, task_svc):
    await task_svc.create(quadrant=0, title="A", now_ms=1000)
    t2 = await task_svc.create(quadrant=0, title="B", now_ms=2000)
    result = await svc.confirm(OBJ_TASK, t2.id, now_ms=3000)
    assert result.pending_count == 1


async def test_confirmation_persisted_in_table(svc, task_svc, db):
    task = await task_svc.create(quadrant=0, title="X", now_ms=1000)
    await svc.confirm(OBJ_TASK, task.id, now_ms=2000)
    async with db.connection.execute("SELECT COUNT(*) FROM confirmations") as cur:
        row = await cur.fetchone()
    assert row[0] == 1
