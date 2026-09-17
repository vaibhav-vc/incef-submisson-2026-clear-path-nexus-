# ClearPath Nexus — government technical evaluation pack

Date: 17 September 2026. Prepared for technical discussion; not submitted to or endorsed by any government body.

## Proposed programme

Develop a successor railway operations platform with a staged migration from incumbent capabilities, beginning with an evidence-assurance component that can be evaluated independently. The full target includes freight and carriage state, operational train identity, traffic regulation, timetable impacts, controller workflows, operational data integration, resilience, security, and eventually assessed control interfaces. The [replacement architecture](INDIAN_RAILWAY_REPLACEMENT_ARCHITECTURE.md) defines these capabilities and the phased retirement gates. The objective is not considered achieved by deploying the current prototype.

The immediate proposal is for a **technical evaluation and authorized shadow pilot**. The requested institutional inputs are a nominated system owner, a nominated territory/workflow, approved data contracts, a representative replay corpus, incumbent comparison results, qualified reviewers, and agreed acceptance criteria. Procurement eligibility, funding, ownership, liability, operating authority and the assessment route need determination by the relevant institutions; none is presumed here.

## Existing systems and research basis

The proposed successor must preserve incumbent functions. CRIS identifies FOIS, COA, RTIS, NTES and related applications in its [official project inventory](https://cris.org.in/loadpage?page=ProjectListPage). [COA](https://cris.org.in/loadpage?page=proCOA) is integrated with multiple railway applications; [RTIS](https://cris.org.in/loadpage?page=proRTIS) supplies automatic movement information into COA. These integrations make identity, correction, completeness, timing and migration requirements material to any successor.

The [RDSO CTC functional requirement specification, version 2.0 effective 3 March 2025](https://rdso.indianrailways.gov.in/uploads/files/CTC%20revised%20FRS%20effected%20from%203rd%20Mar%202025.pdf) is a baseline for detailed interface and functional requirements analysis. Referencing it is not a claim of conformance. A clause-by-clause disposition must be agreed for the exact proposed system boundary and version.

The research hypothesis is that a recommendation-specific evidence contract can reduce admission of unsupported recommendations and improve reconstruction. The novelty claim remains a hypothesis requiring comparison with existing internal systems and published work. Routing, carriage records, train tracking, checksums and conflict checks are not claimed as new inventions.

## Capability and acceptance matrix

| ID | Requirement | Current implementation/evidence | Acceptance evidence still required |
|---|---|---|---|
| GOV-01 | Define every incumbent function to preserve or replace | Replacement architecture and gap matrix | Railway-approved scope and function-level traceability; migration owner for each function |
| GOV-02 | Authorized and attributable data | Source catalog, timestamps, licences, immutable public SNCF snapshots; mandatory subject/context bindings | Approved FOIS/COA/RTIS/engineering contracts, source authentication and reconciliation on actual data |
| GOV-03 | Complete carriage-level load | Expected carriage count, ordered rows, load/axle evidence and completeness validation | Authenticated weighbridge/yard/BPC input, actual consist reconciliation and error trials |
| GOV-04 | Avoid infeasible traffic and quantify secondary delay | Research section/headway conflict engine with explicit incomplete-evidence states | Full territory topology and occupations, disruption replay, controller-approved objectives and comparison against incumbent outcomes |
| GOV-05 | Prevent unsubstantiated evidence approval | Required human assertions remain HOLD; source/context/time/integrity checks and transitive lineage regressions | Independently designed adversarial corpus, domain-qualified interpretation of each evidence role, field false-admission/false-hold measurement |
| GOV-06 | Separate preparation and review | Creator-only writes; assigned independent reviewer; governed role; one final receipt per snapshot | Organization identity governance, reviewer competence records, revocation/expiry integration and multi-organization access evaluation |
| GOV-07 | Reconstruct decisions | Canonical manifests, source/lineage receipts, signed roots and offline checksum verifier | Independent replay of real pilot cases, key custody/rotation exercises, archive retention and correction policy |
| GOV-08 | Availability and recovery | Health/readiness checks, Compose deployment and CI service startup | Agreed service targets, representative endurance/load results, failover and measured backup restoration |
| GOV-09 | Security | Backend authorization, database API lockdown, source impersonation controls and dependency checks | Independent assessment, incident exercises, asset inventory, deployed configuration review and closure of material findings |
| GOV-10 | Controlled delivery | Versioned source, automated tests, migrations, exact research artifact hashes | Signed production release, bill of materials, deployment inventory, rehearsed rollback and operational support ownership |
| GOV-11 | Driver and control interfaces | Public speed/dispatch actions disabled; target architecture specifies future boundaries | Separate hazard-derived design, assessed interfaces, competent approval and supervised field trials before operational use |
| GOV-12 | Quantified value | Controlled experiment with baselines; metrics and limitations published | Authorized shadow evaluation of review time, erroneous admissions/holds, secondary delay and operator workload with predefined analysis |
| GOV-13 | National adoption | Territory-by-territory programme and retirement gates documented | Capability parity, accepted safety/security evidence, field benefits, multi-territory reliability and formal retirement authorization |

“Implemented” describes the code listed here. It is not a substitute for the missing acceptance evidence in the final column. The [release audit](V7_RELEASE_AUDIT.md) records software verification and the distinction between generic v7 tests and the legacy V2 benchmark.

## Evaluation procedure

1. Freeze the exact source commit, configuration, schema version, source contracts and required-role policy before running a trial. Register the decision type, scope, and which organization owns each input.
2. Build from the current checkout using the online or judge runbook. Apply migrations in an isolated environment; verify database/Redis readiness. The existing v6 downloadable binaries are historical.
3. Use the web workspace to create a case with actual subject/context and an explicitly assigned independent reviewer. Capture/import declarations through the documented `/api/v1/assurance` API; these remain unverified. Link provider evidence only after a trusted connector has created and authenticated its immutable record. The current interface does not establish official Indian Railway feed access.
4. Run the policy assessment. Inspect every failing requirement, source licence, observation/capture time, completeness limitation and lineage. Record both accepted controls and rejected cases; never discard failures to improve metrics.
5. The assigned qualified reviewer signs in separately and returns or attests the current assessment. Self-review, obsolete snapshots, changed evidence and duplicate final reviews must be rejected.
6. Export the bundle. Run `python submission/verify_assurance_bundle.py <bundle.json>` on a disconnected laptop. Compare the root with one obtained through a trusted channel and use the trusted API for HMAC signature authentication. Change an evidence value or lineage edge in a copy and confirm verification fails.
7. Compare results against the frozen incumbent/comparator workflow using authorized held-out cases. Publish the denominator, uncertainty, false-admission rate, false-hold rate, review time and observed secondary-delay effects. Do not interpret passing synthetic tests as railway safety performance.
8. Review findings jointly, agree corrective actions, rehearse rollback and approve the next scope only after its acceptance evidence exists.

## Data and infrastructure position

The available real research snapshot is official French SNCF public data with its published attribution and terms. Open-Meteo and NOAA adapters supply environmental observations when reachable. None provides complete Indian carriage loads, interlocking state, national occupations, braking authority or official working timetable data. Those inputs need authorized Indian Railway sources or permitted measurement systems. Missing inputs remain visibly unavailable.

The zero-cost web hosting and local judge deployment are suitable for development evaluation. No government production availability, response-time, data-residency, hosting approval, support SLA or disaster-recovery claim is made for a free hosting account. Hosting, network, operational staffing and assurance budgets must follow the agreed deployment requirement.

Offline judge mode contains labelled staged data and a local demonstration identity. It proves a disconnected demonstration path; it does not establish a railway degraded-operation procedure or an independent-review identity system. Online multi-user access is required to evaluate the assigned reviewer workflow.

## Decision requested at a first technical meeting

Agree an evaluation sponsor, a bounded first workflow, an approved source/data-access route, named technical reviewers, acceptance definitions, and a data-handling arrangement. After that, execute the shadow evaluation and use its evidence to decide whether the programme merits broader integration. No government message or application has been sent by this repository work.
