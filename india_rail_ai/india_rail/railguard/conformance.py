"""Live-data conformance kit: check a feed against the contract before it is connected (LIVE_DATA_INTERFACE.md).

    # CRIS side, offline: are the envelopes our system produces what the receiver accepts?
    python -m india_rail feed-conformance producer --file envelopes.jsonl --source RTIS --key-file rtis_k1.hex

    # Test environment: does the deployed receiver accept the good and refuse the bad?
    python -m india_rail feed-conformance endpoint --url https://nexus-test.example --source RTIS --key-id k1 \\
        --key-file rtis_k1.hex --token-file feed_token.txt

Both write a certificate (JSON) listing every rule checked and its result. The rules are the receiver's own
(constants and parser imported from livefeed.py), so the kit cannot drift from what production enforces. Keys and
tokens are read from files, never from the command line (shell history), and never printed. The endpoint mode
refuses plain HTTP except to this machine: a feed key or token never crosses a network in clear text.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from india_rail.railguard import gps
from india_rail.railguard.livefeed import (
    IST,
    MAX_EVENTS,
    MAX_SKEW_S,
    MIN_SECRET_BYTES,
    SOURCE,
    STATION,
    TRAIN,
    _when,
    canonical,
    sign,
)

POSITION_FIELDS = {"type", "train_number", "start_date", "lat", "lon", "speed_kmph", "observed_at", "satellites",
                   "hdop"}  # fmt: skip
STATION_FIELDS = {"type", "train_number", "start_date", "station_code", "event", "observed_at"}


# ---- rules shared by both modes ---------------------------------------------------------------------------------
def envelope_problems(envelope: Any, secret: bytes | None, now: datetime | None = None) -> list[str]:
    """Contract problems of one envelope on its own (signature checked when the key is given)."""

    if not isinstance(envelope, dict):
        return ["envelope must be a JSON object"]
    out = []
    expected = {"source", "key_id", "sent_at", "nonce", "sequence", "events", "signature"}
    if missing := expected - envelope.keys():
        out.append(f"missing fields: {sorted(missing)}")
    if extra := envelope.keys() - expected:
        out.append(f"unexpected fields: {sorted(extra)} (they would be signed but ignored)")
    if not isinstance(envelope.get("source"), str) or not SOURCE.match(envelope.get("source") or ""):
        out.append("source must match ^[A-Z][A-Z0-9_]{1,15}$")
    if not isinstance(envelope.get("key_id"), str) or not envelope.get("key_id"):
        out.append("key_id must be a non-empty string")
    try:
        sent = _when(envelope.get("sent_at"))
        if now is not None and abs((sent - now).total_seconds()) > MAX_SKEW_S:
            out.append(f"sent_at more than {MAX_SKEW_S} s from the receiver clock")
    except ValueError as exc:
        out.append(f"sent_at: {exc}")
    nonce = envelope.get("nonce")
    if not isinstance(nonce, str) or not 16 <= len(nonce) <= 64:
        out.append("nonce must be a string of 16-64 characters")
    if type(envelope.get("sequence")) is not int or envelope.get("sequence", -1) < 0:
        out.append("sequence must be a non-negative integer")
    events = envelope.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        out.append(f"events must be a list of 1-{MAX_EVENTS}")
    signature = envelope.get("signature")
    if not isinstance(signature, str) or len(signature) != 64:
        out.append("signature must be 64 hex characters (HMAC-SHA256)")
    elif secret is not None and signature != sign(envelope, secret):
        out.append("signature does not verify with this key (canonical JSON: sorted keys, no spaces, UTF-8)")
    return out


def event_problems(event: Any, sent_at: datetime | None = None) -> list[str]:
    """Contract problems of one event (the shape the receiver needs; whether the train runs is its business)."""

    if not isinstance(event, dict):
        return ["event must be a JSON object"]
    kind, out = event.get("type"), []
    if kind not in ("POSITION", "STATION"):
        return ["type must be POSITION or STATION"]
    allowed = POSITION_FIELDS if kind == "POSITION" else STATION_FIELDS
    if extra := event.keys() - allowed:
        out.append(f"unexpected fields: {sorted(extra)}")
    if not isinstance(event.get("train_number"), str) or not TRAIN.match(event.get("train_number") or ""):
        out.append("train_number must match ^[0-9A-Z][0-9A-Z-]{0,15}$")
    try:
        date.fromisoformat(event.get("start_date"))
    except (TypeError, ValueError):
        out.append("start_date must be YYYY-MM-DD (the journey's start)")
    try:
        observed = _when(event.get("observed_at"))
        if sent_at is not None:
            age = (sent_at - observed).total_seconds()
            if age > 180:
                out.append("observed_at more than 3 minutes before sent_at (would be refused as stale)")
            if age < -120:
                out.append("observed_at more than 2 minutes after sent_at (would be refused as future)")
    except ValueError as exc:
        out.append(f"observed_at: {exc}")
    if kind == "POSITION":
        lat, lon = event.get("lat"), event.get("lon")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lon)):
            out.append("lat and lon must be numbers (WGS84 degrees)")
        elif math.isnan(lat + lon) or not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
            out.append("position outside India")
        speed = event.get("speed_kmph", 0.0)
        if not isinstance(speed, int | float) or isinstance(speed, bool) or not 0 <= speed <= 250:
            out.append("speed_kmph must be 0-250")
        sats, hdop = event.get("satellites"), event.get("hdop")
        if sats is not None and (type(sats) is not int or sats < gps.MIN_SATELLITES):
            out.append(f"satellites must be an integer >= {gps.MIN_SATELLITES}")
        if hdop is not None and (not isinstance(hdop, int | float) or not 0 < hdop <= gps.MAX_HDOP):
            out.append(f"hdop must be in (0, {gps.MAX_HDOP}]")
    else:
        if not isinstance(event.get("station_code"), str) or not STATION.match(event.get("station_code") or ""):
            out.append("station_code must match ^[A-Z0-9]{1,8}$")
        if event.get("event") not in ("ARR", "DEP", "PASS"):
            out.append("event must be ARR, DEP or PASS")
    return out


def _certificate(mode: str, checks: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
    failed = [c for c in checks if not c["passed"]]
    return {
        "kind": "Clear Path Nexus live-data conformance certificate",
        "mode": mode,
        "result": "PASS" if not failed else "FAIL",
        "checks": len(checks),
        "failed": len(failed),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "contract": "seva2026/railway_readiness/LIVE_DATA_INTERFACE.md",
        **extra,
        "details": checks,
    }


# ---- producer mode (offline, the feed owner's side) -------------------------------------------------------------
def check_producer(envelopes: list[Any], secret: bytes, source: str) -> dict[str, Any]:
    """Every envelope and event in a producer's sample, in order: shape, signature, unique nonces, increasing
    sequence numbers, and events fresh relative to their envelope."""

    checks, nonces, last_seq, events_seen, events_bad = [], set(), -1, 0, 0
    for n, env in enumerate(envelopes, start=1):
        problems = envelope_problems(env, secret)
        if isinstance(env, dict):
            if env.get("source") != source:
                problems.append(f"source {env.get('source')!r} is not the one being certified ({source})")
            if env.get("nonce") in nonces:
                problems.append("nonce reused (the receiver refuses replays)")
            nonces.add(env.get("nonce"))
            seq = env.get("sequence")
            if type(seq) is int:
                if seq <= last_seq:
                    problems.append(f"sequence {seq} not above the previous {last_seq}")
                last_seq = max(last_seq, seq)
            try:
                sent = _when(env.get("sent_at"))
            except ValueError:
                sent = None
            for k, event in enumerate(env.get("events") or [], start=1):
                events_seen += 1
                if bad := event_problems(event, sent):
                    events_bad += 1
                    problems += [f"event {k}: {p}" for p in bad]
        checks.append({"envelope": n, "passed": not problems, "problems": problems[:20]})
    extra = {"source": source, "envelopes": len(envelopes), "events": events_seen, "events_with_problems": events_bad}
    return _certificate("producer", checks, extra)


# ---- endpoint mode (a deployed receiver in a test environment) --------------------------------------------------
Post = Callable[[dict[str, Any] | str, str | None], tuple[int, Any]]


def check_endpoint(post: Post, source: str, key_id: str, secret: bytes, token: str,
                   now: Callable[[], datetime] | None = None) -> dict[str, Any]:  # fmt: skip
    """Send a battery of good and hostile envelopes; each must get the response the contract promises."""

    now = now or (lambda: datetime.now(IST))
    seq = [int(time.time() * 1000)]

    def envelope(events: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
        seq[0] += 1
        env = {"source": source, "key_id": key_id, "sent_at": now().isoformat(), "nonce": secrets.token_hex(16),
               "sequence": seq[0], "events": events}  # fmt: skip
        env.update({k: v for k, v in overrides.items() if k != "signature"})
        env["signature"] = overrides.get("signature") or sign(env, secret)
        return env

    stamp = now()
    station = {"type": "STATION", "train_number": "12951", "start_date": stamp.date().isoformat(),
               "station_code": "MMCT", "event": "DEP", "observed_at": stamp.isoformat()}  # fmt: skip
    outside = {"type": "POSITION", "train_number": "12951", "start_date": stamp.date().isoformat(), "lat": 51.5,
               "lon": -0.1, "speed_kmph": 80.0, "observed_at": stamp.isoformat()}  # fmt: skip
    good = envelope([station])
    battery: list[tuple[str, Any, str | None, Callable[[int, Any], bool], str]] = [
        ("well-formed signed envelope is received", good, token,
         lambda s, b: s == 200 and isinstance(b, dict) and len(b.get("results", [])) == 1, "200 with one result"),
        ("the same envelope again is refused as a replay", good, token, lambda s, b: s == 401, "401"),
        ("a wrong signature is refused", envelope([station], signature="0" * 64), token,
         lambda s, b: s == 401, "401"),
        ("an envelope sent 10 minutes ago is refused as stale", envelope([station], sent_at=(stamp - timedelta(
            minutes=10)).isoformat()), token, lambda s, b: s == 401, "401"),
        ("a sequence number that does not increase is refused", envelope([station], sequence=1), token,
         lambda s, b: s == 401, "401"),
        (f"more than {MAX_EVENTS} events are refused", envelope([station] * (MAX_EVENTS + 1)), token,
         lambda s, b: s in (401, 413), "401 or 413"),
        ("an unknown key id is refused", envelope([station], key_id="no-such-key"), token,
         lambda s, b: s == 401, "401"),
        ("no bearer token is refused", envelope([station]), None, lambda s, b: s in (401, 403), "401 or 403"),
        ("a body that is not JSON is refused", "{not json", token, lambda s, b: s in (400, 422), "400 or 422"),
        ("a bad event is refused on its own, the batch is received", envelope([outside, station]), token,
         lambda s, b: s == 200 and len(b["results"]) == 2 and not b["results"][0]["accepted"],
         "200 with two results, the first (outside India) refused"),
    ]  # fmt: skip
    checks = []
    for name, body, bearer, ok, expected in battery:
        try:
            status, reply = post(body, bearer)
            passed = bool(ok(status, reply))
        except Exception as exc:  # a crashed check is a failed check, with its reason
            status, reply, passed = None, {"error": f"{type(exc).__name__}: {exc}"[:200]}, False
        detail = reply.get("detail") if isinstance(reply, dict) else None
        checks.append({"check": name, "expected": expected, "status": status, "passed": passed,
                       "detail": str(detail)[:160] if detail else None})  # fmt: skip
    return _certificate("endpoint", checks, {"source": source, "key_id": key_id})


def http_post(url: str) -> Post:
    """POST to <url>/railguard/national/feed/batch with TLS verified; plain HTTP only to this machine."""

    import urllib.error
    import urllib.request

    parts = urlparse(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("use https:// (plain http only to this machine): keys and tokens must not travel in clear")
    target = url.rstrip("/") + "/railguard/national/feed/batch"

    def post(body: dict[str, Any] | str, token: str | None) -> tuple[int, Any]:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(target, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:  # nosec B310 - scheme checked above
                return reply.status, json.loads(reply.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}

    return post


def _secret(path: Path) -> bytes:
    raw = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    if len(raw) < MIN_SECRET_BYTES:
        raise SystemExit(f"key in {path} is shorter than {MIN_SECRET_BYTES} bytes")
    return raw


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail feed-conformance", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    prod = sub.add_parser("producer", help="check a sample of a feed's envelopes offline (JSON lines or a JSON list)")
    prod.add_argument("--file", type=Path, required=True)
    prod.add_argument("--source", required=True)
    prod.add_argument("--key-file", type=Path, required=True, help="file holding the source key in hex")
    end = sub.add_parser("endpoint", help="send good and hostile envelopes to a receiver in a test environment")
    end.add_argument("--url", required=True)
    end.add_argument("--source", required=True)
    end.add_argument("--key-id", required=True)
    end.add_argument("--key-file", type=Path, required=True)
    end.add_argument("--token-file", type=Path, required=True, help="file holding the feed role token")
    for p in (prod, end):
        p.add_argument("--out", type=Path, help="where to write the certificate (JSON)")
    args = parser.parse_args(argv)
    secret = _secret(args.key_file)
    if args.mode == "producer":
        text = args.file.read_text(encoding="utf-8").strip()
        envelopes = (
            json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
        )
        cert = check_producer(envelopes, secret, args.source)
        cert["sample_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    else:
        token = args.token_file.read_text(encoding="utf-8").strip()
        cert = check_endpoint(http_post(args.url), args.source, args.key_id, secret, token)
        cert["receiver"] = urlparse(args.url).hostname
    text = json.dumps(cert, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in cert.items() if k != "details"}, indent=2))
    for c in cert["details"]:
        if not c["passed"]:
            print("FAILED:", json.dumps(c)[:300])
    return 0 if cert["result"] == "PASS" else 1


__all__ = ["canonical", "check_endpoint", "check_producer", "envelope_problems", "event_problems", "http_post"]
