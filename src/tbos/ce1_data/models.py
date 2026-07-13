"""CE.1 — Snapshot storage. Append-only, same immutability discipline as
INF.1's ConfigVersion. A correction never mutates a prior Snapshot; it
publishes a new one with `supersedes` pointing at the old snapshot_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class SnapshotStatus:
    PUBLISHED = "PUBLISHED"


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(255), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    config_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    fields: Mapped[dict] = mapped_column(_JSONVariant)
    status: Mapped[str] = mapped_column(String(20), default=SnapshotStatus.PUBLISHED)
    supersedes: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)

    # Historical reconstruction support (Historical Data Pipeline spec §B):
    reconstructed: Mapped[bool] = mapped_column(default=False)
    as_of_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


event.listen(Snapshot, "before_update", forbid_mutation)
event.listen(Snapshot, "before_delete", forbid_mutation)
