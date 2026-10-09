"""Verification against what really happened: September 2024 actual train running.

    python -m india_rail real validate [--out seva2026/evidence/real_data/real_validation.json]

Every number here is computed from observed actual arrival times (see realdata.py), never from data this
project generated. The time split is forward in time: anything learned uses 1-20 September only and is
scored on 21-30 September, the way a deployed system would be used.

1. credibility   - destination punctuality in the data vs the Ministry of Railways' published figure;
2. timetable     - how far the 2016 open timetable is from the 2024 one (why the real timetable matters);
3. sections      - real time lost per section, on single and on double line (OSM line count);
4. forecast      - arrival-delay forecasts at downstream stations: the twin's current rule, persistence,
                   and a model learned from real running, with a run-grouped bootstrap interval;
5. conflicts     - retrospective shadow run: the national twin, given each train's real delay at fixed times
                   of day, flags conflicts; did the flagged trains really lose time on those sections?
                   Measured with and without the real track data;
6. feed replay   - a real morning's arrivals sent through the signed live-feed gateway, as NTES/COA would.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail.ingest import DB_PATH, PACKAGE_ROOT
from india_rail.network import DEFAULT_PRIORITY
from india_rail.realdata import EXTREME_DELAY_MIN, OBSERVED, REAL_DB_PATH

EVIDENCE = PACKAGE_ROOT / "seva2026" / "evidence" / "real_data" / "real_validation.json"
ETA_MODEL_PATH = PACKAGE_ROOT / "models" / "eta_model.joblib"
SPLIT_DATE = "2024-09-20"  # train on dates up to and including this, test on later dates
OFFICIAL_PUNCTUALITY = {
    "value_pct": 77.12,
    "period": "2024-25 (financial year)",
    "measure": "Mail/Express trains arriving at destination within 15 minutes of schedule",
    "publisher": "Ministry of Railways (Indian Railway Year Book; written reply in Lok Sabha)",
}
ON_TIME_MIN = 15  # Indian Railways' punctuality allowance at destination
LOSS_MIN = 5  # a section traversal "lost time" if the delay grew by at least this much
SUBURBAN_TYPES = {"Pass", "MEMU", "DEMU"}


# ---- loading ---------------------------------------------------------------------------------------
def load(db: Path = REAL_DB_PATH, obs_db: Path | None = None) -> dict[str, pd.DataFrame]:
    """Route tables of the timetable in `db`, and observed running from `obs_db` (default: the same database)."""

    ocon = sqlite3.connect(f"file:{obs_db or db}?mode=ro", uri=True)
    obs = pd.read_sql(
        "SELECT train_number AS train, run_date AS date, seq, station_code AS station, sch_arr_min AS sch, "
        "act_arr_min AS act, delay_min AS delay FROM observed_stops ORDER BY train_number, run_date, seq",
        ocon,
    )
    ocon.close()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    stops = pd.read_sql(
        "SELECT train_number AS train, seq, station_code AS station, arr_min, dep_min, dwell_min FROM stops", con
    )
    sections = pd.read_sql("SELECT train_number AS train, seq, from_code, to_code, crow_km FROM sections", con)
    trains = pd.read_sql("SELECT number AS train, type FROM trains", con)
    km = dict(con.execute("SELECT edge, km FROM official_section_km").fetchall())
    try:
        lines = dict(con.execute("SELECT edge, lines FROM osm_sections WHERE quality = 'ACCEPTED'").fetchall())
    except sqlite3.OperationalError:
        lines = {}
    con.close()
    edge = np.where(sections.from_code < sections.to_code, sections.from_code + "-" + sections.to_code,
                    sections.to_code + "-" + sections.from_code)  # fmt: skip
    sections["edge"] = edge
    sections["km"] = [km.get(e, np.nan) for e in edge]
    sections["km"] = sections["km"].fillna(sections.crow_km * 1.03)
    sections["single"] = [lines.get(e) == 1 for e in edge]
    sections["osm_lines"] = [lines.get(e) for e in edge]
    # An unknown train class stays unknown (NaN) for the forecaster, not the Mail/Express value the twin assumes
    trains["priority"] = trains.type.map(DEFAULT_PRIORITY).astype(float)
    obs["run"] = obs.train + "|" + obs.date
    # The day each report was made (a run started on the 20th can report on the 21st): history and training rows
    # are cut by when a report was observed, not by the day its run started.
    at = obs.act.where(obs.act.notna(), obs.sch + obs.delay).fillna(0.0).to_numpy(dtype=float)
    start = pd.to_datetime(obs.date).to_numpy()
    obs["obs_day"] = pd.DatetimeIndex(start + pd.to_timedelta(np.floor(at / 1440), unit="D")).strftime("%Y-%m-%d")
    return {"obs": obs, "stops": stops, "sections": sections, "trains": trains}


# ---- 1. credibility --------------------------------------------------------------------------------
def credibility(d: dict[str, pd.DataFrame]) -> dict[str, Any]:
    obs, stops, trains = d["obs"], d["stops"], d["trains"]
    last_seq = stops.groupby("train").seq.max()
    final = obs[obs.seq == obs.train.map(last_seq)]
    final = final.merge(trains[["train", "type"]], on="train", how="left")
    mail_express = final[~final.type.isin(SUBURBAN_TYPES)]
    share = float((mail_express.delay <= ON_TIME_MIN).mean() * 100)
    return {
        "runs_observed": int(obs.run.nunique()),
        "arrivals_observed": len(obs),
        "trains": int(obs.train.nunique()),
        "dates": [obs.date.min(), obs.date.max()],
        "runs_with_destination_observed": int(final.run.nunique()),
        "destination_on_time_pct_mail_express": round(share, 2),
        "official_figure": OFFICIAL_PUNCTUALITY,
        "difference_points": round(share - OFFICIAL_PUNCTUALITY["value_pct"], 2),
        "median_destination_delay_min": float(mail_express.delay.median()),
        "extreme_delays_over_12h_excluded_from_accuracy": int((obs.delay > EXTREME_DELAY_MIN).sum()),
        "reading": (
            f"{share:.1f}% on time in September 2024 against the Ministry's {OFFICIAL_PUNCTUALITY['value_pct']}% "
            "for the whole financial year, which includes the winter fog months: a credible sample of real running."
        ),
    }


# ---- 2. timetable drift ----------------------------------------------------------------------------
def timetable_drift(open_db: Path = DB_PATH, real_db: Path = REAL_DB_PATH) -> dict[str, Any]:
    if not open_db.exists():
        return {"skipped": "open timetable not ingested"}
    q = "SELECT number, from_code, to_code, journey_min, n_stops FROM trains"
    old = pd.read_sql(q, sqlite3.connect(f"file:{open_db}?mode=ro", uri=True)).set_index("number")
    new = pd.read_sql(q, sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)).set_index("number")
    both = new.join(old, rsuffix="_2016", how="inner")
    same_route = both[(both.from_code == both.from_code_2016) & (both.to_code == both.to_code_2016)]
    change = (same_route.journey_min - same_route.journey_min_2016).abs()
    edges = {}
    for label, db in (("2016", open_db), ("2024", real_db)):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        edges[label] = {tuple(sorted(r)) for r in con.execute("SELECT DISTINCT from_code, to_code FROM sections")}
        con.close()
    return {
        "trains_2024": len(new),
        "trains_2016": len(old),
        "train_numbers_in_both": len(both),
        "same_number_same_origin_and_destination": len(same_route),
        "same_number_different_route_or_reused": len(both) - len(same_route),
        "trains_2024_not_in_2016": len(new) - len(both),
        "journey_time_changed_over_15_min_pct": round(float((change > 15).mean() * 100), 1),
        "journey_time_abs_change_median_min": float(change.median()),
        "sections_2024_missing_from_2016": len(edges["2024"] - edges["2016"]),
        "reading": "The 2016 open timetable is far from the 2024 railway; the twin now runs on the 2024 one.",
    }


# ---- 3. real time lost per section -----------------------------------------------------------------
def section_running(d: dict[str, pd.DataFrame]) -> dict[str, Any]:
    obs, sections = d["obs"], d["sections"]
    o = obs[obs.delay <= EXTREME_DELAY_MIN]
    nxt = o.groupby("run").shift(-1)
    pair = o[(nxt.seq == o.seq + 1)].copy()
    pair["loss"] = nxt.delay[pair.index] - pair.delay
    pair = pair.merge(sections[["train", "seq", "single", "osm_lines"]], on=["train", "seq"], how="left")

    def stats(frame: pd.DataFrame) -> dict[str, Any]:
        return {
            "traversals": len(frame),
            "mean_time_lost_min": round(float(frame.loss.mean()), 2),
            "lost_5_min_or_more_pct": round(float((frame.loss >= LOSS_MIN).mean() * 100), 2),
            "lost_15_min_or_more_pct": round(float((frame.loss >= 15).mean() * 100), 2),
            "recovered_time_pct": round(float((frame.loss < 0).mean() * 100), 2),
        }

    mapped = pair[pair.osm_lines.notna()]
    return {
        "all": stats(pair),
        "osm_single_line": stats(mapped[mapped.single]),
        "osm_double_or_more": stats(mapped[~mapped.single]),
        "note": "Consecutive timetabled halts that both reported. Early running is recorded as 0 late, so "
        "recovery below the timetable is not visible in this data.",
    }


# ---- 4. arrival-delay forecasting -------------------------------------------------------------------
class Lookups:
    """Per (train, stop) route facts used as forecast features, plus delay history from training dates.

    Route facts come from the timetable the forecast is used on; delay history is keyed by (train, station), so
    the history observed in 2024 serves the same train at the same station in a newer timetable."""

    def __init__(self, d: dict[str, pd.DataFrame], history_until: str = SPLIT_DATE):
        stops, sections, trains, obs = d["stops"], d["sections"], d["trains"], d["obs"]
        self.history_until = history_until
        sec = sections.sort_values(["train", "seq"])
        cum_km = sec.groupby("train").km.cumsum()
        cum_single = (sec.km * sec.single).groupby(sec.train).cumsum()
        # km and single-line km from the origin to stop (seq + 1); stop 0 is at 0
        self.km = {(t, s + 1): k for t, s, k in zip(sec.train, sec.seq, cum_km, strict=True)}
        self.single = {(t, s + 1): k for t, s, k in zip(sec.train, sec.seq, cum_single, strict=True)}
        for t in sec.train.unique():
            self.km[(t, 0)] = self.single[(t, 0)] = 0.0
        st = stops.sort_values(["train", "seq"])
        cum_r = np.maximum(st.dwell_min - 2, 0).groupby(st.train).cumsum()
        self.cum_r = {(t, s): c for t, s, c in zip(st.train, st.seq, cum_r, strict=True)}
        self.sch = {(t, s): a for t, s, a in zip(st.train, st.seq, st.arr_min, strict=True)}
        self.station = {(t, s): c for t, s, c in zip(st.train, st.seq, st.station, strict=True)}
        self.priority = dict(zip(trains.train, trains.priority, strict=True))
        hist = obs[(obs.obs_day <= history_until) & (obs.delay <= EXTREME_DELAY_MIN)]
        agg = hist.groupby(["train", "station"]).delay.agg(["sum", "count"])
        self.hist_sum = agg["sum"].to_dict()
        self.hist_n = agg["count"].to_dict()

    def rows(self, train: str, day: str, p: int, d_now: float, targets: list[int], own: dict | None = None) -> dict:
        """Feature rows for a train at stop `p` with delay `d_now`, forecasting the given later stops.

        `own` (seq -> delay) is this run's own reports that are in the history (observed by `history_until`):
        they are left out of it, so no row ever sees its own answer."""

        km, single, cum_r = self.km, self.single, self.cum_r
        leave_out = own or {}

        def hist(seq: int) -> tuple[float, int]:
            code = self.station.get((train, seq))
            total, n = self.hist_sum.get((train, code), 0.0), self.hist_n.get((train, code), 0)
            if seq in leave_out:
                total, n = total - leave_out[seq], n - 1
            return (total / n if n > 0 else np.nan), n

        h_p, _ = hist(p)
        sch_p = self.sch.get((train, p), np.nan)
        out: dict[str, list] = {k: [] for k in ("q", "sch_gap", "stops_gap", "km_gap", "single_km_gap",
                                                  "dwell_recovery", "hist_q", "hist_n_q", "hist_change")}  # fmt: skip
        for q in targets:
            h_q, n_q = hist(q)
            out["q"].append(q)
            out["sch_gap"].append(self.sch.get((train, q), np.nan) - sch_p)
            out["stops_gap"].append(q - p)
            out["km_gap"].append(km.get((train, q), np.nan) - km.get((train, p), np.nan))
            out["single_km_gap"].append(single.get((train, q), np.nan) - single.get((train, p), np.nan))
            out["dwell_recovery"].append(cum_r.get((train, q - 1), 0.0) - cum_r.get((train, p), 0.0))
            out["hist_q"].append(h_q)
            out["hist_n_q"].append(n_q)
            out["hist_change"].append(h_q - h_p)
        n = len(targets)
        out["d_now"] = [d_now] * n
        out["priority"] = [self.priority.get(train, np.nan)] * n
        out["hour"] = [(sch_p % 1440) / 60] * n
        out["weekday"] = [date.fromisoformat(day).weekday()] * n
        return out


def forecast_rows(d: dict[str, pd.DataFrame], lookups: Lookups | None = None) -> pd.DataFrame:
    """(now, target) pairs per observed run: targets 1, 3 and 6 reporting stops ahead and the last one."""

    lk = lookups or Lookups(d)
    o = d["obs"][d["obs"].delay <= EXTREME_DELAY_MIN]
    columns: dict[str, list] = {}
    for run, g in o.groupby("run", sort=False):
        seq, delay, seen = g.seq.to_numpy(), g.delay.to_numpy(), g.obs_day.to_numpy()
        n = len(seq)
        if n < 2:
            continue
        train, day = g.train.iloc[0], g.date.iloc[0]
        own = {int(s): float(v) for s, v, o in zip(seq, delay, seen, strict=True) if o <= lk.history_until}
        for p in range(n - 1):
            qs = sorted(q for q in {p + 1, p + 3, p + 6, n - 1} if p < q < n)
            block = lk.rows(train, day, int(seq[p]), float(delay[p]), [int(seq[q]) for q in qs], own)
            block["d_tgt"] = [float(delay[q]) for q in qs]
            block["tgt_day"] = [seen[q] for q in qs]  # when the answer was observed
            block["d_prev"] = [float(delay[p - 1]) if p else np.nan] * len(qs)  # the run's previous report
            block["now_seq"] = [int(seq[p])] * len(qs)
            block["run"], block["date"] = [run] * len(qs), [day] * len(qs)
            for k, v in block.items():
                columns.setdefault(k, []).extend(v)
    return pd.DataFrame(columns)


COLD_START_SHARE = 0.15
FORECAST_FEATURES = ["d_now", "sch_gap", "stops_gap", "km_gap", "single_km_gap", "dwell_recovery", "priority",
                     "hour", "weekday", "hist_change", "hist_q", "hist_n_q"]  # fmt: skip
# Damaged inputs a live forecaster must survive, with the share of training rows given each (scenario_bank.py)
STRESS_TRAINING = {
    "feed_noise_pm3_min": 0.05,
    "missed_report": 0.05,
    "garbled_report_pm30_min": 0.02,
    "unknown_train_class": 0.03,
    "unknown_route_facts": 0.03,
}


def cold_start(fit: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """A share of rows without the train's delay history, so the model has learned what to do for a train it has
    never seen (new or renumbered in a new timetable)."""

    fit = fit.copy()
    no_history = rng.random(len(fit)) < COLD_START_SHARE
    fit.loc[no_history, ["hist_q", "hist_change"]] = np.nan
    fit.loc[no_history, "hist_n_q"] = 0
    return fit


def input_states(n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """The recipe's input state of `n` rows: (no history?, damaged input: an index into STRESS_TRAINING, or its
    length for none). History is withheld from COLD_START_SHARE of rows; at most one damage per row, in the
    shares STRESS_TRAINING gives."""

    cold = rng.random(n) < COLD_START_SHARE
    edges = np.cumsum(list(STRESS_TRAINING.values()))
    return cold, np.searchsorted(edges, rng.random(n), side="right")


def apply_input_states(rows: pd.DataFrame, cold: np.ndarray, which: np.ndarray, rng: np.random.Generator):
    """`rows` as a live forecaster would see them in the given input states (the target stays the real outcome)."""

    out = rows.copy()
    out.loc[cold, ["hist_q", "hist_change"]] = np.nan
    out.loc[cold, "hist_n_q"] = 0
    d_now = out.d_now.to_numpy(dtype=float).copy()
    pick = {k: which == i for i, k in enumerate(STRESS_TRAINING)}
    noisy = pick["feed_noise_pm3_min"]
    d_now[noisy] = np.maximum(d_now[noisy] + rng.uniform(-3, 3, int(noisy.sum())), 0)
    missed = pick["missed_report"] & out.d_prev.notna().to_numpy()
    d_now[missed] = out.d_prev.to_numpy(dtype=float)[missed]
    garbled = pick["garbled_report_pm30_min"]
    d_now[garbled] = np.maximum(d_now[garbled] + rng.choice([-30.0, 30.0], int(garbled.sum())), 0)
    out["d_now"] = d_now
    out.loc[pick["unknown_train_class"], "priority"] = np.nan
    out.loc[pick["unknown_route_facts"], ["km_gap", "single_km_gap"]] = np.nan
    return out


def stress_training(fit: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """cold_start, plus rows with the damaged inputs of STRESS_TRAINING (at most one per row, in the shares
    given): the target stays the real outcome, so the model learns how far to trust a report that may be noisy,
    stale or wrong."""

    cold, which = input_states(len(fit), rng)
    return apply_input_states(fit, cold, which, rng)


# ---- training conditions: real pairs under input states ------------------------------------------------------
N_STATES = 2 * (len(STRESS_TRAINING) + 1)  # history known or withheld x (no damage or one of the damages)


def _state_code(cold: np.ndarray, which: np.ndarray) -> np.ndarray:
    return cold.astype(np.int64) * (len(STRESS_TRAINING) + 1) + which


def recipe_state_shares() -> np.ndarray:
    """Share of each input state (by _state_code) in the recipe."""

    damage = np.array([*STRESS_TRAINING.values(), 1 - sum(STRESS_TRAINING.values())])
    return np.concatenate([(1 - COLD_START_SHARE) * damage, COLD_START_SHARE * damage])


def _effective(rows: pd.DataFrame, out: pd.DataFrame, cold: np.ndarray, which: np.ndarray) -> np.ndarray:
    """The input state each row really ended in (a damage that changed nothing - a missed report with no earlier
    report, an unknown class already unknown - leaves the row as it was)."""

    none = len(STRESS_TRAINING)
    had_history = (rows.hist_n_q.to_numpy() > 0) | rows.hist_q.notna().to_numpy() | rows.hist_change.notna().to_numpy()
    eff_cold = cold & had_history
    names = list(STRESS_TRAINING)
    changed = np.zeros(len(rows), dtype=bool)
    moved = out.d_now.to_numpy(dtype=float) != rows.d_now.to_numpy(dtype=float)
    for i, name in enumerate(names):
        m = which == i
        if name in ("feed_noise_pm3_min", "missed_report", "garbled_report_pm30_min"):
            changed[m] = moved[m]
        elif name == "unknown_train_class":
            changed[m] = rows.priority.notna().to_numpy()[m]
        else:
            changed[m] = (rows.km_gap.notna() | rows.single_km_gap.notna()).to_numpy()[m]
    return _state_code(eff_cold, np.where(changed, which, none))


def _condition_keys(rows: pd.DataFrame, pair: np.ndarray) -> np.ndarray:
    """One 64-bit key per (real pair, what the model sees): two rows of the same pair with the same inputs are one
    condition, however they were drawn (a missed report equal to the current one, noise clipped at 0, ...)."""

    seen = pd.util.hash_pandas_object(rows[FORECAST_FEATURES].reset_index(drop=True), index=False).to_numpy()
    return seen ^ (pair.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15))


def training_conditions(train: pd.DataFrame, n: int, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """`n` distinct training conditions: a condition is one real (now, target) pair from the training rows under
    one input state (history known or withheld; the report as made, noisy, missed, garbled; train class or route
    facts unknown). Every real pair is used once in a state drawn as in the recipe (when n is at least the number
    of pairs); beyond that, pairs are drawn again under damaged or history-withheld states, and a draw that gives
    the model the same inputs for the same pair as one already held is refused, so no condition is repeated.
    Returns the rows, their weights (the recipe's mix of the input states the rows really ended in, restored, times
    the situation-type balance) and a breakdown. Draws use their own generator from `seed`, so the same call always
    gives the same conditions."""

    from india_rail.scenario_bank import WEIGHT_DIMS, balance_weights, cells

    rng = np.random.default_rng([seed, 1])
    pairs = len(train)
    if n < 1 or n > pairs * N_STATES:
        raise ValueError(f"{n:,} conditions asked: {pairs:,} real pairs give at most {pairs * N_STATES:,}")
    first = np.arange(pairs) if n >= pairs else np.sort(rng.choice(pairs, n, replace=False))
    cold, which = input_states(len(first), rng)
    parts = [apply_input_states(train.iloc[first], cold, which, rng)]
    pair_of, effective = [first], [_effective(train.iloc[first], parts[0], cold, which)]
    seen = np.sort(_condition_keys(parts[0], first))
    held = len(np.unique(seen))
    # Extra views: the recipe's damaged and history-withheld states in their relative shares (the view as reported
    # with history known is the one most pairs already have)
    others = recipe_state_shares().copy()
    others[_state_code(np.array([False]), np.array([len(STRESS_TRAINING)]))[0]] = 0.0
    others /= others.sum()
    rounds = 0
    while held < n:
        rounds += 1
        if rounds > 50:
            raise ValueError(f"only {held:,} distinct conditions could be drawn from {pairs:,} real pairs")
        need = n - held
        idx = rng.integers(0, pairs, int(need * 1.3) + 64)
        code = rng.choice(N_STATES, size=len(idx), p=others)
        c, w = code >= len(STRESS_TRAINING) + 1, code % (len(STRESS_TRAINING) + 1)
        rows = train.iloc[idx]
        out = apply_input_states(rows, c, w, rng)
        keys = _condition_keys(out, idx)
        _, firsts = np.unique(keys, return_index=True)  # one of each in this draw
        keep = np.zeros(len(idx), dtype=bool)
        keep[firsts] = True
        keep &= ~np.isin(keys, seen)  # and none already held
        keep[np.flatnonzero(keep)[need:]] = False
        seen = np.sort(np.concatenate([seen, keys[keep]]))
        held += int(keep.sum())
        parts.append(out.iloc[keep])
        pair_of.append(idx[keep])
        effective.append(_effective(rows, out, c, w)[keep])
    fit = pd.concat(parts, ignore_index=True)
    pair, eff = np.concatenate(pair_of), np.concatenate(effective)
    # Weights: the mix of input states the rows really ended in, as the recipe gives it on these pairs (its draw
    # over the first pass), restored; times the balance of situation types of the real pairs (before any damage,
    # so a damaged row is not a type of its own)
    target = np.bincount(effective[0], minlength=N_STATES) / len(effective[0])
    observed = np.bincount(eff, minlength=N_STATES) / len(eff)
    mix = np.divide(target, observed, out=np.zeros(N_STATES), where=observed > 0)[eff]
    real = train.iloc[pair].reset_index(drop=True)
    situation = cells(real, float(np.nanquantile(train.net_delay_2h, 0.75)), WEIGHT_DIMS)
    weights = mix * balance_weights(situation)
    weights /= weights.mean()
    damage_of = eff % (len(STRESS_TRAINING) + 1)
    fit.attrs["input_state"], fit.attrs["state_weight"] = eff, mix  # for checks; not model inputs
    info = {
        "conditions": int(len(fit)),
        "distinct": bool(len(np.unique(_condition_keys(fit, pair))) == len(fit)),  # checked on the rows themselves
        "real_pairs_available": int(pairs),
        "real_pairs_used": int(len(np.unique(pair))),
        "runs": int(real.run.nunique()),
        "days": sorted(real.date.unique().tolist()),
        "situation_types": int(situation.nunique()),
        "by_input_state": {
            "history_withheld": int((eff >= len(STRESS_TRAINING) + 1).sum()),
            "history_known": int((eff < len(STRESS_TRAINING) + 1).sum()),
            "nothing_damaged": int((damage_of == len(STRESS_TRAINING)).sum()),
            **{name: int((damage_of == i).sum()) for i, name in enumerate(STRESS_TRAINING)},
        },
        "rows_without_weight": int((weights == 0).sum()),
        "draw_rounds_after_first": rounds,
        "weights": "the recipe's mix of the input states rows really ended in, restored, x square-root balance of "
                   "situation types (mean 1)",
    }  # fmt: skip
    return fit, weights, info


def _with_network_state(d: dict[str, pd.DataFrame], rows: pd.DataFrame) -> pd.DataFrame:
    """The state of the network when each forecast is made (scenario_ml.network_state), joined to the rows."""

    from india_rail.scenario_ml import NETWORK_FEATURES, network_state

    con = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    zone_of = dict(con.execute("SELECT code, zone FROM stations"))
    con.close()
    keyed = network_state(d["obs"], zone_of).set_index(["run", "seq"])
    joined = keyed.reindex(pd.MultiIndex.from_arrays([rows.run, rows.now_seq]))
    for col in ("zone", *NETWORK_FEATURES):
        rows[col] = joined[col].to_numpy()
    return rows


def forecast_recipe() -> str:
    """How the deployed forecaster is trained, as decided by the scenario bank on its selection rounds (days
    before the test days used here): "scenario" = on the six damaged inputs, every situation type weighted in;
    "plain" = random rows, 15% without history (also when no decision has been recorded)."""

    from india_rail.scenario_bank import EVIDENCE as BANK

    if not BANK.exists():
        return "plain"
    try:
        decision = json.loads(BANK.read_text())["forecasts"]["recipe_selection"]["decision"]
    except (OSError, ValueError, KeyError, TypeError) as exc:  # a decision that cannot be read is never guessed
        raise RuntimeError(f"the recorded recipe decision in {BANK} cannot be read: {exc}") from exc
    return decision if decision in ("scenario", "plain") else "plain"


CONDITIONS_EVIDENCE = PACKAGE_ROOT / "seva2026" / "evidence" / "real_data" / "forecaster_conditions.json"
SAMPLE_PAIRS = 1_500_000  # real pairs sampled for the recipes the scenario bank compared


def forecast_conditions() -> int | None:
    """Training conditions of the deployed forecaster, when a conditions run (forecast_conditions.py) decided
    to deploy them; None: the recipe's sample of SAMPLE_PAIRS real pairs."""

    if not CONDITIONS_EVIDENCE.exists():
        return None
    try:
        recorded = json.loads(CONDITIONS_EVIDENCE.read_text())
        return int(recorded["conditions"]) if recorded["decision"] == "deploy" else None
    except (OSError, ValueError, KeyError, TypeError) as exc:  # a decision that cannot be read is never guessed
        raise RuntimeError(f"the recorded conditions decision in {CONDITIONS_EVIDENCE} cannot be read: {exc}") from exc


