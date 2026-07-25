"""Tests for production startup wiring and pressure adapter lifecycle."""

import asyncio
import time

import pytest

from nightshift.domain.models import AttentionFlag, SystemMode
from nightshift.domain.pressure import PressureState
from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.integrations.mqtt.pressure_adapter import (
    PressureAdapterConfig,
    PressureMqttAdapter,
)
from nightshift.persistence.database import Database
from nightshift.services.orchestrator import NightshiftOrchestrator


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


class TestPressureAdapterLifecycle:
    """Verify PressureMqttAdapter start/stop and config wiring."""

    def test_adapter_accepts_config_object(self):
        cfg = PressureAdapterConfig(
            device_id="pressure-01",
            broker_host="127.0.0.1",
            broker_port=1883,
            username="nightshift-opi",
            password="secret",
        )
        adapter = PressureMqttAdapter(config=cfg)
        assert adapter.config.device_id == "pressure-01"
        assert adapter.config.broker_host == "127.0.0.1"
        assert adapter.config.broker_port == 1883
        assert adapter.config.username == "nightshift-opi"

    def test_adapter_snapshot_starts_empty(self):
        cfg = PressureAdapterConfig(device_id="pressure-01")
        adapter = PressureMqttAdapter(config=cfg)
        state = adapter.snapshot()
        assert state.online is False
        assert state.last_sample is None

    async def test_adapter_start_creates_task(self):
        cfg = PressureAdapterConfig(
            device_id="pressure-01",
            broker_host="192.0.2.1",
            broker_port=9999,
        )
        adapter = PressureMqttAdapter(config=cfg)
        await adapter.start()
        assert adapter._task is not None
        assert not adapter._task.done()
        await adapter.stop()
        assert adapter._task is None or adapter._task.done()

    async def test_adapter_stop_is_idempotent(self):
        cfg = PressureAdapterConfig(device_id="pressure-01")
        adapter = PressureMqttAdapter(config=cfg)
        await adapter.stop()
        await adapter.start()
        await adapter.stop()
        await adapter.stop()

    async def test_adapter_reconnects_on_broker_failure(self):
        """Adapter doesn't crash when broker is unreachable."""
        cfg = PressureAdapterConfig(
            device_id="pressure-01",
            broker_host="192.0.2.1",
            broker_port=9999,
        )
        adapter = PressureMqttAdapter(config=cfg)
        await adapter.start()
        await asyncio.sleep(0.2)
        assert not adapter._task.done()
        state = adapter.snapshot()
        assert state.online is False
        await adapter.stop()


class TestProductionWiring:
    """Verify the orchestrator wires correctly with adapter as PressureSource."""

    async def test_orchestrator_with_adapter_as_source(self, db):
        cfg = PressureAdapterConfig(
            device_id="pressure-01",
            broker_host="192.0.2.1",
            broker_port=9999,
        )
        adapter = PressureMqttAdapter(config=cfg)
        uart_cfg = UartConfig(device="/dev/null", baudrate=460800)
        orch = NightshiftOrchestrator(
            pressure_source=adapter,
            uart_config=uart_cfg,
            db=db,
        )
        adapter.on_updated = orch.on_pressure_updated
        assert orch.state.mode == SystemMode.IDLE
        assert AttentionFlag.SENSOR_ERROR in orch.state.attention

    async def test_orchestrator_does_not_fall_back_to_mock(self, db):
        """When MQTT is enabled, adapter stays as source even if broker is down."""
        cfg = PressureAdapterConfig(
            device_id="pressure-01",
            broker_host="192.0.2.1",
            broker_port=9999,
        )
        adapter = PressureMqttAdapter(config=cfg)
        uart_cfg = UartConfig(device="/dev/null", baudrate=460800)
        orch = NightshiftOrchestrator(
            pressure_source=adapter,
            uart_config=uart_cfg,
            db=db,
        )
        await adapter.start()
        await asyncio.sleep(0.1)
        assert orch._pressure_source is adapter
        assert not isinstance(orch._pressure_source, MockPressureSource)
        await adapter.stop()

    async def test_sensor_error_when_adapter_offline(self, db):
        """System stays IDLE+SENSOR_ERROR when adapter has no data."""
        cfg = PressureAdapterConfig(device_id="pressure-01")
        adapter = PressureMqttAdapter(config=cfg)
        uart_cfg = UartConfig(device="/dev/null", baudrate=460800)
        orch = NightshiftOrchestrator(
            pressure_source=adapter,
            uart_config=uart_cfg,
            db=db,
        )
        await orch.on_pressure_updated()
        assert orch.state.mode == SystemMode.IDLE
        assert AttentionFlag.SENSOR_ERROR in orch.state.attention
