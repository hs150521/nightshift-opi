# Nightshift Orange Pi 3B 2G

Orange Pi 3B 2G control service for the Nightshift desktop agent host.

> **Note:** This repository originally assumed an Orange Pi 5B. The target board has been corrected to **Orange Pi 3B 2G**. GPIO and UART defaults below reflect the Orange Pi 3B 40-pin header; always verify with `gpioinfo` on your actual system before running.

## Current wiring

- **Light sensor (EBF26040003)**
  - Pin 1 (3.3V) -> VCC
  - Pin 6 (GND) -> GND
  - Pin 7 (GPIO3_C6) -> digital output

- **T5AI-BOARD UART**
  - Pin 14 (GND) -> T5 GND
  - Pin 15 -> T5 RX (requires matching UART overlay / pinmux)
  - Pin 16 -> T5 TX (requires matching UART overlay / pinmux)

> **Pin 15/16 UART warning:** On Orange Pi 3B these pins are GPIO3_D4/D5 by default and are **not** a UART. You must enable the correct device-tree overlay (commonly `uart3` or `uart4` depending on your wiring) so a `/dev/ttyS*` node appears on these pins. The default `.env.example` uses `/dev/ttyS1` because that is the only UART currently enabled on this board image; change it to the device that matches your overlay.

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gpio]"
cp .env.example .env
# Edit .env to match the actual UART device and GPIO chip/line mapping.
python apps/backend/main.py
```

## Verify GPIO mapping

```bash
sudo gpioinfo | grep -E "gpiochip[0-9]+"
```

Confirm the chip and line for Pin 7 and update `NIGHTSHIFT_GPIO_LIGHT_CHIP` / `NIGHTSHIFT_GPIO_LIGHT_LINE` if needed.

To see which UARTs are enabled and their device nodes:

```bash
ls -l /dev/ttyS*
for u in /proc/device-tree/serial@*; do printf "%s: " "$u"; tr -d '\0' < "$u/status" 2>/dev/null || echo "(no status)"; done
```

## Protocol contracts

Shared with the T5 firmware:

- `contracts/uart/commands.yaml` — command IDs and payload schemas.
- `contracts/uart/golden_vectors.json` — canonical byte sequences for validation.

## TODO

See `TODO.md` for hardware and software capabilities that are not yet wired or implemented.
