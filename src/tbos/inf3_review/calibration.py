"""INF.3 — calibration math (spec §A). Deliberately decoupled from where
predicted probabilities come from: takes plain (predicted, actual) pairs.
CE.2 doesn't exist yet in the build order, but this module needs no
forward dependency on it — it will be fed real CE.2 output later without
any change here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReliabilityBucket(BaseModel):
    predicted_bucket: float  # bucket midpoint, e.g. 0.65
    observed_frequency: float
    count: int


class FindingConfidence(BaseModel):
    sample_size_score: float = Field(ge=0.0, le=1.0)
    version_consistency_score: float = Field(ge=0.0, le=1.0)
    recency_score: float = Field(ge=0.0, le=1.0)
    evidence_stability_score: float = Field(ge=0.0, le=1.0)
    composite: float = Field(ge=0.0, le=1.0)


def brier_score(predictions: list[tuple[float, bool]]) -> float:
    """Mean squared error between predicted probability and realized
    binary outcome. Lower is better; 0.25 is the "always predict 0.5"
    baseline, 0.0 is perfect.
    """
    if not predictions:
        raise ValueError("brier_score requires at least one prediction")
    total = sum((p - (1.0 if outcome else 0.0)) ** 2 for p, outcome in predictions)
    return total / len(predictions)


def reliability_curve(predictions: list[tuple[float, bool]], *, n_buckets: int = 10) -> list[ReliabilityBucket]:
    """Groups predictions into equal-width probability buckets and reports
    the realized win frequency in each — a well-calibrated model has
    observed_frequency ≈ predicted_bucket for every bucket with meaningful count.
    """
    if not predictions:
        return []

    buckets: dict[int, list[tuple[float, bool]]] = {}
    for p, outcome in predictions:
        idx = min(int(p * n_buckets), n_buckets - 1)
        buckets.setdefault(idx, []).append((p, outcome))

    curve = []
    for idx in sorted(buckets):
        items = buckets[idx]
        midpoint = (idx + 0.5) / n_buckets
        observed = sum(1 for _, outcome in items if outcome) / len(items)
        curve.append(ReliabilityBucket(predicted_bucket=midpoint, observed_frequency=observed, count=len(items)))
    return curve


def compute_finding_confidence(
    *,
    sample_size: int,
    min_sample_size_for_full_confidence: int,
    version_consistency_score: float,
    recency_score: float,
    evidence_stability_score: float,
) -> FindingConfidence:
    """INF.3's own §Confidence-in-Findings addition: independent of raw
    statistical significance — a finding can be significant on paper but
    still low-confidence if it spans inconsistent Engine versions, is
    stale, or the underlying evidence is unstable.
    """
    sample_size_score = min(1.0, sample_size / max(1, min_sample_size_for_full_confidence))
    composite = (
        sample_size_score * version_consistency_score * recency_score * evidence_stability_score
    ) ** 0.25  # geometric mean: any single weak axis pulls the composite down hard

    return FindingConfidence(
        sample_size_score=sample_size_score,
        version_consistency_score=version_consistency_score,
        recency_score=recency_score,
        evidence_stability_score=evidence_stability_score,
        composite=composite,
    )
