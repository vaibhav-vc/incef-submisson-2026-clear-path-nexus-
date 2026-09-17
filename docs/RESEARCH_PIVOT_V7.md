# EvidenceGate v7 research and system-design plan

**Authorship notice:** this is AI-assisted internal engineering planning, not a student-authored fair submission. See [international/Indian alignment and assistance disclosure](INTERNATIONAL_AND_INDIAN_ALIGNMENT.md). Students must prepare their own required submission materials under the actual fair's rules.

**Working title:** *From Prediction to Proof: Provenance-Aware Admissibility Gating for Railway Decision Support*

**Submission target:** INSEF 2026–27. **Software status:** research prototype, not an operational railway system. **Safety boundary:** EvidenceGate never issues movement authority, changes a signal, controls an interlocking, applies brakes, or instructs a driver.

## 1. Problem and falsifiable contribution

Indian Railways already has mature systems for freight operations, control-office work, automatic train-location updates, centralized traffic control, signalling, and automatic train protection. FOIS covers freight booking, rake/wagon movement, load and weighbridge data, commercial events, and tracking. COA covers train movement, consist, caution orders, line occupancy, diversion, and controller workflows. RTIS automatically supplies movement/location updates to COA. The RDSO CTC specification already covers headway and route conflicts, rescheduling and repercussions, timestamps, checksums, logs, and replay. Kavach supervises movement authority and speed.

EvidenceGate therefore does not claim that routing, wagon records, tracking, schedule-conflict detection, checksums, or driver speed advice are new. Its narrower research question is:

> Does a role-, authority-, scope-, freshness-, and lineage-aware evidence gate reduce false admission of unsupported railway decision-support recommendations compared with simpler validators, without producing an unacceptable false-hold rate or secondary timetable cost?

The inferred gap is a portable, recommendation-specific evidence envelope that combines the exact source snapshot, scoped source authority, event/fetch/valid time, subject context, required and optional roles, contradictions, complete lineage, policy/model version, fail-closed finding, review receipt, and independently reproducible bundle. Public specifications surveyed for FOIS, COA, RTIS, CTC, LDB, and ULIP do not clearly describe that exact portable contract. This is an inference from public material, not proof that internal railway systems lack equivalent controls.

## 2. Product boundary

The default v7 product is a **non-vital evidence-assurance workspace** with five functions:

1. Register an assurance case supplied by an external decision or incident workflow.
2. Evaluate each policy requirement in an evidence matrix.
3. Show scoped source identity, authority, licence, age, and availability.
4. Bind a reviewer attestation to one exact evidence root.
5. Reconstruct and export what was known at decision time.

Legacy v6 route, reliability, prediction, speed, scheduling, and multimodal demonstrations are not the scientific contribution. They must not be described as dispatch control, collision protection, regulatory compliance, or a replacement for FOIS/COA/RTIS/CTC/Kavach. They may supply external test recommendations to the gate, but they cannot change the assurance result or any real train state.

## 3. Six implementation phases

### Phase 1 — Claim and safety boundary

- Replace “railway command centre,” “dispatch,” “safe speed,” and “compliance” language with evidence-assurance terminology.
- Retire every route, journey, and schedule dispatch endpoint in the public research build.
- Keep schedule/consist/conflict logic only as non-vital research adapters and secondary-cost measurement.
- Publish a claim matrix: implemented, experimentally measured, planned, partner-dependent, and prohibited claims.

**Exit test:** no public UI action claims movement authority; retired endpoints fail before database mutation.

### Phase 2 — Semantic EvidenceGate hardening

- Require known source identity and a source/type contract.
- Bind owner, case/route, snapshot, request, and signed context.
- Validate entity-specific payload schemas and numeric ranges.
- Require non-excluded transitive ancestors for derived evidence.
- Reject broken/cyclic lineage, future timestamps, stale imports, role conflicts, and record/snapshot contradictions.
- Separate internal checksums from external issuer authenticity.
- Treat operator assertions as pending/supplementary unless a server-observed document or authenticated connector verifies them.

**Exit test:** every signed adversarial construction in the September 14 audit and subsequent red-team review returns `HOLD`, while an independently constructed valid control remains reviewable.

### Phase 3 — Generic assurance-case model

Add data independent of `generated_routes`:

- `assurance_cases`: owner, external system/case ID, case type, signed subject context, policy profile/version.
- `assurance_snapshots`: sequence, finding state, reason codes, evidence/policy/context digests, signature metadata.
- `case_evidence_links`: immutable association between a case, an evidence record, and a requirement; each assessment freezes the linked record digests into its snapshot.
- `assurance_findings`: deterministic requirement-level explanations and implicated records.
- `review_receipts`: append-only reviewer identity/role, outcome, signed snapshot root, and time. Receipt expiry/revocation is a later governed-identity extension, not an implemented claim.

Target API:

```text
POST /api/v1/assurance/cases
GET  /api/v1/assurance/cases
GET  /api/v1/assurance/cases/{case_id}
POST /api/v1/assurance/cases/{case_id}/evidence
POST /api/v1/assurance/cases/{case_id}/evidence-links
POST /api/v1/assurance/cases/{case_id}/assessments
GET  /api/v1/assurance/cases/{case_id}/assessments/{snapshot_id}
GET  /api/v1/assurance/cases/{case_id}/matrix
GET  /api/v1/assurance/cases/{case_id}/timeline
GET  /api/v1/assurance/cases/{case_id}/bundle
POST /api/v1/assurance/cases/{case_id}/review-receipts
POST /api/v1/assurance/cases/{case_id}/verify
GET  /api/v1/assurance/policies
GET  /api/v1/provenance/sources
```

The public `/evidence` write accepts only explicitly user-declared operator
input or an unauthenticated document import; it cannot claim `LIVE_PROVIDER`,
`AUTHORIZED_FEED`, or derived status. Authenticated server connectors and
transforms first create immutable provenance records, then `/evidence-links`
binds those records to a case without relabelling them.

Every eligible record now requires `assurance_subject_type`, `assurance_subject_key`
and `assurance_context_checksum` (the canonical checksum of the exact case context).
Existing adapters without these bindings remain ineligible until their authorized
connector implementation is upgraded; linking does not manufacture the bindings.
Required human declarations and unauthenticated imports remain HOLD.

Cases may assign a different reviewer account at creation. That reviewer can read
the case and, with an authorized approver role, issue one final receipt for the
latest intact snapshot. Capture and assessment remain creator-only. A returned
review reopens the case; a new assessment is required before another review.
Exports include the canonical signed manifest, evidence envelopes, source catalog,
lineage and receipt manifests. The dependency-free
`submission/verify_assurance_bundle.py` reconstructs canonical checksums offline;
HMAC signature authentication requires the trusted API.

**Exit test:** an assurance case and its evidence survive independently of any legacy generated route and reproduce the same root offline.

### Phase 4 — Real-data corpus and controlled faults

- Record official SNCF GTFS static and GTFS-Realtime trip-update/service-alert snapshots with retrieval time, HTTP metadata, licence, URL, and SHA-256.
- Keep raw observations immutable; never edit them into “cleaner” data.
- Generate controlled faults in separate derived fixtures: stale/replayed, wrong trip/service day, wrong corridor, duplicate, conflicting, missing parent, future time, wrong units/schema, tampered content, disabled/revoked source, and receipt/root mismatch.
- Label controlled faults as experimental mutations, never as real incidents.
- If authorized Indian Railways, ULIP, port, or operator data becomes available, ingest it through a separately approved connector and preserve its terms.

**Exit test:** every result row identifies the immutable real source snapshot and mutation recipe that produced it.

### Phase 5 — Comparative experiment

Evaluate the same frozen cases under:

- `B0`: parseable/latest-value only.
- `B1`: schema + timestamp + checksum.
- `B2`: source-agnostic quorum.
- `B3`: conservative block-if-any-input-missing.
- `B4`: legacy numerical trust score.
- `E`: full EvidenceGate.
- Ablations removing freshness, authority, context, lineage, contradiction, and receipt binding one at a time.

Primary metrics are false-reviewable rate on critical-invalid cases and false-hold rate on valid cases. Secondary metrics are balanced accuracy, Matthews correlation coefficient, p50/p95/p99 assessment latency, bundle verification success, storage size, evidence-reconstruction time, manual checks/actions, wagon-manifest coverage, and simulated secondary timetable delay. Use paired exact McNemar tests for gate outcomes, Wilson confidence intervals for proportions, Holm correction for multiple comparisons, and service-day/trip clustered bootstrap for latency where appropriate.