def eta_model(loss: str, seed: int, quantile: float | None = None):
    """The forecaster's gradient-boosted trees (median: absolute error; band: P10 and P90 quantiles). A fixed number
    of rounds, no early stopping: its hold-out would be random rows, and with several conditions of one real pair
    a copy of a held-out row could sit in training."""

    from sklearn.ensemble import HistGradientBoostingRegressor

    kw = {"quantile": quantile} if quantile is not None else {}
    return HistGradientBoostingRegressor(
        loss=loss, max_iter=400, learning_rate=0.08, max_leaf_nodes=63, min_samples_leaf=200,
        l2_regularization=1.0, early_stopping=False, random_state=seed, **kw
    )  # fmt: skip


def fit_rows(
    train: pd.DataFrame, recipe: str, conditions: int | None, seed: int
) -> tuple[pd.DataFrame, np.ndarray | None, dict[str, Any]]:
    """The rows (and weights) the forecaster is fitted on: `conditions` distinct training conditions, or the
    recipe's sample of SAMPLE_PAIRS real pairs. Each draws from its own generator, so the rows depend only on
    (`train`, `conditions`, `seed`): the model a conditions run tests is the one `real validate` trains."""

    if conditions is not None:
        if recipe != "scenario":
            raise ValueError("training conditions are input states of the scenario recipe")
        return training_conditions(train, conditions, seed)
    rng = np.random.default_rng(seed)
    fit = train.iloc[rng.choice(len(train), size=min(len(train), SAMPLE_PAIRS), replace=False)].copy()
    if recipe == "scenario":
        from india_rail.scenario_bank import WEIGHT_DIMS, balance_weights, cells

        # Situation types of the real rows (before any damage), so damaged rows are not a type of their own
        weights = balance_weights(cells(fit, float(np.nanquantile(train.net_delay_2h, 0.75)), WEIGHT_DIMS))
        return stress_training(fit, rng), weights, {"real_pairs_sampled": len(fit)}
    return cold_start(fit, rng), None, {"real_pairs_sampled": len(fit)}  # cold start measured below


