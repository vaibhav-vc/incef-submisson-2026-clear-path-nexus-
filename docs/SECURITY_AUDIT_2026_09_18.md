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

## Open findings and limits

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
