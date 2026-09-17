# EvidenceGate v7 | Railway evidence assurance research | INSEF 2026-27

EvidenceGate is a student engineering prototype that tests whether an externally supplied railway/logistics recommendation has sufficiently authoritative, current, context-matched, complete, consistent, and traceable evidence to be reviewed. It produces a tamper-evident reconstruction bundle; it does not control trains or certify the truth of external records.

> **Research boundary.** This repository is not signalling, electronic interlocking, Kavach/ATP, movement authority, driver speed instruction, operational dispatch, regulatory compliance, or a replacement for FOIS/COA/RTIS/CTC. Its long-term adoption path is modular and partner-led: demonstrate one non-vital assurance workflow, integrate through authorized connectors, measure benefit, and then complete the applicable railway engineering, security, safety, and procurement assurance before replacing any existing workflow.

The current six-phase architecture, real-data/API registry, carriage-level evidence rule, timetable-impact method, hypotheses, and sources are in [the v7 research plan](docs/RESEARCH_PIVOT_V7.md). The full long-term objective, capability parity and migration path are in [the Indian Railway replacement architecture](docs/INDIAN_RAILWAY_REPLACEMENT_ARCHITECTURE.md).

## Readiness and downloads

For a government technical discussion, start with [the evaluation pack and acceptance matrix](docs/GOVERNMENT_TECHNICAL_EVALUATION.md). It maps the full replacement objective to implemented capabilities, required field evidence and the proposed authorized evaluation procedure.

**September 17 source upgrade:** 342 backend regression tests pass. The default Evidence Assurance workspace now supports cases, source attribution and licence details, policy matrices, signed exports and assigned independent reviewers. Mandatory subject/context binding, transitive lineage checks, one final review per snapshot and offline checksum reconstruction are implemented. Carriage manifests require an explicit complete count. See [the three-part release audit](docs/V7_RELEASE_AUDIT.md) for exact coverage, current CI status and remaining integration work.

**Historical packages:** the ZIP/APK/PDF downloads below predate this v7 source upgrade. Build from the current checkout for the upgraded code. They are retained for traceability and are not presented as updated v7 binaries.

**Status: tested research prototype; live deployment and submission details remain incomplete.** The September 1 verification passed 215 backend tests twice, web type-check/lint/build, and Android build/tests. These checks do not establish an operational deployment. The audited host returned `/health` 200 and `/ready` 503 because PostgreSQL and Redis were unavailable. The packaged APK has emulator/placeholder configuration and must be rebuilt for a real phone demonstration. The web build displays `Configuration required` when Supabase settings are missing.

**September 7 hardening update:** the backend now passes 231 tests, including 16 new regressions preventing malformed or excluded evidence from becoming READY. Authentication has bounded waits, session-race protection and crash recovery; deployment configuration and release integrity have new automated checks. See the [dated verification report](docs/VERIFICATION_REPORT.md) for measured results and remaining limits. The Android binary and original experimental observations are unchanged, not newly certified by these tests.

**September 15 v7 hardening in progress:** the previously reported six-phase baseline passed 264 backend tests and 16 frontend tests before this v7 change set.
The repository now has explicit `online` and `offline-judge` build contracts, a one-laptop LAN
judge edition with generated secrets and a no-build offline launch, managed PostgreSQL/Redis URL
support, Supabase Data API table lockdown, and separate online/offline runbooks. Docker execution,
real Supabase login, live hosting, and a new Android build still require the corresponding local or
cloud infrastructure; they are not represented as completed by source-level checks. The six-phase
baseline also added provenance-checked GTFS/India timetable ingestion, carriage-level consist
manifests, network-wide section/headway conflict research checks, and a judge-facing web panel.
The v7 work now adds source/type contracts, strict evidence schemas, import expiry, required-ancestor
checks, snapshot consistency, and broken-lineage rejection. Route, journey, and schedule dispatch
entry points are retired: the research build never mutates train-movement state.

