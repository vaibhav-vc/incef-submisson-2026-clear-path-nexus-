# Safety & integration boundaries — and where the code enforces them

| Boundary | Enforced by |
|---|---|
| No movement authority, points, signals, ATP or brakes | No such interface exists. `model.AUTHORITY = "ADVISORY_ONLY"` is stamped on every plan, threat and cab payload. |
| Only a named controller approves, and only the latest reviewable snapshot | `engine.approve` raises on an empty controller name, a superseded snapshot, or a non-REVIEWABLE state. The API adds `RAILGUARD_CONTROLLER_TOKEN`. |
| Driver never chooses a route | `cab.build_advisory` reads only `engine.approved`. Cab endpoints are GET-only (`test_api_cab_is_read_only_and_controller_token_enforced`). |
| Fail closed on stale or missing evidence | `EvidenceStore.assess` returns HOLD or UNAVAILABLE, and the approve button is disabled. The cab shows DATA UNAVAILABLE and withholds the speed band. If the cab loses its link, it blanks its guidance. |
| GPS is not collision protection | In the tabletop twin, simulated GNSS reports are compared, never applied. In the national twin, a signed cab-unit fix that passes every gate (receiver quality, map-matching to the planned route's track, plausible movement) becomes FRESH position evidence for that train: while fresh it is where the twin places the train (what it can still be re-planned from, what lies ahead of it), it can make a ranking reviewable and is shown on the cab; a fix showing the train well behind its plan records the lateness for the controller, as a late station report does. It never moves another train or approves anything, and a fix that fails a gate raises a threat for the controller instead. Proximity rules run on the twin, and nearby-train awareness is labelled "not collision protection". |
| Published times are information, not announcements | `publish.Publisher` only reads the twin (it never changes a plan or reaches a train); every response and page says NTES is official; times follow rules that never show a departure before the timetable and mark trains without a live report as SCHEDULED (hazard H24). Viewer role only. |
| Alert rules never hide a danger | `ThreatRegistry`: a CRITICAL threat is raised and cleared at once and comes back OPEN (blocking approval until acknowledged); an acknowledged threat that becomes more severe reopens; only non-critical threats are kept a minute after they stop being reported (hazard H25). |
| Hardware feed cannot approve | The feed endpoints only report observations. An obstacle report can raise a threat; only a controller can clear it. |
| Tabletop only | The firmware header and hardware README forbid connection to, or testing near, railway equipment. |

**The prototype is allowed to:**
- read simulated, public or authorised data;
- detect inconsistencies and simulated conflicts;
- rank alternatives;
- show controller recommendations and driver advisories;
- record audit trails;
- run a tabletop demo.

**It must not:**
- issue movement authority, or command signals or points;
- connect hobby hardware to a locomotive;
- override Kavach/ATP;
- claim GPS-only collision prevention, or claim a route is certified safe;
- direct a real loco pilot to ignore authorised rules.

**Gates before any real deployment.**
1. Authorised railway interfaces
2. Cybersecurity review
3. Railway safety and hazard analysis
4. Human-factors review
5. Independent verification and validation
6. Controlled shadow pilot
7. Field acceptance and approved integration
