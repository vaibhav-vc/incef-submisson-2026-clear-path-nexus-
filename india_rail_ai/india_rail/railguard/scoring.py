"""Explainable multi-objective scoring shared by the twin and national planners.

    score = Wd*delay + Wc*conflict + Wi*infra_stress + We*energy
          + Wt*threat + Wv*evidence_uncertainty + Wx*complexity      (lower is better)

Every factor is normalised to 0-1 and returned with its weighted contribution
so the controller can see why the winner won and why each alternative lost.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

FACTORS = ("delay", "conflict", "infra", "energy", "threat", "evidence", "complexity")
PRESETS: dict[str, dict[str, float]] = {
    "FASTEST": dict(zip(FACTORS, (1.0, 0.3, 0.05, 0.05, 0.1, 0.3, 0.05), strict=True)),
    "INFRA_PROTECT": dict(zip(FACTORS, (0.3, 0.3, 1.0, 0.2, 0.3, 0.3, 0.1), strict=True)),
    "LOWEST_RISK": dict(zip(FACTORS, (0.3, 1.0, 0.3, 0.1, 1.0, 1.0, 0.2), strict=True)),
    "BALANCED": dict(zip(FACTORS, (0.6, 0.5, 0.6, 0.2, 0.5, 0.5, 0.2), strict=True)),
}
# Delay factor = 1 - exp(-weighted_minutes / 30): a few minutes reads as a few
# minutes, and extra delay is never free (a hard cap would let a 45-minute hold
# tie with a 20-minute one). Network-wide plans move hundreds of weighted minutes,
# so the national planner passes a 180-minute scale to keep large totals apart.
DELAY_SCALE_MIN = 30.0


def _minmax(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    span = high - low
    return [0.0] * len(values) if span < 1e-9 else [(v - low) / span for v in values]


def score(
    raw: list[dict[str, float]], weights: dict[str, float], delay_scale: float = DELAY_SCALE_MIN
) -> list[dict[str, Any]]:
    """Normalise raw factor values and apply weights. Returns one entry per raw row, same order.

    Infrastructure stress and energy are relative to the alternatives on offer;
    the other factors use fixed scales so their meaning does not shift.
    """

    infra, energy = _minmax([r["infra"] for r in raw]), _minmax([r["energy"] for r in raw])
    out = []
    for i, r in enumerate(raw):
        factors = {
            "delay": 1.0 - math.exp(-r["delay"] / delay_scale),
            "conflict": min(r["conflict"] / 2.0, 1.0),
            "infra": infra[i],
            "energy": energy[i],
            "threat": min(r["threat"] / 2.0, 1.0),
            "evidence": min(r["evidence"], 1.0),
            "complexity": min(r["complexity"] / 4.0, 1.0),
        }
        contributions = {k: weights.get(k, 0.0) * v for k, v in factors.items()}
        out.append(
            {
                "index": i,
                "raw": r,
                "factors": factors,
                "contributions": contributions,
                "score": sum(contributions.values()),
            }
        )
    return out


LABEL_KEYS: dict[str, Callable[[dict[str, Any]], tuple]] = {
    "FASTEST": lambda c: (c["raw"]["delay"], c["score"]),
    "LOWEST_INFRA_STRESS": lambda c: (c["raw"]["infra"], c["score"]),
    "LOWEST_RISK": lambda c: (c["factors"]["conflict"] + c["factors"]["threat"] + c["factors"]["evidence"], c["score"]),
}


def rank(scored: list[dict[str, Any]], top: int) -> list[dict[str, Any]]:
    """Order by score (generation order breaks ties), label notable plans, explain losses.

    Returns up to `top` entries, labelled ones first, each with `labels` and `why_lost`.
    """

    ordered = sorted(scored, key=lambda c: (round(c["score"], 9), c["raw"]["delay"], c["index"]))
    winner = ordered[0]
    labels = {"RECOMMENDED": winner, **{name: min(ordered, key=key) for name, key in LABEL_KEYS.items()}}
    shown: list[dict[str, Any]] = []
    for cand in [*labels.values(), *ordered]:
        if all(cand is not s for s in shown):
            shown.append(cand)
        if len(shown) >= top:
            break
    for cand in shown:
        cand["labels"] = [name for name, c in labels.items() if c is cand]
        diffs = sorted(((cand["contributions"][k] - winner["contributions"][k], k) for k in FACTORS), reverse=True)
        cand["why_lost"] = (
            [] if cand is winner else [{"factor": k, "extra": round(d, 3)} for d, k in diffs[:2] if d > 0.001]
        )
    return shown


def public(cand: dict[str, Any]) -> dict[str, Any]:
    """Rounded, JSON-ready view of a scored candidate's scoring fields."""

    return {
        "labels": cand["labels"],
        "score": round(cand["score"], 4),
        "factors": {k: round(v, 3) for k, v in cand["factors"].items()},
        "contributions": {k: round(v, 3) for k, v in cand["contributions"].items()},
        "raw": {k: round(v, 3) for k, v in cand["raw"].items()},
        "why_lost": cand["why_lost"],
    }


def choose_weights(
    current: dict[str, float], preset: str | None, weights: dict[str, float] | None
) -> tuple[str | None, dict[str, float]]:
    """Validated (preset name, weights): a named preset, then optional per-factor overrides in 0-5."""

    name, result = None, dict(current)
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset}")
        name, result = preset, dict(PRESETS[preset])
    for key, value in (weights or {}).items():
        if key not in FACTORS or not 0 <= float(value) <= 5:
            raise ValueError(f"invalid weight {key}={value}")
        result[key], name = float(value), "CUSTOM"
    return name, result
