# Indian Railway Operations Modernization: Replacement-Grade Target Architecture

**Document status:** target-state architecture and gap analysis

**Date:** 15 September 2026

**Applies to:** the operational information, traffic-management, freight, train-location, centralized-control, interlocking-interface, and train-protection capabilities named below

**Does not claim:** that ClearPath Nexus currently implements, operates, has access to, is approved for, or is certified to replace any Indian Railways system

## 1. Executive decision

Replacing the present Indian Railways operational stack can be a long-term programme goal, but it is not a software-release goal. The target is a safety-governed, federated system-of-systems that reaches functional parity with the incumbent estate, proves safer or materially more effective operation, survives regional and national failures, migrates without a big-bang cutover, and earns the required institutional and safety approvals.

The current ClearPath Nexus repository is a research prototype and an early source-assurance component. It is not the replacement described in this document. A successful prototype, unit-test suite, cloud deployment, offline judge demo, or science-fair result would be evidence for continuing the programme; none would be authority to control a railway.

The term **replacement** in this document has a precise meaning:

1. Every incumbent capability in the agreed programme boundary has a named successor and accountable owner.
2. Every authoritative data producer has an approved interface, identity, service-level agreement, data-quality contract, and degraded-mode contract.
3. Safety functions have hazard-derived integrity requirements, independent verification and validation, an accepted safety case, type/site testing, controlled configuration, and operational approval.
4. The successor operates in shadow and then parallel service, meets frozen acceptance criteria, supports immediate rollback, and is adopted territory by territory.
5. The old component is retired only after the competent railway authorities accept the successor and its operational performance.

This architecture deliberately does not set “one app replaces all Indian Railways.” Passenger reservation, ticketing, finance, payroll, asset maintenance, security, customer support, and many other CRIS or departmental systems are outside the initial boundary. They can integrate through governed contracts; adding them to the replacement boundary requires a separate discovery, safety, privacy, and migration workstream.

## 2. Current public baseline

Public documentation establishes substantial incumbent capability. A replacement programme must integrate with and eventually reach parity with these systems rather than rediscovering only their visible screens.

| Incumbent capability | Publicly documented role | Architectural consequence |
|---|---|---|
| **FOIS** | Freight booking and commercial processes; rake, wagon, locomotive and freight-train monitoring; partner integration; actual consignment-weight exchange with in-motion weighbridges | Wagon/consist and freight records need authoritative FOIS migration or an approved FOIS contract. Public passenger data is not a substitute. |
| **COA** | 24×7 control-room workflow; real/near-real-time movement capture; BPC, caution order, train order, regulation, stabling, yarding, schedule modification and diversion; integration with FOIS, ICMS, NTES, RTIS and other applications | The successor needs controller workflow parity, authoritative train identity, operational orders, safe concurrency and cross-system reconciliation. |
| **RTIS** | Automatic satellite-based train position, speed and movement updates; control-chart plotting; emergency messaging; integration into COA/NTES | The successor needs authenticated on-board/central ingestion, sequence and clock handling, coverage state, uncertainty, and an explicit manual/degraded fallback. |
| **CTC/TMS** | Live indications, train description, traffic control, automatic route setting, conflict detection, timetable repercussions and operator-selectable resolutions, with OCC/BCC and interlocking interfaces | Generic pathfinding is not parity. The replacement needs complete resource constraints, deterministic command handling, high availability, replay, field interfaces and controller acceptance. |
| **Electronic/relay interlocking** | Enforces safe routes and prevents incompatible field commands according to approved application data | It remains the vital local authority. A replacement control platform must never bypass its checks. Replacing an interlocking is a separate SIL-governed product and site-application programme. |
| **Kavach/ATP** | Supervises movement authority and speed, including braking intervention and specified protection scenarios | A web or analytics service cannot replace ATP. Any future replacement must be an independently assessed vital product with approved onboard, stationary, radio, key-management and interface behaviour. |
| **LDB/ULIP and partner systems** | Multimodal/container visibility and governed logistics data exchange | A new multimodal screen is not sufficient differentiation. Use authorized contracts and preserve the external system's authority, licensing and correction semantics. |

