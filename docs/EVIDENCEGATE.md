# EvidenceGate operations

EvidenceGate is the release boundary between a route calculation and an operational dispatch action. It never turns missing data into an all-clear result.

## Canonical states

| State | Meaning | Dispatch |
| --- | --- | --- |
| `HARD_BLOCKED` | A physical cargo/segment clearance rule failed. This has absolute precedence. | Refused |
| `UNAVAILABLE` | No stored decision evidence exists. | Refused |
| `HOLD` | Evidence exists but is missing, stale, aging, unavailable, seeded, simulated, or fails integrity verification. | Refused |
| `READY` | Every required role is trustworthy, current, available, and covered by the signed evidence root. | Human approval still required |

Required roles are clearance, corridor weather (including NOAA Kp input), port alignment, congestion, and historical delay.

An operator berth window is eligible for trust only when its request includes a manifest reference and the reviewed manifest file's 64-character SHA-256 digest. The digest and reference are sealed into the port evidence record; older or incomplete operator windows remain `HOLD`.

Live records are re-aged whenever EvidenceGate is evaluated. A route that was `READY` can return to `HOLD` after its provider evidence expires. The operator must run a new evaluation; the application does not silently refresh or rewrite an old decision snapshot.

## Certified engineering import

Seeded engineering values deliberately force `HOLD`. To make engineering evidence eligible for `READY`, an authorized operator prepares a CSV containing these columns:

```text
source_code,destination_code,max_height,max_width,max_weight,congestion_factor,historical_delay_hours,geometry_lon_lat,source_reference,certified_by,certified_at,source_type
```

- `geometry_lon_lat` is JSON such as `[[79.08,21.14],[75.56,19.87]]`.
- `source_type` must be `OPERATOR_INPUT` or `IMPORTED_DOCUMENT`.
- `source_reference`, `certified_by`, and timezone-aware `certified_at` are mandatory.
- `certified_by` must exactly match an issuer configured in
  `ENGINEERING_CERTIFICATION_ALLOWED_ISSUERS`; an empty allowlist, an unknown issuer, or a
  future certification timestamp is rejected.
- Every source/destination pair must already identify a known segment.
- The importer validates the entire file before committing and calculates the canonical SHA-256 checksum used by routing evidence. The digest binds the engineering values, source type, document reference, issuer identity, and certification timestamp.

Run:

```powershell
cd backend
python scripts/import_engineering_evidence.py C:\secure\authorized-segments.csv
```

## Approval and atomic dispatch

1. Evaluate every route leg.
2. Inspect the journey evidence bundle. Each leg has a manifest checksum and signed evidence root; the browser export adds a deterministic journey-root checksum.
3. An authenticated user in a configured approval role approves each current evidence root.
4. Dispatch the complete journey through the batch endpoint. The backend locks and validates every owned leg before committing any dispatch state.

Approval is invalid when its evidence-root checksum does not match the current stored snapshot. Schedules without a linked, owned, approved EvidenceGate route cannot dispatch.

## Incident kit

`GET /api/v1/provenance/routes/{route_id}/evidence-kit` returns stored evidence only. It never refetches a provider during an incident. The response includes:

- decision and kit states;
- reason codes and required-role status;
- value and record-envelope checksum verification;
- stored and computed signed evidence roots;
- complete stored evidence/lineage;
- known limitations.

The web console caches the last retrieved integrity kit for the current browser session and can export all journey legs as one deterministic JSON bundle. A cached kit is clearly labelled and never authorizes dispatch.

## Production configuration

- Set independent strong `SECRET_KEY` and `EVIDENCE_SIGNING_KEY` values. The dedicated evidence key signs roots; protect and back it up so stored kits remain verifiable.
- Set `EVIDENCE_SIGNING_KEY_ID` to a stable identifier. On rotation, change the active ID/key
  and retain retired ID-to-key mappings in `EVIDENCE_VERIFICATION_KEYS`; each snapshot stores
  its own key ID and `HMAC-SHA256` algorithm. Missing or unknown historical keys fail closed.
- Configure `APPROVAL_ALLOWED_ROLES` with dedicated operational roles. Evidence approval reads
  those roles only from admin-controlled Supabase `app_metadata.approval_role` (or
  `app_metadata.roles`), never from user-editable metadata or the generic `authenticated` role.
- Keep `DEMO_DATA_ENABLED=false`.
- Configure live weather, NOAA, rail/AIS, and maritime feeds as available. Missing required evidence fails closed.
- Apply Alembic migrations before starting the upgraded service.

EvidenceGate remains decision support. It is not signalling, interlocking, Kavach/ATP, certified dispatch control, customs authority, or a substitute for qualified railway engineering review.
