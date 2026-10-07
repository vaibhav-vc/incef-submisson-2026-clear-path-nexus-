# Hazard log (draft for Indian Railways review)

Scope: Clear Path Nexus / RailGuard as an **advisory** decision-support tool for section controllers and an
advisory cab display. It has no interface to signalling, interlocking, points, Kavach/ATP or brakes. Hazards are
therefore about *wrong or misleading advice* and *loss of the advice*, never about direct control.

This is a draft prepared by the developer in the EN 50126 style, for IR's safety organisation to review, re-score
and own. Severity and likelihood are the developer's initial estimates. **Residual risk acceptance is IR's
decision.**

Severity: Catastrophic / Critical / Marginal / Negligible. Likelihood (with mitigations): Frequent / Probable /
Occasional / Remote / Improbable.

| ID | Hazard | Causes | Possible consequence if acted on without other barriers | Mitigations in the design | Verification evidence | Residual (dev. estimate) | Status |
|---|---|---|---|---|---|---|---|
| H01 | A ranked plan contains a conflict (two trains planned too close) | Planner defect; stale twin state; horizon limits | Controller sets a conflicting path; protected by signalling/interlocking, but delay or unsafe pressure on staff | Conflict search against every occupation incl. the occupied section; pair-symmetric 240-min horizon; joint re-check of all re-pathed trains; later conflicts raised as WARNING threats | Simulation invariants SAFE_SEPARATION and RANKING: 0 violations in 6.68M operations; `tests/test_national.py` | Marginal / Improbable | Open for IR review |
| H02 | Advice based on stale or wrong train positions | Feed outage; delayed data; GNSS error; spoofing | Plan assumes trains are elsewhere | EvidenceGate: stale → HOLD, missing → UNAVAILABLE; projections are PLANNING_ONLY and cannot be approved as live; signed feed with replay protection; map-matching rejects off-route fixes; implausible jumps rejected | EVIDENCE_GATE / INPUT_REJECTION invariants; `tests/test_livefeed.py` | Marginal / Remote | Open |
| H03 | Approval of an outdated recommendation | State changes between ranking and approval | Plan no longer fits the situation | Version check: any change (clock, position, section, hold, threat) supersedes the ranking | APPROVAL_GATE invariant; `test_superseded_*` tests | Marginal / Improbable | Open |
| H04 | Plan routes a train over a closed or obstructed section | Late infrastructure input; planner defect | Train sent towards a blocked line (stopped by signals) | Hard feasibility filter for every option; SECTION_CLOSED / OBSTACLE critical threats block approval until acknowledged; cab shows HOLD-FOR-CONTROLLER | RANKING / CAB_ADVISORY invariants | Marginal / Improbable | Open |
| H05 | Driver treats the cab advisory as movement authority | Human factors; display design | Driver proceeds against signals | Permanent footer "authorised signals, rules and ATP remain controlling"; no speed band without fresh evidence and an approved plan; status degrades to DATA UNAVAILABLE | CAB_ADVISORY invariant; UI review | Critical / Remote (human factors: needs IR trial) | Open: needs human-factors assessment |
| H06 | Loss of the advisory service during operation | Server failure; network loss; overload | Controllers lose decision support | Advisory only: normal working continues without it; cab shows DATA UNAVAILABLE on link loss; rate limits; bounded memory; 60 s liveness watchdog in simulation | LIVENESS invariant; `test_rate_limit` | Negligible / Occasional | Open |
| H07 | Unauthorised person issues approvals or injects data | Credential theft; network attack | False plans or false positions | Role tokens (viewer / controller / feed), fail-closed production mode, host allow-list, strict schemas, signed feed, audit chain with HMAC | `tests/test_security.py`, `tests/test_attacks.py` (32 cases), Bandit 0, pip-audit 0 | Marginal / Remote | Open: needs external audit |
| H08 | Decision record altered after the fact | Insider tampering | Investigation misled | Hash-chained, HMAC-signed, persisted audit; CLI verification; snapshots replay to the same ranking | `test_audit_chain_detects_tampering_and_survives_restart`; REPLAY invariant | Negligible / Remote | Open |
| H09 | Model under-estimates run times | Training data is planned (not actual) running | Recovery assumed that cannot happen; optimistic plans | Model used only to estimate *recoverable* slack, scaled by a recovery factor 0.5; P10-P90 interval calibrated (80.0% coverage) | `models/runtime_model_metrics.json` | Negligible / Occasional | Open: retrain on actual running data |
| H10 | Inferred infrastructure attributes are wrong | Open data lacks track counts, loops, speeds | Single-line assumed double or vice versa | Unknown → single line (the conservative assumption); every attribute labelled with its source; schedule audit lists 105 stations with suspect coordinates | `evidence/schedules/schedule_audit.json` | Marginal / Occasional | Open: needs IR engineering register |
| H11 | Train shown as running on a day it does not run | Open data has no running days | Phantom conflicts / missed conflicts | Running days honoured when known (official data); unknown days flagged RUNNING_DAYS_UNKNOWN; live feed overrides projections | `test_twin_runs_trains_only_on_their_days` | Marginal / Occasional | Open: ingest official TAG/NTES days |

## Next steps for IR
1. Hazard identification workshop with section controllers, a Chief Controller and S&T, to add hazards from real operation.
2. Re-score severity and likelihood using IR's risk matrix; set tolerability.
3. Assign owners; link each mitigation to a verification record in the safety case (`SAFETY_CASE.md`).
