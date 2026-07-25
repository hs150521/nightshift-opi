"""Tests for MQTT command handler dispatch to real services."""

import json

import pytest

from nightshift.domain.pressure_mock import MockPressureSource
from nightshift.hardware.uart.gateway import UartConfig
from nightshift.integrations.mqtt.command_handler import MqttCommandHandler
from nightshift.integrations.mqtt.topics import TopicBuilder
from nightshift.persistence.database import Database
from nightshift.services.orchestrator import NightshiftOrchestrator


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def orchestrator(db):
    pressure = MockPressureSource()
    config = UartConfig(device="/dev/null", baudrate=460800)
    return NightshiftOrchestrator(pressure, config, db=db)


@pytest.fixture
def topics():
    return TopicBuilder("nightshift/v1", "node01")


@pytest.fixture
def handler(topics, orchestrator):
    return MqttCommandHandler(
        topics=topics,
        orchestrator=orchestrator,
        now_ms=lambda: 5000,
    )


def _cmd(command, args=None, request_id="12345678-1234-1234-1234-123456789abc"):
    return json.dumps({
        "schema": "nightshift.command.v1",
        "request_id": request_id,
        "client_id": "test-client",
        "reply_to": "nightshift/v1/opi/node01/reply/test-client",
        "sent_at_ms": 4000,
        "ttl_ms": 60000,
        "command": command,
        "args": args or {},
    })


async def test_task_confirm_success(handler, orchestrator):
    task = await orchestrator._task_service.create(quadrant=0, title="T", now_ms=1000)
    result = await handler.handle(_cmd("task.confirm", {"task_id": task.id}))
    assert result is not None
    _, reply = result
    assert reply.ok is True
    assert reply.code == "ok"
    assert reply.data["pending_count"] == 0


async def test_task_confirm_nonexistent(handler):
    result = await handler.handle(_cmd("task.confirm", {"task_id": 999}))
    assert result is not None
    _, reply = result
    assert reply.ok is False
    assert reply.code == "not_found"


async def test_task_reject_success(handler, orchestrator):
    task = await orchestrator._task_service.create(quadrant=0, title="T", now_ms=1000)
    result = await handler.handle(
        _cmd("task.reject", {"task_id": task.id}, "22345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is True


async def test_task_retry_success(handler, orchestrator):
    task_svc = orchestrator._task_service
    task = await task_svc.create(quadrant=0, title="T", now_ms=1000)
    await task_svc.confirm(task.id, now_ms=2000)
    await task_svc.fail(task.id, now_ms=3000)
    result = await handler.handle(
        _cmd("task.retry", {"task_id": task.id}, "32345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is True
    assert reply.data["task_id"] == task.id


async def test_task_retry_not_failed(handler, orchestrator):
    task = await orchestrator._task_service.create(quadrant=0, title="T", now_ms=1000)
    result = await handler.handle(
        _cmd("task.retry", {"task_id": task.id}, "42345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is False
    assert reply.code == "not_found"


async def test_notice_dismiss_success(handler, orchestrator):
    notice = await orchestrator._notice_service.create(title="Alert", now_ms=1000)
    result = await handler.handle(
        _cmd("notice.dismiss", {"notice_id": notice.id}, "52345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is True
    assert reply.data["notice_id"] == notice.id


async def test_notice_dismiss_already_dismissed(handler, orchestrator):
    notice = await orchestrator._notice_service.create(title="Alert", now_ms=1000)
    await orchestrator._notice_service.dismiss(notice.id, now_ms=2000)
    result = await handler.handle(
        _cmd("notice.dismiss", {"notice_id": notice.id}, "62345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is False
    assert reply.code == "not_found"


async def test_task_confirm_invalid_arg_type(handler):
    result = await handler.handle(
        _cmd("task.confirm", {"task_id": "not-an-int"}, "72345678-1234-1234-1234-123456789abc")
    )
    assert result is not None
    _, reply = result
    assert reply.ok is False
    assert reply.code == "invalid_argument"


async def test_idempotency_returns_cached_reply(handler, orchestrator):
    task = await orchestrator._task_service.create(quadrant=0, title="T", now_ms=1000)
    request_id = "82345678-1234-1234-1234-123456789abc"
    cmd_payload = _cmd("task.confirm", {"task_id": task.id}, request_id)
    r1 = await handler.handle(cmd_payload)
    r2 = await handler.handle(cmd_payload)
    assert r1 is not None and r2 is not None
    _, reply1 = r1
    _, reply2 = r2
    assert reply1.ok == reply2.ok
    assert reply1.request_id == reply2.request_id


async def test_same_request_id_with_different_command_conflicts(
    handler, orchestrator
):
    task = await orchestrator._task_service.create(
        quadrant=0, title="T", now_ms=1000
    )
    request_id = "92345678-1234-1234-1234-123456789abc"
    original = _cmd("task.confirm", {"task_id": task.id}, request_id)
    changed = _cmd("task.reject", {"task_id": task.id}, request_id)

    first = await handler.handle(original)
    conflict = await handler.handle(changed)
    replay = await handler.handle(original)

    assert first is not None and conflict is not None and replay is not None
    assert first[1].ok is True
    assert conflict[1].ok is False
    assert conflict[1].code == "state_conflict"
    assert replay[1] == first[1]


async def test_mqtt_confirmation_updates_authoritative_state(
    handler, orchestrator
):
    first = await orchestrator._task_service.create(
        quadrant=0, title="A", now_ms=1000
    )
    await orchestrator._task_service.create(
        quadrant=0, title="B", now_ms=1000
    )
    revision = orchestrator.state.revision

    result = await handler.handle(
        _cmd(
            "task.confirm",
            {"task_id": first.id},
            "a2345678-1234-1234-1234-123456789abc",
        )
    )

    assert result is not None and result[1].ok is True
    assert orchestrator.state.confirmation_count == 1
    assert orchestrator.state.revision == revision + 1


async def test_boolean_task_id_is_rejected(handler):
    result = await handler.handle(
        _cmd(
            "task.confirm",
            {"task_id": True},
            "b2345678-1234-1234-1234-123456789abc",
        )
    )
    assert result is not None
    assert result[1].code == "invalid_argument"


async def test_services_none_returns_not_ready():
    pressure = MockPressureSource()
    config = UartConfig(device="/dev/null", baudrate=460800)
    orch = NightshiftOrchestrator(pressure, config)
    topics = TopicBuilder("nightshift/v1", "node01")
    handler = MqttCommandHandler(topics=topics, orchestrator=orch, now_ms=lambda: 5000)
    result = await handler.handle(_cmd("task.confirm", {"task_id": 1}))
    assert result is not None
    _, reply = result
    assert reply.ok is False
    assert reply.code == "not_ready"
