"""Where delay is made, and what would reduce it: research from real running, for the people who can act on it.

    python -m india_rail advisor build      # analyse September 2024 actual running -> data/advisor.json
    python -m india_rail advisor show [--kind sections|stations|late_starts|trains|timetable] [--train N]

Every finding is measured from observed arrivals (realdata.py), never from this project's own simulation, and
checked for persistence: it is found on 1-15 September and must recur on 16-30 September to be called chronic
(a one-off breakdown is not a reason to rebuild a section). Each comes with the minutes a day at stake and the
lever that addresses it. Levers, by who pulls them:

* section loss on single line      -> engineering: crossing loops / doubling (capacity), long-term;
* section loss on double line      -> operations: speed restrictions, signal spacing (block sections), level
                                      crossings, precedence rules at the junction ahead;
* station / junction congestion    -> operations: platform and route allocation, re-spacing arrivals in the
                                      peak hour found;
* late start from origin           -> rake links, pit-line and washing slots, crew booking at the origin;
* timetable tighter than achievable -> timetabling: re-time with the measured running time and take the time
                                      from places the train always recovers (a timetable that is never met
                                      makes every crossing and precedence decision on wrong times);
* chronically late train           -> the train's own action list: its worst sections and its start.

"Minutes at stake" is what the measured loss costs a day. What an intervention would save is for the railway's
own engineering assessment: the figures here say where to look first and how big the prize is, not a promise.
Arrival times only are public, so loss "on a section" includes the stop at its start (dwell overrun).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail.ingest import DATA_DIR, PACKAGE_ROOT
from india_rail.realdata import EXTREME_DELAY_MIN, REAL_DB_PATH

ADVISOR_PATH = DATA_DIR / "advisor.json"
EVIDENCE = PACKAGE_ROOT / "seva2026" / "evidence" / "real_data" / "delay_advisor_summary.json"
SPLIT = "2024-09-15"  # discover on 1-15 September, confirm on 16-30
LOSS_MIN = 5.0
LATE_START_MIN = 10.0
ON_TIME_MIN = 15.0
MIN_TRAVERSALS = 20
TOP = 200
INCIDENT_MIN = 180  # a delay change above 3 h between two stops is an incident or a train not running to its
# published timetable at all: counted, but kept out of the chronic patterns
RETIME_MAX_MIN = 90  # a recurring loss above this is a schedule that does not describe the train, not a timing


def _traversals(db: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Consecutive timetable stops of the same run that were both observed: the delay change between them."""

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    obs = pd.read_sql(
        "SELECT train_number AS train, run_date AS date, seq, station_code AS station, sch_arr_min AS sch, "
        "delay_min AS delay FROM observed_stops ORDER BY train_number, run_date, seq",
        con,
    )
    trains = pd.read_sql("SELECT number AS train, name, type, zone FROM trains", con)
    stations = dict(con.execute("SELECT code, name FROM stations"))
    try:
        infra = pd.read_sql("SELECT edge, lines, electrified_share, maxspeed_kmph, osm_km FROM osm_sections "
                            "WHERE quality = 'ACCEPTED'", con).set_index("edge")  # fmt: skip
    except Exception:
        infra = pd.DataFrame(columns=["lines", "electrified_share", "maxspeed_kmph", "osm_km"])
    con.close()
    obs = obs[obs.delay <= EXTREME_DELAY_MIN]
    nxt = obs.groupby(["train", "date"]).shift(-1)
    t = obs.assign(to_seq=nxt.seq, to_station=nxt.station, to_sch=nxt.sch, to_delay=nxt.delay)
    t = t[t.to_seq == t.seq + 1].copy()
    t["growth"] = t.to_delay - t.delay
    t["edge"] = np.where(t.station < t.to_station, t.station + "-" + t.to_station, t.to_station + "-" + t.station)
    t["hour"] = (t.to_sch % 1440) // 60
    incidents = t[t.growth.abs() > INCIDENT_MIN]
    t = t[t.growth.abs() <= INCIDENT_MIN]
    return t, {
        "incidents": len(incidents),
        "incident_trains": int(incidents.train.nunique()),
        "obs": obs,
        "trains": trains,
        "stations": stations,
        "infra": infra,
    }


