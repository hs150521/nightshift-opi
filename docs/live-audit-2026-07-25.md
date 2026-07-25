# Orange Pi live audit — 2026-07-25

## Pre-change backup

Before changing machine state, the live configuration and repository diff were
copied to:

```text
/opt/nightshift-backups/20260725-embedded-audit-pre
```

It contains the netplan, AP, hostapd, dnsmasq, Mosquitto, systemd, credential
file, and live repository patch needed to inspect or restore the prior state.

## Observed live state

- `eth0`: `192.168.50.1/24`
- `wlan0`: DHCP address `10.72.6.121/20`, default route through `10.72.0.1`
- upstream association: `ADVX-Players`, 5260 MHz (5 GHz)
- `ap0`: down, no `192.168.51.1/24`
- Mosquitto: active; loopback `127.0.0.1:1883` and configured AP listener
  `192.168.51.1:1884`
- `/dev/ttyS3`: present with `dialout` access
- live repository: `/home/ubuntu/nightshift-opi`, not `/opt/nightshift-opi`
- `nightshift-backend.service`: not installed

The AP had started successfully on 2.4 GHz earlier in the boot, then stopped
when the shared radio roamed to 5 GHz. At the same time the ESP32 reported
`NO_AP_FOUND`. Netplan already contained the intended 2.4 GHz band/BSSID pin,
but the running supplicant had not retained that association.

## Safety and current blocker

The live `/home/ubuntu/nightshift-opi` worktree contained unrelated edits from
another debugging session. They were backed up and left untouched. During
diagnosis the board rebooted externally or by watchdog; after boot, COM5 opened
successfully but produced no console output during repeated 30–45 second reads.
No repository deployment or service restart was attempted after that point.

Therefore the repository changes are tested, but these live acceptance items
remain pending on the physical OPI:

1. ensure `wlan0` stays on the pinned 2.4 GHz BSSID;
2. deploy from a clean/reconciled worktree into `/opt/nightshift-opi`;
3. verify `ap0`, DHCP, Mosquitto, backend, UART3, and reboot recovery;
4. observe authenticated ESP32 retained state and T5 HELLO/heartbeat/full sync.

## Rollback

Review the backup first, then restore only the required file rather than
blindly replacing the whole system. After restoring systemd files, run
`systemctl daemon-reload`; after restoring network/AP files, restart the
specific service from a local console to avoid losing upstream access.
