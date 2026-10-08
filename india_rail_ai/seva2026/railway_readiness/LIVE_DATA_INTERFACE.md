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
Map-matched to the train's planned route within 3 km; otherwise a ROUTE_DEVIATION threat is raised.

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

