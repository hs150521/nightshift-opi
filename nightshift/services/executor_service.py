"""Executor service: manages work state lifecycle."""

from __future__ import annotations

import structlog

from nightshift.domain.models import WorkState

logger = structlog.get_logger()

_VALID_TRANSITIONS: dict[WorkState, set[WorkState]] = {
    WorkState.STOPPED: {WorkState.STARTING},
    WorkState.STARTING: {WorkState.RUNNING, WorkState.FAILED},
    WorkState.RUNNING: {WorkState.PAUSED, WorkState.COMPLETED, WorkState.FAILED},
    WorkState.PAUSED: {WorkState.RUNNING, WorkState.STOPPED},
    WorkState.COMPLETED: {WorkState.STOPPED},
    WorkState.FAILED: {WorkState.STOPPED, WorkState.STARTING},
}


class ExecutorError(Exception):
    pass


class ExecutorService:
    def __init__(self) -> None:
        self._state = WorkState.STOPPED

    @property
    def state(self) -> WorkState:
        return self._state

    def pause(self) -> WorkState:
        return self._transition(WorkState.PAUSED)

    def resume(self) -> WorkState:
        return self._transition(WorkState.RUNNING)

    def start(self) -> WorkState:
        return self._transition(WorkState.STARTING)

    def mark_running(self) -> WorkState:
        return self._transition(WorkState.RUNNING)

    def complete(self) -> WorkState:
        return self._transition(WorkState.COMPLETED)

    def fail(self) -> WorkState:
        return self._transition(WorkState.FAILED)

    def stop(self) -> WorkState:
        return self._transition(WorkState.STOPPED)

    def _transition(self, target: WorkState) -> WorkState:
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if target not in allowed:
            raise ExecutorError(
                f"invalid transition: {self._state.value} -> {target.value}"
            )
        previous = self._state
        self._state = target
        logger.info("executor_transition", previous=previous.value, current=target.value)
        return self._state
