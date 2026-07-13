"""INF.2 — Event Store. Append-only. `id` is the physical autoincrement PK
and doubles as the global Event Timeline index (spec §D) — a single
monotonic ordering across every bet, with no separate table needed.
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


class Event(Base):
    __tablename__ = "events"

    # This IS the Event Timeline index — global, monotonic, gap-free.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )
    bet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(Event, "before_update", forbid_mutation)
event.listen(Event, "before_delete", forbid_mutation)
