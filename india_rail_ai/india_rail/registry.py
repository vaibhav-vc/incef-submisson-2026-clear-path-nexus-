"""Every train and station, with the real track each train follows.

Reads the current timetable database (`python -m india_rail current build`, then `real osm --db current` and
`current pins`). A train's route is the chain of real mapped track paths (OpenStreetMap) of its sections; a
section without an accepted mapped path is drawn straight between its stations and says so.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from india_rail.current import CURRENT_DB_PATH
from india_rail.network import clock

OPERATOR_GROUPS = ("IRCTC (private operation)", "Bharat Gaurav (service provider operated)", "Luxury tourist train",
                   "Parcel / cargo", "Rapid rail")  # fmt: skip


class Registry:
    def __init__(self, db: Path = CURRENT_DB_PATH):
        if not db.exists():
            raise FileNotFoundError(f"{db} not built: run python -m india_rail current build")
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    # ---- trains -------------------------------------------------------------------------------------------
    def search(self, q: str = "", operator: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        like = f"%{q.strip().upper()}%"
        return self._rows(
            "SELECT number, name, type, operator, running_days, in_twin, real_running_observed, note "
            "FROM train_registry WHERE (number LIKE ? OR UPPER(name) LIKE ?) AND (? IS NULL OR operator = ?) "
            "ORDER BY number LIMIT ?",
            (like, like, operator, operator, max(1, min(limit, 500))),
        )

    def operators(self) -> dict[str, Any]:
        counts = self._rows("SELECT operator, COUNT(*) AS trains FROM train_registry WHERE in_current_2026 = 1 "
                            "GROUP BY operator ORDER BY trains DESC")  # fmt: skip
        special = self._rows(
            "SELECT number, name, operator, running_days FROM train_registry WHERE in_current_2026 = 1 AND operator IN "
            f"({','.join('?' * len(OPERATOR_GROUPS))}) ORDER BY operator, number",  # nosec B608 - placeholders only
            OPERATOR_GROUPS,
        )
        return {"by_operator": counts, "private_tourist_and_parcel_trains": special}

    def train(self, number: str) -> dict[str, Any] | None:
        reg = self._rows("SELECT * FROM train_registry WHERE number = ?", (number,))
        if not reg:
            return None
        stops = self._rows(
            "SELECT s.seq, s.station_code AS code, st.name, st.zone, st.state, p.pin, p.source AS pin_source, "
            "s.arr_min, s.dep_min, s.dwell_min, st.lat, st.lon FROM stops s "
            "JOIN stations st ON st.code = s.station_code LEFT JOIN station_pin p ON p.code = s.station_code "
            "WHERE s.train_number = ? ORDER BY s.seq",
            (number,),
        )
        for s in stops:
            s["arrival"], s["departure"] = clock(s.pop("arr_min")), clock(s.pop("dep_min"))
        route = self.route(number)
        return {**reg[0], "stops": stops, "route_summary": route["properties"] if route else None}

    def route(self, number: str) -> dict[str, Any] | None:
        """GeoJSON LineString of the train's path along real track, with per-section evidence."""

        sections = self._rows(
            "SELECT seq, from_code, to_code FROM sections WHERE train_number = ? ORDER BY seq", (number,)
        )
        if not sections:
            return None
        coords: list[list[float]] = []
        mapped_km = straight_km = 0.0
        single_km = electrified_km = 0.0
        evidence = []
        for sec in sections:
            a, b = sec["from_code"], sec["to_code"]
            path, info = _section_path(self, a, b)
            if info.get("osm_km"):
                mapped_km += info["osm_km"]
                single_km += info["osm_km"] if info.get("lines") == 1 else 0.0
                electrified_km += info["osm_km"] * (info.get("electrified_share") or 0.0)
            else:
                straight_km += info.get("straight_km", 0.0)
            evidence.append({"from": a, "to": b, "track": "MAPPED" if info.get("osm_km") else "STRAIGHT_LINE"})
            coords.extend(path[1:] if coords else path)
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "train": number,
                "sections": len(sections),
                "sections_on_mapped_track": sum(1 for e in evidence if e["track"] == "MAPPED"),
                "mapped_track_km": round(mapped_km, 1),
                "unmapped_straight_line_km": round(straight_km, 1),
                "single_line_km": round(single_km, 1),
                "electrified_km": round(electrified_km, 1),
                "evidence": evidence,
                "attribution": "Track geometry (c) OpenStreetMap contributors, ODbL",
            },
        }

    # ---- stations -----------------------------------------------------------------------------------------
    def station(self, code: str) -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT st.code, st.name, st.zone, st.state, st.lat, st.lon, p.pin, p.source AS pin_source, "
            "o.located_by FROM stations st LEFT JOIN station_pin p ON p.code = st.code "
            "LEFT JOIN osm_stations o ON o.code = st.code WHERE st.code = ?",
            (code,),
        )
        if not rows:
            return None
        calls = self._rows(
            "SELECT s.train_number AS number, r.name, r.operator, s.arr_min, s.dep_min FROM stops s "
            "JOIN train_registry r ON r.number = s.train_number WHERE s.station_code = ? ORDER BY s.dep_min % 1440",
            (code,),
        )
        for c in calls:
            c["arrival"], c["departure"] = clock(c.pop("arr_min")), clock(c.pop("dep_min"))
        return {**rows[0], "trains_calling": len(calls), "trains": calls}


@lru_cache(maxsize=1)
def registry() -> Registry:
    return Registry()


def _section_path(reg: Registry, a: str, b: str) -> tuple[list[list[float]], dict[str, Any]]:
    edge = f"{a}-{b}" if a < b else f"{b}-{a}"
    rows = reg._rows("SELECT osm_km, lines, electrified_share, geometry FROM osm_sections "
                     "WHERE edge = ? AND quality = 'ACCEPTED'", (edge,))  # fmt: skip
    if rows and rows[0]["geometry"]:
        path = json.loads(rows[0]["geometry"])
        return (path if a < b else path[::-1]), rows[0]
    ends = reg._rows("SELECT code, lat, lon FROM stations WHERE code IN (?, ?)", (a, b))
    pos = {r["code"]: [r["lon"], r["lat"]] for r in ends if r["lat"] is not None}
    if a in pos and b in pos:
        from india_rail.ingest import haversine_km

        km = haversine_km(pos[a][1], pos[a][0], pos[b][1], pos[b][0])
        return [pos[a], pos[b]], {"straight_km": km}
    return [], {}
