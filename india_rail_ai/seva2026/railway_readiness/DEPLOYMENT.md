# Production deployment: Nexus RailGuard

How to run the service at a railway site. It is advisory decision support. It has no interface to signalling,
interlocking, Kavach/ATP or brakes, and none of the steps below adds one.

## 1. Shape of a deployment

```
 cab GNSS units ──signed batches──┐                       ┌── control screens (viewer token / named sessions)
 RTIS / NTES / COA (authorised) ──┤   TLS reverse proxy   ├── controllers (named sessions; decisions audited)
                                  └──►  (Caddyfile)  ◄────┘── cab units (run-scoped capability, live stream)
                                            │
                              railguard (one uvicorn worker, container)
                       /app/data  /app/models  /state (signed checkpoints)  /audit (hash chain)
                                            │
                                 NUT upsd on the host ── UPS (USB / network)
```

* **One active instance.** The digital twin is in-process state with a single writer. Availability comes from a
  hot standby on a second host that mounts the same `/state` (shared or replicated storage). On failover the
  standby restores the latest signed checkpoint, which is at most 60 s old, or 10 s on battery. Evidence then ages
  normally, so positions show as stale until the live feed refreshes them.
* **Nothing third-party is baked into the image.** Timetables, observed running and OpenStreetMap data are fetched and
  built at the site into `/app/data` (licences: see [../SOURCE_REGISTER.md](../SOURCE_REGISTER.md)).

## 2. Build data and models at the site

```bash
python -m india_rail current fetch && python -m india_rail current build       # every train, current timetable
python -m india_rail real fetch && python -m india_rail real build             # observed running (validation, ETA)
python -m india_rail real osm --pbf india-latest.osm.pbf --db current          # real track, line counts, geometry
python -m india_rail current pins --pbf india-latest.osm.pbf                   # station PIN codes
python -m india_rail freight build --pbf india-latest.osm.pbf                  # Dedicated Freight Corridors
python -m india_rail real validate                                             # trains the ETA model, writes evidence
python -m india_rail advisor build                                             # delay-minimisation findings
```

Every download is pinned by SHA-256. A mismatch stops the build.

## 3. Secrets and configuration

Copy `india_rail_ai/railguard.env.example` to `railguard.env`. Never commit it. Generate each secret with
`python -c "import secrets; print(secrets.token_hex(32))"`.

| Variable | Purpose |
|---|---|
| `RAILGUARD_VIEWER_TOKEN`, `RAILGUARD_CONTROLLER_TOKEN`, `RAILGUARD_FEED_TOKEN` | Role tokens (32+ characters, all different). Production refuses to serve without them. |
| `RAILGUARD_REQUIRE_ACCOUNTS=1` | Decisions need a named session. The shared controller token is refused for them. |
| `RAILGUARD_AUDIT_DIR` | Folder where the hash-chained audit log is kept (required in production): the decision record, the shadow trial and cab-link revocations survive a restart. Keep it 180 days or more (CERT-In). |
| `RAILGUARD_AUDIT_KEY` | HMAC on every audit event and snapshot. |
| `RAILGUARD_CHECKPOINT_KEY` | HMAC on state checkpoints. A tampered checkpoint is never restored. |
| `RAILGUARD_CAB_KEY` | Key for run-scoped cab links. If unset, it is derived from the controller token, so rotating that token revokes all cab links. One link, or all links of a train, is revoked from the console (**Revoke**). |
| `RAILGUARD_FEED_KEYS` | `SOURCE:key_id:hex,...`: one key per feed and per cab GNSS unit. |
| `RAILGUARD_UPS` | `<ups>@<host>[:3493]` for the NUT daemon. |
| `RAILGUARD_NTP` | `samay1.nic.in,time.nplindia.org` (three servers are better: a faulty one is outvoted): the clock is checked against NIC/NPL time every 5 minutes (CERT-In); more than 1 s off, agreed by a majority of the servers (or measured twice with one server), raises CLOCK_DRIFT on every console and fails readiness. |
| `RAILGUARD_REGISTER` | Path of the loop and block-section register built from Indian Railways documents (`python -m india_rail register build`, [IR_HANDOVER.md](IR_HANDOVER.md) step 4); re-checked on load. |
| `RAILGUARD_REGISTER_SHA256` | Optional: the SHA-256 of the register file that was reviewed and signed off; any other file is refused. |
| `RAILGUARD_ALLOWED_HOSTS` | Host names the service answers to. |
| `RAILGUARD_LIVE_CLOCK=1`, `RAILGUARD_TIMETABLE=current` | Twin clock follows IST; real current timetable. |

## 4. Start

```bash
docker build -t railguard:local india_rail_ai          # behind a TLS-inspecting proxy: --secret id=proxy_ca,src=ca.pem
docker compose -f india_rail_ai/docker-compose.railguard.yml up -d
docker compose -f india_rail_ai/docker-compose.railguard.yml exec railguard \
    python -m india_rail accounts add --username admin.x --name "X. Admin" --role admin   # asks for the password
```

