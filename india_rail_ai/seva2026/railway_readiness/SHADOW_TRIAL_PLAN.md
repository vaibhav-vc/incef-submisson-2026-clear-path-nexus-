# Shadow-mode trial plan (proposal to a Division of Indian Railways)

## Purpose
Measure, without any effect on operations, whether RailGuard's ranked alternatives contain the decisions experienced
controllers actually take, and where they differ, why.

## Already done on recorded real running (retrospective shadow run)
Before any live trial, the national twin was run against four real days of September 2024 (`REAL_DATA_VALIDATION.md`):
at six times of day it received every train's real delay and its conflict warnings were checked against what the
trains then did. This measures the warnings honestly (informative, far from certain) and shows what a live trial
must add: controllers' actual decisions, and IR's block-section and loop data.

## Set-up
* One division, one or two control boards (e.g. a busy double-line section with a single-line branch).
* RailGuard hosted on railway infrastructure; authorised NTES/COA (and if available RTIS) feed via the signed
  gateway (`LIVE_DATA_INTERFACE.md`).
* Controllers work exactly as today. RailGuard's console is visible only to the trial team, or read-only to
  controllers if the Division agrees. Nothing is sent to drivers during the trial.
* Each actual control decision (hold, precedence, diversion, continue) is logged with
  `POST /railguard/national/shadow/actual` (by the trial team, or automatically from COA once mapped).

## Measures (from `GET /railguard/national/shadow/report`)
* Top-1 agreement: the top recommendation matched the decision taken.
* Shown-alternatives agreement: the decision was among the alternatives shown.
* Cases where the recommendation was HOLD / NO_FEASIBLE_PLAN and why (data gaps, inferred attributes).
* Data quality: feed acceptance rate, stale-position rate, route deviations raised.
* Weekly review of disagreements with the controllers concerned.

## Duration and exit criteria (proposed)
* 3 months of data collection after 2 weeks of feed commissioning; extend to 6-12 months across seasons
  (fog, monsoon) before any operational use.
* Proceed to an advisory trial (controllers may use the advice) only if: shown-alternatives agreement is high and
  disagreements are understood; no hazard in `HAZARD_LOG.md` is found to be worse than assessed; the CERT-In/STQC
  audit is closed; IR's safety organisation accepts the safety case.

## Data handling
No passenger data. Controller identifiers recorded for accountability only (DPDP: employment purpose); logs kept
on railway infrastructure in India for at least 180 days (CERT-In).
