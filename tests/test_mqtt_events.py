"""Tests for MQTT client domain event publishing."""

from unittest.mock import AsyncMock, patch

import pytest

from nightshift.domain.events import (
    ModeChanged,
    PanelConnectivityChanged,
    PressureChanged,
)
from nightshift.domain.models import SystemMode
from nightshift.domain.pressure import PressureState
from nightshift.integrations.mqtt.client import MqttClient
from nightshift.integrations.mqtt.config import MqttConfig


@pytest.fixture
def config():
    return MqttConfig(
        enabled=True,
        host="127.0.0.1",
        port=1883,
        username="",
        password="",
        node_id="node01",
        base_topic="nightshift/v1",
        keepalive=30,
        tls_enabled=False,
        ca_file="",
    )


@pytest.fixture
def orchestrator():
    mock = AsyncMock()
    mock.state = AsyncMock()
    return mock


@pytest.fixture
def client(config, orchestrator):
    return MqttClient(config, orchestrator)


async def test_on_domain_event_mode_changed_calls_publisher(client):
    publisher = AsyncMock()
    client._publisher = publisher
    event = ModeChanged(
        previous=SystemMode.IDLE,
        current=SystemMode.DAY_WORK,
        reason="cushion",
        revision=5,
        occurred_at_ms=1000,
    )
    await client.on_domain_event(event)
    publisher.publish_event.assert_called_once()
    call_kwargs = publisher.publish_event.call_args[1]
    assert call_kwargs["event_type"] == "mode.changed"
    assert call_kwargs["data"]["from"] == "idle"
    assert call_kwargs["data"]["to"] == "day_work"


async def test_on_domain_event_pressure_changed_calls_publisher(client):
    publisher = AsyncMock()
    client._publisher = publisher
    event = PressureChanged(
        pressure=PressureState(online=True, last_sample=None, updated_at_ms=100),
        revision=3,
        occurred_at_ms=500,
    )
    await client.on_domain_event(event)
    publisher.publish_event.assert_called_once()
    call_kwargs = publisher.publish_event.call_args[1]
    assert call_kwargs["event_type"] == "pressure.changed"


async def test_on_domain_event_panel_connectivity_calls_publisher(client):
    publisher = AsyncMock()
    client._publisher = publisher
    event = PanelConnectivityChanged(online=False)
    await client.on_domain_event(event)
    publisher.publish_event.assert_called_once()
    call_kwargs = publisher.publish_event.call_args[1]
    assert call_kwargs["event_type"] == "panel.connectivity"
    assert call_kwargs["data"]["online"] is False


async def test_on_domain_event_no_publisher_is_noop(client):
    client._publisher = None
    event = ModeChanged(
        previous=SystemMode.IDLE,
        current=SystemMode.DAY_WORK,
        reason="test",
        revision=1,
        occurred_at_ms=0,
    )
    await client.on_domain_event(event)


async def test_on_domain_event_publisher_exception_does_not_crash(client):
    publisher = AsyncMock()
    publisher.publish_event.side_effect = Exception("network error")
    client._publisher = publisher
    event = ModeChanged(
        previous=SystemMode.IDLE,
        current=SystemMode.DAY_WORK,
        reason="test",
        revision=1,
        occurred_at_ms=0,
    )
    await client.on_domain_event(event)
