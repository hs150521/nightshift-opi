# Nightshift Orange Pi 3B 2G

Orange Pi 3B 2G control service for the Nightshift desktop agent host.

> **Note:** This repository originally assumed an Orange Pi 5B. The target board has been corrected to **Orange Pi 3B 2G**. GPIO and UART defaults below reflect the Orange Pi 3B 40-pin header; always verify with `gpioinfo` on your actual system before running.

## Current wiring

- **Light sensor (EBF26040003)**
  - Pin 1 (3.3V) -> VCC
  - Pin 6 (GND) -> GND
  - Pin 7 (GPIO4_A4) -> digital output

- **T5AI-BOARD UART (T5 P11 header)**
  - Pin 14 (GND)                 -> T5 P11 Pin 13 or 17 (GND)
  - Pin 15 (GPIO4_A2, UART7_TX) -> T5 P11 Pin 18 (P01, UART1_RX)
  - Pin 16 (GPIO4_A3, UART7_RX) -> T5 P11 Pin 10 (P00, UART1_TX)

> **Why `uart7-m2`:** Orange Pi 3B maps UART7 to physical pins 15/16 via the `uart7m2` pinmux (GPIO4_A2/A3). Other overlays such as `uart7-m1` place UART7 on different pins and will not work with this wiring.

## Required overlay

`/boot/extlinux/extlinux.conf` contains:

```text
fdtoverlays /lib/firmware/5.10.0-1012-rockchip/device-tree/rockchip/overlay/rk3568-uart7-m2.dtbo
```

Reboot for the overlay to take effect:

```bash
sudo reboot
```

After reboot you should see `/dev/ttyS7`.

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gpio]"
cp .env.example .env
# Edit .env to match the actual UART device and GPIO chip/line mapping.
python apps/backend/main.py
```

## Verify GPIO and UART mapping

```bash
# Check UARTs
ls -l /dev/ttyS*
for u in /proc/device-tree/serial@*; do printf "%s: " "$u"; tr -d '\0' < "$u/status" 2>/dev/null || echo "(no status)"; done

# Check GPIO
sudo gpioinfo | grep -E "gpiochip[0-9]+"
```

Confirm the chip and line for Pin 7 and update `NIGHTSHIFT_GPIO_LIGHT_CHIP` / `NIGHTSHIFT_GPIO_LIGHT_LINE` if needed.

You can also run the wiring verification helper:

```bash
sudo .venv/bin/python tools/verify_wiring.py
```

## Protocol contracts

Shared with the T5 firmware:

- `contracts/uart/commands.yaml` — command IDs and payload schemas.
- `contracts/uart/golden_vectors.json` — canonical byte sequences for validation.

## TODO

See `TODO.md` for hardware and software capabilities that are not yet wired or implemented.
