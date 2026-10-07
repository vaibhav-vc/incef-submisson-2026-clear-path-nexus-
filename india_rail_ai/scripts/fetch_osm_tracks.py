"""Download India's mapped railway track from OpenStreetMap via Overpass.

Run this on a machine whose network allows overpass-api.de (it is blocked in
some sandboxes). It writes one GeoJSON-lines file of track ways with the tags a
planner needs (gauge, electrified, tracks, maxspeed, usage, service), split
into state-sized tiles so each Overpass query stays small.

    python scripts/fetch_osm_tracks.py --out data/raw/osm_rail.geojsonl

Data (c) OpenStreetMap contributors, ODbL 1.0. Keep that attribution with any
derived dataset. OSM is volunteer-mapped: track counts, speeds and gauge are
incomplete and must not be treated as engineering records.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
KEEP_TAGS = ("railway", "gauge", "electrified", "voltage", "tracks", "maxspeed", "usage", "service", "name", "operator")
# Bounding boxes (south, west, north, east) covering India in 4 x 4 degree tiles.
INDIA_BBOX = (6.0, 68.0, 37.5, 97.5)
TILE_DEGREES = 4.0


def tiles():
    south, west, north, east = INDIA_BBOX
    lat = south
    while lat < north:
        lon = west
        while lon < east:
            yield (lat, lon, min(lat + TILE_DEGREES, north), min(lon + TILE_DEGREES, east))
            lon += TILE_DEGREES
        lat += TILE_DEGREES


def query(bbox) -> dict:
    s, w, n, e = bbox
    ql = (
        "[out:json][timeout:180];"
        f'area["ISO3166-1"="IN"][admin_level=2]->.india;'
        f'way["railway"~"^(rail|narrow_gauge|light_rail|subway)$"](area.india)({s},{w},{n},{e});'
        "out tags geom;"
    )
    data = urllib.parse.urlencode({"data": ql}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "india-rail-ai/0.1"})
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/raw/osm_rail.geojsonl"))
    parser.add_argument("--pause", type=float, default=5.0, help="seconds between tiles (be polite to Overpass)")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ways = 0
    with args.out.open("w", encoding="utf-8") as out:
        for bbox in tiles():
            for attempt in range(3):
                try:
                    result = query(bbox)
                    break
                except Exception as exc:  # network errors and Overpass 429/504
                    if attempt == 2:
                        raise
                    print(f"tile {bbox}: {exc}; retrying")
                    time.sleep(30 * (attempt + 1))
            for element in result.get("elements", []):
                geometry = element.get("geometry") or []
                if len(geometry) < 2:
                    continue
                tags = element.get("tags", {})
                feature = {
                    "type": "Feature",
                    "id": f"way/{element['id']}",
                    "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in geometry]},
                    "properties": {k: tags[k] for k in KEEP_TAGS if k in tags},
                }
                out.write(json.dumps(feature) + "\n")
                ways += 1
            print(f"tile {bbox}: total ways {ways}")
            time.sleep(args.pause)
    print(f"Wrote {ways} ways to {args.out}. Attribution: (c) OpenStreetMap contributors, ODbL 1.0")


if __name__ == "__main__":
    main()
