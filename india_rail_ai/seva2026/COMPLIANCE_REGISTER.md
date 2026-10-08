# Legal, safety and data compliance register

How Clear Path Nexus / RailGuard is designed against the Indian laws, rules, standards and licences that
apply to railway decision-support software, and what still needs a competent authority. **This is an
engineering register, not legal advice**: before any deployment it must be reviewed by Indian Railways'
legal, safety (RDSO / CRS) and IT (CRIS) functions.

Status key: **Met by design** (built and tested here) · **Ready, needs authority** (built; a body must
approve or grant access) · **Open** (work that remains outside this repository).

## 1. Railway operation and safety

| Instrument | What it requires (relevant part) | How the software complies | Evidence | Status |
|---|---|---|---|---|
| Railways Act, 1989 (operation under the General Rules made by the Central Government, Sec. 60) | Train movement is authorised only by railway staff under the rules; acts endangering passengers are offences (Sec. 152-154) | Advisory only. No interface to signals, points, interlocking, block instruments, Kavach/ATP or brakes; every output carries `authority: ADVISORY_ONLY`; the cab footer says authorised signals and rules remain controlling | `railguard/model.py` AUTHORITY, `cab.py`, `SAFETY_AND_INTEGRATION_BOUNDARIES.md`; feed role cannot approve (`tests/test_attacks.py::test_feed_role_cannot_take_decisions`) | Met by design |
| Indian Railways (Open Lines) General Rules, 1976 and zonal Subsidiary Rules (G&SR) | Station masters / section controllers hold authority to admit trains; written authorities, caution orders and speed restrictions follow G&SR | A plan needs a *named* controller's approval, is recorded in a hash-chained audit, and is superseded by any later state change; caution orders/speed restrictions are only *displayed* from authorised inputs, never generated as authority | `engine.py` approve guard (version check), `tests/test_railguard.py`, simulation invariant APPROVAL_GATE (0 violations) | Met by design |
| RDSO approval (e.g. RDSO/SPN/196 for Kavach) and safety-integrity assessment | Equipment/software in the signalling safety chain needs RDSO approval and independent safety assessment | Kept outside the safety chain on purpose, so it does not claim a SIL. If IR wants it closer to operations, follow EN 50126/50129 + EN 50716 (Basic Integrity or SIL as allocated by hazard analysis) with an ISA | This register; `SAFETY_AND_INTEGRATION_BOUNDARIES.md` | Ready, needs authority |
| CENELEC EN 50126 (RAMS), EN 50129 (safety case), EN 50716:2023 (railway software, supersedes EN 50128/EN 50657) | Lifecycle, hazard log, verification & validation, tool qualification, at least QA for non-safety functions | Practised here: hazard-driven invariants, 5M+-operation randomised V&V, replayable decisions, pinned toolchain (ruff 0.8.6, pinned requirements), traceable audit log. Not yet: formal hazard log signed by IR, ISA, tool qualification dossier | `AUDIT_LOG.md`, `evidence/simulation/`, CI | Open (formal dossier) |
| Commission of Railway Safety (CRS) | Sanction for works/changes affecting public safety | An advisory planning aid does not change operating rules; if IR changes procedures to use it, CRS consultation may be required | - | Needs authority if procedures change |

## 2. Cyber security

