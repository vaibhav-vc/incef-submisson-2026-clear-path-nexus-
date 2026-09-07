# EvidenceGate | ClearPath Nexus 6.0 | INSEF 2026-27

EvidenceGate is a student engineering prototype that checks whether a logistics decision has current, complete and intact supporting evidence before it can be approved. This repository contains the backend, web and Android clients, reproducible experiments, report and downloadable demonstration artifacts.

## Readiness and downloads

**Status: tested research prototype; live deployment and submission details remain incomplete.** The September 1 verification passed 215 backend tests twice, web type-check/lint/build, and Android build/tests. These checks do not establish an operational deployment. The audited host returned `/health` 200 and `/ready` 503 because PostgreSQL and Redis were unavailable. The packaged APK has emulator/placeholder configuration and must be rebuilt for a real phone demonstration. The web build displays `Configuration required` when Supabase settings are missing.

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

## Experimental evidence

The original August 31, 2026 controlled run contains **1,600 trials across eight scenarios**: 200 READY baselines and 1,400 adverse trials with zero false READY results. Each scenario repeats deterministic software checks with different identifiers; these are not independent railway field events. Raw [trial data](submission/experiments/evidencegate_experimental_results.csv) and [method/scripts](submission/experiments/README.md) are included.

Open-Meteo and NOAA SWPC returned **10/10 HTTP 200 and schema-valid responses** in the original observation and a fresh September 1 check. This short observation does not establish continuous availability. Authorized freight, berth and certified engineering feeds were not available for live validation. Seeded data remains labelled and cannot qualify critical clearance as READY.

## Before a live INSEF demonstration

1. Configure PostgreSQL/PostGIS, Redis, Supabase and evidence-signing settings using the [deployment guide](docs/DEPLOYMENT.md); apply migrations and verify `/ready` returns 200.
2. Rebuild the web client with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, and route `/api/v1` to the backend. Never put a service-role key in a client.
3. Rebuild Android with a reachable backend URL and real public Supabase configuration. `10.0.2.2` only reaches the host from an Android emulator. Follow [Android setup](android/README.md); a release build additionally requires HTTPS and your signing configuration.
4. Verify authenticated login, route evaluation, evidence export, approval and dispatch on the actual demonstration device. Missing providers must visibly remain unavailable.
5. Complete the report's participant/grade/school/guide fields, record a working demonstration video, disclose assistance accurately and check the current [official INSEF requirements](https://insef.org/insef/).

