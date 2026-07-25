# Nightshift OPI Completion Goal

## Target

Orange Pi 3B 2G, Node ID: opi3b01, branch: main.

## Accepted Baseline

OPI: `3967e2684249f5fea64ddf82925164700bd7bff7`

## Production Chain

```
ESP32 GPIO4/5/6/7 → Wi-Fi AP stillwork → Mosquitto → OPI pressure adapter
→ authoritative SystemState v2 → SQLite-backed services → T5-Link UART
→ T5 display/touch → OPI MQTT state/event/telemetry/command/reply
```

## Commit Sequence

### Commit 1b — Cross-repository contract convergence

Correct OPI schema, constants, encoders, parsers, vector generator, vectors, and tests
to the exact T5-Link v1 contract. Fix _merge_attention, revision ownership, HELLO validation.

### Commit 2 — UART session, UI_ACTION idempotency, resilient transport

Real T5 UART session based on boot_id. Dedup key: (t5_boot_id, sequence, command).
Server-side digest. Bounded retry/backoff. Heartbeat loop resilience.

### Commit 3 — Real ESP32 pressure MQTT adapter

Subscribe to pressure topics. Strict JSON types. Boot/seq ordering. 10s freshness.
Resubscribe on reconnect. No silent mock fallback.

### Commit 4 — SQLite persistence and real domain services

WAL mode, migrations, task/notice/confirmation/executor services.
Replace all NOT_READY paths with real operations.

### Commit 5 — Complete external OPI MQTT API

Retained state v2, LWT, events, commands with TTL and idempotency.
SHA-256 digest over canonical business JSON.

### Commit 6 — AP, Mosquitto, systemd, end-to-end

ESP32 AUTH_EXPIRE resolution, Mosquitto ACLs, systemd units, live acceptance.

## Definition of Completion

All UI actions call real services. Pressure strict/ordered/reconnect-safe.
Tasks/notices/confirmations survive restart. IDs not reused.
system-state.v2 complete and retained. ESP32→OPI→T5 demonstrated on hardware.
