# Nightshift Orange Pi 5B

Orange Pi 5B control service for the Nightshift desktop agent host.

## Current wiring

- **Light sensor (EBF26040003)**
  - Pin 1 (3.3V) -> VCC
  - Pin 6 (GND) -> GND
  - Pin 7 (GPIO3_B3) -> digital output

- **T5AI-BOARD UART**
  - Pin 14 (GND) -> T5 GND
  - Pin 15 (UART3_TX) -> T5 RX
  - Pin 16 (UART3_RX) -> T5 TX

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
gpioinfo | grep -E "gpiochip[0-9]+"
```

Confirm the chip and line for Pin 7 and update `NIGHTSHIFT_GPIO_LIGHT_CHIP` / `NIGHTSHIFT_GPIO_LIGHT_LINE` if needed.

## Protocol contracts

Shared with the T5 firmware:

- `contracts/uart/commands.yaml` — command IDs and payload schemas.
- `contracts/uart/golden_vectors.json` — canonical byte sequences for validation.

## TODO

See `TODO.md` for hardware and software capabilities that are not yet wired or implemented.
