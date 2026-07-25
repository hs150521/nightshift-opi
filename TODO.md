# Nightshift Orange Pi delivery status

The production path is:

```text
ESP32 GPIO4/5/6/7 -> stillwork -> MQTT -> OPI core -> UART3 -> T5
```

Implemented and automated:

- pressure MQTT validation, `(boot_id, seq)` ordering, 10-second freshness;
- pressure-driven mode state machine and 3-second all-released dwell;
- SystemState v2, retained availability/state, event/telemetry and command/reply;
- SQLite task, confirmation and notice services;
- MQTT command TTL, whitelist, reply routing and digest-backed idempotency;
- T5-Link frozen schema/vectors, UART retry, UI action dedup and full sync;
- deployable AP, Mosquitto ACL and systemd units.

Remaining hardware acceptance:

- verify `stillwork` association, DHCP, retained state, LWT and reconnect after
  the OPI is pinned to the upstream 2.4 GHz BSSID;
- verify the T5 startup HELLO, heartbeat, full sync and touch actions on the
  real OPI UART3 link;
- perform restart checks for AP, Mosquitto, backend, ESP32, T5 and OPI.

Optional hackathon extensions, not delivery blockers:

- HTTP/WebSocket frontend;
- Agent/LLM execution and non-zero token accounting;
- audio commands;
- Home Assistant integration and TLS.
