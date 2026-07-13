"""INF.3 ORM models. Everything here is append-only and read-only with
respect to INF.2 — this module never writes to the events table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class CalibrationRecordRow(Base):
    __tablename__ = "calibration_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, default=uuid.uuid4)
    scope: Mapped[dict] = mapped_column(_JSONVariant)  # {model_id?, engine_version, edge_source_category?, ...}
    sample_size: Mapped[int] = mapped_column(Integer)
    brier_score: Mapped[float]
    reliability_curve: Mapped[list] = mapped_column(_JSONVariant)
    finding_confidence: Mapped[dict] = mapped_column(_JSONVariant)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(CalibrationRecordRow, "before_update", forbid_mutation)
event.listen(CalibrationRecordRow, "before_delete", forbid_mutation)


class DecisionQualityRecordRow(Base):
    __tablename__ = "decision_quality_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    classification: Mapped[str] = mapped_column(String(40))
    confidence_tier: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(10))
    classification_rules_version: Mapped[str] = mapped_column(String(20))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(DecisionQualityRecordRow, "before_update", forbid_mutation)
event.listen(DecisionQualityRecordRow, "before_delete", forbid_mutation)


class MistakePatternRecordRow(Base):
    __tablename__ = "mistake_pattern_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(30))
    time_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrences: Mapped[list] = mapped_column(_JSONVariant)  # list[str(uuid)]
    recurrence_count: Mapped[int] = mapped_column(Integer)
    finding_confidence: Mapped[dict] = mapped_column(_JSONVariant)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(MistakePatternRecordRow, "before_update", forbid_mutation)
event.listen(MistakePatternRecordRow, "before_delete", forbid_mutation)


class CandidateFindingRow(Base):
    """Current status here is a cached projection; the authoritative
    append-only history lives in FindingReviewEvent — same pattern as
    ModelRegistryEntry / ModelLifecycleEvent in INF.1.
    """

    __tablename__ = "candidate_findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(30))  # CalibrationRecord|DecisionQualityRecord|MistakePatternRecord
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    statement: Mapped[str] = mapped_column(String(2000))
    finding_confidence: Mapped[dict] = mapped_column(_JSONVariant)
    proposed_for: Mapped[str] = mapped_column(String(30))  # IL2_KnowledgeBase|IL3_EdgeAttribution
    status: Mapped[str] = mapped_column(String(20), default="CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review_events: Mapped[list["FindingReviewEvent"]] = relationship(
        back_populates="finding", order_by="FindingReviewEvent.timestamp"
    )


class FindingReviewEvent(Base):
    __tablename__ = "finding_review_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_findings.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    reviewer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(String(2000))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped[CandidateFindingRow] = relationship(back_populates="review_events")


event.listen(FindingReviewEvent, "before_update", forbid_mutation)
event.listen(FindingReviewEvent, "before_delete", forbid_mutation)
