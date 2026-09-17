# Evidence-backed speed-risk advisory

`POST /api/v1/speed/advisory` now returns **HTTP 410**. The earlier endpoint
accepted authority labels and checksums supplied by the caller, which could not
prove that a railway authority issued the underlying values. Keeping that path
public would make a driver-facing number look more trustworthy than it was.

The pure calculator remains available to tests and explicitly labelled
simulation research. It does not send commands to a locomotive, signal,
interlocking, ATP/Kavach system, driver, or dispatch system. A future network
endpoint must load certified movement authority, restrictions, braking data,
consist identity and territory context from authenticated server-side records;
it must not accept those trust claims in a request body.

## Required evidence

The API intentionally has no default route speeds, braking values, headways,
or weather caps. The caller must provide current values and a provenance
envelope for each value:

- an `AUTHORITATIVE` `ROUTE_LIMIT` source;
- an `AUTHORITATIVE` `HEADWAY` source (or an authorized `BLOCK_OCCUPANCY`
  constraint in a future network-capacity adapter);
- current consist braking performance from an `AUTHORIZED_FEED` or a
  checksum-certified `IMPORTED_DOCUMENT`;
- a real corridor reference and timezone-aware evaluation timestamp.
- the SHA-256 of the actual carriage-level consist manifest being evaluated.

Supplementary public data (weather, mapped geometry, historical schedules) is
retained for traceability but cannot establish an operational speed cap. The
service returns `HOLD` or `UNAVAILABLE` and withholds all numeric speeds when a
required source is missing, stale, future-dated, non-authoritative, or
invalid. A source's `valid_until` is evaluated against the request's
`evaluation_at`; this makes replayed data visible instead of silently calling
it live.

Imported documents must include a SHA-256 checksum. Public or cached records
cannot be labelled authoritative in the request schema. Private provider keys
must remain server-side; the browser should submit only references and values
obtained through the authenticated API/import workflow.

## Retired request contract (simulation reference only)

The `constraints` array accepts these categories:

`ROUTE_LIMIT`, `TEMPORARY_RESTRICTION`, `TRACK_GEOMETRY`, `GRADIENT`,
`AXLE_LOAD`, `ENVIRONMENT`, `HEADWAY`, and `BLOCK_OCCUPANCY`.

Every item contains `category`, a human-readable `label`, `limit_kph`, and an
evidence object:

```json
{
  "route_id": "<owned-route-uuid>",
  "corridor_reference": "<authority-corridor-id>",
  "consist_manifest_checksum": "<64-hex-sha256-of-the-actual-consist>",
  "evaluation_at": "<timezone-aware-ISO-8601-time>",
  "constraints": [
    {
      "category": "ROUTE_LIMIT",
      "label": "<authority route limit label>",
      "limit_kph": "<value-from-authorized-source>",
      "evidence": {
        "source_key": "<registered-provider-key>",
        "source_type": "AUTHORIZED_FEED",
        "authority_level": "AUTHORITATIVE",
        "source_reference": "<provider-record-or-document-reference>",
        "observed_at": "<source-observation-time>",
        "fetched_at": "<server-fetch-time>",
        "valid_until": "<source-validity-end-time>",
        "checksum": "<64-hex-sha256-of-the-raw-source-payload>",
        "provider_version": "<provider-schema-version>"
      }
    },
    {
      "category": "HEADWAY",
      "label": "<authority block/headway label>",
      "limit_kph": "<value-derived-by-authorized-capacity-system>",
      "evidence": { "<same-provenance-fields-including-checksum>": "<real-values>" }
    }
  ],
  "braking": {
    "effective_deceleration_mps2": "<measured-or-approved-consist-value>",
    "reaction_time_seconds": "<documented-value>",
    "safety_margin_meters": "<documented-value>",
    "evidence": {
      "source_key": "<brake-test-source>",
      "source_type": "IMPORTED_DOCUMENT",
      "authority_level": "AUTHORITATIVE",
      "source_reference": "<manifest-or-brake-test-reference>",
      "observed_at": "<document-time>",
      "fetched_at": "<import-time>",
      "valid_until": "<document-validity-end-time>",
      "checksum": "<64-hex-sha256>"
    }
  }
}
```

The string placeholders above are deliberate. They prevent documentation from
being copied as if it contained an operational value. The UI panel also starts
with blank speed/source fields and labels that values must come from real
authorized evidence.

## Response semantics

- `ADVISORY` in the pure simulation result: all supplied test inputs satisfy
  the calculator's validation rules. It is not a driver instruction. The numeric
  result is the minimum of the supplied authoritative caps, with a transparent
  stopping-distance calculation from the supplied braking evidence.
- `HOLD`: at least one required input was submitted but it is missing, stale,
  future-dated, or not authoritative.
- `UNAVAILABLE`: no complete evidence set exists (for example, no braking
  record or no constraints). No numeric speed is emitted in either blocked
  state.

The response includes every submitted evidence record with its source key,
reference, freshness, and whether it was used. This is the minimum review
surface required to explain why the advisory was produced or withheld.
It also echoes the carriage-manifest checksum so the advisory can be tied to
the exact consist reviewed by a judge or operator.

## Source boundaries

The service does not call a public map, weather, passenger-tracking, or AIS
endpoint and convert its output into a movement limit. OpenStreetMap,
OpenRailwayMap, weather providers, GTFS, RailRadar, or AISstream can be
supplementary inputs only unless an infrastructure manager explicitly
authorizes a feed for the particular decision. Live signal state, block
occupancy, temporary speed orders, and movement authority require an
authorized railway operations source. If that source is not configured, the
correct result is `UNAVAILABLE`, not a guessed speed.

## Testing

The pure service tests cover:

- a complete current evidence set;
- missing headway and braking data;
- expired and future-dated evidence;
- supplementary weather data excluded from the operational cap;
- checksum enforcement for imported brake documents;
- timezone enforcement; and
- the transparent stopping-distance formula.

Run them from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest app/tests/test_speed_advisory.py -q
```
