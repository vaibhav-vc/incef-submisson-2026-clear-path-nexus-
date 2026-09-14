# Data sources and attribution

Provider terms were reviewed 22 August 2026; the runtime source inventory was refreshed 14 September 2026. Provider terms can change; verify them before production or commercial deployment.

## Complete source inventory and runtime behaviour

The application deliberately distinguishes where a value came from. A provider that is
not configured, unavailable, stale, or disabled is recorded as `UNAVAILABLE`; it is not
silently replaced with a plausible-looking number. `SEEDED_BASELINE`, `OPERATOR_INPUT`,
`IMPORTED_DOCUMENT`, `DERIVED`, `SIMULATED`, and `OFFLINE_COMPUTED` are also explicit
source states in SourceLine. Only evidence that satisfies the freshness, integrity,
authority, and approval gates can participate in an operational `READY` decision.

| Source / endpoint | Data used by ClearPath Nexus | Runtime configuration | State and limitations |
| --- | --- | --- | --- |
| OpenStreetMap + Overpass API (`https://www.openstreetmap.org/`, `https://overpass-api.de/api/interpreter`) | Railway station discovery, public rail geometry, and geographic context | `OVERPASS_API_URL`; web map tiles use `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` | `PUBLIC_OPEN_DATA`/`LIVE_PROVIDER` geometry. ODbL attribution is required. Public geometry is not an engineering clearance or operating-authority certificate. Disabled in the offline judge build. |
| Open-Meteo Forecast API (`https://api.open-meteo.com/v1/forecast`) | Current weather, precipitation, wind, visibility, and route environmental risk | `OPEN_METEO_FORECAST_URL`; `ENABLE_LIVE_WEATHER`; `LIVE_DATA_ENABLED` | `LIVE_PROVIDER` with freshness, schema, range, retry, circuit-breaker, and cache checks. The hosted free service has its own rate, licence, and non-commercial terms; no SLA is implied. |
| OpenWeather (optional fallback) (`https://api.openweathermap.org/data/2.5/weather`) | Optional current-weather fallback for the environmental-risk adapter | `OPENWEATHER_API_URL`; server-side `OPENWEATHER_API_KEY`; `ENABLE_LIVE_WEATHER` | `LIVE_PROVIDER` only when a legitimate server-side key is supplied. Keys never belong in Vite/Android public configuration. |
| NOAA Space Weather Prediction Center (`https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json`) | Supplemental planetary Kp telemetry | `NOAA_SPACE_WEATHER_FEED_URL`; `LIVE_DATA_ENABLED` | `LIVE_PROVIDER`, freshness-checked and stored as supplemental environmental telemetry. It is not railway signalling, dispatch, or safety authority. |
| RailRadar (optional) (`https://api.railradar.in/v1`) | Passenger-oriented train/rail signal for a configured corridor | `RAILRADAR_BASE_URL`, `RAILRADAR_API_KEY`, `RAILRADAR_CORRIDOR_STATIONS`, budget/TTL settings, `ENABLE_LIVE_RAIL` | `LIVE_PROVIDER` only with legitimate access. It is supplementary, not official freight-control data. Quota, timeout, cache, and circuit-breaker limits apply. Failure is `UNAVAILABLE`/`AUTH_REQUIRED`. |
| AISstream (optional) (`wss://stream.aisstream.io/v0/stream`) | Vessel-activity observations near a port | `AISSTREAM_URL`, server-side `AISSTREAM_API_KEY` | `LIVE_PROVIDER` activity evidence only. AIS presence is not a verified berth schedule or loading window and can never invent one. |
| Authorized maritime berth feed (optional, no default URL) | Operator-approved berth schedules and port alignment | `MARITIME_BERTH_DATA_FEED`, `MARITIME_FEED_API_KEY` | `AUTHORIZED_FEED` only after the operator supplies a contractual/legitimate endpoint and key. Unconfigured data remains `UNAVAILABLE`. |
| Authorized railway operations feed (optional, no default URL) | Engineering restrictions, maintenance windows, and operational constraints | `RAILWAY_OPERATIONS_FEED`, `RAILWAY_FEED_API_KEY` | Must be supplied by an authorized owner and imported with checksum/signature metadata. No public endpoint is assumed. |
| Authorized ixigo partner endpoint (optional, no default URL) | Supplementary passenger train status | `IXIGO_TRAIN_STATUS_URL`, `IXIGO_API_KEY`, `IXIGO_SYNC_ENABLED` | `AUTH_REQUIRED` unless separately authorized. Consumer pages are not scraped; this signal is never freight authority or train control. |
| Operator input / uploaded documents | Shipment references, loading windows, declarations, permits, approvals, and document metadata | Authenticated API/import workflows | `OPERATOR_INPUT` or `IMPORTED_DOCUMENT`; owner-scoped, checksummed, expiry-checked, and audit logged. Human/legal responsibility remains with the operator. |
| Engineering import | Bridge/OHE/structure-gauge/axle-load limits and approved segment restrictions | `scripts/import_engineering_evidence.py`; allow-listed issuer identities and checksum-certified files | `AUTHORIZED_FEED`/`IMPORTED_DOCUMENT` only after validation. Seeded limits cannot produce `READY`. |
| Seeded baseline data shipped with the repository | Demo stations, static congestion, historical-delay factors, and other deterministic baseline values | Repository fixtures and migrations | `SEEDED_BASELINE`. This is reproducible demonstration data, not live railway authority data; it forces `HOLD` where authority is required. |
| Controlled experiment generator | Synthetic adverse/nominal scenarios used to measure fail-closed behaviour | `submission/experiments/run_evidencegate_experiment.py` | `SIMULATED`; useful for software validation only. It is not field-trial evidence and must not be presented as independent railway events. |