| Instrument | Requirement | How the software complies | Status |
|---|---|---|---|
| IT Act, 2000 - Sec. 43, 66 (unauthorised access), Sec. 70 (protected systems / CII, NCIIPC) | No access to protected railway systems without authorisation; protect own systems | The live-feed gateway ingests only *signed* data pushed by an authorised source (HMAC-SHA256, per-source keys, ±120 s window, nonce + sequence replay protection). Nothing scrapes or probes NTES/RTIS/COA. Role-based tokens, fail-closed production mode, strict input schemas, CSP, host allow-list, body caps, rate limits | Met by design; access to CII needs Ministry/CRIS authorisation |
| CERT-In Directions of 28 April 2022 (Sec. 70B(6)) | Report incidents within 6 hours; keep ICT logs for 180 days within India; synchronise clocks with NIC/NPL NTP; name a point of contact | Tamper-evident audit log (hash chain + optional HMAC), persisted to `RAILGUARD_AUDIT_DIR`, never deleted by the software (retention is the operator's ≥180-day policy on Indian infrastructure); all timestamps from the host clock, which must use NIC/NPL NTP; incident runbook in `SECURITY.md` | Ready (operator must host in India, configure NTP and retention, name a PoC) |
| CERT-In / STQC application security audit ("safe to host") before hosting on government infrastructure; GIGW 3.0 | Independent security audit; secure, accessible government web applications | Self-tested: 32 adversarial tests, Bandit 0 findings, pip-audit 0 known vulnerabilities, strict CSP with no inline script. Needs an empanelled auditor's report | Open (external audit) |

## 3. Data protection and data licences

| Instrument | Requirement | How the software complies | Status |
|---|---|---|---|
| Digital Personal Data Protection Act, 2023 and DPDP Rules, 2025 (notified Nov 2025; most duties apply ~18 months later) | Lawful purpose, notice, security safeguards, breach reporting, retention limits | No passenger data is processed. The only personal data is the controller identifier recorded with each decision (employment / legitimate-use purpose, needed for accountability). Recommend using staff IDs rather than names and documenting retention with HR | Met by design; operator policy needed |
| Government Open Data License - India (GODL) / NDSAP | Attribution when using data.gov.in data | `india_rail/official.py` registers publisher and licence for every official source and records them with the file's SHA-256 in `official_provenance` | Met by design |
| DataMeet Indian Railways data (CC0) | None required (attribution given anyway) | Pinned by SHA-256 in `india_rail/sources.py`; documented in README | Met |
| OpenStreetMap (ODbL 1.0): track line count, electrification, gauge, speed limits, station positions | Attribution "(c) OpenStreetMap contributors"; a *publicly distributed* derived database must itself be ODbL | `india_rail/osm_infra.py` derives per-section attributes from an India extract verified by its published MD5 and recorded by SHA-256. The derived tables stay in the git-ignored `data/` directory; only aggregate counts are published, with attribution. If IR distributes the derived database, it does so under ODbL | Met |
| Observed running, September 2024 (Chowdhury, Koley, Chakraborty, Ghosh - IIT Kharagpur; IEEE T-ITS 2026) | No licence file; published "for research and development" with a citation request. The underlying observations come from NTES, whose terms permit personal use and require permission for reproduction or systematic databases | Used **only to verify** the system (research use), fetched by the user from the authors' repository and checked against a pinned SHA-256, kept in git-ignored `data/`, **never redistributed**; only aggregate validation results are published, with citation; the forecast model trained on it is rebuilt locally by each user and is not distributed either. Nothing in this project scrapes NTES or any railway system | Met for research verification; for operational use the authorised NTES/COA feed replaces it (needs Ministry/CRIS permission) |
| Ministry of Railways punctuality statistic (77.12% Mail/Express, 2024-25) | Public statement (Indian Railway Year Book; written reply in Lok Sabha) | Quoted with its source as the reference the observed data is checked against | Met |
| Licence of this code | - | MIT (repository `LICENSE`) | Met |

## 4. Procurement and adoption pathway (not legal requirements, but how IR adopts software)

* Indian Railways Innovation Policy ("Startups for Railways", 2022): problem statements, prototype trials and
  funding for start-ups/innovators - the natural route for a field trial.
* CRIS is IR's IT organisation: live-feed access (NTES/RTIS/COA), hosting and integration go through it.
* A field trial would run *in shadow mode* first (advisory output compared with what controllers actually did),
  which needs no change to operating rules.

## What remains (honestly)

Only Indian Railways and its authorities can: grant live-data access; share the block-section, loop and line-speed
registers that make conflict warnings precise; approve a trial; sign the hazard log and safety case; appoint an
independent safety assessor; commission the CERT-In/STQC audit; and decide hosting.
The software side of each item above is built and evidenced in this repository.
