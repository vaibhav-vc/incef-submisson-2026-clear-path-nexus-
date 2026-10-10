# Audit log: six passes over the whole system

Each pass examined the whole code base through one lens, fixed what it found, then re-ran the full test suite,
lint (ruff 0.8.6, as pinned in CI) and, where behaviour could change, the simulation, before the next pass.
Findings are listed with the evidence that caught them and the evidence that the fix holds.

Final state after all six passes (the sixth on real-life data): **159 automated tests pass** (Python 3.11 and 3.13),
**Bandit 0 findings**,
**pip-audit 0 known vulnerabilities**, **0 safety-invariant violations** in the randomised simulation
(final code on real data: `evidence/simulation/real_data_final_results.json`, 36,000 episodes, 960,020 operations,
code checksum 55bda851; the main run found two last defects, see pass 1, and the simulation found one more in the
new forecast code, see pass 6), UI regression with **0 HTTP errors and 0 console errors** under
a strict Content-Security-Policy.

## Pass 1 - Safety logic (randomised simulation, `india_rail/railguard/simulate.py`)

A harness drives both twins with random operation sequences and checks eight invariants after every operation
(SAFE_SEPARATION, APPROVAL_GATE, EVIDENCE_GATE, INPUT_REJECTION, CAB_ADVISORY, RANKING, REPLAY,
NO_CRASH/LIVENESS). The first 400-episode batches failed on 47% of tabletop and 25% of national episodes. Every
finding below was reproduced from its episode id, fixed, and re-checked with the same seed.

| # | Finding | Fix |
|---|---|---|
| 1 | Approval checked only the clock: a controller hold, section closure, obstacle or new fix at the same second did not supersede a ranking, and approving it silently cancelled the hold | State version bumped on every change; approval must match the ranked version (both twins) |
| 2 | Re-planning a train mid-section restarted it at the section start (the twin moved it backwards ~1 km) | `Traversal.offset_km`; simulated position continues from the real offset |
| 3 | A held train with no dwell stopped at offset 0 of the *next* section | Hold stops the train at the node |
| 4 | A closed section ahead raised no threat on the tabletop twin; the cab showed NORMAL with a speed band | `SECTION_CLOSED` critical threat; cab goes to HOLD-FOR-CONTROLLER |
| 5 | Stored plan times (rounded to 0.01 min) put a re-planned train back at the station for a fraction of a minute | Position held until the plan's first time |
| 6 | National planner checked closures and conflicts only from the disruption station; `disrupt` accepted a departure the train had already made | Plan from the first section the train can still change (`first_open`) |
| 7 | The PRIORITY-path option skipped the closed/obstructed/axle-limit check | One feasibility filter applied to every option |
| 8 | Conflicts on the section a train already occupies were never examined | Conflict search from the occupied section; other trains yield before entering |
| 9 | Two lower-priority trains could re-path around each other forever (planning hang) | Cascade step bound; LIVENESS invariant with a 60 s watchdog |
| 10 | The 240-minute horizon was applied per train, so a conflicting pair was visible from one side only | Pair is in the horizon if either occupation is; scans extend by a margin |
| 11 | The PRIORITY option returned a plan its own re-check had not validated | Return the validated plan |
| 12 | Trains listed as "re-pathed" whose timings had not changed | Only changed runs are reported |
| 13 | Replay did not reproduce some rankings: threats/acknowledgements not restored; changed-run index order-dependent | Restore derived state; sorted index; 1,585 consecutive replays, 0 mismatches |
| 14 | Found by the 5-million-operation main run (7 of 70,000 tabletop episodes): holding a train that was already held recomputed its stop point from the timetable and released it forward (~4.5 km jump) | A re-hold never moves the stop point later; regression test `test_re_holding_a_held_train_never_moves_it` fails on the old code and passes now |
| 15 | Same run, 1 episode: a harness test case (not the system) read a last-fix time of 0 as "missing" and generated a plausible move it expected to be rejected | Harness fixed; the engine's acceptance was correct |

The main run (160,000 episodes, 5,068,492 operations) therefore ended with 8 violations in the tabletop twin and
0 in the national twin; all 8 episodes replay clean after fixes 14-15. Verification on the fixed, final code
(`evidence/simulation/final_code_results.json`, code checksum 752bfcc1): 24,000 episodes, 1,201,001 operations,
**0 violations**. After the real-data work (pass 6), the final code on real data ran 36,000 mixed episodes (960,020
operations) and 200,000 national episodes on the real network (2,227,905 operations), both with 0 violations and
code checksum 55bda851. All runs together: 9,868,852 checked operations.

