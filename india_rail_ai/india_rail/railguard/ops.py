"""Production operations: power (UPS), state checkpoints, health, metrics and structured logs.

Power - a UPS watched through Network UPS Tools (NUT, the standard open-source UPS daemon; any UPS that NUT
supports, USB or network). RAILGUARD_UPS="<ups>@<host>[:3493]". Every POLL_S:
  OL  on line                    normal;
  OB  on battery                 POWER_ON_BATTERY warning on the console, state checkpointed at once and then
                                 every CHECKPOINT_ON_BATTERY_S;
  LB / FSD, or runtime < LOW_RUNTIME_S
                                 POWER_CRITICAL: state checkpointed, controller approvals paused (read-only:
                                 a decision must not be half-written when power goes), hand over to the standby
                                 site or manual procedure; the feed keeps flowing into the checkpoint;
  NUT unreachable                POWER_MONITOR_LOST warning (a UPS that cannot be seen is not a UPS).
Without RAILGUARD_UPS power is not monitored and /health/ready says so.

Checkpoints - RAILGUARD_STATE_DIR: the twin's dynamic state (plans, holds, pending approvals, evidence,
flags, acknowledgements) and the feed gateway's replay counters, written atomically (temporary file, fsync,
rename) every CHECKPOINT_S and signed with RAILGUARD_CHECKPOINT_KEY (HMAC-SHA256). On start the newest
checkpoint is restored only if its signature holds, it was taken on the same timetable data and it is younger
than MAX_RESTORE_AGE_S; evidence keeps its own timestamps, so restored positions age to STALE as they should.
The audit chain is already persisted append-only (RAILGUARD_AUDIT_DIR) and continues across restarts.

Health - /health/live: the process answers. /health/ready: security configured, the national twin loaded,
power not critical, checkpoints writable when configured. Load balancers route on ready.

Metrics - /metrics in Prometheus text format (viewer role): requests by route and status, latency,
feed events, active threats by type, power state, checkpoint age, live stream subscribers.

Logs - RAILGUARD_LOG_JSON=1: one JSON object per request (time, request id, method, route template, status,
milliseconds). Never tokens, bodies or query strings.

Clock - RAILGUARD_NTP="samay1.nic.in,time.nplindia.org" (CERT-In Directions 2022: ICT clocks synchronised with
the NTP servers of NIC or NPL). Every NTP_POLL_S the offset is measured (SNTP, RFC 4330; a reply must echo our
transmit time, so an off-path forgery is refused). An offset above MAX_CLOCK_OFFSET_S raises CLOCK_DRIFT on every
console and fails readiness: audit timestamps, feed freshness and evidence ageing all depend on the clock. An
unreachable NTP server is reported (notes, metrics) but does not by itself take the service out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import statistics
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("railguard.ops")

POLL_S = 5.0
LOW_RUNTIME_S = 300
CHECKPOINT_S = 60.0
CHECKPOINT_ON_BATTERY_S = 10.0
MAX_RESTORE_AGE_S = 1800
NUT_PORT = 3493
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
NTP_POLL_S = 300.0
MAX_CLOCK_OFFSET_S = 1.0
NTP_EPOCH_OFFSET = 2_208_988_800  # seconds from 1900-01-01 (NTP era 0) to 1970-01-01


def sntp_offset(host: str, port: int = 123, timeout_s: float = 2.0, clock=time.time) -> float:
    """Server clock minus local clock, in seconds (SNTP v4 client, RFC 4330).

    The request's transmit field is random (RFC 4330 allows any value; the send time is kept here) and the reply
    must echo it, and the socket is connected to the server, so the kernel drops datagrams from any other address:
    an off-path sender can neither guess the echo nor use another source address."""

    def read(b: bytes) -> float:
        return int.from_bytes(b[:4], "big") - NTP_EPOCH_OFFSET + int.from_bytes(b[4:8], "big") / 2**32

    request = bytes([0x23]) + bytes(39) + secrets.token_bytes(8)  # LI 0, version 4, mode 3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_s)
        sock.connect((host, port))
        t1 = clock()
        sock.send(request)
        reply = sock.recv(512)
    t4 = clock()
    if len(reply) < 48:
        raise OSError("NTP reply too short")
    leap, mode, stratum = reply[0] >> 6, reply[0] & 0x7, reply[1]
    if mode != 4 or leap == 3 or not 1 <= stratum <= 15:
        raise OSError(f"NTP server not synchronised (mode {mode}, leap {leap}, stratum {stratum})")
    if reply[24:32] != request[40:48]:
        raise OSError("NTP reply does not echo our request (refused as a forgery or a stray reply)")
    t2, t3 = read(reply[32:40]), read(reply[40:48])
    return ((t2 - t1) + (t3 - t4)) / 2


def _agreeing(answers: list[float]) -> list[float]:
    """The largest group of offsets that all lie within MAX_CLOCK_OFFSET_S of each other."""

    values = sorted(answers)
    best: list[float] = []
    for i in range(len(values)):
        group = [v for v in values[i:] if v - values[i] <= MAX_CLOCK_OFFSET_S]
        if len(group) > len(best):
            best = group
    return best


# ---- power -----------------------------------------------------------------------------------------
class NutError(OSError):
    pass


class NutClient:
    """Minimal read-only client for the NUT network protocol (RFC 9271): GET VAR <ups> <var>."""

    def __init__(self, ups: str, host: str = "127.0.0.1", port: int = NUT_PORT, timeout_s: float = 3.0):
        self.ups, self.host, self.port, self.timeout_s = ups, host, port, timeout_s

    @classmethod
    def from_spec(cls, spec: str) -> NutClient:
        ups, _, where = spec.partition("@")
        host, _, port = (where or "127.0.0.1").partition(":")
        if not ups or not ups.replace("-", "").replace("_", "").isalnum():
            raise ValueError("RAILGUARD_UPS must look like <ups>@<host>[:port]")
        return cls(ups, host, int(port or NUT_PORT))

    def get(self, names: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        with socket.create_connection((self.host, self.port), timeout=self.timeout_s) as sock:
            stream = sock.makefile("rwb")
            for name in names:
                stream.write(f"GET VAR {self.ups} {name}\n".encode())
                stream.flush()
                line = stream.readline(512).decode("ascii", "replace").strip()
                if line.startswith("ERR VAR-NOT-SUPPORTED"):
                    continue
                if not line.startswith(f"VAR {self.ups} {name} "):
                    raise NutError(f"NUT: {line[:80]}")
                out[name] = line.split(" ", 3)[3].strip('"')
            stream.write(b"LOGOUT\n")
            stream.flush()
        return out


@dataclass
class PowerState:
    monitored: bool
    status: str = "UNKNOWN"  # NUT ups.status, e.g. "OL", "OB DISCHRG", "OB LB"
    charge_pct: float | None = None
    runtime_s: float | None = None
    error: str | None = None
    checked_at: float = 0.0

    @property
    def flags(self) -> set[str]:
        return set(self.status.split())

    @property
    def level(self) -> str:
        """NORMAL, UNMONITORED, MONITOR_LOST, ON_BATTERY or CRITICAL."""

        if not self.monitored:
            return "UNMONITORED"
        if self.error:
            return "MONITOR_LOST"
        if self.flags & {"LB", "FSD"} or (self.runtime_s is not None and "OB" in self.flags
                                          and self.runtime_s < LOW_RUNTIME_S):  # fmt: skip
            return "CRITICAL"
        if "OB" in self.flags:
            return "ON_BATTERY"
        return "NORMAL"

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "status": self.status, "charge_pct": self.charge_pct,
                "runtime_s": self.runtime_s, "error": self.error, "checked_at": self.checked_at}  # fmt: skip


def read_power(client: NutClient | None, clock=time.time) -> PowerState:
    if client is None:
        return PowerState(monitored=False, checked_at=clock())
    try:
        v = client.get(["ups.status", "battery.charge", "battery.runtime"])
    except (OSError, ValueError) as exc:
        return PowerState(monitored=True, error=str(exc)[:120], checked_at=clock())
    num = lambda k: float(v[k]) if k in v and v[k].replace(".", "", 1).isdigit() else None  # noqa: E731
    return PowerState(True, v.get("ups.status", "UNKNOWN"), num("battery.charge"), num("battery.runtime"),
                      None, clock())  # fmt: skip


POWER_ALERTS = {
    "ON_BATTERY": ("POWER_ON_BATTERY", "WARNING", "Mains power lost: the control system is on UPS battery. State is "
                   "checkpointed every 10 s. Prepare the standby site."),
    "CRITICAL": ("POWER_CRITICAL", "CRITICAL", "UPS battery low: approvals are paused and state is checkpointed. "
                 "Hand over to the standby site or the manual procedure now."),
    "MONITOR_LOST": ("POWER_MONITOR_LOST", "WARNING", "The UPS cannot be read: power state unknown. Check the NUT "
                     "daemon and the UPS link."),
}  # fmt: skip


# ---- checkpoints -------------------------------------------------------------------------------------
def _revocations() -> dict[str, Any]:
    from india_rail.railguard import live

    return live.revocations()


class Checkpointer:
    def __init__(self, folder: Path, key: bytes, clock=time.time):
        if len(key) < 32:
            raise ValueError("RAILGUARD_CHECKPOINT_KEY must be at least 32 bytes")
        self.folder, self.key, self.clock = folder, key, clock
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "railguard_state.json"
        self.last_saved: float | None = None
        self.last_error: str | None = None

    def _mac(self, body: bytes) -> str:
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def save(self, twin: Any, gateway: Any | None = None, reason: str = "periodic") -> dict[str, Any]:
        with twin.lock:
            state = {
                "version": 1,
                "saved_at": self.clock(),
                "reason": reason,
                "data_checksum": twin.data.checksum,
                "now": twin.now,
                "dynamic": twin.dynamic_state(),
                "feed": {"last_sequence": dict(gateway.last_sequence)} if gateway is not None else None,
                "cab_revocations": _revocations(),
            }
        body = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode()
        record = json.dumps({"mac": self._mac(body), "state": body.decode()}).encode()
        fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(record)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self.folder, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            self.last_error = str(exc)[:120]
            Path(tmp).unlink(missing_ok=True)
            raise
        self.last_saved, self.last_error = state["saved_at"], None
        return {"saved_at": state["saved_at"], "bytes": len(record), "reason": reason}

    def load(self, data_checksum: str) -> dict[str, Any] | None:
        """The newest checkpoint if it is authentic, of the same data and recent enough; else None (with a log)."""

        if not self.path.exists():
            return None
        try:
            record = json.loads(self.path.read_bytes())
            body = record["state"].encode()
            if not hmac.compare_digest(record["mac"], self._mac(body)):
                log.error("checkpoint signature invalid: not restored")
                return None
            state = json.loads(body)
        except (ValueError, KeyError, TypeError):
            log.error("checkpoint unreadable: not restored")
            return None
        if state.get("data_checksum") != data_checksum:
            log.warning("checkpoint taken on other timetable data: not restored")
            return None
        if self.clock() - float(state["saved_at"]) > MAX_RESTORE_AGE_S:
            log.warning("checkpoint older than %s s: not restored", MAX_RESTORE_AGE_S)
            return None
        return state


def restore(twin: Any, gateway: Any | None, state: dict[str, Any]) -> None:
    with twin.lock:
        twin.restore(state["dynamic"])
        if state.get("cab_revocations"):
            from india_rail.railguard import live

            live.apply_revocations(state["cab_revocations"])
        if gateway is not None and state.get("feed"):
            for source, seq in state["feed"]["last_sequence"].items():
                gateway.last_sequence[source] = max(gateway.last_sequence.get(source, -1), int(seq))
        twin.audit.record(int(twin.now * 60), "STATE_RESTORED", "system",
                          {"saved_at": state["saved_at"], "reason": state.get("reason")})  # fmt: skip


# ---- metrics -------------------------------------------------------------------------------------------
@dataclass
class Metrics:
    requests: dict[tuple[str, str, int], int] = field(default_factory=lambda: defaultdict(int))
    latency: dict[str, list[int]] = field(default_factory=dict)  # route -> bucket counts (+inf last)
    latency_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self.lock:
            self.requests[(method, route, status)] += 1
            buckets = self.latency.setdefault(route, [0] * (len(LATENCY_BUCKETS) + 1))
            for k, edge in enumerate(LATENCY_BUCKETS):
                if seconds <= edge:
                    buckets[k] += 1
            buckets[-1] += 1
            self.latency_sum[route] += seconds

    def inc(self, name: str, value: float = 1.0) -> None:
        with self.lock:
            self.counters[name] += value

    def render(
        self, gauges: dict[str, float] | None = None, labelled: dict[str, dict[str, float]] | None = None
    ) -> str:
        esc = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        lines = ["# TYPE railguard_requests_total counter"]
        with self.lock:
            for (method, route, status), n in sorted(self.requests.items()):
                lines.append(
                    f'railguard_requests_total{{method="{method}",route="{esc(route)}",status="{status}"}} {n}'
                )
            lines.append("# TYPE railguard_request_seconds histogram")
            for route, buckets in sorted(self.latency.items()):
                for edge, n in zip((*LATENCY_BUCKETS, "+Inf"), buckets, strict=True):
                    lines.append(f'railguard_request_seconds_bucket{{route="{esc(route)}",le="{edge}"}} {n}')
                lines.append(f'railguard_request_seconds_sum{{route="{esc(route)}"}} {self.latency_sum[route]:.6f}')
                lines.append(f'railguard_request_seconds_count{{route="{esc(route)}"}} {buckets[-1]}')
            for name, value in sorted(self.counters.items()):
                lines.append(f"# TYPE railguard_{name} counter")
                lines.append(f"railguard_{name} {value:g}")
        for name, value in sorted((gauges or {}).items()):
            lines.append(f"# TYPE railguard_{name} gauge")
            lines.append(f"railguard_{name} {value:g}")
        for name, series in sorted((labelled or {}).items()):
            lines.append(f"# TYPE railguard_{name} gauge")
            for label, value in sorted(series.items()):
                lines.append(f'railguard_{name}{{type="{esc(label)}"}} {value:g}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()  # one per process: survives a supervisor reset


class ObservabilityMiddleware:
    """Pure ASGI (streams pass through untouched): request id, metrics and one JSON access-log line."""

    def __init__(self, app, metrics: Metrics):
        self.app, self.metrics = app, metrics
        self.access = logging.getLogger("railguard.access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:16]
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            elapsed = time.perf_counter() - started
            self.metrics.observe(scope.get("method", "?"), route, status, elapsed)
            fields = {"request_id": request_id, "method": scope.get("method"), "route": route, "status": status,
                      "ms": round(elapsed * 1000, 1)}  # fmt: skip
            self.access.info("request", extra=fields)


class JsonFormatter(logging.Formatter):
    FIELDS = ("request_id", "method", "route", "status", "ms", "event")

    def format(self, record: logging.LogRecord) -> str:
        out = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
               "logger": record.name, "message": record.getMessage()}  # fmt: skip
        for key in self.FIELDS:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(out)


def configure_logging() -> None:
    if os.environ.get("RAILGUARD_LOG_JSON") == "1":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root = logging.getLogger()
        root.handlers[:] = [handler]
        root.setLevel(logging.INFO)


# ---- the operations supervisor --------------------------------------------------------------------------
class Operations:
    """Owns the power monitor and the checkpoint loop for one process."""

    def __init__(self) -> None:
        self.metrics = METRICS
        self.started_at = time.time()
        spec = os.environ.get("RAILGUARD_UPS")
        self.nut = NutClient.from_spec(spec) if spec else None
        self.power = PowerState(monitored=self.nut is not None)
        folder, key = os.environ.get("RAILGUARD_STATE_DIR"), os.environ.get("RAILGUARD_CHECKPOINT_KEY", "")
        self.config_error: str | None = None
        self.checkpointer: Checkpointer | None = None
        if folder:
            try:
                self.checkpointer = Checkpointer(Path(folder), key.encode())
            except (ValueError, OSError) as exc:
                self.config_error = str(exc)[:160]
        self.twin: Any = None
        self.gateway: Any = None
        self.twin_ready = False
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.subscribers = 0
        self.ntp = [h.strip() for h in os.environ.get("RAILGUARD_NTP", "").split(",") if h.strip()]
        self.clock_offset_s: float | None = None
        self.clock_checked_at: float | None = None
        self.clock_error: str | None = None
        self._last_offset: float | None = None

    @property
    def read_only(self) -> bool:
        return self.power.level == "CRITICAL"

    def attach(self, twin: Any, gateway: Any | None) -> None:
        """Bind the live twin (and feed gateway); restore the newest valid checkpoint into them."""

        self.twin, self.gateway = twin, gateway
        if self.checkpointer is not None:
            state = self.checkpointer.load(twin.data.checksum)
            if state is not None:
                restore(twin, gateway, state)
                log.info("state restored", extra={"event": "STATE_RESTORED"})
        self.twin_ready = True

    def poll_power(self) -> None:
        before = self.power.level
        self.power = read_power(self.nut)
        after = self.power.level
        if self.twin is not None:
            self._apply_power_alert()
        if after != before:
            self.metrics.inc("power_transitions_total")
            log.warning("power %s -> %s", before, after, extra={"event": "POWER_" + after})
            if after in ("ON_BATTERY", "CRITICAL"):
                self.checkpoint(f"power {after.lower()}")

    def _apply_power_alert(self) -> None:
        twin = self.twin
        with twin.lock:
            twin.system_alerts = {k: v for k, v in twin.system_alerts.items() if not k.startswith("POWER_")}
            alert = POWER_ALERTS.get(self.power.level)
            if alert:
                twin.system_alerts[alert[0]] = {"severity": alert[1], "detail": alert[2], "power": self.power.to_dict()}
            twin.refresh(settled=True)  # a measured power state, not a missed report

    def check_clock(self, measure=sntp_offset) -> None:
        """Measure the clock against every configured NTP server; raise CLOCK_DRIFT if it is off.

        With two or more servers, the offset is the median of the largest group that agrees within
        MAX_CLOCK_OFFSET_S, and is used only if that group is a majority of the servers that answered: two servers
        that disagree prove nothing, and one faulty or forged server is outvoted by two good ones. With a single
        configured server, a drift is believed only when it is measured at two checks in a row. A server named
        twice counts once."""

        hosts = list(dict.fromkeys(self.ntp))
        if not hosts:
            return
        errors, answers = [], []
        for host in hosts:
            try:
                answers.append(measure(host))
            except OSError as exc:
                errors.append(f"{host}: {exc}"[:120])
        notes: list[str] = []
        if not answers:
            self.metrics.inc("ntp_failures_total")
            log.warning("NTP unreachable", extra={"event": "NTP_UNREACHABLE"})
        elif len(hosts) == 1:
            offset = answers[0]
            repeated = self._last_offset is not None and abs(offset - self._last_offset) <= MAX_CLOCK_OFFSET_S
            self._last_offset = offset
            if abs(offset) <= MAX_CLOCK_OFFSET_S or repeated:
                self.clock_offset_s, self.clock_checked_at = offset, time.time()
            else:
                notes.append(f"one measurement puts the clock {offset:+.1f} s off: confirming at the next check")
        else:
            group = _agreeing(answers)
            if 2 * len(group) > len(answers):
                self.clock_offset_s, self.clock_checked_at = statistics.median(group), time.time()
            else:
                notes.append(f"NTP servers disagree ({', '.join(f'{a:+.1f} s' for a in sorted(answers))}): "
                             "no majority, the last agreed reading is kept")  # fmt: skip
        self.clock_error = "; ".join(notes + errors) or None
        if self.twin is not None:
            drift = self.clock_offset_s is not None and abs(self.clock_offset_s) > MAX_CLOCK_OFFSET_S
            with self.twin.lock:
                had = "CLOCK_DRIFT" in self.twin.system_alerts
                if drift:
                    self.twin.system_alerts["CLOCK_DRIFT"] = {
                        "severity": "WARNING",
                        "detail": f"Server clock {self.clock_offset_s:+.1f} s from NTP: timestamps and data ageing "
                        "are unreliable until it is corrected",
                    }
                else:
                    self.twin.system_alerts.pop("CLOCK_DRIFT", None)
                if drift != had:
                    self.twin.refresh(settled=True)  # a fresh measurement

    def checkpoint(self, reason: str = "periodic") -> dict[str, Any] | None:
        if self.checkpointer is None or self.twin is None:
            return None
        try:
            result = self.checkpointer.save(self.twin, self.gateway, reason)
        except OSError:
            self.metrics.inc("checkpoint_failures_total")
            log.exception("checkpoint failed", extra={"event": "CHECKPOINT_FAILED"})
            return None
        self.metrics.inc("checkpoints_total")
        return result

    def run(self) -> None:
        last_checkpoint, last_clock = time.time(), 0.0
        while not self.stop.wait(POLL_S):
            self.poll_power()
            if time.time() - last_clock >= NTP_POLL_S:
                self.check_clock()
                last_clock = time.time()
            every = CHECKPOINT_ON_BATTERY_S if self.power.level in ("ON_BATTERY", "CRITICAL") else CHECKPOINT_S
            if time.time() - last_checkpoint >= every:
                self.checkpoint()
                last_checkpoint = time.time()

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="railguard-ops", daemon=True)
            self.thread.start()

    def shutdown(self) -> None:
        self.stop.set()
        self.checkpoint("shutdown")

    # ---- health --------------------------------------------------------------------------------------
    def readiness(self) -> dict[str, Any]:
        from india_rail.security import configuration_problems

        checks = {
            "security_configured": not configuration_problems(),
            "national_twin_loaded": self.twin_ready,
            "power": self.power.level != "CRITICAL",
            "checkpoints": self.config_error is None
            and (self.checkpointer is None or self.checkpointer.last_error is None),
            "clock": self.clock_offset_s is None or abs(self.clock_offset_s) <= MAX_CLOCK_OFFSET_S,
        }
        notes = []
        if not self.ntp:
            notes.append("clock not checked against NTP (RAILGUARD_NTP unset; CERT-In: use NIC/NPL servers)")
        elif self.clock_error:
            notes.append(f"NTP: {self.clock_error}")
        if self.nut is None:
            notes.append("power not monitored (RAILGUARD_UPS unset)")
        if self.config_error:
            notes.append(f"checkpoints misconfigured: {self.config_error}")
        elif self.checkpointer is None:
            notes.append("state checkpoints off (RAILGUARD_STATE_DIR unset)")
        return {"ready": all(checks.values()), "checks": checks, "power": self.power.to_dict(),
                "read_only": self.read_only, "notes": notes}  # fmt: skip

    def gauges(self) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        level = {"NORMAL": 0, "UNMONITORED": 0, "MONITOR_LOST": 1, "ON_BATTERY": 2, "CRITICAL": 3}[self.power.level]
        gauges = {"uptime_seconds": time.time() - self.started_at, "power_level": level,
                  "read_only": int(self.read_only), "stream_subscribers": self.subscribers,
                  "twin_ready": int(self.twin_ready)}  # fmt: skip
        if self.power.charge_pct is not None:
            gauges["ups_battery_charge_pct"] = self.power.charge_pct
        if self.checkpointer is not None and self.checkpointer.last_saved:
            gauges["checkpoint_age_seconds"] = time.time() - self.checkpointer.last_saved
        if self.clock_offset_s is not None:
            gauges["clock_offset_seconds"] = self.clock_offset_s
        threats: dict[str, float] = defaultdict(float)
        if self.twin is not None:
            gauges["twin_minute"] = self.twin.now
            for t in self.twin.threats.active():
                threats[t.type] += 1
        labelled = {"threats_active": dict(threats)}
        fixes = getattr(self.gateway, "fix_outcomes", None)
        if fixes:
            labelled["gnss_fixes"] = {k: float(v) for k, v in fixes.items()}  # since start: a field trial's tally
        return gauges, labelled


OPS = Operations()


def reset() -> Operations:
    """A fresh supervisor from the current environment (start-up and tests)."""

    global OPS
    OPS.stop.set()
    OPS = Operations()
    return OPS
