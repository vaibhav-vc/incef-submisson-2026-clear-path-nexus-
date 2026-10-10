"""Free third-party running-status services as an *unofficial* live source, until CRIS authorises the official feed.

    RAILGUARD_URL=https://<server>/railguard RAILGUARD_FEED_TOKEN=... \\
    RAILGUARD_AGENT_KEY="RAILENGINE:k1:<64+ hex>" RAILGUARD_RAILENGINE_KEY=<key from your Railway Engine account> \\
    python -m india_rail live-sources poll --provider railengine --stations NDLS,CNB,PRYJ,DDU

    python -m india_rail live-sources list                                   # what was checked, and the terms
    python -m india_rail live-sources probe --provider railradar --train 12951 # one request: shape and events

What was checked (October 2026), and why only these two:
* ixigo ("Where is my train"): its terms forbid access "through automated or non-human means" and commercial use
  of its content without written permission. Not used; a partnership with ixigo would be needed.
* NTES (CRIS): the official source; no public API, and this project does not scrape it. The authorised feed
  (livefeed.py, LIVE_DATA_INTERFACE.md) is the way to it.
* Railway Engine: free, a key from a Google sign-in, 60 requests a minute; its terms permit personal and
  commercial use but forbid redistributing its data, serving its responses through another service and keeping
  them beyond temporary use; it is not affiliated with Indian Railways, IRCTC or CRIS. So: internal decision
  support only, nothing stored, never on a public board.
* RailRadar: a free sandbox of 1,000 requests a month with an account key; its data is "compiled using
  crowd-sourced telemetry and publicly accessible databases"; it publishes no API terms and is independent of
  Indian Railways and NTES. So: trials only, and ask RailRadar before more.

How the data is used:
* Reports become the gateway's STATION events (a train has departed from, or is at, a station, at a time),
  signed with this poller's own feed key and sent to /national/feed/batch like any feed: the gateway checks them
  as it checks every feed (on the route, in order, fresh, signed).
* Their source names are *unofficial* (UNOFFICIAL): the twin uses them to place trains and project delays, but a
  plan that relies on them stays PLANNING_ONLY, never REVIEWABLE; published times say where they come from; and
  nothing here can approve, hold or move anything.
* Only what is needed is kept: no response is written anywhere; the poller keeps its request counts (to stay
  inside each free plan, in a small state file of counts only) and, in memory, which events it has sent.
* A response without the documented fields is refused with the reason, never guessed at. A timetable that does
  not match ours (a different scheduled minute) is skipped, not forced onto a journey.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from india_rail.railguard.livefeed import IST, MAX_EVENTS, STATION, TRAIN, sign

CHECKED = "2026-10-10"
USER_AGENT = "india-rail-railguard/1.0 (advisory decision support for Indian Railways controllers)"
QUOTA_SHARE = 0.8  # use at most this share of a free plan, so other users of the same key are not starved
FUTURE_SLACK_S = 120  # an "observed" time this far after the response is not an observation
OLDEST_S = 6 * 3600  # older reports are history, not where a train is
SENT_KEPT_DAYS = 4


@dataclass(frozen=True)
class Provider:
    name: str
    source: str  # feed source name the gateway sees
    base: str
    key_env: str
    per_minute: int | None
    per_month: int | None
    mode: str  # "station": station boards; "train": one train's live status
    terms_url: str
    use: str
    data_source: str


PROVIDERS = {
    "railengine": Provider(
        "railengine", "RAILENGINE", "https://railway-engine.apkscope.workers.dev", "RAILGUARD_RAILENGINE_KEY", 60, None,
        "station", "https://railengine.vercel.app/terms",
        "personal and commercial use; no redistribution, no serving its responses through another service, no "
        "keeping its data beyond temporary use: internal decision support only, never a public board",
        "not named: 'third-party systems, publicly available information, external services'",
    ),
    "railradar": Provider(
        "railradar", "RAILRADAR", "https://api.railradar.in", "RAILGUARD_RAILRADAR_KEY", None, 1000, "train",
        "https://railradar.in/terms",
        "no API terms published: trials only; ask RailRadar before wider use",
        "'crowd-sourced telemetry and publicly accessible databases'",
    ),
}  # fmt: skip
UNOFFICIAL = frozenset(p.source for p in PROVIDERS.values())


def unofficial_sources() -> frozenset[str]:
    """Feed sources whose reports may place trains but never make a plan approvable as live (the third-party
    services above, plus any named in RAILGUARD_UNOFFICIAL_SOURCES)."""

    extra = {s.strip().upper() for s in os.environ.get("RAILGUARD_UNOFFICIAL_SOURCES", "").split(",") if s.strip()}
    return UNOFFICIAL | extra


class Refused(ValueError):
    """A response that does not have the documented shape: nothing is taken from it."""


# ---- staying inside a free plan --------------------------------------------------------------------------------
class Budget:
    """Requests allowed: at most QUOTA_SHARE of a plan's per-minute and per-month limits. The month's count is kept
    in `state` (counts only), so a restart does not overshoot the plan."""

    def __init__(self, provider: Provider, state: Path | None = None, clock: Callable[[], float] = time.time):
        self.provider, self.state, self.clock = provider, state, clock
        self.recent: list[float] = []
        self.month, self.used = self._load()

    def _load(self) -> tuple[str, int]:
        if self.state and self.state.exists():
            try:
                saved = json.loads(self.state.read_text()).get(self.provider.name, {})
                return str(saved.get("month", "")), int(saved.get("used", 0))
            except (OSError, ValueError, TypeError):
                pass  # an unreadable count starts again, on the safe side: below
        return "", 0

    def _save(self) -> None:
        if not self.state:
            return
        try:
            data = json.loads(self.state.read_text()) if self.state.exists() else {}
        except (OSError, ValueError):
            data = {}
        data[self.provider.name] = {"month": self.month, "used": self.used}
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.state)

    def take(self) -> bool:
        now = self.clock()
        month = datetime.fromtimestamp(now, IST).strftime("%Y-%m")
        if month != self.month:
            self.month, self.used = month, 0
        p = self.provider
        if p.per_month is not None and self.used >= int(p.per_month * QUOTA_SHARE):
            return False
        self.recent = [t for t in self.recent if now - t < 60]
        if p.per_minute is not None and len(self.recent) >= max(int(p.per_minute * QUOTA_SHARE), 1):
            return False
        self.recent.append(now)
        self.used += 1
        self._save()
        return True


# ---- our timetable: which journey a report belongs to ------------------------------------------------------------
class Timetable:
    """Scheduled minutes (from midnight of the journey's start day) of every train's calls, from the timetable the
    twin runs on: a report naming a train, a station and a scheduled clock time belongs to the journey that
    started on the day that puts that call at that time."""

    def __init__(self, db: Path):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.calls: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for train, station, arr, dep in con.execute("SELECT train_number, station_code, arr_min, dep_min FROM stops"):
            self.calls[(train, station)].append((int(arr), int(dep)))
        con.close()

    def start_date(self, train: str, station: str, scheduled: datetime, kind: str) -> date | None:
        """The journey start date, or None if our timetable has no such call at that clock time (another timetable
        version, or a report we cannot place)."""

        clock_min = scheduled.hour * 60 + scheduled.minute
        for arr, dep in self.calls.get((train, station), ()):
            m = dep if kind == "DEP" else arr
            if min((clock_min - m) % 1440, (m - clock_min) % 1440) <= 1:
                return scheduled.date() - timedelta(days=m // 1440)
        return None

    def scheduled(self, train: str, station: str, start: date, kind: str) -> datetime | None:
        calls = self.calls.get((train, station), ())
        if not calls:
            return None
        arr, dep = calls[0]
        m = dep if kind == "DEP" else arr
        return datetime.combine(start, datetime.min.time(), IST) + timedelta(minutes=m)


def _instant(value: Any) -> datetime:
    """An ISO 8601 time with its zone (a time without one is refused: guessing the zone would move a train)."""

    if not isinstance(value, str):
        raise Refused("time is not a string")
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise Refused(f"time without a zone: {value!r}")
    return when.astimezone(IST)


def _clock_near(hhmm: Any, near: datetime, before_min: float = 60, after_min: float = 1380) -> datetime:
    """The occurrence of a scheduled "HH:MM" (IST) that lies between `before_min` after and `after_min` before
    `near` (a train runs late far more than early)."""

    if not isinstance(hhmm, str) or len(hhmm) < 4 or ":" not in hhmm:
        raise Refused(f"scheduled time is not HH:MM: {hhmm!r}")
    hour, minute = (int(x) for x in hhmm.split(":")[:2])
    for days in (0, -1, 1):
        candidate = datetime.combine(near.date() + timedelta(days=days), datetime.min.time(), IST).replace(
            hour=hour, minute=minute
        )
        if -before_min <= (near - candidate).total_seconds() / 60 <= after_min:
            return candidate
    raise Refused(f"scheduled {hhmm} is not near {near.isoformat()}")


def _event(train: str, start: date, station: str, kind: str, observed: datetime) -> dict[str, Any]:
    return {"type": "STATION", "train_number": train, "start_date": start.isoformat(), "station_code": station,
            "event": kind, "observed_at": observed.isoformat()}  # fmt: skip


def _fresh(observed: datetime, now: datetime) -> bool:
    age = (now - observed).total_seconds()
    return -FUTURE_SLACK_S <= age <= OLDEST_S


# ---- response shapes (only the documented fields are read) ---------------------------------------------------------
def railengine_board(body: Any, station: str, timetable: Timetable, now: datetime) -> tuple[list[dict], dict]:
    """Railway Engine `GET /v1/station/{code}/live`: a train shown `departed` gives a departure at its expected
    (delay-adjusted) departure time; `at-station` an arrival at its expected arrival. Upcoming, scheduled and
    unknown trains are not observations and give nothing."""

    if not isinstance(body, dict) or body.get("status") not in ("SUCCESS", "STALE_DATA"):
        raise Refused(f"status {body.get('status') if isinstance(body, dict) else type(body).__name__}")
    trains = (body.get("data") or {}).get("trains")
    if not isinstance(trains, list):
        raise Refused("data.trains missing")
    events, skipped = [], defaultdict(int)
    for t in trains:
        try:
            if not isinstance(t, dict):
                raise Refused("train entry is not an object")
            number, state = str(t.get("trainNumber", "")), t.get("liveStatus")
            if not TRAIN.match(number):
                raise Refused("train number")
            if state == "departed":
                kind, scheduled, observed = "DEP", t.get("departure"), t.get("expectedDeparture")
            elif state == "at-station":
                kind, scheduled, observed = "ARR", t.get("arrival"), t.get("expectedArrival")
            else:
                skipped["not an observation"] += 1
                continue
            if scheduled is None or observed is None:
                skipped["no time"] += 1
                continue
            when = _instant(observed)
            if not _fresh(when, now):
                skipped["not fresh"] += 1
                continue
            sched = _clock_near(scheduled, when)
            start = timetable.start_date(number, station, sched, kind)
            if start is None:
                skipped["not in our timetable at that time"] += 1
                continue
            events.append(_event(number, start, station, kind, when))
        except (Refused, ValueError) as exc:
            skipped[f"refused: {str(exc).split(':')[0]}"] += 1
    return events, dict(skipped)


def railradar_train(body: Any, timetable: Timetable, now: datetime) -> tuple[list[dict], dict]:
    """RailRadar `GET /v1/trains/{number}/live`: the stops of `data.route` up to `data.currentLocation` that carry
    an actual arrival or departure give those events (halts only; a stop ahead of the train is never one)."""

    if not isinstance(body, dict) or body.get("success") is not True or not isinstance(body.get("data"), dict):
        raise Refused("success/data missing")
    d = body["data"]
    number, route, here = str(d.get("trainNumber", "")), d.get("route"), d.get("currentLocation")
    if not TRAIN.match(number) or not isinstance(route, list) or not isinstance(here, dict):
        raise Refused("trainNumber, route or currentLocation missing")
    try:
        start = date.fromisoformat(str(d.get("startDate"))[:10])
    except ValueError as exc:
        raise Refused("startDate missing") from exc
    reached = here.get("sequence")
    if not isinstance(reached, int):
        raise Refused("currentLocation.sequence missing")
    events, skipped = [], defaultdict(int)
    for stop in route:
        try:
            if not isinstance(stop, dict) or not isinstance(stop.get("sequence"), int):
                raise Refused("route stop")
            if stop["sequence"] > reached or not stop.get("isHalt", True):
                continue
            station = str(stop.get("stationCode", ""))
            if not STATION.match(station):
                raise Refused("station code")
            for kind, field in (("ARR", "actualArrival"), ("DEP", "actualDeparture")):
                value = stop.get(field)
                if value in (None, "", "--"):
                    continue
                if isinstance(value, str) and "T" in value:
                    when = _instant(value)
                else:  # a clock time: the occurrence from an hour before the scheduled call to 23 hours after it
                    sched = timetable.scheduled(number, station, start, kind)
                    if sched is None:
                        skipped["not in our timetable"] += 1
                        continue
                    when = _clock_near(value, sched, before_min=1380, after_min=60)
                if not _fresh(when, now):
                    skipped["not fresh"] += 1
                    continue
                events.append(_event(number, start, station, kind, when))
        except (Refused, ValueError) as exc:
            skipped[f"refused: {str(exc).split(':')[0]}"] += 1
    return events, dict(skipped)


# ---- fetching ------------------------------------------------------------------------------------------------------
def http_get(provider: Provider, key: str, path: str, query: dict[str, str] | None = None, timeout_s: float = 20.0):
    """(HTTP status, JSON body or None). The key goes in the header the provider documents, never in the URL."""

    url = provider.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    auth = {"x-api-key": key} if provider.name == "railengine" else {"Authorization": f"Bearer {key}"}
    request = urllib.request.Request(url, headers={**auth, "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310 - fixed https base
            return response.status, json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(100_000))
        except ValueError:
            return exc.code, None


class Poller:
    """Polls one provider within its free plan and sends what it observes to the feed gateway, signed."""

    def __init__(
        self,
        provider: Provider,
        key: str,
        timetable: Timetable,
        post: Callable[[dict[str, Any]], dict[str, Any]],
        feed_key: tuple[str, str, bytes],
        budget: Budget | None = None,
        fetch: Callable[..., tuple[int, Any]] = http_get,
        clock: Callable[[], float] = time.time,
    ):
        source, key_id, secret = feed_key
        if source != provider.source:
            raise ValueError(f"the feed key must be for source {provider.source}, not {source}")
        self.provider, self.key, self.timetable, self.post = provider, key, timetable, post
        self.key_id, self.secret = key_id, secret
        self.budget = budget or Budget(provider, clock=clock)
        self.fetch, self.clock = fetch, clock
        self.sent: set[tuple[str, str, str, str]] = set()  # (train, start date, station, event)
        self.sequence = 0
        self.counts: dict[str, int] = defaultdict(int)

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), IST)

    def observe(self, target: str) -> list[dict[str, Any]]:
        """New events from one request (a station board or one train), or [] when the plan's budget is spent."""

        if not self.budget.take():
            self.counts["skipped: budget"] += 1
            return []
        p = self.provider
        path = f"/v1/station/{target}/live" if p.mode == "station" else f"/v1/trains/{target}/live"
        status, body = self.fetch(p, self.key, path)
        self.counts[f"http {status}"] += 1
        if status not in (200,):
            return []
        try:
            if p.mode == "station":
                events, skipped = railengine_board(body, target, self.timetable, self._now())
            else:
                events, skipped = railradar_train(body, self.timetable, self._now())
        except Refused as exc:
            self.counts[f"refused response: {str(exc)[:60]}"] += 1
            return []
        for reason, n in skipped.items():
            self.counts[f"skipped: {reason}"] += n
        new = []
        for e in events:
            ident = (e["train_number"], e["start_date"], e["station_code"], e["event"])
            if ident not in self.sent:
                self.sent.add(ident)
                new.append(e)
        cutoff = (self._now().date() - timedelta(days=SENT_KEPT_DAYS)).isoformat()
        self.sent = {s for s in self.sent if s[1] >= cutoff}
        return new

    def envelope(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        self.sequence = max(self.sequence + 1, int(self.clock() * 1000))
        env = {"source": self.provider.source, "key_id": self.key_id, "sent_at": self._now().isoformat(),
               "nonce": secrets.token_hex(16), "sequence": self.sequence, "events": events}  # fmt: skip
        env["signature"] = sign(env, self.secret)
        return env

    def send(self, events: list[dict[str, Any]]) -> None:
        events = sorted(events, key=lambda e: e["observed_at"])  # each train's reports in the order they happened
        for i in range(0, len(events), MAX_EVENTS):
            chunk = events[i : i + MAX_EVENTS]
            try:
                result = self.post(self.envelope(chunk))
            except OSError:
                self.counts["send failures"] += 1
                for e in chunk:  # not delivered: may be tried again
                    self.sent.discard((e["train_number"], e["start_date"], e["station_code"], e["event"]))
                continue
            self.counts["events sent"] += len(chunk)
            self.counts["events accepted"] += int(result.get("accepted", 0))

    def cycle(self, targets: list[str]) -> None:
        batch: list[dict[str, Any]] = []
        for target in targets:
            batch += self.observe(target)
        if batch:
            self.send(batch)


def _shape(value: Any, depth: int = 0) -> Any:
    """Field names and types of a response, values left out (to confirm a mapping without keeping the data)."""

    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_shape(value[0], depth + 1), f"... {len(value)} items"] if value else []
    return type(value).__name__


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from india_rail.railguard.gnss_agent import http_post
    from india_rail.railguard.livefeed import load_keys
    from india_rail.railguard.national import timetable_source

    parser = argparse.ArgumentParser(prog="python -m india_rail live-sources", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the services checked, their plans and terms")
    for name in ("probe", "poll"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
        cmd.add_argument("--stations", default="", help="station codes (station-board providers)")
        cmd.add_argument("--trains", default="", help="train numbers (per-train providers)")
        if name == "poll":
            cmd.add_argument("--every", type=float, default=60.0, help="seconds between cycles")
            cmd.add_argument("--once", action="store_true")
            cmd.add_argument("--dry-run", action="store_true", help="observe and print, send nothing")
            cmd.add_argument("--state", type=Path, default=Path("data") / "live_sources_budget.json")
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps({"checked": CHECKED, "providers": {k: vars(v) for k, v in PROVIDERS.items()},
                          "not_used": {"ixigo": "terms forbid automated access and commercial use without written "
                                                "permission", "NTES": "official; no public API; not scraped: use "
                                                "the authorised CRIS feed"}}, indent=1))  # fmt: skip
        return 0
    provider = PROVIDERS[args.provider]
    key = os.environ.get(provider.key_env, "")
    if not key:
        print(f"{provider.key_env} is not set: create a free account ({provider.terms_url.rsplit('/', 1)[0]}) and "
              "put its API key in that variable (never in a file in the repository)", file=sys.stderr)  # fmt: skip
        return 2
    raw = args.stations if provider.mode == "station" else args.trains
    targets = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not targets or not all((STATION if provider.mode == "station" else TRAIN).match(t) for t in targets):
        print(f"give --{'stations' if provider.mode == 'station' else 'trains'} as a comma list", file=sys.stderr)
        return 2
    timetable = Timetable(timetable_source()[1])
    if args.command == "probe":
        path = f"/v1/station/{targets[0]}/live" if provider.mode == "station" else f"/v1/trains/{targets[0]}/live"
        status, body = http_get(provider, key, path)
        now = datetime.now(IST)
        try:
            events, skipped = (railengine_board(body, targets[0], timetable, now) if provider.mode == "station"
                               else railradar_train(body, timetable, now))  # fmt: skip
            outcome: Any = {"events": events, "skipped": skipped}
        except Refused as exc:
            outcome = {"refused": str(exc)}
        print(json.dumps({"http": status, "shape": _shape(body), **outcome}, indent=1, default=str))
        return 0
    keys = load_keys(os.environ.get("RAILGUARD_AGENT_KEY", ""))
    if len(keys) != 1:
        print("RAILGUARD_AGENT_KEY must hold exactly one SOURCE:key_id:hexsecret", file=sys.stderr)
        return 2
    (source, key_id), secret = next(iter(keys.items()))
    if args.dry_run:
        post: Callable[[dict[str, Any]], dict[str, Any]] = lambda env: {"accepted": 0, "dry_run": True}  # noqa: E731
    else:
        post = http_post(os.environ["RAILGUARD_URL"], os.environ["RAILGUARD_FEED_TOKEN"])
    poller = Poller(provider, key, timetable, post, (source, key_id, secret), Budget(provider, args.state))
    while True:
        poller.cycle(targets)
        print(json.dumps({"at": datetime.now(IST).isoformat(timespec="seconds"), **poller.counts}), flush=True)
        if args.once:
            return 0
        time.sleep(args.every)