def _persistence(first: pd.Series, second: pd.Series, k: int = 50) -> dict[str, Any]:
    """Do the worst places found on 1-15 September stay among the worst on 16-30 September?"""

    a = first.sort_values(ascending=False)
    b = second.reindex(a.index).dropna()
    top_a = list(a.index[:k])
    top_b = set(second.sort_values(ascending=False).index[: 2 * k])
    rho = float(pd.Series(a.reindex(b.index)).rank().corr(b.rank())) if len(b) > 2 else float("nan")
    again = round(100 * sum(x in top_b for x in top_a) / max(k, 1), 1)
    return {"top_k": k, f"top_{k}_found_again_in_top_{2 * k}_pct": again, "rank_correlation": round(rho, 3)}


def _per_day(frame: pd.DataFrame, days: int) -> pd.Series:
    return frame.growth.clip(lower=0).groupby(frame.key).sum() / days


def build(db: Path = REAL_DB_PATH, out: Path = ADVISOR_PATH) -> dict[str, Any]:
    started = time.time()
    t, ctx = _traversals(db)
    obs, trains, names, infra = ctx["obs"], ctx["trains"], ctx["stations"], ctx["infra"]
    days = obs.date.nunique()
    first, second = t[t.date <= SPLIT], t[t.date > SPLIT]
    d1, d2 = first.date.nunique(), second.date.nunique()

    # ---- sections ----------------------------------------------------------------------------------------
    g = t.groupby("edge")
    sec = pd.DataFrame({
        "traversals": g.size(),
        "trains": g.train.nunique(),
        "mean_growth_min": g.growth.mean(),
        "loss_share_pct": g.growth.apply(lambda s: (s >= LOSS_MIN).mean() * 100),
        "lost_min_per_day": g.growth.apply(lambda s: s.clip(lower=0).sum()) / days,
    })  # fmt: skip
    sec = sec[sec.traversals >= MIN_TRAVERSALS]
    s1 = _per_day(first.assign(key=first.edge), d1)
    s2 = _per_day(second.assign(key=second.edge), d2)
    sec["first_half_min_per_day"], sec["second_half_min_per_day"] = s1.reindex(sec.index), s2.reindex(sec.index)
    rank2 = s2.rank(ascending=False)
    sec["chronic"] = (s1.reindex(sec.index).rank(ascending=False) <= TOP) & (rank2.reindex(sec.index) <= 2 * TOP)
    sec = sec.join(infra, how="left")
    sections = []
    for edge, r in sec.sort_values("lost_min_per_day", ascending=False).head(TOP).iterrows():
        a, b = edge.split("-", 1)
        single = r.get("lines") == 1
        lever = ("Capacity: single line - crossing loops or doubling; until then, crossing plans that favour the "
                 "late-running direction" if single else
                 "Operations: speed restrictions, block-section spacing, level crossings and precedence at the "
                 "junction ahead")  # fmt: skip
        sections.append({
            "section": edge, "between": f"{names.get(a, a)} - {names.get(b, b)}",
            "lost_min_per_day": round(float(r.lost_min_per_day), 1),
            "mean_change_min": round(float(r.mean_growth_min), 2), "loss_share_pct": round(float(r.loss_share_pct), 1),
            "traversals": int(r.traversals), "trains": int(r.trains),
            "lines": None if pd.isna(r.get("lines")) else int(r.lines),
            "electrified": None if pd.isna(r.get("electrified_share")) else bool(r.electrified_share >= 0.5),
            "chronic": bool(r.chronic), "lever": lever,
        })  # fmt: skip

    # ---- stations / junctions (arrivals into the station, by hour) ---------------------------------------
    gs = t.groupby("to_station")
    st = pd.DataFrame({"arrivals": gs.size(), "routes_in": gs.station.nunique(),
                       "lost_min_per_day": gs.growth.apply(lambda s: s.clip(lower=0).sum()) / days})  # fmt: skip
    st = st[st.arrivals >= MIN_TRAVERSALS]
    by_hour = t.assign(pos=t.growth.clip(lower=0)).groupby(["to_station", "hour"]).pos.sum() / days
    t1 = _per_day(first.assign(key=first.to_station), d1)
    t2 = _per_day(second.assign(key=second.to_station), d2)
    stations = []
    for code, r in st[st.routes_in >= 2].sort_values("lost_min_per_day", ascending=False).head(TOP).iterrows():
        hours = by_hour.loc[code]
        peak = int(hours.idxmax())
        share = float(hours.max() / max(hours.sum(), 1e-9) * 100)
        stations.append({
            "station": code, "name": names.get(code, code),
            "lost_min_per_day_arriving": round(float(r.lost_min_per_day), 1),
            "arrivals_observed": int(r.arrivals), "approaches": int(r.routes_in),
            "worst_hour": f"{peak:02d}:00-{(peak + 1) % 24:02d}:00", "worst_hour_share_pct": round(share, 1),
            "chronic": bool(code in t1.nlargest(TOP).index and code in t2.nlargest(2 * TOP).index),
            "lever": ("Junction congestion: review platform and route allocation and re-space arrivals around "
                      f"{peak:02d}:00, the hour carrying {share:.0f}% of the loss"),
        })  # fmt: skip

    # ---- late starts ----------------------------------------------------------------------------------------
    origin = obs[obs.seq == 0]
    go = origin.groupby("train").delay
    ls = pd.DataFrame({"runs": go.size(), "late_share_pct": go.apply(lambda s: (s >= LATE_START_MIN).mean() * 100),
                       "mean_start_delay_min": go.mean(), "median_start_delay_min": go.median()})  # fmt: skip
    ls = ls[(ls.runs >= 8) & (ls.late_share_pct >= 50)].join(trains.set_index("train"), how="left")
    late_starts = [
        {"train": n, "name": r["name"], "zone": r.zone, "runs": int(r.runs),
         "late_share_pct": round(float(r.late_share_pct), 1),
         "median_start_delay_min": round(float(r.median_start_delay_min), 1),
         "lever": "Start on time: rake link (is the incoming rake late?), pit-line / washing slot, crew booking"}
        for n, r in ls.sort_values(["late_share_pct", "median_start_delay_min"], ascending=False).head(TOP).iterrows()
    ]  # fmt: skip

    # ---- timetable realism: per train and section, the change that recurs day after day ------------------
    gt = t.groupby(["train", "edge", "seq"]).growth
    tt = pd.DataFrame({"runs": gt.size(), "median_change_min": gt.median(), "p25_change_min": gt.quantile(0.25)})
    tt = tt[tt.runs >= 8].reset_index()
    tight = tt[tt.p25_change_min >= LOSS_MIN]  # loses at least 5 minutes on three days in four
    mismatch = tight[tight.median_change_min > RETIME_MAX_MIN]
    tight = tight[tight.median_change_min <= RETIME_MAX_MIN]
    slack = tt[tt.median_change_min <= -LOSS_MIN].groupby("train").median_change_min.sum()  # where it always recovers
    timetable = []
    tight = tight.assign(stake=tight.median_change_min * tight.runs)  # minutes lost in the month at this timing
    for _, r in tight.sort_values("stake", ascending=False).head(TOP).iterrows():
        recover = float(-slack.get(r.train, 0.0))
        timetable.append({
            "train": r.train, "section": r.edge, "stop_seq": int(r.seq), "runs": int(r.runs),
            "median_loss_min": round(float(r.median_change_min), 1), "loses_5_plus_min_pct_of_days": ">=75",
            "recovery_elsewhere_min": round(recover, 1),
            "lever": ("Re-time: the timetable here is not achievable; move "
                      f"{min(recover, float(r.median_change_min)):.0f} min of allowance from where the train always "
                      "recovers" if recover >= 1 else "Re-time: add the measured running time here, or remove the "
                      "cause (speed restriction, crossing, precedence)"),
        })  # fmt: skip

    # ---- chronically late trains: their own action lists ------------------------------------------------
    last_seq = obs.groupby("train").seq.transform("max")
    dest = obs[obs.seq == last_seq].groupby("train").delay
    lt = pd.DataFrame({"runs": dest.size(), "on_time_pct": dest.apply(lambda s: (s <= ON_TIME_MIN).mean() * 100),
                       "median_arrival_delay_min": dest.median()})  # fmt: skip
    lt = lt[(lt.runs >= 8) & (lt.on_time_pct < 50)].join(trains.set_index("train"), how="left")
    per_train_loss = t.assign(pos=t.growth.clip(lower=0)).groupby(["train", "edge"]).pos.mean()
    start_delay = origin.groupby("train").delay.median()
    late_trains = []
    for n, r in lt.sort_values("median_arrival_delay_min", ascending=False).head(TOP).iterrows():
        worst = per_train_loss.loc[n].nlargest(3) if n in per_train_loss.index.get_level_values(0) else pd.Series()
        late_trains.append({
            "train": n, "name": r["name"], "type": r.type, "runs": int(r.runs),
            "on_time_pct": round(float(r.on_time_pct), 1),
            "median_arrival_delay_min": round(float(r.median_arrival_delay_min), 1),
            "median_start_delay_min": round(float(start_delay.get(n, 0.0)), 1),
            "worst_sections": [{"section": e, "mean_loss_min": round(float(v), 1)} for e, v in worst.items()],
        })  # fmt: skip

    summary = {
        "data": {
            "observed_days": int(days),
            "traversals": len(t),
            "trains": int(obs.train.nunique()),
            "sections_scored": len(sec),
            "stations_scored": len(st),
        },  # fmt: skip
        "network_lost_min_per_day": round(float(t.growth.clip(lower=0).sum() / days)),
        "network_recovered_min_per_day": round(float(-t.growth.clip(upper=0).sum() / days)),
        "top_20_sections_share_of_loss_pct": round(
            float(sec.lost_min_per_day.nlargest(20).sum() / max(sec.lost_min_per_day.sum(), 1e-9) * 100), 1
        ),  # fmt: skip
        "persistence": {"sections": _persistence(s1, s2), "stations": _persistence(t1, t2)},
        "chronic_sections_in_top_200": int(sum(s["chronic"] for s in sections)),
        "late_starting_trains": len(late_starts),
        "timetable_points_not_achievable": len(tight),
        "schedules_not_describing_real_running": {
            "train_sections": len(mismatch),
            "trains": int(mismatch.train.nunique()),
        },
        "incidents_over_3h_excluded": {"traversals": ctx["incidents"], "trains": ctx["incident_trains"]},
        "chronically_late_trains": len(lt),
    }
    report = _clean({"what": __doc__.split("\n\n")[0], "method": __doc__.split("\n\n")[2], "summary": summary,
                     "sections": sections, "stations": stations, "late_starts": late_starts, "timetable": timetable,
                     "trains": late_trains, "seconds": round(time.time() - started)})  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
    registry.cache_clear()
    return report


