"""Historical Data Pipeline §F — Pipeline Versioning. Every extraction run
is a new immutable, permanently-retained version — same append-only
discipline as INF.1's ConfigVersion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, Uuid, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class HistoricalDatasetVersion(Base):
    __tablename__ = "historical_dataset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )
    source_versions: Mapped[dict] = mapped_column(_JSONVariant)  # {source_id: version}
    extraction_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    config_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))


event.listen(HistoricalDatasetVersion, "before_update", forbid_mutation)
event.listen(HistoricalDatasetVersion, "before_delete", forbid_mutation)


def publish_dataset_version(
    session: Session, *, source_versions: dict[str, str], config_version_id: uuid.UUID
) -> HistoricalDatasetVersion:
    row = HistoricalDatasetVersion(source_versions=source_versions, config_version_id=config_version_id)
    session.add(row)
    session.flush()
    return row


def get_dataset_version(session: Session, dataset_version_id: uuid.UUID) -> HistoricalDatasetVersion | None:
    stmt = select(HistoricalDatasetVersion).where(
        HistoricalDatasetVersion.dataset_version_id == dataset_version_id
    )
    return session.execute(stmt).scalar_one_or_none()


def get_latest_dataset_version(session: Session) -> HistoricalDatasetVersion | None:
    stmt = select(HistoricalDatasetVersion).order_by(HistoricalDatasetVersion.id.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()