def forecast(
    d: dict[str, pd.DataFrame],
    seed: int = 0,
    save_model: bool = True,
    recipe: str | None = None,
    conditions: int | None | str = "recorded",
) -> tuple[dict[str, Any], dict]:
    """Score delay forecasts on the test dates; returns (scores, fitted models). `conditions`: a number of distinct
    training conditions, None for the recipe's sample, "recorded" (default) for what the last conditions run
    decided to deploy (the sample if it decided against, or for the plain recipe)."""

    recipe = recipe or forecast_recipe()
    if conditions == "recorded":
        conditions = forecast_conditions() if recipe == "scenario" else None

    rows = forecast_rows(d)
    if recipe == "scenario":
        rows = _with_network_state(d, rows)
    # Training rows: runs started by the split whose answer was also observed by then (a run started on the split
    # day can report the next day); test rows: runs started after it.
    train, test = rows[(rows.date <= SPLIT_DATE) & (rows.tgt_day <= SPLIT_DATE)], rows[rows.date > SPLIT_DATE]
    fit, weights, fitted_on = fit_rows(train, recipe, conditions, seed)

    def model(loss: str, quantile: float | None = None):
        return eta_model(loss, seed, quantile)

    y = fit.d_tgt - fit.d_now
    median = model("absolute_error").fit(fit[FORECAST_FEATURES], y, sample_weight=weights)
    lo = model("quantile", 0.1).fit(fit[FORECAST_FEATURES], y, sample_weight=weights)
    hi = model("quantile", 0.9).fit(fit[FORECAST_FEATURES], y, sample_weight=weights)
    preds = {
        "twin_current_rule": np.where(test.d_now >= 5, np.maximum(test.d_now - 2 - test.dwell_recovery, 0), 0.0),
        "persistence": test.d_now.to_numpy(dtype=float),
        "history": np.maximum(test.d_now + test.hist_change.fillna(0), 0).to_numpy(),
        "learned_from_real_running": np.maximum(test.d_now + median.predict(test[FORECAST_FEATURES]), 0),
    }
    truth = test.d_tgt.to_numpy(dtype=float)
    buckets = pd.cut(test.sch_gap, [-1, 60, 180, 360, 100000], labels=["<=1h", "1-3h", "3-6h", ">6h"])
    scores = {}
    for name, pred in preds.items():
        err = np.abs(pred - truth)
        scores[name] = {
            "mae_min": round(float(err.mean()), 2),
            "within_15_min_pct": round(float((err <= ON_TIME_MIN).mean() * 100), 2),
            "bias_min": round(float((pred - truth).mean()), 2),
            "mae_by_horizon_min": {
                str(b): round(float(err[(buckets == b).to_numpy()].mean()), 2) for b in buckets.cat.categories
            },  # fmt: skip
        }
    cold = test[FORECAST_FEATURES].copy()
    cold[["hist_q", "hist_change"]] = np.nan
    cold["hist_n_q"] = 0
    cold_err = np.abs(np.maximum(test.d_now + median.predict(cold), 0) - truth)
    scores["learned_from_real_running"]["cold_start_mae_min"] = round(float(cold_err.mean()), 2)
    p_lo = np.maximum(test.d_now + lo.predict(test[FORECAST_FEATURES]), 0)
    p_hi = np.maximum(test.d_now + hi.predict(test[FORECAST_FEATURES]), 0)
    inside = (truth >= p_lo) & (truth <= p_hi)
    coverage = float(inside.mean() * 100)
    coverage_detail = _coverage_detail(test, truth, inside, lo, hi, train, seed) if recipe == "scenario" else None
    learned_err = np.abs(preds["learned_from_real_running"] - truth)
    ci = {}
    for base in ("persistence", "twin_current_rule"):
        ci[base] = _bootstrap_gain(test.run.to_numpy(), np.abs(preds[base] - truth), learned_err, seed)
    result = {
        "recipe": recipe,
        "trained_on": {k: v for k, v in fitted_on.items() if k != "days"},
        "split": {
            "train_dates": f"2024-09-01..{SPLIT_DATE}",
            "test_dates": f"after {SPLIT_DATE}",
            "train_rows_used": len(fit),
            "test_pairs": len(test),
            "test_runs": int(test.run.nunique()),
        },
        "targets": "1, 3 and 6 reporting stops ahead and the last reporting stop of the run",
        "scores": scores,
        "interval_p10_p90_coverage_pct": round(coverage, 1),
        "interval_mean_width_min": round(float((p_hi - p_lo).mean()), 1),
        **({"interval_coverage_detail": coverage_detail} if coverage_detail else {}),
        "mae_reduction_vs": ci,
    }
    if save_model:
        save_eta_model({"median": median, "p10": lo, "p90": hi}, recipe, len(fit) if conditions else None)
    return result, {"median": median, "p10": lo, "p90": hi}


