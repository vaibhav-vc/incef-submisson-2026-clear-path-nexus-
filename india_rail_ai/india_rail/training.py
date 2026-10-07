"""Measured training rounds for the section run-time model.

    python -m india_rail.training            # run every round, log them, report the locked test once

Protocol (so repeated training cannot flatter the score):
1. 15% of train groups (a train and its return working) are locked away as a
   final test set before any round runs. No round ever sees them.
2. Each round changes one thing (features, post-processing, hyper-parameters,
   blending) and is scored with 3-fold GroupKFold on the remaining 85%. A change
   is kept only if mean absolute error improves by at least KEEP_MIN_GAIN.
3. Training stops when a full pass of candidate changes no longer improves.
4. The winning configuration is scored once on the locked test set, next to the
   section-median baseline. That number is the one to quote.

Targets are *scheduled* run times (whole minutes) from the public timetable, so
the honest floor is not zero error: timetables round to the minute and add
operator-chosen allowances that no public feature explains.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from india_rail import runtime_model as rm
from india_rail.ingest import DB_PATH, connect

LOG_PATH = rm.MODEL_DIR / "training_log.json"
HOLDOUT_FRACTION = 0.15
KEEP_MIN_GAIN = 0.005  # minutes of MAE
SEED = 20261007

CONTEXT, EDGE_EXTRA = rm.CONTEXT, rm.EDGE_EXTRA
encode_extra, add_context = rm.encode_extra, rm.add_context


# ---- configurable model --------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "learning_rate": 0.08,
    "max_iter": 400,
    "max_leaf_nodes": 63,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
}


def encode(train: pd.DataFrame, target: pd.DataFrame, config: dict[str, Any], *, training: bool, seed: int):
    if training:
        parts = []
        for a, b in GroupKFold(n_splits=4).split(train, groups=train["group"]):
            enc = rm.encode_priors(train.iloc[a], train.iloc[b])
            if config["edge_extra"]:
                enc = encode_extra(train.iloc[a], enc)
            parts.append(enc)
        encoded = rm.add_train_pace(pd.concat(parts).loc[train.index], mask_rate=rm.PACE_MASK_RATE, seed=seed)
    else:
        encoded = rm.encode_priors(train, target)
        if config["edge_extra"]:
            encoded = encode_extra(train, encoded)
        encoded = rm.add_train_pace(encoded)
    if config["context"]:
        encoded = add_context(encoded)
    return encoded


def features(config: dict[str, Any]) -> list[str]:
    return rm.BASE_FEATURES + (EDGE_EXTRA if config["edge_extra"] else []) + (CONTEXT if config["context"] else [])


def base(encoded: pd.DataFrame, config: dict[str, Any]) -> np.ndarray:
    if config["edge_extra"] and config.get("type_base"):
        typed = encoded["edge_type_prior_min"].where(encoded["edge_prior_n"] >= rm.MIN_EDGE_SUPPORT)
        return typed.fillna(pd.Series(rm.base_estimate(encoded), index=encoded.index)).to_numpy(dtype=float)
    return rm.base_estimate(encoded)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, config: dict[str, Any], seed: int) -> np.ndarray:
    tr = encode(train, train, config, training=True, seed=seed)
    te = encode(train, test, config, training=False, seed=seed)
    params = {**DEFAULT_PARAMS, **config.get("params", {})}
    model = HistGradientBoostingRegressor(
        loss="absolute_error", categorical_features="from_dtype", random_state=SEED, **params
    )
    cols = features(config)
    model.fit(tr[cols], train["runtime_min"].to_numpy(dtype=float) - base(tr, config))
    pred = base(te, config) + model.predict(te[cols])
    if config.get("blend"):  # shrink toward the section median where many other trains agree
        support = te["edge_prior_n"].fillna(0).to_numpy()
        w = support / (support + config["blend"])
        prior = te["edge_prior_min"].to_numpy()
        pred = np.where(np.isnan(prior), pred, (1 - w) * pred + w * prior)
    if config.get("round"):
        pred = np.round(pred)
    return np.clip(pred, 0, None)


def scores(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return rm._scores(y, pred)


def cv(data: pd.DataFrame, config: dict[str, Any], folds: int = 3) -> tuple[dict[str, float], float]:
    y = data["runtime_min"].to_numpy(dtype=float)
    oof = np.zeros(len(data))
    began = time.perf_counter()
    for fold, (a, b) in enumerate(GroupKFold(n_splits=folds).split(data, groups=data["group"])):
        oof[b] = fit_predict(data.iloc[a], data.iloc[b], config, seed=fold)
    return scores(y, oof), time.perf_counter() - began


# ---- the rounds -------------------------------------------------------------------------------------
CANDIDATES: list[tuple[str, dict[str, Any]]] = [
    ("round predictions to whole minutes (timetables are minute-resolution)", {"round": True}),
    ("type- and direction-specific section priors, run-time spread on the section", {"edge_extra": True}),
    ("local pace from the two sections either side (existing trains)", {"context": True}),
    ("start from the type-specific section prior", {"type_base": True}),
    ("more trees, slower learning", {"params": {"learning_rate": 0.05, "max_iter": 700}}),
    ("larger trees", {"params": {"max_leaf_nodes": 127, "min_samples_leaf": 30}}),
    ("smaller leaves, more regularisation", {"params": {"min_samples_leaf": 20, "l2_regularization": 3.0}}),
    ("blend toward well-supported section medians (k=20)", {"blend": 20}),
    ("blend toward well-supported section medians (k=60)", {"blend": 60}),
]


def _merge(config: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    merged = {**config, **{k: v for k, v in change.items() if k != "params"}}
    merged["params"] = {**config.get("params", {}), **change.get("params", {})}
    return merged


def run(max_passes: int = 3, log_path: Path = LOG_PATH) -> dict[str, Any]:
    con = connect(DB_PATH)
    df = rm.load_sections(con)
    data = df[rm.plausibility_mask(df)].reset_index(drop=True)
    dev_idx, hold_idx = next(
        GroupShuffleSplit(n_splits=1, test_size=HOLDOUT_FRACTION, random_state=SEED).split(data, groups=data["group"])
    )
    dev, hold = data.iloc[dev_idx].reset_index(drop=True), data.iloc[hold_idx].reset_index(drop=True)
    log: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": __doc__.split("Protocol")[1].strip().split("\n\n")[0],
        "rows_dev": len(dev),
        "rows_locked_test": len(hold),
        "trains_locked_test": int(hold["train_number"].nunique()),
        "rounds": [],
    }

    def save() -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")

    config: dict[str, Any] = {"edge_extra": False, "context": False, "params": {}}
    best, seconds = cv(dev, config)
    log["rounds"].append({"round": 0, "change": "baseline (current production configuration)", "kept": True,
                          "cv": best, "seconds": round(seconds, 1)})  # fmt: skip
    save()
    print(f"round 0 baseline: {best}", flush=True)
    n = 0
    for _pass in range(max_passes):
        improved = False
        for label, change in CANDIDATES:
            trial = _merge(config, change)
            if trial == config or (change.get("type_base") and not trial["edge_extra"]):
                continue
            n += 1
            result, seconds = cv(dev, trial)
            keep = result["mae_min"] <= best["mae_min"] - KEEP_MIN_GAIN
            entry = {"round": n, "change": label, "kept": keep, "cv": result, "seconds": round(seconds, 1)}
            log["rounds"].append(entry)
            print(f"round {n} {'KEEP' if keep else 'drop'} {label}: {result}", flush=True)
            if keep:
                config, best, improved = trial, result, True
            save()
        if not improved:
            break

    # The one number to quote: the winning configuration on the locked test set.
    y = hold["runtime_min"].to_numpy(dtype=float)
    pred = fit_predict(dev, hold, config, seed=99)
    baseline = rm._baselines(dev, hold)
    log["final_config"] = config
    log["locked_test"] = {
        "model": scores(y, pred),
        "baseline_section_median": scores(y, baseline["section_median"]),
        "baseline_type_speed": scores(y, baseline["type_speed"]),
    }
    log["finished_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    save()
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    args = parser.parse_args(argv)
    log = run(args.passes, args.log)
    print(json.dumps(log["locked_test"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
