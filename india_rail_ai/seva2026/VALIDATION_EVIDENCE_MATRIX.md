# Validation & evidence matrix

Each row links a claim to the code that implements it, the automated test that checks it, the demo scenario that shows it, and its measured result and limitation.
- Test names are in `tests/test_railguard.py` unless another file is named.
- Scenario checks are in `india_rail/railguard/scenarios.py`; their outputs are in `evidence/scenarios/scenario_results.json`.
- Measurements are in `evidence/metrics/railguard_metrics.json`.

| Claim | Code path | Test | Scenario | Measured | Limitation |
|---|---|---|---|---|---|
| Detects simulated route conflict | `threats.evaluate` → `planner.conflicts_between` | `test_converging_path_detected_for_late_train` | Delay conflict | recall 1.0, precision 1.0 over 861 cases | Demo network; not interlocking |
| No false alarm for diverging trains | same | `test_no_converging_threat_for_diverging_trains` | Normal | 0 false alarms in 861 | Same |
| Rejects infeasible plans (hard constraints) | `planner.build_train_plan`, `recommend` | `test_hard_constraints_reject_routes`, `test_axle_limit_is_a_hard_constraint`, `test_recommended_plans_never_conflict` | Threat awareness | 0 single-line overlaps in 462 executed plans | Headway is an input, not a signalling calculation |
| Ranks alternatives with visible factors | `planner.recommend` | `test_every_factor_is_exposed_and_sums_to_score`, `test_losers_explain_why_they_lost` | All | median 10 ms per ranking | Weights are demo presets |
| Considers infrastructure stress | `stress.section_stress` | `test_infrastructure_stress_changes_ranking`, `test_heavier_axle_load_scores_more_stress` | Infrastructure protection | −24.2% mean stress vs fastest on degraded network | Relative research index; not certified |
| Detects stale position evidence and fails closed | `evidence.EvidenceStore.assess`, `engine.recommend` | `test_stale_position_fails_closed` | Stale position | 0 false clears in 42 fault cases | Freshness policy values are demo settings |
| Missing mandatory evidence blocks approval | same | `test_missing_mandatory_evidence_is_unavailable` | — | in the 42 fault cases | Policy correctness needs domain review |
| Implausible movement or contradictory sources are flagged, not trusted | `engine.ingest_position` | `test_impossible_jump_rejected_and_flagged`, `test_contradictory_gnss_is_flagged_not_trusted`, `test_feed_validation` | Stale position | — | GNSS is never the safety authority |
| Critical threat blocks approval until a controller acknowledges it | `engine.recommend`, `threats.ThreatRegistry` | `test_critical_threat_blocks_approval_until_acknowledged`, `test_threat_lifecycle_open_ack_cleared` | Threat awareness | — | Obstacle sensor is a tabletop sensor |
| Controller gets alternatives; the driver never chooses a route | `engine.approve`, `cab.build_advisory` | `test_cab_shows_only_the_approved_plan`, `test_superseded_snapshot_cannot_be_approved`, `test_approval_needs_named_controller` | Normal + conflict | — | Shadow dispatch only |
| Authority is separated at the interface | `railguard/api.py`, `security.py` | `test_roles_are_separated`, `test_feed_role_cannot_take_decisions`, `test_api_cab_is_read_only_and_controller_token_enforced` | — | 32/32 attack tests pass | Needs an external CERT-In/STQC audit before hosting |
| Production deployment fails closed when misconfigured | `security.configuration_problems`, `require` | `test_production_without_tokens_fails_closed`, `test_production_rejects_short_or_shared_tokens` | — | 503 on every route until configured | Token management is the operator's job |
| Malicious input cannot reach the twin | `security.StrictRequest`, `validation_error_handler`, `HardeningMiddleware` | `tests/test_attacks.py` (NaN/Infinity, type confusion, JSON bombs, traversal, injection) | — | 0 crashes, 0 state changes | — |
| Whole-network twin | `national.build_national` | `tests/test_national.py` | National console | 8,990 stations, 1,454 junctions, 8,738 sections, 7,580 runs | Track counts, speeds, lengths inferred from the timetable |
| National plans are conflict-free and feasible | `national.candidates`, `_resolve`, `_priority_path` | `tests/test_national.py`; simulation RANKING / SAFE_SEPARATION | National console | 0 violations in 1,050,320 national operations (main run) | Rolling 240-min horizon; conflicts further out appear as threats |
| Safety invariants hold under random operation | `railguard/simulate.py` | simulation (8 invariants after every operation) | — | Main run 5,068,492 operations: 8 violations, i.e. 1 defect (re-hold) and 1 harness error, both fixed; final code 1,201,001 operations, 0 violations | Software-in-the-loop on open/synthetic data, not field validation |
| Run-time model beats the section median | `runtime_model.py`, `training.py` | locked-test protocol in `training.py` | — | 1.378 vs 1.957 min MAE (−30%), 88.1% vs 80.1% within 2 min | Planned run times only; delays need live data |
| Live feed is authenticated and replay-proof | `railguard/livefeed.py` | `tests/test_livefeed.py` | — | bad signature, unknown key, stale, replayed, out-of-sequence all refused | Field mapping to the real CRIS interface pending |
| Official data with provenance | `india_rail/official.py` | `tests/test_official.py` | — | SHA-256 + publisher + licence recorded per file | data.gov.in must be downloaded from India |
| Recommendation is reconstructable | `audit.AuditLog`, `engine.replay` | `test_snapshot_replay_reproduces_and_detects_tampering`, `test_audit_chain_detects_edits`, `test_scenarios_are_deterministic` | Audit replay | 12/12 replays match | A checksum proves integrity, not source truth |
| All judge scenarios work end to end | `scenarios.run_all` | `test_all_six_judge_scenarios_pass` | All six | 6/6, 31/31 checks | Scripted, not exploratory |

