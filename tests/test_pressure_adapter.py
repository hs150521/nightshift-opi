"""Tests for the real ESP32 pressure MQTT adapter."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from nightshift.domain.pressure import PressureState
from nightshift.integrations.mqtt.pressure_adapter import (
    AVAILABILITY_SCHEMA,
    PressureAdapterConfig,
    PressureMqttAdapter,
)


def _avail_payload(online: bool, boot_id: str = "7f92ab31", device_id: str = "pressure-01") -> bytes:
    return json.dumps({
        "schema": AVAILABILITY_SCHEMA,
        "device_id": device_id,
        "online": online,
        "boot_id": boot_id,
        "version": "0.1.0",
    }).encode()


def _state_payload(
    seq: int = 1,
    cushion: bool = False,
    footrest: bool = False,
    boot_id: str = "7f92ab31",
    device_id: str = "pressure-01",
    sampled_at_ms: int = 1000,
) -> bytes:
    gpio4 = cushion
    gpio5 = False
    gpio6 = footrest
    gpio7 = False
    return json.dumps({
        "schema": "nightshift.pressure-state.v1",
        "device_id": device_id,
        "boot_id": boot_id,
        "seq": seq,
        "sampled_at_ms": sampled_at_ms,
        "time_base": "monotonic_boot_ms",
        "gpio": {"4": gpio4, "5": gpio5, "6": gpio6, "7": gpio7},
        "cushion": cushion,
        "footrest": footrest,
        "presence": cushion or footrest,
    }).encode()


class FakeMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


@pytest.fixture
def adapter() -> PressureMqttAdapter:
    config = PressureAdapterConfig(device_id="pressure-01")
    updated_count: list[int] = [0]

    async def on_updated():
        updated_count[0] += 1

    adap = PressureMqttAdapter(config=config, on_updated=on_updated)
    adap._updated_count = updated_count
    return adap


@pytest.mark.asyncio
async def test_availability_online_sets_state(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.online is True


@pytest.mark.asyncio
async def test_availability_offline_marks_unavailable(adapter: PressureMqttAdapter) -> None:
    # First go online
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    # Then offline
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=False))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.online is False


@pytest.mark.asyncio
async def test_availability_offline_preserves_last_known_sensor_outputs(
    adapter: PressureMqttAdapter,
) -> None:
    await adapter._handle_message(
        FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    )
    await adapter._handle_message(
        FakeMessage(
            adapter._topic_state(),
            _state_payload(seq=1, cushion=True, footrest=False),
        )
    )

    await adapter._handle_message(
        FakeMessage(adapter._topic_availability(), _avail_payload(online=False))
    )

    state = adapter.snapshot()
    assert state.online is False
    assert state.is_valid(int(time.monotonic() * 1000)) is False
    assert state.cushion is True
    assert state.footrest is False
    assert state.last_sample is not None
    assert state.last_sample.seq == 1


@pytest.mark.asyncio
async def test_state_accepted_and_updates_sample(adapter: PressureMqttAdapter) -> None:
    # Online first
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    # State
    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1, cushion=True))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.last_sample is not None
    assert state.last_sample.cushion is True
    assert state.last_sample.seq == 1


@pytest.mark.asyncio
async def test_duplicate_seq_dropped(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=5, cushion=True))
    await adapter._handle_message(msg)

    # Same seq with different data — should be dropped
    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=5, cushion=False))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.last_sample.cushion is True  # First one wins


@pytest.mark.asyncio
async def test_older_seq_dropped(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=10, cushion=True))
    await adapter._handle_message(msg)

    # Older seq — should be dropped
    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=8, cushion=False))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.last_sample.seq == 10


@pytest.mark.asyncio
async def test_new_boot_id_resets_seq(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True, boot_id="boot1"))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=100, boot_id="boot1", cushion=True))
    await adapter._handle_message(msg)

    # New boot — seq=1 should be accepted
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True, boot_id="boot2"))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1, boot_id="boot2", cushion=False))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.last_sample.seq == 1
    assert state.last_sample.boot_id == "boot2"


@pytest.mark.asyncio
async def test_malformed_state_logged_not_offline(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1, cushion=True))
    await adapter._handle_message(msg)

    # Malformed message
    msg = FakeMessage(adapter._topic_state(), b"not json at all")
    await adapter._handle_message(msg)

    # Still online, sample unchanged
    state = adapter.snapshot()
    assert state.online is True
    assert state.last_sample.seq == 1


@pytest.mark.asyncio
async def test_device_id_mismatch_rejected(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(
        adapter._topic_availability(),
        _avail_payload(online=True, device_id="wrong-device"),
    )
    await adapter._handle_message(msg)
    assert adapter.snapshot().online is False  # Not updated


@pytest.mark.asyncio
async def test_state_device_id_mismatch_rejected(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(
        adapter._topic_state(),
        _state_payload(seq=1, device_id="wrong-device"),
    )
    await adapter._handle_message(msg)

    assert adapter.snapshot().last_sample is None


@pytest.mark.asyncio
async def test_retained_availability_and_state_either_order(adapter: PressureMqttAdapter) -> None:
    # State arrives before availability (retained messages)
    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1, boot_id="boot1", cushion=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True, boot_id="boot1"))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    assert state.online is True
    assert state.last_sample is not None
    assert state.last_sample.cushion is True


@pytest.mark.asyncio
async def test_on_updated_called_on_availability_change(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)
    assert adapter._updated_count[0] >= 1


@pytest.mark.asyncio
async def test_on_updated_called_on_state_change(adapter: PressureMqttAdapter) -> None:
    initial = adapter._updated_count[0]
    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1, boot_id="b1"))
    await adapter._handle_message(msg)
    assert adapter._updated_count[0] > initial


@pytest.mark.asyncio
async def test_freshness_via_pressure_state(adapter: PressureMqttAdapter) -> None:
    msg = FakeMessage(adapter._topic_availability(), _avail_payload(online=True))
    await adapter._handle_message(msg)

    msg = FakeMessage(adapter._topic_state(), _state_payload(seq=1))
    await adapter._handle_message(msg)

    state = adapter.snapshot()
    now_ms = int(time.monotonic() * 1000)
    assert state.is_valid(now_ms)
    # After 10s it should be stale
    assert not state.is_valid(now_ms + 10_001)
