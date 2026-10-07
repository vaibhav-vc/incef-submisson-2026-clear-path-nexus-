# Pre-audit security checklist (OWASP ASVS 4.0.3, Level 2 - self-assessment)

Prepared for a CERT-In empanelled / STQC auditor. Self-assessment only; the auditor's findings take precedence.
Status: **Pass** (control in place and tested), **Partial**, **N/A** (feature not present), **Operator**
(deployment responsibility).

| ASVS chapter | Key requirements | Status | Evidence |
|---|---|---|---|
| V1 Architecture | Threat model; trust boundaries; least privilege | Pass | `../../SECURITY.md` threat model; three roles; feed cannot read or decide |
| V2 Authentication | Strong credentials; no default secrets | Pass (service tokens) / Operator (SSO) | 32+ char distinct tokens enforced in production; no defaults; for named staff log-in, integrate IR's identity provider in front (Operator) |
| V3 Session management | No session cookies | N/A | Bearer tokens only; no cookies set |
| V4 Access control | Deny by default; server-side enforcement | Pass | Every route declares a role dependency; `test_roles_are_separated`, `test_feed_role_cannot_take_decisions` |
| V5 Validation / encoding | Strict input validation; output encoding | Pass | `StrictRequest` (no coercion, no extra fields, finite numbers); regex identifiers; `textContent`-only DOM; `test_attacks.py` |
| V6 Cryptography | Approved algorithms; key management | Pass / Operator | HMAC-SHA256, SHA-256, `secrets`; keys via environment; key storage/rotation by operator |
| V7 Errors and logging | No sensitive data in logs; tamper-evident logs | Pass | Tokens never logged; errors never echo input; hash-chained HMAC audit |
| V8 Data protection | Minimal data; no caching of sensitive responses | Pass | No passenger data; `Cache-Control: no-store` on API responses |
| V9 Communications | TLS everywhere | Operator | HSTS sent in production; TLS terminated by the hosting proxy |
| V10 Malicious code | Dependency integrity | Pass | Pinned versions; pip-audit 0; Bandit 0; data files pinned by SHA-256 |
| V11 Business logic | Anti-automation; workflow integrity | Pass | Rate limits; approval only of the latest ranking for the current state |
| V12 Files and resources | Upload limits; path traversal | Pass | No uploads; 64 KB body cap; traversal tests |
| V13 API | Schema enforcement; method restrictions | Pass | Pydantic strict models; 405 on wrong methods; docs disabled in production |
| V14 Configuration | Secure headers; hardened defaults | Pass | CSP without inline script, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS; fail-closed production mode |

Open for the auditor: penetration test on the deployed environment; infrastructure configuration review; key
management procedure; incident drill per CERT-In (6-hour reporting).
