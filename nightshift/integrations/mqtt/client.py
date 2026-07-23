"""MQTT client wrapper with auto-reconnect and lifecycle management."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiomqtt

from nightshift.domain.events import ModeChanged
from nightshift.integrations.mqtt import schemas
from nightshift.integrations.mqtt.command_handler import MqttCommandHandler
from nightshift.integrations.mqtt.config import MqttConfig
from nightshift.integrations.mqtt.publisher import MqttPublisher
from nightshift.integrations.mqtt.topics import TopicBuilder

if TYPE_CHECKING:
    from nightshift.domain.models import SystemState
    from nightshift.services.orchestrator import NightshiftOrchestrator

log = logging.getLogger(__name__)

_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 30.0


class MqttClient:
    def __init__(
        self,
        config: MqttConfig,
        orchestrator: NightshiftOrchestrator,
    ) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._topics = TopicBuilder(config.base_topic, config.node_id)
        self._boot_id = schemas.new_event_id()[:8]
        self._started_at_ms: int = 0
        self._publisher: MqttPublisher | None = None
        self._handler: MqttCommandHandler | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def topics(self) -> TopicBuilder:
        return self._topics

    async def start(self) -> None:
        import time

        self._started_at_ms = int(time.time() * 1000)
        self._handler = MqttCommandHandler(
            topics=self._topics,
            orchestrator=self._orchestrator,
        )
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        log.info(
            "mqtt: client started, broker=%s:%d, node=%s",
            self._config.host,
            self._config.port,
            self._config.node_id,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("mqtt: client stopped")

    async def on_state_changed(self, state: SystemState) -> None:
        if self._publisher is not None:
            try:
                await self._publisher.publish_state(state)
            except Exception:
                log.exception("mqtt: failed to publish state")

    async def on_mode_changed(self, event: ModeChanged) -> None:
        if self._publisher is not None:
            try:
                await self._publisher.publish_event(
                    event_type="mode.changed",
                    event_id=schemas.new_event_id(),
                    revision=event.revision,
                    occurred_at_ms=event.occurred_at_ms,
                    data={
                        "from": str(event.from_mode),
                        "to": str(event.to_mode),
                        "reason": event.reason,
                    },
                )
            except Exception:
                log.exception("mqtt: failed to publish event")

    async def _run_loop(self) -> None:
        backoff = _BACKOFF_BASE
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
                backoff = _BACKOFF_BASE
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mqtt: connection lost, reconnecting in %.1fs", backoff)
                self._publisher = None
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=backoff,
                    )
                    return
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _connect_and_run(self) -> None:
        tls_params = None
        if self._config.tls_enabled and self._config.ca_file:
            tls_params = aiomqtt.TLSParameters(
                ca_certs=self._config.ca_file,
            )

        client_id = f"nightshift-opi-{self._config.node_id}"

        lwt_payload = schemas.build_lwt(self._config.node_id)
        lwt_topic = self._topics.availability()

        async with aiomqtt.Client(
            hostname=self._config.host,
            port=self._config.port,
            username=self._config.username or None,
            password=self._config.password or None,
            identifier=client_id,
            keepalive=self._config.keepalive,
            tls_params=tls_params,
            will=aiomqtt.Will(
                topic=lwt_topic,
                payload=lwt_payload,
                qos=1,
                retain=True,
            ),
        ) as client:
            self._publisher = MqttPublisher(
                client=client,
                topics=self._topics,
                node_id=self._config.node_id,
            )

            await client.subscribe(self._topics.command(), qos=1)

            await self._publisher.publish_availability(
                online=True,
                boot_id=self._boot_id,
                version="0.1.0",
                started_at_ms=self._started_at_ms,
            )

            await self._publisher.publish_state(self._orchestrator.state)

            log.info("mqtt: connected and subscribed")

            async for message in client.messages:
                if self._stop_event.is_set():
                    break
                await self._handle_message(message)

            try:
                await self._publisher.publish_availability(online=False)
            except Exception:
                pass

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        if self._handler is None or self._publisher is None:
            return

        topic_str = str(message.topic)
        if topic_str != self._topics.command():
            return

        try:
            result = await self._handler.handle(message.payload)
        except Exception:
            log.exception("mqtt: unhandled error in command handler")
            return

        if result is None:
            return

        reply_to, reply = result
        try:
            await self._publisher._client.publish(
                reply_to,
                reply.to_json(),
                qos=1,
                retain=False,
            )
            log.info(
                "mqtt: replied to %s request_id=%s ok=%s",
                reply_to,
                reply.request_id,
                reply.ok,
            )
        except Exception:
            log.exception("mqtt: failed to publish reply")
