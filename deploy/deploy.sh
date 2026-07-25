#!/usr/bin/env bash
# deploy.sh — Set up the Nightshift OPI system services.
# Run as root on the Orange Pi 3B.
set -euo pipefail

INSTALL_DIR="/opt/nightshift-opi"
DATA_DIR="/var/lib/nightshift"

echo "==> Creating data directory"
mkdir -p "$DATA_DIR"
chown ubuntu:ubuntu "$DATA_DIR"

echo "==> Installing hostapd config"
cp deploy/hostapd/hostapd.conf /etc/hostapd/hostapd.conf

echo "==> Installing dnsmasq config"
cp deploy/dnsmasq/dnsmasq.conf /etc/dnsmasq.d/nightshift.conf

echo "==> Installing mosquitto config"
cp deploy/mosquitto/mosquitto.conf /etc/mosquitto/conf.d/nightshift.conf

echo "==> Configuring wlan0 static IP"
if ! grep -q "interface wlan0" /etc/dhcpcd.conf 2>/dev/null; then
    cat >> /etc/dhcpcd.conf <<DHCP
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
DHCP
fi

echo "==> Installing systemd service"
cp deploy/systemd/nightshift-backend.service /etc/systemd/system/
systemctl daemon-reload

echo "==> Enabling services"
systemctl enable hostapd dnsmasq mosquitto nightshift-backend

echo "==> Done. Reboot or start services manually:"
echo "    systemctl start hostapd dnsmasq mosquitto nightshift-backend"
