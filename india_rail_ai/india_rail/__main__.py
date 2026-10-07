"""Command line: python -m india_rail <command>."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys


def main(argv: list[str] | None = None) -> int:
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

    ask = sub.add_parser("ask", help="ask the AI assistant (needs an Anthropic API credential)")
    ask.add_argument("question", nargs="*", help="omit for an interactive session")

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
    if args.command == "summary":
        print(json.dumps(services.network.summary(), indent=2))
    elif args.command == "plan":
        print(json.dumps(services.plan(args.train_number, args.station_code, args.delay_min, args.headway), indent=2))
    elif args.command == "slack":
        print(json.dumps(services.timetable_slack(args.train_number), indent=2))
    elif args.command == "ask":
        from india_rail.assistant import RailAssistant

        assistant = RailAssistant(services)
        if args.question:
            print(assistant.ask(" ".join(args.question)))
            return 0
        print("India Rail assistant. Empty line to exit.")
        while line := input("> ").strip():
            print(assistant.ask(line), "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
