"""Loop and block-section register: the engineering data Indian Railways holds and the twin cannot infer.

    python -m india_rail register template --out-dir register/
    python -m india_rail register validate --dir register/
    python -m india_rail register build --dir register/ --out register.json
    RAILGUARD_REGISTER=register.json python -m india_rail serve

`template` writes two empty CSV files - the column headers and nothing else. Nothing is pre-filled: every row and
every value is entered by Indian Railways from its own documents (Station Working Rules, working time table,
signalling plans, engineering registers), and each row names that document as its source:

* stations.csv - station_code, loops, crossing_allowed (Y/N), platform_lines, interlocking, source, effective_from;
* sections.csv - section_id (the two station codes sorted, joined by '-'), tracks, block_system (ABSOLUTE |
  AUTOMATIC | IBS | TOKEN), headway_min, source, effective_from.

`validate` checks every row on its own and for consistency, and against the network the twin runs on: a station or
section the twin does not know is reported (and left out by `build`), as is an express's stop-to-stop path, whose
state comes from the physical sections it runs over. `build` takes only valid rows whose source is one of IR_SOURCES.

What the twin does with a built register:
* a section's track count replaces the inferred one (labelled IR_REGISTER);
* a section's minimum signalled headway replaces the default separation on that track;
* on single line, a planned wait (a hold or a wait for a path) at a station with no loop is refused: the train
  could not stand clear of the line there.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

IR_SOURCES = ("IR_SWR", "IR_WTT", "IR_SIGNALLING_PLAN", "IR_ENGINEERING")
BLOCK_SYSTEMS = ("ABSOLUTE", "AUTOMATIC", "IBS", "TOKEN")
STATION_COLUMNS = ("station_code", "loops", "crossing_allowed", "platform_lines", "interlocking", "source",
                   "effective_from")  # fmt: skip
SECTION_COLUMNS = ("section_id", "tracks", "block_system", "headway_min", "source", "effective_from")


# ---- template ---------------------------------------------------------------------------------------------------
def template(out_dir: Path) -> dict[str, Any]:
    """Two CSV files with the column headers only: Indian Railways enters every row from its own documents."""

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in (("stations.csv", STATION_COLUMNS), ("sections.csv", SECTION_COLUMNS)):
        target = out_dir / name
        if target.exists() and target.stat().st_size > len(",".join(columns)) + 2:
            raise FileExistsError(f"{target} already holds rows: not overwritten")
        with target.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(columns)
    return {"files": [str(out_dir / "stations.csv"), str(out_dir / "sections.csv")], "rows": 0,
            "sources_accepted": list(IR_SOURCES)}  # fmt: skip


def network_codes() -> dict[str, set[str]]:
    """Stations, physical sections and express paths of the network the twin is configured to run on."""

    from india_rail.railguard.national import build_national, timetable_source

    data = build_national(timetable_source()[1])
    physical = {sid for sid in data.network.sections if sid not in data.parts}
    return {"stations": set(data.network.nodes), "sections": physical, "paths": set(data.parts)}


# ---- validate and build -----------------------------------------------------------------------------------------
def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"{path.name}: header must be exactly {','.join(columns)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _int(value: str, lo: int, hi: int, what: str, problems: list[str]) -> int | None:
    if value == "":
        return None
    try:
        n = int(value)
    except ValueError:
        problems.append(f"{what} must be a whole number")
        return None
    if not lo <= n <= hi:
        problems.append(f"{what} must be {lo}-{hi}")
    return n


def check(folder: Path, network: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """Every row checked on its own and for consistency, and (given the twin's network) that it names a station or
    physical section the twin runs on. Returns the usable rows, every problem, and the rows left out."""

    stations, sections, problems, left_out = {}, {}, [], []
    for row in _rows(folder / "stations.csv", STATION_COLUMNS):
        p: list[str] = []
        code = row["station_code"]
        loops = _int(row["loops"], 0, 30, "loops", p)
        platforms = _int(row["platform_lines"], 0, 40, "platform_lines", p)
        crossing = row["crossing_allowed"].upper() or None
        if crossing not in (None, "Y", "N"):
            p.append("crossing_allowed must be Y or N")
        if crossing == "Y" and loops == 0:
            p.append("crossing_allowed=Y with no loop: two trains cannot cross where neither can stand clear")
        filled = any(v is not None for v in (loops, platforms, crossing)) or row["interlocking"]
        if filled and row["source"] not in IR_SOURCES:
            p.append(f"source must be one of {IR_SOURCES} (an Indian Railways document) for a value to be used")
        if filled:
            try:
                date.fromisoformat(row["effective_from"])
            except ValueError:
                p.append("effective_from must be YYYY-MM-DD")
        if code in stations:
            p.append("station listed twice")
        problems += [f"stations.csv {code}: {x}" for x in p]
        if not p and network is not None and code not in network["stations"]:
            left_out.append(f"stations.csv {code}: not a station of the network the twin runs on")
            continue
        if filled and not p:
            stations[code] = {"loops": loops, "crossing_allowed": crossing, "platform_lines": platforms,
                              "interlocking": row["interlocking"] or None, "source": row["source"],
                              "effective_from": row["effective_from"]}  # fmt: skip
    for row in _rows(folder / "sections.csv", SECTION_COLUMNS):
        p = []
        sid = row["section_id"]
        a, b = sid.split("-", 1) if "-" in sid else (sid, "")
        if f"{min(a, b)}-{max(a, b)}" != sid:
            p.append("section_id must be the two station codes sorted, joined by '-'")
        tracks = _int(row["tracks"], 1, 8, "tracks", p)
        block = row["block_system"].upper() or None
        if block not in (None, *BLOCK_SYSTEMS):
            p.append(f"block_system must be one of {BLOCK_SYSTEMS}")
        headway = None
        if row["headway_min"]:
            try:
                headway = float(row["headway_min"])
                if not 1.0 <= headway <= 30.0:
                    p.append("headway_min must be 1-30")
            except ValueError:
                p.append("headway_min must be a number")
        if block == "TOKEN" and tracks not in (None, 1):
            p.append("TOKEN working is single-line working")
        filled = any(v is not None for v in (tracks, block, headway))
        if filled and row["source"] not in IR_SOURCES:
            p.append(f"source must be one of {IR_SOURCES} (an Indian Railways document) for a value to be used")
        if filled:
            try:
                date.fromisoformat(row["effective_from"])
            except ValueError:
                p.append("effective_from must be YYYY-MM-DD")
        if sid in sections:
            p.append("section listed twice")
        problems += [f"sections.csv {sid}: {x}" for x in p]
        if not p and network is not None and sid not in network["sections"]:
            why = ("an express's path over shorter sections: enter those sections instead" if sid in network["paths"]
                   else "not a section of the network the twin runs on")  # fmt: skip
            left_out.append(f"sections.csv {sid}: {why}")
            continue
        if filled and not p:
            sections[sid] = {"tracks": tracks, "block_system": block, "headway_min": headway,
                             "source": row["source"], "effective_from": row["effective_from"]}  # fmt: skip
    return {"stations": stations, "sections": sections, "problems": problems, "left_out": left_out}


def build(folder: Path, out: Path, network: dict[str, set[str]] | None = None) -> dict[str, Any]:
    result = check(folder, network)
    if result["problems"]:
        raise ValueError(f"{len(result['problems'])} problems; first: {result['problems'][0]}")
    digest = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in ("stations.csv", "sections.csv")}
    register = {
        "kind": "Clear Path Nexus loop and block-section register",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_files_sha256": digest,
        "stations": result["stations"],
        "sections": result["sections"],
    }
    out.write_text(json.dumps(register, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"stations": len(register["stations"]), "sections": len(register["sections"]),
            "left_out": result["left_out"], "out": str(out)}  # fmt: skip


def load(path: Path) -> dict[str, Any]:
    register = json.loads(path.read_text(encoding="utf-8"))
    if register.get("kind") != "Clear Path Nexus loop and block-section register":
        raise ValueError(f"{path} is not a register built by `python -m india_rail register build`")
    for row in (*register["stations"].values(), *register["sections"].values()):
        if row.get("source") not in IR_SOURCES:
            raise ValueError("register rows must come from Indian Railways sources")
    register["checksum"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return register


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail register", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template", help="write empty stations.csv and sections.csv (headers only)")
    t.add_argument("--out-dir", type=Path, required=True)
    for name, text in (("validate", "check a filled register"),
                       ("build", "write the register file the twin loads (RAILGUARD_REGISTER)")):  # fmt: skip
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--dir", type=Path, required=True)
        cmd.add_argument("--offline", action="store_true", help="skip the check against the twin's network")
        if name == "build":
            cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "template":
        print(json.dumps(template(args.out_dir), indent=2))
        return 0
    network = None if args.offline else network_codes()
    if args.command == "validate":
        result = check(args.dir, network)
        counts = {k: len(result[k]) for k in ("stations", "sections", "problems", "left_out")}
        print(json.dumps(counts, indent=2))
        for line in [*result["problems"], *result["left_out"]][:200]:
            print(line)
        return 1 if result["problems"] else 0
    print(json.dumps(build(args.dir, args.out, network), indent=2))
    return 0
