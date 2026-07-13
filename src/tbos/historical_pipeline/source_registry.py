"""Historical Data Pipeline §A — Historical Source Registry."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base


class HistoricalSource(Base):
    __tablename__ = "historical_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(30))  # RESULTS|PLAYER_STATS|SURFACE|INJURY_STATE|ODDS|CLOSING_LINES
    coverage_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    format: Mapped[str] = mapped_column(String(50))
    reliability_prior: Mapped[float]
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(HistoricalSource, "before_update", forbid_mutation)
event.listen(HistoricalSource, "before_delete", forbid_mutation)


def register_source(
    session: Session,
    *,
    source_id: str,
    domain: str,
    coverage_start: datetime,
    coverage_end: datetime,
    format: str,
    reliability_prior: float,
) -> HistoricalSource:
    row = HistoricalSource(
        source_id=source_id,
        domain=domain,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        format=format,
        reliability_prior=reliability_prior,
    )
    session.add(row)
    session.flush()
    return row


def get_source(session: Session, source_id: str) -> HistoricalSource | None:
    stmt = select(HistoricalSource).where(HistoricalSource.source_id == source_id)
    return session.execute(stmt).scalar_one_or_none()
