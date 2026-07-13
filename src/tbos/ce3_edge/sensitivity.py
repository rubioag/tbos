"""CE.3 — Sensitivity Analysis: how much does EV move if the underlying
probability estimate is off by ±1%. Identifies unstable opportunities
where the edge only exists because of an unusually precise-looking
probability, not because it survives modest estimation error.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce3_edge.ev import clamp01, ev_value

DEFAULT_DELTA = 0.01


class Perturbation(BaseModel):
    delta_probability: float
    resulting_ev: float


class SensitivityAnalysis(BaseModel):
    perturbations: list[Perturbation]
    dominant_assumption_drivers: list[str]


def run_sensitivity_analysis(
    probability: float, offered_odds: float, *, delta: float = DEFAULT_DELTA
) -> SensitivityAnalysis:
    up = Perturbation(delta_probability=delta, resulting_ev=ev_value(clamp01(probability + delta), offered_odds))
    down = Perturbation(delta_probability=-delta, resulting_ev=ev_value(clamp01(probability - delta), offered_odds))
    return SensitivityAnalysis(
        perturbations=[up, down],
        dominant_assumption_drivers=["probability_estimate"],
    )
