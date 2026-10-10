"""GNSS device agent for a loco or cab unit: receiver sentences in, signed position batches out.

Runs on the unit next to the GNSS receiver (any NMEA 0183 receiver: GPS, NavIC, multi-constellation):

    RAILGUARD_URL=https://railguard.example/railguard \
    RAILGUARD_FEED_TOKEN=... RAILGUARD_AGENT_KEY="GNSS_L30123:k1:<64+ hex>" \
    python -m india_rail gnss --train 12951 --start-date 2026-10-08 --nmea /dev/ttyACM0

* Each line is checked (NMEA checksum) and combined into a fix (RMC position + GGA satellites/HDOP);
  a fix failing the quality gates (`gps.quality_problem`) is dropped on the unit, not sent.
* One fix every `interval_s` (default 10 s) is signed into the gateway envelope (HMAC-SHA256 with this
  unit's own key) and POSTed to /national/feed/batch with the feed role's bearer token over TLS.
* Every unit has its own source name and key, so a stolen unit is revoked alone and its sequence numbers
  never collide with another unit's. Sequence numbers are wall-clock milliseconds: they keep rising
  across restarts.
* While the server cannot be reached, fixes wait in a bounded queue and are dropped once older than the
  gateway's 3-minute position policy: an old fix is not evidence of where the train is now.

The agent only reports observations. It cannot approve, hold or move anything.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from india_rail.railguard import gps
from india_rail.railguard.livefeed import IST, SOURCE, TRAIN, load_keys, sign

POLICY_S = 170  # just inside the gateway's 3-minute observation window
QUEUE_MAX = 64
BATCH_MAX = 20


class GnssAgent:
    def __init__(
        self,
        train_number: str,
        start_date: str,
        source: str,
        key_id: str,
        secret: bytes,
        post: Callable[[dict[str, Any]], dict[str, Any]],
        interval_s: float = 10.0,
        clock: Callable[[], float] = time.time,
    ):
        if not TRAIN.match(train_number) or not SOURCE.match(source):
            raise ValueError("invalid train number or source name")
        datetime.fromisoformat(start_date)
        self.train, self.start_date = train_number, start_date
        self.source, self.key_id, self.secret = source, key_id, secret
        self.post, self.interval_s, self.clock = post, interval_s, clock
        self.builder = gps.FixBuilder()
        self.queue: deque[dict[str, Any]] = deque(maxlen=QUEUE_MAX)
        self.last_taken = -1e18
        self.sequence = 0
        self.counts = {"lines": 0, "bad_sentences": 0, "poor_fixes": 0, "queued": 0, "sent": 0, "accepted": 0,
                       "expired": 0, "send_failures": 0}  # fmt: skip

    # ---- receiver side ------------------------------------------------------------------------------------
    def feed_line(self, line: str) -> str | None:
        """One receiver line. Returns why a completed fix was dropped (None if queued or not yet a fix)."""

        self.counts["lines"] += 1
        try:
            fix = self.builder.feed(line)
        except gps.NmeaError:
            self.counts["bad_sentences"] += 1
            return None
        if fix is None:
            return None
        now = datetime.fromtimestamp(self.clock(), UTC)
        problem = gps.quality_problem(fix, now)
        if problem:
            self.counts["poor_fixes"] += 1
            return problem
        if fix.when.timestamp() - self.last_taken < self.interval_s:
            return None
        self.last_taken = fix.when.timestamp()
        self.queue.append(
            {
                "type": "POSITION",
                "train_number": self.train,
                "start_date": self.start_date,
                "lat": round(fix.lat, 6),
                "lon": round(fix.lon, 6),
                "speed_kmph": round(fix.speed_kmph, 1),
                "satellites": fix.satellites,
                "hdop": round(fix.hdop, 1),
                "observed_at": fix.when.astimezone(IST).isoformat(),
            }
        )
        self.counts["queued"] += 1
        return None

    # ---- server side --------------------------------------------------------------------------------------
    def envelope(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        self.sequence = max(self.sequence + 1, int(self.clock() * 1000))
        env = {
            "source": self.source,
            "key_id": self.key_id,
            "sent_at": datetime.fromtimestamp(self.clock(), IST).isoformat(),
            "nonce": secrets.token_hex(16),
            "sequence": self.sequence,
            "events": events,
        }
        env["signature"] = sign(env, self.secret)
        return env

    def flush(self) -> dict[str, Any] | None:
        """Send what is queued (dropping fixes older than the policy). Keeps the batch on a network failure."""

        now = self.clock()
        while self.queue and now - datetime.fromisoformat(self.queue[0]["observed_at"]).timestamp() > POLICY_S:
            self.queue.popleft()
            self.counts["expired"] += 1
        if not self.queue:
            return None
        events = list(self.queue)[:BATCH_MAX]
        try:
            result = self.post(self.envelope(events))
        except OSError:
            self.counts["send_failures"] += 1
            return None
        for _ in events:
            self.queue.popleft()
        self.counts["sent"] += len(events)
        self.counts["accepted"] += int(result.get("accepted", 0))
        return result


def http_post(url: str, token: str, timeout_s: float = 5.0) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if not url.startswith("https://") and os.environ.get("RAILGUARD_AGENT_ALLOW_HTTP") != "1":
        raise ValueError("the feed URL must be https:// (RAILGUARD_AGENT_ALLOW_HTTP=1 only for a local test)")

    def post(envelope: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url.rstrip("/") + "/national/feed/batch",
            data=json.dumps(envelope).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310 - https enforced above
            return json.loads(response.read(1_000_000))

    return post


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m india_rail gnss", description=__doc__.split("\n\n")[0])
    parser.add_argument("--train", required=True)
    parser.add_argument("--start-date", required=True, help="journey start date (YYYY-MM-DD)")
    parser.add_argument("--nmea", default="-", help="receiver device or file of NMEA sentences ('-' = stdin)")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", help="check sentences and fixes, send nothing")
    args = parser.parse_args(argv)

    keys = load_keys(os.environ.get("RAILGUARD_AGENT_KEY", ""))
    if len(keys) != 1:
        print("RAILGUARD_AGENT_KEY must hold exactly one SOURCE:key_id:hexsecret", file=sys.stderr)
        return 2
    (source, key_id), secret = next(iter(keys.items()))
    if args.dry_run:
        post: Callable[[dict[str, Any]], dict[str, Any]] = lambda env: {"accepted": 0, "dry_run": True}  # noqa: E731
    else:
        post = http_post(os.environ["RAILGUARD_URL"], os.environ["RAILGUARD_FEED_TOKEN"])
    agent = GnssAgent(args.train, args.start_date, source, key_id, secret, post, args.interval)
    stream = sys.stdin if args.nmea == "-" else open(args.nmea, encoding="ascii", errors="replace")
    last_flush = 0.0
    with stream:
        for line in stream:
            agent.feed_line(line)
            if time.time() - last_flush >= 1.0:
                agent.flush()
                last_flush = time.time()
    agent.flush()
    print(json.dumps({"source": source, **agent.counts}))
    return 0
