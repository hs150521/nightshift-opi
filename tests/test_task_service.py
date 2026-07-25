"""Tests for task service."""

import pytest

from nightshift.persistence.database import Database
from nightshift.services.task_service import TaskService, TaskState


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def svc(db):
    return TaskService(db)


async def test_create_task(svc):
    task = await svc.create(quadrant=0, title="Test task", source="test", now_ms=1000)
    assert task.id == 1
    assert task.state == TaskState.PENDING
    assert task.title == "Test task"
    assert task.created_at_ms == 1000


async def test_ids_never_reused(svc):
    t1 = await svc.create(quadrant=0, title="A", now_ms=1000)
    t2 = await svc.create(quadrant=0, title="B", now_ms=2000)
    assert t2.id > t1.id


async def test_get_returns_none_for_missing(svc):
    assert await svc.get(999) is None


async def test_confirm_transitions_pending_to_active(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    confirmed = await svc.confirm(task.id, now_ms=2000)
    assert confirmed is not None
    assert confirmed.state == TaskState.ACTIVE
    assert confirmed.updated_at_ms == 2000


async def test_confirm_fails_if_not_pending(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    await svc.confirm(task.id, now_ms=2000)
    result = await svc.confirm(task.id, now_ms=3000)
    assert result is None


async def test_reject_transitions_pending_to_completed(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    rejected = await svc.reject(task.id, now_ms=2000)
    assert rejected is not None
    assert rejected.state == TaskState.COMPLETED


async def test_retry_transitions_failed_to_pending(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    await svc.confirm(task.id, now_ms=2000)
    await svc.fail(task.id, now_ms=3000)
    retried = await svc.retry(task.id, now_ms=4000)
    assert retried is not None
    assert retried.state == TaskState.PENDING


async def test_retry_fails_if_not_failed(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    result = await svc.retry(task.id, now_ms=2000)
    assert result is None


async def test_complete_transitions_active_to_completed(svc):
    task = await svc.create(quadrant=0, title="X", now_ms=1000)
    await svc.confirm(task.id, now_ms=2000)
    completed = await svc.complete(task.id, now_ms=3000)
    assert completed is not None
    assert completed.state == TaskState.COMPLETED


async def test_count_pending(svc):
    await svc.create(quadrant=0, title="A", now_ms=1000)
    await svc.create(quadrant=0, title="B", now_ms=2000)
    t3 = await svc.create(quadrant=0, title="C", now_ms=3000)
    await svc.confirm(t3.id, now_ms=4000)
    assert await svc.count_pending() == 2
