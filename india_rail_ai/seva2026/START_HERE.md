# ClearPath Nexus — SEVA 2026 build (Nexus RailGuard)

**Controller decision support + driver advisory + evidence assurance. Not signalling or train control.**

Flow: **Observe → Verify (EvidenceGate) → Twin → Detect (RailGuard) → Optimise → Human approves → Driver advisory (Nexus Cab) → Audit**

## Run the demo (one laptop, offline, free)

```sh
cd india_rail_ai
pip install -r requirements.txt
python -m india_rail serve --host 0.0.0.0     # serves everything on port 8100
```

- **Nexus Control** (controller): http://localhost:8100/control
- **Nexus Cab A / B** (driver screens, phones/tablets on the same Wi-Fi): http://LAPTOP-IP:8100/cab?train=A and `?train=B`

The demo needs no internet and no account. No external scripts or fonts load, and the timetable data is not needed for RailGuard.

**Optional: protect the console on a shared network.**
```sh
export RAILGUARD_VIEWER_TOKEN=...       # read-only screens (cab devices get it via the URL fragment #token=...)
export RAILGUARD_CONTROLLER_TOKEN=...   # required on every controller action; cab screens never have it
export RAILGUARD_FEED_TOKEN=...         # required on hardware/live feed reports
# For a real deployment: RAILGUARD_MODE=production refuses all requests until every token is 32+ characters
# and RAILGUARD_ALLOWED_HOSTS is set. See ../SECURITY.md.
```

**Verify:** `python -m pytest -q`, then `python -m india_rail.railguard.metrics --out seva2026/evidence/metrics/railguard_metrics.json`.

## What is built, and how far each claim goes

| Capability | Status | Where |
|---|---|---|
| Digital twin: 10 sections, 3 junctions, single and double line, Train A (heavy freight) and Train B (express) | WORKING IN SIMULATION | `india_rail/railguard/model.py` |
| Route candidates and hold/resequence options with hard-constraint rejection (closed section, obstacle, axle limit, occupation conflict) | WORKING IN SIMULATION | `planner.py` |
| Seven-factor explainable score with presets FASTEST / INFRA_PROTECT / LOWEST_RISK / BALANCED, live weight sliders, "why it lost" | WORKING NOW | `planner.py`, Nexus Control |
| Relative infrastructure-stress index (TrackSense) | WORKING NOW as a research index; not a certified deterioration model | `stress.py` |
| 11 deterministic threat rules with an OPEN → ACKNOWLEDGED → CLEARED lifecycle | WORKING IN SIMULATION | `threats.py` |
| EvidenceGate freshness, completeness and future-timestamp checks; fails closed to HOLD / UNAVAILABLE | WORKING NOW | `evidence.py`, `engine.recommend` |
| Controller APPROVE FOR DEMO / REJECT / HOLD, latest-snapshot-only approval | WORKING NOW | `engine.py`, Nexus Control |
| Nexus Cab A/B: approved plan only, advisory speed band, restrictions, nearby-train awareness with confidence, permanent footer | WORKING IN SIMULATION | `cab.py`, `/cab` |
| Hash-chained audit log, checksummed decision snapshots, deterministic replay | WORKING NOW | `audit.py`, `engine.replay` |
| Six scripted judge scenarios with automatic pass/fail checks | WORKING NOW (6/6 pass) | `scenarios.py` |
| TwinTrack hardware node (ESP32 + OLED + marker sensor + ultrasonic obstacle sensor) | HARDWARE DEMO — firmware written, **not compiled or bench-tested** | `hardware/twintrack_esp32/` |
| Live Indian Railways data (RTIS/COA/NTES, interlocking state) | REQUIRES AUTHORISED RAILWAY DATA | — |
| Any use beside real trains | REQUIRES CERTIFICATION / FIELD VALIDATION | — |

## Measured results

All figures are controlled software experiments on the tabletop twin. None of them are field measurements. They come from [`evidence/metrics/railguard_metrics.json`](evidence/metrics/railguard_metrics.json).

