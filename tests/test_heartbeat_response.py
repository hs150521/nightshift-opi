"""Codec-level tests for the canonical `<HIII>` HEARTBEAT response."""

from __future__ import annotations

import pytest

from nightshift.domain import commands as cmd
from nightshift.hardware.uart import protocol as proto


def test_heartbeat_response_roundtrip_ok() -> None:
    payload = proto.encode_heartbeat_response(
        status=cmd.OK,
        t5_uptime_ms=987_654_321,
        applied_revision=42,
        error_flags=0,
    )
    assert len(payload) == 14
    parsed = proto.parse_heartbeat_response(payload)
    assert parsed.status == cmd.OK
    assert parsed.t5_uptime_ms == 987_654_321
    assert parsed.applied_revision == 42
    assert parsed.error_flags == 0


def test_heartbeat_response_roundtrip_non_ok() -> None:
    payload = proto.encode_heartbeat_response(
        status=cmd.BUSY,
        t5_uptime_ms=1_000,
        applied_revision=7,
        error_flags=0xA55A,
    )
    parsed = proto.parse_heartbeat_response(payload)
    assert parsed.status == cmd.BUSY
    # Non-OK status: caller MUST NOT trust applied_revision as committed;
    # here we just prove the codec preserves the field verbatim.
    assert parsed.applied_revision == 7
    assert parsed.error_flags == 0xA55A


def test_heartbeat_response_rejects_short_payload() -> None:
    with pytest.raises(proto.ProtocolError):
        proto.parse_heartbeat_response(b"\x00" * 13)


def test_heartbeat_response_layout_is_exactly_14_bytes() -> None:
    payload = proto.encode_heartbeat_response(
        status=0xFFFF,
        t5_uptime_ms=0xFFFFFFFF,
        applied_revision=0xFFFFFFFF,
        error_flags=0xFFFFFFFF,
    )
    assert len(payload) == 14
    # First 2 bytes = status LE
    assert payload[:2] == b"\xff\xff"
