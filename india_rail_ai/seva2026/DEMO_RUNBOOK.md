# Judge demo runbook (about 6 minutes)

**Setup.**
- Run `python -m india_rail serve --host 0.0.0.0`.
- Open **Nexus Control** on the laptop.
- Open **Cab A** and **Cab B** on two phones or tablets (`/cab?train=A`, `/cab?train=B`).
- Rehearse once offline. If anything fails live, `POST /railguard/scenarios/{name}/run` replays any scenario headless.

**Opening (20 s).** "ClearPath Nexus does not control trains. It helps a controller compare evidence-backed alternatives, and it gives each driver a clean advisory view of the plan the controller approved."

| # | Do (in Nexus Control) | Show | Say |
|---|---|---|---|
| 1 | Scenario **Normal operation** → *Load*. Click **Rank alternatives**. | Evidence REVIEWABLE, all evidence FRESH; C1 = CONTINUE | "Every input has a source and an age. Nothing is stale, so a plan can be reviewed." |
| 2 | **APPROVE FOR DEMO** on C1, then **+5 min** a few times. | Both cabs switch from *awaiting plan* to their own route, speed and advisory band | "The driver sees only the approved plan. There is no route choice on the cab." |
| 3 | Load **Delay conflict** (Train A is 5 min late). | Threat CONVERGING_PATH (WARNING) on S06, with the time windows | "The late freight would meet the express on single line S06." |
| 4 | **Rank alternatives**. Point to the C1 factor bars and the "Lost on" lines of the others. | C1 reroutes A via bypass K; the hold options lose on delay | "Delay, conflict, track stress, energy, threat, evidence quality, complexity. Every factor is visible." |
| 5 | Load **Infrastructure protection**. Rank, then **Degrade S02**, then rank again. Toggle **FASTEST**. | BALANCED leaves the degraded bridge; FASTEST keeps it | "−24% track stress for about a minute. The controller can see the trade and choose." |
| 6 | Load **Threat awareness** → **Rank alternatives** → approve C1 → **+5 min** → **Obstacle S05** → **Rank alternatives**. | Cab A turns HOLD-FOR-CONTROLLER; ranking shows REVIEW; approve is greyed out | "A critical threat blocks approval until a person acknowledges it." |
| 7 | **Ack**, then **Rank alternatives**. | New plan avoids S05 | "Hard constraint: no plan through a reported obstacle." |
| 8 | Approve the new C1, then **Freeze A feed**, **+30 s** twice, and **Rank alternatives**. | Train A red/dashed; Cab A shows DATA UNAVAILABLE with no speed advice; Cab B rates A as LOW confidence; ranking shows HOLD | "When data goes stale, the system says so instead of pretending." |
| 9 | **Restore A feed**, **+30 s**, then **Replay snapshot**. | Integrity OK, ranking reproduced; audit chain OK | "Every recommendation can be rebuilt exactly. The checksum shows the record is unchanged, not that the inputs were true." |

**Close (15 s).** "We are asking for railway-domain mentors, permitted data, and a bounded shadow evaluation. Not permission to control trains."

**Backup.** Screenshots are in `evidence/screenshots/` and the scripted outputs in `evidence/scenarios/scenario_results.json`. Record a video of the full run as well.
