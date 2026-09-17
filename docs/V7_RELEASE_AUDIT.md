# EvidenceGate v7 release audit — 17 September 2026

Status: software research milestone. The national railway replacement objective remains open. This audit covers code, data provenance and release reproducibility; it does not establish railway field safety or incumbent-system parity.

## Follow-up — synthetic seed isolation

Configuration now rejects `REAL_DATA_ONLY=true` together with `DEMO_DATA_ENABLED=true` in every environment. The standalone seed function independently rejects real-only mode, disabled demo mode and any environment other than development before opening a database session. Regression tests cover these rejection paths and configuration startup.

This prevents new seed writes; it does not remove historical rows or establish the authenticity of imported data. The judge Compose profile now runs with `REAL_DATA_ONLY=true`, `DEMO_DATA_ENABLED=false`, and a separate `evidencegate-judge-real` volume. It mounts the 16 September 2026 SNCF capture read-only, checks the manifest against a pinned digest, and recomputes each file digest before the launcher reports success. A follow-up audit found that a self-checksum alone could be recomputed after changing the manifest; the pin closes that local tampering path. This is an integrity check, not a publisher signature. The captured publisher bytes remain historical French research data, not live Indian operational evidence. The snapshot is not imported into route or decision stores.

Verification: 353 backend tests passed using `--basetemp .pytest-tmp-real-policy-1`; targeted seed/model tests passed (8), and Ruff passed for the changed Python files. The first full run encountered five fixture setup errors from Windows access denial on the system pytest temporary directory; the project-local rerun completed without those errors. One existing Starlette deprecation warning remains.

The recorded source view now offers a bounded decoded preview using the repository's existing timetable parsers. It preserves the capture timestamp and classifies every result as `REPLAYED_SNAPSHOT`; a preview request does not refresh that timestamp. The actual captured static feed parses to 521,778 records (including calendar rows), with 330,490 stop times. The recorded realtime payloads contain 1,675 trip-update entities and 527 alert entities. These are publisher records, not experimental incidents or a field safety result. A cache stores at most three bounded previews, and current file integrity is checked before cache access. The decoder separately compares the exact bytes it reads with the pinned feed checksum, covering a change between inspection and decoding.

Decoded-preview verification: 365 backend tests passed, including actual-file decoding, bounded result size, timestamp preservation, cache corruption and a change between inspection and decoding. The frontend's 22 tests, typecheck, lint and offline build passed. The judge CI smoke now requests all three decoded feeds over HTTP and checks their original checksums and capture times.

## Audit 1 — code and trust boundaries

The independent review reproduced required operator assertions becoming REVIEWABLE, optional invalid ancestors being ignored, evidence reuse without subject binding, self-attestation, and missing lineage verification. These findings caused implementation changes before release:

- The generic assurance policy requires exact subject and context bindings. Required operator input remains HOLD. Provider records require server connector authentication; a browser cannot assign provider classifications.
- Source identity, type, availability, expiry, excluded status, completeness and integrity are checked. A record's valid-until date cannot extend the registered source freshness limit.
- Iterative lineage processing rejects cycles and propagates invalid optional ancestors through derived descendants, regardless of input ordering. It avoids recursive traversal limits.
- Each assessment signs its source metadata and lineage checksums. Verification checks the stored checksum column, current envelope, source catalog and graph.
- Cases optionally name an independent reviewer. The creator may capture and assess evidence; only the assigned, separately authorized reviewer may record a final review. Ordinary operator roles cannot attest. A snapshot accepts one final receipt. New evidence, obsolete snapshots, changed integrity, or changed policy state require a new assessment.
- Reviewer identity is bound into the case seal. Historical receipts contain the role at review time. The system does not claim an external identity-provider revocation feed for other users.
- Carriage manifests require a declared expected count and contiguous, complete carriage positions. Public manifests, section policies and occupation windows cannot self-assign VERIFIED.
- Public dispatch and driver-speed endpoints return HTTP 410. Conflict assessments retain the limits of the captured timetable and section evidence.

The reviewer sub-agents reached their usage limit after producing findings and partial fixes. The primary agent inspected those edits, completed the changes and ran the regression suite. This is an engineering review, not an accredited independent safety assessment.

## Audit 2 — research data and reconstruction

Real publisher snapshot: [`20260916T064806641708Z_sncf_snapshot_2dc07b37`](../submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37/source_manifest.json).

