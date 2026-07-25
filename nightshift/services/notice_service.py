"""Notice service: CRUD and dismissal for notices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from nightshift.persistence.database import Database

logger = structlog.get_logger()


@dataclass(frozen=True)
class Notice:
    id: int
    flags: int
    title: str
    body: str
    expires_at_ms: int | None
    created_at_ms: int
    dismissed_at_ms: int | None


class NoticeService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        title: str,
        body: str = "",
        flags: int = 0,
        expires_at_ms: int | None = None,
        now_ms: int,
    ) -> Notice:
        conn = self._db.connection
        cursor = await conn.execute(
            "INSERT INTO notices (flags, title, body, expires_at_ms, created_at_ms)"
            " VALUES (?, ?, ?, ?, ?)",
            (flags, title, body, expires_at_ms, now_ms),
        )
        await conn.commit()
        notice = Notice(
            id=cursor.lastrowid,  # type: ignore[arg-type]
            flags=flags,
            title=title,
            body=body,
            expires_at_ms=expires_at_ms,
            created_at_ms=now_ms,
            dismissed_at_ms=None,
        )
        logger.info("notice_created", notice_id=notice.id, title=title)
        return notice

    async def get(self, notice_id: int) -> Notice | None:
        conn = self._db.connection
        async with conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return self._row_to_notice(row)

    async def dismiss(self, notice_id: int, *, now_ms: int) -> Notice | None:
        conn = self._db.connection
        cursor = await conn.execute(
            "UPDATE notices SET dismissed_at_ms = ? WHERE id = ? AND dismissed_at_ms IS NULL",
            (now_ms, notice_id),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get(notice_id)

    async def count_active(self) -> int:
        conn = self._db.connection
        async with conn.execute(
            "SELECT COUNT(*) FROM notices WHERE dismissed_at_ms IS NULL"
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def latest_active(self, *, now_ms: int) -> Notice | None:
        """Return the newest non-dismissed, non-expired notice."""
        conn = self._db.connection
        async with conn.execute(
            "SELECT * FROM notices"
            " WHERE dismissed_at_ms IS NULL"
            " AND (expires_at_ms IS NULL OR expires_at_ms > ?)"
            " ORDER BY created_at_ms DESC, id DESC LIMIT 1",
            (now_ms,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_notice(row) if row is not None else None

    @staticmethod
    def _row_to_notice(row: object) -> Notice:
        return Notice(
            id=row["id"],  # type: ignore[index]
            flags=row["flags"],  # type: ignore[index]
            title=row["title"],  # type: ignore[index]
            body=row["body"],  # type: ignore[index]
            expires_at_ms=row["expires_at_ms"],  # type: ignore[index]
            created_at_ms=row["created_at_ms"],  # type: ignore[index]
            dismissed_at_ms=row["dismissed_at_ms"],  # type: ignore[index]
        )
