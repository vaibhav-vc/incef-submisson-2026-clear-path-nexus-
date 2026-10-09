"""Live, one-to-one: server-sent event streams for the control console and for each train's cab.

* Console stream (viewer role): the live picture - every running train's position and evidence state, and the
  active threats - pushed every TICK_S when it changes. One snapshot is computed per tick and shared by every
  subscriber, so a thousand screens cost one computation.
* Cab stream (one train): the advisory for that run only, pushed the moment it changes. A cab unit holds a
  *run-scoped capability token* issued by a controller for that run and a limited time: it cannot read any
  other train or the network, and a stolen token is worth one train for a few hours. Tokens are HMAC-signed
  with a key derived from RAILGUARD_CAB_KEY (or, if unset, from the controller token, so rotating that
  revokes every cab token).
* A controller can revoke one cab link (by its token id, recorded when it was issued) or every link of a run;
  revocations are audit events, re-read from the persisted audit log (RAILGUARD_AUDIT_DIR) after a restart.
* Every stream sends a heartbeat comment every HEARTBEAT_S (proxies keep the connection open) and stops when
  the client goes away. At most MAX_STREAMS streams per process, of which control screens may hold at most
  MAX_CONSOLE_STREAMS (the rest is kept for cab units); beyond that a client is refused, not queued.

Streams carry advice and observations only, never movement authority.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

TICK_S = 1.0
WAKE_S = 0.05
HEARTBEAT_S = 15.0
MAX_STREAMS = 1000
MAX_CONSOLE_STREAMS = 200  # control screens; the rest is kept for cab units, so viewers can never starve them
MAX_STREAMS_PER_CLIENT = 64  # console streams per credential and address
MAX_STREAMS_PER_CAB_LINK = 4  # a cab unit reconnecting may briefly hold two or three
MAX_STREAM_S = 12 * 3600  # a console stream is re-opened (and re-authorised) at least this often
CAB_TOKEN_TTL_S = 12 * 3600
_PROCESS_KEY = secrets.token_bytes(32)  # demo mode without any configured secret: tokens die with the process


def _cab_key() -> bytes:
    explicit = os.environ.get("RAILGUARD_CAB_KEY", "")
    if len(explicit) >= 32:
        return hashlib.sha256(b"railguard-cab|" + explicit.encode()).digest()
    controller = os.environ.get("RAILGUARD_CONTROLLER_TOKEN", "")
    if controller:
        return hashlib.sha256(b"railguard-cab-from-controller|" + controller.encode()).digest()
    return _PROCESS_KEY


MAX_CAB_TOKEN_TTL_S = 24 * 3600
_revoked_ids: dict[str, float] = {}  # token id -> when the revocation can be forgotten (every such token expired)
_revoked_runs: dict[str, int] = {}  # run -> links issued at or before this time (ms) are revoked
_revoked_lock = threading.Lock()


def issue_cab_token(run: str, ttl_s: int = CAB_TOKEN_TTL_S, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """`run` names the journey absolutely (train number and start date, e.g. 12951@2026-10-09), so a link stays
    with its train however the twin numbers its runs from day to day."""

    now = clock()
    expires, issued_ms = int(now) + int(ttl_s), int(now * 1000)
    token_id = secrets.token_hex(8)  # names the link in the audit log (and for revocation); it is not the secret
    payload = f"{run}|{expires}|{token_id}|{issued_ms}".encode()
    mac = hmac.new(_cab_key(), payload, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + mac
    return {"run": run, "token": token, "token_id": token_id, "expires_at": expires}


def revoke(journey: str, token_id: str | None = None, clock: Callable[[], float] = time.time) -> None:
    """Revoke one cab link (its token id) or, with no id, every link of the journey issued until now. A
    revocation only ever widens: a later "revoke all" with an earlier clock never re-validates a link."""

    now = clock()
    with _revoked_lock:
        if token_id:
            _revoked_ids[token_id] = max(_revoked_ids.get(token_id, 0.0), now + MAX_CAB_TOKEN_TTL_S)
        else:
            _revoked_runs[journey] = max(_revoked_runs.get(journey, -1), int(now * 1000))
        for k in [k for k, until in _revoked_ids.items() if until < now]:
            del _revoked_ids[k]


def revocations() -> dict[str, Any]:
    """The revocations in force (for checkpoints, so a restored or standby server keeps them)."""

    with _revoked_lock:
        return {"ids": dict(_revoked_ids), "journeys": dict(_revoked_runs)}


def apply_revocations(saved: dict[str, Any]) -> None:
    with _revoked_lock:
        for k, until in (saved.get("ids") or {}).items():
            if isinstance(k, str) and isinstance(until, int | float):
                _revoked_ids[k] = max(_revoked_ids.get(k, 0.0), float(until))
        for k, when in (saved.get("journeys") or {}).items():
            if isinstance(k, str) and isinstance(when, int):
                _revoked_runs[k] = max(_revoked_runs.get(k, -1), when)


def load_revocations(events_path: Any, key: bytes | None = None, clock: Callable[[], float] = time.time) -> int:
    """Re-apply the revocations of the last day from a persisted audit log (after a restart). Only records whose
    hash (and, with the audit key, MAC) verify are used; anything else in the file is skipped."""

    from datetime import datetime

    from india_rail.railguard.evidence import checksum

    count, horizon = 0, clock() - MAX_CAB_TOKEN_TTL_S
    try:
        handle = open(events_path, encoding="utf-8")
    except OSError:
        return 0
    with handle:
        for line in handle:
            if '"CAB_LINK_REVOKED"' not in line:
                continue
            try:
                event = json.loads(line)
                body = {k: v for k, v in event.items() if k not in ("hash", "mac")}
                if event.get("type") != "CAB_LINK_REVOKED" or checksum(body) != event["hash"]:
                    continue
                if key is not None:
                    mac = hmac.new(key, event["hash"].encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(str(event.get("mac", "")).encode(), mac.encode()):
                        continue
                at = datetime.fromisoformat(event["at"]).timestamp()
                details = event["details"]
                journey, token_id = details["journey"], details.get("token_id")
                if not isinstance(journey, str) or not (token_id is None or isinstance(token_id, str)):
                    continue
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if at >= horizon:
                revoke(journey, token_id, clock=lambda at=at: at)
                count += 1
    return count


def cab_token_valid(token: str | None, run: str, clock: Callable[[], float] = time.time) -> bool:
    if not token or len(token) > 300 or token.count(".") != 1 or not token.isascii():
        return False
    body, mac = token.split(".")
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError:
        return False
    if not hmac.compare_digest(mac.encode(), hmac.new(_cab_key(), payload, hashlib.sha256).hexdigest().encode()):
        return False
    parts = payload.decode("utf-8", "replace").split("|")
    if len(parts) != 4 or not hmac.compare_digest(parts[0].encode(), run.encode()):
        return False
    if not (parts[1].isdigit() and parts[3].isdigit()) or int(parts[1]) <= clock():
        return False
    with _revoked_lock:
        return parts[2] not in _revoked_ids and int(parts[3]) > _revoked_runs.get(run, -1)


class Hub:
    """Shared live snapshot of the network (recomputed at most once per tick) and the stream count."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cached: tuple[float, int, str] | None = None  # (computed at, twin version, JSON)
        self.streams = 0
        self.pools: dict[str, int] = {}
        self.by_client: dict[tuple[str, str], int] = {}

    def network(self, twin: Any) -> str:
        now = time.monotonic()
        with self.lock:
            if self.cached and now - self.cached[0] < TICK_S:
                return self.cached[2]
        positions = twin.positions()
        with twin.lock:
            threats = [t.to_dict() for t in twin.threats.active()]
            minute, version = twin.now, twin.version
        body = json.dumps({"minute": round(minute, 2), "version": version, "positions": positions,
                           "threats": threats}, separators=(",", ":"))  # fmt: skip
        with self.lock:
            self.cached = (now, version, body)
        return body

    def open(self, pool: str = "console", client: str = "") -> bool:
        """A stream slot, or False: at most MAX_STREAMS in all, at most MAX_CONSOLE_STREAMS for control screens
        (the rest are kept for cab units), and a cap per client (console) or per cab link."""

        cap = MAX_STREAMS_PER_CAB_LINK if pool == "cab" else MAX_STREAMS_PER_CLIENT
        with self.lock:
            if self.streams >= MAX_STREAMS or self.by_client.get((pool, client), 0) >= cap:
                return False
            if pool != "cab" and self.pools.get(pool, 0) >= MAX_CONSOLE_STREAMS:
                return False
            self.streams += 1
            self.pools[pool] = self.pools.get(pool, 0) + 1
            self.by_client[(pool, client)] = self.by_client.get((pool, client), 0) + 1
            return True

    def close(self, pool: str = "console", client: str = "") -> None:
        with self.lock:
            self.streams -= 1
            self.pools[pool] -= 1
            self.by_client[(pool, client)] -= 1
            if not self.by_client[(pool, client)]:
                del self.by_client[(pool, client)]


