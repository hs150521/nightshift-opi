# Nightshift v2 — Gap Analysis, Frozen Decisions, Cross-Repo Checklist

Working baseline commit: `80115fa` (docs: T5 P11 pin correction).
Author: OPI agent, per user decisions on the pressure-over-MQTT architecture.

This document supersedes the light-sensor rule. It is the source of truth for
the current cross-repo effort until it is closed out by a follow-up doc.

---

## 1. Frozen decisions

### 1.1 UART / T5-Link (commands.yaml is authoritative for both repos)

- `MODE_SET.reason` is **u8**. OPI currently encodes u32; fix OPI.
- `WORK_STATE_SET` payload gains a **u32 `revision` prefix**. T5 side must
  add a revision guard (monotonic; ignore older revisions).
- Heartbeat schema is **unchanged**; response payload is fixed at **14 bytes**
  (`state:u8, mode:u8, revision:u32, tokens_in:u32, tokens_out:u32`). OPI
  currently checks `< 10` — fix to `< 14`.
- ACK frames for panel-originated commands must echo the **original sequence
  number** (currently OPI calls `send_no_wait(...)` which allocates a new seq).
- Startup handshake: OPI sends HELLO on connect; on inbound HELLO from panel
  (panel reboot) OPI re-emits the full snapshot.

Cross-repo release rule: any breaking wire change lives on a branch in each
repo and only lands when both branches pass the shared golden-vector suite.
No OPI-only merge for wire changes.

### 1.2 System state schema

- Single schema version cutover: `nightshift.system-state.v1` → `v2`.
- No dual-publish, no migration window. The retained `state` topic is
  overwritten with v2 the first time v2 backend runs.
- Delete all v1 code once v2 is in.

### 1.3 IDs

