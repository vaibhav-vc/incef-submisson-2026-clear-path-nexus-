"""Section run-time model: how many minutes a train needs between two stops.

This is the planning quantity a timetable or rescheduling tool needs most. The
target is the *scheduled* run time in the public timetable, so the model learns
how Indian Railways plans run times, not how late trains actually run (no open
punctuality feed exists for that).

Method
------
* Gradient-boosted trees (scikit-learn HistGradientBoosting) with an absolute
  error objective, plus two quantile models (P10, P90) for a prediction interval.
  The trees learn the *residual* from a section prior, not the raw run time.
* The P10-P90 band is widened by split-conformal calibration (CQR) so its
  out-of-sample coverage meets the 80% target.
* The strongest signal, the run time other trains are given on the same track
  section, is target-encoded *inside each cross-validation fold* from training
  trains only, so the score is never computed with the answer in the features.
* Section priors are also kept per train type and per direction, with the
  spread of run times on the section, and an existing train's pace on the two
  sections either side of the one being predicted is used (leave-one-out).
  Predictions are rounded to whole minutes, as timetables are. This
  configuration won the measured training rounds in `india_rail.training`.
* GroupKFold by train pair (a train and its return working share sections), so
  every evaluated train is unseen during training.
* Two baselines: median speed by train type, and the training-fold median for
  the same section. The model must beat both to be worth using.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

from india_rail.ingest import PACKAGE_ROOT

MODEL_DIR = PACKAGE_ROOT / "models"
MODEL_PATH = MODEL_DIR / "runtime_model.joblib"
METRICS_PATH = MODEL_DIR / "runtime_model_metrics.json"

CATEGORICAL = ["train_type", "zone"]
NUMERIC = [
    "crow_km",
    "dep_hour",
    "position",
    "is_first",
    "is_last",
    "train_distance_km",
    "stops_per_100km",
    "from_degree",
    "to_degree",
    "edge_train_count",
]
ENCODED = ["edge_prior_min", "edge_prior_min_per_km", "edge_prior_n", "type_speed_kmph", "train_pace", "pace_residual"]
EDGE_EXTRA = ["edge_type_prior_min", "edge_dir_prior_min", "edge_q25_min", "edge_q75_min", "edge_min_min"]
CONTEXT = ["local_pace", "local_residual", "prev_runtime_min", "next_runtime_min"]
BASE_FEATURES = CATEGORICAL + NUMERIC + ENCODED
FEATURES = BASE_FEATURES + EDGE_EXTRA + CONTEXT
# The configuration selected by the measured training rounds (python -m india_rail.training; see
# models/training_log.json): section priors by train type and direction, local pace from neighbouring
# sections, type-specific starting point, larger/slower boosting, predictions rounded to whole minutes.
PRODUCTION = {
    "learning_rate": 0.05,
    "max_iter": 700,
    "max_leaf_nodes": 127,
    "min_samples_leaf": 30,
    "l2_regularization": 1.0,
}
MIN_EDGE_SUPPORT = 2
MIN_PACE_BASIS_MIN = 15
PACE_MASK_RATE = 0.2
INTERVAL_TARGET = 0.80
FALLBACK_BASE_MIN = 5.0


def load_sections(con: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT s.train_number, s.seq, s.from_code, s.to_code, s.dep_min, s.runtime_min,
               s.crow_km, t.type AS train_type, t.zone, t.distance_km AS train_distance_km,
               t.n_stops, t.return_train
        FROM sections s JOIN trains t ON t.number = s.train_number
        """,
        con,
    )
    n_sections = df.groupby("train_number")["seq"].transform("max") + 1
    df["position"] = df["seq"] / n_sections
    df["is_first"] = (df["seq"] == 0).astype(int)
    df["is_last"] = (df["seq"] == n_sections - 1).astype(int)
    df["dep_hour"] = (df["dep_min"] % 1440) // 60
    df["stops_per_100km"] = 100 * df["n_stops"] / df["train_distance_km"].where(df["train_distance_km"] > 0)
    df["edge"] = np.where(
        df["from_code"] < df["to_code"], df["from_code"] + "|" + df["to_code"], df["to_code"] + "|" + df["from_code"]
    )

    neighbours = pd.concat(
        [df[["from_code", "to_code"]], df[["to_code", "from_code"]].set_axis(["from_code", "to_code"], axis=1)]
    ).drop_duplicates()
    degree = neighbours.groupby("from_code").size()
    df["from_degree"] = df["from_code"].map(degree).fillna(0)
    df["to_degree"] = df["to_code"].map(degree).fillna(0)
    df["edge_train_count"] = df.groupby("edge")["train_number"].transform("nunique")

    # A train and its return working share every section; keep them together.
    df["group"] = [
        min(a, b) if isinstance(b, str) and b else a
        for a, b in zip(df["train_number"], df["return_train"], strict=True)
    ]
    for column in CATEGORICAL:
        df[column] = df[column].fillna("").astype("category")
    return df


