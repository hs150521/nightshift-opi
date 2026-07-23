"""Per-input debounce helpers for digital GPIO inputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Debouncer:
    """Stable-state debouncer with asymmetric rising/falling delays."""

    rising_ms: int
    falling_ms: int
    _stable_value: bool = False
    _candidate_value: bool = False
    _candidate_since_ms: int = 0
    _settled: bool = False

    def update(self, raw: bool, now_ms: int) -> tuple[bool, bool]:
        """Return (stable_value, changed).

        ``changed`` is True only when the stable value transitions.
        """
        if raw == self._stable_value:
            self._candidate_value = raw
            self._settled = True
            return self._stable_value, False

        if raw != self._candidate_value:
            self._candidate_value = raw
            self._candidate_since_ms = now_ms
            self._settled = False
            return self._stable_value, False

        delay = self.rising_ms if raw else self.falling_ms
        if now_ms - self._candidate_since_ms >= delay:
            previous = self._stable_value
            self._stable_value = raw
            self._settled = True
            return self._stable_value, self._stable_value != previous

        return self._stable_value, False

    @property
    def settled(self) -> bool:
        return self._settled