Primary public sources for this baseline are [CRIS FOIS](https://cris.org.in/loadpage?page=proFOIS), [CRIS COA](https://cris.org.in/loadpage?page=proCOA), [CRIS RTIS](https://cris.org.in/loadpage?page=proRTIS), the [RDSO CTC FRS v2.0 effective 3 March 2025](https://rdso.indianrailways.gov.in/uploads/files/CTC%20revised%20FRS%20effected%20from%203rd%20Mar%202025.pdf), and the [RDSO Kavach v4.0 system requirements, amendment 3](https://rdso.indianrailways.gov.in/uploads/System%20requiremnt%20specification%20amd%203%20ver%204_0.pdf). The [2026 PIB LDB account](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2299348&lang=2&reg=48) documents existing national multimodal/container visibility at scale.

Public pages do not expose full internal architectures, schemas, incident records, cybersecurity controls, commercial terms, or every deployed version. All discovery conclusions must therefore be validated with the relevant system owners before a procurement or safety claim is made.

## 3. Programme scope and principles

### 3.1 Initial replacement boundary

The first target programme covers:

- authoritative railway topology and configuration distribution;
- master timetable, working timetable, special schedules and possessions;
- train identity, service journey, movement events and live operational state;
- freight booking linkage and wagon-by-wagon consist state;
- train regulation, conflict prediction and controller decision support;
- caution orders, temporary speed restrictions and relevant engineering constraints;
- OCC/BCC controller workflows and audit/replay;
- certified field gateways to existing interlockings;
- certified interfaces to Kavach/ATP and train-integrity sources;
- evidence provenance, data-quality enforcement and incident reconstruction;
- partner exchange with authorized government and logistics systems.

Replacing the interlocking logic or Kavach product itself is **not implied** by replacing their supervisory interfaces. Each vital product requires its own system definition, hazard analysis and certification programme.

### 3.2 Non-negotiable design principles

1. **Safety authority stays local.** Loss of a national, zonal or cloud service must not create an unsafe route, movement authority or braking command.
2. **Commands and observations are different types.** No telemetry, prediction, chat output, heuristic score or inferred location can be mistaken for a command.
3. **Fail safe, not merely fail closed.** The safe state is hazard- and context-specific and must be enforced by the certified vital boundary, not assumed by an HTTP error path.
4. **No hidden hardcoding.** Operational rules, topology, headways, vehicle limits, source authority and thresholds come from versioned, approved and signed configuration. The software may contain protocol constants, invariants and safe defaults, but not corridor facts disguised as code.
5. **Human authority is explicit.** Controller, station master, maintainer, signaller and driver responsibilities are represented by authenticated roles, territorial scope, shift/handover state and dual-control rules where required.
6. **Every state has provenance.** The system records source, event time, receive time, validity, correction history, confidence/quality where applicable, configuration version and decision use.
7. **AI is non-vital until proven otherwise.** Generative or statistical output may explain or rank non-vital options; it must not directly issue route, signal, movement-authority, temporary-speed-restriction or brake commands.
8. **Open contracts, controlled authority.** Interface specifications should be portable and testable, while production access, credentials and actions remain strictly authorized.
9. **Migration is reversible.** Every territory cutover includes shadow comparison, parallel operation, rollback triggers and restoration rehearsals.
10. **Evidence precedes claims.** Availability, safety, throughput, delay improvement and false-alert claims come from frozen tests and operational trials, not architecture diagrams.

## 4. Required operating model

### 4.1 Authority hierarchy

| Layer | Owns | Must not own |
|---|---|---|
| Ministry/Railway Board programme governance | policy, funding, system boundary, enterprise accountability, adoption and retirement decisions | individual real-time train commands |
| RDSO and designated assurance authorities | applicable specifications, product/system assessment inputs, test and approval processes | routine traffic regulation |
| National platform operations | shared identity, schema registry, national reference data, cross-zone observability, aggregated planning and disaster coordination | single point of failure for safe local movement |
| Zonal/divisional OCC and BCC | territory traffic regulation, priorities, possessions, controller workflow and degraded-operation coordination | bypass of interlocking or ATP |
| Station/territory vital systems | route safety, field state, command interlocking, local safe failure | commercial or passenger-facing truth |
| Onboard ATP/Kavach and driver | speed supervision/braking functions per approved design; driver operation under applicable rules and authority | accepting a web-app recommendation as movement authority |
| Source-system owners | authoritative facts within an approved scope | silent semantic changes or unversioned corrections |

### 4.2 Safety and non-safety partition

The architecture has three trust zones:

- **Vital OT zone:** interlocking, field I/O, certified communications and ATP/Kavach functions. Only assessed binaries, data and interfaces operate here.
- **Operational control zone:** CTC/TMS, controller workstations, movement registry, timetable/conflict engine, operational orders and audit. This zone may include safety-related functions whose integrity classification is assigned by hazard analysis. It does not inherit a SIL merely because it is important.
- **Enterprise/research zone:** analytics, evidence reconstruction, public information, simulations, machine learning, reporting and external partner services. It cannot directly reach field command interfaces.

Data flows outward through allow-listed, monitored conduits. Commands flow inward only through an authenticated command broker, territory-authority checks, deterministic validation, operator confirmation where required, and the certified field gateway. There is no general-purpose database trigger or message consumer that can actuate field equipment.

## 5. Target architecture

```text
                         National governance plane
       identity | schema registry | PKI/HSM | policy/config registry
       national audit index | fleet/timetable reference | SOC/NOC
                                    |
                 +------------------+------------------+
                 |                                     |
       Zonal/Divisional Region A                Zonal/Divisional Region B
     +---------------------------+             +---------------------------+
     | OCC active cluster        |             | OCC active cluster        |
     | BCC isolated standby      |             | BCC isolated standby      |
     | movement/state registry   |<--events--->| movement/state registry   |
     | timetable/conflict engine |             | timetable/conflict engine |
     | order/command broker      |             | order/command broker      |
     | evidence + audit ledger   |             | evidence + audit ledger   |
     +-------------+-------------+             +-------------+-------------+
                   | certified territory conduit             |
          +--------+--------+                        +--------+--------+
          | station/field   |                        | station/field   |
          | gateway pair    |                        | gateway pair    |
          +---+---------+---+                        +---+---------+---+
              |         |                                |         |
       interlocking   Kavach/ATP                   interlocking   Kavach/ATP
       and field I/O  interfaces                   and field I/O  interfaces

 External authoritative systems enter through governed adapters:
 FOIS | COA migration bridge | RTIS | ICMS/CMS/NTES | engineering/TSR
 traction SCADA | weather when operationally approved | ports | ULIP/LDB
```

### 5.1 National governance plane

The national plane is a governance and coordination plane, not a national vital controller. It provides:

- canonical identifiers and reference-data distribution;
- schema and compatibility registry;
- certificate, key, device and workload identity lifecycle using HSM-backed roots;
- signed operational configuration publication and revocation;
- national timetable and cross-region coordination views;
- audit-location catalogue and evidence retention policy;
- cybersecurity monitoring and incident coordination;
- software/configuration release registry, SBOMs, attestations and rollback packages.

Safety-relevant configuration is approved, signed and distributed ahead of use. Regions verify signatures and activation windows locally. National-plane unavailability prevents unsafe new configuration activation but does not invalidate already approved local operation within its defined lifetime.

### 5.2 Zonal/divisional operational cell

Each bounded control territory owns an operational cell with an active OCC deployment and a separately faulted BCC. It contains:

- a strongly consistent authority/command store within the territory;
- an append-only operational-event log and time-indexed state projections;
- a timetable, path and resource model;
- train identity and movement correlation;
- conflict detection, consequence evaluation and explainable options;
- controller workstations, shift handover, voice/event linkage and alarm management;
- EvidenceGate for source admissibility and exact decision reconstruction;
- interfaces to neighbouring cells using explicit handover protocols.

Regional replication is not permission for two territories to command the same field resource. A lease/authority token is subordinate to the certified field boundary, narrowly scoped, time-bounded, fenced by monotonically increasing epochs, and transferred only by an approved handover procedure.

### 5.3 Station and territory edge

Station/territory gateways terminate dedicated railway communications and normalize approved interfaces. They provide:

- protocol validation, sequencing, freshness and replay protection;
- local time holdover and explicit clock-quality status;
- store-and-forward for non-command observations;
- bounded signed configuration cache;
- dual-channel/hot-standby operation where the approved design requires it;
- command fencing so stale, duplicate, wrong-territory or wrong-configuration requests are rejected;
- health and maintenance telemetry on a separate management path.

The gateway does not recreate interlocking logic in ordinary application code. The interlocking remains the final route-safety authority, and the ATP/Kavach safety boundary remains independent.

## 6. Canonical data contracts

### 6.1 Common event envelope

Every authoritative event must carry, at minimum:

```json
{
  "schema_version": "ir.operation-event/1.0",
  "event_id": "uuid",
  "event_type": "train.position-observed",
  "aggregate_type": "train_run",
  "aggregate_id": "stable-id",
  "authority": {
    "organization": "registered-owner",
    "system": "registered-source",
    "scope": ["territory-or-asset"],
    "credential_id": "key-or-device-id"
  },
  "source_sequence": 123456,
  "event_time": "RFC3339 timestamp",
  "observed_at": "RFC3339 timestamp",
  "received_at": "RFC3339 timestamp",
  "valid_from": "RFC3339 timestamp",
  "valid_until": "RFC3339 timestamp or null",
  "topology_version": "approved-version",
  "timetable_version": "approved-version or null",
  "correlation_id": "end-to-end-id",
  "causation_id": "prior-event-id or null",
  "correction_of": "prior-event-id or null",
  "quality": {"status": "measured", "uncertainty": null},
  "payload": {},
  "payload_sha256": "hex",
  "signature": {"algorithm": "approved-suite", "key_id": "id", "value": "..."}
}
```

The exact cryptographic suite and certificate profile are procurement/certification decisions. A checksum detects accidental or post-capture change; it does not authenticate the issuer. Authenticity requires an approved credential, protected key, verified scope, revocation status and trusted ingestion boundary.

### 6.2 Event rules

- IDs are immutable and stable across applications; aliases are explicit mappings.
- Event time, observation time, receipt time and validity are never collapsed into one timestamp.
- Units use a controlled registry; conversions record source unit and transformation version.
- Corrections append and supersede; they never silently rewrite history.
- Every consumer declares supported schema ranges and fails visibly on incompatible versions.
- Sequence gaps, duplicate IDs, key revocation, clock uncertainty, late arrival and source outage are first-class states.
- The producer publishes completeness semantics: expected cardinality, end-of-batch marker, partition/territory, and reconciliation watermark.
- Commands have a different schema family, channel, credential policy and retention class from observations.

### 6.3 Core entities

| Entity | Required identity/version semantics |
|---|---|
| `infrastructure_resource` | stable asset/resource ID, topology version, geometry/direction, controlling territory, interlocking reference, validity |
| `train_service` | planned service identity and operating dates; not reused as a live journey identity |
| `train_run` | unique dated journey, direction, authority handovers, service links and status history |
| `consist_version` | immutable ordered vehicle list, applicable train-run interval, source, verification state and supersession |
| `vehicle` | registered vehicle/wagon/coach ID, type and approved technical limits |
| `occupation` | resource, direction, train/vehicle if known, source, start/end or uncertainty, sequence and quality |
| `movement_authority_reference` | opaque reference to the certified authority, territory, validity and state; sensitive vital payload remains in its approved system |
| `operational_order` | order type, issuer, recipient/scope, issue/acknowledgement/effective/withdrawal times and exact document version |
| `timetable_plan` | immutable plan version, train paths, timing points, resources, allowances, priorities and approval state |
| `evidence_bundle` | exact input event IDs/hashes, policy and model versions, exclusions, lineage, finding, reviewer receipt |

## 7. Wagon, coach and consist model

A load-sensitive or braking-sensitive computation must represent every vehicle individually and the whole train as an aggregate. It should not ask an operator to retype every wagon when an authoritative FOIS, yard, RFID, BPC or weighbridge feed is available; it must preserve the per-vehicle record and its source.

Each consist version requires:

- expected and observed vehicle count;
- vehicle/wagon/coach ID and ordinal position, including locomotive(s), brake/guard vehicles and end-of-train equipment where applicable;
- vehicle class/type, tare mass, declared load, measured load when available, gross mass and units;
- axle count, axle-load distribution or approved derivation, length and relevant loading/gauge constraints;
- brake system/state and BPC reference where the authorized workflow supplies it;
- commodity/dangerous-goods classification and handling constraint when applicable and permitted;
- origin, destination, attach/detach/reversal events and effective times;
- source system, observation/measurement time, sequence, quality, checksum/signature and verifier;
- completeness marker and explicit reason for every unknown field.

Validation invariants include:

```text
ordered vehicle IDs are unique
expected vehicle count == received vehicle count
sum(vehicle gross mass) == consist aggregate within approved tolerance
vehicle gross mass == tare + load within approved tolerance
each axle/vehicle/load/length limit satisfies approved route and structure constraints
brake/continuity evidence applies to this exact consist version
any attach, detach, reversal or material measurement creates a new consist version
```

Missing or conflicting required vehicle data produces `INCOMPLETE/HOLD`; it must not be replaced with a guessed “average carriage.” Passenger occupancy, commercial capacity and engineering load are separate facts with different authorities. FOIS's public documentation already describes wagon/fleet monitoring and in-motion-weighbridge exchange; replacement value must come from authorized integration and better assurance, not fabricated live values.

## 8. Timetable and conflict management

The planning/control model is a time-dependent resource-allocation problem, not a shortest-path graph alone.

### 8.1 Hard constraints

- mutually exclusive and incompatible routes;
- block/section occupation by direction and applicable working method;
- interlocking route release and flank/overlap constraints as exposed by approved interfaces;
- platform length, route, direction and occupancy;
- headway by infrastructure, signalling, train class, speed profile and operating condition;
- permanent and temporary restrictions, possessions and engineering blocks;
- traction-power limitations and OHE isolation/power blocks;
- rolling-stock, load, axle, gauge, braking and route compatibility;
- crew, locomotive, rake and maintenance availability where in programme scope;
- connections and handovers across neighbouring territories;
- emergency and special-order constraints.

### 8.2 Objectives and outputs

Candidate objectives may minimize weighted secondary delay, cancellations, missed connections, freight commitment failures, platform changes, energy use and recovery time while preserving published priorities and operational rules. Weights are versioned, approved policy—not source-code constants.

The engine returns multiple feasible options with:

- changed resources and timing;
- affected trains, passengers/freight commitments and downstream territories;
- predicted direct and secondary delay;
- binding constraints and rejected alternatives;
- evidence age/completeness;
- the policy/objective version;
- uncertainty and degraded-data warnings.

The operator remains in charge during non-vital decision-support phases. The current RDSO CTC FRS already specifies station and inter-station conflict classes, priority-based alternatives, repercussions and operator selection. Replacement acceptance therefore requires parity and measurable improvement over that workflow, not merely a new UI.

### 8.3 “Do not interrupt other trains” requirement

No system can honestly promise zero interruption under all disruptions. The enforceable requirement is:

> Never recommend or command a plan that violates a hard safety/occupation constraint; minimize and expose secondary timetable impact according to approved policy; and re-evaluate every affected train and resource after a state or plan change.

An acceptance test uses complete territory timetables plus neighbouring-boundary traffic, injects disruptions, and compares secondary-delay distribution, cancellations, infeasible proposals, compute latency and operator acceptance with the incumbent workflow.

## 9. Speed, movement authority and driver interface

A recommended speed is never the movement authority. Any advisory envelope must be below the most restrictive applicable authorized constraint:

```text
advisory ceiling = minimum of
  certified movement-authority / ATP braking envelope,
  signal and block-working authority,
  permanent speed restriction,
  temporary speed restriction and caution order,
  route/curve/structure limit,
  vehicle and consist limit,
  braking-performance limit,
  approved weather/adhesion restriction,
  timetable or energy target.
```

The vital ATP/Kavach system performs certified speed supervision and intervention. A non-vital optimizer may propose an energy- or punctuality-efficient target below the ceiling only when every required input is authoritative, current and complete. Loss, conflict, staleness or uncertainty of a required restriction removes the advisory; it must not relax the certified limit.

Before any driver trial, complete:

- human-factors and workload analysis, including alarm rate and distraction;
- unambiguous visual/audio priority relative to approved cab indications;
- simulator trials and pre-approved human-participant research where applicable;
- wrong-side failure analysis for stale/misidentified train, track, direction, consist, clock and restriction;
- independent verification of braking and transition behaviour;
- interface and safety approval for the exact rolling-stock and territory application.

The present repository must describe speed output as simulation-only. A production driver advisory is a separate assessed workstream, and an ATP replacement is a separate vital product programme.

## 10. APIs and integration contracts

### 10.1 Required authoritative interfaces

| Interface family | Required producer/owner | Minimum contract |
|---|---|---|
| Train movement/location | RTIS/onboard system, CTC/COA or approved infrastructure source | train-run identity, position/resource, direction, speed where authoritative, observation and receive times, sequence, coverage/quality, correction and outage state |
| Occupation/field indication | certified interlocking/CTC field interface | resource/application-data version, vital/non-vital classification, sequence, state, time, communication health and fail-safe semantics |
| Movement authority / ATP | certified Kavach/ATP boundary | narrowly specified approved protocol; authentication, sequence/freshness, territory/train binding, safe timeout; no general REST control endpoint |
| Timetable/path | SATSaNG/authorized timetable owner and controller amendments | immutable plan version, operating date, timing points, paths/resources, allowances, priority, approval and supersession |
| Consist/freight | FOIS/ICMS/yard/BPC/weighbridge owners | per-vehicle records, ordering, weights/units, commercial/engineering authority separation, completeness, verification and effective interval |
| Restrictions/orders | authorized engineering/operations order system | asset/route/direction scope, issuer authority, exact document, issue/effective/expiry/withdrawal, acknowledgement and revision |
| Crew/traction/maintenance | CMS, traction SCADA and maintenance owners | resource identity, availability/constraint semantics, validity, authority and privacy classification |
| Multimodal handoff | ULIP/LDB/PCS/terminal/carrier through approved agreements | shipment/container/booking identity, milestone semantics, event/correction times, rights, licence and outage state |
| Weather/environment | operationally approved provider or railway sensors | geospatial scope, observed vs forecast, issue/valid time, units, quality and threshold-policy link |

No anonymous public API was established for production FOIS, COA, RTIS, interlocking or Kavach control. “Get the API” requires a named Railway/CRIS/RDSO/system-owner use case, data-sharing and security agreement, network onboarding, test environment, credentials, schema documentation, support contacts, service levels and production approval. The system must display `UNAVAILABLE/NOT_AUTHORIZED`; it must never fill a missing authority with demo or scraped values.

### 10.2 Interface styles

- **Streaming events:** an approved durable log protocol for movement, occupation and telemetry, partitioned by authority/territory with idempotent consumers.
- **Transactional commands:** a separately secured command channel with request ID, authority epoch, expected-state precondition, expiry, acknowledgement and final disposition.
- **Queries:** REST/gRPC read APIs for bounded state and history, with snapshot/version tokens so callers know what was consistent.
- **Bulk/reference data:** signed manifests plus content-addressed packages for topology, timetable, configuration and historical replay.
- **Field/OT:** only protocols and physical/network designs approved for the specific RDSO/railway application; no assumption that ordinary internet APIs are suitable.

### 10.3 Example non-vital API surface

```text
GET  /v1/reference/topologies/{version}
GET  /v1/train-runs/{id}?as_of={event-watermark}
GET  /v1/train-runs/{id}/consist/{version}
GET  /v1/territories/{id}/occupations?as_of={watermark}
GET  /v1/timetable-plans/{version}
POST /v1/conflict-studies
GET  /v1/conflict-studies/{id}
POST /v1/evidence/cases
GET  /v1/evidence/cases/{id}/bundle
POST /v1/evidence/bundles/{id}/verify
```

The public/non-vital API never exposes an endpoint such as `set_signal`, `issue_movement_authority` or `apply_brake`. Assessed command interfaces are not internet-facing and are documented under controlled system specifications.

## 11. Storage and consistency

| Data class | Storage pattern | Consistency/retention rule |
|---|---|---|
| Territory command/authority state | synchronous replicated transactional store, fenced writer | linearizable within authority scope; no split-brain commands |
| Operational event history | append-only replicated log plus immutable archive | ordered per source/aggregate; correction by new event; retention set by railway/legal policy |
| Live state projection | in-memory/time-series projection rebuilt from events/checkpoints | bounded staleness published with every response |
| Topology/timetable/configuration | content-addressed immutable objects plus approval metadata | activation by signed version and effective interval; local last-known-approved cache |
| Evidence/audit | WORM-capable archive with signed manifests and independently verifiable export | access logged; legal/privacy retention; cryptographic-agility plan |
| Analytics/research | de-identified lakehouse separated from operations | no write path to operational or vital state; reproducible datasets and lineage |

Cross-region state is eventually consistent for analytics, but boundary train handover and command authority use an explicit protocol. Consensus is kept within failure domains small enough to remain available and testable; a nationwide consensus cluster must not become a movement dependency.

## 12. Availability, capacity and disaster recovery

The RDSO CTC FRS publicly specifies 99.99% for critical functions/interfaces, 99.97% for non-critical functions/interfaces, no more than two seconds from wayside state change to central display, dual-active/hot-standby server redundancy, a BCC, and redundant field communications. These are minimum comparator requirements for a CTC replacement, not proof that this design meets them.

### 12.1 Candidate programme SLOs

These are proposed acceptance targets to be ratified by the railway and revised by hazard/RAMS analysis:

| Service | Candidate target | Failure response |
|---|---|---|
| Local interlocking/ATP safety functions | applicable approved RDSO product requirements and accepted safety case | remain safe and locally operable without national/zonal application service |
| Critical territory control/display | at least the current 99.99% comparator; state-change display within the applicable approved bound | seamless local failover; station/degraded working under operating rules |
| Non-critical planning/reporting | at least the current 99.97% comparator | queued/retried work; never affects safe movement |
| Accepted command and audit record | RPO 0 within the command authority domain | reject ambiguous outcome, reconcile with field state, never blindly retry a non-idempotent command |
| OCC loss | BCC transfer target established and rehearsed per territory hazard/operations plan | fenced authority transfer, controller handover and station fallback |
| National governance/analytics loss | no unsafe local operational effect | regions use bounded last-known-approved data; defer new national configuration |

### 12.2 Capacity engineering

Do not size from guessed train counts. During authorized discovery, measure events per source, peak-to-average ratio, bursts at control boundaries, timetable recalculation fan-out, retention, evidence-bundle size and recovery replay rate. Then test:

- sustained peak plus approved growth headroom;
- at least the agreed burst multiplier without loss or unbounded latency;
- full regional loss and replay without duplicate state transitions;
- timetable disruption causing simultaneous re-evaluation of all affected trains;
- key/certificate rotation and configuration rollout at peak;
- BCC takeover, dual link cuts and stale/late event storms.

Capacity results must report loss, duplicates, out-of-order depth, end-to-end age, p50/p95/p99 latency, recovery time and operator-visible degradation—not requests per second alone.

### 12.3 Multi-region and failure domains

- Primary and BCC sites use separate power, communications, physical risk and administrative failure domains.
- Zonal cells exchange state but retain bounded territorial authority.
- A region loss does not silently transfer command authority; the approved handover protocol fences the old epoch first.
- Backups are encrypted, offline/immutable where required, restored in exercises, and checked against configuration and key dependencies.
- Time sources are redundant; each event publishes clock quality/uncertainty. Loss of trusted time narrows or removes functions that depend on freshness.

## 13. Offline and degraded operation

“Offline” has different meanings and must not be represented by a single UI toggle.

| Condition | Permitted behaviour | Prohibited behaviour |
|---|---|---|
| National platform disconnected | continue local operation on approved territory data; queue non-vital events; show loss | fetching new national rules or treating cached analytics as current authority |
| OCC to station communication loss | operate under approved railway degraded/block-working procedures; local vital systems maintain safety | remote command retries with unknown outcome; inferred field state shown as confirmed |
| Source feed unavailable | preserve last observation with age and outage state; HOLD affected decision roles | silently converting last-known data to “live” or inventing replacements |
| BCC takeover | explicit fenced authority transfer, authenticated operator handover, reconciliation | simultaneous active command from OCC and BCC |
| Judge/demo laptop offline | synthetic or previously captured replay, conspicuously labelled; no external dependency | claiming real-time Indian Railway operation or live authority |

Store-and-forward is allowed for observations and audits. It is not a generic strategy for expired commands. Reconciliation uses source sequence, event identity, correction links and approved conflict resolution; “last write wins” is not acceptable for authority, restriction or consist state.

## 14. Cybersecurity architecture

RDSO's Kavach cloud/cybersecurity requirements reference EN 50126, IEC 62443, ISO 27017 and EN 50701. The replacement programme must tailor the current applicable standards and Indian government requirements with the competent authorities; listing a standard is not compliance.

Required controls include:

- IT/OT segmentation into documented zones and conduits; deny-by-default crossings;
- workload, device and human identities with MFA, hardware-protected keys and short, scoped credentials;
- RBAC plus attribute checks for territory, shift, duty, train/resource and action;
- dual authorization and independent confirmation for defined high-impact actions;
- mTLS/message signing, anti-replay sequence/nonce/expiry and certificate revocation that works during network degradation;
- secure boot, measured boot, firmware/application signing, protected maintenance ports and asset inventory;
- tamper-evident centralized audit plus local buffered logging, synchronized time and voice/action correlation;
- SBOM and hardware/software/AI bill of materials, dependency provenance, reproducible builds and release attestations;
- threat modelling, SAST/DAST/fuzzing, protocol robustness, penetration and red-team testing in representative environments;
- controlled patch/vulnerability process that assesses both security risk and safety regression;
- offline signed recovery media and independently tested clean-room restoration;
- vendor remote access disabled by default, time-boxed, approved, recorded and routed through controlled access infrastructure;
- data minimization, purpose/role controls, encryption and applicable compliance with the [Digital Personal Data Protection Act and rules](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit);
- CERT-In incident reporting/log obligations and audits by appropriately empanelled organizations where applicable.

Relevant official references include the [RDSO Kavach Cloud and Cyber Security Requirements, Annexure R](https://rdso.indianrailways.gov.in/uploads/2025-04-29-Annexure%20R.pdf), [CERT-In Guidelines for Government Entities](https://www.cert-in.org.in/guidelinesgovtentities.jsp), [CERT-In API security guidance](https://www.cert-in.org.in/PDF/CIWP-2023-0001.pdf), and [CERT-In Directions under section 70B](https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf).

Cyber controls must not create a wrong-side safety failure. The safety case and cybersecurity case share assumptions, configuration, incident scenarios and change-impact analysis.

## 15. Safety assurance and certification path

The safety lifecycle applies to the exact system boundary and application, not to the project name. Integrity levels are assigned by hazard and risk analysis. It would be wrong to call the entire platform “SIL-4” or to infer certification from using a SIL-rated component.

### 15.1 Required assurance artefacts

1. System definition, operational concept, boundary and authority model.
2. Applicable laws, rules, RDSO/IRS specifications and standards register with controlled versions.
3. Hazard identification and risk analysis covering normal, degraded, maintenance, migration and cybersecurity conditions.
4. Safety requirements allocation and bidirectional traceability through design, code/configuration, tests and hazards.
5. Independent verification and validation plan; organizational independence and competence evidence.
6. Software/hardware/configuration safety plans and tool-assurance decisions.
7. Preliminary, subsystem and functional hazard analyses; tolerable hazard-rate rationale where applicable.
8. Interface hazard analysis for COA/CTC, interlocking, ATP/Kavach, field gateway, time, telecom and external sources.
9. Generic product safety case and specific application/site safety case.
10. Cybersecurity risk assessment and security-assurance case linked to safety assumptions.
11. Human factors, alarm management, workload, training, competence and operating-rule changes.
12. Factory/type tests, integration tests, simulator tests, site/application-data tests, failure-injection tests and trial reports.
13. Independent Safety Assessor findings, closure evidence and residual-risk acceptance by competent authority.
14. Configuration baseline, release signatures, asset serials, installation/commissioning records and rollback plan.
15. Post-commissioning monitoring, incident/near-miss reporting, change control and periodic reassessment.

The RDSO Kavach requirements explicitly call for independent safety assessment to SIL-4 for the relevant hardware/software and list hazard log, PHA, SSHA, FHA, THR, reliability, software/protocol evaluation and a generic application safety case among the documentation. The [RDSO vendor-approval work instruction](https://rdso.indianrailways.gov.in/uploads/Work%20instruction%20for%20vendor%20approval%20in%20Signal%20Directorate%2008_06_2023.pdf) also demonstrates that successful type testing can be followed by bounded field performance assessment before wider supply. The exact current procedure must be confirmed with RDSO and the procuring railway for this product and date.

### 15.2 Release gates for vital influence

No component may influence movement, signalling or braking merely because it passed ordinary CI. Before crossing that boundary, all of these are required:

- frozen and approved operational boundary;
- hazard-derived integrity allocation;
- independent V&V with zero open unacceptable safety findings;
- deterministic behaviour and timing evidence for the assessed configuration;
- secure and fail-safe interface test under corruption, loss, replay, delay, duplication, split brain and clock faults;
- application-data verification for the exact territory;
- operator/maintainer competence and rehearsed degraded procedures;
- type/site/field trials required by the approving bodies;
- accepted safety case and written commissioning authority;
- rollback and emergency-isolation proof.

## 16. Operations and support model

Replacement-grade software requires a permanent operational organization:

- 24×7 OCC/BCC staffing and accountable traffic authority;
- 24×7 NOC for application, network, database, time and device health;
- central and zonal SOC coordination with OT-aware detection and response;
- service desk, escalation, vendor/OEM support and spare strategy;
- safety incident manager distinct from routine SRE incident command;
- controlled shift handover and current contact/territory roster;
- runbooks for partial data, telecom loss, clock loss, source disagreement, split brain, cyber isolation, rollback and manual/degraded working;
- immutable timeline and evidence package for every significant incident;
- safety performance indicators, false-alarm burden, unavailability, command ambiguity, data-age breaches and near misses;
- scheduled disaster, BCC, restore, key-recovery and degraded-operation exercises;
- safety-governed change advisory process and emergency-change reconciliation.

For vital or safety-related components, automatic continuous deployment to production is inappropriate unless the certified lifecycle explicitly permits that mechanism. Releases use assessed binaries/configuration, segregation of duties, staged territory rollout and evidence of exact deployed versions.

## 17. Procurement, ownership and commercial requirements

A replacement cannot be procured as an unspecified “AI railway platform.” The buyer must own the outcome, system boundary, data, safety responsibilities and acceptance evidence.

Tender/procurement packages should require:

- complete functional and non-functional baseline with incumbent parity traceability;
- open, versioned interface and test specifications; no opaque proprietary lock-in at safety boundaries;
- railway ownership or durable rights for operational data, configuration, schemas, audit and migration tooling;
- source escrow/continuity provisions appropriate to criticality, plus build and deployment reproducibility;
- named safety, cybersecurity, privacy and quality responsibilities across buyer, integrator and subsystem vendors;
- ISA independence and access to evidence;
- test environments, reference simulators and conformance suites available to competing vendors;
- availability, support, spares, vulnerability-remediation, obsolescence and lifecycle obligations;
- data-centre/on-premise/cloud-residency and network requirements approved for the data/system classification;
- training and competence transfer to railway personnel;
- performance payments tied to frozen operational outcomes, not dashboard delivery;
- exit, data export, certificate/key transition and safe supplier-replacement plans;
- field-trial quantities/duration and stop/rollback rights;
- audit rights for subcontractors and software/hardware supply chains.

Government procurement route, Railway Board/RDSO involvement, zonal ownership, Commissioner of Railway Safety involvement and other approvals depend on the exact works and statutory scope. Legal/procurement specialists and the competent railway authorities must define them; this document does not grant or substitute for those approvals.

## 18. Migration phases

### Phase 0 — programme definition and authority discovery

**Purpose:** establish what is actually being replaced and who can authorize it.

Deliverables:

- signed system boundary and incumbent capability catalogue;
- responsible owners for FOIS, COA, RTIS, timetable, CTC, interlocking, Kavach, engineering, telecom, traction, security and each pilot territory;
- interface/data-access agreements and controlled test environments;
- rules/standards register, hazard classification plan and independent assessor strategy;
- observed workload and operational baseline;
- programme governance, procurement route, funding and stop criteria.

**Exit gate:** no unknown owner or authority for any pilot-critical input/action; no “API later” dependency hidden in the plan.

### Phase 1 — evidence and observation shadow

**Purpose:** prove canonical identity, provenance, data quality and reconstruction without affecting operation.

Deliverables:

- read-only adapters to authorized replay or live-shadow sources;
- signed event envelope, schema registry and source contract monitoring;
- consist completeness and cross-system identity reconciliation;
- incident evidence bundles and independent verifier;
- comparative data-quality experiment against simple validation.

**Exit gate:** zero critical false-admission on the frozen adversarial corpus; source/outage states never appear as live; operators reconstruct selected incidents materially faster without safety influence.

### Phase 2 — federated operational data plane

**Purpose:** establish regional event/state infrastructure and parity views.

Deliverables:

- OCC/BCC regional cells, station-edge adapters and national governance services;
- topology/timetable/configuration packages and event replay;
- identity, PKI, security monitoring and disaster recovery;
- state comparison with incumbent systems over representative operating periods.

**Exit gate:** agreed parity and data-latency/completeness targets; successful OCC/BCC, partition, restore and replay exercises; unresolved mismatches have owners and safe dispositions.

### Phase 3 — non-vital workflow parity

**Purpose:** replace bounded reporting, investigation, planning or coordination workflows first.

Deliverables:

- controller-grade HMI for selected non-vital tasks;
- timetable/conflict analysis and multi-train repercussion views;
- freight/consist and operational-order workflows within approved scope;
- training, support and audit operations.

**Exit gate:** task success and workload no worse than incumbent; measurable improvement in selected outcome; rollback proven; no new unsafe dependency.

### Phase 4 — supervised traffic decision support

**Purpose:** provide explainable options to controllers while incumbents retain command authority.

Deliverables:

- frozen constraint/priority policy, full-territory conflict engine and uncertainty handling;
- human-factors validation, alarm management and simulator exercises;
- shadow A/B comparisons on real authorized operations;
- independent review of dangerous or infeasible proposals.

**Exit gate:** zero hard-constraint violations in the frozen safety corpus and operational shadow; secondary-delay and operator-burden targets achieved; competent authority approves the next boundary.

### Phase 5 — certified bounded command pilot

**Purpose:** replace one narrowly bounded command/control function in one territory, only after certification.

Deliverables:

- assessed command broker/field gateway and exact application data;
- factory, integration, site, failure-injection and field trials;
- accepted safety/cybersecurity cases and written commissioning authority;
- parallel operation, fenced control transfer, BCC and immediate rollback.

**Exit gate:** all formal approvals and trial outcomes satisfied; no open unacceptable safety/security issue; incumbent fallback remains available for the agreed stabilization period.

### Phase 6 — territory-by-territory adoption and retirement

**Purpose:** scale only what has passed the previous gates.

Deliverables:

- repeated application safety cases/configuration verification for each territory;
- cross-region handover, national observability and fleet-wide support;
- independent benefits/safety monitoring and controlled product evolution;
- formal incumbent decommissioning and data/record preservation.

**Exit gate:** the competent authorities—not the development team—accept replacement for every named capability and territory; retirement produces no lost operational, legal, audit or recovery dependency.

## 19. Replacement gap matrix

Status terms: **prototype** means partial repository functionality; **missing** means no replacement-grade evidence was identified; **external** means access/authority depends on railway partners. This is not a code-line audit and must be refreshed against each release.

| Capability | Replacement requirement | Present repository position | Evidence needed to close gap |
|---|---|---|---|
| System authority/governance | named railway owners, legal authority, safety responsibility, procurement and commissioning route | missing/external | signed programme charter, system boundary, RACI and approval plan |
| FOIS freight parity | booking/commercial, rake/wagon/loco, weight and partner workflows or governed integration | demo/prototype; no authoritative FOIS access | authorized contracts, parity catalogue, migration and reconciliation trials |
| COA workflow parity | controller movement, BPC, orders, regulation, stabling/yarding, diversion and integrations | demo/prototype | controller task analysis, approved requirements and long-duration shadow parity |
| RTIS ingestion | authenticated locomotive position/speed, sequence, coverage, clock and emergency semantics | public/demo providers, not RTIS | authorized RTIS interface, device/central test harness and outage trials |
| CTC/TMS | complete territory resources, conflicts, repercussions, ARS/control, OCC/BCC and field interfaces | route/conflict heuristics only | approved topology/application data, conformance suite, RAMS and field trials |
| Interlocking boundary | certified protocol/gateway, command fencing, fail-safe behaviour and site data | absent | assessed product/interface, lab simulator, ISA, site testing and approval |
| Kavach/ATP boundary | certified train/territory/authority/speed interface and safe timeout | absent; speed is simulation | RDSO-approved design, SIL allocation, ISA, type/application tests and trials |
| Consist/wagon state | complete ordered vehicle data, measured/declared load, BPC/brake, effective versions | prototype consist model | FOIS/yard/weighbridge/BPC contracts; missing-wagon and mutation trials |
| Timetable non-interruption | full constraints, adjacent traffic, priorities, secondary impact and operator explanation | simplified prototype | authorized timetable/resource data; incumbent comparison across disruptions |
| Driver speed | certified authority hierarchy, braking model, human factors and ATP supervision | simulation-only advisory | separate safety lifecycle, rolling-stock/territory data, simulator/field approvals |
| Evidence/provenance | source identity, scope, time, schema, ancestry, corrections, approval binding and reconstruction | strongest prototype area; under repair/evaluation | independent adversarial study, issuer trust boundary and partner pilot |
| Canonical data platform | versioned schemas, source sequences, correction, completeness and state replay | partial | cross-system contracts, conformance suite, sustained authorized replay |
| HA and DR | OCC/BCC, ≥ incumbent availability, redundant communications, tested restores | local/cloud demo only | architecture deployment, fault injection, measured SLOs and restoration records |
| Offline/degraded working | local safe continuity, bounded caches, explicit outage and reconciliation | judge-demo mode only | approved railway degraded procedures and territory exercises |
| Cybersecurity | IT/OT zoning, PKI/HSM, device trust, SBOM, SOC, audit, supply-chain and incident controls | ordinary application controls only | threat model, secure architecture, CERT-In/railway audits and OT exercises |
| Safety assurance | hazard lifecycle, traceability, independent V&V/ISA and accepted safety case | absent | complete lifecycle evidence for exact assessed system/application |
| Human factors/operations | controller/driver workload, alarms, training, 24×7 support and competence | unvalidated UI | approved studies, simulator trials, training records and operational acceptance |
| Scale/performance | measured national/territory workload, peak/burst/replay and latency | development benchmarks only | authorized load model and representative endurance/failover tests |
| Privacy/retention | lawful purpose, minimization, classification, access, retention and subject obligations | draft policies | legal review, data inventory, approved schedules and audits |
| Deployment provenance | reproducible assessed build/config, signed release, exact fleet inventory and rollback | CI/release hashes are an early start | controlled build, HSM release signing, configuration/application baselines |
| Decommissioning | reversible cutover, historical records, contract exit and restoration | missing | territory retirement plans and authority sign-off |

## 20. Acceptance gates and proof standard

### 20.1 Cross-cutting gates

| Gate | Pass condition | Evidence |
|---|---|---|
| Functional parity | every in-scope incumbent use case passes or has an approved disposition | requirements traceability, controller UAT and system-owner sign-off |
| Data authority | every required decision input is from an approved source with scope/time/completeness | contracts, credentials, conformance and outage tests |
| Safety | residual risks accepted and required independent assessment complete | hazard log, V&V, ISA report, safety case and written approval |
| Availability | service and failover targets achieved under representative faults and duration | monitored endurance, failover, communications-cut and restore reports |
| Command integrity | no unauthorized, duplicate, stale, ambiguous or wrong-territory actuation | protocol/fuzz/failure tests and field reconciliation evidence |
| Conflict quality | no hard-constraint violations; approved objective improves or equals incumbent | frozen scenario corpus and shadow operational comparison |
| Consist completeness | every required vehicle is bound to the active consist; no guessed critical values | source reconciliation, mutation and missing-wagon tests |
| Cybersecurity | no open unacceptable finding; incident/recovery path exercised | independent audit, penetration/red-team and restore evidence |
| Human factors | acceptable workload, alarm burden, error recovery and training outcomes | simulator/UAT studies with prior approval where required |
| Migration | parallel operation and immediate rollback work with no record loss | rehearsal logs, reconciled state and responsible authority sign-off |
| Benefit | selected safety/operational/economic outcome exceeds frozen threshold | independent analysis on representative authorized data |

### 20.2 Claim rules

- Say **“target architecture for replacement”** until a competent authority adopts the programme.
- Say **“research prototype”** for the current repository.
- Say **“shadow validated”** only after real authorized shadow data and a frozen comparator.
- Say **“field trial”** only for an approved, documented field trial.
- Say **“certified/approved”** only with the exact product, version, application, authority and certificate/approval reference.
- Never convert a planned target, passing unit test, simulated fault, public-data demo or checksum into an operational safety claim.

## 21. Immediate engineering backlog for ClearPath Nexus

These actions move the prototype toward the target without pretending to complete the replacement:

1. Make EvidenceGate source-, scope-, time-, schema-, lineage- and correction-aware; test independent adversarial cases.
2. Introduce the common event envelope and immutable configuration/source registries for non-vital research data.
3. Enforce complete versioned wagon-by-wagon consists; never synthesize missing critical load.
4. Replace hardcoded corridor weights, speeds, headways and priorities with signed/versioned research configuration.
5. Separate observation, recommendation and command types at schema, service and UI levels; keep command APIs absent.
6. Replace repeated scripted trials with varied, held-out comparative experiments and independent expected labels.
7. Build an official-source connector framework that refuses use without a declared licence, authority, credential and purpose.
8. Implement deterministic offline replay with exact capture hashes and conspicuous `REPLAY/SYNTHETIC` status.
9. Create interface simulators for FOIS/COA/RTIS/CTC/interlocking/Kavach contracts; use no real names or live claims until authorized specifications are obtained.
10. Maintain requirement-to-test traceability and generate a gap report on every release.

The first partner request should be for a **read-only, non-vital shadow pilot** and schema/authority discovery—not access to movement commands.

## 22. Assumptions, trade-offs and revisit points

### Assumptions requiring confirmation

- The initial programme boundary is operations/freight/control integration, not every Indian Railways business system.
- Existing interlockings and Kavach remain in service through early migration.
- Regions can retain safe local operation during national service loss.
- System owners will provide controlled schemas, replay data and test environments before production integration.
- The competent authorities will determine exact standards, SIL allocation, assessment and procurement routes.

### Principal trade-offs

| Decision | Benefit | Cost/risk |
|---|---|---|
| Federated regional authority | limits blast radius and WAN dependency | harder cross-region coordination and identity reconciliation |
| Event history plus derived state | audit/replay and correction transparency | greater storage, schema and operational complexity |
| Strict source admissibility | blocks unsupported decisions | more HOLD states and demand for source-owner discipline |
| Separate vital/non-vital planes | protects safety boundary and enables innovation | duplicated interfaces, testing and operational teams |
| Signed immutable configuration | reproducibility and controlled activation | slower change; key and revocation complexity |
| Incremental coexistence | safer migration and measurable parity | longer programme and temporary bridge cost |
| Open contracts | interoperability and vendor competition | requires strong governance to prevent incompatible interpretations |

### Revisit when evidence exists

- exact national/zonal/divisional partitioning after workload, telecom and authority discovery;
- storage/streaming technologies after measured capacity and approved hosting constraints;
- availability/RPO/RTO targets after RAMS and business-impact analysis;
- whether any decision-support function is safety-related after hazard analysis;
- inclusion of crew, traction, maintenance, passenger and commercial systems after boundary approval;
- driver advisory or automatic route-setting scope only after human-factors and safety evidence;
- cryptographic algorithms, retention and data residency as current government/railway policy requires;
- whether replacing, modernizing or wrapping each incumbent component produces the safest and best-value outcome.

## 23. Source register

Public sources establish incumbent roles and indicate the assurance/procurement bar. They do not grant data access or operational authority.

1. Centre for Railway Information Systems, [Freight Operations Information System (FOIS)](https://cris.org.in/loadpage?page=proFOIS).
2. Centre for Railway Information Systems, [Control Office Application (COA)](https://cris.org.in/loadpage?page=proCOA).
3. Centre for Railway Information Systems, [Real Time Train Information System (RTIS)](https://cris.org.in/loadpage?page=proRTIS).
4. Centre for Railway Information Systems, [project catalogue](https://cris.org.in/loadpage?page=ProjectListPage), including ICMS, CMS, SATSaNG, FOIS, COA and RTIS context.
5. RDSO, [Functional Requirement Specification of CTC, version 2.0, effective 3 March 2025](https://rdso.indianrailways.gov.in/uploads/files/CTC%20revised%20FRS%20effected%20from%203rd%20Mar%202025.pdf).
6. RDSO, [System Requirement Specification of Kavach v4.0, amendment 3](https://rdso.indianrailways.gov.in/uploads/System%20requiremnt%20specification%20amd%203%20ver%204_0.pdf).
7. RDSO, [Kavach Cloud and Cyber Security Requirements, Annexure R](https://rdso.indianrailways.gov.in/uploads/2025-04-29-Annexure%20R.pdf).
8. RDSO, [Work Instruction for vendor approval in the Signal Directorate, version 2.2](https://rdso.indianrailways.gov.in/uploads/Work%20instruction%20for%20vendor%20approval%20in%20Signal%20Directorate%2008_06_2023.pdf).
9. RDSO, [Specification for Fail-Safe Network Multiplexer, RDSO/SPN/211/2022](https://rdso.indianrailways.gov.in/uploads/Specification%20for%20Failsafe%20Network%20Multiplexer%20FNmux%2024%20Nov%202022.pdf), an example of SIL-4 vital-information exchange requirements.
10. CERT-In, [Guidelines on Information Security Practices for Government Entities](https://www.cert-in.org.in/guidelinesgovtentities.jsp).
11. CERT-In, [API Security: Threats, Best Practices, Challenges and Way Forward](https://www.cert-in.org.in/PDF/CIWP-2023-0001.pdf).
12. CERT-In, [Directions under section 70B of the Information Technology Act](https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf).
13. Ministry of Electronics and Information Technology, [Digital Personal Data Protection Act 2023](https://www.meity.gov.in/writereaddata/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf) and [Digital Personal Data Protection Rules 2025](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit).
14. Press Information Bureau, [Logistics Data Bank tracks 10 crore EXIM containers](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2299348&lang=2&reg=48), 14 August 2026.
15. W3C, [PROV Overview](https://www.w3.org/TR/prov-overview/), provenance-model background for portable evidence bundles; W3C PROV is not a railway safety certification.

## 24. Bottom line

The replacement ambition is legitimate only when expressed as a staged, authority-led modernization programme. The codebase can contribute a provenance-aware evidence layer, canonical contracts, consist assurance, replay tools and later non-vital planning research. It cannot leap from prototype to national railway authority.

The nearest defensible milestone is: **prove a read-only evidence and operational-data layer on authorized shadow data, with complete wagon/consist semantics and independently measured improvement.** The long-term end state remains a genuine replacement, but every crossing toward command, speed supervision, signalling or braking must pass the relevant safety, cybersecurity, procurement, human-factors and operational acceptance gates above.
