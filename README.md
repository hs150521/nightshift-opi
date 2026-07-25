# Nightshift Orange Pi 3B

Nightshift's authoritative backend for Orange Pi 3B 2G.

```text
GPIO4/5/6/7 -> ESP32-S3 -> Wi-Fi AP stillwork -> MQTT
             -> OPI state/services -> UART3 T5-Link -> T5 panel
```

The OPI does not read pressure GPIO or a light sensor. T5 never uses MQTT.
Missing/stale pressure input enters safe `IDLE + SENSOR_ERROR`; a valid
all-released input enters `NIGHT_EXEC` after three seconds, while either
pressure group enters `DAY_WORK` promptly.

## Interfaces

- `wlan0`: existing upstream STA, pinned to a 2.4 GHz BSSID so the single radio
  can host `ap0` on the same channel.
- `ap0`: `stillwork`, `192.168.51.1/24`, DHCP `.10-.100`.
- MQTT: `127.0.0.1:1883` for the backend and `192.168.51.1:1884` for ESP32 and
  the development console. Authentication and ACLs are required.
- T5: `/dev/ttyS3`, 460800 8-N-1, COBS + CRC-16/CCITT-FALSE.

Verified wiring:

| Orange Pi | T5 P11 | Direction |
|---|---|---|
| Pin 28 / UART3 TX | Pin 1 / P10 / UART0 RX | OPI -> T5 |
| Pin 27 / UART3 RX | Pin 2 / P11 / UART0 TX | T5 -> OPI |
| Pin 14 / GND | GND | common ground |

UART7 remains disabled because it conflicts with Ethernet MDIO.

## Local development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp deploy/.env.example .env
pytest -q
python apps/backend/main.py
```

Keep `.env` local. Development credentials may be plain text there for easy
debugging, but examples and Git history contain placeholders only.

## OPI deployment

Create Mosquitto users once (use `-c` only when the password file does not
already exist), prepare local configuration, then deploy:

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd nightshift-opi
sudo mosquitto_passwd /etc/mosquitto/passwd pressure-01
sudo mosquitto_passwd /etc/mosquitto/passwd nightshift-console

cp deploy/.env.example .env
# Fill NIGHTSHIFT_MQTT_PASSWORD with the local backend password.

sudo install -d /etc/hostapd
sudo install -m 600 deploy/hostapd/hostapd.conf /etc/hostapd/nightshift-ap.conf
# Fill wpa_passphrase while preserving the existing stillwork credentials.

sudo bash deploy/deploy.sh
```

The script backs up every replaced system file under
`/opt/nightshift-backups/<timestamp>`, installs the app at
`/opt/nightshift-opi`, creates its venv, installs AP/Mosquitto/systemd config,
and starts `nightshift-ap`, `mosquitto`, and `nightshift-backend`.

Health check:

```bash
ip -br addr
iw dev wlan0 link
iw dev ap0 info
systemctl --no-pager --full status nightshift-ap mosquitto nightshift-backend
ss -lntp
journalctl -u nightshift-backend -n 100 --no-pager
```

## Frozen contracts

- `contracts/uart/commands.yaml`
- `contracts/uart/golden_vectors.json`

The T5 repository must keep byte-identical copies. Check with:

```bash
python tools/check_cross_repo_contract.py --t5-path ../nightshift-t5
```
