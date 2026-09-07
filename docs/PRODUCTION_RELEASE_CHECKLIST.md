# Production Release Checklist

ClearPath Nexus must remain in staging until every required data, security, and legal item below has a named owner and dated approval.

## Hard launch gates

- [ ] Contract and activate an authorized Indian railway infrastructure/clearance dataset.
- [ ] Contract and activate an authorized live freight feed through `RAILWAY_OPERATIONS_FEED` and `RAILWAY_FEED_API_KEY`; validate its station-code request and score/timestamp response contract.
- [ ] Contract and activate an authorized berth/sailing provider through `MARITIME_BERTH_DATA_FEED`.
- [ ] Receive legal approval for each provider's permitted routing and reliability use.
- [ ] Calibrate Route Reliability Index weights against real historical delay data.
- [ ] Complete operator acceptance testing; do not use Nexus for signalling, dispatch, collision avoidance, or safety-critical control.

## Deployment configuration

- [ ] Use managed PostgreSQL/PostGIS and Redis with private networking, encryption, backups, and a tested restore.
- [ ] Run `alembic upgrade head` before starting the API; production startup performs this automatically.
- [ ] Set `ENVIRONMENT=production`, `DEMO_DATA_ENABLED=false`, independent high-entropy `SECRET_KEY` and `EVIDENCE_SIGNING_KEY` values, and strong database credentials.
- [ ] Restrict `APPROVAL_ALLOWED_ROLES` to reviewed operational roles stored only in Supabase admin-controlled `app_metadata`; do not include generic `authenticated`.
- [ ] Configure `ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS` and prove unknown issuers and future-dated certificates are rejected before importing engineering limits.
- [ ] Record the active evidence key ID and retain retired ID-to-key mappings in `EVIDENCE_VERIFICATION_KEYS`; prove an old snapshot verifies after rotation and an unknown key fails closed.
- [ ] Set exact `CORS_ORIGINS`, `DOMAIN`, `AUTH_COOKIE_SECURE=true`, and an HTTPS Android `releaseBackendBaseUrl`.
- [ ] Keep `REGISTRATION_ENABLED=false` unless invitation and verification controls have been approved.
- [ ] Rotate and remove `BOOTSTRAP_ADMIN_PASSWORD` after the first administrator login.
- [ ] Store Android signing keystore and all deployment secrets only in CI/hosting secret managers.

## Operational readiness

- [ ] Monitor `/ready` and `/status/providers`; alert on a provider becoming unavailable or stale.
- [ ] Enable centralized JSON log collection and request-ID correlation.
- [ ] Run authenticated `/planner/evaluate`, `/planner/suggest`, and `/planner/simulate` load tests against staging PostGIS/Redis.
- [ ] Commission independent penetration testing and legal/privacy review.
- [ ] Publish reviewed Terms of Service, Privacy Policy, support contacts, and Play Store data-safety declarations.
- [ ] Define and implement the retention/deletion schedule for `GeneratedRoute` records.

## Verification commands

```powershell
cd backend
python -m compileall app scripts alembic
python -m pytest -q

cd ../frontend
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run build
pnpm run lint
pnpm audit --prod --audit-level=high

cd ../android
.\gradlew.bat testDebugUnitTest assembleDebug lintDebug --no-daemon
# A distributable release additionally needs real HTTPS backend/Supabase
# Gradle properties and android/key.properties; placeholders must fail.
```

The release is not approved until the hard launch gates are signed off.