**Folders.**
- `evidence/tests/` — pytest output.
- `evidence/scenarios/` — step logs.
- `evidence/metrics/` — measurements.
- `evidence/simulation/` — randomised simulation results (main run and final-code regression).
- `evidence/audit/` — test summary, Bandit and pip-audit outputs.
- `evidence/screenshots/` — UI captures.
- `evidence/hardware/` — empty until the tabletop node is built and filmed.
- `evidence/source-register/` — see [SOURCE_REGISTER.md](SOURCE_REGISTER.md).

## Verified on real-life data (September 2024 actual running; OpenStreetMap track data)

| Claim | Code path | Test | Real data used | Measured | Limitation |
|---|---|---|---|---|---|
| The twin runs on the real current-era timetable with real running days | `realdata.build`, `national.timetable_source` | `test_build_derives_running_days_*`, `test_production_runs_only_on_the_real_timetable` | 3,549 trains, 56,395 runs | Running days observed for 100% of trains; 343 placeholder timetables excluded | One month of observation |
| Track line count from real mapped track | `osm_infra.lines_at`, `section_attributes` | `tests/test_osm_infra.py` | 101,805 OSM running-line ways | 90% of sections mapped; checked on Konkan (single) and Delhi-Bhopal (double) | Volunteer-mapped; no block sections or loops |
| The data is a credible sample of real running | `realval.credibility` | `test_destination_punctuality_*` | Destination arrivals vs Ministry figure | 82.0% (Sep 2024) vs 77.12% (FY 2024-25, includes fog months) | Different periods |
| Late trains are forecast better than by carrying the delay forward | `realval.forecast`, `railguard/eta.py` | `test_forecast_history_never_contains_*` | 1.42M forecasts on unseen days | 13.7 vs 17.2 min average error (3.4-3.7 min better, 95% CI); P10-P90 covers 81.5% | Trained on September only |
| Forecast projections stay physically possible and never override a controller | `eta.forecast_plan`, `national.disrupt` | `test_forecast_plans_never_overlap_*`, `test_a_forecast_never_replaces_*` | - | RANKING invariant clean on the final code (see simulation evidence) | - |
| Conflict warnings precede real time loss | `realval.conflict_replay` | `test_flag_scores_compare_*` | 4 unseen days x 6 snapshots, ~88,000 scored traversals | Give-way trains lost 5+ min in 29.4% of warnings vs 23.9% for comparable trains (1.23x) | Needs IR block-section and loop data |
| The signed gateway handles a real morning's reports | `livefeed.FeedGateway`, `realval.feed_replay` | `test_reports_are_matched_from_the_last_observation_*`, `test_a_feed_batch_re_evaluates_threats_once` | 7,979 real arrivals, 06:00-10:00 | 96.6% accepted (the rest out of order or unknown runs); ~0.1-0.2 s per one-minute batch | Recorded data, not the live CRIS feed |

## Production build (current timetable, GNSS, live push, operations, accounts, advisor, freight)

| Claim | Code path | Test | Data or scenario | Measured | Limitation |
|---|---|---|---|---|---|
| Every current train with its route on real track | `current.build`, `registry.route` | `test_build_takes_every_train_*`, `test_registry_serves_trains_routes_and_stations` | Real current timetable | 10,594 trains; 90% of sections on mapped track; 5,073 stations with a PIN | Community GTFS until CRIS supplies the timetable; PINs approximate |
| GNSS fixes placed on the real track; spoofing refused | `gps.TrackMatcher`, `gps.locate`, `livefeed._position` | `tests/test_gps.py`, invariant GNSS_GATE | Every train running at 10:00, 10 minutes, simulated receivers | 99.66% genuine accepted; 100% jumps/teleports refused; 0.02% false alarms | Receivers simulated; field units needed |
| Live push to each cab | `live.Broadcaster`, `/national/cab/{run}/stream` | `tests/test_live.py`, `tests/test_attacks_live.py` | 50 consoles + 500 cabs, real network | push p50 0.35 s; 0 streams dropped | One 4-CPU machine; clients on the same host |
| Power loss handled | `ops.Operations`, `/health/ready` | `tests/test_ops.py` (fake NUT server) | On battery, low battery, restore | Alert + checkpoint; approvals paused at low battery | Needs the site UPS on NUT |
| State survives a restart | `ops.Checkpointer`, `ops.restore` | `test_checkpoint_restores_state_*`, `test_a_tampered_*` | Production container restart | STATE_RESTORED in the audit chain; tampered/old/foreign refused | Shared storage for the standby is the site's |
| Decisions carry the person | `accounts`, `security.authorised`, `_actor` | `tests/test_accounts.py` | Login, lockout, roles, first-password change | Audit actor "R. Sharma (sharma.r)" | IR SSO not connected |
| Where delay is made, persistently | `delay_advisor.build` | `tests/test_advisor.py` | Real running, Sep 2024 | 92% of the worst 50 sections recur on held-out days | One month; IR's own running data next |
| Forecasts hold up across situations | `scenario_ml.run`, `realval.forecast` | rolling-origin rounds | 5 rounds x 4 days | Beats both baselines in 44/44 situations; cold start 15.4 min | No fog/monsoon in a September sample |
| Freight paths never conflict | `freight.FreightPlanner`, `freight.check` | `tests/test_freight.py` | 200 random days on both DFCs | 0 conflicts in 33,475 trains | Uniform demand; DFCCIL block data needed |