def _clean(value: Any) -> Any:
    """Plain JSON: numpy scalars to Python, NaN to null (strict JSON has no NaN)."""

    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    if not ADVISOR_PATH.exists():
        raise FileNotFoundError("delay advisor not built: run python -m india_rail advisor build")
    return json.loads(ADVISOR_PATH.read_text())


def for_train(number: str) -> dict[str, Any]:
    """Everything the advisor knows about one train: its lateness, late starts, unachievable timings, sections."""

    adv = registry()
    pick = lambda kind: [x for x in adv[kind] if x.get("train") == number]  # noqa: E731
    mine = pick("trains")
    sections = {s["section"] for t in mine for s in t["worst_sections"]}
    return {"train": number, "chronic_lateness": mine[0] if mine else None, "late_start": pick("late_starts"),
            "timetable": pick("timetable"),
            "hotspots_on_its_route": [s for s in adv["sections"] if s["section"] in sections]}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m india_rail advisor", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="analyse the observed running")
    b.add_argument("--evidence", type=Path, default=EVIDENCE)
    s = sub.add_parser("show", help="print findings")
    s.add_argument("--kind", default="sections", choices=("sections", "stations", "late_starts", "timetable", "trains"))
    s.add_argument("--train")
    s.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.command == "build":
        report = build()
        public = {k: report[k] for k in ("what", "method", "summary")}
        public["examples"] = {k: report[k][:10] for k in ("sections", "stations", "late_starts", "timetable", "trains")}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(public, indent=1) + "\n")
        print(json.dumps(report["summary"], indent=2))
    elif args.train:
        print(json.dumps(for_train(args.train), indent=2))
    else:
        print(json.dumps(registry()[args.kind][: args.limit], indent=2))
    return 0
