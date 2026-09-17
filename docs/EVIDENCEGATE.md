# EvidenceGate v2/v7 transition

EvidenceGate is a non-vital evidence-admissibility boundary. It evaluates stored evidence for an externally supplied research case and produces deterministic findings and a reconstruction bundle. It never issues movement authority, dispatches a train, sets a signal, overrides an interlocking/ATP system, certifies engineering data, or tells a driver what speed to use.

## Assessment states

| Stored state | v7 presentation | Meaning |
| --- | --- | --- |
| `HARD_BLOCKED` | `CONFLICTING_EVIDENCE` | The legacy cargo/segment rule reports an explicit physical conflict. This is evidence of a conflict, not a certified railway prohibition. |
| `UNAVAILABLE` | `UNAVAILABLE` | No stored assessment evidence exists. |
| `HOLD` | `REVIEW_REQUIRED` | Required evidence is missing, stale, aging, unavailable, excluded, malformed, unauthorized, context-mismatched, contradictory, or fails integrity/lineage checks. |
| `READY` | `REVIEWABLE` | Every required policy-v2 role passed the implemented checks. It does not mean safe, compliant, cleared, or authorized to move. |

The transitional route policy requires one direct record for each legacy role: clearance finding, local weather, port alignment, congestion, and historical delay. Each direct role has an exact expected entity type and a minimum semantic payload schema. Required transitive parents must be present, used in the decision, current for their source class, and connected by a trust-relevant lineage edge.

NOAA planetary Kp is supplementary `REFERENCES` telemetry. It is not a required weather ancestor and cannot raise or lower ordinary railway evidence sufficiency. An asset-specific policy may require geomagnetic evidence only when it names the susceptible equipment, authority, geography, validity interval, threshold, and human response.

## Fail-closed checks

EvidenceGate v2 currently verifies:

- exact owner, route/case, snapshot, and request binding;
- known source ID and source/type compatibility;
- expected entity type and role-specific payload structure;
- nonempty payload and calculated completeness marker;
- aware fetch/observation/validity timestamps, future-time rejection, live-source freshness, and conservative maximum age for imports/operator statements without issuer expiry;
- availability and explicit unavailable/degraded states;
- value checksum and trust-field envelope checksum;
- one unambiguous direct record per required role;
- complete, non-excluded transitive ancestors;
- missing endpoints and cycles in trust-relevant lineage;
- clearance/derived score consistency with the signed snapshot;
- signed evidence-root completeness and verification.

All uncertainty fails to `HOLD`/`REVIEW_REQUIRED`. A valid application HMAC over a malformed or unsupported construction does not make it reviewable.

## Authenticity boundary

Three claims are deliberately separate:

1. SHA-256 says current bytes match recorded bytes.
2. The EvidenceGate HMAC says this application sealed the recorded envelope with the configured key.
3. External authenticity says a scoped railway, infrastructure, port, weather, or other authority issued the content.

Only the first two are implemented generically. External authenticity requires a provider-authenticated connector, independently verifiable issuer signature/public key, or governed ingestion service. Typing an allowlisted issuer name or a 64-character hash is not sufficient. Existing CSV engineering imports are integrity-preserved but set `signature_verified=false`, so they cannot independently satisfy the authoritative engineering contract.

Operator-entered berth windows are retained as supplementary/pending evidence. They cannot satisfy the authoritative port role by themselves; a server-observed document whose bytes are hashed and whose issuer/scope is verified, or an authenticated berth connector, is required.

## Time policy

Live-source observations are dynamically re-aged at every assessment. Operator/imported evidence must include an aware issue/observation time. If an issuer does not provide `valid_until`, v2 applies a conservative maximum age (24 hours for operator statements and approximately one year for imported documents). Production policies should instead store issuer-provided effective-from, valid-until, version, supersession, and revocation data.

## Review attestation and dispatch retirement

The legacy route approval endpoint records that an authenticated configured role reviewed one exact evidence root. The web client presents this as an **evidence review attestation**, not route approval.

Route, multi-leg journey, and schedule dispatch endpoints are retired and return HTTP 410 before database access. The UI exposes no dispatch action. Users export the deterministic evidence bundle and continue in the railway's authorized control, signalling, interlocking, and ATP workflow.

Future v7 work replaces mutable legacy route approval columns with append-only, separately signed review receipts bound to case, snapshot, evidence root, reviewer identity/role, purpose, time, expiry, and revocation state. Any evidence/context/policy change creates a new root and never inherits an old receipt.

## Incident/reconstruction kit

`GET /api/v1/provenance/routes/{route_id}/evidence-kit` is the legacy transition endpoint. It returns stored evidence only and never refreshes external providers while reconstructing the historical case. It includes:

- assessment/kit state and reason codes;
- requirement-level status;
- stored and recomputed value/envelope checksums;
- stored and recomputed signed evidence root;
- evidence records and lineage;
- known limitations.

The browser can export all legs as one deterministic JSON bundle. Browser hashing supports reproducibility; it is not external issuer authentication.

## Configuration

- Use separate strong `SECRET_KEY` and `EVIDENCE_SIGNING_KEY` values.
- Give the evidence key a stable `EVIDENCE_SIGNING_KEY_ID`; preserve retired verification keys for historical reconstruction.
- Protect signing keys server-side. Never expose them to Vite/Android or commit them.
- Keep seeded/simulated data clearly labelled; it is judge-demo material, never real operational evidence.
- `REAL_DATA_ONLY` is not treated as a magic truth flag. Reviewability is decided role by role from source identity, authority, authenticity, context, time, schema, lineage, and availability.
- Missing external providers remain explicit `UNAVAILABLE`; no adapter substitutes demo data in online mode.

See [the v7 research/system-design plan](RESEARCH_PIVOT_V7.md) for the generic assurance-case model, comparative baselines, official real-data sources, six phases, and acceptance gates.
