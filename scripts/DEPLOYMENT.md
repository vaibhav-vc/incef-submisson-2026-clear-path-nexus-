# Production preflight

This is a read-only configuration gate, not evidence of a deployed product or science-fair readiness. It never echoes environment values, tokens, or raw Docker errors.

1. Install Docker with Compose **2.24.4 or newer**. The production overlay uses `!reset []` to remove inherited service ports. An ordinary empty list does not remove ports during Compose merging ([Docker merge reference](https://docs.docker.com/reference/compose-file/merge/)).
2. Copy `.env.example` to an ignored `.env` locally. Supply separate random session and evidence-signing secrets, a strong PostgreSQL password, the real matching frontend/backend Supabase project, and its **public** publishable/anon key. Never put a service-role or secret API key in the frontend.
3. Set `EVIDENCE_VERIFICATION_KEYS={}` for a first deployment; preserve old verification-only secrets under retired IDs when rotating signing keys. Set the exact HTTPS `DOMAIN`, `CORS_ORIGINS`, and `ALLOWED_HOSTS` (including `127.0.0.1` for container healthchecks).
4. Run `python scripts/deployment_preflight.py --env-file .env`. Resolve every reported blocker before deployment. The tool exits nonzero on failure. Compose is resolved with both production and HTTPS profiles; no containers are created by this command.
5. With valid configuration, deploy using `docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml --profile https up -d --build --wait`.
6. Run `python scripts/deployment_preflight.py --env-file .env --url https://YOUR_REAL_DOMAIN`. This additionally requires HTTP 200 and the actual JSON `status=ready`; an HTTP 200 SPA fallback is not accepted.
7. Test real sign-in, live provider timestamps/provenance, evidence export and independent verification, and the rebuilt Android app on a real device. Record results honestly, including unavailable operational feeds.

Production PostgreSQL, Redis, frontend and API do not publish host ports; only Caddy exposes HTTPS/HTTP. Development database/cache ports bind to loopback. API health now depends on `/ready`, including real database/cache access. Workers inherit the same signing/provider/retention settings as the API, and the production overlay disables debug and authentication bypass for all backend processes.

## Verification and rollback

Run `python -m unittest discover -s scripts/tests -v` for synthetic configuration regression tests. The deployment CI job resolves configuration and starts the real production API with disposable PostgreSQL/Redis containers. CI secrets and Supabase host/key fixtures are synthetic; this job tests migrations/startup/readiness, **not** real Supabase authentication or real provider delivery.

Before deployment, back up the database and retain the previously deployed image/version and verification-only signing keys. If readiness fails, authentication regresses, or evidence verification fails, stop rollout and restore the prior application release. Do not automatically downgrade schema or delete production volumes; assess migrations and restore from the verified backup only with operator authorization. Never use the CI cleanup `down --volumes` command on a real deployment.

Remaining external gates: provisioned hosting, TLS/DNS, authorized operational feeds, real authentication/device/end-to-end checks, genuine student identity and original submission materials. A preflight pass alone does not satisfy those gates.
