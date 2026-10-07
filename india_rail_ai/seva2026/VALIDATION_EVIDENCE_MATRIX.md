# Validation & evidence matrix

Each row links a claim to the code that implements it, the automated test that checks it, the demo scenario that shows it, and its measured result and limitation.
- Test names are in `tests/test_railguard.py`.
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
| Authority is separated at the interface | `railguard/api.py` | `test_api_cab_is_read_only_and_controller_token_enforced`, `test_feed_cannot_approve_and_needs_feed_token` | — | — | Token is a LAN demo control, not railway-grade security |
| Recommendation is reconstructable | `audit.AuditLog`, `engine.replay` | `test_snapshot_replay_reproduces_and_detects_tampering`, `test_audit_chain_detects_edits`, `test_scenarios_are_deterministic` | Audit replay | 12/12 replays match | A checksum proves integrity, not source truth |
| All judge scenarios work end to end | `scenarios.run_all` | `test_all_six_judge_scenarios_pass` | All six | 6/6, 31/31 checks | Scripted, not exploratory |

**Folders.**
- `evidence/tests/` — pytest output.
- `evidence/scenarios/` — step logs.
- `evidence/metrics/` — measurements.
- `evidence/screenshots/` — UI captures.
- `evidence/hardware/` — empty until the tabletop node is built and filmed.
- `evidence/source-register/` — see [SOURCE_REGISTER.md](SOURCE_REGISTER.md).
