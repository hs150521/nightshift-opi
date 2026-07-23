"""Mode derivation logic for Nightshift."""

from __future__ import annotations

from nightshift.domain.models import AttentionFlag, EnvironmentState, SystemMode


def derive_mode(environment: EnvironmentState) -> tuple[SystemMode, str]:
    """Return the system mode and reason given stable environment input.

    Rules:
      - Not ready -> IDLE with SENSOR_ERROR.
      - Light off -> NIGHT_EXEC.
      - Light on + sit -> DAY_WORK.
      - Light on + not sit -> IDLE.
    """
    if not environment.ready:
        return SystemMode.IDLE, "environment_not_ready"
    if not environment.light:
        return SystemMode.NIGHT_EXEC, "light_off"
    if environment.sit:
        return SystemMode.DAY_WORK, "day_work_detected"
    return SystemMode.IDLE, "idle_lit_no_sit"


def derive_attention(environment: EnvironmentState) -> AttentionFlag:
    """Return attention flags implied by environment state."""
    flags = AttentionFlag.NONE
    if not environment.ready:
        flags |= AttentionFlag.SENSOR_ERROR
    return flags
