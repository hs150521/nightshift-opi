"""In-memory pressure source for tests and offline development.

The real adapter lives in `nightshift.integrations.mqtt.pressure_adapter`.
The mock is deterministic — no wall clock, no MQTT — so state-machine tests
can pin `now_ms` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from nightshift.domain.pressure import PressureSample, PressureSource, PressureState


@dataclass
class MockPressureSource(PressureSource):
    state: PressureState = PressureState.empty()

    def snapshot(self) -> PressureState:
        return self.state

    def go_offline(self) -> None:
        self.state = PressureState(online=False, last_sample=None, updated_at_ms=0)

    def go_online(self) -> None:
        # Availability retained payload flipped to online. No sample yet.
        self.state = PressureState(online=True, last_sample=None, updated_at_ms=0)

    def push(
        self,
        *,
        now_ms: int,
        cushion: bool,
        footrest: bool,
        boot_id: str = "mock-boot",
        seq: int | None = None,
        device_id: str = "pressure-01",
    ) -> PressureSample:
        prev_seq = self.state.last_sample.seq if self.state.last_sample else 0
        sample = PressureSample(
            device_id=device_id,
            boot_id=boot_id,
            seq=prev_seq + 1 if seq is None else seq,
            cushion=cushion,
            footrest=footrest,
            present=cushion or footrest,
            uptime_ms=now_ms,
            received_at_ms=now_ms,
        )
        self.state = PressureState(online=True, last_sample=sample, updated_at_ms=now_ms)
        return sample
