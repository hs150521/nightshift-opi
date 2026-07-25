"""Tests for SQLite database layer."""

import pytest

from nightshift.persistence.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


async def test_database_opens_with_wal_mode(db):
    async with db.connection.execute("PRAGMA journal_mode") as cur:
        row = await cur.fetchone()
    assert row[0] == "wal"


async def test_migration_creates_tables(db):
    tables = []
    async with db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        async for row in cur:
            tables.append(row[0])
    assert "tasks" in tables
    assert "notices" in tables
    assert "confirmations" in tables
    assert "schema_version" in tables


async def test_schema_version_is_zero(db):
    async with db.connection.execute("SELECT version FROM schema_version") as cur:
        row = await cur.fetchone()
    assert row[0] == 0


async def test_reopen_does_not_remigrate(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.open()
    await db.connection.execute(
        "INSERT INTO tasks (quadrant, state, title, created_at_ms, updated_at_ms)"
        " VALUES (0, 'pending', 'x', 1000, 1000)"
    )
    await db.connection.commit()
    await db.close()

    db2 = Database(tmp_path / "test.db")
    await db2.open()
    async with db2.connection.execute("SELECT COUNT(*) FROM tasks") as cur:
        row = await cur.fetchone()
    assert row[0] == 1
    await db2.close()
