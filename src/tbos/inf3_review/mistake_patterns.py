"""INF.3 §F — Mistake Pattern aggregation. Detection of *what* went wrong
on a given bet belongs to future integration with CE.2-CE.5 (a Model
malfunction, a slippage spike, a bias-checklist flag); this module only
aggregates already-tagged occurrences into recurring patterns.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import MistakeCategory
from tbos.inf3_review.calibration import FindingConfidence, compute_finding_confidence


class MistakeOccurrence(BaseModel):
    bet_id: uuid.UUID
    category: MistakeCategory
    occurred_at: datetime
    description: str
    engine_or_model_version: str | None = None


class MistakePatternRecord(BaseModel):
    category: MistakeCategory
    time_window_start: datetime
    time_window_end: datetime
    occurrences: list[uuid.UUID]
    recurrence_count: int
    finding_confidence: FindingConfidence


def aggregate_mistake_patterns(
    occurrences: list[MistakeOccurrence],
    *,
    min_sample_size_for_full_confidence: int,
    now: datetime,
    recency_half_life_days: float = 30.0,
) -> list[MistakePatternRecord]:
    by_category: dict[MistakeCategory, list[MistakeOccurrence]] = defaultdict(list)
    for occ in occurrences:
        by_category[occ.category].append(occ)

    records: list[MistakePatternRecord] = []
    for category, items in by_category.items():
        versions = {i.engine_or_model_version for i in items if i.engine_or_model_version is not None}
        version_consistency_score = 1.0 if len(versions) <= 1 else 1.0 / len(versions)

        most_recent = max(i.occurred_at for i in items)
        age_days = max(0.0, (now - most_recent).total_seconds() / 86400)
        recency_score = 0.5 ** (age_days / recency_half_life_days)

        confidence = compute_finding_confidence(
            sample_size=len(items),
            min_sample_size_for_full_confidence=min_sample_size_for_full_confidence,
            version_consistency_score=version_consistency_score,
            recency_score=recency_score,
            evidence_stability_score=1.0,  # no independent signal available yet; documented default
        )

        records.append(
            MistakePatternRecord(
                category=category,
                time_window_start=min(i.occurred_at for i in items),
                time_window_end=most_recent,
                occurrences=[i.bet_id for i in items],
                recurrence_count=len(items),
                finding_confidence=confidence,
            )
        )
    return records