def save_eta_model(models: dict, recipe: str, conditions: int | None) -> None:
    import joblib

    ETA_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ETA_MODEL_PATH.with_suffix(".tmp")
    joblib.dump({**models, "features": FORECAST_FEATURES, "recipe": recipe, "conditions": conditions,
                 "trained_on": f"observed running 2024-09-01..{SPLIT_DATE}"
                 + (f", {conditions:,} training conditions" if conditions else ""),
                 "source": OBSERVED["publisher"]}, tmp, compress=3)  # fmt: skip
    tmp.replace(ETA_MODEL_PATH)  # a reader never sees half a model


def _coverage_detail(test, truth, inside, lo, hi, train, seed: int) -> dict[str, Any]:
    """How often the P10-P90 band holds the real outcome, by situation and under the six damaged inputs (one
    overall figure can hide a situation where the band is too narrow)."""

    from india_rail.scenario_bank import STRESS, damage
    from india_rail.scenario_ml import strata

    by: dict[str, dict[str, Any]] = {}
    for dim, labels in strata(test, float(np.nanquantile(train.net_delay_2h, 0.75))).items():
        if dim not in ("time_of_day", "current_delay", "train_class", "line", "horizon", "network"):
            continue
        labels = pd.Series(labels).astype(str).to_numpy()
        by[dim] = {str(lab): {"n": int((labels == lab).sum()), "coverage_pct": round(float(inside[labels == lab].mean()
                   * 100), 1)} for lab in pd.unique(labels) if (labels == lab).sum() >= 500}  # fmt: skip
    rng = np.random.default_rng(seed)
    codes = pd.factorize(test.run)[0]
    damaged = {}
    for name in STRESS:
        f = damage(test, name, codes, rng)
        d_lo = np.maximum(f.d_now + lo.predict(f[FORECAST_FEATURES]), 0)
        d_hi = np.maximum(f.d_now + hi.predict(f[FORECAST_FEATURES]), 0)
        damaged[name] = round(float(((truth >= d_lo) & (truth <= d_hi)).mean() * 100), 1)
    shares = [v["coverage_pct"] for dim in by.values() for v in dim.values()]
    return {"range_over_situations_pct": [min(shares), max(shares)] if shares else None, "by_situation": by,
            "under_damaged_inputs_pct": damaged}  # fmt: skip


