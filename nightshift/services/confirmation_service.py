"""Confirmation service: records confirm/reject decisions and updates system counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from nightshift.domain.commands import OBJ_NOTICE, OBJ_TASK

if TYPE_CHECKING:
    from nightshift.persistence.database import Database
    from nightshift.services.notice_service import NoticeService
    from nightshift.services.task_service import TaskService

logger = structlog.get_logger()


class ConfirmationError(Exception):
    pass


@dataclass(frozen=True)
class ConfirmationResult:
    object_type: int
    object_id: int
    decision: str
    pending_count: int


class ConfirmationService:
    def __init__(
        self,
        db: Database,
        task_service: TaskService,
        notice_service: NoticeService,
    ) -> None:
        self._db = db
        self._task_service = task_service
        self._notice_service = notice_service

    async def confirm(
        self, object_type: int, object_id: int, *, now_ms: int
    ) -> ConfirmationResult:
        if object_type == OBJ_TASK:
            task = await self._task_service.confirm(object_id, now_ms=now_ms)
            if task is None:
                raise ConfirmationError(f"task {object_id} not in pending state")
        elif object_type == OBJ_NOTICE:
            notice = await self._notice_service.dismiss(object_id, now_ms=now_ms)
            if notice is None:
                raise ConfirmationError(f"notice {object_id} not active")
        else:
            raise ConfirmationError(f"unsupported object_type={object_type}")

        await self._record(object_type, object_id, "confirmed", now_ms)
        pending = await self._task_service.count_pending()
        return ConfirmationResult(
            object_type=object_type,
            object_id=object_id,
            decision="confirmed",
            pending_count=pending,
        )

    async def reject(
        self, object_type: int, object_id: int, *, now_ms: int
    ) -> ConfirmationResult:
        if object_type == OBJ_TASK:
            task = await self._task_service.reject(object_id, now_ms=now_ms)
            if task is None:
                raise ConfirmationError(f"task {object_id} not in pending state")
        elif object_type == OBJ_NOTICE:
            notice = await self._notice_service.dismiss(object_id, now_ms=now_ms)
            if notice is None:
                raise ConfirmationError(f"notice {object_id} not active")
        else:
            raise ConfirmationError(f"unsupported object_type={object_type}")

        await self._record(object_type, object_id, "rejected", now_ms)
        pending = await self._task_service.count_pending()
        return ConfirmationResult(
            object_type=object_type,
            object_id=object_id,
            decision="rejected",
            pending_count=pending,
        )

    async def _record(
        self, object_type: int, object_id: int, decision: str, now_ms: int
    ) -> None:
        conn = self._db.connection
        await conn.execute(
            "INSERT INTO confirmations (object_type, object_id, decision, decided_at_ms)"
            " VALUES (?, ?, ?, ?)",
            (object_type, object_id, decision, now_ms),
        )
        await conn.commit()
        logger.info(
            "confirmation_recorded",
            object_type=object_type,
            object_id=object_id,
            decision=decision,
        )
