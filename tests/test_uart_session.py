"""Tests for UART session management and UI_ACTION idempotency."""

from __future__ import annotations

import pytest

from nightshift.domain import commands as cmd
from nightshift.hardware.uart.session import (
    DedupKey,
    Disposition,
    UartSession,
    _compute_digest,
)


def test_empty_session_is_not_active() -> None:
    session = UartSession()
    assert not session.is_active()
    assert session.boot_id is None


def test_reset_activates_session() -> None:
    session = UartSession()
    session.reset(0xAABBCCDD)
    assert session.is_active()
    assert session.boot_id == 0xAABBCCDD


def test_reset_clears_dedup_cache() -> None:
    session = UartSession()
    session.reset(0x11111111)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    result = session.check_action(0x11111111, 1, cmd.UI_ACTION, payload)
    assert result.disposition == Disposition.EXECUTE
    session.record_result(result.dedup_key, result.digest, cmd.OK)

    # New boot resets everything
    session.reset(0x22222222)
    result2 = session.check_action(0x22222222, 1, cmd.UI_ACTION, payload)
    assert result2.disposition == Disposition.EXECUTE


def test_same_key_same_payload_replays() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r1.disposition == Disposition.EXECUTE
    session.record_result(r1.dedup_key, r1.digest, cmd.OK, b"\x42")

    # Same key, same payload → replay
    r2 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r2.disposition == Disposition.REPLAY
    assert r2.cached_status == cmd.OK
    assert r2.cached_reply == b"\x42"


def test_same_key_different_payload_conflicts() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload1 = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    payload2 = b"\x02\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload1)
    assert r1.disposition == Disposition.EXECUTE
    session.record_result(r1.dedup_key, r1.digest, cmd.OK)

    # Same key, different payload → conflict
    r2 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload2)
    assert r2.disposition == Disposition.CONFLICT


def test_in_flight_returns_busy() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r1.disposition == Disposition.EXECUTE

    # Same key while still in-flight
    r2 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r2.disposition == Disposition.IN_FLIGHT


def test_wrong_boot_id_returns_new_session() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r = session.check_action(0xBBBBBBBB, 5, cmd.UI_ACTION, payload)
    assert r.disposition == Disposition.NEW_SESSION


def test_different_sequence_is_new_action() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    session.record_result(r1.dedup_key, r1.digest, cmd.OK)

    # Different sequence → new action
    r2 = session.check_action(0xAAAAAAAA, 6, cmd.UI_ACTION, payload)
    assert r2.disposition == Disposition.EXECUTE


def test_cancel_in_flight_allows_retry() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r1.disposition == Disposition.EXECUTE

    session.cancel_in_flight(r1.dedup_key)

    # After cancel, same key can execute again
    r2 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r2.disposition == Disposition.EXECUTE


def test_cache_eviction_at_max_size() -> None:
    session = UartSession(_max_cache_size=3)
    session.reset(0xAAAAAAAA)

    for seq in range(5):
        payload = seq.to_bytes(4, "little")
        r = session.check_action(0xAAAAAAAA, seq + 1, cmd.UI_ACTION, payload)
        session.record_result(r.dedup_key, r.digest, cmd.OK)

    # Earliest entries should have been evicted
    r = session.check_action(0xAAAAAAAA, 1, cmd.UI_ACTION, (0).to_bytes(4, "little"))
    assert r.disposition == Disposition.EXECUTE  # Evicted, so new

    # Latest should still be cached
    r = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, (4).to_bytes(4, "little"))
    assert r.disposition == Disposition.REPLAY


def test_service_failure_cached_non_ok() -> None:
    session = UartSession()
    session.reset(0xAAAAAAAA)
    payload = b"\x01\x00\x01\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    r1 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    session.record_result(r1.dedup_key, r1.digest, cmd.INTERNAL_ERROR)

    # Replay returns the cached error
    r2 = session.check_action(0xAAAAAAAA, 5, cmd.UI_ACTION, payload)
    assert r2.disposition == Disposition.REPLAY
    assert r2.cached_status == cmd.INTERNAL_ERROR