def _bootstrap_gain(runs: np.ndarray, base_err: np.ndarray, new_err: np.ndarray, seed: int, n: int = 200) -> dict:
    """MAE reduction (minutes) of the learned forecast over a baseline, with a run-grouped 95% interval."""

    codes, run_index = np.unique(runs, return_inverse=True)
    diff = np.bincount(run_index, base_err - new_err)
    count = np.bincount(run_index)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        pick = rng.integers(0, len(codes), len(codes))
        draws.append(diff[pick].sum() / count[pick].sum())
    return {
        "mae_reduction_min": round(float(diff.sum() / count.sum()), 2),
        "ci95_min": [round(float(np.percentile(draws, 2.5)), 2), round(float(np.percentile(draws, 97.5)), 2)],
    }


# ---- 5. conflicts flagged by the twin vs real time loss -----------------------------------------------
def _learned_plan(twin, key, p, d_now, train, run_date, model, lookups, until):
    """The run's plan with the learned forecast of its delay at every later stop up to `until` (then held)."""

    from india_rail.railguard.eta import forecast_plan

    plan = twin.plan_of(key)
    n = len(plan.sections)
    targets = [q for q in range(p + 1, n + 1) if plan.s_exit[q - 1] <= until]
    delay_at = {p: d_now}
    if targets:
        rows = pd.DataFrame(lookups.rows(train, run_date, p, d_now, targets))
        pred = np.maximum(d_now + model.predict(rows[FORECAST_FEATURES]), 0.0)
        delay_at.update(zip(targets, pred.tolist(), strict=True))
    return forecast_plan(plan, p, delay_at)


