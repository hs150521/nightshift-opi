"""MQTT publisher for availability, state, and event topics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nightshift.domain.models import DashboardState, SystemState
from nightshift.integrations.mqtt import schemas
from nightshift.integrations.mqtt.topics import TopicBuilder

if TYPE_CHECKING:
    import aiomqtt

log = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(
        self,
        client: aiomqtt.Client,
        topics: TopicBuilder,
        node_id: str,
    ) -> None:
        self._client = client
        self._topics = topics
        self._node_id = node_id

    async def publish_availability(
        self,
        *,
        online: bool,
        boot_id: str | None = None,
        version: str | None = None,
        started_at_ms: int | None = None,
    ) -> None:
        payload = schemas.build_availability(
            online=online,
            node_id=self._node_id,
            boot_id=boot_id,
            version=version,
            started_at_ms=started_at_ms,
        )
        await self._client.publish(
            self._topics.availability(),
            payload,
            qos=1,
            retain=True,
        )
        log.info("mqtt: published availability online=%s", online)

    async def publish_state(
        self,
        state: SystemState,
        dashboard: DashboardState | None = None,
    ) -> None:
        payload = schemas.build_state(
            state=state,
            node_id=self._node_id,
            dashboard=dashboard,
        )
        await self._client.publish(
            self._topics.state(),
            payload,
            qos=1,
            retain=True,
        )
        log.debug("mqtt: published state revision=%d", state.revision)

    async def publish_event(
        self,
        *,
        event_type: str,
        event_id: str,
        revision: int,
        occurred_at_ms: int,
        data: dict[str, Any],
    ) -> None:
        payload = schemas.build_event(
            event_type=event_type,
            event_id=event_id,
            revision=revision,
            occurred_at_ms=occurred_at_ms,
            data=data,
        )
        await self._client.publish(
            self._topics.event(),
            payload,
            qos=1,
            retain=False,
        )
        log.debug("mqtt: published event type=%s", event_type)
