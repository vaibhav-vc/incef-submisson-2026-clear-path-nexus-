"""Exercise every feature: every API route, every command, and (with --ui) every page in Chromium.

    python scripts/verify_features.py [--ui] [--out seva2026/evidence/features/feature_check.json]

API: a scripted day of real operations on the national twin (current timetable, real network): sign in, search
trains, record a delay, rank, approve, replay, issue a cab link, hold the cab's live stream, send a signed feed
batch, log shadow decisions, read the advisor, path freight, ask the assistant - plus the tabletop twin. Every
route the application serves must be exercised: a route nobody calls fails the check. Every protected route is
also called with no credentials and must refuse.

Commands: `--help` for every command, and a working run of each one that is quick on this machine.

Pages (--ui): the server is started in its own process and the console, the cab (with a link issued from the
console, a forged link and a silent link) and the tabletop pages are driven in Chromium (node + playwright).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess  # nosec B404 - runs this project's own commands with fixed arguments
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "seva2026" / "evidence" / "features" / "feature_check.json"
PUBLIC = {
    "/health",
    "/health/live",
    "/health/ready",
    "/cab",
    "/control",
    "/control/national",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/railguard/static",
    "/auth/login",
}
CAPABILITY = {"/railguard/national/cab/{run}/live", "/railguard/national/cab/{run}/stream"}  # cab token, not a role


def _routes(app) -> set[tuple[str, str]]:
    out = set()

    def walk(routes):
        for r in routes:
            if hasattr(r, "original_router"):
                walk(r.original_router.routes)
            elif hasattr(r, "path"):
                for m in getattr(r, "methods", None) or ["GET"]:
                    if m != "HEAD":
                        out.add((m, r.path))

    walk(app.routes)
    return out


class Harness:
    def __init__(self, client, tokens: dict[str, str]):
        self.client, self.tokens = client, tokens
        self.results: list[dict[str, Any]] = []
        self.called: set[tuple[str, str]] = set()

    def call(
        self,
        method: str,
        template: str,
        role: str | None = "viewer",
        expect=(200,),
        params=None,
        json_body=None,
        content=None,
        headers=None,
        fill: dict[str, str] | None = None,
        what: str = "",
    ):
        path = template.format(**(fill or {}))
        h = dict(headers or {})
        if role:
            h["Authorization"] = f"Bearer {self.tokens[role]}"
        started = time.perf_counter()
        try:
            r = self.client.request(method, path, params=params, json=json_body, content=content, headers=h)
            status, body = r.status_code, r
        except Exception as exc:  # recorded as a failure, never hidden
            status, body = None, exc
        ok = status in expect
        self.called.add((method, template))
        self.results.append(
            {
                "route": f"{method} {template}",
                "what": what,
                "status": status,
                "ok": ok,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        if not ok:
            detail = body.text[:200] if hasattr(body, "text") else str(body)[:200]
            self.results[-1]["detail"] = detail
        return body if hasattr(body, "json") else None


def api_checks(feed_secret: bytes) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from india_rail import accounts
    from india_rail.api import app
    from india_rail.railguard.livefeed import IST, sign

    tokens = {
        "viewer": os.environ["RAILGUARD_VIEWER_TOKEN"],
        "controller": os.environ["RAILGUARD_CONTROLLER_TOKEN"],
        "feed": os.environ["RAILGUARD_FEED_TOKEN"],
    }
    store = accounts.Accounts(Path(os.environ["RAILGUARD_ACCOUNTS_DB"]))
    admin_pw, ctrl_pw = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    store.add("admin.feature", "Feature Admin", "admin", admin_pw, must_change=False)
    store.add("sharma.feature", "R. Sharma", "controller", ctrl_pw, must_change=False)
    accounts._ACCOUNTS = store
    client = TestClient(app)
    h = Harness(client, tokens)
    c = h.call
    # ---- service and identity
    for path in ("/health", "/health/live", "/health/ready"):
        c("GET", path, None, expect=(200, 503), what="liveness and readiness")
    c("GET", "/openapi.json", None)
    c("GET", "/docs", None)
    c("GET", "/docs/oauth2-redirect", None)
    c("GET", "/metrics", what="Prometheus metrics")
    for page in ("/control", "/control/national", "/cab"):
        c("GET", page, None, what="page served")
    c("GET", "/railguard/static/national.js", None, what="static assets")
    h.called.add(("GET", "/railguard/static"))
    login = c("POST", "/auth/login", None, json_body={"username": "admin.feature", "password": admin_pw})
    admin = login.json()["token"]
    h.tokens["admin"] = admin
    c("GET", "/auth/me", "admin")
    c("GET", "/auth/users", "admin")
    c(
        "POST",
        "/auth/users",
        "admin",
        json_body={
            "username": "screen.feature",
            "display_name": "Screen",
            "role": "viewer",
            "initial_password": secrets.token_urlsafe(16),
        },
    )
    c("POST", "/auth/users/{username}/{action}", "admin", fill={"username": "screen.feature", "action": "disable"})
    session = c("POST", "/auth/login", None, json_body={"username": "sharma.feature", "password": ctrl_pw}).json()
    h.tokens["session"] = session["token"]
    new_pw = secrets.token_urlsafe(18)
    c("POST", "/auth/password", "session", json_body={"old_password": ctrl_pw, "new_password": new_pw})
    session = c("POST", "/auth/login", None, json_body={"username": "sharma.feature", "password": new_pw}).json()
    h.tokens["session"] = session["token"]
    # ---- the open timetable services
    c("GET", "/summary")
    c("GET", "/trains/search", params={"q": "Rajdhani"})
    open_train = c("GET", "/trains/{number}", fill={"number": "12951"}).json()
    call_at = open_train["stops"][1]["station_code"]  # a station the train calls at, in the open timetable
    c("GET", "/trains/{number}/working-schedule", fill={"number": "12951"}, expect=(200, 404))
    c("GET", "/trains/{number}/slack", fill={"number": "12951"}, expect=(200, 404))
    c("GET", "/stations/search", params={"q": "Mumbai"})
    c("GET", "/stations/{code}/board", fill={"code": "NDLS"})
    c("GET", "/between", params={"origin": "NDLS", "destination": "MMCT"})
    c("GET", "/sections/busiest")
    c("GET", "/path", params={"origin": "NDLS", "destination": "MMCT"}, expect=(200, 404))
    c(
        "POST",
        "/plan/disruption",
        "controller",
        json_body={"train_number": "12951", "station_code": call_at, "delay_min": 30},
    )
    c(
        "POST",
        "/assistant/ask",
        "viewer",
        json_body={"question": "Which trains run between NDLS and MMCT?", "provider": "offline"},
    )
    # ---- national twin: every train, the network, a disruption decided and replayed
    c("GET", "/railguard/national/summary")
    c("GET", "/railguard/national/network")
    c("GET", "/railguard/national/positions")
    c("GET", "/railguard/national/operators")
    trains = c("GET", "/railguard/national/trains", params={"q": "Rajdhani"}).json()["trains"]
    number = next((t["number"] for t in trains if t.get("in_twin")), trains[0]["number"])
    c("GET", "/railguard/national/trains/{number}", fill={"number": number})
    c("GET", "/railguard/national/trains/{number}/route", fill={"number": number})
    runs = c("GET", "/railguard/national/runs/{number}", fill={"number": number}).json()
    run = next(r for r in runs if r["next_departures"])
    station = run["next_departures"][0]["station"]
    c("GET", "/railguard/national/stations/{code}", fill={"code": station})
    c("GET", "/railguard/national/plan/{run}", fill={"run": run["run"]})
    c("GET", "/railguard/national/eta/{run}", fill={"run": run["run"]}, expect=(200, 503))
    c("GET", "/railguard/national/cab/{run}", fill={"run": run["run"]})
    c(
        "POST",
        "/railguard/national/disrupt",
        "session",
        json_body={"run": run["run"], "station": station, "delay_min": 25},
    )
    rec = c("POST", "/railguard/national/recommend", "session", json_body={"run": run["run"]}).json()
    if rec.get("approvable") and rec["ranking"]["candidates"]:
        c(
            "POST",
            "/railguard/national/approve",
            "session",
            json_body={
                "snapshot_id": rec["snapshot_id"],
                "candidate_id": rec["ranking"]["candidates"][0]["candidate_id"],
                "controller": "sharma.feature",
            },
        )
    else:
        c(
            "POST",
            "/railguard/national/approve",
            "session",
            expect=(409, 422, 400),
            json_body={"snapshot_id": rec["snapshot_id"], "candidate_id": "N1", "controller": "sharma.feature"},
            what="refused: nothing approvable",
        )
    c("GET", "/railguard/national/audit/{snapshot_id}/replay", fill={"snapshot_id": rec["snapshot_id"]})
    c("POST", "/railguard/national/tick", "controller", json_body={"minutes": 1})
    nodes = c("GET", "/railguard/national/plan/{run}", fill={"run": run["run"]}).json()["nodes"]
    sid = "-".join(sorted(nodes[:2]))  # the run's next section
    c(
        "POST",
        "/railguard/national/section",
        "controller",
        json_body={"section_id": sid, "temp_restriction_kmph": 45},
        expect=(200, 404),
    )
    summary = c("GET", "/railguard/national/summary").json()
    threat = next((t["id"] for t in summary.get("threats", []) if t.get("lifecycle") == "OPEN"), "missing-threat")
    c(
        "POST",
        "/railguard/national/threats/{threat_id}/ack",
        "controller",
        fill={"threat_id": threat},
        json_body={"by": "controller-1"},
        expect=(200, 404),
    )
    # ---- live: console stream, cab capability, cab stream
    c("GET", "/railguard/national/stream", params={"events": 1}, what="console live push")
    issued = c(
        "POST",
        "/railguard/national/cab/{run}/token",
        "session",
        fill={"run": run["run"]},
        json_body={"issued_by": "sharma.feature", "hours": 1},
    ).json()
    cab = {"Authorization": f"Bearer {issued['token']}"}
    c("GET", "/railguard/national/cab/{run}/live", None, fill={"run": run["run"]}, headers=cab)
    c(
        "GET",
        "/railguard/national/cab/{run}/stream",
        None,
        fill={"run": run["run"]},
        headers=cab,
        params={"events": 1},
        what="cab live push",
    )
    # ---- feed: a signed batch and a position
    now = datetime.now(IST)
    env = {
        "source": "NTES",
        "key_id": "k1",
        "sent_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "sequence": int(time.time()),
        "events": [
            {
                "type": "STATION",
                "train_number": run["run"].split("@")[0],
                "start_date": now.date().isoformat(),
                "station_code": station,
                "event": "DEP",
                "observed_at": now.isoformat(),
            }
        ],
    }
    env["signature"] = sign(env, feed_secret)
    c("POST", "/railguard/national/feed/batch", "feed", json_body=env, what="signed feed batch")
    c(
        "POST",
        "/railguard/national/feed/position",
        "feed",
        json_body={"run": run["run"], "section_id": sid, "offset_km": 0.5},
        expect=(200,),
    )
    # ---- shadow trial
    c(
        "POST",
        "/railguard/national/shadow/actual",
        "session",
        json_body={"run": run["run"], "action": "HOLD", "controller": "sharma.feature"},
    )
    day = summary.get("stats", {}).get("service_date") or now.date().isoformat()
    csv_text = (
        "train_number,start_date,action,decided_at,station,hold_min,desk,note\n"
        f"{run['run'].split('@')[0]},{day},CONTINUE,{now.isoformat()},{station},,Desk-1,\n"
    )
    c(
        "POST",
        "/railguard/national/shadow/import",
        "session",
        json_body={"csv": csv_text, "controller": "sharma.feature"},
    )
    c("GET", "/railguard/national/shadow/report")
    # ---- delay advisor and freight
    c("GET", "/railguard/national/advisor", expect=(200, 503))
    c("GET", "/railguard/national/advisor/{kind}", fill={"kind": "sections"}, expect=(200, 503))
    c("GET", "/railguard/national/advisor/train/{number}", fill={"number": number}, expect=(200, 404, 503))
    corridors = c("GET", "/railguard/freight/corridors", expect=(200, 503))
    c(
        "POST",
        "/railguard/freight/plan",
        "controller",
        json_body={
            "corridor": "Western",
            "trains": [{"id": "F1", "origin_km": 0, "destination_km": 200, "ready_min": 60}],
        },
        expect=(200, 503),
    )
    del corridors
    c("POST", "/railguard/national/reset", "controller")
    # ---- the tabletop twin (demonstration network)
    c("GET", "/railguard/state")
    scenarios = c("GET", "/railguard/scenarios").json()
    name = scenarios[0]["name"] if isinstance(scenarios, list) else next(iter(scenarios))
    c("POST", "/railguard/scenarios/{name}/load", "controller", fill={"name": name})
    c("POST", "/railguard/tick", "controller", json_body={"seconds": 60})
    c(
        "POST",
        "/railguard/twintrack/position",
        "feed",
        json_body={"train_id": "A", "from_node": "N1"},
        expect=(200, 404, 422),
    )
    state = c("GET", "/railguard/state").json()
    some_section = (
        next(iter(state.get("sections", {})), "S1")
        if isinstance(state.get("sections"), dict)
        else (state.get("sections", [{}])[0].get("id", "S1"))
    )
    c(
        "POST",
        "/railguard/tracksense/section",
        "feed",
        json_body={"section_id": some_section, "condition": 0.8},
        expect=(200, 404),
    )
    c(
        "POST",
        "/railguard/console/section",
        "controller",
        json_body={"section_id": some_section, "condition": 0.9},
        expect=(200, 404),
    )
    c(
        "POST",
        "/railguard/twintrack/obstacle",
        "feed",
        json_body={"section_id": some_section, "detected": False},
        expect=(200, 404),
    )
    c("POST", "/railguard/fault", "controller", json_body={"kind": "sensor_online"}, expect=(422,),
      what="refused with the missing field named")  # fmt: skip
    demo_train = next(iter(c("GET", "/railguard/state").json().get("trains", {})), "A")
    c("POST", "/railguard/fault", "controller", json_body={"kind": "sensor_online", "train_id": demo_train})
    rec = c("POST", "/railguard/recommend", "controller", json_body={}).json()
    snap = rec.get("snapshot_id", "SNAP-0001")
    c(
        "POST",
        "/railguard/approve",
        "controller",
        json_body={"snapshot_id": snap, "candidate_id": "C1", "controller": "controller-1"},
        expect=(200, 409, 400, 404),
    )
    c(
        "POST",
        "/railguard/reject",
        "controller",
        json_body={"snapshot_id": snap, "controller": "controller-1"},
        expect=(200, 409, 400, 404),
    )
    c("POST", "/railguard/hold", "controller", json_body={"controller": "controller-1"})
    threats = c("GET", "/railguard/state").json().get("threats", [])
    tid = threats[0]["id"] if threats else "missing-threat"
    c(
        "POST",
        "/railguard/threats/{threat_id}/ack",
        "controller",
        fill={"threat_id": tid},
        json_body={"by": "controller-1"},
        expect=(200, 404),
    )
    c("GET", "/railguard/cab/{train_id}", fill={"train_id": "A"})
    c("GET", "/railguard/cab/{train_id}/compact", fill={"train_id": "A"})
    c("GET", "/railguard/audit")
    c("GET", "/railguard/audit/{snapshot_id}", fill={"snapshot_id": snap}, expect=(200, 404))
    c("GET", "/railguard/audit/{snapshot_id}/replay", fill={"snapshot_id": snap}, expect=(200, 404))
    c("POST", "/railguard/scenarios/{name}/run", "controller", fill={"name": name}, expect=(200,))
    c("POST", "/auth/logout", "session")
    # ---- every protected route refuses a request without credentials
    refused = []
    for method, template in sorted(_routes(app)):
        if template in PUBLIC or template.startswith("/docs"):
            continue
        path = re.sub(r"\{[^}]+\}", "X1", template)
        r = client.request(method, path, json={} if method == "POST" else None)
        refused.append(
            {
                "route": f"{method} {template}",
                "status": r.status_code,
                "ok": r.status_code in (401, 403) or (template in CAPABILITY and r.status_code in (403, 422)),
            }
        )
    missing = sorted(f"{m} {p}" for m, p in _routes(app) - h.called)
    return {
        "routes": len(_routes(app)),
        "routes_exercised": len(_routes(app) & h.called),
        "routes_not_exercised": missing,
        "calls": len(h.results),
        "calls_ok": sum(r["ok"] for r in h.results),
        "failures": [r for r in h.results if not r["ok"]],
        "protected_routes_refuse_without_credentials": f"{sum(r['ok'] for r in refused)}/{len(refused)}",
        "not_refused": [r for r in refused if not r["ok"]],
        "calls_detail": h.results,
    }


COMMANDS = [
    "ingest",
    "train",
    "setup",
    "summary",
    "plan",
    "slack",
    "ask",
    "official",
    "schedules",
    "real",
    "current",
    "gnss",
    "accounts",
    "loadtest",
    "advisor",
    "gnss-verify",
    "freight",
    "shadow-report",
    "feed-conformance",
    "register",
    "audit-pack",
    "serve",
]


def _run(args: list[str], env: dict[str, str], timeout: int = 600) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, "-m", "india_rail", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )  # nosec B603 - this project's own CLI
    return done.returncode, (done.stdout + done.stderr)[-400:]


def cli_checks(env: dict[str, str], work: Path, feed_secret: bytes) -> dict[str, Any]:
    from india_rail.railguard.livefeed import IST, sign

    results = []
    for cmd in COMMANDS:
        code, tail = _run([cmd, "--help"], env, 120)
        results.append({"command": f"{cmd} --help", "ok": code == 0, "tail": None if code == 0 else tail})
    key = work / "k.hex"
    key.write_text(feed_secret.hex())
    now = datetime.now(IST)
    env_ = {
        "source": "NTES",
        "key_id": "k1",
        "sent_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "sequence": 1,
        "events": [
            {
                "type": "STATION",
                "train_number": "12951",
                "start_date": now.date().isoformat(),
                "station_code": "MMCT",
                "event": "DEP",
                "observed_at": now.isoformat(),
            }
        ],
    }
    env_["signature"] = sign(env_, feed_secret)
    (work / "sample.jsonl").write_text(json.dumps(env_) + "\n")
    working = [
        (["summary"], 0),
        (["slack", "12951"], 0),
        (["plan", "12951", "BCT", "30"], 0),
        (["plan", "12951", "NOWHERE", "30"], 2),  # a station off the route: a clear error, not a traceback
        (["ask", "--provider", "offline", "trains", "between", "NDLS", "and", "MMCT"], 0),
        (
            [
                "feed-conformance",
                "producer",
                "--file",
                str(work / "sample.jsonl"),
                "--source",
                "NTES",
                "--key-file",
                str(key),
            ],
            0,
        ),
        (["register", "template", "--out-dir", str(work / "reg")], 0),
        (["register", "validate", "--dir", str(work / "reg")], 0),
        (["shadow-report", "--audit-dir", str(work / "audit")], 0),
        (["audit-pack", "--out", str(work / "pack")], 0),
        (["accounts", "list"], 0),
        (["gnss-verify", "--rounds", "1", "--out", str(work / "gnss.json")], 0),
    ]
    for args, want in working:
        started = time.perf_counter()
        code, tail = _run(args, env)
        results.append(
            {
                "command": " ".join(a if not a.startswith(str(work)) else "<tmp>" for a in args),
                "ok": code == want,
                "seconds": round(time.perf_counter() - started, 1),
                "tail": None if code == want else tail,
            }
        )
    return {
        "commands": len(results),
        "ok": sum(r["ok"] for r in results),
        "failures": [r for r in results if not r["ok"]],
        "detail": results,
    }


def ui_checks(env: dict[str, str], work: Path) -> dict[str, Any]:
    """Start the server in its own process and drive the pages in Chromium."""

    port = 8911
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "india_rail.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env={**env, "RAILGUARD_OPS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # nosec B603
    try:
        import urllib.request

        for _ in range(120):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=5) as r:  # nosec B310
                    if json.loads(r.read()).get("ready"):
                        break
            except OSError:
                pass
            time.sleep(2)
        node_path = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=False).stdout.strip()  # nosec
        out = {}
        silent = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "ui" / "silent_server.py"),
                str(ROOT / "india_rail" / "railguard" / "static"),
                str(port + 1),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # nosec B603
        try:
            for script in sorted((ROOT / "scripts" / "ui").glob("*.js")):
                target = port + 1 if script.name == "silent_link.cab.js" else port  # a link that falls silent
                done = subprocess.run(
                    ["node", str(script), f"http://127.0.0.1:{target}", str(work / f"{script.stem}.png")],
                    env={**env, "NODE_PATH": node_path},
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )  # nosec B603 B607
                try:
                    result = json.loads(done.stdout[done.stdout.index("{") :])
                except ValueError:
                    result = {"output": (done.stdout + done.stderr)[-400:]}
                out[script.stem] = {"ok": done.returncode == 0, **result}
        finally:
            silent.terminate()
        return {"pages_checked": len(out), "ok": sum(v["ok"] for v in out.values()), "detail": out}
    finally:
        server.terminate()
        server.wait(timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true", help="also drive the pages in Chromium (node + playwright)")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="features-"))
    feed_secret = secrets.token_bytes(32)
    env = {
        **os.environ,
        "RAILGUARD_VIEWER_TOKEN": secrets.token_urlsafe(32),
        "RAILGUARD_CONTROLLER_TOKEN": secrets.token_urlsafe(32),
        "RAILGUARD_FEED_TOKEN": secrets.token_urlsafe(32),
        "RAILGUARD_FEED_KEYS": f"NTES:k1:{feed_secret.hex()}",
        "RAILGUARD_ACCOUNTS_DB": str(work / "accounts.db"),
        "RAILGUARD_AUDIT_DIR": str(work / "audit"),
        "RAILGUARD_RATE_LIMIT": "off",
        "RAILGUARD_ALLOWED_HOSTS": "127.0.0.1,localhost,testserver",
        "PYTHONPATH": str(ROOT),
    }
    os.environ.update(env)
    started = time.time()
    report: dict[str, Any] = {
        "what": __doc__.split("\n\n")[0],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    report["api"] = api_checks(feed_secret)
    report["commands"] = cli_checks(env, work, feed_secret)
    if args.ui:
        report["pages"] = ui_checks(env, work)
    report["seconds"] = round(time.time() - started)
    ok = (
        not report["api"]["failures"]
        and not report["api"]["routes_not_exercised"]
        and not report["api"]["not_refused"]
        and not report["commands"]["failures"]
        and (not args.ui or report["pages"]["ok"] == report["pages"]["pages_checked"])
    )
    report["result"] = "PASS" if ok else "FAIL"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str) + "\n")
    shown = {k: v for k, v in report["api"].items() if k != "calls_detail"}
    print(
        json.dumps(
            {
                "result": report["result"],
                "api": shown,
                "commands": {k: v for k, v in report["commands"].items() if k != "detail"},
                "pages": {k: v for k, v in report.get("pages", {}).items() if k != "detail"},
            },
            indent=1,
            default=str,
        )[:6000]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
