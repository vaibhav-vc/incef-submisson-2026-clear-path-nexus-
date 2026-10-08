"""Live, one-to-one: server-sent event streams for the control console and for each train's cab.

* Console stream (viewer role): the live picture - every running train's position and evidence state, and the
  active threats - pushed every TICK_S when it changes. One snapshot is computed per tick and shared by every
  subscriber, so a thousand screens cost one computation.
* Cab stream (one train): the advisory for that run only, pushed the moment it changes. A cab unit holds a
  *run-scoped capability token* issued by a controller for that run and a limited time: it cannot read any
  other train or the network, and a stolen token is worth one train for a few hours. Tokens are HMAC-signed
  with a key derived from RAILGUARD_CAB_KEY (or, if unset, from the controller token, so rotating that
  revokes every cab token).
* Every stream sends a heartbeat comment every HEARTBEAT_S (proxies keep the connection open) and stops when
  the client goes away. At most MAX_STREAMS streams per process; beyond that a client is refused, not queued.

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


def issue_cab_token(run: str, ttl_s: int = CAB_TOKEN_TTL_S, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    expires = int(clock()) + int(ttl_s)
    payload = f"{run}|{expires}|{secrets.token_hex(8)}".encode()
    mac = hmac.new(_cab_key(), payload, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + mac
    return {"run": run, "token": token, "expires_at": expires}


def cab_token_valid(token: str | None, run: str, clock: Callable[[], float] = time.time) -> bool:
    if not token or len(token) > 300 or token.count(".") != 1:
        return False
    body, mac = token.split(".")
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError:
        return False
    if not hmac.compare_digest(mac, hmac.new(_cab_key(), payload, hashlib.sha256).hexdigest()):
        return False
    parts = payload.decode("utf-8", "replace").split("|")
    return len(parts) == 3 and hmac.compare_digest(parts[0], run) and parts[1].isdigit() and int(parts[1]) > clock()


class Hub:
    """Shared live snapshot of the network (recomputed at most once per tick) and the stream count."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cached: tuple[float, int, str] | None = None  # (computed at, twin version, JSON)
        self.streams = 0

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

    def open(self) -> bool:
        with self.lock:
            if self.streams >= MAX_STREAMS:
                return False
            self.streams += 1
            return True

    def close(self) -> None:
        with self.lock:
            self.streams -= 1


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

    def _compute(self, keys: list[str]) -> dict[str, str]:
        out = {}
        if NETWORK in keys:
            out[NETWORK] = HUB.network(self.twin)
        with self.twin.lock:
            for key in keys:
                if key != NETWORK:
                    out[key] = json.dumps(self.twin.cab(key), separators=(",", ":"), default=str)
        return out

    async def _loop(self) -> None:
        """Recompute as soon as the twin changes (checked every WAKE_S) and at least every TICK_S: a decision or a
        live report reaches its cab within a fraction of a second, a quiet network costs one pass a second."""

        version, computed = None, 0.0
        while self.watchers:
            now = time.monotonic()
            if self.twin.version != version or now - computed >= TICK_S:
                version, computed = self.twin.version, now
                latest = await asyncio.to_thread(self._compute, list(self.watchers))
                async with self.changed:
                    self.latest, self.tick = latest, self.tick + 1
                    self.changed.notify_all()
            await asyncio.sleep(min(WAKE_S, TICK_S))
        self.task = None

    def watch(self, key: str) -> None:
        self.watchers[key] = self.watchers.get(key, 0) + 1
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
    twin: Any, key: str, is_disconnected: Callable[[], Any], max_events: int | None = None, kind: str = "state"
) -> AsyncIterator[bytes]:
    """Push the latest picture for `key` (NETWORK or a run) whenever it changes, with heartbeats."""

    from india_rail.railguard import ops

    if not HUB.open():
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
        HUB.close()
