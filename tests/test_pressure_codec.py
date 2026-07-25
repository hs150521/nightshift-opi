"""Tests for the pressure state decoder (strict validation per frozen contract)."""

from __future__ import annotations

import json

import pytest

from nightshift.domain.pressure_codec import PressureDecodeError, decode_pressure_state


def _payload(**overrides) -> bytes:
    """Build a valid ESP32 pressure-state.v1 JSON payload with optional overrides."""
    base = {
        "schema": "nightshift.pressure-state.v1",
        "device_id": "pressure-01",
        "boot_id": "7f92ab31",
        "seq": 123,
        "sampled_at_ms": 45678,
        "time_base": "monotonic_boot_ms",
        "gpio": {"4": True, "5": False, "6": True, "7": True},
        "cushion": True,
        "footrest": True,
        "presence": True,
    }
    base.update(overrides)
    return json.dumps(base).encode()


def test_decode_valid_payload_populates_all_fields() -> None:
    sample = decode_pressure_state(_payload(), received_at_ms=99)
    assert sample.device_id == "pressure-01"
    assert sample.boot_id == "7f92ab31"
    assert sample.seq == 123
    assert sample.cushion is True
    assert sample.footrest is True
    assert sample.present is True
    assert sample.uptime_ms == 45678
    assert sample.received_at_ms == 99


def test_decode_all_released() -> None:
    sample = decode_pressure_state(
        _payload(
            gpio={"4": False, "5": False, "6": False, "7": False},
            cushion=False,
            footrest=False,
            presence=False,
        ),
        received_at_ms=1,
    )
    assert sample.cushion is False
    assert sample.footrest is False
    assert sample.present is False


def test_decode_rejects_wrong_schema() -> None:
    with pytest.raises(PressureDecodeError, match="unexpected schema"):
        decode_pressure_state(_payload(schema="wrong"), received_at_ms=1)


def test_decode_rejects_missing_field() -> None:
    data = json.loads(_payload())
    del data["seq"]
    with pytest.raises(PressureDecodeError, match="missing field"):
        decode_pressure_state(json.dumps(data).encode(), received_at_ms=1)


def test_decode_rejects_bad_json() -> None:
    with pytest.raises(PressureDecodeError, match="invalid JSON"):
        decode_pressure_state(b"not json{", received_at_ms=1)


def test_decode_rejects_non_object_payload() -> None:
    with pytest.raises(PressureDecodeError, match="not a JSON object"):
        decode_pressure_state(b"[1,2,3]", received_at_ms=1)


def test_decode_rejects_boolean_where_int_required() -> None:
    with pytest.raises(PressureDecodeError, match="must be int"):
        decode_pressure_state(_payload(seq=True), received_at_ms=1)


def test_decode_rejects_negative_seq() -> None:
    with pytest.raises(PressureDecodeError, match="must be non-negative"):
        decode_pressure_state(_payload(seq=-1), received_at_ms=1)


def test_decode_rejects_negative_sampled_at_ms() -> None:
    with pytest.raises(PressureDecodeError, match="must be non-negative"):
        decode_pressure_state(_payload(sampled_at_ms=-100), received_at_ms=1)


def test_decode_rejects_int_where_bool_required() -> None:
    with pytest.raises(PressureDecodeError, match="must be bool"):
        decode_pressure_state(_payload(cushion=1), received_at_ms=1)


def test_decode_rejects_string_where_int_required() -> None:
    with pytest.raises(PressureDecodeError, match="must be int"):
        decode_pressure_state(_payload(seq="not-an-int"), received_at_ms=1)


def test_decode_rejects_missing_gpio() -> None:
    data = json.loads(_payload())
    del data["gpio"]
    with pytest.raises(PressureDecodeError, match="gpio"):
        decode_pressure_state(json.dumps(data).encode(), received_at_ms=1)


def test_decode_rejects_missing_gpio_pin() -> None:
    data = json.loads(_payload())
    del data["gpio"]["4"]
    with pytest.raises(PressureDecodeError, match="gpio pin '4'"):
        decode_pressure_state(json.dumps(data).encode(), received_at_ms=1)


def test_decode_rejects_non_bool_gpio_pin() -> None:
    data = json.loads(_payload())
    data["gpio"]["4"] = 1
    with pytest.raises(PressureDecodeError, match="gpio pin '4' must be bool"):
        decode_pressure_state(json.dumps(data).encode(), received_at_ms=1)


def test_decode_rejects_inconsistent_cushion() -> None:
    with pytest.raises(PressureDecodeError, match="cushion.*inconsistent"):
        decode_pressure_state(
            _payload(
                gpio={"4": False, "5": False, "6": False, "7": False},
                cushion=True,
                footrest=False,
                presence=True,
            ),
            received_at_ms=1,
        )


def test_decode_rejects_inconsistent_footrest() -> None:
    with pytest.raises(PressureDecodeError, match="footrest.*inconsistent"):
        decode_pressure_state(
            _payload(
                gpio={"4": True, "5": False, "6": False, "7": False},
                cushion=True,
                footrest=True,
                presence=True,
            ),
            received_at_ms=1,
        )


def test_decode_rejects_inconsistent_presence() -> None:
    with pytest.raises(PressureDecodeError, match="presence.*inconsistent"):
        decode_pressure_state(
            _payload(
                gpio={"4": False, "5": False, "6": False, "7": False},
                cushion=False,
                footrest=False,
                presence=True,
            ),
            received_at_ms=1,
        )


def test_decode_verifies_presence_equals_cushion_or_footrest() -> None:
    sample = decode_pressure_state(
        _payload(
            gpio={"4": True, "5": False, "6": False, "7": False},
            cushion=True,
            footrest=False,
            presence=True,
        ),
        received_at_ms=1,
    )
    assert sample.present is True
