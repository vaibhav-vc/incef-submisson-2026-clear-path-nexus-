# EvidenceGate verification and handoff

## September 14, 2026 online/offline deployment verification

This pass adds two explicit runtime contracts rather than allowing a demonstration bypass to leak
into a public build. The authenticated `online` build uses Supabase and a configured HTTPS API.
The `offline-judge` build uses only its same-origin Docker gateway, disables every external
operational provider, labels its identity and seeded evidence, and is intentionally unsuitable for
public exposure.

| Current check | Measured result |
| --- | --- |
| Backend | 237/237 tests passed; Ruff, compileall and dependency checks passed |
| Frontend | 16/16 tests passed; type-check and lint passed |
| Explicit builds | Online and offline-judge builds passed, 203 modules each |
| Production dependencies | `pnpm audit --prod --audit-level=high`: no known vulnerabilities |
| Release/experiment tests | 29 passed, 1 skipped because this Windows host does not grant symlink creation |
| Deployment preflight tests | 16/16 passed, including rejection of offline frontend mode in production |
| Credential signatures | 384 included source files scanned; no recognized private credential signature found |
| Managed services | PostgreSQL/Supabase URL normalization, bounded pools, explicit transaction-pooler rejection, and TLS Redis URLs tested |
| Supabase table exposure | Migration head `20260913_15` enables RLS and revokes `PUBLIC`, `anon`, and `authenticated` access to all 28 backend-owned tables |
| Judge launcher | PowerShell parsed; Compose YAML parsed; launcher performs gateway/readiness/station smoke checks after startup |
| Controlled repeat | 1,600/1,600 expected states; 1,400 adverse trials produced zero false `READY` results |
| Docker execution | Not run on this host because Docker is not installed; the judge Compose runtime remains to be rehearsed on the demonstration laptop |
| Android | Not rebuilt in this pass; the previously audited debug APK remains unchanged |

The database review followed Supabase's connection-pooling, prepared-statement, least-privilege,
and RLS guidance. The backend-owned schema deliberately has no permissive browser policies; the
browser uses Supabase Auth while FastAPI owns operational data authorization. The online runbook
documents the supported direct/session-pooler choices and rejects the incompatible transaction endpoint.

### Added deployment controls

- `VITE_APP_MODE` is the canonical mode switch. Offline mode rejects absolute API URLs, never
  constructs a Supabase client, omits map tiles and Overpass calls, and adds a restrictive CSP.
- `LIVE_DATA_ENABLED=false` is a backend master network kill switch. Weather, geometry, rail,
  AIS, port, dust and provider adapters return explicit unavailable values without an HTTP or
  WebSocket call.
- The judge launcher generates run-scoped database/session secrets. Its evidence-signing key is
  generated once per persistent dataset so prior evidence remains verifiable. No demo password is
  committed.
- The explicit `-Offline` / `--offline` launch forbids a container rebuild after the initial
  internet-connected preparation, avoiding judging-day registry dependence.
- The online path accepts managed `DATABASE_URL` and `REDIS_URL` values without discarding TLS or
  credentials. Vercel now uses the pnpm lockfile and an explicit online build.

### Remaining external proof

Install Docker Desktop on the judge laptop and complete the documented online preparation plus a
disconnected rehearsal. Provision the real Supabase/Vercel/API/Redis environment and test sign-in,
RLS migration, `/ready`, evidence export, restart verification and the complete judge walkthrough.
No authorized freight, port, certified engineering, or independent field-validation dataset was
added. These are external deployment and research gates, not facts that can be manufactured in
source code.

The dated raw repeat is preserved at
[`20260914T041823845605Z_evidencegate_c2a60ced`](../submission/experiments/runs/20260914T041823845605Z_evidencegate_c2a60ced/evidencegate_experimental_summary.json).
Its CSV SHA-256 is `cf6afd7ac5c407b48af039e4d7b9b5520540c7037e1fc5dc39e38e96b381730a`.

## September 7, 2026 hardening verification

The upgrade is a tested research prototype, **not a fully live or certified submission**. The original study files and Android binary are preserved. The PDF retains the original controlled study and labels the later verification separately in its conclusion; new raw observations are stored separately and must not be substituted for the original results.

| Current check | Measured result |
| --- | --- |
| Backend | 231 passed, independently repeated; 16 new fail-closed regressions |
| Python checks | Backend and new tooling Ruff checks passed; pip check passed |
| Release/experiment tests | 29 passed, 1 skipped because Windows did not grant physical symlink creation; mocked link rejection also passed |
| Deployment preflight tests | 15 passed; configuration fixtures are synthetic, not live accounts |
| Frontend | 12 tests passed; type-check, lint and production build passed (202 modules) |
| Private client-key guard | A synthetic server key caused Vite to exit 1 before bundling, without echoing the key |
| Browser smoke | Final production setup page checked at 390x844 and 1440x1000; no page errors or mobile horizontal overflow; malformed-URL setup also checked earlier |
| Controlled repeat | 1,600/1,600 expected decisions, including 1,400 adverse trials with zero false READY |
| Current public requests | NOAA SWPC 5/5 HTTP 200/schema-valid; Open-Meteo 0/5, all five requests timed out on this host |
| Docker execution | Not run: Docker executable unavailable; preflight correctly exited 1 with COMPOSE_UNAVAILABLE |
| Deployment definitions | Compose/CI YAML parsed with PyYAML, including custom !reset handling; actual Compose merge/build remains unverified locally |
| Linux launchers | Android Gradle and backend startup shell files normalized to LF; Git attributes preserve LF in future checkouts |

