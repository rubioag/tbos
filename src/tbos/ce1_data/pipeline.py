"""CE.1 — Data Ingestion Pipeline (spec §F).

    fetch -> parse -> validate -> availability -> freshness -> reliability
    -> provenance -> taxonomy -> conflict detection -> research merge
    -> lineage -> snapshot assembly -> publish

Each step below is a small, independently testable pure function. The
orchestration in `build_field_envelope` composes steps 2-8 for a single
field; conflict detection and research merge operate across multiple
candidate envelopes for the *same* field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeVar

from tbos.ce1_data.envelope import (
    FieldEnvelope,
    LineageStep,
    ModificationHistoryEntry,
    Provenance,
    ReliabilityInfo,
    compute_freshness,
    is_future_dated,
)
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, InformationReliability

T = TypeVar("T")


class RawFieldCandidate:
    """A single unvalidated observation from one source, pre-pipeline."""

    def __init__(
        self,
        *,
        value: object,
        source_id: str,
        collected_at: datetime,
        parser_version: str,
        source_priority_rank: int,
        source_trust_score: float,
        taxonomy_tag: InformationReliability = InformationReliability.FACT,
    ) -> None:
        self.value = value
        self.source_id = source_id
        self.collected_at = collected_at
        self.parser_version = parser_version
        self.source_priority_rank = source_priority_rank
        self.source_trust_score = source_trust_score
        self.taxonomy_tag = taxonomy_tag


def build_field_envelope(
    candidate: RawFieldCandidate | None,
    *,
    validate: object,  # Callable[[object], bool]
    freshness_threshold_seconds: float,
    now: datetime | None = None,
) -> FieldEnvelope:
    """Steps: validate -> availability -> freshness -> reliability
    -> provenance -> taxonomy -> lineage, for one field from one source.
    """
    now = now or datetime.now(timezone.utc)

    if candidate is None:
        return FieldEnvelope.missing(reason="no source produced this field")

    if is_future_dated(candidate.collected_at, now=now):
        return FieldEnvelope(
            value=None,
            availability=FieldAvailability.PRESENT,
            validity=FieldValidity.INVALID,
            taxonomy_tag=candidate.taxonomy_tag,
            lineage=[
                LineageStep(stage="Validation", timestamp=now, detail="collected_at is future-dated")
            ],
        )

    is_valid = bool(validate(candidate.value)) if callable(validate) else True
    validity = FieldValidity.VALID if is_valid else FieldValidity.INVALID

    freshness = compute_freshness(
        candidate.collected_at, threshold_seconds=freshness_threshold_seconds, now=now
    )
    reliability = ReliabilityInfo(
        source_trust_score=candidate.source_trust_score, source_id=candidate.source_id
    )
    provenance = Provenance(
        source_id=candidate.source_id,
        collected_at=candidate.collected_at,
        parser_version=candidate.parser_version,
        source_priority_rank=candidate.source_priority_rank,
    )

    return FieldEnvelope(
        value=candidate.value if is_valid else None,
        availability=FieldAvailability.PRESENT,
        validity=validity,
        freshness=freshness,
        reliability=reliability,
        provenance=provenance,
        taxonomy_tag=candidate.taxonomy_tag,
        lineage=[
            LineageStep(stage="RawSource", timestamp=candidate.collected_at, detail=candidate.source_id),
            LineageStep(stage="Validation", timestamp=now, detail=f"valid={is_valid}"),
            LineageStep(stage="Normalization", timestamp=now),
            LineageStep(stage="PublishedRecord", timestamp=now),
        ],
    )


def detect_conflict(candidates: list[FieldEnvelope]) -> FieldEnvelope:
    """Multiple usable envelopes for the same field, from different sources,
    disagreeing on value: publish the highest-priority source's value as
    `.value`, but never hide the disagreement — `has_conflict` + all
    candidates remain attached. No automatic resolution (CE.1 §9).
    """
    usable = [c for c in candidates if c.is_usable()]
    if len(usable) <= 1:
        return candidates[0] if candidates else FieldEnvelope.missing()

    distinct_values = {c.value for c in usable}
    if len(distinct_values) <= 1:
        return usable[0]

    best = min(usable, key=lambda c: c.provenance.source_priority_rank if c.provenance else 999)
    return best.model_copy(update={"has_conflict": True, "conflicting_candidates": usable})


def merge_research_update(
    existing: FieldEnvelope, update: FieldEnvelope, *, changed_by: str, reason: str
) -> FieldEnvelope:
    """Additive merge of an IL.1 Research Update into an existing published
    field. Never overwrites a FACT-tagged field (CE.1 §6 step 10 / §9).
    """
    if existing.taxonomy_tag == InformationReliability.FACT:
        return existing

    now = datetime.now(timezone.utc)
    history_entry = ModificationHistoryEntry(
        prior_value=existing.value, changed_at=now, reason=reason, changed_by=changed_by
    )
    lineage_step = LineageStep(stage="ResearchMerge", timestamp=now, detail=reason)

    return update.model_copy(
        update={
            "modification_history": [*existing.modification_history, history_entry],
            "lineage": [*existing.lineage, lineage_step],
        }
    )
