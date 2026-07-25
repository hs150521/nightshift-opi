"""Tests for executor service."""

import pytest

from nightshift.domain.models import WorkState
from nightshift.services.executor_service import ExecutorError, ExecutorService


def test_initial_state_is_stopped():
    svc = ExecutorService()
    assert svc.state == WorkState.STOPPED


def test_pause_from_running():
    svc = ExecutorService()
    svc.start()
    svc.mark_running()
    result = svc.pause()
    assert result == WorkState.PAUSED


def test_resume_from_paused():
    svc = ExecutorService()
    svc.start()
    svc.mark_running()
    svc.pause()
    result = svc.resume()
    assert result == WorkState.RUNNING


def test_pause_from_stopped_raises():
    svc = ExecutorService()
    with pytest.raises(ExecutorError):
        svc.pause()


def test_resume_from_stopped_raises():
    svc = ExecutorService()
    with pytest.raises(ExecutorError):
        svc.resume()


def test_full_lifecycle():
    svc = ExecutorService()
    svc.start()
    assert svc.state == WorkState.STARTING
    svc.mark_running()
    assert svc.state == WorkState.RUNNING
    svc.complete()
    assert svc.state == WorkState.COMPLETED
    svc.stop()
    assert svc.state == WorkState.STOPPED


def test_fail_from_running():
    svc = ExecutorService()
    svc.start()
    svc.mark_running()
    svc.fail()
    assert svc.state == WorkState.FAILED


def test_start_from_failed():
    svc = ExecutorService()
    svc.start()
    svc.mark_running()
    svc.fail()
    svc.start()
    assert svc.state == WorkState.STARTING


def test_stop_from_paused():
    svc = ExecutorService()
    svc.start()
    svc.mark_running()
    svc.pause()
    svc.stop()
    assert svc.state == WorkState.STOPPED
