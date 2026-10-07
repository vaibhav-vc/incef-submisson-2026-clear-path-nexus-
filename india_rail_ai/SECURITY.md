# Security

## Threat model (what we defend against)

| Threat | Control | Test |
|---|---|---|
| Unauthenticated or wrong-role use (e.g. a cab screen or sensor issuing decisions) | Three roles (viewer / controller / feed) with separate 32+ character tokens; constant-time comparison; tokens only in `Authorization: Bearer` (never in URLs); feed role cannot read or decide | `tests/test_security.py`, `tests/test_attacks.py` |
| Misconfigured production server | `RAILGUARD_MODE=production` refuses every request (503) until all tokens are long, distinct and `RAILGUARD_ALLOWED_HOSTS` is set; interactive API docs disabled | `test_production_without_tokens_fails_closed` |
| Spoofed, replayed or stale live data | Signed feed envelopes (HMAC-SHA256 per source key), ±120 s clock window, nonce memory, increasing sequence, 250-event cap, per-event validation; off-route fixes become route-deviation threats; the twin flags implausible jumps and stale positions | `tests/test_livefeed.py`, simulation invariant INPUT_REJECTION |
| Malicious input (NaN/Infinity, wrong types, unknown fields, JSON bombs, injection strings, path traversal) | Strict request models (`StrictRequest`: no coercion, no extra fields, finite numbers only); 64 KB body cap; chunked uploads refused; regex-constrained identifiers; parameterised SQL only; validation errors never echo input | `tests/test_attacks.py` (32 cases) |
| Cross-site scripting / framing | Strict CSP (`script-src 'self'`, no inline script or style), `X-Frame-Options: DENY`, DOM built with `textContent` only | `test_pages_have_no_inline_script_or_style`, CSP checks in Chromium |
| Denial of service | Token-bucket rate limits per client and endpoint class; bounded memory everywhere (rate-limit table, audit events, snapshots, threats, nonces); 60 s watchdog proven in simulation | `test_rate_limit`, simulation LIVENESS |
| Tampering with the decision record | Hash-chained audit events, optional HMAC with `RAILGUARD_AUDIT_KEY`, checksummed snapshots, replay that must reproduce the ranking; `python -m india_rail.railguard.audit verify <file>` | `test_audit_chain_detects_tampering_and_survives_restart`, simulation REPLAY |
| Vulnerable dependencies | Pinned versions; `pip-audit` reports 0 known vulnerabilities (FastAPI 0.142.2 / Starlette 1.7.0 / pytest 9.0.3) | CI + `seva2026/AUDIT_LOG.md` |
| Insecure code patterns | Bandit: 0 findings (7 reviewed suppressions, each justified in the code); ruff lint | `seva2026/AUDIT_LOG.md` |

## Deployment checklist (production)

1. Generate tokens: `python -c "import secrets; print(secrets.token_urlsafe(48))"` (one per role), and feed keys
   (`secrets.token_hex(32)`) per authorised source in `RAILGUARD_FEED_KEYS`.
2. Set `RAILGUARD_MODE=production`, `RAILGUARD_ALLOWED_HOSTS`, `RAILGUARD_AUDIT_DIR` (on Indian infrastructure,
   retained ≥180 days per CERT-In) and `RAILGUARD_AUDIT_KEY`.
3. Terminate TLS in front of the service (the service sends HSTS in production); synchronise the host clock
   with NIC/NPL NTP; keep the service on the railway's internal network.
4. Run `python -m pytest -q`, `pip-audit -r requirements.txt` and the simulation regression before each release.

## Incident response (CERT-In: report within 6 hours)

1. Contain: rotate the affected role tokens / feed keys (restart with new environment values); set the feed
   source's key to a new value to cut off a compromised sender.
2. Preserve: copy `RAILGUARD_AUDIT_DIR`; verify it with `python -m india_rail.railguard.audit verify`.
3. Report to CERT-In (incident@cert-in.org.in) and the railway's CISO within 6 hours of noticing it.
4. Review: replay every decision snapshot taken during the incident window.

## Reporting a vulnerability

Report privately to the repository owner (GitHub security advisory). Please do not open public issues for
security problems.
