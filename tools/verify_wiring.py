"""Wiring verification helper for Orange Pi 3B 2G + T5AI-BOARD.

Run as root so UART device access reports fully:
    sudo .venv/bin/python tools/verify_wiring.py

The Opi3B no longer talks to any GPIO — the light sensor was removed and the
pressure sensor is an ESP32 that publishes over MQTT. Only UART3 wiring to the
T5 P11 header is verified here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def check_uart() -> None:
    print("=== UART devices ===")
    print(run(["ls", "-l", "/dev/ttyS3"]))

    print("=== Device-tree UART status ===")
    for node in sorted(Path("/proc/device-tree").glob("serial@*")):
        status_file = node / "status"
        if status_file.exists():
            status = status_file.read_text().replace("\x00", "")
        else:
            status = "(no status)"
        print(f"{node.name}: {status}")

    if not Path("/dev/ttyS3").exists():
        print("\nWARNING: /dev/ttyS3 is missing.")
        print(
            "  1. Confirm rk3566-orangepi-3b-uart3 overlay is enabled in "
            "/boot/extlinux/extlinux.conf."
        )
        print("  2. Reboot the board.")
    else:
        print("\nOK: /dev/ttyS3 is present.")


def print_expected_wiring() -> None:
    print("\n=== Expected wiring (T5 P11 header) ===")
    print("Opi3B Pin 14 (GND)                 -> T5 P11 GND")
    print("Opi3B Pin 28 (GPIO1_A0, UART3_TX)  -> T5 P11 Pin 1 (T5 UART0_RX)")
    print("Opi3B Pin 27 (GPIO1_A1, UART3_RX)  -> T5 P11 Pin 2 (T5 UART0_TX)")
    print()
    print("Pressure sensor: ESP32 pressure-01 publishes over MQTT — no GPIO.")


def main() -> None:
    if os.geteuid() != 0:
        print("This script should be run as root for full device access.")
    check_uart()
    print_expected_wiring()


if __name__ == "__main__":
    main()