- `task_id`, `notice_id` are SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`,
  exposed on the wire as **u32**. `0` is reserved for "no object".
- `request_id`, `event_id` are UUIDv4 strings.

### 1.4 Persistence

- Database path: `/var/lib/nightshift/nightshift.db` (WAL mode).
- systemd unit uses `StateDirectory=nightshift`.
- Tests override via `NIGHTSHIFT_DB_PATH`.

### 1.5 ESP32 pressure node

- Repo: `hs150521/nightshift-esp32` (separate agent).
- Wi-Fi: SSID `stillwork`, WPA2-PSK. AP `192.168.51.1/24`.
- Broker: `192.168.51.1:1884`. Credentials: `pressure-01` / *(see dev secrets)*.
- `device_id` = `pressure-01`.
- State topic: `nightshift/v1/sensor/pressure/pressure-01/state`.

Frozen state payload:

```json
{
  "schema": "nightshift.pressure-state.v1",
  "device_id": "pressure-01",
  "boot_id": "a1b2c3d4",
  "seq": 128,
  "uptime_ms": 372810,
  "gpio": {"4": true, "5": false, "6": true, "7": true},
  "cushion": true,
  "footrest": true,
  "present": true
}
```

Semantics (ESP32 side):

- `cushion = gpio4 OR gpio5`
- `footrest = gpio6 OR gpio7`
- `present = cushion OR footrest`
- Publish on every logical change **and** every 3 seconds as a full resend.
- No sensor diagnostics (no open-circuit / short / saturation / stuck detection).

OPI side:

- Stamp `received_at_ms` with `time.monotonic_ns()` on receipt.
- Any state older than **10 seconds** or missing → mark `pressure_valid=false`.
- Track `(boot_id, seq)` for staleness/reorder rejection; on `boot_id` change
  accept any `seq`.

### 1.6 State machine v2

| Input | Mode | Attention |
|---|---|---|
| No valid pressure yet, or ESP32 offline, or pressure state older than 10s | `IDLE` | `SENSOR_ERROR` (or closest input-unavailable flag) |
| `cushion=true` (regardless of footrest) | `DAY_WORK` | none |
| `cushion=false and footrest=true` | `DAY_WORK` | none |
| `cushion=false and footrest=false` continuously for **3 s** | `NIGHT_EXEC` | none |

Rules:

- The 3-second all-released dwell lives **only on OPI**. ESP32 debounce is
  not a mode dwell.
- Transition `NIGHT_EXEC → DAY_WORK` is immediate on the first stable
  triggered input (no second 3-s delay).
- Loss of pressure validity while in any mode → back to `IDLE` with
  attention flag. Never map "offline" to "all released" and enter
  `NIGHT_EXEC`.

### 1.7 MQTT idempotency

- Server-computed digest. Client does not transmit `content_digest`.
- Digest input: canonical JSON of `{schema, client_id, command, args}` with
  sorted keys, no whitespace, then `SHA-256`.
- Cache `(request_id → (digest, reply))` with 60-second TTL.
- Same `request_id` + same digest → return cached reply.
- Same `request_id` + different digest → error `idempotency_conflict`,
  no execution.

### 1.8 MQTT identities and dev credentials

Real values live in `.env` and `/etc/mosquitto/passwd` on the box. Repo
holds placeholders only.

| Client | Username | Purpose |
|---|---|---|
| ESP32 pressure node | `pressure-01` | Publish availability/state/telemetry only |
| OPI backend | `nightshift-opi` | Full backend topics + subscribe pressure/# |
| Dev console | `nightshift-console` | Read state/event/telemetry, publish command, read own reply |

Dev passwords were provided out-of-band and installed to
`/etc/mosquitto/passwd` on this host. Not committed. Repo templates use
placeholder `changeme`.

### 1.9 Network scope

- ESP32 lives on AP subnet `192.168.51.0/24` and uses listener
  `192.168.51.1:1884` only.
- eth0 (`192.168.50.0/24`) is reserved for wired T5 side link, unused for
  ESP32.
- No NAT / no forwarding across subnets.
- Do not expose 1884 on the STA (Internet-facing) address.

---

## 2. Current gaps (OPI repo, from audit)

| Area | Current state | Gap | Phase |
|---|---|---|---|
| Config env | Has `NIGHTSHIFT_GPIO_LIGHT_*`, no pressure vars | Remove GPIO_LIGHT; add PRESSURE_* | 4, 3 |
| Domain models | `EnvironmentState.light`, no `PressureState`, `system-state.v1` | Add `PressureState`, cut to v2, drop `light` | 2 |
| Mode logic | `derive_mode` reads `light` and inverts | Rewrite per §1.6 | 4 |
| Pressure adapter | Missing | New `MqttPressureSensorAdapter` + `MockPressureSource` | 3 |
| Command handler | `request_id` cache only, no digest | Add server-side digest per §1.7 | 5 |
| Task/notice services | Whitelisted commands return `not_found` stubs | Real SQLite-backed services | 6 |
| Telemetry publisher | Topic in `TopicBuilder`, no publisher wiring | Add periodic publish | 5 |
| UART protocol | `MODE_SET.reason` u32; `WORK_STATE_SET.revision` missing; heartbeat length check `<10`; ACK uses new seq | Fix per §1.1 | 7 |
| UART gateway | No re-handshake on inbound HELLO | Add HELLO handler + resnapshot | 7 |
| Persistence | None | Sqlite `/var/lib/nightshift/nightshift.db` | 6 |
| Tests | `tests/` missing | pytest suite for schemas, adapter, state machine, protocol golden, command handler | 3-7 |
| Docs | README has light sensor wiring | Rewrite | 8 |

Two audit-report inaccuracies flagged and corrected here:
- STA is on **netplan + wpa_supplicant** (NetworkManager is `managed=false`);
  changes go through `/etc/netplan/99-nightshift.yaml`.
- AP is **hostapd + dnsmasq** via `nightshift-ap.service` (the system
  `hostapd.service` unit is masked to avoid conflict; our unit runs the
  binary directly with `-B`). Do not unmask the system unit.

---

## 3. Phased plan (OPI side)

Ordering respects the "do not break running STA / AP / UART / Mosquitto" rule.

1. **Docs freeze** — this file lands first (current commit).
2. **Contract freeze** — `contracts/uart/commands.yaml` + regenerated
   `golden_vectors.json` reflect the fixed widths. Land on both repos'
   branches before any code change.
3. **Pressure model + mock adapter + tests** — additive, no runtime effect.
4. **State machine v2 + light sensor deletion** — single atomic commit;
   remove `EnvironmentState.light`, replace `derive_mode` with the v2 table.
5. **Command handler digest idempotency** — additive; test-driven.
6. **Persistence + real task / notice / confirmation services** — sqlite;
   wire the seven whitelisted commands.
7. **UART protocol fixes** — behind matching T5 branch; do not merge to main
   until T5 branch passes shared golden vectors.
8. **Docs + `.env.example`** — reflect the whole cutover.
9. **Reboot smoke test** — proves the whole stack survives cold boot.

Every phase commits standalone with a clear rollback (`git revert <sha>`).

---

## 4. Cross-repo checklist (T5 side, tracked here for the T5 agent)

T5 branch `feat/uart-v2` must:

- [ ] Accept `MODE_SET.reason` as **u8** (was u32).
- [ ] Accept `WORK_STATE_SET` with **u32 `revision` prefix**; add revision
      guard: if incoming `revision < current`, drop; if `==`, treat as
      idempotent; if `>`, apply.
- [ ] Emit heartbeat response as **exactly 14 bytes**:
      `state:u8 | mode:u8 | revision:u32 | tokens_in:u32 | tokens_out:u32`.
- [ ] Preserve `sequence` from panel-originated request in the ACK.
- [ ] On panel reboot / power-on, send HELLO; expect OPI to re-emit the
      full snapshot; drop own retained UI cache first.
- [ ] Bind `ATTENTION_SET.short_message` to a visible label (currently
      only `attention_flags` drives the LED; short_message is discarded).
- [ ] Load a CJK-capable LVGL font, or convert all UI labels to ASCII;
      the current build shows tofu for Chinese strings under Montserrat.

Both branches merge only after `tests/test_protocol_golden.py` passes in
OPI **and** the equivalent C-side vector test passes in T5.

---

## 5. Cross-repo checklist (ESP32 side, tracked here for the ESP32 agent)

ESP32 branch must:

- [ ] Wi-Fi STA to `stillwork` / `haowenti` (WPA2-PSK), obtain DHCP on
      `192.168.51.0/24`.
- [ ] MQTT client to `192.168.51.1:1884`, username `pressure-01`, password
      from device NVS / build-time secret (never committed).
- [ ] LWT: publish
      `nightshift/v1/sensor/pressure/pressure-01/availability` with
      `{"schema":"nightshift.sensor-availability.v1","device_id":"pressure-01","online":false}`,
      retain=true, qos=1, set as MQTT will before connecting.
- [ ] On connect, publish availability `online=true` retain=true qos=1
      with `boot_id`, `version`, `started_at_ms`.
- [ ] Publish `nightshift.pressure-state.v1` per §1.5 on every logical
      change and every 3 seconds regardless.
- [ ] Publish telemetry (`nightshift.pressure-telemetry.v1`) every 30 s,
      qos 0 or 1, not retained.
- [ ] No sensor diagnostics (open / short / saturation / stuck).
- [ ] Debounce is a raw digital debounce only, ~20 ms, not a mode dwell.

---

## 6. Test evidence (updated as phases land)

- [ ] Phase 2 (contract): `pytest tests/test_protocol_golden.py -q`
- [ ] Phase 3 (pressure): `pytest tests/test_pressure_adapter.py -q`
- [ ] Phase 4 (state machine): `pytest tests/test_state_machine.py -q`
- [ ] Phase 5 (command): `pytest tests/test_command_handler.py -q`
- [ ] Phase 6 (services): `pytest tests/test_tasks.py tests/test_notices.py -q`
- [ ] Phase 7 (uart wire fixes): `pytest tests/test_protocol_golden.py -q` after regenerated vectors
- [ ] Phase 9 (reboot smoke): journal excerpt showing STA + AP + Mosquitto + nightshift up in order

---

## 7. Do-not-do list

- Do not commit real MQTT passwords. Placeholders only.
- Do not unmask the system `hostapd.service` unit. Our own
  `nightshift-ap.service` owns the hostapd process.
- Do not touch `/etc/netplan/99-nightshift.yaml` (STA config).
- Do not add NAT / IP forwarding for AP clients.
- Do not add TLS to Mosquitto in dev.
- Do not modify UART wiring or the `rk3566-orangepi-3b-uart3.dtbo`
  overlay.
- Do not double-publish v1 alongside v2.
- Do not add sensor-fault logic to ESP32.
- Do not merge OPI-side wire changes without the paired T5 branch passing
  the same golden vectors.
