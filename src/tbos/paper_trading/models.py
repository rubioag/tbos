"""Paper Trading storage. Append-only throughout — run status is a cached
projection on PaperTradingRunRow, authoritative history lives in
PaperTradingRunEventRow (same pattern as Model Registry / Finding lifecycle).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class PaperTradingRunRow(Base):
    __tablename__ = "paper_trading_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    protocol_version: Mapped[str] = mapped_column(String(20))
    config_version_id_at_start: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    status_events: Mapped[list["PaperTradingRunEventRow"]] = relationship(
        back_populates="run", order_by="PaperTradingRunEventRow.timestamp"
    )


class PaperTradingRunEventRow(Base):
    __tablename__ = "paper_trading_run_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper_trading_runs.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[PaperTradingRunRow] = relationship(back_populates="status_events")


event.listen(PaperTradingRunEventRow, "before_update", forbid_mutation)
event.listen(PaperTradingRunEventRow, "before_delete", forbid_mutation)


class PaperTradingBetRow(Base):
    __tablename__ = "paper_trading_bets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    structural_error: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(PaperTradingBetRow, "before_update", forbid_mutation)
event.listen(PaperTradingBetRow, "before_delete", forbid_mutation)


class ApprovalRecordRow(Base):
    __tablename__ = "paper_trading_approval_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(ApprovalRecordRow, "before_update", forbid_mutation)
event.listen(ApprovalRecordRow, "before_delete", forbid_mutation)