| Download | Contents / requirement |
| --- | --- |
| [Complete shareable ZIP](output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip) | Source, debug APK, web assets, report, experiment files and checksums |
| [Project report PDF](output/pdf/EvidenceGate_INSEF_2026_27_Final_Report.pdf) | Scientific method, measured results, limitations and submission checklist |
| [Debug APK](release/EvidenceGate-v6.0.0-debug.apk) | Android 8+; debug-signed, requires configured backend and Supabase rebuild |
| [Source ZIP](release/EvidenceGate-v6.0.0-source.zip) | Source and experiment scripts; dependencies installed separately |
| [Web build ZIP](release/EvidenceGate-v6.0.0-web.zip) | Serve through HTTP; supply build-time Supabase settings for authentication |
| [Experimental package](submission/EvidenceGate_INSEF_2026_27_Experimental_Package.zip) | Original CSV/JSON, rerun scripts and report |
| [Verification report](docs/VERIFICATION_REPORT.md) | Checks performed, dates, failures found and remaining blockers |
| [Bundle checksum](output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip.sha256) | SHA-256 of the complete ZIP; internal manifest verifies its contents |

GitHub may show a download button instead of previewing ZIP/APK files. Download the complete ZIP and read `START_HERE.txt`. It is a distributable project package, not a hosted application.

Verify a downloaded bundle without extracting its payloads (Python 3.11+):

```sh
python submission/verify_release.py output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip --checksum output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip.sha256
```

Obtain the outer checksum from a trusted copy of this repository. Hashes detect corruption; they do not prove authorship, live operation or research validity.

## Experimental evidence

The [September 16 official SNCF snapshot and paired benchmark](submission/experiments/README.md) preserve real publisher bytes with licences, URLs, retrieval times and hashes. The benchmark contains 2,400 unique controlled software fixtures (481 clean, 1,919 mutated); the full legacy EvidenceGate V2 recorded zero false admissions or false holds in that run. These are controlled fault tests, not measured Indian Railway incidents or validation of the separate generic v7 policy.

The original August 31, 2026 controlled run contains 1,600 executions across only eight deterministic scenario templates. It is retained as historical regression evidence, but it is **not** 1,600 independent railway cases and is no longer the headline experiment. The September 14 audit found signed unsupported constructions that the old gate admitted; those cases are now permanent v2 regressions. The replacement experiment uses immutable real public feed snapshots plus separately labelled controlled faults and comparator gates.

Open-Meteo and NOAA SWPC returned **10/10 HTTP 200 and schema-valid responses** in the original observation and a fresh September 1 check. This short observation does not establish continuous availability. Authorized freight, berth and certified engineering feeds were not available for live validation. Seeded data remains labelled and cannot qualify critical clearance as READY.

**September 7 repeat:** the controlled experiment again passed 1,600/1,600 cases. NOAA passed 5/5 live requests, but Open-Meteo timed out on all five requests from this host. Both successful and failed observations are preserved under [dated runs](submission/experiments/runs/); the original report data was not overwritten. These results do not support an "everything is live" claim.

## Before a live INSEF demonstration

1. Configure PostgreSQL/PostGIS, Redis, Supabase and evidence-signing settings using the [deployment guide](docs/DEPLOYMENT.md); apply migrations and verify `/ready` returns 200.
2. Rebuild the web client with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, and route `/api/v1` to the backend. Never put a service-role key in a client.
3. Rebuild Android with a reachable backend URL and real public Supabase configuration. `10.0.2.2` only reaches the host from an Android emulator. Follow [Android setup](android/README.md); a release build additionally requires HTTPS and your signing configuration.
4. Verify authenticated login, case capture, evidence assessment, review attestation, export and offline reconstruction on the actual demonstration device. Missing providers must visibly remain unavailable.
5. Complete the report's participant/grade/school/guide fields, record a working demonstration video, disclose assistance accurately and check the current [official INSEF requirements](https://insef.org/insef/).

