# Audit log: five passes over the whole system

Each pass examined the whole code base through one lens, fixed what it found, then re-ran the full test suite,
lint (ruff 0.8.6, as pinned in CI) and, where behaviour could change, the simulation, before the next pass.
Findings are listed with the evidence that caught them and the evidence that the fix holds.

Final state after all five passes: **115 automated tests pass** (Python 3.11 and 3.13), **Bandit 0 findings**,
**pip-audit 0 known vulnerabilities**, **0 safety-invariant violations** in the randomised simulation
(`evidence/simulation/simulation_results.json`), UI regression with **0 HTTP errors and 0 console errors** under
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