The container runs as a non-root user (uid 10001). Its root filesystem is read-only, all capabilities are dropped
and `no-new-privileges` is set. It writes only to `/tmp`, `/state` and `/audit`. Its health check uses `/health/ready`.

What was verified in this project (Docker 29.8.2):

* the image builds;
* the container starts in production mode and is ready once the national twin has loaded;
* requests without a token are refused (403), and the interactive API documentation is not served;
* a signed checkpoint is written within a minute;
* after `docker restart` the container restores its state (`STATE_RESTORED` in the audit chain) and is ready again;
* no secret value appears in its logs.

## 5. Power: UPS through Network UPS Tools

Install NUT on the host (`apt install nut`). Then:

```
# /etc/nut/ups.conf          # /etc/nut/upsd.conf          # /etc/nut/nut.conf
[ups]                        LISTEN 127.0.0.1 3493          MODE=netserver
  driver = usbhid-ups        LISTEN 172.17.0.1 3493         # (docker bridge address for the container)
  port = auto
```

Set `RAILGUARD_UPS=ups@host.docker.internal`. Reads need no NUT account (`GET VAR` only). What the service does:

| UPS state | Service behaviour |
|---|---|
| `OL` (mains) | Normal. |
| `OB` (on battery) | `POWER_ON_BATTERY` warning on every console. State is checkpointed at once, then every 10 s. Prepare the standby site. |
| `LB` / `FSD`, or less than 300 s of runtime on battery | `POWER_CRITICAL`. Controller decisions are refused with a clear message (a decision must not be half-written when power fails). `/health/ready` fails, so the load balancer sends people to the standby. The feed keeps flowing into checkpoints. |
| NUT unreachable | `POWER_MONITOR_LOST` warning: a UPS that cannot be seen is not a UPS. |

## 6. Live feeds and cab units

* **Authorised feeds** (RTIS / NTES / COA) send signed batches to `POST /railguard/national/feed/batch`. See
  [LIVE_DATA_INTERFACE.md](LIVE_DATA_INTERFACE.md).
* **Cab GNSS units.** Each unit runs `python -m india_rail gnss --train N --start-date D --nmea /dev/ttyACM0`
  with its own source name and key (`RAILGUARD_AGENT_KEY`). A GNSS receiver outputs NMEA, and NavIC receivers are
  supported. Fixes are quality-gated on the unit, then:
  * map-matched onto the mapped track of the train's planned sections;
  * refused as spoofing or multipath if they jump or run backwards;
  * dropped if older than 3 minutes.
* **Cab displays.** A controller issues each unit a capability for its own run, valid 1–24 h:
  `POST /railguard/national/cab/{run}/token`, or **Issue cab link** in the national console. The unit then holds
  `GET /railguard/national/cab/{run}/stream`, a server-sent event stream that delivers that train's advisory the
  moment it changes.
  * The console's link is `/cab?run=<run>#cab=<capability>`. The capability travels in the URL fragment, which
    browsers never send to a server. The cab page moves it out of the address bar into the tab's session storage.
  * The cab screen holds no viewer or controller token: it can read its own train's advisory and nothing else.
  * If the stream goes silent for 25 s (the server speaks at least every 15 s), the screen shows
    `DATA UNAVAILABLE` and clears the speed band until the link is back. An expired or wrong link shows a
    message asking for a new one.

## 7. Monitoring and logs

* `GET /health/live`: the process is up. `GET /health/ready`: it can serve controllers safely. Use this one for the
  load balancer.
* `GET /metrics` (viewer token): Prometheus text. It covers requests by route and status, latency histograms,
  power level, checkpoint age, live stream count and active threats by type. Alert on `railguard_power_level >= 2`,
  `railguard_checkpoint_age_seconds > 180`, `railguard_twin_ready == 0`, and any rise in
  `railguard_threats_active{type="GNSS_IMPLAUSIBLE"}`.
* Logs are one JSON object per request: time, request id, method, route template, status, milliseconds. They never
  contain query strings, tokens, passwords or bodies. Uvicorn's own access log is off for the same reason.

## 8. Capacity measured

Load test on one 4-CPU machine: `python -m india_rail loadtest`. The service ran in its own process, as deployed,
on the real current timetable, with 2,537 trains running. Results:
[../evidence/live/loadtest.json](../evidence/live/loadtest.json).

## 9. Backups and records

* `/audit/*.jsonl` is the append-only hash chain of every decision, approval, login, account change, feed batch and
  restore. Ship it off-site daily. `GET /railguard/national/audit/{snapshot}/replay` re-derives any approved
  recommendation from its snapshot.
* Back up `/state/accounts.sqlite`. It holds password hashes and sessions; tokens are stored only as SHA-256.

## 10. What only the railway can do

* Authorise the live feeds and issue keys.
* Host the service on Indian Railways infrastructure and have it audited (CERT-In / STQC).
* Run the hazard workshop and the independent safety assessment.
* Run the shadow trial on a division before any operational use.

See [README.md](README.md).
