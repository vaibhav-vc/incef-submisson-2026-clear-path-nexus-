# Handover to Indian Railways: the remaining steps, made run-and-sign

The software is built and verified. Every step below can only be completed by Indian Railways, CRIS, an empanelled
auditor or an independent safety assessor: no software can authorise itself, audit itself or accept its own
safety. For each step this project ships the tool, the template and the evidence. What remains is to run them on
railway systems and sign.

## 1. The steps, in order

| # | Step | Who | Run | Closed by |
|---|---|---|---|---|
| 1 | Host on railway infrastructure | CRIS / IR IT | `docker compose -f docker-compose.railguard.yml up` ([DEPLOYMENT.md](DEPLOYMENT.md)) | `/health/ready` true with UPS, checkpoints and clock configured |
| 2 | Clock on NIC/NPL time (CERT-In) | IR IT | `RAILGUARD_NTP=samay1.nic.in,time.nplindia.org` | readiness check `clock` true; `railguard_clock_offset_seconds` within 1 s |
| 3 | Security audit | CERT-In empanelled auditor or STQC | `python -m india_rail audit-pack` inside the production image; [SECURITY_ASVS_CHECKLIST.md](SECURITY_ASVS_CHECKLIST.md); attack tests | the auditor's "safe to host" certificate |
| 4 | Loop and block-section register | Divisional engineering and S&T | `python -m india_rail register template --out-dir reg/` (two empty CSV files, headers only); enter every row from Station Working Rules, working time table and signalling plans, naming the document; `register validate --dir reg/` (also reports stations and sections the twin does not run on); `register build --dir reg/ --out register.json`; `RAILGUARD_REGISTER=register.json` | twin statistics show the register checksum and the sections and stations it covers |
| 5 | Live feeds (RTIS, NTES, COA) | CRIS | Share the interface specification; `python -m india_rail feed-conformance producer --file sample.jsonl --source RTIS --key-file k.hex` on CRIS's own sample; exchange keys out of band; `feed-conformance endpoint --url https://<test host> --train <a train running today> --station <a stop of it> --test-environment ...` | both certificates `PASS`; [LIVE_DATA_INTERFACE.md](LIVE_DATA_INTERFACE.md) onboarding checklist complete |
| 6 | Cab units | Mechanical and S&T | Fit GNSS/NavIC receivers; `python -m india_rail gnss --train N --start-date D --nmea /dev/ttyACM0` with a per-unit key; controllers issue each cab its link (console: **Issue cab link**) | `gnss-verify` re-run on field traces; accepted share and false alarms within the hazard log's limits |
| 7 | Identity | IR IT | Named accounts (`python -m india_rail accounts add ...`), `RAILGUARD_REQUIRE_ACCOUNTS=1`; or connect IR SSO | every decision in the audit chain carries a named person |
| 8 | Safety acceptance | Safety directorate, RDSO, independent safety assessor | Hazard workshop on [HAZARD_LOG.md](HAZARD_LOG.md); [SAFETY_CASE.md](SAFETY_CASE.md); section 2 below | acceptance for shadow use, then for advisory use |
| 9 | Shadow-mode trial | One division, 3-12 months | Controllers log what they decided (console, or a CSV export of the Control Office Application: `POST /railguard/national/shadow/import`); weekly `python -m india_rail shadow-report --audit-dir <RAILGUARD_AUDIT_DIR>` | exit criteria of [SHADOW_TRIAL_PLAN.md](SHADOW_TRIAL_PLAN.md) met |
| 10 | Training and roll-out | Zonal training centres | [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) modules | trained controllers and loco pilots; procedures issued |

Steps 1-7 can run in parallel; 8 needs 4 and 5 for its evidence; 9 needs 1-8 for shadow use; 10 follows 9.

## 2. Safety acceptance dossier (EN 50126-1:2017 lifecycle)

The system advises; it has no interface to signalling, interlocking, points, Kavach/ATP or brakes, and every output
needs a named controller's approval. The safety case therefore argues that no hazard depends on the software
alone. The integrity level is for IR and RDSO to decide; the evidence is organised so they can.

| Phase | Evidence here | Left to IR / RDSO / assessor |
|---|---|---|
| 1-2 Concept, system definition | [SAFETY_AND_INTEGRATION_BOUNDARIES.md](../SAFETY_AND_INTEGRATION_BOUNDARIES.md): advisory scope, interfaces, what it cannot know | Confirm scope and operational context |
| 3 Risk analysis | [HAZARD_LOG.md](HAZARD_LOG.md): hazards with causes, mitigations, verification and residual risk | Hazard workshop; risk scoring against IR's matrix |
| 4 Requirements | [SAFETY_CASE.md](SAFETY_CASE.md) safety requirements SR1-SR8, each traced to code and tests | Accept or amend the requirements |
| 5 Apportionment | Barriers outside the software: signals, rules, Kavach, the controller | Confirm the apportionment |
| 6-7 Design, implementation | Code with tests; strict schemas; deterministic, replayable decisions; hash-chained audit | Code review by the assessor |
| 8 Manufacture | Pinned dependencies, digest-pinned container, software bill of materials (`audit-pack`) | Configuration management on IR systems |
| 9 Installation | [DEPLOYMENT.md](DEPLOYMENT.md); readiness checks | Site acceptance |
| 10 Validation | Randomised simulation with safety invariants (millions of operations, 0 violations on the final code); real-day replays; 75,556 forecast and 75,556 planner scenarios ([../evidence/scenarios](../evidence/scenarios)) | Validation on IR data in the shadow trial |
| 11 Acceptance | This dossier and the shadow-trial report | The acceptance decision |
| 12 Operation | Operator guide; monitoring; incident procedure ([../../SECURITY.md](../../SECURITY.md)) | Operate, monitor, report |

Software process: EN 50716:2023 (railway software) is the reference the assessor will apply. The verification
record (tests, simulation, audit passes in [../AUDIT_LOG.md](../AUDIT_LOG.md)) is written to be read against it.

## 3. What the project cannot supply, stated plainly

* Authorisation to connect to CRIS systems, and the keys for it.
* Indian Railways' engineering data: loops, block sections, signal positions, gradients, permanent speed
  restrictions. The register template is empty: nothing is pre-filled, and only rows that name an Indian Railways
  document are ever used.
* An independent security audit and an independent safety assessment.
* Operational experience: the shadow trial is the only way to learn how controllers and the system disagree.