## Pass 2 - Security (`tests/test_security.py`, `tests/test_attacks.py`, `tests/test_livefeed.py`)

| # | Finding | Fix | Evidence |
|---|---|---|---|
| 1 | Starlette 0.41.3 (via FastAPI 0.115.6) had 7 published advisories; pytest 8.3.4 had 1 | FastAPI 0.142.2, Starlette 1.7.0, Uvicorn 0.54.0, pytest 9.0.3; CI reproduced on Python 3.11 | `evidence/audit/pip_audit.json`: 0 |
| 2 | A request containing NaN produced a 500: the default 422 handler echoed the input and could not serialise NaN; echoing input also reflects attacker text | Validation handler that never echoes input | `test_non_finite_and_mistyped_numbers_never_reach_the_clock` |
| 3 | Lax coercion accepted `"5"` and `true` as numbers and silently ignored unknown fields | `StrictRequest` base for all 17 request models (exact types, no extra fields, finite numbers) | same test, 8 cases |
| 4 | A persisted audit file failed verification after a restart (second GENESIS in one file) | Chain resumes from the last record of the file | `test_audit_chain_detects_tampering_and_survives_restart` |
| 5 | Ollama URL from the environment opened without a scheme check (`file://` possible) | http(s) only; ingest downloads https only | Bandit B310 cleared |
| 6 | One SQL statement assembled with an f-string (values were bound, but fragile) | Constant statement, all values bound | Bandit B608 cleared |
| 7 | Chunked uploads bypassed the body-size cap | 411 for bodies without Content-Length; receive guard | `test_body_limits` |
| 8 | Interactive API docs exposed in production; feed-simulator nonces from a non-cryptographic RNG | Docs disabled in production; `secrets.token_hex` | Bandit B311 cleared |

Also verified with no change needed: auth-bypass header tricks (9 cases), tokens in query strings, path
traversal (5 encodings), JSON bombs, SQL/markup injection strings in identifiers, method tampering, no CORS
grants, no tracebacks in errors, feed role cannot decide, no `innerHTML`/`eval` in any page script.

## Pass 3 - Performance and efficiency

Profiled a 40-episode run (cProfile). Hot spots: ~100,000 rebuilds of unchanged timetabled plans, approved plans
re-parsed on every threat evaluation, the stress model recomputed per section, generic `deepcopy` of snapshots.

| Change | Safety argument |
|---|---|
| Default plan cached, keyed on the train's departure and every attribute of every section on its route | Key contains every input, so a stale answer is impossible (a test mutates a section directly and still passes) |
| Approved plan parsed once per approval | Keyed on snapshot, candidate and approval time; plans treated as read-only (`planned_conflicts` no longer mutates) |
| Stress factors memoised on their numeric inputs (`lru_cache`) | Pure function |
| `plain_copy` for snapshot freezing; node-distance cache per twin | Same values, lengths are immutable |

Result: **−39% CPU** for the profiled episodes (19.1 s → 11.7 s), with **byte-identical behaviour**: checksums of
all six scenario results and of snapshot/audit hashes from 30 random episodes were equal before and after.
The SEVA metrics re-run gave identical values.

## Pass 4 - Data and machine learning

| # | Finding / work | Result |
|---|---|---|
| 1 | Model lost to the section median on "within 2 min" (76.6% vs 80.4%) | Measured training rounds with a locked 15% test set; 17 rounds, 6 kept |
| 2 | Winning configuration | Type- and direction-specific section priors, neighbouring-section pace, type-specific base, larger/slower boosting, whole-minute rounding |
| 3 | Locked test (58,110 sections, 767 trains never seen) | MAE **1.378 min vs 1.957** for the section median (−30%); within 2 min **88.1% vs 80.1%** |
| 4 | Production model retrained (5-fold grouped CV) | Existing trains 1.387 min / 88.0%; new paths 1.680 min / 83.7%; P10-P90 coverage 80.0% with width 3.86 min (was 5.35) |
| 5 | Official data | `official.py`: registry with publisher and licence, SHA-256 provenance, data.gov.in parser, reconciliation, official rail distances; a test caught the 00:00:00 placeholder convention |
| 6 | Whole network | All 8,990 stations: 7,679 with halts, 914 non-halt stations placed on their section, 397 not placeable (106 without coordinates) |
| 7 | Live data | Signed feed gateway with map-matching and station events, tested end to end |

