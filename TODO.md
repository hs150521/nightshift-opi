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
  - No MQTT client, topics, publisher or command handler implemented.

- **Audio service and T5 audio commands**
  - Commands `AUDIO_PLAY`, `AUDIO_STOP`, `VOLUME_SET`, `MIC_START`, etc. are defined in the protocol but not used.

- **Simulator tools**
  - `tools/gpio_simulator.py`, `tools/t5_uart_simulator.py`, `tools/mqtt_debug_client.py` do not exist.

- **Tests**
  - No `tests/` directory yet.

## Completed / in progress

- [x] Correct target board to Orange Pi 3B 2G.
- [x] Enable `rk3568-uart7-m2` overlay in `/boot/extlinux/extlinux.conf`.
- [ ] Reboot so `/dev/ttyS7` appears.
- [ ] Verify `gpiochip4 line 4` (GPIO4_A4) maps to Pin 7 and the light sensor active level.
- [ ] Verify UART7 wiring: OPI Pin15 -> T5 P11 Pin18 (UART1_RX), OPI Pin16 -> T5 P11 Pin10 (UART1_TX), GND -> T5 P11 Pin13/17.
- [ ] Power on and run a smoke test: light on -> IDLE (warm), light off -> NIGHT_EXEC (blue).
- [ ] Wire pressure sensor and enable `NIGHTSHIFT_GPIO_SIT_ENABLED`.
