"""Train the deployed arrival-delay forecaster under a given number of training conditions, and decide whether to
deploy it.

    python -m india_rail real conditions --conditions 5055558

A training condition is one real (now, target) pair of observed September 2024 running under one input state:
the train's delay history known or withheld (a train never seen before), and its latest report as made, noisy by
up to 3 minutes, missed (the previous report stands), garbled by 30 minutes, or with the train class or the
route facts unknown. There are fewer real pairs than conditions asked, so every real pair is used and pairs are
drawn again under input states they do not yet have: no condition is repeated (realval.training_conditions).
The weights restore the input-state mix of the recipe the scenario bank selected, so the extra damaged views
widen what the model has seen without making it distrust ordinary reports.

The decision is taken before the test days are looked at, the way the recipe itself was chosen:
1. selection - the ways of training are fitted on what was observed before the last SELECTION_DAYS training days
   (delay history included: it is cut there too) and compared on the runs of those days, clean and under each
   damaged input, with run-clustered intervals: the recipe's sample of real pairs (deployed until now), every
   real pair once (to tell how much comes from using all pairs and how much from the extra views), and the
   conditions (scaled to the selection's share of the pairs). The conditions are deployed if they are no worse
   than the sample by more than NON_INFERIORITY of its error, on clean inputs and on damaged inputs (95%
   interval);
2. test - the same ways are fitted on everything observed by the split and scored on the runs after it (21-30
   September), which played no part in the decision. If deployed, the model trained under the conditions
   becomes the one the twin uses (models/eta_model.joblib) and the evidence records the decision, so
   `real validate` trains the same rows the same way (the draw depends only on the rows, the number and the
   seed).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from india_rail import realval
from india_rail.realval import FORECAST_FEATURES, SPLIT_DATE

SELECTION_DAYS = 4
TESTED_DAMAGES = ("cold_start", *realval.STRESS_TRAINING)


def _median(fit: pd.DataFrame, weights: np.ndarray | None, seed: int):
    return realval.eta_model("absolute_error", seed).fit(fit[FORECAST_FEATURES], fit.d_tgt - fit.d_now,
                                                         sample_weight=weights)  # fmt: skip


def _errors(model, rows: pd.DataFrame) -> np.ndarray:
    pred = np.maximum(rows.d_now.to_numpy(dtype=float) + model.predict(rows[FORECAST_FEATURES]), 0)
    return np.abs(pred - rows.d_tgt.to_numpy(dtype=float))


def _damaged_views(rows: pd.DataFrame, seed: int) -> dict[str, pd.DataFrame]:
    """The rows under each damaged input, applied per run (all of a run's forecasts see the same damage)."""

    from india_rail.scenario_bank import damage

    codes = np.unique(rows.run.to_numpy(), return_inverse=True)[1]
    rng = np.random.default_rng(seed)
    return {name: damage(rows, name, codes, rng) for name in TESTED_DAMAGES}


def _compare(base_model, cond_model, rows: pd.DataFrame, seed: int, base: str = "sample") -> dict[str, Any]:
    """Errors of both on clean rows and on each damaged view; gains are base minus conditions (positive: the
    conditions are better), with run-clustered 95% intervals."""

    from india_rail.scenario_bank import _paired

    runs = rows.run.to_numpy()
    out: dict[str, Any] = {}
    views = {"clean": rows, **_damaged_views(rows, seed)}
    pooled_runs, pooled_diff = [], []
    for name, view in views.items():
        a, b = _errors(base_model, view), _errors(cond_model, view)
        out[name] = {f"mae_{base}_min": round(float(a.mean()), 3), "mae_conditions_min": round(float(b.mean()), 3),
                     "gain": _paired(runs, a - b, seed)}  # fmt: skip
        if name != "clean":
            pooled_runs.append(runs)
            pooled_diff.append(a - b)
    out["damaged_pooled"] = {"gain": _paired(np.concatenate(pooled_runs), np.concatenate(pooled_diff), seed)}
    return out


def _decide(compared: dict[str, Any], margin: float) -> str:
    clean = compared["clean"]["gain"].get("ci95_min")
    damaged = compared["damaged_pooled"]["gain"].get("ci95_min")
    if not clean or not damaged or None in clean or None in damaged:
        return "undecided"
    return "deploy" if clean[0] >= -margin and damaged[0] >= -margin else "keep the sample"


def _arms(
    train: pd.DataFrame, recipe: str, conditions: int, seed: int, band: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Median models of the three ways of training on `train` (and, with `band`, the P10/P90 models of the
    conditions), and each one's breakdown."""

    models, info = {}, {}
    for arm, n in (("sample", None), ("every_pair_once", len(train)), ("conditions", conditions)):
        fit, w, info[arm] = realval.fit_rows(train, recipe, n, seed)
        models[arm] = _median(fit, w, seed)
        if band and arm == "conditions":
            x, y = fit[FORECAST_FEATURES], fit.d_tgt - fit.d_now
            models["p10"] = realval.eta_model("quantile", seed, 0.1).fit(x, y, sample_weight=w)
            models["p90"] = realval.eta_model("quantile", seed, 0.9).fit(x, y, sample_weight=w)
            del x, y
        del fit, w
    return models, info


def run(conditions: int, seed: int = 0, out: Path | None = None) -> dict[str, Any]:
    from india_rail.scenario_bank import NON_INFERIORITY

    started = time.time()
    recipe = realval.forecast_recipe()
    if recipe != "scenario":
        raise SystemExit("training conditions are input states of the scenario recipe; the recorded recipe is "
                         f"{recipe!r}")  # fmt: skip
    d = realval.load()
    rows = realval._with_network_state(d, realval.forecast_rows(d))
    days = sorted(x for x in rows.date.unique() if x <= SPLIT_DATE)
    first_selection_day, last_training_day = days[-SELECTION_DAYS], days[-SELECTION_DAYS - 1]
    train = rows[(rows.date <= SPLIT_DATE) & (rows.tgt_day <= SPLIT_DATE)]
    report: dict[str, Any] = {"what": __doc__.split("\n\n")[0], "conditions": conditions, "seed": seed,
                              "recipe": recipe}  # fmt: skip

    # 1. selection: rows (with their delay history) as known before the selection days, compared on their runs
    early = realval._with_network_state(d, realval.forecast_rows(d, realval.Lookups(d, last_training_day)))
    sel_train = early[(early.date <= last_training_day) & (early.tgt_day <= last_training_day)]
    sel_rows = early[(early.date >= first_selection_day) & (early.date <= SPLIT_DATE) & (early.tgt_day <= SPLIT_DATE)]
    del early
    sel_n = round(conditions * len(sel_train) / len(train))  # the same conditions per real pair as deployed
    models, sel_info = _arms(sel_train, recipe, sel_n, seed)
    margin = NON_INFERIORITY * float(_errors(models["sample"], sel_rows).mean())
    compared = _compare(models["sample"], models["conditions"], sel_rows, seed)
    decision = _decide(compared, margin)
    report["selection"] = {
        "trained_on": f"runs of 2024-09-01..{last_training_day} observed by then (delay history cut there too)",
        "scored_on": f"runs of {first_selection_day}..{SPLIT_DATE} ({len(sel_rows):,} forecasts, "
                     f"{sel_rows.run.nunique():,} runs)",
        "conditions": {k: v for k, v in sel_info["conditions"].items() if k != "days"},
        "margin_min": round(margin, 3),
        "rule": "deploy if neither the clean nor the pooled damaged-input gain over the sample is below -margin "
                "(95% interval, runs resampled)",
        "compared": compared,
        "conditions_vs_every_pair_once": _compare(models["every_pair_once"], models["conditions"], sel_rows, seed,
                                                  "every_pair_once"),
    }  # fmt: skip
    report["decision"] = decision
    del models, sel_rows, sel_train

    # 2. test: fitted on everything observed by the split, scored on the runs after it
    test = rows[rows.date > SPLIT_DATE]
    models, info = _arms(train, recipe, conditions, seed, band=True)
    band = {"p10": models["p10"], "p90": models["p90"]}
    tested = _compare(models["sample"], models["conditions"], test, seed)
    coverage = {}
    for name, view in {"clean": test, **_damaged_views(test, seed)}.items():
        lo = np.maximum(view.d_now + band["p10"].predict(view[FORECAST_FEATURES]), 0)
        hi = np.maximum(view.d_now + band["p90"].predict(view[FORECAST_FEATURES]), 0)
        coverage[name] = round(float(((view.d_tgt >= lo) & (view.d_tgt <= hi)).mean() * 100), 1)
    cond_info = info["conditions"]
    report["deployed_model"] = {
        "trained_on": {k: v for k, v in cond_info.items() if k != "days"},
        "training_days": f"{cond_info['days'][0]}..{cond_info['days'][-1]}",
        "test": {
            "scored_on": f"runs after {SPLIT_DATE} ({len(test):,} forecasts, {test.run.nunique():,} runs); "
                         "not used for the decision",
            "compared_with_the_recipe_sample": tested,
            "conditions_vs_every_pair_once": _compare(models["every_pair_once"], models["conditions"], test, seed,
                                                      "every_pair_once"),
            "p10_p90_coverage_pct": coverage,
        },
    }  # fmt: skip
    if decision == "deploy":
        realval.save_eta_model({"median": models["conditions"], **band}, recipe, int(cond_info["conditions"]))
    report["model_file"] = str(realval.ETA_MODEL_PATH.relative_to(realval.PACKAGE_ROOT)) if decision == "deploy" \
        else "unchanged"  # fmt: skip
    report["seconds"] = round(time.time() - started)
    out = out or realval.CONDITIONS_EVIDENCE
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str) + "\n")
    tmp.replace(out)
    return report
