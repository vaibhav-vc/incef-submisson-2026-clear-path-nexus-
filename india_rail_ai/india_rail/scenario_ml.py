"""Delay forecasts trained and scored under different situations, on real running (September 2024).

    python -m india_rail real scenarios [--out seva2026/evidence/real_data/scenario_ml.json]

One train/test split can flatter a model. Here the forecast is retrained in rolling-origin rounds - each round
learns only from days up to its origin and is scored on the next four days - and every score is broken down by
the situation the forecast was made in:

* time of day, weekday or weekend, how late the train already is, train class, single or double line,
  forecast horizon, the railway zone, and how disrupted the network is at that moment;
* stress situations that are not frequent enough in September to score on their own:
  - cold start: a train/station with no delay history (a new train, or a renumbered one in a new timetable),
  - feed noise: the reported current delay off by a random +/-3 minutes (late or garbled reports).

Two learned variants are compared with the baselines (persistence: the delay stays as it is; the twin's rule:
dwell recovery only):

* `learned`: the features of the deployed forecaster (realval.FORECAST_FEATURES);
* `learned_network`: plus the state of the network when the forecast is made - mean delay of every train
  reported in the last two hours across India and in the train's own zone - trained with 15% of rows having
  their history, and 15% their network state, removed, so the model has learned what to do without them.

Network state uses only reports made at or before the moment of the forecast, as a live feed would have them.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail.ingest import PACKAGE_ROOT
from india_rail.realdata import EXTREME_DELAY_MIN, REAL_DB_PATH

EVIDENCE = PACKAGE_ROOT / "seva2026" / "evidence" / "real_data" / "scenario_ml.json"
ORIGINS = ("2024-09-08", "2024-09-12", "2024-09-16", "2024-09-20", "2024-09-24")
TEST_DAYS = 4
WINDOW_MIN = 120
NETWORK_FEATURES = ["net_delay_2h", "zone_delay_2h", "zone_reports_2h"]
FIT_ROWS = 600_000
DAY0 = date(2024, 9, 1)


# ---- network state ---------------------------------------------------------------------------------
def _window_mean(t: np.ndarray, v: np.ndarray, window: float) -> tuple[np.ndarray, np.ndarray]:
    """For each point (sorted by t): mean of v and count over (t - window, t]."""

    cs = np.concatenate([[0.0], np.cumsum(v)])
    hi = np.searchsorted(t, t, side="right")
    lo = np.searchsorted(t, t - window, side="right")
    n = hi - lo
    return (cs[hi] - cs[lo]) / np.maximum(n, 1), n


def network_state(obs: pd.DataFrame, zone_of: dict[str, str]) -> pd.DataFrame:
    """Mean delay of all reports in the last two hours, India-wide and in the zone, at each report's time."""

    o = obs[obs.delay <= EXTREME_DELAY_MIN].copy()
    days = (pd.to_datetime(o.date) - pd.Timestamp(DAY0)).dt.days.to_numpy()
    o["abs_min"] = days * 1440 + o.act.to_numpy(dtype=float)
    o["zone"] = o.station.map(zone_of).fillna("?")
    o = o.sort_values("abs_min", kind="stable")
    mean, _ = _window_mean(o.abs_min.to_numpy(), o.delay.to_numpy(dtype=float), WINDOW_MIN)
    o["net_delay_2h"] = mean
    o["zone_delay_2h"], o["zone_reports_2h"] = np.nan, 0.0
    for _zone, g in o.groupby("zone", sort=False):
        m, n = _window_mean(g.abs_min.to_numpy(), g.delay.to_numpy(dtype=float), WINDOW_MIN)
        o.loc[g.index, "zone_delay_2h"], o.loc[g.index, "zone_reports_2h"] = m, n
    return o[["run", "seq", "zone", *NETWORK_FEATURES]]


# ---- rows --------------------------------------------------------------------------------------------
def rows_with_state(
    d: dict[str, pd.DataFrame], lookups: Any, state: pd.DataFrame, dates: tuple[str, str]
) -> pd.DataFrame:
    """Forecast rows (realval.forecast_rows) for runs dated in [dates], with the network state at the 'now' stop."""

    from india_rail import realval

    sub = {**d, "obs": d["obs"][(d["obs"].date >= dates[0]) & (d["obs"].date <= dates[1])]}
    rows = realval.forecast_rows(sub, lookups)
    keyed = state.set_index(["run", "seq"])
    joined = keyed.reindex(pd.MultiIndex.from_arrays([rows.run, rows.now_seq]))
    for col in ("zone", *NETWORK_FEATURES):
        rows[col] = joined[col].to_numpy()
    return rows


