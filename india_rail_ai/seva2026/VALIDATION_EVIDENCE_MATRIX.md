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
