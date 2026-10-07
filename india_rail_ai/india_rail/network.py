"""Read-only queries over the normalised timetable and the derived station network."""

from __future__ import annotations

import heapq
import sqlite3
from collections import defaultdict
from functools import cached_property
from typing import Any

# Lower value = higher dispatch priority. Indian Railways gives premium
# services precedence; the exact ranking used by a control office is an
# operating rule that must be supplied by the authority, so this is a
# configurable default rather than a fact about any division.
DEFAULT_PRIORITY = {
    "Raj": 1,
    "Shtb": 1,
    "Drnt": 1,
    "JShtb": 2,
    "GR": 2,
    "SKr": 2,
    "Del": 2,
    "SF": 2,
    "Mail": 3,
    "Exp": 3,
    "Hyd": 4,
    "MEMU": 4,
    "DEMU": 4,
    "Pass": 4,  # nosec B105 - "Pass" is the passenger train type, not a password
    "Toy": 5,
}
UNKNOWN_PRIORITY = 3


def clock(minutes: int) -> str:
    """Journey minutes to 'HH:MM (day N)'."""

    day, rem = divmod(int(minutes), 1440)
    return f"{rem // 60:02d}:{rem % 60:02d} (day {day + 1})"


class RailNetwork:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.row_factory = sqlite3.Row

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    # ---- lookups -----------------------------------------------------------
    def station(self, code: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM stations WHERE code = ?", (code.upper(),))
        return rows[0] if rows else None

    def search_stations(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        like = f"%{text.strip()}%"
        # Exact code, then exact name, then the station most trains call at:
        # "Ahmedabad" should find the main junction, not a minor halt.
        return self._rows(
            """
            SELECT code, name, zone, state,
                   (SELECT count(*) FROM stops WHERE stops.station_code = stations.code) AS train_calls
            FROM stations WHERE code = ? OR name LIKE ?
            ORDER BY (code = ?) DESC, (upper(name) = upper(?)) DESC, train_calls DESC, length(name)
            LIMIT ?
            """,
            (text.upper(), like, text.upper(), text.strip(), limit),
        )

    def train(self, number: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM trains WHERE number = ?", (number,))
        return rows[0] if rows else None

    def search_trains(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        like = f"%{text.strip()}%"
        return self._rows(
            "SELECT number, name, type, from_code, to_code, distance_km FROM trains "
            "WHERE number = ? OR name LIKE ? ORDER BY (number = ?) DESC LIMIT ?",
            (text.strip(), like, text.strip(), limit),
        )

    def schedule(self, number: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT seq, station_code, station_name, arr_min, dep_min, dwell_min "
            "FROM stops WHERE train_number = ? ORDER BY seq",
            (number,),
        )
        for row in rows:
            row["arrival"] = clock(row["arr_min"])
            row["departure"] = clock(row["dep_min"])
        return rows

    def trains_between(self, origin: str, destination: str, limit: int = 25) -> list[dict[str, Any]]:
        rows = self._rows(
            """
            SELECT t.number, t.name, t.type, a.dep_min AS depart_min, b.arr_min AS arrive_min,
                   b.arr_min - a.dep_min AS travel_min, b.seq - a.seq AS sections
            FROM stops a
            JOIN stops b ON a.train_number = b.train_number AND b.seq > a.seq
            JOIN trains t ON t.number = a.train_number
            WHERE a.station_code = ? AND b.station_code = ?
            ORDER BY a.dep_min % 1440
            LIMIT ?
            """,
            (origin.upper(), destination.upper(), limit),
        )
        for row in rows:
            row["departs"] = clock(row.pop("depart_min"))
            row["arrives"] = clock(row.pop("arrive_min"))
        return rows

    def station_board(self, code: str, limit: int = 40) -> list[dict[str, Any]]:
        rows = self._rows(
            """
            SELECT t.number, t.name, t.type, s.arr_min, s.dep_min, s.dwell_min
            FROM stops s JOIN trains t ON t.number = s.train_number
            WHERE s.station_code = ? ORDER BY s.dep_min % 1440 LIMIT ?
            """,
            (code.upper(), limit),
        )
        for row in rows:
            row["arrival"] = clock(row.pop("arr_min") % 1440)
            row["departure"] = clock(row.pop("dep_min") % 1440)
        return rows

    # ---- network analytics -------------------------------------------------
    def busiest_sections(self, limit: int = 20, zone: str | None = None) -> list[dict[str, Any]]:
        """Sections ranked by scheduled daily trains (both directions)."""

        # One constant statement: the optional zone filter is a bound parameter too (no SQL is assembled).
        return self._rows(
            """
            SELECT min(s.from_code, s.to_code) AS station_a, max(s.from_code, s.to_code) AS station_b,
                   count(DISTINCT s.train_number) AS trains_per_day,
                   round(avg(s.runtime_min), 1) AS mean_runtime_min,
                   round(avg(s.crow_km), 2) AS straight_line_km
            FROM sections s JOIN trains t ON t.number = s.train_number
            WHERE ? IS NULL OR t.zone = ?
            GROUP BY station_a, station_b
            ORDER BY trains_per_day DESC LIMIT ?
            """,
            (zone, zone, limit),
        )

    @cached_property
    def graph(self) -> dict[str, list[tuple[str, float]]]:
        """Directed station graph weighted by median scheduled run time."""

        samples: dict[tuple[str, str], list[int]] = defaultdict(list)
        for a, b, minutes in self.con.execute("SELECT from_code, to_code, runtime_min FROM sections"):
            samples[(a, b)].append(minutes)
        graph: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (a, b), values in samples.items():
            values.sort()
            graph[a].append((b, max(float(values[len(values) // 2]), 0.5)))
        return graph

    def fastest_path(self, origin: str, destination: str) -> dict[str, Any] | None:
        """Dijkstra over the timetable network: the quickest station sequence.

        This is a network path, not a journey plan: it ignores whether one train
        actually runs the whole way and does not include waiting for connections.
        """

        origin, destination = origin.upper(), destination.upper()
        best = {origin: 0.0}
        previous: dict[str, str] = {}
        heap = [(0.0, origin)]
        while heap:
            cost, node = heapq.heappop(heap)
            if node == destination:
                break
            if cost > best.get(node, float("inf")):
                continue
            for neighbour, minutes in self.graph.get(node, []):
                candidate = cost + minutes
                if candidate < best.get(neighbour, float("inf")):
                    best[neighbour] = candidate
                    previous[neighbour] = node
                    heapq.heappush(heap, (candidate, neighbour))
        if destination not in best:
            return None
        path = [destination]
        while path[-1] != origin:
            path.append(previous[path[-1]])
        path.reverse()
        return {"stations": path, "running_minutes": round(best[destination], 1), "hops": len(path) - 1}

    def summary(self) -> dict[str, Any]:
        def one(sql: str) -> int:
            return self.con.execute(sql).fetchone()[0]

        return {
            "stations": one("SELECT count(*) FROM stations"),
            "trains": one("SELECT count(*) FROM trains"),
            "stops": one("SELECT count(*) FROM stops"),
            "train_sections": one("SELECT count(*) FROM sections"),
            "distinct_track_sections": one(
                "SELECT count(*) FROM (SELECT DISTINCT min(from_code,to_code), max(from_code,to_code) FROM sections)"
            ),
        }
