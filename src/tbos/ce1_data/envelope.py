"""CE.1 — the canonical FieldEnvelope<T> metadata wrapper.

Every field published by CE.1 is a FieldEnvelope, never a raw value. The
five metadata axes (availability, validity, freshness, reliability,
provenance) plus taxonomy_tag are independent — CE.2 and downstream
consumers must be able to read each without any of them collapsing into
a single "quality" score. See CE.1 §A of the frozen spec.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from tbos.inf1_config.taxonomy import (
    FieldAvailability,
    FieldValidity,
    FreshnessStatus,
    InformationReliability,
)

T = TypeVar("T")


class Provenance(BaseModel):
    source_id: str
    collected_at: datetime
    parser_version: str
    source_priority_rank: int


class FreshnessInfo(BaseModel):
    collected_at: datetime
    age_seconds: float
    threshold_seconds: float
    status: FreshnessStatus


class ReliabilityInfo(BaseModel):
    source_trust_score: float = Field(ge=0.0, le=1.0)
    source_id: str


class ModificationHistoryEntry(BaseModel):
    prior_value: Any
    changed_at: datetime
    reason: str
    changed_by: str


class LineageStep(BaseModel):
    stage: str  # RawSource | Validation | Normalization | ResearchMerge | PublishedRecord
    timestamp: datetime
    detail: str | None = None


class FieldEnvelope(BaseModel, Generic[T]):
    value: T | None = None
    availability: FieldAvailability
    validity: FieldValidity
    freshness: FreshnessInfo | None = None
    reliability: ReliabilityInfo | None = None
    provenance: Provenance | None = None
    taxonomy_tag: InformationReliability

    has_conflict: bool = False
    conflicting_candidates: list["FieldEnvelope[T]"] = Field(default_factory=list)

    modification_history: list[ModificationHistoryEntry] = Field(default_factory=list)
    lineage: list[LineageStep] = Field(default_factory=list)

    @classmethod
    def missing(cls, *, reason: str = "not available at source") -> "FieldEnvelope[T]":
        """Explicit MISSING envelope — never a bare None, never fabricated."""
        return cls(
            value=None,
            availability=FieldAvailability.MISSING,
            validity=FieldValidity.INVALID,
            taxonomy_tag=InformationReliability.OPINION,
            lineage=[
                LineageStep(stage="RawSource", timestamp=datetime.now(timezone.utc), detail=reason)
            ],
        )

    def is_usable(self) -> bool:
        """True only when a Model/Engine may safely read `.value`."""
        return (
            self.availability == FieldAvailability.PRESENT
            and self.validity == FieldValidity.VALID
        )


def compute_freshness(
    collected_at: datetime, *, threshold_seconds: float, now: datetime | None = None
) -> FreshnessInfo:
    now = now or datetime.now(timezone.utc)
    age = (now - collected_at).total_seconds()
    status = FreshnessStatus.FRESH if age <= threshold_seconds else FreshnessStatus.STALE
    return FreshnessInfo(
        collected_at=collected_at, age_seconds=age, threshold_seconds=threshold_seconds, status=status
    )


def is_future_dated(collected_at: datetime, *, now: datetime | None = None, skew_seconds: float = 300) -> bool:
    now = now or datetime.now(timezone.utc)
    return collected_at > now + timedelta(seconds=skew_seconds)