No field validation, safety certification, official railway authority integration or guaranteed INSEF acceptance is claimed.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20Postgres%2FPostGIS-009688)](backend)
[![Frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61DAFB)](frontend)
[![Android](https://img.shields.io/badge/android-Kotlin%20%2F%20Compose-3DDC84)](android)

The scientific contribution under test is a provenance-aware evidence-admissibility contract that can operate beside existing authoritative systems. The broad v6 operations modules remain only as legacy case generators and comparison adapters.

## Table of contents

- [What is implemented](#what-is-implemented)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Verification](#verification)
- [Data honesty](#data-honesty)
- [From the original concept to v6.0](#from-the-original-concept-to-v60)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [License](#license)

## What is implemented

**Core evidence assurance**
- Generic `/api/v1/assurance` cases support separate creators and assigned reviewers. Reviewers can read assigned cases; only creators capture and assess. Review requires an authorized non-operator role, the latest intact assessment and one final receipt per snapshot.
- Signed exports include canonical evidence, source metadata, lineage and review manifests. `python submission/verify_assurance_bundle.py <bundle.json>` reconstructs checksums offline; HMAC authentication still needs the trusted server.
- Supabase-issued authentication tokens verified by FastAPI; operational records remain backend-authorized and owner-scoped.
- `/api/v1` FastAPI API with Postgres/PostGIS, SQLAlchemy 2, Redis, Alembic, WebSockets, health/readiness, and metrics.
- **EvidenceGate v2** exposes one canonical legacy state (`HARD_BLOCKED`, `UNAVAILABLE`, `HOLD`, or `READY`) while the v7 presentation maps a successful assessment to `REVIEWABLE` rather than movement authority.
- It validates record/snapshot ownership and context, source identity/type, entity-specific schemas, timestamp validity and expiry, non-excluded transitive lineage, role uniqueness, signed record envelopes, and the signed evidence root.
- A signed bundle that contains semantically unsupported evidence remains `HOLD`; application signing is explicitly separate from external issuer authenticity.
- Route, journey, and schedule dispatch endpoints return HTTP 410 in the research build. Authorized railway control systems retain movement authority.
- Legacy Dijkstra routing, RRI scoring, schedule/conflict simulation, weather, and port adapters may generate test cases, but they are not the research novelty or operational outputs.

**Data & provenance**
- Open-Meteo/OpenWeather weather adapters, NOAA SWPC supplemental telemetry, optional RailRadar/AIS signals, explicit provider-health states, and honest unavailable states.
- **Nexus SourceLine** — immutable decision snapshots, normalized source types, dynamically evaluated freshness, record-envelope checksums, signed lineage roots, source catalog, traceability counts, and hot incident evidence-kit APIs.
- **Document Evidence Checklist** — deterministic reference completeness and expiry findings. It is not a legal or regulatory compliance engine.
- **LiveOps** — normalized provider envelopes, durable observations, Redis latest-value cache, circuit breakers, a single background ingestor, operational events/SSE, explicit shipment tracking consent, and an owner-scoped control center.

**Machine learning & prediction**
- Production ML foundation: versioned datasets/training runs/models/predictions, chronological splits, leakage checks, deterministic benchmarking, checksummed artifacts, promotion gates, SourceLine prediction evidence, and deterministic fallback.
- **Predictive Intelligence v5.3** — empirical intervals that fail closed without trusted calibration, exact deterministic factor decomposition, owner-scoped drift monitoring, and manual-only retraining readiness.
- **Multimodal v5.4** — operator/provider-evidence plans across road, rail, port, and sea legs with continuity validation, per-leg ETA/cost/risk/compliance/source state, hard-block precedence, counted traceability, lineage, and immutable input snapshots.
- **Integrated Operations v6** — one owner-scoped overview across routes, schedules, shipments, events, compliance, predictive ETA, multimodal plans, providers, audit export, and an explicitly limited shipment-state projection.

**Integrations & clients**
- Optional authorized ixigo train synchronization with a fail-closed `AUTH_REQUIRED` state, whitelisted passenger-status fields, SourceLine evidence, schedule ownership checks, manual sync API, and a separately enabled worker profile. It is never freight authority or train control.
- Concurrent provider resolution, route-specific client time budgets, normalized low-cardinality metrics paths, paginated/batched compliance history, and lazy-loaded web modules.
- React 19/Vite/Tailwind/Leaflet evidence-assurance workspace, Source Trust Center, evidence matrix/reconstruction views, and document checklist.
- Kotlin/Compose Android client using Supabase auth and FastAPI operational APIs. Operational route decisions are live-backend-only; failures surface as unavailable rather than bundled substitutes.

## Architecture

```
┌──────────────┐     ┌──────────────┐
│ React Web    │     │ Android      │
│ Console      │     │ (Kotlin/     │
│ (Vite/       │     │  Compose)    │
│  Tailwind)   │     │              │
└──────┬───────┘     └──────┬───────┘
       │      Supabase auth │
       └─────────┬──────────┘
                  ▼
          ┌───────────────┐
          │ FastAPI        │  /api/v1
          │ (SQLAlchemy 2) │  health · readiness · metrics
          └───────┬────────┘
                  │
   ┌──────────────┼───────────────────────┐
   ▼              ▼                       ▼
Postgres/     Redis (cache,        Background workers
PostGIS       circuit breakers)    (live ingestor, ixigo sync)
   │                                       │
   ▼                                       ▼
Alembic migrations              External providers (weather,
                                 NOAA SWPC, RailRadar/AIS, ixigo)
```

Every displayed assessment must expose its SourceLine records and limitations. A checksum proves byte integrity after capture, not that an external issuer's statement is true.

## Quick start

### Offline judge edition

For a venue-safe demonstration on one laptop and judge devices connected to the same local
network, install Docker Desktop and run:

```powershell
.\scripts\start_judge_demo.ps1
```

This separate build disables authentication only in guarded development mode, labels all seeded
data, makes no live-provider calls, and exposes the web console on port `8080`. See the
[offline judge guide](docs/JUDGE_DEMO.md). It must never be deployed publicly.
Run the ordinary launcher once with internet to build/cache the containers; use
`.\scripts\start_judge_demo.ps1 -Offline` for the disconnected judging-day rehearsal and event.

### Authenticated online edition

Copy `.env.example` to `.env` and provide your own Supabase project settings. Never expose a Supabase service-role key to either client.
For the split Vercel + Supabase + managed API deployment, follow the
[online deployment runbook](docs/ONLINE_DEPLOYMENT.md).

```powershell
docker compose up --build
```

Apply database migrations before starting a newly upgraded environment:

```powershell
cd backend
alembic upgrade head
```

Android reads `backendBaseUrl`, `supabaseUrl`, and `supabaseAnonKey` Gradle properties. Repository defaults are non-secret placeholders; configure values locally in `~/.gradle/gradle.properties` or secured CI.

## Verification

```powershell
cd backend
python -m pytest -q
ruff check .

cd ..\frontend
pnpm install
pnpm run build:online
pnpm run build:judge
pnpm run lint
```

Android requires a locally installed JDK and Android SDK: `gradlew testDebugUnitTest assembleDebug lintDebug`.

Legacy engineering CSV values can be imported as internally checksummed evidence:

```powershell
cd backend
python scripts/import_engineering_evidence.py C:\secure\authorized-segments.csv
```

This import does not prove external issuer authenticity and therefore cannot independently authorize a reviewable v7 case. See [EvidenceGate operations](docs/EVIDENCEGATE.md).

The live ingestor runs separately from API requests:

```powershell
cd backend
python -m app.workers.live_ingestor
```

The ixigo adapter has no default consumer endpoint. Only users with separately authorized partner access should configure `IXIGO_TRAIN_STATUS_URL`, `IXIGO_API_KEY`, and `IXIGO_SYNC_ENABLED=true`, then start its isolated profile:

```powershell
docker compose --profile ixigo up --build train-synchronizer
```

Without those credentials, train sync truthfully returns `AUTH_REQUIRED`; route planning and scheduling continue normally.

Build and evaluate the first delay-model candidate only after the schema is migrated:

```powershell
python scripts/build_ml_dataset.py --include-simulated --register
python scripts/train_delay_model.py --register
python scripts/evaluate_delay_model.py
```

`--include-simulated` is strictly a pipeline-validation path. The generated rows are labelled `SIMULATED`, remain ineligible for production evaluation, and cannot pass the promotion gate.

## Data honesty

Source states distinguish `LIVE_PROVIDER`, `PUBLIC_OPEN_DATA`, `CACHED_PROVIDER`, `OPERATOR_INPUT`, `SEEDED_BASELINE`, `DERIVED`, `SIMULATED`, `OFFLINE_COMPUTED`, `IMPORTED_DOCUMENT`, and `UNAVAILABLE`. Provider-specific raw states remain stored separately.

Seeded segment engineering constraints, static congestion values, and historical-delay factors remain explicitly labelled `SEEDED_BASELINE` and force `HOLD`. Operator declarations and self-generated document hashes are not external authenticity. A reviewable engineering role requires a verifiable issuer signature or authenticated connector, scoped validity, and complete lineage. OpenStreetMap geometry does not certify bridge/OHE clearances, structure gauge, axle load, signal state, or movement authority.

## From the original concept to v6.0

The project began as "AI-Powered Railway Intelligence Command Center", an MVP concept covering route planning, environmental risk, port synchronization, and reliability scoring. Much of that survived intact. Some of it changed once the system had to defend its own numbers, and a good deal was added that the original scope never described.

### Carried over unchanged

The Route Reliability Index still weights exactly as originally specified — weather `0.40`, port alignment `0.30`, congestion `0.15`, historical delay `0.15` — and those values live in `backend/app/core/config.py` today. A failed physical clearance check still overrides the numerical score outright rather than degrading it. Cargo clearance validation, weather and dust-storm intelligence, space-weather telemetry, port synchronization, the interactive Leaflet map, the threat simulator, and the React/FastAPI/Postgres/MIT foundation all shipped as described.

### Changed in practice

| Original concept | v6.0 as built |
| --- | --- |
| Route marked `BLOCKED` | `HARD_BLOCKED`, which overrides the numerical score rather than sitting alongside it |
| PostgreSQL | Postgres + **PostGIS** for geospatial work, plus **Redis** for provider caching and circuit breakers |
| `npm install` / `npm run dev` at the repository root | **pnpm** inside `frontend/`, or `docker compose up --build` for the whole stack |
| `database/` directory for schema and migrations | Alembic migrations under `backend/alembic` |
| React | React 19 |
| Phase 3: "AI Delay Prediction" | The ML pipeline exists — versioned datasets, training runs, benchmarking, promotion gates — but **every registered model is still a `CANDIDATE`**. Deterministic prediction remains in control, because the promotion gates require real operational rows and the current dataset is entirely simulated. |

### Added beyond the original scope

Nothing in the original concept described where a number came from. Most of what v6 adds exists to answer that:

- **Nexus SourceLine** — immutable decision snapshots, lineage edges, checksums, and traceability counts
- **Document Evidence Checklist** — legacy document/reference checks, rule-source versioning, and reasoned review records
- **LiveOps** — durable observations, provider circuit breakers, operational events, an owner-scoped control center
- **Multimodal v5.4** — road, rail, port, and sea legs with continuity validation and per-leg evidence
- **Integrated Operations v6** — one owner-scoped view across every subsystem
- **Supabase authentication** with backend-authorized, owner-scoped records
- **A Kotlin/Compose Android client** whose operational route decisions come only from the authenticated FastAPI backend
- **The source-state vocabulary** described under [Data honesty](#data-honesty), so an unavailable provider reports itself instead of being quietly filled in
- **Optional ixigo train synchronization**, fail-closed at `AUTH_REQUIRED` and never treated as freight authority

### Still out of scope

Unchanged from the original decision: track maintenance forecasting, rail wear prediction, locomotive health monitoring, passenger booking, crew scheduling, and ticketing integrations. The focus remains freight decision support.

## Project layout

| Path | Description |
| --- | --- |
| `backend/` | FastAPI, SQLAlchemy/PostGIS, Alembic, deterministic services, and pytest suite. |
| `frontend/` | React 19 operations console. |
| `android/` | Kotlin/Jetpack Compose client. |
| `docs/` | Product truth, evidence model, compliance scope, and source attribution. |

## Documentation

| Topic | Doc |
| --- | --- |
| Product scope and truthfulness constraints | [PRODUCT_TRUTH.md](docs/PRODUCT_TRUTH.md) |
| Live data ingestion, circuit breakers, control center | [LIVEOPS.md](docs/LIVEOPS.md) |
| ML datasets, training, promotion gates | [ML.md](docs/ML.md) |
| Multimodal v6 planning | [MULTIMODAL_V6.md](docs/MULTIMODAL_V6.md) |
| ixigo train synchronization | [IXIGO_TRAIN_SYNC.md](docs/IXIGO_TRAIN_SYNC.md) |
| SourceLine evidence and lineage model | [SOURCELINE.md](docs/SOURCELINE.md) |
| EvidenceGate states, certified import, approval, and incident kits | [EVIDENCEGATE.md](docs/EVIDENCEGATE.md) |
| Document checklist and legacy audit trail | [COMPLIANCEGUARD.md](docs/COMPLIANCEGUARD.md) |
| Provider attribution and terms | [DATA_SOURCES_AND_ATTRIBUTION.md](docs/DATA_SOURCES_AND_ATTRIBUTION.md) |
| Deployment | [DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Production release checklist | [PRODUCTION_RELEASE_CHECKLIST.md](docs/PRODUCTION_RELEASE_CHECKLIST.md) |

## License

Project code is provided under [MIT](LICENSE). External datasets and providers retain their own terms and attribution requirements.
