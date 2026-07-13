"""CE.3 — Edge Robustness Score: what fraction of the plausible EV range
(worst_case..best_case) stays positive. A fragile edge (+EV only at the
point estimate, negative under modest uncertainty) scores low even with
the same `expected` value as a robust one — this is the whole point of
never treating EV magnitude alone as "the edge" (spec §Robustness).
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce3_edge.ev import EVDistribution


class RobustnessScore(BaseModel):
    score: float
    method: str


def compute_robustness(ev_distribution: EVDistribution) -> RobustnessScore:
    worst, best = ev_distribution.worst_case, ev_distribution.best_case

    if worst >= 0:
        score = 1.0
    elif best <= 0:
        score = 0.0
    else:
        score = best / (best - worst)

    return RobustnessScore(score=max(0.0, min(1.0, score)), method="ev_range_positive_fraction")
