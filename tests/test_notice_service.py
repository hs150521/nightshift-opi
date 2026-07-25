"""Tests for notice service."""

import pytest

from nightshift.persistence.database import Database
from nightshift.services.notice_service import NoticeService


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def svc(db):
    return NoticeService(db)


async def test_create_notice(svc):
    notice = await svc.create(title="Alert", body="Something happened", now_ms=1000)
    assert notice.id == 1
    assert notice.title == "Alert"
    assert notice.dismissed_at_ms is None


async def test_dismiss_notice(svc):
    notice = await svc.create(title="Alert", now_ms=1000)
    dismissed = await svc.dismiss(notice.id, now_ms=2000)
    assert dismissed is not None
    assert dismissed.dismissed_at_ms == 2000


async def test_dismiss_already_dismissed_returns_none(svc):
    notice = await svc.create(title="Alert", now_ms=1000)
    await svc.dismiss(notice.id, now_ms=2000)
    result = await svc.dismiss(notice.id, now_ms=3000)
    assert result is None


async def test_get_returns_none_for_missing(svc):
    assert await svc.get(999) is None


async def test_count_active(svc):
    await svc.create(title="A", now_ms=1000)
    n2 = await svc.create(title="B", now_ms=2000)
    await svc.create(title="C", now_ms=3000)
    await svc.dismiss(n2.id, now_ms=4000)
    assert await svc.count_active() == 2


async def test_ids_never_reused(svc):
    n1 = await svc.create(title="A", now_ms=1000)
    n2 = await svc.create(title="B", now_ms=2000)
    assert n2.id > n1.id


async def test_latest_active_skips_dismissed_and_expired(svc):
    await svc.create(title="Expired", expires_at_ms=1500, now_ms=1000)
    dismissed = await svc.create(title="Dismissed", now_ms=2000)
    await svc.dismiss(dismissed.id, now_ms=2500)
    current = await svc.create(title="Current", expires_at_ms=5000, now_ms=3000)

    assert await svc.latest_active(now_ms=4000) == current
    assert await svc.latest_active(now_ms=6000) is None
