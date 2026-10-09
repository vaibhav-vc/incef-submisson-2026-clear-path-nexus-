# Live data interface contract (for CRIS / Ministry of Railways)

What an authorised source (RTIS, NTES, COA or a CRIS integration service) sends to Clear Path Nexus. The receiving
side is implemented and tested (`india_rail/railguard/livefeed.py`, `tests/test_livefeed.py`). Field names can be
mapped to CRIS's own interface without changing the twin.

## Transport
`POST https://<host>/railguard/national/feed/batch`, JSON body, `Authorization: Bearer <feed role token>`.
Responses: `200` with per-event results; `401` envelope refused (reason in `detail`); `403` wrong role;
`413`/`411` body too large or without length; `422` not JSON; `429` rate limit; `503` keys not configured.

## Envelope
| Field | Type | Rule |
|---|---|---|
| `source` | string | Registered source, e.g. `RTIS`, `NTES`, `COA` (`^[A-Z][A-Z0-9_]{1,15}$`) |
| `key_id` | string | Key identifier for rotation, e.g. `k1` |
| `sent_at` | ISO 8601 with offset | Within ±120 s of the receiver's NTP-synced clock |
| `nonce` | string, 16-64 chars | Unique per envelope (random 128 bits recommended) |
| `sequence` | integer | Strictly increasing per source |
| `events` | array, 1-250 | See below |
| `signature` | hex | HMAC-SHA256 with the source key over the canonical JSON of all other fields |

Canonical JSON = keys sorted, no whitespace (`","` and `":"` separators), UTF-8, non-ASCII not escaped.

## Events
**POSITION** (e.g. RTIS): `train_number`, `start_date` (journey start, `YYYY-MM-DD`), `lat`, `lon` (WGS84),
`speed_kmph` (0-250), `observed_at` (ISO 8601 with offset; no older than 3 minutes, no later than 2 minutes ahead).
Optional receiver quality: `satellites` (integer, at least 4) and `hdop` (above 0, at most 5); a fix below
either is refused. Accuracy is taken as HDOP x 5 m (30 m when HDOP is not sent).

Each fix is map-matched to the track of the train's planned route ahead of its last accepted position: within
max(50 m, 3 x accuracy) of mapped (OpenStreetMap) track, widened to 300 m within 1.5 km of a station (yard
lines), and within 3 km of the straight line on sections with no mapped track. A fix that matches nothing is
refused; if it is 1 km or more from the route, or is the second unmatched fix in a row, a ROUTE_DEVIATION threat
is raised. A matched fix must also be plausible against the train's last accepted fix (no implied speed above
200 km/h, no backward move beyond max(200 m, 3 x accuracy, 300 m in a station zone)); otherwise it is refused
and a GNSS_IMPLAUSIBLE threat is raised. The gateway tallies every fix by outcome (`railguard_gnss_fixes{type=...}`
on `/metrics`), which is how a field trial of cab units is measured.

**STATION** (e.g. NTES/COA): `train_number`, `start_date`, `station_code`, `event` (`ARR` | `DEP` | `PASS`),
`observed_at`. Lateness of 5 minutes or more is recorded as a disruption for the controller; the feed approves
nothing.

## Test vector
Key (hex): `000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f`

Canonical body:
```
{"events":[{"lat":22.30712,"lon":73.18121,"observed_at":"2026-10-07T10:14:52+05:30","speed_kmph":104.0,"start_date":"2026-10-07","train_number":"12951","type":"POSITION"}],"key_id":"k1","nonce":"0123456789abcdef0123456789abcdef","sent_at":"2026-10-07T10:15:00+05:30","sequence":1,"source":"RTIS"}
```
Signature: `8ae2417f1ce117df5593a0fff30e1e2806d6f12a22eb3677a08f2d33139b0886`
(checked by `tests/test_livefeed.py::test_published_signing_test_vector`).

## Onboarding checklist
1. CRIS shares its interface specification; map field names (this document's names are the receiver's).
2. Generate a 32-byte key per source (`python -c "import secrets; print(secrets.token_hex(32))"`), exchange it
   out of band, set `RAILGUARD_FEED_KEYS="RTIS:k1:<hex>,NTES:k1:<hex>"`; rotate by adding `k2` then removing `k1`.
3. Run the feed in a test environment with the signed simulator (`FeedSimulator`) and with CRIS test data;
   confirm acceptance rates and the map-matching tolerance on real GNSS traces.
4. Set `RAILGUARD_LIVE_CLOCK=1` so the twin follows Indian Standard Time; keep both clocks on NIC/NPL NTP.
5. Start the shadow trial (`SHADOW_TRIAL_PLAN.md`).

## Behaviour verified on real running data
A real morning (24 September 2024) was replayed through the gateway: every actual arrival sent as a signed
STATION event at its real time (`python -m india_rail real validate`, `live_feed_replay`). This changed the gateway:
* a report is matched from the run's **last accepted observation**, never from the timetable projection (a late
  train that has not reported yet is projected ahead of where it really is);
* a report for a station **behind** the last accepted one is refused as out of order: a train is never moved back;
* threats are re-evaluated **once per batch**, after all its events (about 0.1 s per one-minute batch at national
  scale over a whole morning);
* the origin of a journey is reported as a departure (`DEP`), not an arrival.
CRIS should confirm ordering guarantees per train and whether corrections are sent as new events.


## What the feed drives for passengers, customers and staff
Accepted reports move the twin, and the twin's projection is published as expected times (viewer role):
* `GET /railguard/national/expected/{run}`: every stop of a run, scheduled and expected arrival and departure,
  status (`LATE N MIN`, `ON TIME`, `SCHEDULED`, `DUE`, `ARRIVED`, `DEPARTED`), the likely arrival range where the
  forecaster gives one, and the evidence behind it (`LIVE`, `LAST_REPORT` with its age and section, `TIMETABLE`);
* `GET /railguard/national/board/{code}?window=30-360&rows=1-100`: the trains due at a station, soonest first,
  including late trains scheduled earlier and diverted trains no longer calling there; page `/board`.
Times are published under rules that avoid needless changes (`railguard/publish.py`, hazard H24): later at once,
earlier only once held for 3 minutes, no change under 2 minutes, never departing before the timetable. So the
feed does not need to smooth anything: send every report as it is made, and corrections as new events.
NTES remains the official passenger information; these endpoints can feed station displays or enquiry staff
only with CRIS/NTES agreement on wording and hand-off.