def conflict_replay(
    d: dict[str, pd.DataFrame],
    dates: list[str],
    snapshots: tuple[int, ...] = (360, 540, 720, 900, 1080, 1260),
    horizon: float = 120.0,
    use_osm: bool = True,
    projection: str = "twin_rule",
    shared_track: bool = True,
    model: Any = None,
    lookups: Lookups | None = None,
) -> dict[str, Any]:
    """Retrospective shadow run: at fixed times of real days the twin gets every train's real delay, flags
    conflicts in the next `horizon` minutes, and each flagged traversal is checked against what happened.

    The train that must give way (lower priority; the later one at equal priority) is the one a correct
    flag predicts will lose time. It is compared with unflagged traversals of trains in the same state
    (already late or not), because late trains tend to recover time on their own."""

    from india_rail.railguard.national import NationalTwin, build_national

    obs = d["obs"][d["obs"].delay <= EXTREME_DELAY_MIN]
    delays = {
        (t, dt): (g.seq.to_numpy(), g.delay.to_numpy(), g.act.to_numpy())
        for (t, dt), g in obs.groupby(["train", "date"])
    }
    rows, timings = [], []
    for day in dates:
        service = date.fromisoformat(day)
        data = build_national(REAL_DB_PATH, service_date=service, use_osm=use_osm, shared_track=shared_track)
        twin = NationalTwin(data)
        observed_runs = {}
        for key, run in data.runs.items():
            offset = int(key.split("@")[1])
            run_date = (service + timedelta(days=offset)).isoformat()
            got = delays.get((run.number, run_date))
            if got is not None:
                observed_runs[key] = (offset, run_date, *got)
        for snap in snapshots:
            started = time.perf_counter()
            twin.start_min = snap
            twin.reset()
            changed = {}
            for key, (offset, run_date, seq, delay, act) in observed_runs.items():
                t_act = act + offset * 1440
                seen = np.nonzero(t_act <= snap)[0]
                if not len(seen) or snap - t_act[seen[-1]] > 180:
                    continue  # not yet reported, or no fresh report: stays on its timetable projection
                p, d_now = int(seq[seen[-1]]), float(delay[seen[-1]])
                plan = twin.plan_of(key)
                if p >= len(plan.sections):
                    continue
                if d_now < 1:
                    continue  # both projections re-plan the same trains: those reported late
                if projection == "learned":
                    new = _learned_plan(twin, key, p, d_now, data.runs[key].number, run_date, model, lookups,
                                        snap + horizon + 240)  # fmt: skip
                else:
                    new = twin.propagate(plan, {p: d_now})
                twin._set_plan(key, new)
                changed[key] = p
            # Which trains count as late, and which traversals are scored, do not depend on the projection: a
            # train is late if its latest fresh report says so; a traversal is scored if it really began in the
            # window. So the rule and the learned projection are compared on the same traversals.
            late = {k for k, (_o, _rd, seq, delay, act) in observed_runs.items() if _fresh_delay(seq, delay, act
                    + observed_runs[k][0] * 1440, snap) >= 1}  # fmt: skip
            role: dict[tuple[str, int], str] = {}
            for key, p in changed.items():
                plan = twin.plans[key]
                for c in twin.conflicts(key, plan, p):
                    i, other, j = c["index"], c["other"], c["other_index"]
                    if not c["is_conflict"] or not snap <= plan.enter[i] <= snap + horizon:
                        continue
                    a, b = data.runs[key].priority, data.runs[other].priority
                    later = plan.enter[i] >= twin.plan_of(other).enter[j]
                    gives_way = (key, i) if (a > b or (a == b and later)) else (other, j)
                    keeps = (other, j) if gives_way == (key, i) else (key, i)
                    role[gives_way] = "gives_way"
                    if role.get(keeps) != "gives_way":
                        role[keeps] = "keeps_way"
            timings.append(time.perf_counter() - started)
            for key, (offset, _rd, seq, delay, act) in observed_runs.items():
                plan = twin.plan_of(key)
                pos = {int(s): float(v) for s, v in zip(seq, delay, strict=True)}
                began = {int(s): float(a) + offset * 1440 for s, a in zip(seq, act, strict=True)}
                for i in range(len(plan.sections)):
                    if i in pos and i + 1 in pos and snap <= began[i] <= snap + horizon:
                        rows.append((key in late, role.get((key, i), "none"), pos[i + 1] - pos[i],
                                     twin.section(plan.sections[i]).tracks == 1))  # fmt: skip
    frame = pd.DataFrame(rows, columns=["late", "role", "loss", "single"])
    return {
        "use_real_track_data": use_osm,
        "shared_track_checked": shared_track,
        "projection": projection,
        "dates": dates,
        "snapshots_min": list(snapshots),
        "horizon_min": horizon,
        "traversals_scored": len(frame),
        **_flag_scores(frame),
        "single_line": _flag_scores(frame[frame.single]),
        "double_line": _flag_scores(frame[~frame.single]),
        "seconds_per_national_snapshot": _spread(timings, 2),
    }


def _fresh_delay(seq, delay, t_act, snap: float) -> float:
    """The delay in a run's latest report at or before `snap`, if no older than 180 minutes (else 0)."""

    seen = np.nonzero(t_act <= snap)[0]
    if not len(seen) or snap - t_act[seen[-1]] > 180:
        return 0.0
    return float(delay[seen[-1]])


def _spread(values: list[float], digits: int) -> dict[str, float]:
    return {"median": round(float(np.median(values)), digits), "max": round(float(max(values)), digits)}


def _flag_scores(frame: pd.DataFrame) -> dict[str, Any]:
    flagged, none = frame[frame.role == "gives_way"], frame[frame.role == "none"]
    if not len(flagged) or not len(none):
        return {"flagged_gives_way": len(flagged)}
    hit = float((flagged.loss >= LOSS_MIN).mean())
    # baseline: unflagged traversals, weighted to the same mix of late / not-late trains as the flagged ones
    base = sum(
        share * float((none[none.late == state].loss >= LOSS_MIN).mean())
        for state, share in flagged.late.value_counts(normalize=True).items()
        if len(none[none.late == state])
    )
    big = frame[frame.loss >= 15]
    return {
        "flagged_gives_way": len(flagged),
        "gives_way_lost_5_min_pct": round(hit * 100, 2),
        "comparable_unflagged_lost_5_min_pct": round(base * 100, 2),
        "lift": round(hit / base, 2) if base else None,
        "keeps_way_lost_5_min_pct": round(float((frame[frame.role == "keeps_way"].loss >= LOSS_MIN).mean() * 100), 2)
        if (frame.role == "keeps_way").any()
        else None,
        "losses_15_min_or_more_flagged_pct": (
            round(float((big.role == "gives_way").mean() * 100), 2) if len(big) else None
        ),
    }


