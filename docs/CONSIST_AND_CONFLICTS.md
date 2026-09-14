# Consist and network-conflict API

The planner now supports carriage-level manifests and section-occupation
conflict analysis. These endpoints are decision-support only. They do not
replace signalling, interlocking, ATP/Kavach, movement authority, or a
railway dispatcher.

## Source contract

Every carriage, occupation window, and section policy requires:

- a real source type (`LIVE_PROVIDER`, `AUTHORIZED_FEED`,
  `IMPORTED_DOCUMENT`, `OPERATOR_INPUT`, `REAL_HISTORICAL`, or
  `REPLAYED_SNAPSHOT`);
- a source reference;
- a lowercase or uppercase SHA-256 checksum;
- timezone-aware observed and fetched timestamps.

`SEEDED_BASELINE` and `SIMULATED` are rejected by the API. Historical and
replayed real records remain available for research, but the conflict engine
will return `UNAVAILABLE` instead of `CLEAR` for a current operational claim.

## Carriage-level manifest

Create or replace the complete manifest for a schedule:

```text
PUT /api/v1/planner/schedules/{schedule_id}/consist
```

Each carriage must be listed in contiguous train order, starting at position
1. The API validates that:

```text
gross_weight = tare_weight + cargo_weight
```

and derives total gross weight, total length, maximum dimensions, and maximum
axle load. The submitted `manifest_checksum` must match the canonical
position-ordered normalized payload. This checksum proves integrity of the
submitted representation; it does not prove that the underlying source is an
authorized railway document.

## Segment occupation windows

Store the exact time a consist enters and clears each route segment:

```text
PUT /api/v1/planner/schedules/{schedule_id}/occupation-windows
```

The `train_length_m` field must equal the sum of carriage lengths. Occupation
windows are never derived from a hardcoded speed or duration. An importer or
authorized operations feed must supply the times; `expected_speed_kmh` is
optional metadata and is not used as movement authority.

## Track section policy

Ingest an evidence-backed section policy:

```text
PUT /api/v1/planner/track-section-policies/{segment_id}
```

The policy supplies `single_track` and, when applicable,
`minimum_headway_seconds`, together with its source identity. The engine never
invents a headway number.

## Conflict assessment

Assess a schedule against every non-cancelled schedule visible to the
backend-owned network scope:

```text
GET /api/v1/planner/schedules/{schedule_id}/conflicts
```

The result is one of:

- `BLOCKED`: a same-section overlap, opposing single-track movement, or
  minimum-headway violation exists;
- `UNAVAILABLE`: the candidate or network coverage is missing, historical,
  malformed, or lacks a source-backed policy;
- `CLEAR`: all supplied current real-source windows satisfy all supplied
  policies.

`CLEAR` is deliberately stronger than “no overlap found.” If another active
schedule has no occupation windows, or a candidate section has no policy, the
engine returns `UNAVAILABLE` because it cannot prove that another train will
not be interrupted.

Every conflict includes the conflicting train code, segment ID, UTC conflict
interval, required headway, and the policy source reference. This makes the
decision explainable without exposing the raw provider payload.

## Provider boundaries

GTFS, government timetable files, OpenStreetMap geometry, and passenger
tracking APIs may support research and scheduling previews. They do not supply
signal state, axle-counter state, movement authority, certified braking data,
or collision protection. For a live operational claim, configure an
authorized railway/infrastructure-manager feed and retain its timestamps and
checksums. See [DATA_SOURCES_AND_ATTRIBUTION.md](DATA_SOURCES_AND_ATTRIBUTION.md)
and [ONLINE_DEPLOYMENT.md](ONLINE_DEPLOYMENT.md).
