"""UART session manager with UI_ACTION idempotency.

Session identity is `t5_boot_id`. A new boot ID clears all session state.
Dedup key is (t5_boot_id, sequence, command).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DedupKey:
    boot_id: int
    sequence: int
    command: int


@dataclass(frozen=True)
class DedupEntry:
    digest: str
    status: int
    reply_data: bytes


@dataclass
class UartSession:
    """Manages T5 panel session state and action idempotency."""

    boot_id: int | None = None
    _dedup_cache: dict[DedupKey, DedupEntry] = field(default_factory=dict)
    _in_flight: set[DedupKey] = field(default_factory=set)
    _max_cache_size: int = 256

    def reset(self, new_boot_id: int) -> None:
        self.boot_id = new_boot_id
        self._dedup_cache.clear()
        self._in_flight.clear()

    def is_active(self) -> bool:
        return self.boot_id is not None

    def check_action(
        self, boot_id: int, sequence: int, command: int, payload: bytes
    ) -> DedupResult:
        if boot_id != self.boot_id:
            return DedupResult(disposition=Disposition.NEW_SESSION)

        key = DedupKey(boot_id=boot_id, sequence=sequence, command=command)
        digest = _compute_digest(payload)

        existing = self._dedup_cache.get(key)
        if existing is not None:
            if existing.digest == digest:
                return DedupResult(
                    disposition=Disposition.REPLAY,
                    cached_status=existing.status,
                    cached_reply=existing.reply_data,
                )
            else:
                return DedupResult(disposition=Disposition.CONFLICT)

        if key in self._in_flight:
            return DedupResult(disposition=Disposition.IN_FLIGHT)

        self._in_flight.add(key)
        return DedupResult(disposition=Disposition.EXECUTE, dedup_key=key, digest=digest)

    def record_result(
        self, key: DedupKey, digest: str, status: int, reply_data: bytes = b""
    ) -> None:
        self._in_flight.discard(key)
        if len(self._dedup_cache) >= self._max_cache_size:
            oldest_key = next(iter(self._dedup_cache))
            del self._dedup_cache[oldest_key]
        self._dedup_cache[key] = DedupEntry(
            digest=digest, status=status, reply_data=reply_data
        )

    def cancel_in_flight(self, key: DedupKey) -> None:
        self._in_flight.discard(key)


class Disposition:
    EXECUTE = "execute"
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_FLIGHT = "in_flight"
    NEW_SESSION = "new_session"


@dataclass(frozen=True)
class DedupResult:
    disposition: str
    cached_status: int | None = None
    cached_reply: bytes | None = None
    dedup_key: DedupKey | None = None
    digest: str | None = None


def _compute_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]
