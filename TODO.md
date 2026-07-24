# Nightshift Orange Pi 3B 2G TODO

This file tracks hardware and software capabilities that are **not yet wired or implemented**.
No mocks or stubs are kept in the production code for these items; they are intentionally absent.

## Hardware not yet connected

- **Pressure sensor (sit detect)**
  - Wiring: not connected to Orange Pi 3B 2G GPIO.
  - Impact: `NIGHTSHIFT_GPIO_SIT_ENABLED=false` by default.
  - State machine treats `sit` as `false` until the sensor is enabled in configuration.
  - TODO after wiring: set `NIGHTSHIFT_GPIO_SIT_ENABLED=true`, update chip/line, verify active-high/low.

## Software capabilities not yet implemented

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
  - No `apps/backend` or `apps/frontend` code.

- **MQTT external interface**
  - `NIGHTSHIFT_MQTT_ENABLED=false` by default.
  - Core MQTT adapter implemented: client, topics, schemas, publisher, command handler.
  - Remaining: ACL/auth, TLS, Home Assistant integration, telemetry, dev broker CLI.

- **Audio service and T5 audio commands**
  - Commands `AUDIO_PLAY`, `AUDIO_STOP`, `VOLUME_SET`, `MIC_START`, etc. are defined in the protocol but not used.

- **Simulator tools**
  - `tools/gpio_simulator.py`, `tools/t5_uart_simulator.py` do not exist.
  - `tools/mqtt_debug_client.py` not yet created.

- **Tests**
  - No `tests/` directory yet.

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
- [ ] Verify `gpiochip4 line 4` (GPIO4_A4) maps to Pin 7 and the light sensor active level.
- [x] Rewire T5 to OPI Pin27/28 (UART3) and verify: OPI Pin28 -> T5 P11 header Pin 1 (T5 UART0_RX), OPI Pin27 -> T5 P11 header Pin 2 (T5 UART0_TX), GND -> T5 P11 header GND. Loopback verified on both sides.
- [ ] Power on and run a smoke test: light on -> IDLE (warm), light off -> NIGHT_EXEC (blue).
- [ ] Wire pressure sensor and enable `NIGHTSHIFT_GPIO_SIT_ENABLED`.
- [ ] Implement `tools/mqtt_debug_client.py` for local debugging.