Leakage controls kept throughout: section priors re-encoded inside every fold from training trains only;
GroupKFold by train pair; train-pace and neighbour context leave the row's own run time out.

## Pass 5 - Code quality and compactness

| # | Finding | Fix |
|---|---|---|
| 1 | `build_national` had cyclomatic complexity 62 (radon grade F) | Split into `_build_sections`, `_place_nodes`, `_build_runs`, `_build_occupancy`: grade C (16); data checksum, statistics and passing points identical before and after |
| 2 | Dead code (vulture): unused `PositionObservation` | Removed (other vulture hits are serialised dataclass fields) |
| 3 | Duplicated scoring constants between the two planners (found in an earlier pass) | One `scoring.py` shared by both |
| 4 | CI parity | Lint/format clean with the CI-pinned ruff 0.8.6; tests pass on Python 3.11 and 3.13 |
| 5 | Documentation | `SECURITY.md`, `COMPLIANCE_REGISTER.md`, this log, report generator `scripts/build_report.py` |

## Pass 6 - Real-life data (`india_rail/realdata.py`, `osm_infra.py`, `realval.py`)

The system was run against what actually happened: 56,395 real train runs with 1.26 million actual arrival
times (September 2024, IIT Kharagpur research dataset), real track data from OpenStreetMap, and the Ministry of
Railways' published punctuality figure. Results: `evidence/real_data/real_validation.json` and
`railway_readiness/REAL_DATA_VALIDATION.md`. Each finding below was reproduced on the real data, fixed, and
re-checked on the same data.

| # | Finding | Fix | Evidence |
|---|---|---|---|
| 1 | The live-feed gateway rejected 19% of a real morning's reports: a late train not yet reported was projected on time, so its real report at a station the projection had passed was "not ahead on the route" | Reports are matched from the run's last *accepted observation*, never from the projection; a report behind it is refused as out of order; the memory is dropped when the twin is reset | `test_reports_are_matched_from_the_last_observation_and_never_move_a_train_back`; real replay: acceptance 80% -> 96.6% |
| 2 | Every feed event re-evaluated all national threats: 505 ms per one-minute batch | Threats are re-evaluated once per batch, after all its events; the version still changes, so earlier rankings are superseded | `test_a_feed_batch_re_evaluates_threats_once`; real replay about 0.1 s per batch over a whole morning |
| 3 | 343 trains in the 2024 file list every stop at the same minute (placeholder timetables); their "actual" times are meaningless | Detected (more than 30% zero-minute sections) and excluded from the twin and every score, and counted | `test_build_derives_running_days_and_actual_times_and_drops_placeholder_timetables` |
| 4 | The first OpenStreetMap line count read curving single lines and the parallel Dedicated Freight Corridor as double line, and missed double lines mapped far apart | Lines are counted where they cross a perpendicular cross-section; freight corridors, metros and sidings are not counted; a lone line with a parallel line 30-150 m away reads double; checked on Konkan (single) and Delhi-Bhopal (double) | `tests/test_osm_infra.py` (7 cases) |
| 5 | The 2016 open timetable lacks 6,091 sections of 2024 and differs by over 15 minutes in two thirds of journey times | The national twin runs on the 2024 timetable, with real running days for every train; production refuses any other timetable | `test_production_runs_only_on_the_real_timetable`, `test_real_network_runs_on_real_timetable_days_and_track_data` |
| 6 | With the old projection (a delay carried forward), conflict warnings were barely better than chance at predicting real time loss | Late trains reported by the feed are projected with a forecast learned from real running (13.9 vs 17.4 min average error on unseen days); warnings became clearly more predictive | `evidence/real_data/real_validation.json` (forecast, conflicts) |
| 7 | Found by the randomised simulation within 60 episodes of the new code: a forecast that recovers time faster than physically possible made a projected plan overlap itself (RANKING invariant, 7 episodes) | Forecast plans never leave a stop before arriving and never run a section in under 85% of its timetabled time | `test_forecast_plans_never_overlap_themselves_or_run_impossibly_fast`; the 7 episodes replay clean |
| 8 | A forecast could have replaced a plan already shaped by a controller's decision (a hold) | A forecast only replaces a projection; once a controller decision shapes the plan, a new delay is added on top of it | `test_a_forecast_never_replaces_a_controller_decision` |
| 9 | Simulation workers stalled: model inference threads in every worker spun against each other (OpenMP) | One inference thread per simulation worker | 600 episodes in 35 s (was over 10 minutes) |
| 10 | The twin's data label still said the network was inferred from the open timetable | The label states the timetable used and how many sections have mapped track data | `recommend()` output |

