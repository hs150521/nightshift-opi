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


def decode_pressure_state(raw: bytes | str, *, received_at_ms: int) -> PressureSample:
    """Parse an ESP32 pressure state JSON payload.

    Raises PressureDecodeError on malformed input, wrong schema, or missing
    required fields. The MQTT adapter should log and drop; it must NOT
    demote the state to IDLE on a single decode error — only true staleness
    (>10 s) or the retained availability topic going offline can do that.
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
        return PressureSample(
            device_id=str(data["device_id"]),
            boot_id=str(data["boot_id"]),
            seq=int(data["seq"]),
            cushion=bool(data["cushion"]),
            footrest=bool(data["footrest"]),
            present=bool(data["present"]),
            uptime_ms=int(data["uptime_ms"]),
            received_at_ms=received_at_ms,
        )
    except KeyError as exc:
        raise PressureDecodeError(f"missing field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise PressureDecodeError(f"bad field type: {exc}") from exc
