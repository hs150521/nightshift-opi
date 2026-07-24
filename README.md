# Nightshift Orange Pi 3B 2G

Orange Pi 3B 2G control service for the Nightshift desktop agent host.

> **Note:** This repository originally assumed an Orange Pi 5B. The target board has been corrected to **Orange Pi 3B 2G**. GPIO and UART defaults below reflect the Orange Pi 3B 40-pin header; always verify with `gpioinfo` on your actual system before running.

## Current wiring

- **Light sensor (EBF26040003)**
  - Pin 1 (3.3V) -> VCC
  - Pin 6 (GND) -> GND
  - Pin 7 (GPIO4_A4) -> digital output

- **T5AI-BOARD UART (T5 P11 header)**
  - Pin 14 (GND)                -> T5 P11 Pin 13 or 17 (GND)
  - Pin 28 (GPIO1_A0, UART3_TX) -> T5 P11 Pin 14 (P11, UART0_TX)
  - Pin 27 (GPIO1_A1, UART3_RX) -> T5 P11 Pin 12 (P10, UART0_RX)

> **Why UART3:** UART7 (on pins 15/16) conflicts with the Ethernet GMAC MDIO pins, so it is disabled in the device tree. UART3-M0 uses pins 27/28 (GPIO1_A1/A0) and leaves Ethernet functional.

## Required overlay

`/boot/extlinux/extlinux.conf` contains:

```text
fdtoverlays /lib/firmware/5.10.0-1012-rockchip/device-tree/rockchip/overlay/rk3566-orangepi-3b-uart3.dtbo
```

The base device tree (`rk3566-orangepi-3b.dtb`) has also been patched to enable UART3 and disable UART7. Reboot for changes to take effect:

```bash
sudo reboot
```

After reboot you should see `/dev/ttyS3`.

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gpio]"
cp .env.example .env
# Edit .env to match the actual UART device and GPIO chip/line mapping.
python apps/backend/main.py
```

## MQTT / Network

Mosquitto runs two listeners:

| Listener | Address | Port | Purpose |
|----------|---------|------|---------|
| Loopback | 127.0.0.1 | 1883 | Local backend (`nightshift-opi`) |
| Wired LAN | 192.168.50.1 | 1884 | Remote MQTT device (`t5-device`) |

Anonymous access is disabled on both. Credentials are stored in `/etc/mosquitto/passwd`.

`eth0` is configured as a static host (`192.168.50.1/24`, no gateway, no DNS) for a dedicated wired link to the MQTT device. It is brought up even without a cable plugged in via a `ConfigureWithoutCarrier=yes` drop-in at `/etc/systemd/network/10-netplan-eth0.network.d/carrier.conf`.

To test the loopback listener:

```bash
mosquitto_pub -h 127.0.0.1 -p 1883 -u nightshift-opi -P nightshift-opi-secret \
  -t 'nightshift/v1/test' -m 'hello'
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