## Pass 7 - Production build (every train, GNSS, live push, operations, accounts, advisor, freight)

New surfaces (13 findings below): the current all-India timetable and registry, freight corridors, GNSS tracking and the cab agent,
live event streams, UPS/checkpoints/health/metrics, named accounts, the delay advisor and scenario training. Each
was run on the real network or real running data, attacked, and load-tested; the findings below were found that
way and fixed.

| # | Finding | Fix | Evidence |
|---|---|---|---|
| 1 | GNSS fixes on track that curves back on itself, or at reversal stations (Jalandhar City), matched the wrong pass, so 99 genuine fixes in 21,851 looked like jumps | Every pass of the track near the fix is kept; the one nearest where the train should be (last position + reported speed) is reported, and all of them bound the train's position until later fixes narrow it | `test_a_track_that_doubles_back_*`, `test_reported_speed_picks_*`; implausible refusals 99 -> 4 (the rest are timetable entries implying 220-240 km/h) |
| 2 | A train standing at a station was drawn on the station's map pin, up to 700 m off the track, so its first fix after departure looked like a backward move | Stopped trains are placed on the track at the station; the backward allowance widens to the yard width in station zones | `gnss_verification.json` |
| 3 | The 3 km slack beside unmapped sections also applied beyond their ends, swallowing off-track fixes near a junction | Beyond a straight section's ends only the station zone (1.5 km) applies | `test_a_fix_on_the_straight_line_but_off_the_mapped_track_is_a_deviation` |
| 4 | One multipath fix raised a route-deviation alarm (a nuisance alarm is a hazard of its own) | A fix under 1 km off is refused quietly; the second in a row, or any fix 1 km+ off, raises the alarm | 66 quiet refusals, 4 alarms (0.02%) in 21,851 genuine fixes |
| 5 | A live stream whose advisory did not change sent nothing at all, so proxies would drop it and clients could not tell it was alive | Heartbeat after 15 s of silence, whatever the tick rate | `test_a_quiet_stream_still_sends_heartbeats`; found when the load test hung |
| 6 | Every stream recomputed its own picture each second (500 thread hops a second competing for the twin lock) | One broadcaster per event loop recomputes when the twin changes (checked every 50 ms) and wakes every stream together | Load test, server in its own process: push p50 0.96 s -> 0.35 s, feed batch p50 0.43 s -> 0.16 s |
| 7 | A lint auto-fix (`--unsafe-fixes`, C416) turned a pandas group-by comprehension into `dict(groupby)`, which raises | Restored; caught by `test_current.py` before commit | Full suite |
| 8 | Rate-limit buckets leaked between tests, so later tests saw 429 | Each test starts with fresh buckets (`conftest.py`) | 215 tests pass in any order |
| 9 | Special trains running hours away from their published 2024 timings ("527-minute loss") distorted the advisor's rankings | Changes over 3 h are counted as incidents, recurring losses over 90 min as schedules that do not describe the train, both kept out of the patterns | Section persistence 78% -> 92% |
| 10 | 72% of current trains have no observed running, and the forecast was trained only on trains with history | Training withholds the history from 15% of rows; cold-start error is measured (15.4 min) | `scenario_ml.json`, `real_validation.json` |
| 11 | The image would not build behind a TLS-inspecting proxy (common on railway networks) | The proxy's CA can be passed as a build secret; verification is never disabled | `Dockerfile` |
| 12 | Bandit flagged the load-test harness (subprocess, URL open) | Fixed arguments, loopback URL, no shell; each suppression states why | Bandit 0 findings on 13,555 lines |
| 13 | Found by the randomised simulation's new GNSS_GATE invariant (1 episode in 24,000, national:23648, seed 6161): where the route uses the same track twice (through Solapur, arriving from Hotgi and leaving for Akkalkot Road) a genuine fix matched both passes, and the train was then tracked as being anywhere *between* them, so a spoofed fix 7 km on was accepted | The train is tracked at each candidate place as a point; a new fix must be a plausible move from one of them | `test_a_fix_between_two_possible_places_is_not_plausible_from_either`; the episode replays clean; run that found it: `evidence/simulation/production_found_gnss_defect_results.json` |

Verification after the pass: 215 tests, ruff 0.8.6 lint and format, Bandit 0, pip-audit 0; the randomised
simulation re-run on the final code with the new GNSS_GATE invariant (`evidence/simulation/production_final_results.json`);
the production container built, run, restarted and checked for secrets in its logs; the console driven in Chromium
with no console errors or CSP violations.
