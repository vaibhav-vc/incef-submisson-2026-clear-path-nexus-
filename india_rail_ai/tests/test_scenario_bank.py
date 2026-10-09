"""Scenario bank: even spread over situation types, damaged inputs, training weights, planner scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from test_shared_track import data  # noqa: F401 - synthetic network with an express over a local's track

from india_rail import realval, scenario_bank
from india_rail.railguard.national import NationalTwin


def test_scenarios_are_spread_evenly_and_rare_situations_give_all_they_have():
    cell = pd.Series(["common"] * 1000 + ["rare"] * 7 + ["middle"] * 60)
    chosen = scenario_bank.pick_scenarios(cell, 100, np.random.default_rng(0))
    picked = cell[chosen].value_counts()
    assert len(chosen) == len(set(chosen)) == 100
    assert picked["rare"] == 7  # all of the rare type
    assert abs(picked["common"] - picked["middle"]) <= 1  # the rest split evenly
    small = scenario_bank.pick_scenarios(cell, 2000, np.random.default_rng(0))
    assert len(small) == len(cell)  # quota above the pool: everything, nothing twice


def _frame():
    return pd.DataFrame({
        "d_now": [10.0, 10.0, 40.0, 0.0], "d_prev": [4.0, 4.0, np.nan, 2.0], "hist_q": [5.0] * 4,
        "hist_change": [1.0] * 4, "hist_n_q": [9] * 4, "priority": [2] * 4, "km_gap": [50.0] * 4,
        "single_km_gap": [0.0] * 4, "dwell_recovery": [3.0] * 4,
    })  # fmt: skip


def test_each_damaged_input_changes_only_what_it_names():
    f, codes, rng = _frame(), np.array([0, 0, 1, 2]), np.random.default_rng(1)
    noisy = scenario_bank.damage(f, "feed_noise_pm3_min", codes, rng)
    assert noisy.d_now[0] == noisy.d_now[1]  # one scenario, one noise draw for all its targets
    assert (np.abs(noisy.d_now - f.d_now) <= 3).all() and (noisy.d_now >= 0).all()
    missed = scenario_bank.damage(f, "missed_report", codes, rng)
    assert missed.d_now.tolist() == [4.0, 4.0, 40.0, 2.0]  # the previous report; the first report keeps its own
    garbled = scenario_bank.damage(f, "garbled_report_pm30_min", codes, rng)
    assert set(np.abs(garbled.d_now - f.d_now).round(6)) <= {0.0, 10.0, 30.0}  # +-30, floored at 0
    cold = scenario_bank.damage(f, "cold_start", codes, rng)
    assert cold.hist_q.isna().all() and (cold.hist_n_q == 0).all() and cold.d_now.equals(f.d_now)
    assert scenario_bank.damage(f, "unknown_train_class", codes, rng).priority.isna().all()  # unknown, not 3
    route = scenario_bank.damage(f, "unknown_route_facts", codes, rng)
    assert route.km_gap.isna().all() and route.single_km_gap.isna().all() and route.d_now.equals(f.d_now)
    with pytest.raises(ValueError):
        scenario_bank.damage(f, "made_up", codes, rng)


def test_training_weights_lift_rare_situations_within_the_cap():
    cell = pd.Series(["a"] * 10_000 + ["b"] * 4)
    w = scenario_bank.balance_weights(cell)
    assert w[-1] > w[0] and w.max() <= scenario_bank.BALANCE_CAP
    assert np.isclose(w.mean(), 1.0, atol=0.05) or w.max() == scenario_bank.BALANCE_CAP


def test_stress_training_keeps_the_real_answer_and_the_deployed_recipe_is_unchanged():
    f = pd.concat([_frame()] * 500, ignore_index=True)
    f["d_tgt"] = 12.0
    out = realval.stress_training(f, np.random.default_rng(3))
    assert (out.d_tgt == 12.0).all() and len(out) == len(f)  # the target is always the real outcome
    assert (out.d_now != f.d_now).any() and out.priority.isna().any() and out.km_gap.isna().any()
    # at most one damage per row: a row whose class or route facts were blanked kept its real report
    blanked = out.priority.isna() | out.km_gap.isna()
    assert (out.d_now[blanked] == f.d_now[blanked]).all() and not (out.priority.isna() & out.km_gap.isna()).any()
    # cold_start draws exactly as the deployed training always did: same rows lose their history
    a, b = realval.cold_start(f, np.random.default_rng(9)), realval.cold_start(f, np.random.default_rng(9))
    assert a.hist_q.isna().equals(b.hist_q.isna()) and 0.05 < a.hist_q.isna().mean() < 0.3


def test_planner_scenarios_run_clean_on_shared_track(data):  # noqa: F811
    tw = NationalTwin(data, start_min=600.0)
    losses = np.array([3.0, 8.0, 25.0, 45.0, 90.0])
    results = [scenario_bank.planner_scenario(i, 7, tw, losses) for i in range(120)]
    ran = [r for r in results if "state" in r]
    assert ran, "no scenario found a running train"
    assert not [v for r in ran for v in r["violations"]]
    assert any("top_delay" in r for r in ran)  # some were ranked and independently checked
    summary = scenario_bank.summarise_planner(results, losses, 1.0, 7)
    assert summary["violations"] == 0 and summary["crashes"] == 0
    assert summary["run"] + sum(summary["skipped"].values()) == len(results)


def test_the_recipe_is_chosen_only_on_a_clear_interval():
    win = {"clean": {"ci95_min": [-0.01, 0.05]}, "damaged": {"ci95_min": [0.2, 0.6]}}
    assert scenario_bank._decide(win) == "scenario"
    worse = {"clean": {"ci95_min": [-0.2, -0.05]}, "damaged": {"ci95_min": [0.2, 0.6]}}
    assert scenario_bank._decide(worse) == "plain"
    unclear = {"clean": {"ci95_min": [-0.01, 0.05]}, "damaged": {"ci95_min": [-0.1, 0.6]}}
    assert scenario_bank._decide(unclear) == "plain"
    assert scenario_bank._decide({"clean": {"scenarios": 0}, "damaged": {"scenarios": 0}}).startswith("undecided")
    paired = scenario_bank._paired(np.array([0.5, 0.4, 0.6, 0.5]), seed=1)
    assert paired["scenarios"] == 4 and paired["ci95_min"][0] > 0


def test_scores_never_write_nan_when_no_situation_has_enough_scenarios():
    err = {m: np.array([1.0, 2.0]) for m in ("persistence", "twin_rule", "learned")}
    out = scenario_bank._scores(err, np.array([0, 1]), np.array(["a", "b"]))
    assert out["learned"]["worst_situation_mae_min"] is None and out["learned"]["mae_min"] == 1.5