No field validation, safety certification, official railway authority integration or guaranteed INSEF acceptance is claimed.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20Postgres%2FPostGIS-009688)](backend)
[![Frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61DAFB)](frontend)
[![Android](https://img.shields.io/badge/android-Kotlin%20%2F%20Compose-3DDC84)](android)

ClearPath Nexus is an explainable freight operations intelligence and decision-support platform combining rail-route feasibility, cargo clearance, environmental risk, congestion, port coordination, scheduling, information provenance, compliance review, and dispatch lifecycle management.

> **Scope.** It is not railway signalling, Kavach/ATP, electronic interlocking, official dispatch control, customs authority, a certified engineering source, or legal authority. Qualified humans retain final operational and legal responsibility.

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

**Core routing & compliance**
- Supabase-issued authentication tokens verified by FastAPI; operational records remain backend-authorized and owner-scoped.
- `/api/v1` FastAPI API with Postgres/PostGIS, SQLAlchemy 2, Redis, Alembic, WebSockets, health/readiness, and metrics.
- Deterministic cargo height, width, and weight clearance. A physical failure produces `HARD_BLOCKED` and overrides the numerical route score.
- **EvidenceGate** exposes one canonical state (`HARD_BLOCKED`, `UNAVAILABLE`, `HOLD`, or `READY`), re-ages live evidence at decision time, verifies signed evidence roots, and refuses dispatch unless the current evidence root has an authenticated human approval receipt.
- Dijkstra rail routing, route evaluation/suggestion/history, dispatch, train schedules, and conflict detection.
- Multi-leg journeys are approved per signed leg and dispatched atomically, so a failed leg cannot leave a partially dispatched journey.
- Deterministic reliability scoring using weather, congestion, historical baseline, and port alignment. Missing port data is excluded and weights are renormalized.

**Data & provenance**
- Open-Meteo/OpenWeather weather adapters, NOAA SWPC supplemental telemetry, optional RailRadar/AIS signals, explicit provider-health states, and honest unavailable states.
- **Nexus SourceLine** — immutable decision snapshots, normalized source types, dynamically evaluated freshness, record-envelope checksums, signed lineage roots, source catalog, traceability counts, and hot incident evidence-kit APIs.
- **Nexus ComplianceGuard** — deterministic document completeness, document/permit expiry versus ETA, declaration and approval checks, rule-source versioning, owner-scoped history, and reasoned override audit records.
- **LiveOps** — normalized provider envelopes, durable observations, Redis latest-value cache, circuit breakers, a single background ingestor, operational events/SSE, explicit shipment tracking consent, and an owner-scoped control center.

**Machine learning & prediction**
- Production ML foundation: versioned datasets/training runs/models/predictions, chronological splits, leakage checks, deterministic benchmarking, checksummed artifacts, promotion gates, SourceLine prediction evidence, and deterministic fallback.
- **Predictive Intelligence v5.3** — empirical intervals that fail closed without trusted calibration, exact deterministic factor decomposition, owner-scoped drift monitoring, and manual-only retraining readiness.
- **Multimodal v5.4** — operator/provider-evidence plans across road, rail, port, and sea legs with continuity validation, per-leg ETA/cost/risk/compliance/source state, hard-block precedence, counted traceability, lineage, and immutable input snapshots.
- **Integrated Operations v6** — one owner-scoped overview across routes, schedules, shipments, events, compliance, predictive ETA, multimodal plans, providers, audit export, and an explicitly limited shipment-state projection.

**Integrations & clients**
- Optional authorized ixigo train synchronization with a fail-closed `AUTH_REQUIRED` state, whitelisted passenger-status fields, SourceLine evidence, schedule ownership checks, manual sync API, and a separately enabled worker profile. It is never freight authority or train control.
- Concurrent provider resolution, route-specific client time budgets, normalized low-cardinality metrics paths, paginated/batched compliance history, and lazy-loaded web modules.
- React 19/Vite/Tailwind/Leaflet web operations console, Source Trust Center, evidence drawer, and ComplianceGuard review.
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

Every routing, clearance, compliance, and prediction decision is backed by a SourceLine-tracked evidence trail rather than an opaque score.

## Quick start

Copy `.env.example` to `.env` and provide your own Supabase project settings. Never expose a Supabase service-role key to either client.

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
pnpm run build
pnpm run lint
```

Android requires a locally installed JDK and Android SDK: `gradlew testDebugUnitTest assembleDebug lintDebug`.

Authorized engineering constraints are imported as a checksum-certified operator action:

```powershell
cd backend
python scripts/import_engineering_evidence.py C:\secure\authorized-segments.csv
```

See [EvidenceGate operations](docs/EVIDENCEGATE.md) for the required columns and dispatch lifecycle.

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

Seeded segment engineering constraints, static congestion values, and historical-delay factors remain explicitly labelled `SEEDED_BASELINE` and force `HOLD`; they can never produce `READY`. An authorized, checksum-certified engineering import can replace them without changing application code. OpenStreetMap geometry does not certify bridge/OHE clearances, structure gauge, or axle-load capacity. ComplianceGuard is decision support, not legal advice, and it never invents penalty amounts.

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
- **Nexus ComplianceGuard** — document and permit checks, rule-source versioning, reasoned override audit records
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
| ComplianceGuard rules and audit trail | [COMPLIANCEGUARD.md](docs/COMPLIANCEGUARD.md) |
| Provider attribution and terms | [DATA_SOURCES_AND_ATTRIBUTION.md](docs/DATA_SOURCES_AND_ATTRIBUTION.md) |
| Deployment | [DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Production release checklist | [PRODUCTION_RELEASE_CHECKLIST.md](docs/PRODUCTION_RELEASE_CHECKLIST.md) |

## License

Project code is provided under [MIT](LICENSE). External datasets and providers retain their own terms and attribution requirements.
