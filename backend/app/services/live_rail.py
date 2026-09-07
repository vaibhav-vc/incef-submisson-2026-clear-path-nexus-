"""Live corridor congestion from RailRadar (free sandbox: 1,000 req/month).

What this gives us: real delay minutes for passenger trains moving through the
requested route corridor right now. That is a genuine congestion signal.

What it does NOT give us: freight-specific data. RailRadar tracks the NTES
passenger network. On a shared-track corridor passenger delays correlate with
freight delays, but they are not the same thing - the reading is labelled
accordingly and treated as an adjustment to the seeded baseline, never as
ground truth.

Budget discipline: the free tier is 1,000 requests/month across 5 stations.
The cache TTL is load-bearing, not an optimisation. When the budget is spent
we return UNAVAILABLE and the caller keeps its static value.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Free tier allows hours in {2, 4, 6, 8}.
LOOKAHEAD_HOURS = 4


def configured_corridor_stations() -> tuple[str, ...]:
    """Return explicitly configured standalone telemetry coverage.

    Route decisions pass their own station codes. An empty configuration is
    deliberately allowed and means UNAVAILABLE rather than a hidden corridor.
    """

    return tuple(
        dict.fromkeys(
            code.strip().upper()
            for code in settings.RAILRADAR_CORRIDOR_STATIONS.split(",")
            if code.strip()
        )
    )


def _bounded_station_codes(stations: tuple[str, ...]) -> tuple[str, ...]:
    """Respect provider budget while retaining both ends of long routes."""

    normalized = tuple(dict.fromkeys(code.strip().upper() for code in stations if code.strip()))
    limit = max(1, settings.RAILRADAR_MAX_LIVE_LOOKUPS)
    if len(normalized) <= limit:
        return normalized
    if limit == 1:
        return normalized[:1]
    indices = [round(index * (len(normalized) - 1) / (limit - 1)) for index in range(limit)]
    return tuple(normalized[index] for index in indices)


class RailDataSource(str, Enum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class StationCongestion:
    station_code: str
    source: RailDataSource
    train_count: int = 0
    mean_delay_minutes: float = 0.0
    max_delay_minutes: int = 0
    at_station_count: int = 0
    observed_at: datetime | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.source is not RailDataSource.UNAVAILABLE


@dataclass(frozen=True)
class CorridorCongestion:
    source: RailDataSource
    stations: list[StationCongestion] = field(default_factory=list)
    score: float | None = None  # 0-100, higher = clearer
    fetched_at: datetime | None = None
    observed_at: datetime | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.source is not RailDataSource.UNAVAILABLE and self.score is not None


class _Budget:
    """Tracks monthly request spend so we fail predictably instead of at 429."""

    def __init__(self, monthly_limit: int) -> None:
        self.monthly_limit = monthly_limit
        self._used = 0
        self._period = self._current_period()

    @staticmethod
    def _current_period() -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        return now.year, now.month

    def _roll(self) -> None:
        period = self._current_period()
        if period != self._period:
            self._period, self._used = period, 0

    @property
    def remaining(self) -> int:
        self._roll()
        return max(0, self.monthly_limit - self._used)

    def spend(self, n: int = 1) -> bool:
        self._roll()
        if self._used + n > self.monthly_limit:
            return False
        self._used += n
        return True

    def refund(self, n: int = 1) -> None:
        """Return quota for a request that never reached the provider.

        A connection error, DNS failure, or timeout means RailRadar never saw
        the request and did not bill it. Counting it locally would let a flaky
        network silently drain the entire monthly allowance without a single
        successful call.
        """
        self._roll()
        self._used = max(0, self._used - n)


class RailRadarClient:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, StationCongestion]] = {}
        self._lock = asyncio.Lock()
        self.budget = _Budget(settings.RAILRADAR_MONTHLY_BUDGET)

    def _cached(self, code: str) -> StationCongestion | None:
        entry = self._cache.get(code)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > settings.RAILRADAR_CACHE_TTL_SECONDS:
            return None
        # Re-label: a cache hit is honest about being a cache hit.
        return StationCongestion(
            station_code=value.station_code,
            source=RailDataSource.CACHED,
            train_count=value.train_count,
            mean_delay_minutes=value.mean_delay_minutes,
            max_delay_minutes=value.max_delay_minutes,
            at_station_count=value.at_station_count,
            observed_at=value.observed_at,
            detail=value.detail,
        )

    @staticmethod
    def parse_station_board(code: str, payload: dict[str, Any]) -> StationCongestion:
        """Turn a /stations/{code}/live envelope into a congestion reading.

        Split out from the network call so it can be tested against fixtures.
        """
        if not payload.get("success"):
            err = (payload.get("error") or {}).get("message", "unknown error")
            return StationCongestion(code, RailDataSource.UNAVAILABLE, detail=err)

        # A success envelope with no data block is malformed, not "no trains".
        # Reporting it as LIVE with zero trains would score the corridor as
        # perfectly clear - the exact silent-optimism bug removed from port_sync.
        data = payload.get("data")
        if not isinstance(data, dict) or "trains" not in data:
            return StationCongestion(
                code, RailDataSource.UNAVAILABLE, detail="Malformed response: no train list"
            )

        trains = data.get("trains") or []
        delays: list[int] = []
        at_station = 0

        for entry in trains:
            live = entry.get("live") or {}
            if live.get("type") == "at-station":
                at_station += 1
            delay = live.get("delayMinutes")
            if isinstance(delay, (int, float)):
                delays.append(int(delay))

        if not trains:
            return StationCongestion(
                code,
                RailDataSource.LIVE,
                observed_at=datetime.now(timezone.utc),
                detail="No trains in window",
            )

        return StationCongestion(
            station_code=code,
            source=RailDataSource.LIVE,
            train_count=len(trains),
            mean_delay_minutes=round(sum(delays) / len(delays), 1) if delays else 0.0,
            max_delay_minutes=max(delays) if delays else 0,
            at_station_count=at_station,
            observed_at=datetime.now(timezone.utc),
        )

    async def fetch_station(self, code: str) -> StationCongestion:
        cached = self._cached(code)
        if cached is not None:
            return cached

        if not settings.RAILRADAR_API_KEY:
            return StationCongestion(
                code, RailDataSource.UNAVAILABLE, detail="RAILRADAR_API_KEY not set"
            )

        if not self.budget.spend():
            logger.warning("RailRadar monthly budget exhausted; serving static baseline")
            return StationCongestion(
                code, RailDataSource.UNAVAILABLE, detail="Monthly request budget exhausted"
            )

        url = f"{settings.RAILRADAR_BASE_URL.rstrip('/')}/stations/{code}/live"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    url,
                    params={"hours": LOOKAHEAD_HOURS},
                    headers={"Authorization": f"Bearer {settings.RAILRADAR_API_KEY}"},
                )
                if resp.status_code == 429:
                    # The provider counted this one; do not refund.
                    return StationCongestion(
                        code, RailDataSource.UNAVAILABLE, detail="Rate limited by RailRadar"
                    )
                resp.raise_for_status()
                reading = self.parse_station_board(code, resp.json())
        except httpx.HTTPStatusError as exc:
            # We got a response, so the request was billed. No refund.
            logger.warning("RailRadar returned %s for %s", exc.response.status_code, code)
            return StationCongestion(
                code, RailDataSource.UNAVAILABLE, detail=f"HTTP {exc.response.status_code}"
            )
        except (httpx.HTTPError, ValueError) as exc:
            # Connection/timeout/decode failure - the provider never billed us.
            self.budget.refund()
            logger.warning("RailRadar unreachable for %s: %s", code, exc)
            return StationCongestion(
                code, RailDataSource.UNAVAILABLE, detail=f"{type(exc).__name__}"
            )

        if reading.available:
            self._cache[code] = (time.monotonic(), reading)
        return reading

    @staticmethod
    def parse_authorized_corridor(
        station_codes: tuple[str, ...], payload: Any, fetched_at: datetime
    ) -> CorridorCongestion:
        """Validate the contracted freight-operations response without defaults."""

        if not isinstance(payload, dict):
            raise ValueError("Railway operations response must be a JSON object")
        score = payload.get("congestion_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError("Railway operations response has no numeric congestion_score")
        if not 0 <= float(score) <= 100:
            raise ValueError("Railway operations congestion_score must be between 0 and 100")
        observed_raw = payload.get("observed_at")
        if not isinstance(observed_raw, str) or not observed_raw.strip():
            raise ValueError("Railway operations response is missing observed_at")
        try:
            observed_at = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Railway operations observed_at is invalid") from exc
        if observed_at.tzinfo is None:
            raise ValueError("Railway operations observed_at must include a timezone")
        observed_at = observed_at.astimezone(timezone.utc)
        return CorridorCongestion(
            source=RailDataSource.LIVE,
            stations=[
                StationCongestion(
                    station_code=code,
                    source=RailDataSource.LIVE,
                    observed_at=observed_at,
                    detail="Authorized freight operations feed",
                )
                for code in station_codes
            ],
            score=float(score),
            fetched_at=fetched_at,
            observed_at=observed_at,
            detail="Authorized freight operations feed",
        )

    async def fetch_authorized_corridor(
        self, station_codes: tuple[str, ...]
    ) -> CorridorCongestion:
        """Call the configured freight feed; failures remain UNAVAILABLE."""

        fetched_at = datetime.now(timezone.utc)
        if not settings.RAILWAY_FEED_API_KEY:
            return CorridorCongestion(
                source=RailDataSource.UNAVAILABLE,
                fetched_at=fetched_at,
                detail="RAILWAY_FEED_API_KEY not set for configured freight feed",
            )
        try:
            async with httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    settings.RAILWAY_OPERATIONS_FEED,
                    json={"station_codes": list(station_codes)},
                    headers={"Authorization": f"Bearer {settings.RAILWAY_FEED_API_KEY}"},
                )
                response.raise_for_status()
                payload = response.json()
            return self.parse_authorized_corridor(station_codes, payload, fetched_at)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Authorized railway operations feed returned HTTP %s",
                exc.response.status_code,
            )
            return CorridorCongestion(
                source=RailDataSource.UNAVAILABLE,
                fetched_at=fetched_at,
                detail=f"Authorized freight feed HTTP {exc.response.status_code}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Authorized railway operations feed unavailable (%s)", type(exc).__name__
            )
            return CorridorCongestion(
                source=RailDataSource.UNAVAILABLE,
                fetched_at=fetched_at,
                detail=f"Authorized freight feed unavailable: {type(exc).__name__}",
            )

    async def fetch_corridor(
        self, stations: tuple[str, ...] | None = None
    ) -> CorridorCongestion:
        all_requested_stations = tuple(
            dict.fromkeys(
                code.strip().upper()
                for code in (
                    stations if stations is not None else configured_corridor_stations()
                )
                if code.strip()
            )
        )
        if not all_requested_stations:
            return CorridorCongestion(
                source=RailDataSource.UNAVAILABLE,
                detail=(
                    "No route station coverage supplied and "
                    "RAILRADAR_CORRIDOR_STATIONS is not configured"
                ),
            )
        # A configured freight feed is authoritative. Never mask its outage or
        # malformed response with passenger RailRadar telemetry.
        if settings.RAILWAY_OPERATIONS_FEED:
            return await self.fetch_authorized_corridor(all_requested_stations)

        requested_stations = _bounded_station_codes(all_requested_stations)
        async with self._lock:
            readings = await asyncio.gather(
                *(self.fetch_station(code) for code in requested_stations)
            )

        usable = [r for r in readings if r.available]
        if not usable:
            return CorridorCongestion(
                source=RailDataSource.UNAVAILABLE,
                stations=list(readings),
                detail="No corridor station returned live data",
            )

        source = (
            RailDataSource.LIVE
            if any(r.source is RailDataSource.LIVE for r in usable)
            else RailDataSource.CACHED
        )
        return CorridorCongestion(
            source=source,
            stations=list(readings),
            score=delay_to_congestion_score(usable),
            fetched_at=datetime.now(timezone.utc),
            observed_at=min(
                (reading.observed_at for reading in usable if reading.observed_at is not None),
                default=None,
            ),
        )


def delay_to_congestion_score(readings: list[StationCongestion]) -> float:
    """Map observed delays to a 0-100 congestion score (100 = clear).

    Piecewise-linear against Indian Railways corridor norms:
        0 min   -> 100   running clean
        15 min  ->  85   normal slack
        30 min  ->  70   noticeable
        60 min  ->  40   congested
        120 min ->  10   severe
        180 min+->   0   corridor effectively blocked

    Deliberately not a smooth curve: the breakpoints are operationally
    meaningful and easy for a controller to sanity-check.
    """
    if not readings:
        return 100.0

    weighted = sum(r.mean_delay_minutes * max(r.train_count, 1) for r in readings)
    total = sum(max(r.train_count, 1) for r in readings)
    mean_delay = weighted / total

    breakpoints = [(0, 100.0), (15, 85.0), (30, 70.0), (60, 40.0), (120, 10.0), (180, 0.0)]

    if mean_delay >= breakpoints[-1][0]:
        return 0.0
    for (x0, y0), (x1, y1) in zip(breakpoints, breakpoints[1:]):
        if x0 <= mean_delay <= x1:
            span = x1 - x0
            ratio = (mean_delay - x0) / span if span else 0.0
            return round(y0 + (y1 - y0) * ratio, 1)
    return 100.0


rail_client = RailRadarClient()
