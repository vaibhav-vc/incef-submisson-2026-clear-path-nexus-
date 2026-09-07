# ClearPath Nexus deployment

This document is the operational runbook for the v6 EvidenceGate tree. The application is
not a signalling, dispatch, collision-avoidance, or safety-critical control
system.

## Local Docker development

```sh
cp .env.example .env
# Set POSTGRES_PASSWORD, SECRET_KEY, EVIDENCE_SIGNING_KEY, SUPABASE_URL,
# and the remaining provider/authentication values in .env.
docker compose up --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

The development template keeps `DEMO_DATA_ENABLED=false`. Seeded engineering
rows remain visibly labelled and force EvidenceGate `HOLD`; use the authorized
engineering importer to make certified values eligible for `READY`. The local web application is at `http://localhost:5173` and the
API is at `http://localhost:8000`.

## Production Docker deployment

Requires Docker Compose **2.24.4+**. The production override uses `!reset` to
remove inherited development ports; an empty list alone does not remove them.

Use managed PostgreSQL/PostGIS and Redis where possible. Put `.env` in the
deployment secret store and set at minimum:

- `ENVIRONMENT=production`
- `DEMO_DATA_ENABLED=false`
- a random `SECRET_KEY` of at least 32 characters
- a separate high-entropy `EVIDENCE_SIGNING_KEY`
- a unique `EVIDENCE_SIGNING_KEY_ID`; retain retired keys in the JSON
  `EVIDENCE_VERIFICATION_KEYS` keyring when rotating
- explicit `ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS` before importing certified limits
- strong database credentials
- exact HTTPS `CORS_ORIGINS`
- `ALLOWED_HOSTS` for the edge/API hostnames and `127.0.0.1` for container readiness probes
- `AUTH_COOKIE_SECURE=true`
- `DOMAIN` for Caddy
- authorized `MARITIME_BERTH_DATA_FEED` / `MARITIME_FEED_API_KEY` and
  `RAILWAY_OPERATIONS_FEED` / `RAILWAY_FEED_API_KEY` pairs

Set matching `SUPABASE_URL` and `VITE_SUPABASE_URL` HTTPS origins and a public
publishable/anonymous `VITE_SUPABASE_ANON_KEY`. Never pass a secret/service-role
key to Vite. The edge content security policy permits only the configured
Supabase origin. Keep `EVIDENCE_VERIFICATION_KEYS={}` until actual key rotation.

First run the read-only, secret-redacting configuration gate from the repository
root. It returns a nonzero status when required configuration is unsafe or cannot
be resolved; it does not create services or prove the providers are available:

```sh
python scripts/deployment_preflight.py --env-file .env
```

Then start the production profile:

```sh
docker compose --profile https -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose --profile https -f docker-compose.yml -f docker-compose.prod.yml ps
curl -f https://$DOMAIN/health
curl -f https://$DOMAIN/ready
python scripts/deployment_preflight.py --env-file .env --url https://$DOMAIN
```

The backend runs Alembic migrations before serving traffic. It does not seed
demo rows when `DEMO_DATA_ENABLED=false`. Configure backups, restore tests,
private database/Redis networking, TLS certificates, centralized logs, and
monitoring for `/ready` and authenticated provider status before launch. Backend
container health and worker startup now depend on `/ready`, not just process
liveness. `/health` and `/ready` are proxied through the frontend and must return
backend JSON, never the web application's HTML fallback.

## Direct backend/frontend verification

```sh
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m compileall app scripts alembic
.venv/bin/ruff check app scripts alembic
.venv/bin/python -m pytest -q

cd ../frontend
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint
pnpm test
pnpm run build
pnpm audit --prod --audit-level=high
```

The canonical frontend lockfile is `frontend/pnpm-lock.yaml`; use pnpm in CI
and release environments.

The release and deployment regression suites need only Python's standard library:

```sh
python -m unittest discover -s submission/tests -v
python -m unittest discover -s scripts/tests -v
```

CI additionally defines a disposable PostgreSQL/PostGIS + Redis production-startup
test with explicitly synthetic credentials. That job is infrastructure validation,
not verification of Supabase login or authorized railway feeds. Review the actual
CI result for the commit being deployed; configuration tests alone are not enough.

## Authentication smoke tests

Web and Android authenticate with Supabase. Both send the Supabase access token
as a bearer token to FastAPI, which verifies its signature, expiry, audience,
and subject before owner-scoped queries execute. Exercise sign-in and an
authenticated `/planner/stations` call against staging; never place a service-role
key in either client.

## Android release

```sh
cd android
./gradlew assembleDebug -PbackendBaseUrl=http://10.0.2.2:8000/api/v1 --no-daemon
./gradlew assembleRelease -PreleaseBackendBaseUrl=https://api.example.com/api/v1 --no-daemon
```

The release command requires `android/key.properties` and an external
keystore. The repository intentionally contains neither. CI may use
`-PallowUnsignedRelease=true` to verify compilation only; never distribute an
unsigned APK.

## Current launch gates

EvidenceGate safely fails closed without authorized providers, but operational
use remains staging-only until railway infrastructure, freight operations, and
maritime data are authorized; reliability weights are calibrated; approval
roles are reviewed; operator acceptance and independent security testing are
complete; and legal documents are published.
