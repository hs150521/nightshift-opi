"""Nightshift orchestrator: wires the pressure source, state machine, UART, and MQTT.

The orchestrator holds the authoritative `SystemState`. Inputs:
- Pressure updates (event-driven from the MQTT pressure adapter, or manual
  pushes from tests / the mock source).
- A low-rate dwell tick so the 3 s all-released timer keeps advancing when
  no new pressure sample arrives.
- UART events from the T5 panel (heartbeat, connectivity, UI actions).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from nightshift.domain import commands as cmd
from nightshift.domain.events import (
    DomainEvent,
    HeartbeatFailed,
    HeartbeatReceived,
    ModeChanged,
    PanelConnectivityChanged,
    PressureChanged,
    UiAction,
)
from nightshift.domain.models import (
    AttentionFlag,
    DashboardState,
    PanelTelemetry,
    SystemMode,
    SystemState,
    WorkState,
)
from nightshift.domain.pressure import PressureSource, PressureState
from nightshift.domain.state_machine import StateMachineV2
from nightshift.hardware.uart import protocol as proto
from nightshift.hardware.uart.gateway import UartConfig, UartGateway

logger = structlog.get_logger()

StateListener = Callable[[SystemState], Coroutine[Any, Any, None]]
EventListener = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class NightshiftOrchestrator:
    """Owns the authoritative SystemState and coordinates all subsystems."""

    def __init__(
        self,
        pressure_source: PressureSource,
        uart_config: UartConfig,
        *,
        dwell_ms: int | None = None,
        stale_ms: int | None = None,
        tick_interval_ms: float = 250.0,
    ) -> None:
        self._pressure_source = pressure_source
        self._uart_config = uart_config
        self._tick_interval_ms = tick_interval_ms

        sm_kwargs: dict[str, int] = {}
        if dwell_ms is not None:
            sm_kwargs["dwell_ms"] = dwell_ms
        if stale_ms is not None:
            sm_kwargs["stale_ms"] = stale_ms
        self._state_machine = StateMachineV2(**sm_kwargs)

        now = int(time.monotonic() * 1000)
        self._state = SystemState(
            revision=0,
            mode=SystemMode.IDLE,
            attention=AttentionFlag.SENSOR_ERROR,
            work_state=WorkState.STOPPED,
            pressure=PressureState.empty(),
            panel_online=False,
            confirmation_count=0,
            token_input=0,
            token_output=0,
            updated_at_ms=now,
        )
        self._dashboard = DashboardState(revision=0)
        self._uart = UartGateway(
            uart_config,
            on_event=self._on_event,
            on_panel_hello=self._on_panel_hello,
            ui_action_handler=self._handle_ui_action,
        )
        self._tick_task: asyncio.Task[None] | None = None
        self._state_listeners: list[StateListener] = []
        self._event_listeners: list[EventListener] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SystemState:
        return self._state

    async def start(self) -> None:
        await self._uart.start()
        self._tick_task = asyncio.create_task(self._tick_loop())
        await self._full_sync()
        logger.info("orchestrator_started")

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
        await self._uart.stop()
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

    async def on_pressure_updated(self) -> None:
        """Called by the pressure adapter after each new sample or availability flip."""
        await self._evaluate_and_apply()

    async def _tick_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._tick_interval_ms / 1000.0)
                await self._evaluate_and_apply()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("tick_loop_iteration_failed")

    async def _evaluate_and_apply(self) -> None:
        async with self._lock:
            pressure = self._pressure_source.snapshot()
            now_ms = int(time.monotonic() * 1000)
            decision = self._state_machine.evaluate(pressure, now_ms=now_ms)

            previous_mode = self._state.mode
            previous_attention = self._state.attention
            previous_pressure = self._state.pressure

            attention = self._merge_attention(decision.attention)

            pressure_changed = pressure != previous_pressure
            mode_changed = decision.mode != previous_mode
            attention_changed = attention != previous_attention

            if not (pressure_changed or mode_changed or attention_changed):
                return

            self._state = self._state.evolve(
                mode=decision.mode,
                attention=attention,
                pressure=pressure,
                updated_at_ms=now_ms,
            )

            logger.info(
                "state_evaluated",
                revision=self._state.revision,
                mode=self._state.mode.value,
                attention=int(self._state.attention),
                reason=decision.reason,
                pressure_online=pressure.online,
                pressure_valid=pressure.is_valid(now_ms, stale_ms=self._state_machine.stale_ms),
                cushion=pressure.cushion,
                footrest=pressure.footrest,
            )

            if pressure_changed:
                await self._notify_event_listeners(
                    PressureChanged(
                        pressure=pressure,
                        revision=self._state.revision,
                        occurred_at_ms=now_ms,
                    )
                )
            if mode_changed:
                await self._notify_event_listeners(
                    ModeChanged(
                        previous=previous_mode,
                        current=decision.mode,
                        reason=decision.reason,
                        revision=self._state.revision,
                        occurred_at_ms=now_ms,
                    )
                )

            await self._publish_state()

    def _merge_attention(self, from_state_machine: AttentionFlag) -> AttentionFlag:
        preserved = self._state.attention & ~AttentionFlag.SENSOR_ERROR
        sensor = from_state_machine & AttentionFlag.SENSOR_ERROR
        return preserved | sensor

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
            was_online = self._state.panel_online
            telemetry = PanelTelemetry(
                t5_uptime_ms=event.t5_uptime_ms,
                error_flags=event.error_flags,
                applied_revision=event.applied_revision,
                last_heartbeat_at_ms=event.received_at_ms,
            )
            attention = self._state.attention & ~AttentionFlag.PANEL_OFFLINE
            self._state = self._state.evolve(
                panel_online=True,
                attention=attention,
                panel_telemetry=telemetry,
                updated_at_ms=event.received_at_ms or int(time.monotonic() * 1000),
                bump_revision=False,
            )
            if not was_online:
                logger.info(
                    "panel_online",
                    applied_revision=event.applied_revision,
                    t5_uptime_ms=event.t5_uptime_ms,
                )
                asyncio.create_task(self._full_sync())
        elif isinstance(event, HeartbeatFailed):
            logger.warning(
                "heartbeat_failed",
                status=event.status,
                error_flags=event.error_flags,
            )
            # No state mutation: transport still up, T5 just refused to
            # commit this revision. applied_revision was not advanced by
            # the gateway either.
        elif isinstance(event, PanelConnectivityChanged):
            attention = self._state.attention
            if not event.online:
                attention = attention | AttentionFlag.PANEL_OFFLINE
            else:
                attention = attention & ~AttentionFlag.PANEL_OFFLINE
            attention_changed = attention != self._state.attention
            self._state = self._state.evolve(
                panel_online=event.online,
                attention=attention,
                updated_at_ms=int(time.monotonic() * 1000),
                bump_revision=attention_changed,
            )
            if attention_changed:
                asyncio.create_task(self._publish_state())
        elif isinstance(event, UiAction):
            logger.info("ui_action_received", action=event.action, object_id=event.object_id)

    async def _handle_ui_action(self, event: UiAction) -> tuple[int, bytes]:
        """Route a UI action to the appropriate service. Returns (status, reply_data)."""
        action = event.action

        if action == cmd.ACTION_PAUSE_EXECUTION:
            await self.pause_executor()
            return cmd.OK, b""
        elif action == cmd.ACTION_RESUME_EXECUTION:
            await self.resume_executor()
            return cmd.OK, b""
        elif action == cmd.ACTION_REQUEST_RESYNC:
            await self._full_sync()
            return cmd.OK, b""
        elif action in (
            cmd.ACTION_CONFIRM,
            cmd.ACTION_REJECT,
            cmd.ACTION_RETRY,
            cmd.ACTION_DISMISS_NOTICE,
        ):
            return cmd.NOT_READY, b""
        else:
            return cmd.OK, b""

    async def _on_panel_hello(self) -> None:
        await self._full_sync()