def training_rows(d: dict[str, pd.DataFrame], lookups: Any, state: pd.DataFrame, origin: str) -> pd.DataFrame:
    """Rows a model trained at `origin` may learn from: runs started by then whose answer was observed by then
    (a run started on the origin day can report the next day, after the forecasts it would be scored on)."""

    rows = rows_with_state(d, lookups, state, ("2024-09-01", origin))
    return rows[rows.tgt_day <= origin].reset_index(drop=True)


# ---- scenarios -----------------------------------------------------------------------------------------
def strata(rows: pd.DataFrame, net_q75: float) -> dict[str, pd.Series]:
    hour = rows.hour
    tod = np.select([(hour >= 22) | (hour < 6), hour < 10, hour < 17], ["night 22-06", "morning 06-10", "day 10-17"],
                    "evening 17-22")  # fmt: skip
    single_share = rows.single_km_gap / rows.km_gap.replace(0, np.nan)
    return {
        "time_of_day": pd.Series(tod, index=rows.index),
        "day_type": pd.Series(np.where(rows.weekday >= 5, "weekend", "weekday"), index=rows.index),
        # 5 minutes late counts as late, as in the twin's rule
        "current_delay": pd.cut(
            rows.d_now, [-1e9, 5, 30, 120, 1e9], labels=["<5 min", "5-30", "30-120", ">=120"], right=False
        ),  # fmt: skip
        "train_class": rows.priority.map(
            {1: "premium", 2: "superfast", 3: "mail/express", 4: "passenger/suburban", 5: "hill"}
        ).fillna("other"),  # fmt: skip
        "line": pd.Series(
            np.select(
                [single_share.isna() & rows.km_gap.isna(), single_share.fillna(0) >= 0.5],
                ["route facts unknown", "mostly single line"],
                "mostly double/multiple",
            ),
            index=rows.index,
        ),  # fmt: skip
        "horizon": pd.cut(rows.sch_gap, [-1, 60, 180, 360, 1e9], labels=["<=1h", "1-3h", "3-6h", ">6h"]),
        "network": pd.Series(
            np.where(rows.net_delay_2h >= net_q75, "disrupted (top quarter)", "normal"), index=rows.index
        ),
        "zone": rows.zone.fillna("?"),
        "history": pd.Series(np.where(rows.hist_n_q > 0, "has history", "no history (cold start)"), index=rows.index),
    }


def _model(seed: int):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=0.08, max_leaf_nodes=63,
                                         min_samples_leaf=200, l2_regularization=1.0, random_state=seed)  # fmt: skip


