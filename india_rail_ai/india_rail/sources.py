"""Registry of the public datasets this package can ingest.

Every source records where it came from, its licence, what it can and cannot
support, and (where pinned) the SHA-256 of the exact bytes used to train the
committed model metrics. A download whose digest differs is rejected unless the
caller explicitly accepts an unpinned refresh.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataSource:
    key: str
    url: str
    sha256: str | None
    licence: str
    publisher: str
    description: str
    limitations: tuple[str, ...]


DATAMEET_BASE = "https://raw.githubusercontent.com/datameet/railways/master"

DATAMEET_LIMITATIONS = (
    "Community-gathered snapshot (collected around 2015-2016), not a current Indian Railways timetable.",
    "No running-day (days of week) information: every train is treated as daily.",
    "Pass-through stations carry interpolated, minute-resolution times.",
    "Not an authoritative source for any operational decision.",
)

SOURCES: dict[str, DataSource] = {
    "stations": DataSource(
        key="stations",
        url=f"{DATAMEET_BASE}/stations.json",
        sha256="9bd5e1da3a859e5359a95f40b6009aa468efb177da4faac57ffdcd7daeb4df18",
        licence="CC0-1.0",
        publisher="DataMeet (datameet/railways)",
        description="GeoJSON points for ~9,000 Indian railway stations with zone and state.",
        limitations=DATAMEET_LIMITATIONS,
    ),
    "trains": DataSource(
        key="trains",
        url=f"{DATAMEET_BASE}/trains.json",
        sha256="e434d9c56016ccdf2291ccd446586ef87a7fab101084efa5f68871ab27800167",
        licence="CC0-1.0",
        publisher="DataMeet (datameet/railways)",
        description="GeoJSON LineStrings for ~5,200 trains with type, zone, classes and distance.",
        limitations=DATAMEET_LIMITATIONS,
    ),
    "schedules": DataSource(
        key="schedules",
        url=f"{DATAMEET_BASE}/schedules.json",
        sha256="105d63816acb177eac30a7d156eb2d312625a42ddebd273edee810d2989878ec",
        licence="CC0-1.0",
        publisher="DataMeet (datameet/railways)",
        description="~417,000 train stop rows (arrival, departure, day) in route order.",
        limitations=DATAMEET_LIMITATIONS,
    ),
}

# Optional sources that need network access this package does not assume.
OPTIONAL_SOURCES = {
    "osm_rail": {
        "url": "https://overpass-api.de/api/interpreter",
        "licence": "ODbL-1.0 (OpenStreetMap contributors)",
        "loader": "scripts/fetch_osm_tracks.py",
        "description": (
            "Physical track geometry (railway=rail) with gauge, electrification, "
            "track count and max speed tags where mapped."
        ),
    },
    "ntes_live": {
        "url": "https://enquiry.indianrail.gov.in/mntes/",
        "licence": "Indian Railways terms of use; no open API",
        "loader": None,
        "description": (
            "Live running status. Requires an authorised data-sharing agreement; "
            "scraping is not supported by this package."
        ),
    },
}
