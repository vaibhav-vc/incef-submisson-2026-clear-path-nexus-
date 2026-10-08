# Operator guide and training outline

## For section controllers (Nexus Control)
1. **What it is:** a second opinion. It ranks alternatives; you decide under the General & Subsidiary Rules.
2. **Reading the state badge:**
   * `PLANNING_ONLY`: positions are timetable projections (no live feed): use for planning, not as live truth.
   * `REVIEWABLE`: every involved train has a fresh live position: the alternatives can be approved.
   * `HOLD`: a live position is stale. Confirm by voice or another authorised source before acting.
   * `REVIEW`: a critical threat is open (obstacle, closed section, opposing occupancy). Acknowledge after checking.
   * `NO_FEASIBLE_PLAN`: nothing conflict-free within the options. Use normal control procedures.
3. **Approving:** only the latest ranking can be approved. If anything changed, re-rank first. Your name is recorded.
4. **Threats:** acknowledge only after you have acted or confirmed. Acknowledgement is recorded.
5. **When it is wrong or unavailable:** carry on with normal working. Note the case for the shadow-trial review.
6. **Forecasts of late trains:** a train the live feed reports late is projected with a forecast learned from real
   running (`ETA` view: median and a P10-P90 band per station). On real days it was within 15 minutes 81% of the
   time, so treat the band, not the single number, as the forecast. A forecast never changes a decision you made.
7. **Conflict warnings are advice with a known hit rate:** on real days the train that should give way lost time
   about 1.2 times as often as comparable trains. Use them to look, not as certainties.

## For loco pilots (Nexus Cab)
* The cab view shows only the controller-approved plan, as **advice**. **Signals, Kavach/ATP, caution orders
  and your rules always take precedence.**
* `DATA UNAVAILABLE` or `HOLD-FOR-CONTROLLER` means: no advice; follow signals and the controller.
* The speed band is a target range for smooth running, never a permission.

## Training modules (half a day each)
1. Concepts and boundaries: advisory role, evidence states, what the system cannot know.
2. Console practice on the tabletop twin: the six scenarios (`../DEMO_RUNBOOK.md`).
3. National console practice: disruption, ranking presets, approval, replay of a past decision.
4. Failure drills: feed loss, stale positions, closed section, conflicting sources.
5. Shadow-trial logging and review of disagreements.

## For administrators
Deployment and incident response: `../../SECURITY.md`. Feed onboarding: `LIVE_DATA_INTERFACE.md`. Verifying the
audit log: `python -m india_rail.railguard.audit verify <events.jsonl>`.