It contains official SNCF static GTFS, Trip Updates and Service Alerts response bytes, retrieval timestamps, requested/final URLs, response sizes, SHA-256 digests, licence/attribution and ZIP validation. Read the [SNCF redistribution notice](data/SNCF_ODBL_NOTICE.md). These are French public transport feeds, not Indian Railway operational authority. Stored observations are historical once captured. The dependency-free recorder preserves GTFS-RT protobuf bytes without semantic decoding.

Paired experiment: [`20260916T064855068103Z_evidence_assurance_1431e7d7`](../submission/experiments/runs/20260916T064855068103Z_evidence_assurance_1431e7d7/).

The actual legacy EvidenceGate V2 evaluated 2,400 unique controlled fixtures: 481 clean controls and 1,919 mutations across 19 fault classes. This run recorded zero false admissions, zero false holds and zero policy exceptions for the full gate. Baseline comparisons, intervals, per-fault counts and timing are in the run artifacts. These are software mutation outcomes, not 2,400 real train incidents, and do not validate the separate generic v7 policy or collision prevention. The generic v7 policy is covered by its dedicated regression tests.

Public production observations must retain their actual classification. Synthetic unit tests and offline demo fixtures remain explicitly labelled and cannot be represented as live measurements. No authorized FOIS/COA/RTIS operational connector or certified engineering feed was obtained during this release.

Exported generic assurance bundles now contain the canonical sealed manifest, full redacted evidence envelopes, source catalog, lineage and canonical review receipts. Judges can check these sections without an API or dependencies:

```sh
python submission/verify_assurance_bundle.py path/to/downloaded-assurance-bundle.json
```

The verifier detects changed or duplicate records, changed terms, altered lineage and checksum mismatches. It explicitly reports HMAC authentication as unchecked: independently authenticating the signature needs the trusted server, while a root obtained through a trusted channel can anchor offline checksum comparison. Supplementary display summaries and live freshness are outside this offline integrity result.

## Audit 3 — release verification

**Verified runtime release:** commit `7dfc91bd063e26f73084301bf0b2cce8f1619adb` passed all five jobs in [CI run 35176284755](https://github.com/vaibhav-vc/incef-submisson-2026-clear-path-nexus-/actions/runs/35176284755), including the HTTP/PostgreSQL assurance smoke and offline reconstruction. Subsequent alignment documentation does not change that runtime code.

Local results and GitHub CI are recorded below after final execution. Existing packaged v6 ZIP/APK/PDF files are historical and do not contain these source upgrades.

- Backend regression suite: 346 passed (13.99 seconds); one dependency deprecation warning.
- Backend Ruff and Python compilation: passed.
- Frontend: 22 tests, typecheck, lint and online/offline builds passed after review UI changes.
- Frontend production dependency audit: no known vulnerabilities at this check.
- Submission utilities: 31 tests, 30 passed and one skipped because this Windows host cannot create symlinks.
- Deployment script tests: 17 passed in the preceding verification pass.
- Local Docker and JDK executables are unavailable. Docker services, PostgreSQL migrations, Redis readiness and Android therefore require the GitHub CI jobs before their status can be claimed.
- Hosted authentication, a configured public deployment, official Indian operational feeds and testing on the actual judge device remain incomplete.

The initial upgrade commit `249bdcf` passed all five GitHub jobs (backend,
frontend, deployment, judge-demo and Android). A subsequently added HTTP/PostgreSQL
assurance smoke test exposed findings being inserted before their parent snapshot.
The fix explicitly flushes the parent. Evidence capture also seals the database's
numeric representation after refresh, preventing float/Decimal checksum drift.
The smoke now exercises empty-case UNAVAILABLE, unverified capture, HOLD,
persisted signature verification, bundle export, offline reconstruction and
self-review rejection. Final verification of the latest commit is recorded in
the linked GitHub run and the release handoff.

### Deployment and rollback

Back up the database before applying migrations 17 and 18. They add generic assurance tables/reviewer separation and carriage-count completeness. Existing consist records are conservatively marked unverified. Do not downgrade a database containing review evidence without an explicit retention and recovery plan. To recover a failed deployment, restore the prior application and its matching database backup in an isolated environment, retain logs and evidence, and investigate the failing migration/readiness check.

Use [the online deployment runbook](ONLINE_DEPLOYMENT.md) and [the judge edition runbook](JUDGE_DEMO.md) if present in your checkout; the launchers and Compose files are the executable configuration. Verify authentication and `/ready` on the actual target. Do not infer live readiness from a successful frontend build.

The full replacement roadmap, incumbent capability mapping, integration dependencies, research questions and sources remain in [the replacement architecture](INDIAN_RAILWAY_REPLACEMENT_ARCHITECTURE.md) and [the v7 plan](RESEARCH_PIVOT_V7.md).