**Exit test:** frozen, independently labelled test cases; no repeated identifier-only cases presented as independent trials; complete raw rows and analysis script.

### Phase 6 — Release, offline judge edition, and three audits

- Build authenticated online and one-laptop/LAN offline judge editions from one commit.
- The offline edition uses clearly labelled staged evidence and makes no live/real-data claim.
- Export source, experiment, policy, environment, and artifact checksums.
- Rehearse clean installation, disconnected launch, evidence reconstruction, and bundle verification.
- Audit 1: correctness/security and adversarial gate review.
- Audit 2: scientific method/data lineage/statistical claims.
- Audit 3: clean-machine release, UI language, documentation, licence, and checksum consistency.

**Exit test:** a second machine can reproduce the benchmark and judge workflow without source edits; all three audits have dated results and unresolved limitations.

## 4. Real data and API registry

| Source | What it can validly support | Access/licence reality | EvidenceGate treatment |
| --- | --- | --- | --- |
| [SNCF GTFS static](https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip) | Published passenger timetable entities and scheduled trips | Public official French open-transport data; record the dataset licence and retrieval receipt | Immediate real-data benchmark source; not Indian freight authority |
| [SNCF GTFS-RT trip updates](https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-trip-updates) | Current trip-update messages | Public official feed; availability does not guarantee every record is semantically complete | Real live observations with schema/time/identity checks |
| [SNCF GTFS-RT alerts](https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-service-alerts) | Current service-alert messages | Public official feed | Optional/supporting role unless policy explicitly requires it |
| [SNCF dataset description](https://transport.data.gouv.fr/datasets/horaires-sncf?locale=fr) | Publisher, coverage, licence, update information | Authoritative catalogue metadata | Stored source-registry evidence |
| [Open-Meteo](https://open-meteo.com/en/docs) | Public weather observation/forecast for a named point/time | Free public API; not railway operating authority | Optional research input; never movement/speed authority |
| [NOAA SWPC](https://www.swpc.noaa.gov/products/planetary-k-index) | Planetary Kp space-weather telemetry | Public US government source | Supplementary telemetry only; not mandatory for ordinary rail cases |
| [CRIS FOIS](https://cris.org.in/loadpage?page=proFOIS) | Authoritative Indian freight, rake/wagon/load/commercial workflows | No anonymous public production API established | Comparator and future authorized connector; never scraped or fabricated |
| [CRIS COA](https://cris.org.in/loadpage?page=proCOA) | Authoritative control-office/train-movement workflow | Restricted operational system | Comparator/future partner integration only |
| [CRIS RTIS](https://cris.org.in/loadpage?page=proRTIS) | Automatic Indian train movement/location observations | Restricted operational integration | Comparator/future authenticated connector only |
| [ULIP](https://goulip.in/) | Cross-ministry logistics APIs | Registration, use-case review, NDA, security checks, and testing are required | Team must apply; no key or approval is promised by this repository |
| [Logistics Data Bank](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2299348&lang=2&reg=48) | EXIM container movement and multimodal visibility | Authorized ecosystem access | Future scoped connector, not duplicated as project novelty |
| [Indian Railways timetable catalogue](https://jk.data.gov.in/catalog/indian-railways-train-time-table) | Historical public timetable data | Historical/last-updated metadata must be retained | Historical transfer test only; never labelled current/live |

Free hosting and API services do not turn a data source into operational authority. GitHub Actions can run tests and scheduled recorders but is not an always-on FastAPI host. Vercel/Netlify can host the web client; Supabase can provide managed Postgres/auth; the FastAPI recorder/assessor still needs a suitable runtime. API credentials are supplied by the owner through environment variables and are never committed or exposed to the browser.

## 5. Carriage, speed, and timetable questions

### Carriage-by-carriage load

Yes: a load-sensitive consist must enumerate every expected wagon/carriage, its stable identifier and position, tare/cargo/gross mass, dimensions, axle count/load, brake data where applicable, source reference, observation time, and checksum. EvidenceGate must compare expected and received wagon counts and hold the case if even one required wagon is missing or unverified. FOIS and railway weighbridge integrations already address the operational record; the research contribution is verifying completeness and provenance before a downstream recommendation is admitted.

### Driver speed

EvidenceGate must not tell a driver what speed is safe. Any displayed speed is a simulation-only performance/energy envelope subordinate to the authorized timetable, signal aspect, movement authority, permanent/temporary speed restrictions, braking rules, driver instructions, and certified ATP/Kavach. The research can measure timetable repercussions of an externally supplied envelope; it cannot issue the envelope as authority.

### Other trains

The experiment can measure whether holding a recommendation causes secondary timetable delay and can compare conservative gating with required-versus-optional policies. It cannot promise that no other train is interrupted without authoritative, complete occupation, signalling, headway, priority, maintenance, and route data. RDSO CTC and operational controllers remain the correct authority.

## 6. Pre-registered success and failure criteria

Research targets—not industry certification thresholds:

- Zero false `REVIEWABLE` results on the frozen set of critical missing, unauthorized, wrong-scope, contradictory, invalid-ancestry, or root-mismatch cases.
- Less than 5% false holds on clean policy-compliant cases; report every false hold.
- At least 30% lower median reconstruction time than the selected baseline workflow in an approved pilot.
- At least 20% fewer manual cross-system checks/actions.
- At least 95% evidence-role coverage for the selected workflow.
- No claim of improvement if a simpler baseline performs equivalently with less burden.

## 7. Trust and security model

- SHA-256 detects byte changes; it does not prove authorship or real-world truth.
- The application HMAC proves EvidenceGate sealed a bundle; it does not prove an external railway/port/meteorological issuer created the content.
- External authenticity requires an authenticated connector, issuer signature/public key, or independently governed ingestion service.
- “Official” is always scoped to a source, subject, jurisdiction, purpose, and time.
- Unknown, missing, disabled, stale, excluded, contradictory, or unverifiable required evidence fails closed.
- Any material change creates a new root; an old reviewer receipt never transfers.

## 8. Architecture and reliability

```text
authorized/public source -> controlled recorder -> immutable raw snapshot
                                              -> source registry/receipt
external case ----------> context binder ----> policy evaluator
raw snapshot ------------> schema/time/scope/authority/lineage checks
                                                   |
                                                   v
                                  findings + evidence matrix + signed root
                                                   |
                              reviewer attestation + offline reconstruction
```

Online mode uses Supabase-issued identity, Postgres persistence, protected signing keys, bounded connector timeouts, explicit degraded states, and metrics/logging. Offline judge mode serves a local API and staged bundle over LAN and is visibly labelled non-operational. Provider failure never substitutes a reassuring value; optional evidence may be excluded only when the selected policy says it is optional.

## 9. Sources and prior art

- [RDSO CTC Functional Requirement Specification v2.0](https://rdso.indianrailways.gov.in/uploads/files/CTC%20revised%20FRS%20effected%20from%203rd%20Mar%202025.pdf)
- [RDSO Kavach v4.0 system requirements](https://rdso.indianrailways.gov.in/uploads/System%20requiremnt%20specification%20amd%203%20ver%204_0.pdf)
- [W3C PROV overview](https://www.w3.org/TR/2013/NOTE-prov-overview-20130430/) and [PROV-N Recommendation](https://www.w3.org/TR/2013/REC-prov-n-20130430/)
- [Understanding data quality in the rail industry, IEEE Big Data 2017](https://doi.org/10.1109/BigData.2017.8258380)
- [Freshness Detection Mechanism for Railway Applications](https://doi.org/10.1109/PRDC.2004.1276579)
- [Logical consistency verification of state sensing](https://doi.org/10.1049/itr2.12194)
- [OPTIMA railway communication platform](https://doi.org/10.1016/j.treng.2023.100222)
- [ACCESS machine-readable assurance cases](https://doi.org/10.1016/j.jss.2024.112034)
- [Limits of quantified assurance confidence](https://doi.org/10.1016/j.ssci.2016.09.014)
- [in-toto software supply-chain provenance](https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias)
- [Decision Provenance](https://arxiv.org/abs/1804.05741)

## 10. Honest submission statement

> We began with a broad railway operations platform. Comparison with official railway systems showed that routing, train control, tracking, consist management, conflict handling, and speed supervision were already mature and safety-governed domains. We rejected a delay model that lost to its deterministic baseline, removed mandatory space-weather influence, retired operational dispatch actions, and isolated a falsifiable contribution: whether context-aware, temporally valid, tamper-evident evidence assurance reduces critical evidence errors and reconstruction effort alongside authoritative railway systems.