def _augment(fit: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Teach the model the situations it must survive: no history for the train, no network picture."""

    out = fit.copy()
    blank_hist = rng.random(len(out)) < 0.15
    out.loc[blank_hist, ["hist_q", "hist_change"]] = np.nan
    out.loc[blank_hist, "hist_n_q"] = 0
    blank_net = rng.random(len(out)) < 0.15
    out.loc[blank_net, NETWORK_FEATURES] = np.nan
    return out


def run_round(d, state, origin: str, seed: int = 0) -> dict[str, Any]:
    from india_rail import realval

    lk = realval.Lookups(d, history_until=origin)
    end = (date.fromisoformat(origin) + timedelta(days=TEST_DAYS)).isoformat()
    train = training_rows(d, lk, state, origin)
    test = rows_with_state(d, lk, state, ((date.fromisoformat(origin) + timedelta(days=1)).isoformat(), end))
    rng = np.random.default_rng(seed)
    fit = train.iloc[rng.choice(len(train), size=min(len(train), FIT_ROWS), replace=False)]
    base_f, net_f = realval.FORECAST_FEATURES, realval.FORECAST_FEATURES + NETWORK_FEATURES
    y = fit.d_tgt - fit.d_now
    base = _model(seed).fit(fit[base_f], y)
    aug = _augment(fit, rng)
    net = _model(seed).fit(aug[net_f], aug.d_tgt - aug.d_now)

    def predict(frame: pd.DataFrame) -> dict[str, np.ndarray]:
        return {
            "persistence": frame.d_now.to_numpy(dtype=float),
            "twin_rule": np.where(frame.d_now >= 5, np.maximum(frame.d_now - 2 - frame.dwell_recovery, 0), 0.0),
            "learned": np.maximum(frame.d_now + base.predict(frame[base_f]), 0),
            "learned_network": np.maximum(frame.d_now + net.predict(frame[net_f]), 0),
        }

    truth = test.d_tgt.to_numpy(dtype=float)
    preds = predict(test)
    errs = {k: np.abs(v - truth) for k, v in preds.items()}
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for dim, labels in strata(test, float(np.nanquantile(train.net_delay_2h, 0.75))).items():
        labels = pd.Series(labels).astype(str).to_numpy()
        by[dim] = {}
        for lab in pd.unique(labels):
            mask = labels == lab
            if mask.sum() < 500:
                continue
            by[dim][lab] = {"n": int(mask.sum()), **{k: round(float(e[mask].mean()), 2) for k, e in errs.items()}}
    stress = {}
    cold = test.copy()
    cold[["hist_q", "hist_change"]] = np.nan
    cold["hist_n_q"] = 0
    noisy = test.copy()
    noisy["d_now"] = np.maximum(noisy.d_now + rng.uniform(-3, 3, len(noisy)), 0)
    blind = test.copy()
    blind[NETWORK_FEATURES] = np.nan
    for name, frame in (("cold_start_all_history_removed", cold), ("feed_noise_pm3_min", noisy),
                        ("no_network_picture", blind)):  # fmt: skip
        stress[name] = {k: round(float(np.abs(v - truth).mean()), 2) for k, v in predict(frame).items()}
    return {
        "origin": origin,
        "train_days": f"2024-09-01..{origin}",
        "test_days": f"{(date.fromisoformat(origin) + timedelta(days=1)).isoformat()}..{end}",
        "train_rows": len(train),
        "fit_rows": len(fit),
        "test_rows": len(test),
        "mae": {k: round(float(e.mean()), 2) for k, e in errs.items()},
        "within_15_min_pct": {k: round(float((e <= 15).mean() * 100), 2) for k, e in errs.items()},
        "by_situation": by,
        "stress": stress,
    }


def summarise(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    models = list(rounds[0]["mae"])
    overall = {m: {"mean": round(float(np.mean([r["mae"][m] for r in rounds])), 2),
                   "worst_round": round(float(np.max([r["mae"][m] for r in rounds])), 2)} for m in models}  # fmt: skip
    situations: dict[str, dict[str, Any]] = {}
    for dim in rounds[0]["by_situation"]:
        situations[dim] = {}
        labels = set().union(*(r["by_situation"].get(dim, {}).keys() for r in rounds))
        for lab in sorted(labels):
            cells = [r["by_situation"][dim][lab] for r in rounds if lab in r["by_situation"].get(dim, {})]
            entry = {"rounds": len(cells), "n": int(sum(c["n"] for c in cells))}
            for m in models:
                entry[m] = round(float(np.average([c[m] for c in cells], weights=[c["n"] for c in cells])), 2)
            best_baseline = min(entry["persistence"], entry["twin_rule"])
            entry["learned_network_gain_vs_best_baseline_min"] = round(best_baseline - entry["learned_network"], 2)
            situations[dim][lab] = entry
    wins = sum(
        1 for dim in situations.values() for e in dim.values() if e["learned_network_gain_vs_best_baseline_min"] > 0
    )
    total = sum(len(dim) for dim in situations.values())
    stress = {name: {m: round(float(np.mean([r["stress"][name][m] for r in rounds])), 2) for m in models}
              for name in rounds[0]["stress"]}  # fmt: skip
    return {"overall_mae_min": overall, "situations_where_learned_network_beats_both_baselines": f"{wins}/{total}",
            "by_situation": situations, "stress": stress}  # fmt: skip


def run(out: Path = EVIDENCE, origins: tuple[str, ...] = ORIGINS) -> dict[str, Any]:
    import sqlite3

    from india_rail import realval
    from india_rail.railguard.national import timetable_source

    started = time.time()
    d = realval.load(REAL_DB_PATH)
    con = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    zone_of = dict(con.execute("SELECT code, zone FROM stations"))
    con.close()
    state = network_state(d["obs"], zone_of)
    rounds = []
    for k, origin in enumerate(origins):
        rounds.append(run_round(d, state, origin, seed=k))
        print(f"round {origin}: {rounds[-1]['mae']}", flush=True)
    report = {
        "what": __doc__.split("\n\n")[1].strip(),
        "data": {
            "observed_running": "September 2024 actual arrivals (see realdata.py)",
            "timetable_used_by_twin": timetable_source()[0],
        },  # fmt: skip
        "protocol": {
            "origins": list(origins),
            "test_days_per_round": TEST_DAYS,
            "fit_rows_per_round": FIT_ROWS,
            "network_window_min": WINDOW_MIN,
            "augmentation": "15% rows without history, 15% without network state (learned_network only)",
        },
        "summary": summarise(rounds),
        "rounds": rounds,
        "not_covered": [
            "Fog (December-February) and monsoon flooding are not in a September sample: retrain on a "
            "full year of running before relying on forecasts in those seasons.",
            "Freight trains: no observed freight running is public.",
        ],  # fmt: skip
        "seconds": round(time.time() - started),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    return report
