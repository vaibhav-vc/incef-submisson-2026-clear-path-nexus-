"""Training conditions: exactly as many as asked, none repeated, the recipe's input-state mix restored."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from india_rail import realval


def _pairs(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d_now = rng.uniform(0, 90, n)
    return pd.DataFrame({
        "d_now": d_now, "d_prev": np.where(rng.random(n) < 0.8, d_now - 2, np.nan),
        "d_tgt": d_now + rng.normal(0, 9, n),
        "sch_gap": rng.uniform(10, 600, n), "stops_gap": rng.integers(1, 9, n), "km_gap": rng.uniform(5, 400, n),
        "single_km_gap": rng.uniform(0, 50, n), "dwell_recovery": rng.uniform(0, 5, n),
        "priority": rng.choice([1.0, 2.0, 3.0, np.nan], n), "hour": rng.integers(0, 24, n),
        "weekday": rng.integers(0, 7, n), "hist_change": rng.normal(0, 5, n), "hist_q": rng.uniform(0, 30, n),
        "hist_n_q": rng.integers(0, 6, n), "net_delay_2h": rng.uniform(0, 50, n), "zone": "NR",
        "run": [f"T{i // 5}|2024-09-0{1 + i % 5}" for i in range(n)],
        "date": [f"2024-09-0{1 + i % 5}" for i in range(n)],
    })  # fmt: skip


def _keys(fit: pd.DataFrame) -> pd.DataFrame:
    return fit[[*realval.FORECAST_FEATURES, "d_tgt", "run"]].round(9).astype(str)


def test_more_conditions_than_pairs_uses_every_pair_and_repeats_none():
    train = _pairs(2_000)
    fit, weights, info = realval.training_conditions(train, 5_055, np.random.default_rng(0))
    assert len(fit) == len(weights) == info["conditions"] == 5_055 and info["distinct"]
    assert info["real_pairs_used"] == 2_000
    assert not _keys(fit).duplicated().any()  # no two conditions alike
    assert np.isclose(weights.mean(), 1.0) and (weights > 0).all()
    # Targets are always the real outcome of the pair
    assert set(fit.d_tgt.round(9)) <= set(train.d_tgt.round(9))


def test_the_weights_restore_the_recipe_mix_of_input_states():
    train = _pairs(3_000)
    fit, weights, info = realval.training_conditions(train, 9_000, np.random.default_rng(0))
    states = info["by_input_state"]
    assert states["history_withheld"] > 0 and states["garbled_report_pm30_min"] > 0
    as_made = (fit.d_now.round(9).isin(train.d_now.round(9))).to_numpy()
    # Unweighted, the extra conditions make damaged inputs common; weighted, the plain reports dominate again
    assert np.average(as_made, weights=weights) > as_made.mean()


def test_fewer_conditions_than_pairs_samples_pairs_without_repeats():
    fit, _, info = realval.training_conditions(_pairs(2_000), 500, np.random.default_rng(0))
    assert len(fit) == 500 and info["real_pairs_used"] == 500 and info["distinct"]


def test_more_conditions_than_exist_are_refused():
    with pytest.raises(ValueError, match="real pairs give"):
        realval.training_conditions(_pairs(10), 10 * realval.N_STATES + 1, np.random.default_rng(0))


def test_the_stress_recipe_is_unchanged_by_the_refactor():
    train = _pairs(1_000)
    a = realval.stress_training(train, np.random.default_rng(7))
    rng = np.random.default_rng(7)
    expected = realval.cold_start(train, rng)
    which = np.searchsorted(np.cumsum(list(realval.STRESS_TRAINING.values())), rng.random(len(train)), side="right")
    assert (a.hist_n_q.to_numpy() == expected.hist_n_q.to_numpy()).all()
    assert ((which == len(realval.STRESS_TRAINING)) <= (a.d_now.to_numpy() == train.d_now.to_numpy())).all()
