# Nightshift Orange Pi 3B 2G TODO

This file tracks hardware and software capabilities that are **not yet wired or implemented**.
No mocks or stubs are kept in the production code for these items; they are intentionally absent.

## Hardware not yet connected

- **Pressure sensor (ESP32 pressure-01)**
  - The Opi3B does not read pressure via GPIO. The pressure sensor is an ESP32
    that publishes `nightshift.pressure-state.v1` over MQTT under
    `nightshift/v1/sensor/pressure/pressure-01/{availability,state,telemetry}`.
  - Until the ESP32 firmware ships and the MQTT pressure adapter lands, the
    backend runs with `MockPressureSource`, which stays offline. The state
    machine correctly parks in `IDLE` with `SENSOR_ERROR`.
  - TODO: build `nightshift/integrations/mqtt/pressure_adapter.py` and swap it
    for the mock in `apps/backend/main.py`.

## Software capabilities not yet implemented

- **MQTT pressure adapter**
  - Subscribes to `nightshift/v1/sensor/pressure/<client_id>/*`, decodes the
    payload, tracks `(boot_id, seq)` for reorder rejection, and calls
    `orchestrator.on_pressure_updated()`.

- **Task database and persistence layer**
  - No database module exists under `nightshift/persistence/`.

- **Task service / night executor**
  - `WorkState` is managed in the orchestrator but no real execution engine exists.

- **Agent / LLM integration and token accounting**
  - `token_input` and `token_output` are always zero.

- **Confirmation service**
  - `UI_ACTION` events from T5 are logged but not processed.
  - `confirmation_count` is always zero.

- **Morning report generation**
  - No report builder or file output.

- **HTTP / WebSocket API and frontend**
  - No `apps/frontend` code.

- **MQTT external interface**
  - `NIGHTSHIFT_MQTT_ENABLED=false` by default.
  - Core MQTT adapter implemented: client, topics, schemas, publisher, command handler.
  - `system-state` schema is now `nightshift.system-state.v2` (pressure block).
  - Remaining: ACL/auth polish, TLS, Home Assistant integration, telemetry,
    dev broker CLI, SHA-256 command digest verification.

- **Audio service and T5 audio commands**
  - Commands `AUDIO_PLAY`, `AUDIO_STOP`, `VOLUME_SET`, `MIC_START`, etc. are defined in the protocol but not used.

- **Simulator tools**
  - `tools/mqtt_debug_client.py`, `tools/pressure_simulator.py` do not exist.

## Completed / in progress

- [x] Correct target board to Orange Pi 3B 2G.
- [x] Disable UART7 in device tree to free Ethernet MDIO pins.
- [x] Enable UART3-M0 and install custom overlay `rk3566-orangepi-3b-uart3.dtbo`.
- [x] Implement MQTT external integration (client, topics, schemas, publisher, command handler).
- [x] Configure Mosquitto dual listeners: 127.0.0.1:1883 (loopback) + 192.168.50.1:1884 (wired LAN).
- [x] Add MQTT auth (password_file) and ACL for nightshift-opi and t5-device users.
- [x] Configure eth0 static 192.168.50.1/24 with ConfigureWithoutCarrier.
- [x] Disable cloud-init network management.
- [x] Reboot — `/dev/ttyS3` confirmed present, eth0 address assigned.
- [x] Rewire T5 to OPI Pin27/28 (UART3) and verify: OPI Pin28 -> T5 P11 header Pin 1 (T5 UART0_RX), OPI Pin27 -> T5 P11 header Pin 2 (T5 UART0_TX), GND -> T5 P11 header GND. Loopback verified on both sides.
- [x] Freeze T5-Link v1 contract (HEARTBEAT response 14 B, WORK_STATE_SET revision prefix, MODE_SET.reason u8) and lock golden vectors.
- [x] State machine v2 (pressure-driven, 3 s all-released dwell) with tests.
- [x] Delete light-sensor GPIO code; migrate `SystemState` to `pressure` block; publish `nightshift.system-state.v2`.
- [ ] Power on and run a smoke test end-to-end (needs ESP32 firmware + adapter).
- [ ] Implement `tools/mqtt_debug_client.py` for local debugging.
