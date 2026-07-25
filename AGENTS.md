# AGENTS.md — Nightshift OPI Non-Negotiable Rules

## Repository

- Authoritative branch: `main`
- Never force-push or rewrite accepted history.
- Atomic commits by concern. Push each commit after its acceptance gate passes.

## Frozen Contracts

- Do not invent, rename, widen, reorder, or remove frozen protocol fields.
- Cross-repository byte compatibility is mandatory (OPI ↔ T5).
- T5-Link v1 statuses stop at `STATE_CONFLICT = 0x000B`. No `NOT_IMPLEMENTED`.
- Object types: NONE=0, TASK=1, NOTICE=2, EXECUTOR=3, PANEL=4.

## Production Behavior

- Do not keep production on `MockPressureSource` when pressure MQTT is enabled.
- Do not silently fall back to mocks after adapter or service startup failure.
- Do not ACK a UI action with `OK` before the real service operation reaches a deterministic result.
- Do not hide required functionality behind permanent `NOT_IMPLEMENTED` or hard-coded success.
- Periodic heartbeat telemetry must not increment authoritative revision.
- A real panel online/offline edge that changes `PANEL_OFFLINE` attention must increment revision exactly once.

## Attention Ownership

The pressure state machine owns only `SENSOR_ERROR`. It must preserve all other attention bits:
```
preserved = current_attention & ~AttentionFlag.SENSOR_ERROR
sensor = machine_attention & AttentionFlag.SENSOR_ERROR
result = preserved | sensor
```

## Revision Rules

Increment `SystemState.revision` exactly once for a meaningful authoritative snapshot change:
- mode, attention content, work state, confirmation count, task/notice state, panel online/offline attention edge.

Do not increment for telemetry-only: heartbeat timestamps, T5 uptime, applied revision, repeated identical connectivity.

## Infrastructure

- Do not break STA connectivity, SSH access, default route, DNS, UART3, or rollback access.
- Back up every live configuration file before changing it.
- Do not commit credentials or secrets.

## Commit Sequence

1. **Commit 1b** — Cross-repository contract convergence and state semantics
2. **Commit 2** — UART session, UI_ACTION idempotency, resilient transport
3. **Commit 3** — Real ESP32 pressure MQTT adapter and state-v2 correctness
4. **Commit 4** — SQLite persistence and real domain services
5. **Commit 5** — Complete external OPI MQTT API
6. **Commit 6** — AP, Mosquitto, systemd, documentation, end-to-end acceptance
