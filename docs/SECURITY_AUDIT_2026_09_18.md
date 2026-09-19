# Local adversarial audit — 18 September 2026

Scope: repository review and bounded local tests, with three independent
read-only sub-agent reviews. No deployed URL was supplied, so no remote
penetration test, destructive test, or exhaustion load test was performed.
This is not certification or evidence of railway operational safety.

## Reproduced and repaired

- **Unauthenticated metric growth:** distinct nonexistent URLs retained distinct
  metric entries indefinitely. Unknown URLs now share one label; nonstandard
  HTTP methods share `OTHER`. Registered routes retain their template labels.
- **Monitoring-output corruption:** a quoted URL produced invalid Prometheus
  labels. Dynamic labels now escape quotes, backslashes and newlines.
- **Carriage save failure:** valid manifests accessed a nonexistent carriage
  verification field. Removed that assignment; public manifests remain UNVERIFIED.
- **Manifest validation:** duplicate physical identifiers, blank identity/source
  strings, and infinite measurements were accepted. Inputs now normalize outer
  whitespace, require unique identifiers and finite typed measurements.

Before repair, the focused carriage suite had nine failures and 25 passes.
After repair it had 34 passes. Endpoint regression uses real ORM construction
but mocks database I/O; it is not a PostgreSQL round-trip test.
Metrics and carriage focused tests together: 41 passes.
Final complete backend test suite: 393 passes, with one existing Starlette
deprecation warning. Backend Ruff checks and Git whitespace checks pass.

## Configuration hardening

- Both Docker contexts now exclude nested environment and common private-key
  files. No actual credential disclosure was established; images were not built
  locally because Docker is unavailable on this host.
- Vercel configuration now includes frame blocking, nosniff, a referrer policy,
  and a minimal CSP restricting frames, objects and base URLs. A complete
  script/connect resource policy still needs the actual deployment origins.
  Deployed headers have not been verified.

## Findings recorded on 18 September (see follow-up below)

1. Assurance arbitrary JSON fields accept nonfinite numbers and lack explicit
   byte/depth/node limits; required-role strings lack a per-item length limit.
   Reproduced at schema level, not as a database failure. Add bounded recursive
   JSON validation and request-body limits.
2. Timetable ingestion buffers provider responses before checking feed size.
   Stream with a decoded-byte ceiling and concurrency limits. No oversized
   external response was requested during this review.
3. Shipment position ingestion accepts explicitly labeled SIMULATED records
   even in real-data-only mode. They are not trusted decision evidence, but
   acceptance conflicts with that runtime policy.
4. Owners can annotate compliance overrides without a privileged role. Existing
   behavior does not change overall status or re-enable dispatch. Decide whether
   this is an owner annotation or a qualified approval before changing roles.
5. Full online CSP and deployed-header verification remain outstanding.
6. Changing consist data versus previously assessed occupation windows needs
   dedicated invalidation/concurrency review. Current-network coverage and
   freshness are not established merely by a conflict result.

Existing authentication/reviewer tests passed in the independent review (30).
Owner/assigned-reviewer checks, signed app-metadata roles and production rejection
of authentication bypass held in this bounded review. No exhaustive security,
secret-history, live-provider or real railway validation claim is made.

All example malicious inputs were local test fixtures, not real operational data.

## 19 September follow-up

The following repairs address findings 1–3 above; their remaining limitations
are explicit rather than treated as a complete production-security sign-off.

- Assurance `context`, `value_summary` and `metadata` now reject nonfinite
  numbers, cycles, non-JSON values and invalid Unicode. Each object is limited
  to 65,536 compact UTF-8 JSON bytes, 16 levels below the root and 4,096 nodes
  including keys. These are resource limits, not railway engineering thresholds.
  Normalized role names are limited to 80 characters, including Unicode uppercase
  expansion. Accepted evidence content is preserved, not replaced with defaults.
- Validation errors return HTTP 422 without echoing submitted `input` or exception
  `ctx`; responses contain at most 64 errors with `type`, `loc` and `msg`. Existing
  frontend error presentation uses `msg` and does not require removed fields.
- Timetable HTTP downloads enforce the smaller of the existing global and configured
  feed-byte limits while streaming. Oversized Content-Length is rejected before body
  reads; missing or inaccurate lengths cannot bypass actual byte accounting. Responses
  close on overflow, timeout and HTTP failure. Authentication error mapping is retained.
- Downloads request `Accept-Encoding: identity` and reject other HTTP content encodings
  with `UNSUPPORTED_ENCODING` before reading/decompressing the body. This prevents
  automatic HTTP decompression from allocating an oversized decoded chunk. Providers
  that insist on HTTP gzip must be reconfigured; there is no buffering fallback.
  A GTFS ZIP archive is application content and remains supported by the existing parser.
- Real-data-only mode now rejects SIMULATED shipment positions with HTTP 422 before
  any write. Owner/tracking checks still run first. Real user submissions remain
  unverified operator declarations; disabling real-data-only mode retains explicitly
  labeled simulation behavior, never trusted provider provenance.

Still outstanding: pre-parse HTTP body limits, ingestion concurrency limits, the
compliance-override policy decision, full online CSP/deployed checks, and consist/
occupation-window invalidation and concurrency review. No remote attacks or oversized
external-provider requests were made. Local mocks verify download failure behavior;
they do not prove compatibility with every live provider.

Verification: the full backend suite passed 438 tests, with one existing Starlette
deprecation warning; backend Ruff and Git whitespace checks passed. Test fixtures
use short parameter IDs so large adversarial values do not become Windows paths.
