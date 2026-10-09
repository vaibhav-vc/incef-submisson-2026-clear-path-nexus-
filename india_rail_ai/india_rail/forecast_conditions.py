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
1. selection - both ways of training (the recipe's sample of real pairs, and the conditions) are fitted on what
   was observed before the last SELECTION_DAYS training days and compared on the runs of those days, clean and
   under each damaged input, with run-clustered intervals. The conditions are deployed if they are no worse
   than the sample by more than NON_INFERIORITY on clean inputs and not worse under damaged inputs;
2. test - both are fitted on everything observed by the split and scored on the runs after it (21-30
   September), which played no part in the decision. If deployed, the model trained under the conditions
   becomes the one the twin uses (models/eta_model.joblib) and the evidence records the decision, so
   `real validate` trains the same way.
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


def _compare(sample_model, cond_model, rows: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Errors of both on clean rows and on each damaged view; gains are sample minus conditions (positive: the
    conditions are better), with run-clustered 95% intervals."""

    from india_rail.scenario_bank import _paired

    runs = rows.run.to_numpy()
    out: dict[str, Any] = {}
    views = {"clean": rows, **_damaged_views(rows, seed)}
    pooled_runs, pooled_diff = [], []
    for name, view in views.items():
        a, b = _errors(sample_model, view), _errors(cond_model, view)
        out[name] = {"mae_sample_min": round(float(a.mean()), 3), "mae_conditions_min": round(float(b.mean()), 3),
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
    first_selection_day = days[-SELECTION_DAYS]
    report: dict[str, Any] = {"what": __doc__.split("\n\n")[0], "conditions_asked": conditions, "seed": seed,
                              "recipe": recipe}  # fmt: skip

    # 1. selection: fitted on what was observed before the selection days, compared on their runs
    sel_train = rows[(rows.date < first_selection_day) & (rows.tgt_day < first_selection_day)]
    sel_rows = rows[(rows.date >= first_selection_day) & (rows.date <= SPLIT_DATE) & (rows.tgt_day <= SPLIT_DATE)]
    rng = np.random.default_rng(seed)
    fit, w, _ = realval.fit_rows(sel_train, recipe, None, rng)
    sample_model = _median(fit, w, seed)
    fit, w, sel_info = realval.fit_rows(sel_train, recipe, conditions, rng)
    cond_model = _median(fit, w, seed)
    del fit, w
    margin = NON_INFERIORITY * float(_errors(sample_model, sel_rows).mean())
    compared = _compare(sample_model, cond_model, sel_rows, seed)
    decision = _decide(compared, margin)
    report["selection"] = {
        "trained_on": f"runs of 2024-09-01..{days[-SELECTION_DAYS - 1]} observed by then",
        "scored_on": f"runs of {first_selection_day}..{SPLIT_DATE} ({len(sel_rows):,} forecasts, "
                     f"{sel_rows.run.nunique():,} runs)",
        "conditions": {k: v for k, v in sel_info.items() if k != "days"},
        "margin_min": round(margin, 3),
        "rule": "deploy if neither the clean nor the pooled damaged-input gain is below -margin (95% interval, "
                "runs resampled)",
        "compared": compared,
    }  # fmt: skip
    report["decision"] = decision

    # 2. test: fitted on everything observed by the split, scored on the runs after it
    train, test = rows[(rows.date <= SPLIT_DATE) & (rows.tgt_day <= SPLIT_DATE)], rows[rows.date > SPLIT_DATE]
    rng = np.random.default_rng(seed)
    fit, w, _ = realval.fit_rows(train, recipe, None, rng)
    sample_model = _median(fit, w, seed)
    fit, w, info = realval.fit_rows(train, recipe, conditions, rng)
    y = fit.d_tgt - fit.d_now
    x = fit[FORECAST_FEATURES]
    models = {
        "median": realval.eta_model("absolute_error", seed).fit(x, y, sample_weight=w),
        "p10": realval.eta_model("quantile", seed, 0.1).fit(x, y, sample_weight=w),
        "p90": realval.eta_model("quantile", seed, 0.9).fit(x, y, sample_weight=w),
    }
    del fit, w, x, y
    tested = _compare(sample_model, models["median"], test, seed)
    coverage = {}
    for name, view in {"clean": test, **_damaged_views(test, seed)}.items():
        lo = np.maximum(view.d_now + models["p10"].predict(view[FORECAST_FEATURES]), 0)
        hi = np.maximum(view.d_now + models["p90"].predict(view[FORECAST_FEATURES]), 0)
        coverage[name] = round(float(((view.d_tgt >= lo) & (view.d_tgt <= hi)).mean() * 100), 1)
    report["deployed_model"] = {
        "trained_on": {k: v for k, v in info.items() if k != "days"},
        "training_days": f"{info['days'][0]}..{info['days'][-1]}",
        "test": {
            "scored_on": f"runs after {SPLIT_DATE} ({len(test):,} forecasts, {test.run.nunique():,} runs); "
                         "not used for the decision",
            "compared_with_the_recipe_sample": tested,
            "p10_p90_coverage_pct": coverage,
        },
    }  # fmt: skip
    if decision == "deploy":
        realval.save_eta_model(models, recipe, int(info["conditions"]))
    report["model_file"] = str(realval.ETA_MODEL_PATH.relative_to(realval.PACKAGE_ROOT)) if decision == "deploy" \
        else "unchanged"  # fmt: skip
    report["seconds"] = round(time.time() - started)
    out = out or realval.CONDITIONS_EVIDENCE
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str) + "\n")
    tmp.replace(out)
    return report
