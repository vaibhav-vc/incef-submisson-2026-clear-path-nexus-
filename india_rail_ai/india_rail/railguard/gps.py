"""GPS / GNSS tracking: receiver sentences, quality gates, map-matching onto real track, plausibility checks.

A loco or cab unit with a GNSS receiver (GPS, GLONASS, Galileo, BeiDou or India's NavIC) produces NMEA 0183
sentences. This module turns them into checked positions on the train's route:

1. parse    - GGA (fix quality, satellites, HDOP) and RMC (validity, position, speed, course, date) with
              checksum verification; any talker (GP, GN, GL, GA, GB/BD, GI = NavIC);
2. gate     - no fix, too few satellites, poor geometry (HDOP), an old fix or an impossible speed is refused;
3. match    - the fix is projected onto the *mapped track* (OpenStreetMap geometry) of the sections the train
              is planned to use next; it must lie within max(50 m, 3 x estimated accuracy) of the track.
              Where a section has no mapped track the straight station-to-station line is used with a 3 km
              tolerance and the match is labelled STRAIGHT_LINE;
4. plausibility - against the train's previous accepted fix: no backwards movement beyond the error
              allowance and no implied speed above the limit (a jump is spoofing or multipath, never a move).

Nothing here gives movement authority. A refused fix leaves the train's last evidence to age into HOLD.
"""

from __future__ import annotations

import bisect
import itertools
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

UERE_M = 5.0  # user equivalent range error: accuracy ~ HDOP x UERE (consumer receiver, open sky)
MIN_SATELLITES = 4
MAX_HDOP = 5.0
MAX_AGE_S = 30
MAX_SPEED_KMPH = 200.0  # above any Indian Railways line speed: a higher implied speed is a jump
MATCH_FLOOR_M = 50.0
STRAIGHT_LINE_TOLERANCE_M = 3000.0
BACKWARD_ALLOWANCE_M = 200.0
TALKERS = {"GP", "GN", "GL", "GA", "GB", "BD", "GI", "GQ"}


class NmeaError(ValueError):
    """A sentence that is malformed, fails its checksum or carries no usable data."""