# ---- 6. live-feed replay of a real morning ------------------------------------------------------------
def feed_replay(
    d: dict[str, pd.DataFrame], day: str = "2024-09-24", start: int = 360, end: int = 600, eta: Any = None
) -> dict[str, Any]:
    import secrets

    from india_rail.railguard.livefeed import IST, FeedGateway, FeedSimulator
    from india_rail.railguard.national import NationalTwin, build_national

    service = date.fromisoformat(day)
    data = build_national(REAL_DB_PATH, service_date=service)
    twin = NationalTwin(data, start_min=start - 1)
    twin.eta = eta
    secret = secrets.token_bytes(32)
    clock = {"t": 0.0}
    midnight = datetime.combine(service, datetime.min.time(), IST)
    gateway = FeedGateway(twin, keys={("NTES", "k1"): secret}, service_date=service, clock=lambda: clock["t"],
                          follow_clock=True)  # fmt: skip
    sender = FeedSimulator(gateway, "NTES", "k1", secret)
    obs = d["obs"][d["obs"].delay <= EXTREME_DELAY_MIN]
    events = []
    for offset in (0, -1, -2):
        run_date = (service + timedelta(days=offset)).isoformat()
        part = obs[obs.date == run_date]
        minute = part.act + offset * 1440
        part = part[(minute >= start) & (minute < end)]
        for train, station, seq, m in zip(part.train, part.station, part.seq, minute[part.index], strict=True):
            events.append((float(m), train, run_date, int(seq), station, "DEP" if seq == 0 else "ARR"))  # route order
    events.sort()
    accepted = rejected = 0
    reasons: dict[str, int] = {}
    errors, latencies = [], []
    batch: list[dict] = []
    current = None

    def flush(minute: float) -> None:
        nonlocal accepted, rejected
        if not batch:
            return
        clock["t"] = (midnight + timedelta(minutes=minute)).timestamp()
        for chunk in range(0, len(batch), 250):
            started = time.perf_counter()
            result = gateway.receive(sender.envelope(batch[chunk : chunk + 250]))
            latencies.append(time.perf_counter() - started)
            accepted += result["accepted"]
            rejected += result["rejected"]
            for r in result["results"]:
                if not r["accepted"] and "reason" in r:
                    reason = r["reason"].split(" ")[0:4]
                    reasons[" ".join(reason)] = reasons.get(" ".join(reason), 0) + 1
        batch.clear()

    for m, train, run_date, _seq, station, what in events:
        minute = int(m)
        if current is not None and minute != current:
            flush(current + 0.5)
        current = minute
        key = f"{train}@{(date.fromisoformat(run_date) - service).days}"
        if key in twin.runs and what == "ARR":  # error of the twin's projection just before the real arrival
            plan = twin.plan_of(key)
            ahead = range(len(plan.sections))
            nxt = next((i for i in ahead if plan.to[i] == station and plan.exit[i] >= m - 600), None)
            if nxt is not None:
                errors.append(m - plan.exit[nxt])
        batch.append({"type": "STATION", "train_number": train, "start_date": run_date, "station_code": station,
                      "event": what, "observed_at": (midnight + timedelta(minutes=m)).isoformat()})  # fmt: skip
    if current is not None:
        flush(current + 0.5)
    err = np.abs(np.array(errors))
    pending = list(twin.pending)[:20]
    rank_times, feasible = [], 0
    for key in pending:
        started = time.perf_counter()
        ranking = twin.recommend(key)
        rank_times.append(time.perf_counter() - started)
        feasible += bool(ranking.get("ranking", {}).get("candidates"))
    return {
        "projection": "learned forecast" if eta is not None else "twin rule (delay carried forward)",
        "day": day,
        "window": f"{start // 60:02d}:00-{end // 60:02d}:00 IST",
        "events_sent": len(events),
        "accepted": accepted,
        "rejected": rejected,
        "rejection_reasons": reasons,
        "batch_latency_ms": {
            "p50": round(float(np.percentile(latencies, 50)) * 1000, 1),
            "p95": round(float(np.percentile(latencies, 95)) * 1000, 1),
        },  # fmt: skip
        "disruptions_recorded_automatically": len(twin.pending),
        "projection_error_at_arrival_min": {
            "median": round(float(np.median(err)), 1),
            "within_15_min_pct": round(float((err <= 15).mean() * 100), 1),
        },
        "recommendation_seconds": _spread(rank_times, 2) if rank_times else None,
        "recommendations_with_options": feasible,
        "alerts": {
            "raised": twin.threats.raised,
            "came_back_as_the_same_alert": twin.threats.came_back,
            "evaluations_a_missing_threat_was_kept": twin.threats.held,
            "active_at_end": len(twin.threats.active()),
        },
    }


