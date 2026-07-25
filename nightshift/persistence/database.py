"""SQLite database with WAL mode and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger()

_MIGRATIONS: list[str] = [
    # Migration 0: initial schema
    """\
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quadrant INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    flags INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flags INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    dismissed_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type INTEGER NOT NULL,
    object_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    decided_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version) VALUES (0);
""",
]


class Database:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._db: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("database not open")
        return self._db

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._path))
        self._db.row_factory = sqlite3.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._migrate()
        logger.info("database_opened", path=str(self._path))

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _migrate(self) -> None:
        db = self.connection
        current = await self._current_version()
        for i in range(current + 1, len(_MIGRATIONS)):
            await db.executescript(_MIGRATIONS[i])
            await db.execute("UPDATE schema_version SET version = ?", (i,))
            await db.commit()
            logger.info("database_migrated", version=i)

    async def _current_version(self) -> int:
        db = self.connection
        try:
            async with db.execute("SELECT version FROM schema_version") as cur:
                row = await cur.fetchone()
                return row[0] if row else -1
        except aiosqlite.OperationalError:
            return -1