def _checksum_ok(sentence: str) -> bool:
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, given = sentence[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return given[:2].upper() == f"{calc:02X}"


def _coord(value: str, hemi: str, degrees: int) -> float:
    if not value:
        raise NmeaError("empty coordinate")
    d, m = float(value[:degrees]), float(value[degrees:])
    if not (0 <= m < 60):
        raise NmeaError("minutes out of range")
    out = d + m / 60
    return -out if hemi in ("S", "W") else out


def parse_nmea(sentence: str) -> dict[str, Any]:
    """One NMEA 0183 sentence (GGA or RMC) -> fields. Raises NmeaError otherwise."""

    sentence = sentence.strip()
    if len(sentence) > 120 or not _checksum_ok(sentence):
        raise NmeaError("bad checksum or not an NMEA sentence")
    fields = sentence[1:].split("*")[0].split(",")
    talker, kind = fields[0][:2], fields[0][2:]
    if talker not in TALKERS:
        raise NmeaError(f"unknown talker {talker}")
    try:
        if kind == "GGA":
            quality = int(fields[6] or 0)
            out = {"type": "GGA", "talker": talker, "utc": fields[1], "quality": quality,
                   "satellites": int(fields[7] or 0), "hdop": float(fields[8] or 99)}  # fmt: skip
            if quality > 0:
                out.update(lat=_coord(fields[2], fields[3], 2), lon=_coord(fields[4], fields[5], 3))
            return out
        if kind == "RMC":
            course = float(fields[8]) if fields[8] else None
            out = {"type": "RMC", "talker": talker, "utc": fields[1], "valid": fields[2] == "A", "date": fields[9],
                   "speed_kmph": float(fields[7] or 0) * 1.852, "course": course}  # fmt: skip
            if out["valid"]:
                out.update(lat=_coord(fields[3], fields[4], 2), lon=_coord(fields[5], fields[6], 3))
            return out
    except (IndexError, ValueError) as exc:
        raise NmeaError(f"malformed {kind}: {exc}") from exc
    raise NmeaError(f"unsupported sentence {kind}")


@dataclass
class GpsFix:
    when: datetime  # UTC
    lat: float
    lon: float
    speed_kmph: float
    hdop: float
    satellites: int
    course: float | None = None

    @property
    def accuracy_m(self) -> float:
        return self.hdop * UERE_M


class FixBuilder:
    """Pairs the RMC (position, speed, date) and GGA (satellites, HDOP) of the same second, in either order.

    A receiver that sends no GGA produces no fixes: without satellites and HDOP a fix cannot be quality-gated."""

    def __init__(self) -> None:
        self.gga: dict[str, Any] | None = None
        self.rmc: dict[str, Any] | None = None

    def feed(self, sentence: str) -> GpsFix | None:
        data = parse_nmea(sentence)
        if data["type"] == "GGA":
            self.gga = data
        else:
            self.rmc = data
        rmc, gga = self.rmc, self.gga
        if rmc is None or gga is None or rmc["utc"] != gga["utc"]:
            return None
        self.rmc = self.gga = None
        if not rmc["valid"] or gga["quality"] == 0:
            return None
        try:
            when = _utc(rmc["date"], rmc["utc"])
        except (ValueError, IndexError) as exc:
            raise NmeaError(f"bad date/time: {exc}") from exc
        return GpsFix(when, rmc["lat"], rmc["lon"], rmc["speed_kmph"], gga["hdop"], gga["satellites"], rmc["course"])


def _utc(ddmmyy: str, hhmmss: str) -> datetime:
    day = date(2000 + int(ddmmyy[4:6]), int(ddmmyy[2:4]), int(ddmmyy[0:2]))
    sec = float(hhmmss[4:])
    return datetime.combine(day, time(int(hhmmss[0:2]), int(hhmmss[2:4]), int(sec)), UTC)


def quality_problem(fix: GpsFix, now: datetime) -> str | None:
    """Why a fix must not be used (None = usable)."""

    if fix.satellites < MIN_SATELLITES:
        return f"only {fix.satellites} satellites"
    if fix.hdop > MAX_HDOP:
        return f"HDOP {fix.hdop} above {MAX_HDOP}"
    age = (now - fix.when).total_seconds()
    if age > MAX_AGE_S or age < -5:
        return f"fix age {age:.0f} s"
    if not 0 <= fix.speed_kmph <= MAX_SPEED_KMPH:
        return f"speed {fix.speed_kmph:.0f} km/h"
    if not (6.0 <= fix.lat <= 37.5 and 68.0 <= fix.lon <= 97.5):
        return "outside India"
    return None


# ---- map-matching onto real track ------------------------------------------------------------------------------
STATION_ZONE_M = 1500.0  # within this distance of a station the train may be on any line of the yard
STATION_YARD_M = 300.0  # ... so the cross-track allowance widens to this


@dataclass
class Match:
    index: int  # section index on the run's plan
    section_id: str
    offset_km: float  # from the section's start in the direction of travel
    cross_track_m: float
    method: str  # MAPPED_TRACK or STRAIGHT_LINE
    in_station_zone: bool = False  # within STATION_ZONE_M of either end of the section (platforms, yard lines)
    chainage_m: float = 0.0  # distance along the run's planned route from its origin


class Polyline:
    """A section's track as [lon, lat] points with cumulative metres, for projection and interpolation."""

    def __init__(self, points: list[tuple[float, float]]):
        self.points = points
        self.cum = [0.0]
        for (x1, y1), (x2, y2) in itertools.pairwise(points):
            mx = 111320.0 * math.cos(math.radians((y1 + y2) / 2))
            self.cum.append(self.cum[-1] + math.hypot((x2 - x1) * mx, (y2 - y1) * 110574.0))

    @property
    def length_m(self) -> float:
        return self.cum[-1]

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        return _project(self.points, lon, lat)

    def candidates(self, lon: float, lat: float, limit_m: float) -> list[tuple[float, float]]:
        """Every place the track passes within `limit_m` of the point, as (cross-track m, along m).

        A curve that doubles back (a horseshoe or ghat loop) passes the same spot more than once; the caller
        picks the pass that fits where the train should be."""

        mx, my = 111320.0 * math.cos(math.radians(lat)), 110574.0
        out: list[tuple[float, float]] = []
        for k, ((x1, y1), (x2, y2)) in enumerate(zip(self.points, self.points[1:], strict=False)):
            ax, ay, bx, by = (x1 - lon) * mx, (y1 - lat) * my, (x2 - lon) * mx, (y2 - lat) * my
            sx, sy = bx - ax, by - ay
            seg2 = sx * sx + sy * sy
            t = 0.0 if seg2 == 0 else min(max(-(ax * sx + ay * sy) / seg2, 0.0), 1.0)
            cross = math.hypot(ax + t * sx, ay + t * sy)
            if cross <= limit_m:
                along = self.cum[k] + t * (self.cum[k + 1] - self.cum[k])
                if out and abs(out[-1][1] - along) < 1.0:  # the shared vertex of two segments: one place
                    out[-1] = min(out[-1], (cross, along))
                else:
                    out.append((cross, along))
        return out

    def point_at(self, along_m: float) -> tuple[float, float]:
        along = min(max(along_m, 0.0), self.cum[-1])
        k = min(max(bisect.bisect_right(self.cum, along) - 1, 0), len(self.points) - 2)
        seg = self.cum[k + 1] - self.cum[k]
        f = 0.0 if seg <= 0 else (along - self.cum[k]) / seg
        (x1, y1), (x2, y2) = self.points[k], self.points[k + 1]
        return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f


@dataclass
class TrackMatcher:
    """Projects fixes onto the mapped track of a twin's sections (geometry from OpenStreetMap)."""

    twin: Any
    _cache: dict[str, Polyline | None] = field(default_factory=dict)

    def geometry(self, sid: str) -> Polyline | None:
        """The section's mapped track in the section id's own order (A-B), or None where it is not mapped."""

        if sid not in self._cache:
            info = self.twin.data.infrastructure.get(sid) or {}
            raw = info.get("geometry")
            points = [(float(p[0]), float(p[1])) for p in json.loads(raw)] if raw else []
            self._cache[sid] = Polyline(points) if len(points) >= 2 else None
        return self._cache[sid]

    def line(self, frm: str, to: str, sid: str) -> tuple[Polyline, str]:
        """The track from `frm` to `to`: mapped where available, else the straight station-to-station line."""

        geom = self.geometry(sid)
        if geom is not None:
            if sid.split("-", 1)[0] == frm:
                return geom, MAPPED_TRACK
            key = f"{sid}~reversed"
            if key not in self._cache:
                self._cache[key] = Polyline(geom.points[::-1])
            return self._cache[key], MAPPED_TRACK  # type: ignore[return-value]
        nodes = self.twin.net.nodes
        return Polyline([tuple(nodes[frm]), tuple(nodes[to])]), STRAIGHT_LINE

    def candidates(
        self, key: str, lon: float, lat: float, accuracy_m: float, indices: range
    ) -> tuple[list[Match], float]:
        """Every place on the run's plan (sections `indices`) the fix may be, and the nearest cross-track distance.

        Mapped track: within max(50 m, 3 x accuracy), widened to the yard width near stations. A route that
        passes the same spot twice, or a curve that doubles back, gives more than one place."""

        plan = self.twin.plan_of(key)
        tolerance = max(MATCH_FLOOR_M, 3 * accuracy_m)
        lengths = [self.twin.section(sid).length_km for sid in plan.sections]
        out: list[Match] = []
        nearest = math.inf
        base = sum(lengths[: max(indices.start, 0)])
        for i in range(max(indices.start, 0), min(indices.stop, len(plan.sections))):
            line, method = self.line(plan.frm[i], plan.to[i], plan.sections[i])
            closest = line.project(lon, lat)
            nearest = min(nearest, closest[0])
            if method == STRAIGHT_LINE:
                # Alongside the straight station line, with slack for curves; beyond its ends only in the station.
                beside = 1.0 < closest[1] < line.length_m - 1.0  # (metres: the foot is not clamped to an end)
                found = [closest] if closest[0] <= (STRAIGHT_LINE_TOLERANCE_M if beside else STATION_ZONE_M) else []
            else:
                found = [c for c in line.candidates(lon, lat, max(tolerance, STATION_YARD_M))
                         if c[0] <= tolerance or min(c[1], line.length_m - c[1]) <= STATION_ZONE_M]  # fmt: skip
            for cross, along in found:
                offset = (min(along / line.length_m, 1.0) if line.length_m > 0 else 0.0) * lengths[i]
                zone = method == MAPPED_TRACK and min(along, line.length_m - along) <= STATION_ZONE_M
                out.append(Match(i, plan.sections[i], round(offset, 3), round(cross, 1), method, zone,
                                 (base + offset) * 1000))  # fmt: skip
            base += lengths[i]
        return out, nearest

    def match(self, key: str, lon: float, lat: float, accuracy_m: float, indices: range) -> tuple[Match | None, float]:
        """The nearest place on the run's plan for the fix (no history), and the nearest cross-track distance."""

        found, nearest = self.candidates(key, lon, lat, accuracy_m, indices)
        return min(found, key=lambda m: m.cross_track_m, default=None), nearest

    def lonlat(self, frm: str, to: str, sid: str, share: float) -> tuple[float, float]:
        """Point a share (0-1) of the way from `frm` to `to` along the track."""

        line, _ = self.line(frm, to, sid)
        return line.point_at(min(max(share, 0.0), 1.0) * line.length_m)


MAPPED_TRACK, STRAIGHT_LINE = "MAPPED_TRACK", "STRAIGHT_LINE"


def _project(line: list[tuple[float, float]], lon: float, lat: float) -> tuple[float, float]:
    """Cross-track distance (m) from a point to a polyline, and the distance along it (m) to the foot."""

    mx, my = 111320.0 * math.cos(math.radians(lat)), 110574.0
    best_cross, best_along, run = math.inf, 0.0, 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(line):
        ax, ay, bx, by = (x1 - lon) * mx, (y1 - lat) * my, (x2 - lon) * mx, (y2 - lat) * my
        sx, sy = bx - ax, by - ay
        seg = math.hypot(sx, sy)
        t = 0.0 if seg == 0 else min(max(-(ax * sx + ay * sy) / (seg * seg), 0.0), 1.0)
        cross = math.hypot(ax + t * sx, ay + t * sy)
        if cross < best_cross:
            best_cross, best_along = cross, run + t * seg
        run += seg
    return best_cross, best_along


@dataclass
class Track:
    """The last accepted position of one run (for plausibility of the next fix).

    Where the fix fitted more than one place on the route (track passing the same spot twice), the train is at
    one of `places` - each a point, never the stretch between them - and the next fixes tell which."""

    when: datetime
    chainage_m: float  # the earliest place
    places: tuple[float, ...] = ()  # every place the train may be, when more than one
    first_index: int = 0  # plan section of the earliest place (where the next match starts)

    def all(self) -> tuple[float, ...]:
        return self.places or (self.chainage_m,)


def chainage_m(twin: Any, key: str, index: int, offset_km: float) -> float:
    """Distance (m) along the run's planned route from its origin to a point on section `index`."""

    plan = twin.plan_of(key)
    before = sum(twin.section(plan.sections[i]).length_km for i in range(index))
    return (before + offset_km) * 1000


def plausibility_problem(
    prev: Track | None, when: datetime, position_m: float, accuracy_m: float, in_station_zone: bool = False
) -> str | None:
    """Why a matched fix cannot be the same train's next position (None = plausible).

    A train does not run backwards along its route (beyond the error allowance) and cannot cover more ground
    than MAX_SPEED_KMPH allows: either is a jump (spoofing, multipath, a wrong train number), never a move.
    In a station zone the allowance is the yard width: where a station's lines join, the mapped paths of the
    sections either side do not meet at one point."""

    if prev is None:
        return None
    dt = (when - prev.when).total_seconds()
    if dt <= 0:
        return "fix not newer than the last accepted one"
    allowance = max(BACKWARD_ALLOWANCE_M, 3 * accuracy_m, STATION_YARD_M if in_station_zone else 0.0)
    reach = MAX_SPEED_KMPH / 3.6 * dt + allowance
    moves = [position_m - place for place in prev.all()]
    if any(-allowance <= moved <= reach for moved in moves):
        return None  # a plausible move from one of the places the train may have been
    moved = min(moves, key=abs)
    if moved < 0:
        return f"moved {-moved:.0f} m backwards along the route"
    return f"implied speed {moved / dt * 3.6:.0f} km/h over {dt:.0f} s: a jump, not a move"


def locate(
    prev: Track | None, when: datetime, found: list[Match], accuracy_m: float, speed_kmph: float
) -> tuple[Match | None, Track | None, str | None]:
    """Choose where a fix puts the train: (place, new track, None) or (None, None, why it is implausible).

    Only places consistent with the last accepted position count. Among them, the one nearest where the train
    should be (last position moved on at the reported speed) is reported, and all of them bound the new track."""

    plausible = [
        m for m in found if plausibility_problem(prev, when, m.chainage_m, accuracy_m, m.in_station_zone) is None
    ]
    if not plausible:
        nearest = min(found, key=lambda m: m.cross_track_m)
        return None, None, plausibility_problem(prev, when, nearest.chainage_m, accuracy_m, nearest.in_station_zone)
    # Only places about as close to the fix as the closest one: a straight station line kilometres away is not
    # an alternative to mapped track the fix lies on.
    closest = min(m.cross_track_m for m in plausible)
    plausible = [m for m in plausible if m.cross_track_m <= closest + max(MATCH_FLOOR_M, 3 * accuracy_m)]
    if prev is None:
        best = min(plausible, key=lambda m: m.cross_track_m)
    else:
        step = max(speed_kmph, 0.0) / 3.6 * (when - prev.when).total_seconds()
        expected = [place + step for place in prev.all()]
        best = min(plausible, key=lambda m: (min(abs(m.chainage_m - e) for e in expected), m.cross_track_m))
    earliest = min(plausible, key=lambda m: m.chainage_m)
    places = tuple(sorted({round(m.chainage_m, 1) for m in plausible}))
    return best, Track(when, earliest.chainage_m, places if len(places) > 1 else (), earliest.index), None


def nmea_sentence(kind: str, fix: GpsFix, talker: str = "GN") -> str:
    """Build a valid NMEA sentence for a fix (used by the device agent's self-test and the test-suite)."""

    def dm(value: float, width: int) -> str:
        d = int(abs(value))
        return f"{d:0{width}d}{(abs(value) - d) * 60:07.4f}"

    hhmmss = fix.when.strftime("%H%M%S") + ".00"
    ns, ew = ("N" if fix.lat >= 0 else "S"), ("E" if fix.lon >= 0 else "W")
    if kind == "GGA":
        body = (
            f"{talker}GGA,{hhmmss},{dm(fix.lat, 2)},{ns},{dm(fix.lon, 3)},{ew},1,{fix.satellites:02d},"
            f"{fix.hdop:.1f},100.0,M,,M,,"
        )
    else:
        course = "" if fix.course is None else f"{fix.course:.1f}"
        body = (f"{talker}RMC,{hhmmss},A,{dm(fix.lat, 2)},{ns},{dm(fix.lon, 3)},{ew},{fix.speed_kmph / 1.852:.1f},"
                f"{course},{fix.when.strftime('%d%m%y')},,,A")  # fmt: skip
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return f"${body}*{calc:02X}"


def ist(when: datetime) -> datetime:
    return when.astimezone(UTC) + timedelta(hours=5, minutes=30)
