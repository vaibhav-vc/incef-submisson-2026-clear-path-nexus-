"""Authorised live-feed gateway: ready for RTIS / NTES / COA data once access is granted.

No live Indian Railways feed is connected (access is controlled by the Ministry
of Railways / CRIS). This gateway is the integration point, built and tested now
so that only credentials and the field mapping of the authorised interface remain:

* Envelope: {source, key_id, sent_at, nonce, sequence, events[], signature}.
  `signature` = HMAC-SHA256 (hex) of the canonical JSON of every other field
  (sorted keys, no whitespace, UTF-8), with the per-source key in
  RAILGUARD_FEED_KEYS="RTIS:k1:<hex secret>,NTES:k1:<hex secret>".
* Rejected before any event is read: unknown source or key, bad signature,
  `sent_at` outside +/-MAX_SKEW_S of the server clock, a nonce already seen,
  a sequence number not above the last one, more than MAX_EVENTS events.
* Events:
  POSITION {train_number, start_date, lat, lon, speed_kmph, observed_at, [satellites, hdop]} - a GNSS
    fix (e.g. RTIS or a cab unit, see `gps`). A fix with too few satellites or poor geometry (HDOP) is
    refused. It is map-matched onto the *mapped track* (OpenStreetMap) of the train's planned sections,
    within max(50 m, 3 x accuracy), 300 m inside station yards; unmapped sections use the straight
    station line within MATCH_KM. A fix off the route is a route deviation, never silently accepted.
    A fix that implies running backwards or faster than any line speed since the run's last accepted
    position is a jump (spoofing, multipath, wrong train number): refused and flagged GNSS_IMPLAUSIBLE.
  STATION {train_number, start_date, station_code, event ARR|DEP|PASS, observed_at}
    - a station event (e.g. NTES/COA). Lateness of AUTO_DISRUPTION_MIN or more is
    recorded as a disruption for the controller to decide on; the feed never
    approves anything.
* Every batch is written to the audit chain (counts and a SHA-256 of the body).

Times are Indian Standard Time; `start_date` is the train's journey start date.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from india_rail.railguard import gps

IST = timezone(timedelta(hours=5, minutes=30))
MAX_SKEW_S = 120
MAX_EVENTS = 250
MATCH_KM = gps.STRAIGHT_LINE_TOLERANCE_M / 1000  # unmapped sections: straight station line, curves need slack
DEFAULT_ACCURACY_M = 30.0  # a feed that does not state HDOP: assume a modest receiver
DEVIATION_NOW_M = 1000.0  # a fix this far from the route raises a route deviation at once; nearer, only the second
# off-route fix in a row does (one multipath fix must not become a nuisance alarm)
AUTO_DISRUPTION_MIN = 5.0
MIN_SECRET_BYTES = 32
NONCES_KEPT = 100_000
TRAIN = re.compile(r"^[0-9A-Z][0-9A-Z-]{0,15}$")
STATION = re.compile(r"^[A-Z0-9]{1,8}$")
SOURCE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")


class FeedRejected(ValueError):
    """The whole envelope is refused (authentication, freshness, replay or shape)."""


def load_keys(spec: str | None = None) -> dict[tuple[str, str], bytes]:
    spec = os.environ.get("RAILGUARD_FEED_KEYS", "") if spec is None else spec
    keys = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        source, key_id, secret = item.split(":", 2)
        raw = bytes.fromhex(secret)
        if len(raw) < MIN_SECRET_BYTES:
            raise ValueError(f"feed key {source}:{key_id} is shorter than {MIN_SECRET_BYTES} bytes")
        keys[(source, key_id)] = raw
    return keys


def canonical(envelope: dict[str, Any]) -> bytes:
    body = {k: v for k, v in envelope.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(envelope: dict[str, Any], secret: bytes) -> str:
    return hmac.new(secret, canonical(envelope), hashlib.sha256).hexdigest()


def _when(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("timestamp must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a time zone")
    return parsed


class FeedGateway:
    def __init__(
        self,
        twin: Any,
        keys: dict[tuple[str, str], bytes] | None = None,
        service_date: date | None = None,
        clock: Any = time.time,
        auto_disruption_min: float = AUTO_DISRUPTION_MIN,
        follow_clock: bool | None = None,
    ):
        self.twin = twin
        # Live operation: the twin clock follows Indian Standard Time (RAILGUARD_LIVE_CLOCK=1).
        self.follow_clock = os.environ.get("RAILGUARD_LIVE_CLOCK") == "1" if follow_clock is None else follow_clock
        self.keys = load_keys() if keys is None else keys
        self.clock = clock
        # Day 0 of the twin: the date its timetable window starts (IST).
        self.service_date = service_date or datetime.fromtimestamp(clock(), IST).date()
        self.auto_disruption_min = auto_disruption_min
        self.nonces: OrderedDict[str, None] = OrderedDict()
        self.last_sequence: dict[str, int] = {}
        # Section index of each run's last accepted observation: a real report is matched from there on, not
        # from the projection (a late train not yet reported is projected ahead of where it really is).
        self.last_index: dict[str, int] = {}
        # Each run's last accepted position along its route, for the plausibility of the next fix.
        self.tracks: dict[str, gps.Track] = {}
        self.off_route: dict[str, int] = {}  # consecutive off-route fixes per run
        self.matcher = gps.TrackMatcher(twin)

    # ---- envelope ----------------------------------------------------------------------------------
    def receive(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if not self.keys:
            raise FeedRejected("no feed keys configured: live feed disabled")
        if not isinstance(envelope, dict):
            raise FeedRejected("envelope must be a JSON object")
        source, key_id = envelope.get("source"), envelope.get("key_id")
        if not isinstance(source, str) or not SOURCE.match(source) or not isinstance(key_id, str):
            raise FeedRejected("invalid source or key id")
        secret = self.keys.get((source, key_id))
        signature = envelope.get("signature")
        if secret is None or not isinstance(signature, str):
            raise FeedRejected("unknown source/key or missing signature")
        if not hmac.compare_digest(signature, sign(envelope, secret)):
            raise FeedRejected("bad signature")
        try:
            sent = _when(envelope.get("sent_at"))
        except ValueError as exc:
            raise FeedRejected(f"sent_at: {exc}") from exc
        if abs(sent.timestamp() - self.clock()) > MAX_SKEW_S:
            raise FeedRejected("sent_at outside the accepted clock window (stale or replayed)")
        nonce, sequence = envelope.get("nonce"), envelope.get("sequence")
        if not isinstance(nonce, str) or not 16 <= len(nonce) <= 64:
            raise FeedRejected("nonce must be 16-64 characters")
        if f"{source}:{nonce}" in self.nonces:
            raise FeedRejected("replayed nonce")
        if type(sequence) is not int or sequence <= self.last_sequence.get(source, -1):
            raise FeedRejected("sequence number not increasing")
        events = envelope.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
            raise FeedRejected(f"events must be a list of 1-{MAX_EVENTS}")
        # Authenticated and fresh: remember it before acting, so a crash mid-batch cannot enable a replay.
        self.nonces[f"{source}:{nonce}"] = None
        while len(self.nonces) > NONCES_KEPT:
            self.nonces.popitem(last=False)
        self.last_sequence[source] = sequence

        twin = self.twin
        with twin.lock:
            if self.follow_clock:
                wall = self._minutes(datetime.fromtimestamp(self.clock(), IST))
                if wall > twin.now:
                    twin.tick(wall - twin.now, refresh=False)  # threats are re-evaluated once, below
            results = [self._event(source, event) for event in events]
            accepted = sum(1 for r in results if r["accepted"])
            twin.refresh()  # threats re-evaluated once per batch, after every event is in
            twin.audit.record(
                int(twin.now * 60),
                "FEED_BATCH",
                f"feed:{source}",
                {
                    "key_id": key_id,
                    "sequence": sequence,
                    "events": len(events),
                    "accepted": accepted,
                    "body_sha256": hashlib.sha256(canonical(envelope)).hexdigest(),
                },
            )
        return {"source": source, "sequence": sequence, "accepted": accepted, "rejected": len(events) - accepted,
                "results": results}  # fmt: skip

    # ---- events --------------------------------------------------------------------------------------
    def _event(self, source: str, event: Any) -> dict[str, Any]:
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            kind = event.get("type")
            key = self._run_key(event.get("train_number"), event.get("start_date"))
            minute = self._minutes(_when(event.get("observed_at")))
            if minute > self.twin.now + 2:
                raise ValueError("observed in the future of the twin clock")
            if minute < self.twin.now - 3:
                raise ValueError("observation older than the 3-minute position policy")
            if kind == "POSITION":
                return self._position(source, key, event)
            if kind == "STATION":
                return self._station(source, key, event, minute)
            raise ValueError("type must be POSITION or STATION")
        except (ValueError, TypeError, KeyError) as exc:
            return {"accepted": False, "reason": str(exc)[:200]}

    def _run_key(self, number: Any, start: Any) -> str:
        if not isinstance(number, str) or not TRAIN.match(number):
            raise ValueError("invalid train_number")
        if not isinstance(start, str):
            raise ValueError("start_date required")
        day = (date.fromisoformat(start) - self.service_date).days
        key = f"{number}@{day}"
        if key not in self.twin.runs:
            raise ValueError(f"no timetabled run {key}")
        return key

    def _observed_from(self, key: str, default: int) -> int:
        """Where to match a run's next report: its last accepted observation, while the twin still holds it
        (a twin reset drops the evidence, and with it this memory)."""

        if f"position:{key}" in self.twin.evidence.records:
            return self.last_index.get(key, default)
        self.last_index.pop(key, None)
        self.tracks.pop(key, None)
        return default

    def _minutes(self, when: datetime) -> float:
        midnight = datetime.combine(self.service_date, datetime.min.time(), IST)
        return (when - midnight).total_seconds() / 60

    def _position(self, source: str, key: str, event: dict[str, Any]) -> dict[str, Any]:
        lat, lon = float(event["lat"]), float(event["lon"])
        if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5) or math.isnan(lat + lon):
            raise ValueError("position outside India")
        speed = float(event.get("speed_kmph", 0.0))
        if not 0 <= speed <= 250:
            raise ValueError("speed outside 0-250 km/h")
        accuracy = self._gnss_accuracy(event)
        when = _when(event["observed_at"])
        twin = self.twin
        here = twin.position(key)["index"]
        start = self._observed_from(key, max(here - 3, 0))
        found, nearest = self.matcher.candidates(key, lon, lat, accuracy, range(start, max(here, start) + 8))
        if not found:
            streak = self.off_route[key] = self.off_route.get(key, 0) + 1
            reason = f"fix {nearest / 1000:.2f} km from the planned route's track"
            if nearest < DEVIATION_NOW_M and streak < 2:
                return {
                    "accepted": False,
                    "run": key,
                    "reason": f"{reason} (refused; a second in a row is a deviation)",
                }
            result = twin.ingest_position(key, "UNMATCHED", 0.0, source=f"FEED_{source}", refresh=False)
            return {**result, "run": key, "reason": reason}
        match, track, problem = gps.locate(self.tracks.get(key), when, found, accuracy, speed)
        if match is None or track is None:
            sid = min(found, key=lambda m: m.cross_track_m).section_id
            twin.flags[key] = [f for f in twin.flags[key] if f["type"] != "GNSS_IMPLAUSIBLE"] + [
                {"type": "GNSS_IMPLAUSIBLE", "until": twin.now + 5, "section": sid,
                 "title": "GNSS position implausible - controller review",
                 "detail": f"Fix refused: {problem}. Possible spoofing, multipath or a wrong train number.",
                 "action": "Confirm the train's position through authorised means before relying on it."}]  # fmt: skip
            return {"accepted": False, "run": key, "reason": f"implausible: {problem}"}
        result = twin.ingest_position(key, match.section_id, match.offset_km, source=f"FEED_{source}", refresh=False)
        if result.get("accepted"):
            self.last_index[key] = track.first_index
            self.tracks[key] = track
            self.off_route.pop(key, None)
        out = {**result, "run": key, "section_id": match.section_id, "cross_track_m": match.cross_track_m,
               "matched_to": match.method}  # fmt: skip
        if track.places:
            out["possible_places"] = len(track.places)
        return out

    @staticmethod
    def _gnss_accuracy(event: dict[str, Any]) -> float:
        """Estimated horizontal accuracy (m); refuses a fix whose stated quality is too poor to place a train."""

        sats, hdop = event.get("satellites"), event.get("hdop")
        if sats is not None and (type(sats) is not int or sats < gps.MIN_SATELLITES):
            raise ValueError(f"GNSS: {sats} satellites (minimum {gps.MIN_SATELLITES})")
        if hdop is None:
            return DEFAULT_ACCURACY_M
        hdop = float(hdop)
        if not 0 < hdop <= gps.MAX_HDOP:
            raise ValueError(f"GNSS: HDOP {hdop} outside 0-{gps.MAX_HDOP}")
        return hdop * gps.UERE_M

    def _station(self, source: str, key: str, event: dict[str, Any], minute: float) -> dict[str, Any]:
        station, what = event.get("station_code"), event.get("event")
        if not isinstance(station, str) or not STATION.match(station) or what not in ("ARR", "DEP", "PASS"):
            raise ValueError("invalid station_code or event")
        twin = self.twin
        plan = twin.plan_of(key)
        window = range(self._observed_from(key, 0), len(plan.sections))
        if what == "DEP":
            i = next((i for i in window if plan.frm[i] == station), None)
            planned, offset = (plan.enter[i], 0.0) if i is not None else (None, 0.0)
        else:
            i = next((i for i in window if plan.to[i] == station), None)
            planned = plan.exit[i] if i is not None else None
            offset = twin.section(plan.sections[i]).length_km if i is not None else 0.0
        if i is None:
            behind = any(plan.to[k] == station or plan.frm[k] == station for k in range(window.start))
            if behind:
                raise ValueError(f"{station} is behind the last reported position of {key} (out-of-order report)")
            raise ValueError(f"{station} is not ahead on the planned route of {key}")
        late = minute - planned
        recorded = None
        if late >= self.auto_disruption_min and key not in twin.pending:
            # Departure lateness counts in full; arrival lateness carries to the next departure less a 2-min dwell.
            j = i if what == "DEP" else i + 1
            delay = late if what == "DEP" else late - 2.0
            if j < len(plan.sections) and delay >= 1:
                observed = late if what != "DEP" else None
                twin.disrupt(key, plan.frm[j], min(delay, 720), actor=f"feed:{source}", at_index=j,
                             observed_arrival_delay=observed, refresh=False)  # fmt: skip
                recorded = {"station": plan.frm[j], "delay_min": round(delay, 1)}
        result = twin.ingest_position(
            key, twin.plan_of(key).sections[i], round(offset, 3), source=f"FEED_{source}", refresh=False
        )
        if result.get("accepted"):
            self.last_index[key] = i
            self.tracks[key] = gps.Track(_when(event["observed_at"]), gps.chainage_m(twin, key, i, offset), (), i)
        out = {**result, "run": key, "late_min": round(late, 1)}
        if recorded:
            out["disruption_recorded"] = recorded
        return out


class FeedSimulator:
    """Produces correctly signed envelopes from the twin's own projection (plus optional noise and faults)."""

    def __init__(self, gateway: FeedGateway, source: str, key_id: str, secret: bytes, seed: int = 0):
        import random

        self.gateway, self.source, self.key_id, self.secret = gateway, source, key_id, secret
        self.rng = random.Random(seed)  # nosec B311 - GPS noise for tests only; nonces use `secrets`
        self.sequence = 0

    def envelope(self, events: list[dict[str, Any]], *, sent_at: datetime | None = None) -> dict[str, Any]:
        self.sequence += 1
        sent = sent_at or datetime.fromtimestamp(self.gateway.clock(), IST)
        env = {
            "source": self.source,
            "key_id": self.key_id,
            "sent_at": sent.isoformat(),
            "nonce": secrets.token_hex(16),
            "sequence": self.sequence,
            "events": events,
        }
        env["signature"] = sign(env, self.secret)
        return env

    def position_event(
        self, key: str, noise_m: float = 10.0, hdop: float = 1.2, satellites: int = 12
    ) -> dict[str, Any] | None:
        """A fix on the run's projected position along the mapped track, with receiver noise (metres, 1 sigma)."""

        twin, gw = self.gateway.twin, self.gateway
        lonlat = twin.lonlat(key)
        if lonlat is None:
            return None
        lon, lat = lonlat
        lat += self.rng.gauss(0, noise_m / 110574.0)
        lon += self.rng.gauss(0, noise_m / (111320.0 * math.cos(math.radians(lat))))
        number, day = key.split("@")
        midnight = datetime.combine(gw.service_date, datetime.min.time(), IST)
        return {
            "type": "POSITION",
            "train_number": number,
            "start_date": (gw.service_date + timedelta(days=int(day))).isoformat(),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "speed_kmph": round(twin.position(key).get("speed_kmph", 0.0), 1),
            "satellites": satellites,
            "hdop": hdop,
            "observed_at": (midnight + timedelta(minutes=twin.now)).isoformat(),
        }
