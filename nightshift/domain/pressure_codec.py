"""Decoder for the `nightshift.pressure-state.v1` MQTT payload.

Kept separate from `nightshift.integrations.mqtt` so the domain model has no
dependency on aiomqtt or paho. The MQTT adapter feeds raw bytes/JSON into
`decode_pressure_state`; the mock source constructs `PressureSample`
directly.
"""

from __future__ import annotations

import json
from typing import Any

from nightshift.domain.pressure import PRESSURE_SCHEMA_V1, PressureSample


class PressureDecodeError(ValueError):
    pass


def _require_int(data: dict, key: str) -> int:
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise PressureDecodeError(f"field '{key}' must be int, got {type(val).__name__}")
    if val < 0:
        raise PressureDecodeError(f"field '{key}' must be non-negative, got {val}")
    return val


def _require_bool(data: dict, key: str) -> bool:
    val = data[key]
    if not isinstance(val, bool):
        raise PressureDecodeError(f"field '{key}' must be bool, got {type(val).__name__}")
    return val


def _require_str(data: dict, key: str) -> str:
    val = data[key]
    if not isinstance(val, str):
        raise PressureDecodeError(f"field '{key}' must be str, got {type(val).__name__}")
    return val


def decode_pressure_state(raw: bytes | str, *, received_at_ms: int) -> PressureSample:
    """Parse an ESP32 pressure state JSON payload.

    Raises PressureDecodeError on malformed input, wrong schema, or missing
    required fields. Uses strict type checking: rejects booleans where integers
    are required, rejects negative sequence/timestamp values.
    """

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PressureDecodeError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise PressureDecodeError("payload is not a JSON object")

    schema = data.get("schema")
    if schema != PRESSURE_SCHEMA_V1:
        raise PressureDecodeError(f"unexpected schema: {schema!r}")

    try:
        device_id = _require_str(data, "device_id")
        boot_id = _require_str(data, "boot_id")
        seq = _require_int(data, "seq")
        sampled_at_ms = _require_int(data, "sampled_at_ms")
        cushion = _require_bool(data, "cushion")
        footrest = _require_bool(data, "footrest")
        presence = _require_bool(data, "presence")
    except KeyError as exc:
        raise PressureDecodeError(f"missing field: {exc.args[0]}") from exc

    if "gpio" not in data or not isinstance(data["gpio"], dict):
        raise PressureDecodeError("missing or invalid 'gpio' object")

    gpio = data["gpio"]
    for pin in ("4", "5", "6", "7"):
        if pin not in gpio:
            raise PressureDecodeError(f"missing gpio pin '{pin}'")
        if not isinstance(gpio[pin], bool):
            raise PressureDecodeError(f"gpio pin '{pin}' must be bool")

    expected_cushion = gpio["4"] or gpio["5"]
    expected_footrest = gpio["6"] or gpio["7"]
    expected_presence = expected_cushion or expected_footrest

    if cushion != expected_cushion:
        raise PressureDecodeError(
            f"cushion={cushion} inconsistent with gpio4={gpio['4']}, gpio5={gpio['5']}"
        )
    if footrest != expected_footrest:
        raise PressureDecodeError(
            f"footrest={footrest} inconsistent with gpio6={gpio['6']}, gpio7={gpio['7']}"
        )
    if presence != expected_presence:
        raise PressureDecodeError(
            f"presence={presence} inconsistent with cushion={cushion}, footrest={footrest}"
        )

    return PressureSample(
        device_id=device_id,
        boot_id=boot_id,
        seq=seq,
        cushion=cushion,
        footrest=footrest,
        present=presence,
        uptime_ms=sampled_at_ms,
        received_at_ms=received_at_ms,
    )