def alert_hygiene(d: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Alerts a controller would get on a real morning's feed with the hygiene rules (threats.CLEAR_AFTER_S,
    REOPEN_S) and without them (every disappearance a clear, every return a new alert to acknowledge)."""

    from india_rail.railguard import threats

    with_rules = feed_replay(d)["alerts"]
    saved = threats.CLEAR_AFTER_S, threats.REOPEN_S
    threats.CLEAR_AFTER_S, threats.REOPEN_S = 0, -1
    try:
        without = feed_replay(d)["alerts"]
    finally:
        threats.CLEAR_AFTER_S, threats.REOPEN_S = saved
    return {
        "with_rules": with_rules,
        "without_rules": without,
        "alerts_avoided": without["raised"] - with_rules["raised"],
        "rules": f"non-critical threats clear after {saved[0]} s gone; one back within {saved[1]} s keeps its id and "
                 "acknowledgement unless more severe; critical threats clear at once and come back open",
    }  # fmt: skip


def build_metadata(db: Path = REAL_DB_PATH) -> dict[str, Any]:
    """The real-data build report and the OpenStreetMap coverage summary recorded in the database."""

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM metadata WHERE key IN "
                                                      "('real_build_report', 'osm_summary')")}  # fmt: skip
    con.close()
    return {"data_build": meta.get("real_build_report", {}), "track_data": meta.get("osm_summary", {})}


def validate_all(out: Path | None = None, conflict_dates: int = 4) -> dict[str, Any]:
    from india_rail.railguard.eta import EtaForecaster

    started = time.time()
    d = load()
    lookups = Lookups(d)
    test_dates = sorted(x for x in d["obs"].date.unique() if x > SPLIT_DATE)
    picked = test_dates[1 :: max(len(test_dates) // conflict_dates, 1)][:conflict_dates]
    scores, models = forecast(d)
    learned = {"projection": "learned", "model": models["median"], "lookups": lookups}
    eta = EtaForecaster(db=REAL_DB_PATH, history_until=SPLIT_DATE)  # just trained; history to the split only
    result = {
        "source": OBSERVED,
        **build_metadata(),
        "credibility": credibility(d),
        "timetable_drift": timetable_drift(),
        "section_running": section_running(d),
        "forecast": scores,
        "conflicts": {
            "twin_rule_without_real_track_data": conflict_replay(d, picked, use_osm=False),
            "twin_rule_with_real_track_data": conflict_replay(d, picked, use_osm=True),
            "learned_projection_with_real_track_data": conflict_replay(d, picked, use_osm=True, **learned),
            # the same, with each train compared only with trains on its own stop-to-stop sections: what checking
            # shared track changes, measured the same way on the same days
            "learned_projection_without_shared_track": conflict_replay(
                d, picked, use_osm=True, shared_track=False, **learned
            ),  # fmt: skip
        },
        "live_feed_replay": {"twin_rule": feed_replay(d), "learned_projection": feed_replay(d, eta=eta)},
        "alert_hygiene": alert_hygiene(d),
        "seconds": round(time.time() - started, 1),
    }
    out = out or EVIDENCE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    SUMMARY.write_text(summary_markdown(json.loads(out.read_text(encoding="utf-8"))), encoding="utf-8")
    return result


SUMMARY = PACKAGE_ROOT / "seva2026" / "railway_readiness" / "REAL_DATA_VALIDATION.md"


def summary_markdown(r: dict[str, Any]) -> str:
    """The human-readable verification report, generated from the evidence file (no number is typed by hand)."""

    cred, drift, fc, track, build = (
        r["credibility"],
        r["timetable_drift"],
        r["forecast"],
        r["track_data"],
        r["data_build"],
    )
    lines = track.get("accepted_lines", {})
    double = sum(v for k, v in lines.items() if k not in ("1", "None"))
    out = [
        "# Verification on real-life data",
        "",
        "Generated by `python -m india_rail real validate` from `seva2026/evidence/real_data/real_validation.json`.",
        "Every number below is computed from what actually happened, not from data this project generated.",
        "",
        "## Data",
        f"* **Actual running:** {cred['runs_observed']:,} train runs, {cred['arrivals_observed']:,} actual arrival "
        f"times, {cred['trains']:,} trains, {cred['dates'][0]} to {cred['dates'][1]}. Source: "
        f"{r['source']['publisher']}. {r['source']['licence']}",
        f"* **Timetable:** September 2024, {build.get('trains', 0):,} trains, {build.get('sections', 0):,} timed "
        f"sections; {build.get('trains_with_placeholder_timetable_excluded', 0)} trains with placeholder times "
        "excluded.",
        f"* **Running days:** observed for all {build.get('trains_with_running_days', 0):,} trains "
        f"({build.get('trains_daily', 0):,} daily).",
        f"* **Track data (OpenStreetMap, ODbL):** {track.get('stations_located_by_osm_ref', 0):,} stations located by "
        f"their IR code; {track.get('sections_accepted', 0):,} of {track.get('sections', 0):,} sections mapped: "
        f"{lines.get('1', 0):,} single line, {double:,} double or more; "
        f"{track.get('accepted_electrified_over_90pct', 0):,} at least 90% electrified.",
        "",
        "## 1. Is the data credible?",
        f"Mail/Express trains at destination within 15 minutes: **{cred['destination_on_time_pct_mail_express']}%** "
        f"observed in September 2024; the Ministry of Railways published **{cred['official_figure']['value_pct']}%** "
        f"for {cred['official_figure']['period']}, which includes the winter fog months. A credible sample of real "
        "running.",
        "",
        "## 2. How old was the open timetable?",
        f"Of {drift.get('same_number_same_origin_and_destination', 0):,} trains with the same number, origin and "
        f"destination in 2016 and 2024, {drift.get('journey_time_changed_over_15_min_pct', 0)}% changed journey time "
        f"by more than 15 minutes; {drift.get('sections_2024_missing_from_2016', 0):,} sections of 2024 are not in "
        "the 2016 data. The twin now runs on the 2024 timetable.",
        "",
        "## 3. Forecasting late trains (learned on 1-20 Sep, scored on 21-30 Sep)",
        "",
        "| Method | Average error (min) | Within 15 min | <=1 h | 1-3 h | 3-6 h | >6 h |",
        "|---|---|---|---|---|---|---|",
    ]
    names = {
        "twin_current_rule": "Previous twin rule",
        "persistence": "Delay stays the same",
        "history": "Train's own history",
        "learned_from_real_running": "**Learned from real running**",
    }
    for key, label in names.items():
        sc = fc["scores"][key]
        hz = sc["mae_by_horizon_min"]
        out.append(f"| {label} | {sc['mae_min']} | {sc['within_15_min_pct']}% | {hz['<=1h']} | {hz['1-3h']} | "
                   f"{hz['3-6h']} | {hz['>6h']} |")  # fmt: skip
    gain = fc["mae_reduction_vs"]["twin_current_rule"]
    out += [
        "",
        f"{fc['split']['test_pairs']:,} forecasts for {fc['split']['test_runs']:,} runs on unseen days. Improvement "
        f"over the previous rule: **{gain['mae_reduction_min']} min** (95% interval {gain['ci95_min'][0]} to "
        f"{gain['ci95_min'][1]}, bootstrap over runs). P10-P90 band coverage {fc['interval_p10_p90_coverage_pct']}% "
        "(target 80%). The deployed model (`models/eta_model.joblib`) is the one scored here; it is rebuilt locally by "
        "this command and, like the data it learned from, never distributed.",
        "",
        "## 4. Do conflict warnings come true?",
        "At six times of day on four unseen days the national twin was given every train's real delay and flagged "
        "conflicts in the next two hours. A correct warning predicts that the train which must give way loses time "
        "on that section; it is compared with unflagged trains in the same state (late or not).",
        "",
        "| Twin | Warnings | Give-way train lost >=5 min | Comparable trains | Lift |",
        "|---|---|---|---|---|",
    ]
    variants = (
        ("twin_rule_without_real_track_data", "Previous projection, no track data"),
        ("twin_rule_with_real_track_data", "Previous projection + real track data"),
        ("learned_projection_with_real_track_data", "Learned projection + real track data"),
    )
    for key, label in variants:
        c = r["conflicts"][key]
        out.append(f"| {label} | {c['flagged_gives_way']:,} | {c['gives_way_lost_5_min_pct']}% | "
                   f"{c['comparable_unflagged_lost_5_min_pct']}% | {c['lift']}x |")  # fmt: skip
    out += [
        "",
        "Warnings are informative but far from certain: sections between stopping stations cannot show block "
        "sections, intermediate loops or signals. Indian Railways' engineering registers and COA data are the next "
        "real gain (hazard H14).",
        "",
        "## 5. A real morning through the signed live-feed gateway",
        "",
        "| Projection | Reports | Accepted | Batch p50 / p95 | Projection within 15 min of the real arrival |",
        "|---|---|---|---|---|",
    ]
    for key, label in (("twin_rule", "Previous rule"), ("learned_projection", "Learned forecast")):
        f = r["live_feed_replay"][key]
        out.append(f"| {label} | {f['events_sent']:,} | {f['accepted'] / f['events_sent'] * 100:.1f}% | "
                   f"{f['batch_latency_ms']['p50']} / {f['batch_latency_ms']['p95']} ms | "
                   f"{f['projection_error_at_arrival_min']['within_15_min_pct']}% |")  # fmt: skip
    first = r["live_feed_replay"]["twin_rule"]
    out += [
        "",
        f"{first['window']} on {first['day']}. Refused reports are out of order or for unknown runs, refused on "
        "purpose. Disruptions recorded automatically for controllers: "
        f"{first['disruptions_recorded_automatically']:,}.",
        "",
        "## 6. Real time lost per section",
        f"Single line: {r['section_running']['osm_single_line']['lost_5_min_or_more_pct']}% of traversals lost 5+ "
        f"minutes; double line or more: {r['section_running']['osm_double_or_more']['lost_5_min_or_more_pct']}%. "
        "Busy double-line trunk routes lose time as often as single lines.",
        "",
        "## Limits",
        "One month (September, no fog season). Only arrivals are observed; departures in the file are arrival plus "
        "scheduled halt. Early running is recorded as zero. Freight and suburban trains are not included. "
        "OpenStreetMap is volunteer-mapped. A shadow trial on live data with controllers is still needed.",
        "",
    ]
    return "\n".join(out)