| Metric | Result |
|---|---|
| Conflict-detection recall / precision (861 delay combinations vs analytic ground truth) | 100% / 100% (480 real conflicts, 0 missed, 0 false alarms) |
| False-clear count (42 injected fault cases: stale feed, offline sensor, missing evidence, unacknowledged obstacle, future timestamp) | **0** |
| Approved plans executed in the twin (462 runs) | 0 single-line overlaps; minimum observed separation 4.8 min (3 min headway) |
| Recommendation latency (ranking about 250 feasible plan pairs) | median 10 ms, p95 13 ms |
| BALANCED vs fastest plan, healthy network | +2.4 min weighted delay on average, −4.8% infrastructure stress |
| BALANCED vs fastest plan, degraded bridge S02 | +3.4 min on average, **−24.2% infrastructure stress** (up to −31%) |
| Infrastructure scenario (degraded S02) | −23.8% stress for +1.1 min delay |
| Scenarios / replay | 6/6 pass; 12/12 snapshots replay exactly; tampering detected |
| Evidence completeness / freshness across scenario recommendations | 100% / 99.4% |

**Trade-off to state honestly.** BALANCED will accept extra delay for a lower-stress route. In the worst grid case it holds an already 20-minute-late freight a further 9.8 minutes rather than send it over a 12% higher-stress bypass. The FASTEST preset does not make that trade. The controller sees both, with factor bars, and decides.

## Whole network, security, simulation and readiness (added after the tabletop build)

| Capability | Status | Where |
|---|---|---|
| National twin: all 8,990 stations (7,679 halts + 914 non-halt stations placed), 1,454 junctions, 8,738 sections, 7,580 train runs | WORKING ON OPEN DATA (attributes inferred and labelled) | `railguard/national.py`, `/control/national` |
| Randomised simulation with 8 safety invariants after every operation | **5M+ operations, 0 violations** (13 defects found and fixed on the way) | `railguard/simulate.py`, `evidence/simulation/` |
| Security: roles, fail-closed production, strict schemas, CSP, rate limits, signed feed | 115 tests incl. 32 attack tests; Bandit 0; pip-audit 0 | `SECURITY.md`, `evidence/audit/` |
| Run-time ML after measured training rounds | 1.38 min vs 1.96 baseline on a locked test (−30%) | `models/training_log.json` |
| Live-feed gateway (RTIS/NTES/COA-style, signed) | READY - needs CRIS specification and keys | `railguard/livefeed.py` |
| Official data pipeline (data.gov.in, GODL) | READY - file must be downloaded from India | `india_rail/official.py` |
| Legal / safety / data compliance register | Engineering register; needs IR legal and safety review | `COMPLIANCE_REGISTER.md` |
| Five audit passes | Done | `AUDIT_LOG.md` |

| All-train working schedules and completeness audit (5,208 trains) | WORKING: stop matrix, metrics, flags; running days honoured when official data supplies them | `india_rail/schedules.py`, `evidence/schedules/` |
| Railway-readiness packs: hazard log, safety case, live-data interface contract, ASVS checklist, shadow-trial plan and tooling, operator guide | DRAFTS FOR IR REVIEW | `railway_readiness/` |

Readiness (judgement, reasons in the report):
- **Software side:** about 92%.
- **Whole path to railway use:** about 52% done, 48% left.

What is left is authorisation of live data, an independent security audit, safety acceptance and a field trial. Only Indian Railways and its authorities can complete those, and the project has prepared each one for review and sign-off.

## Pack contents

- [ClearPath_Nexus_RailGuard_Report.pdf](ClearPath_Nexus_RailGuard_Report.pdf) - the full report: what was built, technology, data, ML, simulation, security, audits, compliance, readiness
- [AUDIT_LOG.md](AUDIT_LOG.md) - five audit passes with findings and fixes
- [COMPLIANCE_REGISTER.md](COMPLIANCE_REGISTER.md) - laws, rules, standards and licences, and how each is addressed

- [VALIDATION_EVIDENCE_MATRIX.md](VALIDATION_EVIDENCE_MATRIX.md) — claim → code → test → scenario → measurement → limitation
- [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) — click-by-click judge demo
- [SEVA_PPT_CONTENT.md](SEVA_PPT_CONTENT.md) — slide text with measured numbers only
- [SAFETY_AND_INTEGRATION_BOUNDARIES.md](SAFETY_AND_INTEGRATION_BOUNDARIES.md) — authority limits and where the code enforces them
- [SOURCE_REGISTER.md](SOURCE_REGISTER.md) — official sources, what was verified and what each does *not* prove
- [../hardware/twintrack_esp32/README.md](../hardware/twintrack_esp32/README.md) — tabletop hardware
- `evidence/` — test results, scenario outputs, metrics, screenshots