HUB = Hub()


def _event(kind: str, data: str, ident: int) -> bytes:
    return f"id: {ident}\nevent: {kind}\ndata: {data}\n\n".encode()


NETWORK = "*"


class Broadcaster:
    """One computation per tick for every stream on an event loop: the network picture (if anyone watches it)
    and the advisory of every subscribed run, under one twin lock, in one worker thread; then every stream is
    woken together. A thousand streams cost one computation a tick, not a thousand."""

    def __init__(self, twin: Any) -> None:
        self.twin = twin
        self.watchers: dict[str, int] = {}
        self.latest: dict[str, str] = {}
        self.tick = 0
        self.changed = asyncio.Condition()
        self.task: asyncio.Task | None = None
        self.new_watcher = False  # a stream just opened: compute now, not at the next tick

    def _compute(self, keys: list[str]) -> dict[str, str]:
        out = {}
        if NETWORK in keys:
            out[NETWORK] = HUB.network(self.twin)
        for key in keys:
            if key != NETWORK:
                with self.twin.lock:  # one run at a time: a feed batch or a decision never waits for every cab
                    advisory = self.twin.cab(key)
                out[key] = json.dumps(advisory, separators=(",", ":"), default=str)
        return out

    async def _loop(self) -> None:
        """Recompute as soon as the twin changes (checked every WAKE_S) and at least every TICK_S: a decision or a
        live report reaches its cab within a fraction of a second, a quiet network costs one pass a second."""

        version, computed = None, 0.0
        while self.watchers:
            now = time.monotonic()
            if self.twin.version != version or now - computed >= TICK_S or self.new_watcher:
                version, computed, self.new_watcher = self.twin.version, now, False
                latest = await asyncio.to_thread(self._compute, list(self.watchers))
                async with self.changed:
                    self.latest, self.tick = latest, self.tick + 1
                    self.changed.notify_all()
            await asyncio.sleep(min(WAKE_S, TICK_S))
        self.task = None

    def watch(self, key: str) -> None:
        self.watchers[key] = self.watchers.get(key, 0) + 1
        if key not in self.latest:
            self.new_watcher = True
        if self.task is None:
            self.task = asyncio.get_running_loop().create_task(self._loop())

    def unwatch(self, key: str) -> None:
        self.watchers[key] -= 1
        if not self.watchers[key]:
            del self.watchers[key]


