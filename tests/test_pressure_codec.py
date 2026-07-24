"""Tests for `nightshift.pressure-state.v1` payload decoder."""

from __future__ import annotations

import json

import pytest

from nightshift.domain.pressure_codec import PressureDecodeError, decode_pressure_state


BASE = {
    "schema": "nightshift.pressure-state.v1",
    "device_id": "pressure-01",
    "boot_id": "a1b2c3d4",
    "seq": 128,
    "uptime_ms": 372810,
    "gpio": {"4": True, "5": False, "6": True, "7": True},
    "cushion": True,
    "footrest": True,
    "present": True,
}


def _payload(**overrides: object) -> bytes:
    body = {**BASE, **overrides}
    return json.dumps(body).encode()


def test_decode_valid_payload_populates_all_fields() -> None:
    sample = decode_pressure_state(_payload(), received_at_ms=1234)
    assert sample.device_id == "pressure-01"
    assert sample.boot_id == "a1b2c3d4"
    assert sample.seq == 128
    assert sample.cushion is True
    assert sample.footrest is True
    assert sample.present is True
    assert sample.uptime_ms == 372810
    assert sample.received_at_ms == 1234


def test_decode_rejects_wrong_schema() -> None:
    with pytest.raises(PressureDecodeError, match="unexpected schema"):
        decode_pressure_state(_payload(schema="nightshift.pressure-state.v2"), received_at_ms=1)


def test_decode_rejects_missing_field() -> None:
    body = {k: v for k, v in BASE.items() if k != "cushion"}
    with pytest.raises(PressureDecodeError, match="missing field: cushion"):
        decode_pressure_state(json.dumps(body).encode(), received_at_ms=1)


def test_decode_rejects_bad_json() -> None:
    with pytest.raises(PressureDecodeError, match="invalid JSON"):
        decode_pressure_state(b"not-json", received_at_ms=1)


def test_decode_rejects_non_object_payload() -> None:
    with pytest.raises(PressureDecodeError, match="not a JSON object"):
        decode_pressure_state(b"[1,2,3]", received_at_ms=1)


def test_decode_rejects_wrong_field_type() -> None:
    with pytest.raises(PressureDecodeError, match="bad field type"):
        decode_pressure_state(_payload(seq="not-an-int"), received_at_ms=1)
