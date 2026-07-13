"""CE.3 — EdgeDescription storage. Append-only, same discipline as every
other published artifact in TBOS.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class EdgeDescriptionRow(Base):
    __tablename__ = "edge_descriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    edge_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    instrument_type: Mapped[str] = mapped_column(String(20))
    book_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(EdgeDescriptionRow, "before_update", forbid_mutation)
event.listen(EdgeDescriptionRow, "before_delete", forbid_mutation)
