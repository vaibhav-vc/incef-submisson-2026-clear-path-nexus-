"""Load test of the live service on the real network: streams, feed and one-to-one push latency.

    python -m india_rail loadtest [--consoles 50] [--cabs 500] [--seconds 60]

Starts the real service (uvicorn, one worker, the national twin on the current timetable) on a local port and,
at the same time:
* `consoles` control screens hold the network stream;
* `cabs` cab units each hold their own train's stream with their own run-scoped token;
* a feed posts signed position batches (250 fixes, the gateway's maximum) every second;
* every 5 s a controller records a disruption on a train whose cab is listening, and the time until that cab's
  stream shows the change is measured - the one-to-one push latency.
Reported: time to first event, push latency p50/p95/p99, feed batch latency, refused or dropped streams.
On one machine the clients compete with the server for CPU, so the figures are conservative.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).resolve().parents[2] / "seva2026" / "evidence" / "live" / "loadtest.json"
FEED_SECRET = bytes(range(32))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(int(q * len(ordered)), len(ordered) - 1)], 1)


async def _run(base: str, twin: Any, consoles: int, cabs: int, seconds: float) -> dict[str, Any]:
    import httpx

    from india_rail.railguard.livefeed import FeedSimulator

    running = [k for k in twin.running() if twin.position(k)["state"] == "RUNNING"][:cabs]
    first_event: list[float] = []
    push_ms: list[float] = []
    feed_ms: list[float] = []
    dropped = refused = 0
    changes: dict[str, tuple[float, float]] = {}  # run -> (when the controller acted, deviation before it)
    started = time.perf_counter()
    stop = started + seconds
    limits = httpx.Limits(max_connections=consoles + cabs + 20, max_keepalive_connections=consoles + cabs + 20)

    actions: dict[str, int] = {}
    async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(30.0, read=None), limits=limits) as http:
        tokens = {}
        for k in running:  # each cab unit's capability, issued by a controller
            issued = await http.post(f"/railguard/national/cab/{k}/token", json={"hours": 1, "issued_by": "load test"})
            tokens[k] = issued.json()["token"]

        async def listen(path: str, run: str | None) -> None:
            nonlocal dropped, refused
            opened = time.perf_counter()
            got_first = False
            try:
                async with http.stream("GET", path) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("event: refused"):
                            refused += 1
                            return
                        if line.startswith("data: "):
                            now = time.perf_counter()
                            if not got_first:
                                first_event.append((now - opened) * 1000)
                                got_first = True
                            elif run in changes:
                                acted, before = changes[run]
                                # The change has arrived (recovery downstream may absorb part of the 7 min).
                                if json.loads(line[6:])["schedule_deviation_min"] > before + 0.5:
                                    push_ms.append((now - changes.pop(run)[0]) * 1000)
                        if time.perf_counter() > stop:
                            return
            except (httpx.HTTPError, OSError):
                dropped += 1

        async def feeder() -> None:
            sim = FeedSimulator(twin.gateway, "LOAD", "k1", FEED_SECRET, seed=1)
            keys = twin.running()
            k = 0
            while time.perf_counter() < stop:
                batch = []
                while len(batch) < 250 and keys:
                    event = sim.position_event(keys[k % len(keys)])
                    k += 1
                    if event:
                        batch.append(event)
                t0 = time.perf_counter()
                await http.post("/railguard/national/feed/batch", json=sim.envelope(batch))
                feed_ms.append((time.perf_counter() - t0) * 1000)
                await asyncio.sleep(1.0)

        async def controller() -> None:
            k = 0
            await asyncio.sleep(3.0)
            while time.perf_counter() < stop - 3 and running:
                run = running[(k * 7) % len(running)]
                k += 1
                plan = twin.plan_of(run)
                i = min(twin.position(run)["index"] + 1, len(plan.sections) - 1)
                live_view = (await http.get(f"/railguard/national/cab/{run}/live?token={tokens[run]}")).json()
                changes[run] = (time.perf_counter(), live_view["schedule_deviation_min"])
                body = {"run": run, "station": plan.frm[i], "delay_min": 7}
                answer = await http.post("/railguard/national/disrupt", json=body)
                actions[str(answer.status_code)] = actions.get(str(answer.status_code), 0) + 1
                if answer.status_code != 200:
                    changes.pop(run, None)
                await asyncio.sleep(5.0)

        async def bounded(path: str, run: str | None) -> None:
            try:
                await asyncio.wait_for(listen(path, run), timeout=max(stop - time.perf_counter(), 1) + 5)
            except TimeoutError:
                pass  # the test is over; the stream itself was healthy

        tasks = [bounded("/railguard/national/stream", None) for _ in range(consoles)]
        tasks += [bounded(f"/railguard/national/cab/{r}/stream?token={tokens[r]}", r) for r in running]
        await asyncio.gather(*tasks, feeder(), controller())
    return {
        "consoles": consoles,
        "cab_streams": len(running),
        "seconds": seconds,
        "first_event_ms": {"p50": _pct(first_event, 0.5), "p95": _pct(first_event, 0.95), "n": len(first_event)},
        "push_latency_ms": {
            "p50": _pct(push_ms, 0.5),
            "p95": _pct(push_ms, 0.95),
            "p99": _pct(push_ms, 0.99),
            "max": round(max(push_ms), 1) if push_ms else None,
            "n": len(push_ms),
        },  # fmt: skip
        "feed_batch_ms": {
            "p50": _pct(feed_ms, 0.5),
            "p95": _pct(feed_ms, 0.95),
            "batches": len(feed_ms),
            "fixes_per_batch": 250,
        },  # fmt: skip
        "controller_actions_by_status": actions,
        "streams_refused": refused,
        "streams_dropped": dropped,
    }


def main(argv: list[str] | None = None) -> int:
    import subprocess  # nosec B404 - starts this project's own service for the test, fixed arguments
    import sys
    import urllib.request

    parser = argparse.ArgumentParser(prog="python -m india_rail loadtest", description=__doc__.split("\n\n")[0])
    parser.add_argument("--consoles", type=int, default=50)
    parser.add_argument("--cabs", type=int, default=500)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    args = parser.parse_args(argv)

    port = _free_port()
    env = {**os.environ, "RAILGUARD_FEED_KEYS": f"LOAD:k1:{FEED_SECRET.hex()}", "RAILGUARD_OPS": "1",
           # every client is 127.0.0.1 here; in service each cab unit has its own address
           "RAILGUARD_RATE_LIMIT": "off", "RAILGUARD_LOG_JSON": "0"}  # fmt: skip
    for k in ("RAILGUARD_VIEWER_TOKEN", "RAILGUARD_CONTROLLER_TOKEN", "RAILGUARD_FEED_TOKEN", "RAILGUARD_MODE"):
        env.pop(k, None)  # demo security: the load test measures the service, not the token checks
    # The service in its own process, as deployed (one uvicorn worker): clients do not share its interpreter.
    command = [sys.executable, "-m", "uvicorn", "india_rail.api:app", "--host", "127.0.0.1", "--port", str(port),
               "--no-access-log", "--log-level", "warning"]  # fmt: skip
    server = subprocess.Popen(command, env=env)  # nosec B603 - no shell, fixed command, integer port
    try:
        from india_rail.railguard.livefeed import FeedGateway
        from india_rail.railguard.national import NationalTwin

        twin = NationalTwin()  # the client's own copy, to choose trains and make realistic fixes
        twin.gateway = FeedGateway(twin, {("LOAD", "k1"): FEED_SECRET})
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                ready = f"http://127.0.0.1:{port}/health/ready"  # loopback, fixed scheme
                if urllib.request.urlopen(ready, timeout=2).status == 200:  # nosec B310
                    break
            except OSError:
                time.sleep(1)
        result = asyncio.run(_run(f"http://127.0.0.1:{port}", twin, args.consoles, args.cabs, args.seconds))
    finally:
        server.terminate()
        server.wait(timeout=30)
    result.update(timetable_trains=len({k.split("@")[0] for k in twin.runs}), running_trains=len(twin.running()),
                  measured_on=datetime.now().isoformat(timespec="seconds"), service_date=str(date.today()),
                  cpus=os.cpu_count(), server="separate process, one uvicorn worker")  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if not result["streams_dropped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
