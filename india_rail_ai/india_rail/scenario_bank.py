"""Training and testing under 75,556 scenarios.

    python -m india_rail real scenario-bank [--scenarios 75556] [--planner 75556] [--workers 4]

A. Delay forecasts, on 75,556 real scenarios. A scenario is one real train at one real reporting moment of
   September 2024: its real delay, the real state of the network, and its real delays at later stops (the
   answer). They are held out in five rolling-origin rounds (each model learns only from days before the
   scenario) and drawn evenly across situation types - time of day x how late x train class x single or double
   line x network disrupted or not - so rare situations are not drowned out by common ones. Every scenario is
   scored clean and under six damaged inputs: no delay history (a new train), feed noise of +/-3 min, a missed
   report (the previous report's delay), a garbled report (off by 30 min), an unknown train class, and unknown
   route facts (a diversion the twin does not know).

   Two learned models are compared with the baselines (persistence; the twin's dwell-recovery rule):
   * `learned`: the deployed recipe (realval.forecast): random rows, 15% without history;
   * `scenario_trained`: rows weighted so every situation type counts (square-root inverse frequency, capped),
     and trained on the six damaged inputs too (realval.STRESS_TRAINING).

B. The planner, on 75,556 disruption scenarios on the real network (the current timetable, every train). A
   train running at a random time of day is delayed at a station ahead by a real delay - drawn from the time
   losses actually observed between consecutive reports in September 2024 - with, in some scenarios, a section
   ahead closed, obstructed, speed-restricted or under a weather alert, or a second train delayed nearby. The
   planner ranks alternatives; every candidate shown is checked independently (no conflict for the train or any
   train it re-times, no closed or obstructed track), the first is approved and checked again. Outcome: the
   weighted delay of the first-ranked plan against the plan in which the late train simply waits its turn behind
   every other train.

Written to seva2026/evidence/scenarios/scenario_bank.json.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import random
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail.ingest import PACKAGE_ROOT

EVIDENCE = PACKAGE_ROOT / "seva2026" / "evidence" / "scenarios" / "scenario_bank.json"
SCENARIOS = 75_556
CELL_DIMS = ("time_of_day", "current_delay", "train_class", "line", "network")
STRESS = (
    "cold_start",
    "feed_noise_pm3_min",
    "missed_report",
    "garbled_report_pm30_min",
    "unknown_train_class",
    "unknown_route_facts",
)
BALANCE_CAP = 20.0  # no situation type weighs more than 20x a typical row
MIN_CELL_SCENARIOS = 30  # a situation type is scored on its own from this many scenarios


# ---- A. forecasts ---------------------------------------------------------------------------------------------
def cells(rows: pd.DataFrame, net_q75: float) -> pd.Series:
    """The situation type of every row: time of day | how late | train class | line | network."""

    from india_rail.scenario_ml import strata

    s = strata(rows, net_q75)
    parts = [pd.Series(s[d], index=rows.index).astype(str) for d in CELL_DIMS]
    out = parts[0]
    for p in parts[1:]:
        out = out + " | " + p
    return out


def pick_scenarios(scenario_cell: pd.Series, quota: int, rng: np.random.Generator) -> np.ndarray:
    """`quota` scenario ids spread as evenly as possible over situation types (a rare type gives all it has)."""

    by_cell = {c: ids.to_numpy() for c, ids in scenario_cell.groupby(scenario_cell).groups.items()}
    remaining, take = quota, {c: 0 for c in by_cell}
    open_cells = sorted(by_cell, key=lambda c: len(by_cell[c]))
    while remaining > 0 and open_cells:
        share = max(remaining // len(open_cells), 1)
        still = []
        for c in open_cells:
            extra = min(share, len(by_cell[c]) - take[c], remaining)
            take[c] += extra
            remaining -= extra
            if take[c] < len(by_cell[c]):
                still.append(c)
            if remaining == 0:
                break
        open_cells = still
    chosen = [rng.choice(by_cell[c], size=n, replace=False) for c, n in sorted(take.items()) if n]
    return np.sort(np.concatenate(chosen)) if chosen else np.array([], dtype=int)


def damage(frame: pd.DataFrame, name: str, scenario_codes: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    """One of the six damaged inputs, applied per scenario (all of a scenario's targets see the same damage)."""

    from india_rail.network import UNKNOWN_PRIORITY

    f = frame.copy()
    n = int(scenario_codes.max()) + 1 if len(scenario_codes) else 0
    if name == "cold_start":
        f[["hist_q", "hist_change"]] = np.nan
        f["hist_n_q"] = 0
    elif name == "feed_noise_pm3_min":
        f["d_now"] = np.maximum(f.d_now + rng.uniform(-3, 3, n)[scenario_codes], 0)
    elif name == "missed_report":
        f["d_now"] = f.d_prev.fillna(f.d_now)
    elif name == "garbled_report_pm30_min":
        f["d_now"] = np.maximum(f.d_now + rng.choice([-30.0, 30.0], n)[scenario_codes], 0)
    elif name == "unknown_train_class":
        f["priority"] = UNKNOWN_PRIORITY
    elif name == "unknown_route_facts":
        f[["km_gap", "single_km_gap"]] = np.nan
    else:
        raise ValueError(name)
    return f


def balance_weights(cell: pd.Series) -> np.ndarray:
    """Square-root inverse frequency of each row's situation type, mean 1, capped at BALANCE_CAP."""

    counts = cell.map(cell.value_counts()).to_numpy(dtype=float)
    w = 1.0 / np.sqrt(counts)
    w /= w.mean()
    return np.minimum(w, BALANCE_CAP)


def _baselines(f: pd.DataFrame) -> dict[str, np.ndarray]:
    d_now = f.d_now.to_numpy(dtype=float)
    return {
        "persistence": d_now,
        "twin_rule": np.where(d_now >= 5, np.maximum(d_now - 2 - f.dwell_recovery.to_numpy(dtype=float), 0), 0.0),
    }


def _scores(err: dict[str, np.ndarray], scen: np.ndarray, cell: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {}
    frame = pd.DataFrame({"scen": scen, "cell": cell, **err})
    per_scen = frame.groupby("scen").agg({"cell": "first", **{m: "mean" for m in err}})
    per_cell = per_scen.groupby("cell")
    sizes = per_cell.size()
    scored = sizes[sizes >= MIN_CELL_SCENARIOS].index
    cell_mae = per_cell[list(err)].mean().loc[scored]
    best_base = cell_mae[["persistence", "twin_rule"]].min(axis=1)
    for m in err:
        out[m] = {
            "mae_min": round(float(frame[m].mean()), 2),
            "scenario_mae_min": round(float(per_scen[m].mean()), 2),
            "within_15_min_pct": round(float((frame[m] <= 15).mean() * 100), 2),
            "situation_balanced_mae_min": round(float(cell_mae[m].mean()), 2),
            "worst_situation_mae_min": round(float(cell_mae[m].max()), 2),
            "situations_better_than_both_baselines": f"{int((cell_mae[m] < best_base).sum())}/{len(cell_mae)}",
        }
    return out


def forecast_bank(quota: int = SCENARIOS, seed: int = 0) -> dict[str, Any]:
    import sqlite3

    from india_rail import realval
    from india_rail.realdata import REAL_DB_PATH
    from india_rail.scenario_ml import FIT_ROWS, ORIGINS, TEST_DAYS, _model, network_state, rows_with_state

    d = realval.load(REAL_DB_PATH)
    con = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    zone_of = dict(con.execute("SELECT code, zone FROM stations"))
    con.close()
    state = network_state(d["obs"], zone_of)
    rng = np.random.default_rng(seed)
    rounds, pooled_err, pooled_scen, pooled_cell, offset = [], {}, [], [], 0
    stressed: dict[str, dict[str, list]] = {s: {} for s in STRESS}
    features = realval.FORECAST_FEATURES
    # Quota per round in proportion to the scenarios each round's test days hold (counted below), fixed order.
    tests = []  # test rows first (small); each round's training rows are built only while that round runs
    for origin in ORIGINS:
        lk = realval.Lookups(d, history_until=origin)
        end = (date.fromisoformat(origin) + timedelta(days=TEST_DAYS)).isoformat()
        first = (date.fromisoformat(origin) + timedelta(days=1)).isoformat()
        tests.append((origin, lk, rows_with_state(d, lk, state, (first, end))))
    available = [t[2].groupby(["run", "now_seq"]).ngroups for t in tests]
    quotas = np.floor(np.array(available) / sum(available) * quota).astype(int)
    quotas[: quota - quotas.sum()] += 1
    for (origin, lk, test), q in zip(tests, quotas, strict=True):
        started = time.time()
        train = rows_with_state(d, lk, state, ("2024-09-01", origin))
        q75 = float(np.nanquantile(train.net_delay_2h, 0.75))
        test_cell = cells(test, q75)
        scen_codes, _ = pd.factorize(pd.MultiIndex.from_arrays([test.run, test.now_seq]))
        scen_cell = pd.Series(test_cell.to_numpy()).groupby(scen_codes).first()
        chosen = pick_scenarios(scen_cell, int(q), rng)
        mask = np.isin(scen_codes, chosen)
        held = test[mask].reset_index(drop=True)
        held_codes = pd.factorize(scen_codes[mask])[0]
        held_cell = test_cell.to_numpy()[mask]

        fit = train.iloc[rng.choice(len(train), size=min(len(train), FIT_ROWS), replace=False)].copy()
        deployed = realval.cold_start(fit, rng)
        learned = _model(seed).fit(deployed[features], deployed.d_tgt - deployed.d_now)
        robust = realval.stress_training(fit, rng)
        weights = balance_weights(cells(robust, q75))
        scen_trained = _model(seed).fit(robust[features], robust.d_tgt - robust.d_now, sample_weight=weights)

        def predict(f: pd.DataFrame, learned=learned, scen_trained=scen_trained) -> dict[str, np.ndarray]:
            d_now = f.d_now.to_numpy(dtype=float)
            return {
                **_baselines(f),
                "learned": np.maximum(d_now + learned.predict(f[features]), 0),
                "scenario_trained": np.maximum(d_now + scen_trained.predict(f[features]), 0),
            }

        truth = held.d_tgt.to_numpy(dtype=float)
        err = {m: np.abs(p - truth) for m, p in predict(held).items()}
        for m, e in err.items():
            pooled_err.setdefault(m, []).append(e)
        pooled_scen.append(held_codes + offset)
        pooled_cell.append(held_cell)
        for name in STRESS:
            damaged = damage(held, name, held_codes, rng)
            for m, p in predict(damaged).items():
                stressed[name].setdefault(m, []).append(np.abs(p - truth))
        offset += int(held_codes.max()) + 1
        rounds.append({
            "origin": origin,
            "train_days": f"2024-09-01..{origin}",
            "test_days": f"{(date.fromisoformat(origin) + timedelta(days=1)).isoformat()}.."
                         f"{(date.fromisoformat(origin) + timedelta(days=TEST_DAYS)).isoformat()}",
            "scenarios_available": int(scen_cell.size),
            "scenarios_scored": int(held_codes.max()) + 1,
            "forecasts_scored": len(held),
            "fit_rows": len(fit),
            "mae_min": {m: round(float(e.mean()), 2) for m, e in err.items()},
            "seconds": round(time.time() - started),
        })  # fmt: skip
        print(f"round {origin}: {rounds[-1]['scenarios_scored']} scenarios, {rounds[-1]['mae_min']}", flush=True)
    scen = np.concatenate(pooled_scen)
    cell = np.concatenate(pooled_cell)
    clean = _scores({m: np.concatenate(v) for m, v in pooled_err.items()}, scen, cell)
    stress = {}
    for name in STRESS:
        s = _scores({m: np.concatenate(v) for m, v in stressed[name].items()}, scen, cell)
        stress[name] = {
            m: {
                "mae_min": s[m]["mae_min"],
                "added_error_min": round(s[m]["mae_min"] - clean[m]["mae_min"], 2),
                "worst_situation_mae_min": s[m]["worst_situation_mae_min"],
            }
            for m in s
        }
    counts = Counter(cell[np.unique(scen, return_index=True)[1]])
    return {
        "scenarios": int(scen.max()) + 1,
        "scenario_variants_scored": (int(scen.max()) + 1) * (1 + len(STRESS)),
        "forecasts_scored": int(len(scen)),
        "situation_types_covered": len(counts),
        "situation_types_scored_on_their_own": sum(1 for v in counts.values() if v >= MIN_CELL_SCENARIOS),
        "scenarios_per_situation_type": {"min": min(counts.values()), "max": max(counts.values())},
        "clean": clean,
        "damaged_inputs": stress,
        "rounds": rounds,
    }


# ---- B. planner ------------------------------------------------------------------------------------------------
_TWIN = None
_LOSSES: np.ndarray | None = None


def real_losses() -> np.ndarray:
    """Time actually lost between consecutive reports of a run (1-720 min), September 2024."""

    from india_rail import realval
    from india_rail.realdata import EXTREME_DELAY_MIN, REAL_DB_PATH

    o = realval.load(REAL_DB_PATH)["obs"]
    o = o[o.delay <= EXTREME_DELAY_MIN].sort_values(["run", "seq"])
    loss = o.groupby("run", sort=False).delay.diff().to_numpy(dtype=float)
    loss = loss[np.isfinite(loss) & (loss >= 1) & (loss <= 720)]
    return np.round(loss, 1)


def _init_worker(losses: np.ndarray, twin: Any = None) -> None:
    global _TWIN, _LOSSES
    from india_rail.railguard.national import NationalTwin

    _LOSSES = losses
    _TWIN = twin if twin is not None else NationalTwin()


def _first_change(new: list[float], old: list[float]) -> int | None:
    return next((i for i, (a, b) in enumerate(zip(new, old, strict=False)) if abs(a - b) > 1e-9), None)


def check_candidate(tw: Any, key: str, cand: dict[str, Any]) -> list[str]:
    """Independent check of a ranked candidate: no conflict for the train or any train it re-times, from where
    each one changes, and no closed or obstructed track ahead of the train."""

    problems = []
    plan, here = cand["plan"], tw.position(key)["index"]
    overrides = {k: p for k, (p, _hold) in cand["yields"].items()}
    joint = {**overrides, key: plan}
    if any(c["is_conflict"] for c in tw.conflicts(key, plan, here, overrides=overrides)):
        problems.append("conflict")
    for k, p in overrides.items():
        first = _first_change(p.enter, tw.plan_of(k).enter)
        if first is not None and any(c["is_conflict"] for c in tw.conflicts(k, p, first, overrides=joint)):
            problems.append(f"conflict for {k}")
    for i in range(here, len(plan.sections)):
        sec = tw.physical(plan.sections[i])
        if plan.enter[i] >= tw.now and (not sec.available or sec.obstacle):
            problems.append(f"blocked {plan.sections[i]}")
    return problems


def planner_scenario(index: int, seed: int, tw: Any = None, losses: np.ndarray | None = None) -> dict[str, Any]:
    """One disruption scenario on the real network; returns its outcome and any violation found."""

    tw = tw if tw is not None else _TWIN
    losses = losses if losses is not None else _LOSSES
    rng = random.Random(f"{seed}:{index}")  # nosec B311 - scenario sampling, not security
    tw.start_min = rng.uniform(0, 1440)
    tw.reset()
    running = sorted(tw.running())
    if not running:
        return {"skipped": "no train running"}
    key = rng.choice(running)
    plan = tw.plan_of(key)
    first = tw.first_open(key)
    stations = [plan.frm[j] for j in range(first, min(first + 8, len(plan.sections)))]
    if not stations:
        return {"skipped": "train at its last section"}
    station, delay = rng.choice(stations), float(losses[rng.randrange(len(losses))])
    ahead = plan.sections[first : first + 12]
    roll, extra = rng.random(), "none"
    if roll < 0.10:
        extra = "closure ahead"
        tw.update_section(rng.choice(ahead), "SCENARIO", available=False)
    elif roll < 0.20:
        extra = "speed restriction ahead"
        tw.update_section(rng.choice(ahead), "SCENARIO", temp_restriction_kmph=rng.choice((30.0, 45.0, 60.0)))
    elif roll < 0.25:
        extra = "obstacle ahead"
        tw.update_section(rng.choice(ahead), "SCENARIO", obstacle=True)
    elif roll < 0.30:
        extra = "weather alert ahead"
        tw.update_section(rng.choice(ahead), "SCENARIO", weather_alert=rng.choice(("FOG", "HEAT", "FLOOD_WATCH")))
    elif roll < 0.40:
        nearby = sorted({
            k for sid in ahead[:6] for piece in tw.members.get(sid, (sid,))
            for k, *_ in tw.occupants(piece, tw.now, tw.now + 120) if k != key
        })  # fmt: skip
        other = rng.choice(nearby) if nearby else None
        if other is not None:
            o_plan, o_first = tw.plan_of(other), tw.first_open(other)
            if o_first < len(o_plan.sections):
                extra = "second train delayed nearby"
                tw.disrupt(other, o_plan.frm[o_first], float(losses[rng.randrange(len(losses))]), at_index=o_first,
                           refresh=False)  # fmt: skip
    started = time.perf_counter()
    tw.disrupt(key, station, delay, at_index=None)
    rec = tw.recommend(key, actor="scenario-bank")
    seconds = time.perf_counter() - started
    out: dict[str, Any] = {"state": rec["state"], "extra": extra, "delay_min": delay, "seconds": seconds,
                           "violations": []}  # fmt: skip
    ranking = rec["ranking"]
    if ranking["state"] != "RANKED":
        return out
    start = tw.first_open(key)
    shown = [tw._cache[(key, c["candidate_id"])] for c in ranking["candidates"]]
    for cand in shown:
        out["violations"] += [f"shown {cand['label']}: {p}" for p in check_candidate(tw, key, cand)]
    weighted = [tw._raw(key, start, c)["delay"] for c in shown]
    out["top_delay"] = weighted[0]
    out["best_shown_delay"] = min(weighted)
    waits = tw._path_through(key, tw.plan_of(key), start)
    if waits is not None and not tw._violations(waits, start, tw.runs[key]):
        out["wait_your_turn_delay"] = tw._raw(key, start, {"plan": waits, "yields": {}, "pairs": [], "holds": 0})[
            "delay"
        ]
    out["action"] = ranking["candidates"][0]["action"]
    if rec["approvable"]:
        top = shown[0]
        before = {k: tw.plan_of(k) for k in top["yields"]}
        tw.approve(rec["snapshot_id"], "N1", "scenario-bank")
        starts = {key: tw.position(key)["index"]}
        for k, old in before.items():
            ch = _first_change(tw.plan_of(k).enter, old.enter)
            starts[k] = len(old.enter) if ch is None else ch
        pending = frozenset(tw.pending)
        for k, s in starts.items():
            if any(c["is_conflict"] for c in tw.conflicts(k, tw.plan_of(k), s, ignore=pending)):
                out["violations"].append(f"approved plan conflicts for {k}")
        out["approved"] = True
    return out


def _safe(args: tuple[int, int]) -> dict[str, Any]:
    index, seed = args
    try:
        return planner_scenario(index, seed)
    except Exception as exc:  # a crash is a finding: recorded, never hidden
        return {"crash": f"{type(exc).__name__}: {exc}", "index": index}


def planner_bank(n: int = SCENARIOS, workers: int = 4, seed: int = 2026) -> dict[str, Any]:
    losses = real_losses()
    started = time.time()
    ctx = mp.get_context("fork")
    with ctx.Pool(workers, initializer=_init_worker, initargs=(losses,)) as pool:
        results = pool.map(_safe, [(i, seed) for i in range(n)], chunksize=200)
    return summarise_planner(results, losses, time.time() - started, seed)


def summarise_planner(results: list[dict[str, Any]], losses: np.ndarray, wall: float, seed: int) -> dict[str, Any]:
    done = [r for r in results if "state" in r]
    crashes = [r for r in results if "crash" in r]
    violations = [v for r in done for v in r["violations"]]
    ranked = [r for r in done if "top_delay" in r]
    compared = [r for r in ranked if "wait_your_turn_delay" in r]
    saved = np.array([r["wait_your_turn_delay"] - r["top_delay"] for r in compared])
    best_saved = np.array([r["wait_your_turn_delay"] - r["best_shown_delay"] for r in compared])
    seconds = np.array([r["seconds"] for r in done])
    by_extra: dict[str, dict[str, Any]] = {}
    for r in done:
        e = by_extra.setdefault(r["extra"], {"scenarios": 0, "ranked": 0, "states": Counter()})
        e["scenarios"] += 1
        e["ranked"] += "top_delay" in r
        e["states"][r["state"]] += 1
    for e in by_extra.values():
        e["ranked_pct"] = round(100 * e["ranked"] / max(e["scenarios"], 1), 1)
        e["states"] = dict(e["states"])
    return {
        "scenarios": len(results),
        "run": len(done),
        "skipped": Counter(r["skipped"] for r in results if "skipped" in r),
        "crashes": len(crashes),
        "first_crashes": crashes[:5],
        "violations": len(violations),
        "first_violations": violations[:10],
        "real_delays_drawn_from": {
            "losses_observed": int(len(losses)),
            "median_min": float(np.median(losses)),
            "p90_min": float(np.percentile(losses, 90)),
        },  # fmt: skip
        "states": dict(Counter(r["state"] for r in done)),
        "first_ranked_action": dict(Counter(r["action"] for r in ranked)),
        "approved_and_rechecked": sum(1 for r in done if r.get("approved")),
        "by_condition": by_extra,
        "delay_vs_wait_your_turn": {
            "scenarios_compared": len(compared),
            "first_ranked_saves_weighted_min": {
                "median": round(float(np.median(saved)), 1) if len(saved) else None,
                "mean": round(float(saved.mean()), 1) if len(saved) else None,
                "total_per_1000_scenarios": round(float(saved.sum()) / max(len(saved), 1) * 1000),
                "better_pct": round(float((saved > 0.5).mean() * 100), 1) if len(saved) else None,
                "same_pct": round(float((np.abs(saved) <= 0.5).mean() * 100), 1) if len(saved) else None,
                "worse_pct": round(float((saved < -0.5).mean() * 100), 1) if len(saved) else None,
            },
            "best_shown_saves_weighted_min": {
                "median": round(float(np.median(best_saved)), 1) if len(best_saved) else None,
                "mean": round(float(best_saved.mean()), 1) if len(best_saved) else None,
            },
            "note": "Weighted final-arrival delay of the train and every train it re-times (weights by train class). "
            "The first-ranked plan also weighs separation margins, track stress, energy, threats, evidence and "
            "complexity, so it is not always the lowest-delay plan; the lowest-delay plan shown is reported too.",
        },
        "seconds_per_scenario": {
            "median": round(float(np.median(seconds)), 3),
            "p95": round(float(np.percentile(seconds, 95)), 3),
        }
        if len(seconds)
        else None,  # fmt: skip
        "seed": seed,
        "wall_seconds": round(wall),
    }


# ---- run --------------------------------------------------------------------------------------------------------
def run(out: Path = EVIDENCE, scenarios: int = SCENARIOS, planner: int = SCENARIOS, workers: int = 4) -> dict:
    from india_rail.railguard.national import timetable_source

    started = time.time()
    report: dict[str, Any] = {"what": __doc__.split("\n\n")[1].strip(), "labels": []}
    if scenarios:
        report["forecasts"] = forecast_bank(scenarios)
    if planner:
        report["planner"] = planner_bank(planner, workers)
        report["planner"]["timetable"] = timetable_source()[0]
    report["labels"] = [
        "Forecast scenarios are real (September 2024 observed running); the six damaged inputs are applied to "
        "real scenarios, whose real outcome is the answer.",
        "Planner scenarios use the real network and current timetable and real observed time losses; the "
        "disruptions are sampled, not observed, and their outcome is the twin's own projection.",
        "Not covered: fog (December-February) and monsoon running, freight trains (no public observed running).",
    ]
    report["seconds"] = round(time.time() - started)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report