def plausibility_mask(df: pd.DataFrame) -> pd.Series:
    """Exclude timetable rows that cannot describe a real movement.

    Kept: positive run time up to 10 hours, and implied straight-line speed
    under 200 km/h. Zero-minute rows (interpolated pass-through points) carry no
    run-time information at minute resolution.
    """

    speed = df["crow_km"] / (df["runtime_min"] / 60)
    ok = (df["runtime_min"] > 0) & (df["runtime_min"] <= 600)
    ok &= ~(speed > 200)
    return ok


def encode_priors(train: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Attach section and train-type priors computed from `train` rows only."""

    out = target.copy()
    stats = train.groupby("edge")["runtime_min"].agg(["median", "size"])
    per_km = (train["runtime_min"] / train["crow_km"].where(train["crow_km"] > 0.2)).groupby(train["edge"]).median()
    out["edge_prior_n"] = out["edge"].map(stats["size"]).fillna(0)
    supported = out["edge_prior_n"] >= MIN_EDGE_SUPPORT
    out["edge_prior_min"] = out["edge"].map(stats["median"]).where(supported)
    out["edge_prior_min_per_km"] = out["edge"].map(per_km).where(supported)
    speed = (train["crow_km"] / (train["runtime_min"] / 60)).groupby(train["train_type"], observed=False).median()
    out["type_speed_kmph"] = out["train_type"].map(speed).astype(float)
    return out


def encode_extra(train: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Type- and direction-specific section priors and the spread of run times on the section."""

    out = target.copy()
    support = out["edge_prior_n"] >= MIN_EDGE_SUPPORT
    by_type = train.groupby(["edge", "train_type"], observed=True)["runtime_min"].median()
    keys = pd.MultiIndex.from_arrays([out["edge"], out["train_type"]])
    out["edge_type_prior_min"] = by_type.reindex(keys).to_numpy()
    by_dir = train.groupby(["edge", "from_code"])["runtime_min"].median()
    out["edge_dir_prior_min"] = by_dir.reindex(pd.MultiIndex.from_arrays([out["edge"], out["from_code"]])).to_numpy()
    q = train.groupby("edge")["runtime_min"].quantile([0.25, 0.75]).unstack()
    out["edge_q25_min"] = out["edge"].map(q[0.25]).where(support)
    out["edge_q75_min"] = out["edge"].map(q[0.75]).where(support)
    out["edge_min_min"] = out["edge"].map(train.groupby("edge")["runtime_min"].min()).where(support)
    return out


def add_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Local pace: the train's run times on the two sections either side, relative to their priors.

    Leave-one-out like `train_pace` (the row's own run time never enters). Rows whose train pace
    was masked (new-path training) get no context either.
    """

    out = frame.sort_values(["train_number", "seq"]).copy()
    by_train = out.groupby("train_number", sort=False)
    has = out["edge_prior_min"].notna()
    runtime = out["runtime_min"].where(has)
    prior = out["edge_prior_min"].where(has)
    num = pd.Series(0.0, index=out.index)
    den = pd.Series(0.0, index=out.index)
    for k in (-2, -1, 1, 2):
        r = runtime.groupby(out["train_number"], sort=False).shift(k)
        p = prior.groupby(out["train_number"], sort=False).shift(k)
        ok = r.notna() & p.notna()
        num += r.where(ok, 0.0)
        den += p.where(ok, 0.0)
    out["local_pace"] = (num / den.where(den >= 5)).where(out["train_pace"].notna())
    out["local_residual"] = (out["local_pace"] - 1) * out["edge_prior_min"]
    masked = out["train_pace"].isna()
    out["prev_runtime_min"] = by_train["runtime_min"].shift(1).where(~masked)
    out["next_runtime_min"] = by_train["runtime_min"].shift(-1).where(~masked)
    return out.loc[frame.index]


def add_train_pace(frame: pd.DataFrame, *, mask_rate: float = 0.0, seed: int = 0) -> pd.DataFrame:
    """How fast this train runs on its *other* sections relative to the section prior.

    Leave-one-section-out: a row's own run time never enters its pace. This is
    available for any train already in the timetable (re-planning, slack
    analysis). A brand-new path has no pace, so during training a share of
    trains is masked to teach the model that fallback.
    """

    out = frame.copy()
    has_prior = out["edge_prior_min"].notna()
    runtime = out["runtime_min"].where(has_prior, 0.0)
    prior = out["edge_prior_min"].where(has_prior, 0.0)
    sum_runtime = runtime.groupby(out["train_number"]).transform("sum")
    sum_prior = prior.groupby(out["train_number"]).transform("sum")
    basis = sum_prior - prior
    pace = (sum_runtime - runtime) / basis.where(basis >= MIN_PACE_BASIS_MIN)
    if mask_rate > 0:
        trains = out["train_number"].unique()
        rng = np.random.default_rng(seed)
        masked = set(rng.choice(trains, size=int(len(trains) * mask_rate), replace=False))
        pace = pace.where(~out["train_number"].isin(masked))
    out["train_pace"] = pace
    out["pace_residual"] = (pace - 1) * out["edge_prior_min"]
    return out


def base_estimate(frame: pd.DataFrame) -> np.ndarray:
    """Starting point the trees correct: section prior, else type-speed estimate.

    Trees bin each feature into at most 255 values, so they cannot copy an exact
    prior back out. Learning the residual from this base keeps the prior's
    precision and lets the model spend its capacity on the corrections.
    """

    by_speed = frame["crow_km"] / frame["type_speed_kmph"] * 60
    base = frame["edge_prior_min"].fillna(by_speed).fillna(FALLBACK_BASE_MIN)
    return base.to_numpy(dtype=float)


def production_base(frame: pd.DataFrame) -> np.ndarray:
    """Base for the production model: the section prior for this train type where it is supported."""

    typed = frame["edge_type_prior_min"].where(frame["edge_prior_n"] >= MIN_EDGE_SUPPORT)
    return typed.fillna(pd.Series(base_estimate(frame), index=frame.index)).to_numpy(dtype=float)


def encode_for_prediction(reference: pd.DataFrame, frame: pd.DataFrame, *, use_train_pace: bool) -> pd.DataFrame:
    encoded = encode_extra(reference, encode_priors(reference, frame))
    if use_train_pace and "runtime_min" in encoded:
        return add_context(add_train_pace(encoded))
    encoded["train_pace"] = np.nan
    encoded["pace_residual"] = np.nan
    for column in CONTEXT:
        encoded[column] = np.nan
    return encoded


def _model(loss: str, quantile: float | None = None) -> HistGradientBoostingRegressor:
    kwargs: dict[str, Any] = {
        "loss": loss,
        **PRODUCTION,
        "categorical_features": "from_dtype",
        "random_state": 20261007,
    }
    if quantile is not None:
        kwargs["quantile"] = quantile
    return HistGradientBoostingRegressor(**kwargs)


def _baselines(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    speed = (train["crow_km"] / (train["runtime_min"] / 60)).groupby(train["train_type"], observed=False).median()
    overall = float((train["crow_km"] / (train["runtime_min"] / 60)).median())
    test_speed = test["train_type"].map(speed).astype(float).fillna(overall)
    type_speed = (test["crow_km"] / test_speed * 60).fillna(train["runtime_min"].median()).to_numpy()
    edge_median = train.groupby("edge")["runtime_min"].median()
    section = test["edge"].map(edge_median).to_numpy()
    section = np.where(np.isnan(section), type_speed, section)
    return {"type_speed": type_speed, "section_median": section}


def _scores(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    err = np.abs(y - pred)
    long = y >= 10
    return {
        "mae_min": round(float(err.mean()), 3),
        "median_ae_min": round(float(np.median(err)), 3),
        "mape_sections_10min_plus": round(float((err[long] / y[long]).mean() * 100), 2),
        "within_2_min_pct": round(float((err <= 2).mean() * 100), 2),
    }


@dataclass
class TrainedRuntimeModel:
    median: HistGradientBoostingRegressor
    p10: HistGradientBoostingRegressor
    p90: HistGradientBoostingRegressor
    reference: pd.DataFrame  # rows used to compute priors at inference time
    metadata: dict[str, Any]

    interval_margin: float = 0.0  # conformal widening of the P10-P90 band, minutes

    def predict_frame(self, frame: pd.DataFrame, *, use_train_pace: bool = True) -> pd.DataFrame:
        """Predict run times for rows shaped like `load_sections` output.

        With use_train_pace the train's other scheduled sections inform the
        prediction (existing train). Disable it to treat the path as new.
        """

        reference = self.reference
        if "train_number" in frame:
            # Training priors never include the row's own train; match that here.
            reference = reference[~reference["train_number"].isin(frame["train_number"].unique())]
        encoded = encode_for_prediction(reference, frame, use_train_pace=use_train_pace)
        x = encoded[FEATURES]
        base = production_base(encoded)
        out = pd.DataFrame(index=frame.index)
        out["p50"] = np.round(base + self.median.predict(x))  # timetables are minute-resolution
        out["p10"] = np.minimum(base + self.p10.predict(x), out["p50"]) - self.interval_margin
        out["p90"] = np.maximum(base + self.p90.predict(x), out["p50"]) + self.interval_margin
        return out.clip(lower=0)


def _encode_training_rows(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Section priors for training rows, computed without each row's own train.

    Inner GroupKFold mirrors what the model sees at prediction time: a prior
    built from *other* trains. Train pace is then added, with some trains masked
    so the model also learns the new-path case.
    """

    parts = [
        encode_extra(train.iloc[a], encode_priors(train.iloc[a], train.iloc[b]))
        for a, b in GroupKFold(n_splits=4).split(train, groups=train["group"])
    ]
    encoded = pd.concat(parts).loc[train.index]
    return add_context(add_train_pace(encoded, mask_rate=PACE_MASK_RATE, seed=seed))


def _fit_three(encoded: pd.DataFrame, y: np.ndarray) -> dict[str, HistGradientBoostingRegressor]:
    residual = y - production_base(encoded)
    models = {"p50": _model("absolute_error"), "p10": _model("quantile", 0.1), "p90": _model("quantile", 0.9)}
    for model in models.values():
        model.fit(encoded[FEATURES], residual)
    return models


def evaluate_and_train(con: sqlite3.Connection, *, folds: int = 5, save: bool = True) -> dict[str, Any]:
    df = load_sections(con)
    mask = plausibility_mask(df)
    data = df[mask].reset_index(drop=True)
    y = data["runtime_min"].to_numpy(dtype=float)

    names = ["p50", "p10", "p90", "new_path_p50", "type_speed", "section_median"]
    oof = {name: np.zeros(len(data)) for name in names}
    fold_of = np.zeros(len(data), dtype=int)
    for fold, (train_idx, test_idx) in enumerate(GroupKFold(n_splits=folds).split(data, y, groups=data["group"])):
        train, test = data.iloc[train_idx], data.iloc[test_idx]
        fold_of[test_idx] = fold
        train_encoded = _encode_training_rows(train, seed=fold)
        test_encoded = encode_for_prediction(train, test, use_train_pace=True)
        models = _fit_three(train_encoded, train["runtime_min"].to_numpy(dtype=float))
        base = production_base(test_encoded)
        for key, model in models.items():
            oof[key][test_idx] = base + model.predict(test_encoded[FEATURES])
        oof["p50"][test_idx] = np.round(oof["p50"][test_idx])
        new_path = encode_for_prediction(train, test, use_train_pace=False)
        oof["new_path_p50"][test_idx] = np.round(production_base(new_path) + models["p50"].predict(new_path[FEATURES]))
        for key, pred in _baselines(train, test).items():
            oof[key][test_idx] = pred

    p10 = np.minimum(oof["p10"], oof["p50"])
    p90 = np.maximum(oof["p90"], oof["p50"])
    # Split-conformal widening (CQR): each fold's margin comes from the other
    # folds' conformity scores, so reported coverage is out-of-sample.
    conformity = np.maximum(p10 - y, y - p90)
    margins = np.zeros(len(data))
    for fold in range(folds):
        others = conformity[fold_of != fold]
        margins[fold_of == fold] = max(float(np.quantile(others, INTERVAL_TARGET)), 0.0)
    lo, hi = np.maximum(p10 - margins, 0), p90 + margins

    metrics: dict[str, Any] = {
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": "scheduled section run time (minutes) from the public timetable",
        "rows_total": len(df),
        "rows_used": len(data),
        "rows_excluded_implausible_or_zero": int((~mask).sum()),
        "trains": int(data["train_number"].nunique()),
        "cv": (
            f"{folds}-fold GroupKFold by train pair (every scored train unseen in training); "
            "section priors re-encoded inside each fold"
        ),
        "scores": {
            "gradient_boosting_existing_train": _scores(y, oof["p50"]),
            "gradient_boosting_new_path": _scores(y, oof["new_path_p50"]),
            "baseline_section_median": _scores(y, oof["section_median"]),
            "baseline_type_speed": _scores(y, oof["type_speed"]),
        },
        "score_notes": {
            "existing_train": "Uses the train's other scheduled sections (leave-one-section-out pace and the "
            "pace on the two sections either side).",
            "new_path": "Train pace and neighbouring-section context withheld, as for a path not yet timetabled.",
        },
        "interval_p10_p90": {
            "target_coverage_pct": INTERVAL_TARGET * 100,
            "raw_quantile_coverage_pct": round(float(((y >= p10) & (y <= p90)).mean() * 100), 2),
            "conformal_coverage_pct": round(float(((y >= lo) & (y <= hi)).mean() * 100), 2),
            "conformal_mean_width_min": round(float((hi - lo).mean()), 3),
        },
        "features": FEATURES,
        "limitations": [
            "Learns planned (timetabled) run times, not observed running or delays.",
            "Timetable snapshot is ~2016; track upgrades since then are not reflected.",
            "Straight-line distance stands in for track distance where no track geometry is loaded.",
        ],
    }

    if save:
        encoded = _encode_training_rows(data, seed=folds)
        models = _fit_three(encoded, y)
        final_margin = max(float(np.quantile(conformity, INTERVAL_TARGET)), 0.0)
        bundle = TrainedRuntimeModel(
            median=models["p50"],
            p10=models["p10"],
            p90=models["p90"],
            reference=data[["train_number", "edge", "from_code", "runtime_min", "crow_km", "train_type"]].copy(),
            metadata={k: metrics[k] for k in ("created_at_utc", "target", "rows_used", "features")},
            interval_margin=final_margin,
        )
        metrics["interval_p10_p90"]["deployed_margin_min"] = round(final_margin, 3)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, MODEL_PATH, compress=3)
        METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def load_model(path: Path = MODEL_PATH) -> TrainedRuntimeModel:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `python -m india_rail train` first.")
    return joblib.load(path)
