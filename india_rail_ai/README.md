# India Rail AI

Planning automation for Indian Railways traffic control, built on open data:

1. **Data pipeline.** It ingests the open Indian Railways timetable (about 9,000 stations, 5,200 trains and 394,000 timed stops) into SQLite, with every source file's SHA-256 pinned. The national twin runs on **real data**: the September 2024 timetable with every train's observed running days, and real track data from OpenStreetMap. It is verified against 1.26 million actual arrival times ([Real-life data and verification](#real-life-data-and-verification)).
2. **ML run-time model.** Gradient-boosted trees predict how many minutes a train needs between two stops, with a calibrated P10–P90 interval.
3. **Disruption planner.** When a train runs late, it spreads the delay through the network, finds trains that would come too close, and proposes priority-based holds to restore separation.
4. **Assistant.** Answers questions like "which trains run Delhi to Mumbai?" or "12002 is 30 minutes late at NDLS — what should we hold?" by calling all of the above. It's free by default: built-in offline, or a local open-source AI model.

**Cost: nothing.** The data is public domain (CC0) or open (ODbL). All code and libraries are open source. Everything runs on your own computer with no account, API key or subscription. The only paid option is the Claude assistant; it's off unless you choose it by name and use your own key.

## What "automation" means here

This automates the **planning work of a section controller**: noticing a knock-on conflict, choosing who waits, and working out the effect. Every plan comes back as `PROPOSED_FOR_CONTROLLER_REVIEW`. Nothing here connects to signalling, interlocking, Kavach or a locomotive. Those are safety-critical (SIL-4) systems that need RDSO/CRIS certification and authorised data feeds. The path from this prototype to field use is in [Next steps](#next-steps-towards-real-deployment).

## Quick start

```sh
cd india_rail_ai
pip install -r requirements.txt
python -m india_rail setup            # download + verify data (~100 MB), build DB, train model (~4 min)
python -m india_rail summary
python -m india_rail plan 12002 NDLS 30          # Shatabdi 30 min late at New Delhi
python -m india_rail slack 12951                 # where the Mumbai Rajdhani timetable has padding
python -m india_rail serve                       # HTTP API on http://127.0.0.1:8100/docs
python -m india_rail ask "trains from New Delhi to Howrah"     # free assistant
python -m india_rail ask "12002 is 30 min late at NDLS"
python -m india_rail ask                         # interactive session
```

Tests run offline on a hand-made three-station network: `python -m pytest -q`.

## Data

| Source | Contents | Licence | Status |
|---|---|---|---|
| [DataMeet `stations.json`](https://github.com/datameet/railways) | 8,990 stations with code, zone, state and coordinates | CC0 | Ingested, SHA-256 pinned |
| [DataMeet `trains.json`](https://github.com/datameet/railways) | 5,208 trains with type, zone, classes, distance and route geometry | CC0 | Ingested, SHA-256 pinned |
| [DataMeet `schedules.json`](https://github.com/datameet/railways) | 417,080 stop rows (arrival, departure, day) | CC0 | Ingested, SHA-256 pinned |
| **September 2024 timetable and actual running** (IIT Kharagpur research dataset, IEEE T-ITS 2026) | 3,892 trains; 1.28M *actual* arrival times over 57,485 real train runs | No licence; research use with citation | `python -m india_rail real fetch && ... real build`: SHA-256 pinned, kept in git-ignored `data/`, never redistributed. Used for real running days and to verify the system |
| **Current all-India timetable** (community GTFS by P. Radha Krishna, valid 30 Aug–30 Sep 2026) | 10,594 trains with every halt, time, running days and validity dates; IRCTC-operated, Bharat Gaurav, tourist and parcel trains flagged | No licence stated | `python -m india_rail current fetch && ... current build`: SHA-256 pinned, kept in git-ignored `data/`, never redistributed. The national twin's default timetable; replaced by the CRIS timetable when authorised |
| **OpenStreetMap India extract** (`download.openstreetmap.fr`, MD5-verified) | 101,805 mapped running-line ways, 10,314 stations (93% with their IR code) | ODbL | `python -m india_rail real osm --pbf ...`: real line count, electrification, gauge, speed limits and station positions per section |
| NTES / COA / FOIS / ICMS | Live running, control charts, freight, crew | Indian Railways (no open API) | Needs an authorised data-sharing agreement. Not scraped |

**Data quality**, from the ingest report:

- 443 duplicate stop listings were removed. Some trains appear twice under different row IDs, which would otherwise splice into a looping train.
- 22,508 untimed rows were dropped.
- 780 small backward clock steps (for example 08:30 followed by 08:29) were clamped rather than read as a 24-hour section.
- 1,220 rows disagree with the published `day` field. Spot checks show the published day is the faulty field: train 59298 increments its day at most stops within four hours.

The open timetable is a **community snapshot from about 2016** with **no running-days field**. The national twin therefore runs on the **September 2024 timetable** instead whenever it has been built (`RAILGUARD_TIMETABLE=real`, required in production): every train's running days come from the days it was actually seen running, and the line count of each section from OpenStreetMap. See [Real-life data and verification](#real-life-data-and-verification).

## ML model: section run time

- **Target:** the scheduled minutes between consecutive timed points (383,192 sections, 5,184 trains).
- **Validation:** 5-fold `GroupKFold` with a train and its return working kept together, so every scored train is unseen during training.
- **No target leakage:** section averages are rebuilt inside each fold from the training trains only.
- **Method:**
  - Gradient-boosted trees learn the *difference* from the section's typical run time. Trees group each input into at most 255 bins, so they can't reproduce an exact typical value; learning only the correction avoids that.
  - P10 and P90 quantile models give the interval, checked with split-conformal calibration (CQR).

- **Features chosen by measured training rounds** (`python -m india_rail.training`, log in `models/training_log.json`): section priors by train type and direction, the spread of run times on the section, the train's pace on the two sections either side (leave-one-out), a type-specific starting point, and whole-minute rounding. Before any round, 15% of train groups were locked away as a final test and scored once at the end.

| Model (5-fold grouped CV, all data) | Mean abs. error | Error on sections ≥10 min | Within 2 min |
|---|---|---|---|
| Speed by train type (baseline) | 2.57 min | 31.3% | 64.0% |
| Median of other trains on the same section (baseline) | 1.95 min | 24.9% | 80.4% |
| Gradient boosting, new path (no train context) | 1.68 min | 21.3% | 83.7% |
| **Gradient boosting, existing train** | **1.39 min** | **16.5%** | **88.0%** |

- Locked test set (58,110 sections of 767 trains never used in any round): **1.378 min vs 1.957** for the section median (−30%), 88.1% vs 80.1% within 2 minutes.
- The P10–P90 interval covers **80.0%** of held-out sections against an 80% target, with a mean width of 3.9 minutes (was 5.4).
- **Honest read:** timetables are whole minutes with operator-chosen allowances, so zero error is not reachable from public data. The model learns **planned** run times; delay prediction needs NTES-style actual running data, which the live-feed gateway is built to receive.
- Full metrics are in [`models/runtime_model_metrics.json`](models/runtime_model_metrics.json).

## Disruption planner

The planner works the way a controller does:

1. **Spread the delay.** It carries the delay along the late train's remaining route. On each section it recovers half of (scheduled time − the model's P10). At each halt it can shorten the stop down to 2 minutes.
2. **Check every section entry.** It compares the late train with every other train entering the same section. The separation it requires is `min(headway, the separation the published timetable already plans for that pair)`. The timetable is taken as feasible, so only gaps the disruption makes *worse* count as conflicts.
3. **Choose who waits.** The lower-priority train is held at the station before the section. The default ranking is Rajdhani/Shatabdi/Duronto, then SF/Garib Rath, then Mail/Express, then Passenger/MEMU; it's configurable. A held train is re-planned in turn, up to 30 trains.

Results from the real timetable (6-minute headway):

| Disruption | Conflicts | Trains held | Delay at destinations (sum) | Runtime |
|---|---|---|---|---|
| 12951 Mumbai Rajdhani, +20 min at BRC | 2 | 2 | 0.4 min | 0.5 s |
| 12002 Bhopal Shatabdi, +30 min at NDLS | 34 | 12 | 1.2 min | 1.9 s |
| 12259 Duronto, +60 min at SDAH | 87 | 27 | 43 min | 4.2 s |
| 12301 Howrah Rajdhani, +45 min at CNB | 342 | 29 | 205 min | 4.6 s |

Large delays on the Delhi–Howrah and Delhi–Mumbai trunk routes can cascade past the 30-train limit. Those cases are listed under `unresolved` rather than dropped. Because the planner chooses who waits one conflict at a time, it isn't an optimiser. A mixed-integer or constraint-programming re-scheduler is the natural next step once track-count and loop-line data are available.

## Assistant

All three assistants share the same nine read-only tools in `india_rail/tools.py`:
- train and station search;
- schedule, trains between stations, station board;
- busiest sections, fastest path;
- timetable slack;
- the disruption planner.

None of them can change anything; plans are proposals.

| Provider | Cost | Needs | Understands |
|---|---|---|---|
| `offline` | Free | Nothing | The common question types: delays/holds, trains between stations, fastest route, schedule, station board, busiest sections, slack, train/station search |
| `ollama` | Free | [Ollama](https://ollama.com) installed, then `ollama pull qwen2.5:7b` (about 5 GB; runs on a laptop CPU, faster with a GPU) | Free-form questions, with the model calling the tools itself |
| `claude` | **Paid** (Anthropic API, your own key) | `ANTHROPIC_API_KEY` | Free-form questions, strongest reasoning |

- `--provider auto` (the default) uses Ollama if it's running and the offline assistant otherwise. It never picks the paid option.
- Choose a different local model with `OLLAMA_MODEL=llama3.1:8b`.
- The HTTP API refuses `provider: "claude"` unless the server sets `INDIA_RAIL_ALLOW_PAID_ASSISTANT=1`, so nobody can run up charges on a shared server.
- The tests run the offline assistant on a miniature network and the Ollama and Claude tool loops against mocked servers.

## Nexus RailGuard (SEVA 2026 build)

`india_rail/railguard/` is a controller decision-support and driver-advisory layer with two digital twins:
- **National twin:** runs on **real data**: the September 2024 timetable (3,549 trains, 9,065 sections between halts, 2,000+ junctions), every train's running days as observed, station positions and single/double line from OpenStreetMap on 90% of sections, and rail distances from the timetable. Every attribute is labelled with its evidence. Without the real data it falls back to the 2016 open timetable (production refuses that). Console: `/control/national`.
- **Tabletop twin:** two trains on ten sections, with the TwinTrack ESP32 node and six judge scenarios. Console: `/control`; driver screens: `/cab?train=A|B` or `/cab?run=<train>@<day>`.

The parts:
- **Planner:** CONTINUE, HOLD, PATH-THROUGH, PRIORITY (lower-priority trains re-pathed) and REROUTE options. It makes lower-priority trains yield to resolve conflicts, then ranks on seven visible factors.
- **EvidenceGate:** stale or missing evidence fails closed. Projections without a live feed are PLANNING_ONLY rehearsals.
- **Approval:** only a named controller can approve, and only the latest ranking for the current state.
- **Cab:** each driver sees only the approved plan.
- **Audit:** a hash chain (optional HMAC, persisted) records every decision, and each decision replays to the same ranking.
- **Live-feed gateway** (`livefeed.py`): accepts signed RTIS/NTES/COA-style batches, protects against replays, map-matches positions, and turns late station events into disruptions for the controller. It is ready for authorised data.
- **Simulation** (`simulate.py`): randomised operation sequences on both twins, with eight safety invariants checked after every operation. The main run checked 5,068,492 operations and found one last defect, now fixed. On the final code with real data and the learned forecast attached, 236,000 episodes (3,187,925 operations, 200,000 of them on the real national network) ran with 0 violations, after the simulation caught one defect in the new forecast code. All runs together: 9,868,852 checked operations. See [`seva2026/AUDIT_LOG.md`](seva2026/AUDIT_LOG.md).

Security: role tokens, fail-closed production mode, strict request schemas, CSP, rate limits, and a signed feed. See [SECURITY.md](SECURITY.md). Compliance with the Railways Act / G&SR, RDSO and EN 50716, the IT Act, CERT-In, DPDP and the data licences is covered in [seva2026/COMPLIANCE_REGISTER.md](seva2026/COMPLIANCE_REGISTER.md). The full report is [seva2026/ClearPath_Nexus_RailGuard_Report.pdf](seva2026/ClearPath_Nexus_RailGuard_Report.pdf).

Start with [seva2026/START_HERE.md](seva2026/START_HERE.md). The tabletop ESP32 node is in [hardware/twintrack_esp32](hardware/twintrack_esp32/README.md); it is written but not yet bench-tested.

## Production build (October 2026)

| Capability | What it does | Evidence |
|---|---|---|
| **Every train, every track** | Registry of 10,594 current trains: number, name, operator (IRCTC private, Bharat Gaurav, tourist, parcel), running days, validity, every halt with its station PIN code (5,073 stations, approximate from OSM postcodes), and each train's route drawn along the mapped track (GeoJSON). `GET /railguard/national/trains?q=`, `/trains/{n}`, `/trains/{n}/route`, `/stations/{code}`, `/operators` | `tests/test_current.py` |
| **Freight corridors** | Eastern and Western DFC from OpenStreetMap; conflict-free freight pathing (headway, loops, single-line crossings, blocks) with an independent checker. `POST /railguard/freight/plan` | 0 violations in 200 randomised days (33,475 trains): `seva2026/evidence/freight/` |
| **GNSS tracking** | NMEA from any GPS/NavIC receiver, quality gates, map-matching onto mapped track (yards, horseshoe curves), spoof/jump rejection (`GNSS_IMPLAUSIBLE`), device agent signing batches: `python -m india_rail gnss` | Real network, every running train, simulated receivers: 99.66% of genuine fixes accepted, 0.02% false alarms, 100% of jumps and teleports refused: `seva2026/evidence/gnss/` |
| **Delay advisor** | Where delay is made, from real running: chronic section losses with the lever (capacity on single line, operations on double), junction congestion by hour, late starts, timings no train achieves, chronically late trains. `GET /railguard/national/advisor/...` | Findings persist on held-out days (92% of the worst 50 sections recur): `seva2026/evidence/real_data/delay_advisor_summary.json` |
| **Forecasts under different situations** | Rolling-origin retraining (5 rounds), scored by time of day, weekday, current delay, class, line type, horizon, zone, network state, cold start and feed noise; deployed model trained for cold start (72% of current trains have no observed history) | Beats both baselines in 44/44 situations: `seva2026/evidence/real_data/scenario_ml.json` |
| **Power (UPS)** | Network UPS Tools: on battery warn + checkpoint every 10 s; low battery pause approvals and fail readiness | `tests/test_ops.py` (fake NUT server) |
| **Checkpoints, health, metrics, logs** | Signed atomic checkpoints restored on start; `/health/live`, `/health/ready`, Prometheus `/metrics`; JSON access logs without secrets | Container restart restores state: [DEPLOYMENT.md](seva2026/railway_readiness/DEPLOYMENT.md) |
| **Live one-to-one** | Server-sent event streams: console picture and each cab's own advisory, pushed on change; run-scoped cab capability tokens | 550 concurrent streams on the real network, push p50 0.35 s: `seva2026/evidence/live/loadtest.json` |
| **Named accounts** | scrypt passwords, lockout, hashed sessions, roles (viewer/controller/admin); decisions record the signed-in person; `RAILGUARD_REQUIRE_ACCOUNTS=1` | `tests/test_accounts.py`, `tests/test_attacks_live.py` |
| **Container** | Non-root, read-only root filesystem, digest-pinned base, health check: `Dockerfile`, `docker-compose.railguard.yml` | Built and run in production mode |

## Real-life data and verification

```sh
python -m india_rail real fetch                              # observed running, Sep 2024 (SHA-256 pinned)
python -m india_rail real build                              # data/real.sqlite: 2024 timetable, real running days
python -m india_rail real osm --pbf data/raw/osm/india.osm.pbf   # real track data from OpenStreetMap
python -m india_rail real validate                           # verify against what actually happened
```

The verification ([`seva2026/railway_readiness/REAL_DATA_VALIDATION.md`](seva2026/railway_readiness/REAL_DATA_VALIDATION.md), generated from [`seva2026/evidence/real_data/real_validation.json`](seva2026/evidence/real_data/real_validation.json)) uses 56,395 real train runs with 1.26 million actual arrival times. It checks the data against the Ministry of Railways' published punctuality; scores delay forecasts forward in time on days the model never saw; tests whether the twin's conflict warnings precede real time loss; and replays a real morning through the signed live-feed gateway. Running on real data found ten defects, all fixed (`seva2026/AUDIT_LOG.md`, pass 6). Late trains reported by the feed are now projected with the forecast learned from real running (`railguard/eta.py`, `GET /railguard/national/eta/{run}`).

The observed-running data has no licence beyond research use with citation, so it is never committed or redistributed: each user fetches it, it is checked by SHA-256 and stays in git-ignored `data/`. OpenStreetMap data is ODbL.

## HTTP API

Run `python -m india_rail serve`; the endpoint docs are at `/docs` (disabled when `RAILGUARD_MODE=production`). With role tokens configured, send `Authorization: Bearer <token>`.

- `GET /health`
- `GET /trains/search?q=`, `/trains/{number}`, `/trains/{number}/slack`
- `GET /stations/search?q=`, `/stations/{code}/board`
- `GET /between?origin=&destination=`, `/sections/busiest`, `/path`
- `POST /plan/disruption`, `POST /assistant/ask`
- RailGuard: `/railguard/...` (tabletop) and `/railguard/national/...` (summary, network, positions, runs, plan, cab, disrupt, recommend, approve, tick, section, replay, `feed/batch`)
- Official data: `python -m india_rail official --list | --file <csv>`

## Next steps towards real deployment

0. **Done with real data:** the twin runs on the 2024 timetable with observed running days and mapped track data, and is verified against 56,395 real train runs (see above).
1. **Authorised live data.** NTES running status, RTIS positions and COA control charts through CRIS; the signed gateway is built and needs the interface specification and keys. Also running days and the current timetable (Trains at a Glance / ICMS); the official-data pipeline ingests the data.gov.in release.
2. **Track data.** OpenStreetMap line counts are loaded; the Indian Railways engineering register (block sections, loops, signals) is what makes conflict warnings precise (measured on real days: informative, far from certain).
3. **Delay model.** Done on one month of actual running; retrain on IR's own feed across seasons (fog, monsoon).
4. **Optimiser.** Replace the greedy holds with an optimiser that minimises weighted delay, then trial it in shadow mode beside a real control office, comparing its proposals with the controllers' decisions.
5. **Certification.** Any step that issues commands to trains or signals goes through RDSO safety certification and Kavach/EI integration by the authority. That is outside this software.

Data attribution: DataMeet (CC0). © OpenStreetMap contributors (ODbL). Observed running: K. Chowdhury, P. Koley, A. Chakraborty, S. Ghosh, "RSTGCN: Railway-centric spatio-temporal graph convolutional network for train delay prediction", IEEE Transactions on Intelligent Transportation Systems, 2026 (arXiv:2510.01262).
