# SEVA 2026 — slide content (paste into the official template)

Sector: **Infrastructure & Mobility**. Every number below was measured on the final build in `evidence/metrics/railguard_metrics.json`. They come from a tabletop twin, not from field operation.

## 1. Problem
Railway controllers have to balance delay, network conflicts, track condition and incomplete data, all at once. A fast recommendation is not useful if nobody can show which data it used, or how fresh that data was.

## 2. Solution
**ClearPath Nexus ranks controller-level operating alternatives and gives each driver an advisory view of the approved plan, while signalling and Kavach keep full authority.**

## 3. How it works
Observe → Verify (EvidenceGate) → Twin → Detect (RailGuard) → Optimise → **Human approves** → Driver advisory (Nexus Cab) → Audit

## 4. Key innovation
- Ranks alternatives on delay, conflict, **infrastructure stress**, energy, threat, evidence quality and complexity. Every factor is shown.
- **Fails closed**: stale or missing evidence gives HOLD or UNAVAILABLE, never a confident plan.
- Controller authority is separate from the driver advisory; the cab cannot choose a route.
- Every recommendation is checksummed and can be replayed exactly.

## 5. Prototype (screenshots from `evidence/screenshots/`)
- Nexus Control: candidates with factor bars
- Cab A and Cab B
- Stale-feed HOLD
- TwinTrack photo, once the hardware is built

## 6. Validation (measured)
- **6/6** judge scenarios pass (31 automated checks); **134** automated tests pass
- Randomised verification: **9.87M** checked operations; **0** violations on the final code with real data
- Verified on **56,395 real train runs** (1.26M actual arrivals): forecasts 13.7 vs 17.2 min error on unseen days
- Conflict detection: **100% recall, 100% precision** on 861 synthetic delay cases
- **0 false clears** in 42 injected fault cases
- **0** single-line overlaps across 462 executed plans
- Recommendation in **~10 ms** (median)
- Degraded section: **−24% track stress** for **+3.4 min** average delay vs the fastest plan
- **12/12** decisions replayed exactly; tampering detected

## 7. Deployment path
1. Tabletop and simulation (now)
2. Read-only shadow pilot
3. Authorised data integration (RTIS/COA, interlocking state)
4. Safety, security and human-factors validation
5. Approved integration

## 8. Ask
Railway-domain mentors, permitted datasets and interfaces, and a bounded shadow-evaluation opportunity.

**Limitations to state on the slide.**
- Demo network and simulated data.
- The stress index is relative and not certified.
- GNSS is not collision protection.
- Not signalling, interlocking, Kavach or movement authority.
