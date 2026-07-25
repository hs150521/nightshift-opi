#!/usr/bin/env bash
# deploy.sh — Deploy Nightshift OPI system services.
# Run as root on the Orange Pi 3B.
#
# IMPORTANT:
# - Does NOT modify wlan0, SSH, default route, or DNS.
# - Uses ap0 virtual interface for the AP (shared radio with wlan0).
# - Requires local secrets to exist before installing configs.
# - Backs up all modified files before overwriting.
set -euo pipefail

INSTALL_DIR="/opt/nightshift-opi"
DATA_DIR="/var/lib/nightshift"
BACKUP_DIR="/opt/nightshift-backups/$(date +%Y%m%d-%H%M%S)"

# --- Preflight checks ---

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root." >&2
    exit 1
fi

# Refuse to deploy without local secrets
if [ ! -f /etc/mosquitto/passwd ]; then
    echo "ERROR: /etc/mosquitto/passwd missing. Create it first:" >&2
    echo "  mosquitto_passwd -c /etc/mosquitto/passwd nightshift-opi" >&2
    echo "  mosquitto_passwd    /etc/mosquitto/passwd pressure-01" >&2
    exit 1
fi

if [ ! -f /etc/hostapd/nightshift-ap.conf ]; then
    echo "ERROR: /etc/hostapd/nightshift-ap.conf missing." >&2
    echo "  Copy deploy/hostapd/hostapd.conf there and set the real wpa_passphrase." >&2
    exit 1
fi

if grep -q "CHANGE_ME" /etc/hostapd/nightshift-ap.conf 2>/dev/null; then
    echo "ERROR: /etc/hostapd/nightshift-ap.conf still contains CHANGE_ME placeholder." >&2
    exit 1
fi

# --- Backup ---

echo "==> Creating backup at $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
for f in /etc/mosquitto/conf.d/nightshift.conf \
         /etc/mosquitto/acl \
         /etc/nightshift-ap/dnsmasq.conf \
         /etc/systemd/system/nightshift-backend.service \
         /etc/systemd/system/nightshift-ap.service; do
    if [ -f "$f" ]; then
        mkdir -p "$BACKUP_DIR/$(dirname "$f")"
        cp "$f" "$BACKUP_DIR/$f"
    fi
done
echo "    Backup complete."

# --- Data directory ---

echo "==> Creating data directory"
mkdir -p "$DATA_DIR"
chown ubuntu:ubuntu "$DATA_DIR"

# --- dnsmasq config for AP ---

echo "==> Installing AP dnsmasq config"
mkdir -p /etc/nightshift-ap
cp deploy/dnsmasq/dnsmasq.conf /etc/nightshift-ap/dnsmasq.conf

# --- Mosquitto config ---

echo "==> Installing mosquitto config"
cp deploy/mosquitto/mosquitto.conf /etc/mosquitto/conf.d/nightshift.conf
cp deploy/mosquitto/acl /etc/mosquitto/acl
systemctl restart mosquitto

# --- systemd service ---

echo "==> Installing systemd service"
cp deploy/systemd/nightshift-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable nightshift-backend

# --- Done ---

echo "==> Deployment complete."
echo "    Backups at: $BACKUP_DIR"
echo "    To rollback: cp -a $BACKUP_DIR/* / && systemctl daemon-reload"
echo ""
echo "    Start services:"
echo "      systemctl restart nightshift-ap"
echo "      systemctl restart nightshift-backend"
