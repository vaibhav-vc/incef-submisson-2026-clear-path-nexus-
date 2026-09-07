# EvidenceGate verification and handoff

Prepared 7 September 2026. Full backend/client and fresh-provider measurements below were executed on 1 September 2026. Packaging checks are repeated when the bundle is built. This date distinction prevents historical observations being presented as continuously live results.

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

Build the web client, then run `python submission/package_release.py` from the repository root in an environment with ReportLab installed. It rebuilds the source, web, PDF, experiment and complete archives and their checksums. It does not invent deployment credentials or rebuild/sign Android; the existing audited debug APK is included explicitly as such. Original experiment outputs remain preserved.
