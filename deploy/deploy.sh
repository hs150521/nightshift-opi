#!/usr/bin/env bash
# deploy.sh — Deploy Nightshift OPI system services.
# Run as root on the Orange Pi 3B.
#
# IMPORTANT:
# - Does not replace wlan0, SSH, the default route, or DNS configuration.
# - Installs brcmfmac/wpa_supplicant drop-ins needed for stable shared-radio use.
# - Uses the ap0 virtual interface for the AP (shared radio with wlan0).
# - Requires local secrets to exist before installing configs.
# - Backs up all modified files before overwriting.
set -euo pipefail

INSTALL_DIR="/opt/nightshift-opi"
DATA_DIR="/var/lib/nightshift"
BACKUP_DIR="/opt/nightshift-backups/$(date +%Y%m%d-%H%M%S)"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${NIGHTSHIFT_PYTHON:-python3.11}"

# --- Preflight checks ---

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root." >&2
    exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON_BIN is required (override with NIGHTSHIFT_PYTHON)." >&2
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

if [ ! -f "$INSTALL_DIR/.env" ] && [ ! -f "$SOURCE_DIR/.env" ]; then
    echo "ERROR: local .env missing." >&2
    echo "  cp deploy/.env.example .env" >&2
    echo "  Edit .env with the local MQTT password, then rerun deploy.sh." >&2
    exit 1
fi

# --- Backup ---

echo "==> Creating backup at $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
for f in /etc/mosquitto/conf.d/nightshift.conf \
         /etc/mosquitto/acl \
         /etc/mosquitto/passwd \
         /etc/systemd/system/mosquitto.service.d/nightshift-network.conf \
         /etc/nightshift-ap/dnsmasq.conf \
         /etc/hostapd/nightshift-ap.conf \
         /etc/systemd/system/nightshift-backend.service \
         /etc/systemd/system/nightshift-ap.service \
         /etc/sysctl.d/90-nightshift-ap.conf \
         /etc/modprobe.d/90-nightshift-brcmfmac.conf \
         /etc/systemd/system/netplan-wpa-wlan0.service.d/nightshift-p2p.conf \
         /usr/local/sbin/nightshift-ap-start \
         /usr/local/sbin/nightshift-ap-stop \
         /usr/local/sbin/nightshift-ap-down \
         "$INSTALL_DIR/.env" \
         "$DATA_DIR/nightshift.db"; do
    if [ -f "$f" ]; then
        mkdir -p "$BACKUP_DIR/$(dirname "$f")"
        cp "$f" "$BACKUP_DIR/$f"
    fi
done
echo "    Backup complete."

# --- Application and data ---

echo "==> Installing application at $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$DATA_DIR"
if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
    cp -a "$SOURCE_DIR/apps" "$INSTALL_DIR/"
    cp -a "$SOURCE_DIR/contracts" "$INSTALL_DIR/"
    cp -a "$SOURCE_DIR/nightshift" "$INSTALL_DIR/"
    cp -a "$SOURCE_DIR/tools" "$INSTALL_DIR/"
    cp -a "$SOURCE_DIR/pyproject.toml" "$INSTALL_DIR/"
    cp -a "$SOURCE_DIR/README.md" "$INSTALL_DIR/"
    if [ -f "$SOURCE_DIR/.env" ]; then
        install -m 0600 "$SOURCE_DIR/.env" "$INSTALL_DIR/.env"
    fi
fi
chown ubuntu:ubuntu "$DATA_DIR"
chown -R ubuntu:ubuntu "$INSTALL_DIR"

if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
    sudo -u ubuntu "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi
sudo -u ubuntu "$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR"

# --- AP service and shared-radio networking ---

echo "==> Installing AP service and scripts"
mkdir -p /etc/nightshift-ap
cp "$SOURCE_DIR/deploy/dnsmasq/dnsmasq.conf" \
    /etc/nightshift-ap/dnsmasq.conf
install -m 0755 "$SOURCE_DIR/deploy/scripts/nightshift-ap-start" \
    /usr/local/sbin/nightshift-ap-start
install -m 0755 "$SOURCE_DIR/deploy/scripts/nightshift-ap-stop" \
    /usr/local/sbin/nightshift-ap-stop
install -m 0755 "$SOURCE_DIR/deploy/scripts/nightshift-ap-down" \
    /usr/local/sbin/nightshift-ap-down
install -m 0644 "$SOURCE_DIR/deploy/systemd/nightshift-ap.service" \
    /etc/systemd/system/nightshift-ap.service

install -d -m 0755 /etc/sysctl.d
install -m 0644 "$SOURCE_DIR/deploy/sysctl/90-nightshift-ap.conf" \
    /etc/sysctl.d/90-nightshift-ap.conf
sysctl -p /etc/sysctl.d/90-nightshift-ap.conf

install -d -m 0755 /etc/modprobe.d
install -m 0644 "$SOURCE_DIR/deploy/modprobe/90-nightshift-brcmfmac.conf" \
    /etc/modprobe.d/90-nightshift-brcmfmac.conf
install -d -m 0755 /etc/systemd/system/netplan-wpa-wlan0.service.d
install -m 0644 \
    "$SOURCE_DIR/deploy/systemd/netplan-wpa-wlan0-nightshift.conf" \
    /etc/systemd/system/netplan-wpa-wlan0.service.d/nightshift-p2p.conf

# --- Mosquitto config ---

echo "==> Installing mosquitto config"
cp "$SOURCE_DIR/deploy/mosquitto/mosquitto.conf" \
    /etc/mosquitto/conf.d/nightshift.conf
cp "$SOURCE_DIR/deploy/mosquitto/acl" /etc/mosquitto/acl
install -d -m 0755 /etc/systemd/system/mosquitto.service.d
install -m 0644 "$SOURCE_DIR/deploy/systemd/mosquitto-nightshift.conf" \
    /etc/systemd/system/mosquitto.service.d/nightshift-network.conf

# --- systemd services ---

echo "==> Installing systemd services"
cp "$SOURCE_DIR/deploy/systemd/nightshift-backend.service" \
    /etc/systemd/system/
systemctl daemon-reload
systemctl reset-failed nightshift-ap mosquitto nightshift-backend
systemctl enable nightshift-ap mosquitto nightshift-backend
systemctl restart nightshift-ap
systemctl restart mosquitto
systemctl restart nightshift-backend

# --- Done ---

echo "==> Deployment complete."
echo "    Backups at: $BACKUP_DIR"
echo "    To rollback: cp -a $BACKUP_DIR/* / && systemctl daemon-reload"
echo ""
echo "    Services started: nightshift-ap, mosquitto, nightshift-backend"
