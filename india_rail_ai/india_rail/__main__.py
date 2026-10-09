"""Command line: python -m india_rail <command>."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

# Commands with their own argument parsers: name -> (module, function)
PASS_THROUGH = {
    "official": ("india_rail.official", "main"),
    "freight": ("india_rail.freight", "main"),
    "accounts": ("india_rail.accounts", "main"),
    "loadtest": ("india_rail.railguard.loadtest", "main"),
    "advisor": ("india_rail.delay_advisor", "main"),
    "gnss-verify": ("india_rail.railguard.gnss_verify", "main"),
    "gnss": ("india_rail.railguard.gnss_agent", "main"),
    "current": ("india_rail.current", "main"),
    "real": ("india_rail.realdata", "main"),
    "schedules": ("india_rail.schedules", "main"),
    "shadow-report": ("india_rail.railguard.shadow", "main"),
    "feed-conformance": ("india_rail.railguard.conformance", "main"),
    "register": ("india_rail.railguard.register", "main"),
    "audit-pack": ("india_rail.audit_pack", "main"),
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] and argv[0] in PASS_THROUGH:
        import importlib

        module, function = PASS_THROUGH[argv[0]]
        return getattr(importlib.import_module(module), function)(argv[1:])
    parser = argparse.ArgumentParser(prog="india_rail", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="download open datasets and build the SQLite database")
    ingest.add_argument("--allow-unpinned", action="store_true", help="accept upstream files whose hash changed")
    sub.add_parser("train", help="cross-validate and train the run-time model")
    setup = sub.add_parser("setup", help="ingest then train")
    setup.add_argument("--allow-unpinned", action="store_true")
    sub.add_parser("summary", help="print dataset summary")

    plan = sub.add_parser("plan", help="propose a re-plan after a delay")
    plan.add_argument("train_number")
    plan.add_argument("station_code")
    plan.add_argument("delay_min", type=int)
    plan.add_argument("--headway", type=int, default=6)

    slack = sub.add_parser("slack", help="compare a train's timetable with model predictions")
    slack.add_argument("train_number")

    ask = sub.add_parser("ask", help="ask the assistant (free by default: local Ollama model or offline)")
    ask.add_argument("question", nargs="*", help="omit for an interactive session")
    ask.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "offline", "ollama", "claude"],
        help="auto/offline/ollama are free; claude uses the paid Anthropic API with your own key",
    )

    sub.add_parser("official", help="register/ingest official Government of India railway data (--help for options)")
    sub.add_parser("schedules", help="working schedule, metrics and completeness audit of every train (--help)")
    sub.add_parser("real", help="real-life data: observed running, real track data, validation (--help)")
    sub.add_parser("current", help="every train running now: current timetable, registry, PIN codes (--help)")
    sub.add_parser("gnss", help="GNSS device agent for a loco/cab unit: NMEA in, signed position batches out (--help)")
    sub.add_parser("accounts", help="named user accounts: add, list, disable, enable (--help)")
    sub.add_parser("loadtest", help="load-test the live service on the real network (streams, feed, push latency)")
    sub.add_parser("advisor", help="delay-minimisation advisor: where delay is made on the real network (--help)")
    sub.add_parser("gnss-verify", help="verify GNSS tracking on the real network with simulated receivers")
    sub.add_parser("freight", help="Dedicated Freight Corridors: network and automated freight pathing (--help)")
    sub.add_parser("shadow-report", help="shadow-trial agreement over the whole persisted audit (--help)")
    sub.add_parser("feed-conformance", help="check a feed (CRIS side) or a receiver against the live-data contract")
    sub.add_parser("register", help="loop and block-section register: empty template, validate, build (--help)")
    sub.add_parser("audit-pack", help="build the CERT-In/STQC audit pack: SBOM, evidence index, controls (--help)")

    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8100)

    args = parser.parse_args(argv)

    if args.command in {"ingest", "setup"}:
        from india_rail.ingest import build_database, download_sources

        report = build_database(download_sources(allow_unpinned=args.allow_unpinned))
        print(json.dumps(report.__dict__, indent=2))
    if args.command in {"train", "setup"}:
        from india_rail.ingest import DB_PATH
        from india_rail.runtime_model import METRICS_PATH, evaluate_and_train

        metrics = evaluate_and_train(sqlite3.connect(DB_PATH))
        print(json.dumps({k: metrics[k] for k in ("rows_used", "trains", "scores", "interval_p10_p90")}, indent=2))
        print(f"Full metrics: {METRICS_PATH}")
    if args.command in {"ingest", "train", "setup"}:
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("india_rail.api:app", host=args.host, port=args.port)
        return 0

    from india_rail.services import Services

    services = Services()
    try:
        return _service_command(args, services)
    except (ValueError, KeyError) as exc:  # bad train, station or input: a message, not a traceback
        print(f"error: {str(exc).strip(chr(39))}", file=sys.stderr)
        return 2


def _service_command(args: argparse.Namespace, services) -> int:
    if args.command == "summary":
        print(json.dumps(services.network.summary(), indent=2))
    elif args.command == "plan":
        print(json.dumps(services.plan(args.train_number, args.station_code, args.delay_min, args.headway), indent=2))
    elif args.command == "slack":
        print(json.dumps(services.timetable_slack(args.train_number), indent=2))
    elif args.command == "ask":
        from india_rail.free_assistant import make_assistant

        assistant = make_assistant(services, args.provider)
        if args.question:
            print(assistant.ask(" ".join(args.question)))
            return 0
        print(f"India Rail assistant ({assistant.name}). Empty line to exit.")
        while line := input("> ").strip():
            print(assistant.ask(line), "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
