"""Wiring verification helper for Orange Pi 3B 2G + T5AI-BOARD.

Run as root so gpioinfo and UART device access work:
    sudo .venv/bin/python tools/verify_wiring.py
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def check_uart() -> None:
    print("=== UART devices ===")
    print(run(["ls", "-l", "/dev/ttyS*"]))

    print("=== Device-tree UART status ===")
    for node in sorted(Path("/proc/device-tree").glob("serial@*")):
        status_file = node / "status"
        if status_file.exists():
            status = status_file.read_text().replace("\x00", "")
        else:
            status = "(no status)"
        print(f"{node.name}: {status}")

    if not Path("/dev/ttyS7").exists():
        print("\nWARNING: /dev/ttyS7 is missing.")
        print("  1. Confirm rk3568-uart7-m2 overlay is enabled in /boot/extlinux/extlinux.conf.")
        print("  2. Reboot the board.")
    else:
        print("\nOK: /dev/ttyS7 is present.")


def check_gpio() -> None:
    print("\n=== GPIO info ===")
    print(run(["gpioinfo"]))

    print("\n=== Expected wiring ===")
    print("Light sensor -> Pin 7 = gpiochip4 line 4 (GPIO4_A4)")
    print("T5 GND       -> Pin 14 (GND) -> T5 P11 Pin 13 or 17")
    print("T5 TX        -> Pin 16 = gpiochip4 line 3 (GPIO4_A3, UART7_RX)")
    print("                -> T5 P11 Pin 10 (P00, UART1_TX)")
    print("T5 RX        -> Pin 15 = gpiochip4 line 2 (GPIO4_A2, UART7_TX)")
    print("                -> T5 P11 Pin 18 (P01, UART1_RX)")


def main() -> None:
    if os.geteuid() != 0:
        print("This script should be run as root for gpioinfo access.")
    check_uart()
    check_gpio()


if __name__ == "__main__":
    main()
