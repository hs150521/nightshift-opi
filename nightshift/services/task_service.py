"""Task service: CRUD and state transitions for tasks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from nightshift.persistence.database import Database

logger = structlog.get_logger()


class TaskState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Task:
    id: int
    quadrant: int
    state: TaskState
    flags: int
    title: str
    source: str
    created_at_ms: int
    updated_at_ms: int


class TaskService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        quadrant: int,
        title: str,
        source: str = "",
        flags: int = 0,
        now_ms: int,
    ) -> Task:
        conn = self._db.connection
        cursor = await conn.execute(
            "INSERT INTO tasks (quadrant, state, flags, title, source, created_at_ms, updated_at_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (quadrant, TaskState.PENDING, flags, title, source, now_ms, now_ms),
        )
        await conn.commit()
        task = Task(
            id=cursor.lastrowid,  # type: ignore[arg-type]
            quadrant=quadrant,
            state=TaskState.PENDING,
            flags=flags,
            title=title,
            source=source,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        logger.info("task_created", task_id=task.id, title=title)
        return task

    async def get(self, task_id: int) -> Task | None:
        conn = self._db.connection
        async with conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return self._row_to_task(row)

    async def confirm(self, task_id: int, *, now_ms: int) -> Task | None:
        return await self._transition(task_id, TaskState.PENDING, TaskState.ACTIVE, now_ms)

    async def reject(self, task_id: int, *, now_ms: int) -> Task | None:
        return await self._transition(task_id, TaskState.PENDING, TaskState.COMPLETED, now_ms)

    async def complete(self, task_id: int, *, now_ms: int) -> Task | None:
        return await self._transition(task_id, TaskState.ACTIVE, TaskState.COMPLETED, now_ms)

    async def fail(self, task_id: int, *, now_ms: int) -> Task | None:
        return await self._transition(task_id, TaskState.ACTIVE, TaskState.FAILED, now_ms)

    async def retry(self, task_id: int, *, now_ms: int) -> Task | None:
        return await self._transition(task_id, TaskState.FAILED, TaskState.PENDING, now_ms)

    async def count_pending(self) -> int:
        conn = self._db.connection
        async with conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE state = ?", (TaskState.PENDING,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def _transition(
        self, task_id: int, from_state: TaskState, to_state: TaskState, now_ms: int
    ) -> Task | None:
        conn = self._db.connection
        cursor = await conn.execute(
            "UPDATE tasks SET state = ?, updated_at_ms = ? WHERE id = ? AND state = ?",
            (to_state, now_ms, task_id, from_state),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get(task_id)

    @staticmethod
    def _row_to_task(row: object) -> Task:
        return Task(
            id=row["id"],  # type: ignore[index]
            quadrant=row["quadrant"],  # type: ignore[index]
            state=TaskState(row["state"]),  # type: ignore[index]
            flags=row["flags"],  # type: ignore[index]
            title=row["title"],  # type: ignore[index]
            source=row["source"],  # type: ignore[index]
            created_at_ms=row["created_at_ms"],  # type: ignore[index]
            updated_at_ms=row["updated_at_ms"],  # type: ignore[index]
        )