### Storage and processing services are not authoritative sources

Supabase PostgreSQL/PostGIS stores owner-scoped operational records, SourceLine envelopes,
lineage, approvals, and audit exports. Redis stores bounded latest-value caches, rate-limit
state, and circuit-breaker state. Neither service creates physical railway facts. The backend
normalizes every provider response into a versioned envelope, records provider attribution,
timestamps, raw source state, validation errors, and a checksum, then applies freshness and
authority rules before a decision is eligible for approval.

The online deployment may use managed Supabase Postgres and managed Redis. The offline judge
edition uses local PostGIS and Redis containers, disables all external provider calls, and
labels its output `OFFLINE_COMPUTED`/`SEEDED_BASELINE`. It is intentionally a reproducible
demonstration, not a claim that external conditions are live.

## OpenStreetMap

- Use: rail geometry, stations, and geographic context.
- License: Open Database License (ODbL).
- Attribution: `© OpenStreetMap contributors` with a link to <https://www.openstreetmap.org/copyright>.
- Limitation: geometry does not certify railway clearance, axle load, structure gauge, or operating authority.

## Open-Meteo

- Use: optional weather adapter.
- API data license: CC BY 4.0; see <https://open-meteo.com/en/license>.
- Terms: <https://open-meteo.com/en/terms>. The hosted free API has usage and non-commercial conditions and does not guarantee uninterrupted provision; review current terms for the intended deployment.
- Limitation: weather information is not railway operating authority.

## NOAA Space Weather Prediction Center

- Use: supplemental planetary Kp telemetry from <https://services.swpc.noaa.gov/products/>.
- Limitation: SourceLine records the feed as supplemental telemetry. ClearPath does not treat it as signalling or dispatch authority.

## RailRadar

- Use: optional third-party passenger-oriented rail signal when legitimate credentials and terms allow.
- Authority: supplementary and non-official for freight operations.
- Limitation: unconfigured or failed access is `UNAVAILABLE`, never fabricated.

## AISstream

- Use: optional AIS vessel-activity signal with legitimate configured access.
- Limitation: AIS activity is not a verified berth schedule and must never generate a fictional loading window.

## Operator input and seeded baselines

- Loading windows, shipment references, and document metadata are labelled `OPERATOR_INPUT`/operator-declared.
- Engineering limits, static congestion, and historical delay are labelled `SEEDED_BASELINE` where applicable.
