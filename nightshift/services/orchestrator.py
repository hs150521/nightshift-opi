"""Nightshift orchestrator: wires GPIO, state machine and UART gateway."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from nightshift.domain import commands as cmd
from nightshift.domain.events import (
    DomainEvent,
    EnvironmentChanged,
    HeartbeatReceived,
    ModeChanged,
    PanelConnectivityChanged,
    UiAction,
)
from nightshift.domain.models import (
    AttentionFlag,
    DashboardState,
    EnvironmentState,
    SystemMode,
    SystemState,
    WorkState,
)
from nightshift.domain.state_machine import derive_attention, derive_mode
from nightshift.hardware.gpio.adapter import GpioAdapter
from nightshift.hardware.gpio.config import GpioConfig
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.gateway import UartConfig, UartGateway

logger = structlog.get_logger()

StateListener = Callable[[SystemState], Coroutine[Any, Any, None]]
EventListener = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class NightshiftOrchestrator:
    """Owns the authoritative SystemState and coordinates all subsystems."""

    def __init__(
        self,
        gpio_config: GpioConfig,
        uart_config: UartConfig,
        poll_interval_ms: float = 50.0,
    ) -> None:
        self._gpio_config = gpio_config
        self._uart_config = uart_config
        self._poll_interval_ms = poll_interval_ms

        now = int(time.monotonic() * 1000)
        self._state = SystemState(
            revision=0,
            mode=SystemMode.IDLE,
            attention=AttentionFlag.NONE,
            work_state=WorkState.STOPPED,
            environment=EnvironmentState(ready=False, sit=False, light=False, changed_at_ms=now),
            panel_online=False,
            confirmation_count=0,
            token_input=0,
            token_output=0,
            updated_at_ms=now,
        )
        self._dashboard = DashboardState(revision=0)
        self._uart = UartGateway(uart_config, on_event=self._on_event)
        self._gpio = GpioAdapter(gpio_config)
        self._poll_task: asyncio.Task[None] | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._state_listeners: list[StateListener] = []
        self._event_listeners: list[EventListener] = []

    @property
    def state(self) -> SystemState:
        return self._state

    async def start(self) -> None:
        self._gpio.open()
        await self._uart.start()
        self._poll_task = asyncio.create_task(self._gpio_poll_loop())
        await self._full_sync()
        logger.info("orchestrator_started")

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        if self._sync_task:
            self._sync_task.cancel()
        await self._uart.stop()
        self._gpio.close()
        logger.info("orchestrator_stopped")

    def register_state_listener(self, listener: StateListener) -> None:
        self._state_listeners.append(listener)

    def register_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.append(listener)

    async def pause_executor(self) -> None:
        self._state = self._state.evolve(
            work_state=WorkState.PAUSED,
            updated_at_ms=int(time.monotonic() * 1000),
        )
        await self._publish_state()

    async def resume_executor(self) -> None:
        self._state = self._state.evolve(
            work_state=WorkState.RUNNING,
            updated_at_ms=int(time.monotonic() * 1000),
        )
        await self._publish_state()

    async def resync_panel(self) -> None:
        await self._full_sync()

    async def _gpio_poll_loop(self) -> None:
        while True:
            try:
                env = self._gpio.poll()
                await self._apply_environment(env)
                await asyncio.sleep(self._poll_interval_ms / 1000.0)
            except asyncio.CancelledError:
                break

    async def _apply_environment(self, env: EnvironmentState) -> None:
        mode, reason = derive_mode(env)
        attention = derive_attention(env)

        previous_mode = self._state.mode

        if mode == self._state.mode and attention == self._state.attention:
            if env != self._state.environment:
                self._state = self._state.evolve(
                    environment=env,
                    updated_at_ms=env.changed_at_ms,
                )
                await self._notify_event_listeners(
                    EnvironmentChanged(
                        environment=env,
                        revision=self._state.revision,
                        occurred_at_ms=env.changed_at_ms,
                    )
                )
            return

        self._state = self._state.evolve(
            mode=mode,
            attention=attention,
            environment=env,
            updated_at_ms=env.changed_at_ms,
        )
        logger.info(
            "state_changed",
            revision=self._state.revision,
            mode=self._state.mode.value,
            attention=int(self._state.attention),
            reason=reason,
            ready=self._state.environment.ready,
            light=self._state.environment.light,
            sit=self._state.environment.sit,
        )
        await self._publish_state()

        if mode != previous_mode:
            await self._notify_event_listeners(
                ModeChanged(
                    previous=previous_mode,
                    current=mode,
                    reason=reason,
                    revision=self._state.revision,
                    occurred_at_ms=env.changed_at_ms,
                )
            )

    async def _publish_state(self) -> None:
        try:
            await self._uart.send(
                cmd.MODE_SET,
                proto.encode_mode_set(
                    self._state.revision,
                    self._state.mode,
                    self._state.updated_at_ms,
                ),
            )
            await self._uart.send(
                cmd.ATTENTION_SET,
                proto.encode_attention_set(
                    self._state.revision,
                    self._state.attention,
                    self._state.confirmation_count,
                ),
            )
            await self._uart.send(
                cmd.WORK_STATE_SET,
                proto.encode_work_state_set(
                    revision=self._state.revision,
                    work_state=self._state.work_state,
                ),
            )
        except Exception as exc:
            logger.warning("publish_state_failed", error=str(exc))

        await self._notify_state_listeners(self._state)

    async def _notify_state_listeners(self, state: SystemState) -> None:
        for listener in self._state_listeners:
            try:
                await listener(state)
            except Exception:
                logger.exception("state_listener_failed")

    async def _notify_event_listeners(self, event: DomainEvent) -> None:
        for listener in self._event_listeners:
            try:
                await listener(event)
            except Exception:
                logger.exception("event_listener_failed")

    async def _full_sync(self) -> None:
        try:
            await self._uart.send(
                cmd.STATE_SYNC_BEGIN,
                proto.encode_state_sync_begin(self._state.revision, reason=0),
            )
            await self._publish_state()
            await self._uart.send(
                cmd.STATE_SYNC_END,
                proto.encode_state_sync_end(self._state.revision, snapshot_crc32=0),
            )
        except Exception as exc:
            logger.warning("full_sync_failed", error=str(exc))

    def _on_event(self, event: DomainEvent) -> None:
        if isinstance(event, HeartbeatReceived):
            panel_online = self._state.panel_online
            self._state = self._state.evolve(
                panel_online=True,
                updated_at_ms=int(time.monotonic() * 1000),
            )
            if not panel_online:
                asyncio.create_task(self._full_sync())
        elif isinstance(event, PanelConnectivityChanged):
            self._state = self._state.evolve(
                panel_online=event.online,
                attention=self._state.attention | AttentionFlag.PANEL_OFFLINE
                if not event.online
                else self._state.attention & ~AttentionFlag.PANEL_OFFLINE,
                updated_at_ms=int(time.monotonic() * 1000),
            )
            asyncio.create_task(self._publish_state())
        elif isinstance(event, UiAction):
            logger.info("ui_action_received", action=event.action, object_id=event.object_id)
            # TODO: forward to confirmation/task service once implemented.
