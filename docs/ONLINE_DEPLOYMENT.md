# Online Deployment: Vercel + Supabase + Managed API

The authenticated online edition is a split deployment. Vercel serves the static React frontend;
Supabase provides authentication and PostgreSQL/PostGIS; a container host runs the persistent
FastAPI service and workers; and a managed Redis service supplies rate limiting and live-data
caches.

Do not deploy the offline judge Compose file publicly. Do not place a Supabase secret/service-role
key in any `VITE_*` variable. The browser needs only the project URL and a public publishable key
(or a legacy `anon` key).

## 1. Prepare Supabase

1. Create the project and enable SSL enforcement.
2. Choose a database endpoint suited to the API host:
   - use the direct connection for a persistent IPv6-capable host;
   - use the session pooler for a persistent IPv4-only host.
   Do not use Supabase's transaction-pooler endpoint with this SQLAlchemy asyncpg backend: the
   dialect prepares every statement. The application rejects that endpoint during startup rather
   than failing unpredictably during migrations or requests.
3. Percent-encode special characters in the database password before placing it in a URL.
4. Run the API container once; `backend/scripts/start.sh` applies every Alembic migration before
   accepting traffic. Migration `20260913_15` enables RLS and revokes direct Data API access from
   `anon` and `authenticated` for backend-owned tables. Do not add permissive table policies just
   to make the browser query these tables; all application data access belongs behind FastAPI.

Authoritative reference: [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
and [SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement).

## 2. Deploy the API and Redis

Build `backend/Dockerfile` on a container platform that supports a persistent web process. The
current application also has workers and an AIS WebSocket collector, so a static host or GitHub
Pages is not an API host. The web process starts with `backend/scripts/start.sh`; worker commands
are listed in `docker-compose.yml`.

Set these secret-store variables on the API service:

```dotenv
ENVIRONMENT=production
DEBUG=false
AUTH_DISABLED=false
DEMO_DATA_ENABLED=false
SECRET_KEY=<random value of at least 32 characters>
EVIDENCE_SIGNING_KEY=<different random value of at least 32 characters>
EVIDENCE_SIGNING_KEY_ID=evidence-hmac-v1
EVIDENCE_VERIFICATION_KEYS={}

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_AUDIENCE=authenticated

DATABASE_URL=postgresql://<user>:<encoded-password>@<database-host>:<port>/postgres?sslmode=require
DATABASE_POOL_MODE=queue
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_PREPARED_STATEMENT_CACHE_SIZE=100

REDIS_URL=rediss://<user>:<password>@<redis-host>:<port>/<database-number>
CORS_ORIGINS=["https://app.example.org"]
ALLOWED_HOSTS=["api.example.org","127.0.0.1"]
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
APPROVAL_ALLOWED_ROLES=["operator","approver","admin"]
ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS=[]
```

Provider URLs and keys are optional at startup. Unconfigured or disabled providers return an
explicit `UNAVAILABLE` state and cannot silently become evidence eligible. Configure only feeds
you are authorized to use. Open-source application code does not grant a license to third-party
rail, port, weather, or AIS data.

The deployment is healthy only when both probes pass:

```sh
curl -f https://api.example.org/health
curl -f https://api.example.org/ready
```

`/health` proves the process is alive. `/ready` additionally checks PostgreSQL and Redis. Monitor
`/ready`, `/status/providers`, and `/metrics`; configure database backups and rehearse a restore.

## 3. Deploy the frontend on Vercel

Import the repository and set Vercel's root directory to `frontend`. The committed
`frontend/vercel.json` installs with the pnpm lockfile and uses the explicit online build.

Set these Vercel project variables for Production and Preview as appropriate:

```dotenv
VITE_APP_MODE=online
VITE_API_BASE_URL=https://api.example.org/api/v1
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<public publishable key or legacy anon key>
VITE_REGISTRATION_ENABLED=false
```

Use an absolute HTTPS API URL on Vercel. A value such as `/api/v1` is intended for the bundled
Docker reverse proxy and would otherwise be handled by the SPA fallback on a frontend-only Vercel
deployment.

Add the final Vercel and custom-domain origins to the API's exact `CORS_ORIGINS`. Add the API
hostname to `ALLOWED_HOSTS`. Never use wildcard CORS with credentialed requests.

## 4. Release gate

Before announcing the deployment, verify all of the following:

- the GitHub Actions run for the deployed commit is green;
- Supabase login succeeds and an authenticated `/planner/stations` request succeeds;
- a seeded record is visibly labelled and cannot produce `READY`;
- a missing provider produces `UNAVAILABLE` or `HOLD`, never fabricated live data;
- `/ready` fails when PostgreSQL or Redis is deliberately unavailable;
- the evidence kit verifies after an ordinary API restart;
- the custom domain uses HTTPS and no secret appears in browser assets or logs;
- one laptop and one mobile browser complete the planned judge walkthrough.

Passing this gate supports the claim **production-grade pilot**. It does not certify EvidenceGate
as railway signalling, dispatch authority, collision avoidance, or a safety-critical control
system.
