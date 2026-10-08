"""Verify GNSS tracking on the real network: every running train, real mapped track, simulated receivers.

No live GNSS feed from Indian Railways is available to this project, so the *receivers* are simulated; the
network, the timetable (every train of the current timetable) and the track geometry (OpenStreetMap) are real.
For `rounds` consecutive minutes, every running train reports one fix:

* genuine fixes  - on the train's position along the mapped track, with receiver noise drawn per fix from a
                   realistic HDOP (0.6-2.5, x 5 m UERE) and 2 % multipath outliers of 30-80 m;
* off-track      - a sample displaced 500 m at right angles to the track (a wrong line, a road, a spoofer);
* jump           - a sample placed 15 km further along the train's own route one minute later (spoofing);
* teleport       - a sample moved to a random point in India.

Measured: share of genuine fixes accepted (and why any were refused), share of each attack refused, and
gateway throughput. Written to seva2026/evidence/gnss/gnss_verification.json.
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from india_rail.railguard import gps
from india_rail.railguard.livefeed import IST, MAX_EVENTS, FeedGateway, FeedSimulator

SECRET = bytes(range(32))
EVIDENCE = Path(__file__).resolve().parents[2] / "seva2026" / "evidence" / "gnss" / "gnss_verification.json"


def _ahead(twin: Any, matcher: gps.TrackMatcher, key: str, metres: float) -> tuple[float, float] | None:
    """Point `metres` further along the run's planned route than its current projected position."""

    plan, pos = twin.plan_of(key), twin.position(key)
    i, left = pos["index"], metres / 1000 + pos.get("offset_km", 0.0)  # at a station: from its departure
    while i < len(plan.sections):
        length = twin.section(plan.sections[i]).length_km
        if left <= length:
            return matcher.lonlat(plan.frm[i], plan.to[i], plan.sections[i], left / max(length, 1e-6))
        left -= length
        i += 1
    return None


def _sideways(twin: Any, matcher: gps.TrackMatcher, key: str, metres: float) -> tuple[float, float] | None:
    pos = twin.position(key)
    if pos["section_id"] is None:
        return None
    line, _ = matcher.line(pos["from_node"], pos["to_node"], pos["section_id"])
    along = pos["offset_km"] / max(twin.section(pos["section_id"]).length_km, 1e-6) * line.length_m
    (x1, y1), (x2, y2) = line.point_at(along - 50), line.point_at(along + 50)
    lon, lat = line.point_at(along)
    mx = 111320.0 * math.cos(math.radians(lat))
    dx, dy = (x2 - x1) * mx, (y2 - y1) * 110574.0
    norm = math.hypot(dx, dy) or 1.0
    return lon + (-dy / norm) * metres / mx, lat + (dx / norm) * metres / 110574.0


def verify(rounds: int = 10, start_min: float = 600.0, attack_share: float = 0.05, seed: int = 0) -> dict[str, Any]:
    from india_rail.railguard.national import NationalTwin

    rng = random.Random(seed)  # nosec B311 - simulated receivers, not security
    twin = NationalTwin(start_min=start_min)
    day = date.today()
    now = [datetime.combine(day, datetime.min.time(), IST).timestamp() + start_min * 60]
    gateway = FeedGateway(twin, {("GNSS", "k1"): SECRET}, service_date=day, clock=lambda: now[0])
    sim = FeedSimulator(gateway, "GNSS", "k1", SECRET, seed=seed)
    matcher = gateway.matcher
    genuine = {"sent": 0, "accepted": 0, "on_mapped_track": 0, "refused": {}}
    attacks = {k: {"sent": 0, "refused": 0} for k in ("off_track_500m", "jump_15km_in_60s", "teleport")}
    events_total, seconds = 0, 0.0
    for r in range(rounds):
        if r:
            twin.tick(1)
            now[0] += 60
        running = twin.running()
        events: list[tuple[str, dict[str, Any]]] = []
        for key in running:
            hdop = round(rng.uniform(0.6, 2.5), 1)
            noise = hdop * gps.UERE_M / math.sqrt(2)
            event = sim.position_event(key, noise_m=noise, hdop=hdop, satellites=rng.randint(6, 20))
            if event is None:
                continue
            if rng.random() < 0.02:  # multipath: a reflected signal pulls the fix 30-80 m
                bearing, size = rng.uniform(0, 2 * math.pi), rng.uniform(30, 80)
                event["lat"] += size * math.sin(bearing) / 110574.0
                event["lon"] += size * math.cos(bearing) / (111320.0 * math.cos(math.radians(event["lat"])))
            kind = "genuine"
            if r and rng.random() < attack_share:
                kind = rng.choice(list(attacks))
                if kind == "off_track_500m":
                    point = _sideways(twin, matcher, key, 500 * rng.choice((-1, 1)))
                elif kind == "jump_15km_in_60s":
                    point = _ahead(twin, matcher, key, 15000)
                else:
                    point = (rng.uniform(70, 95), rng.uniform(8, 34))
                if point is None:
                    kind = "genuine"
                else:
                    event["lon"], event["lat"] = round(point[0], 6), round(point[1], 6)
            events.append((kind, event))
        for k in range(0, len(events), MAX_EVENTS):
            chunk = events[k : k + MAX_EVENTS]
            started = time.perf_counter()
            results = gateway.receive(sim.envelope([e for _, e in chunk]))["results"]
            seconds += time.perf_counter() - started
            events_total += len(chunk)
            for (kind, _event), res in zip(chunk, results, strict=True):
                if kind == "genuine":
                    genuine["sent"] += 1
                    if res["accepted"]:
                        genuine["accepted"] += 1
                        genuine["on_mapped_track"] += res.get("matched_to") == gps.MAPPED_TRACK
                    else:
                        reason = res.get("reason", "")
                        reason = "off route" if "from the planned route" in reason else reason.split(":")[0][:60]
                        genuine["refused"][reason] = genuine["refused"].get(reason, 0) + 1
                else:
                    attacks[kind]["sent"] += 1
                    attacks[kind]["refused"] += not res["accepted"]
    for a in attacks.values():
        a["refused_pct"] = round(100 * a["refused"] / max(a["sent"], 1), 2)
    genuine["accepted_pct"] = round(100 * genuine["accepted"] / max(genuine["sent"], 1), 3)
    genuine["on_mapped_track_pct"] = round(100 * genuine["on_mapped_track"] / max(genuine["accepted"], 1), 1)
    return {
        "what": __doc__.split("\n\n")[0],
        "data": {
            "timetable_trains": len({k.split("@")[0] for k in twin.runs}),
            "rounds_minutes": rounds,
            "start": (datetime.combine(day, datetime.min.time()) + timedelta(minutes=start_min)).strftime("%H:%M"),
            "sections_with_mapped_track": sum(1 for v in twin.data.infrastructure.values() if v.get("geometry")),
            "sections": len(twin.net.sections),
        },  # fmt: skip
        "genuine_fixes": genuine,
        "attacks": attacks,
        "throughput": {
            "events": events_total,
            "seconds": round(seconds, 2),
            "events_per_second": round(events_total / max(seconds, 1e-9)),
        },  # fmt: skip
        "labels": [
            "Receivers simulated (no live GNSS access); network, timetable and track geometry are real.",
            "Accuracy model: HDOP x 5 m UERE; field trials with RTIS/cab units must re-measure it.",
        ],  # fmt: skip
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail gnss-verify")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    args = parser.parse_args(argv)
    report = verify(args.rounds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("genuine_fixes", "attacks", "throughput")}, indent=2))
    return 0