Current raw outputs: [controlled repeat](../submission/experiments/runs/20260907T084720727010Z_evidencegate_d2bc4940/evidencegate_experimental_summary.json) and [live observation, including failures](../submission/experiments/runs/20260907T084729589519Z_live_providers_34602b14/live_provider_summary.json). The live-observation command returned exit 1. Public-provider responses prove only the measured observations, not continuous uptime or authenticated railway/port integration.

### What changed

- Only explicitly APPROVED clearance can reach READY. Excluded required records, unsupported freshness labels and unknown/unavailable source categories now fail closed, even when the evidence was signed.
- Authentication handles malformed configuration, failed/stalled SDK promises and stale session-read races; rendering failures show a recovery screen instead of an empty workspace. Client builds reject recognized privileged keys and credential-bearing public URLs. This follows [Supabase's public/server key separation](https://supabase.com/docs/guides/getting-started/api-keys); no database policy or live authentication change is claimed.
- Backend and workers receive matching signing/provider settings. Production removes inherited internal ports, disables auth bypass/demo/debug modes, gates health on dependency readiness and permits only the configured Supabase origin through the edge CSP.
- Experiment reruns use fresh output directories, refuse overwrite and exit nonzero on failed measurements. Numeric/timestamp provider validation is stricter.
- Packaging checks portable paths, collisions, linked files, selected credential signatures and every generated payload hash. ZIP replacement is atomic per archive. A standalone verifier checks the bundle without extraction. These checks complement, not replace, an independent security audit; checksums are not digital signatures.
- PDF callout spacing now reserves its border padding so boxes do not overlap preceding headings; the conclusion distinguishes the original successful observation from the later weather timeouts.
- CI now defines deployment, release and frontend regression gates. The disposable container job needs an actual successful CI run before its result can be claimed.

### Limits of this verification

No Docker/container deployment, real Supabase sign-in, authenticated end-to-end operation, new Android build/device installation, independent field validation or official INSEF review was performed in this hardening pass. Open-Meteo was unavailable from this host during the current observation. No success state or substitute observation was manufactured to hide that failure.

## Historical September 1 verification

The following measurements were executed on September 1, 2026, not during the current hardening run. Packaging checks are repeated when the bundle is built. This date distinction prevents historical observations being presented as continuously live results.

| Check | Observed result |
| --- | --- |
| Backend suite, two passes | 215/215 each; no failures |
| Python static/dependency checks | Ruff, compileall and pip check passed |
| Database migration graph | 14 revisions, one head: `20260831_14`; offline SQL generation passed |
| API schema | 58 paths, 64 operations, 91 schemas |
| Service smoke check | `/health` 200; `/ready` 503 (database and Redis unavailable) |
| Public provider requests | Open-Meteo 5/5 and NOAA SWPC 5/5 HTTP 200/schema-valid |
| Web | Type-check, lint, production build and production dependency audit passed |
| Android | 53 Gradle tasks; 3/3 unit tests; lint 0 errors, 19 warnings |
| Original controlled experiment | 1,600/1,600 expected states; 0 false READY in 1,400 adverse trials |
| APK | Valid Android debug signature; Android 8+; no connected-device installation test |

## Defects found and corrected

- Missing Supabase settings caused web module initialization to throw. The client now renders a configuration-required screen and does not create an authentication client until settings exist. Production build rendering was checked with headless Chrome.
- PDF portability depended on viewer font substitution. The builder now embeds available Arial or DejaVu fonts; the revised PDF rendered without the earlier missing-font warnings.
- A standalone submission checksum listed older PDF/archive hashes. The packaging script regenerates manifests from current bytes and verifies ZIP entries after generation.

## Remaining work

- Provision and configure PostgreSQL/PostGIS, Redis, Supabase and signing keys. Apply migrations to the real database and achieve `/ready` 200.
- Rebuild web/Android with the real deployment configuration. The included Android binary is an emulator-oriented debug build with placeholder Supabase values; sideloading alone does not make login or live operations work.
- Run end-to-end authenticated workflows on the actual demonstration deployment and device. Compile/unit tests do not substitute for this.
- Obtain authorized freight/berth feeds and certified engineering data if those live capabilities will be demonstrated. Public weather checks do not verify railway or port operations.
- Complete participant, grade, school and guide identities; record/test the demonstration-video URL; confirm eligibility and submission requirements with the organizer.
- Android has 19 nonfatal lint warnings. Production signing, independent security review, operational acceptance and field validation remain outstanding.

## Assessment

The repository and measured experiments are ready to share for review. A fully live demonstration and the official submission are not yet complete. No defensible overall percentage can replace the outstanding deployment and participant requirements above.

## Reproducing the artifacts

Run `python submission/package_release.py` from the repository root in an environment with pnpm
and ReportLab installed. It explicitly builds the authenticated online web contract, then rebuilds
the source, web, PDF, experiment and complete archives and their checksums. The offline judge
edition is reproduced from the source archive with its dedicated Compose launcher. Packaging does
not invent deployment credentials or rebuild/sign Android; the existing audited debug APK is
included explicitly as such. Original experiment outputs remain preserved.