_BROADCASTERS: dict[tuple[int, int], Broadcaster] = {}


def broadcaster(twin: Any) -> Broadcaster:
    key = (id(asyncio.get_running_loop()), id(twin))
    if key not in _BROADCASTERS:
        if len(_BROADCASTERS) > 64:  # loops of finished test clients or replaced twins
            _BROADCASTERS.clear()
        _BROADCASTERS[key] = Broadcaster(twin)
    return _BROADCASTERS[key]


async def stream(
    twin: Any,
    key: str,
    is_disconnected: Callable[[], Any],
    max_events: int | None = None,
    kind: str = "state",
    allowed: Callable[[], bool] | None = None,
    pool: str = "console",
    client: str = "",
) -> AsyncIterator[bytes]:
    """Push the latest picture for `key` (NETWORK or a run) whenever it changes, with heartbeats.

    `allowed` is re-checked before every event and heartbeat: a cab link revoked, or expiring, while its stream
    is open ends that stream (a `revoked` event) instead of serving the train's advisory any longer."""

    from india_rail.railguard import ops

    if not HUB.open(pool, client):
        yield b'event: refused\ndata: {"detail": "too many live streams on this server"}\n\n'
        return
    hub = broadcaster(twin)
    hub.watch(key)
    ops.OPS.subscribers += 1
    try:
        last, sent, seen = None, 0, -1
        spoke = time.monotonic()
        yield b"retry: 3000\n\n"
        while max_events is None or sent < max_events:
            body = None
            async with hub.changed:
                try:
                    await asyncio.wait_for(hub.changed.wait_for(lambda seen=seen: hub.tick != seen), HEARTBEAT_S)
                    seen, body = hub.tick, hub.latest.get(key)
                except TimeoutError:
                    pass
            if await is_disconnected():
                return
            if allowed is not None and not allowed():
                yield b'event: revoked\ndata: {"detail": "this cab link is no longer valid"}\n\n'
                return
            if body is not None and body != last:
                sent += 1
                last, spoke = body, time.monotonic()
                yield _event(kind, body, sent)
            elif time.monotonic() - spoke >= HEARTBEAT_S:  # nothing new: keep the connection visibly alive
                spoke = time.monotonic()
                yield b": heartbeat\n\n"
    finally:
        hub.unwatch(key)
        ops.OPS.subscribers -= 1
        HUB.close(pool, client)
