"""SQLAlchemy 2.0 ORM models for INF.1.

Both tables are append-only. `config_versions` and `model_lifecycle_events`
must never be UPDATEd or DELETEd — enforced here at the ORM event-listener
level (raises hard) and should additionally be enforced with a DB-level
trigger/REVOKE UPDATE,DELETE in the Alembic migration before production.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tbos.db import Base
from tbos.inf1_config.taxonomy import ModelLifecycleStatus, ValidationStatus

# JSON on SQLite (tests), JSONB on PostgreSQL (production) — same logical type.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ImmutableRecordError(RuntimeError):
    """Raised when code attempts to UPDATE or DELETE an append-only row."""


def _forbid_mutation(mapper: object, connection: object, target: object) -> None:
    raise ImmutableRecordError(
        f"{type(target).__name__} is append-only; UPDATE/DELETE is not permitted. "
        "Publish a new version instead."
    )


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    # Physical PK is a plain autoincrement int — the reliable, portable
    # ordering key (SQLite and PostgreSQL both autoincrement a sole integer
    # PK natively). created_at has insufficient resolution under rapid
    # successive publishes to be used for "latest" ordering on its own.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by: Mapped[str] = mapped_column(String(255))
    bundle: Mapped[dict] = mapped_column(_JSONVariant)


event.listen(ConfigVersion, "before_update", _forbid_mutation)
event.listen(ConfigVersion, "before_delete", _forbid_mutation)


class ModelRegistryEntry(Base):
    """One row per (model_id, version). `lifecycle_status` here reflects the
    *current* known status; the authoritative append-only history lives in
    ModelLifecycleEvent. Updating lifecycle_status is done exclusively via
    repository.transition_model_lifecycle(), never by direct ORM mutation.
    """

    __tablename__ = "model_registry_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(String(100), index=True)
    domain: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    owner: Mapped[str] = mapped_column(String(255))
    required_fields: Mapped[list] = mapped_column(_JSONVariant)
    optional_fields: Mapped[list] = mapped_column(_JSONVariant)
    output_schema_compliance: Mapped[bool] = mapped_column(default=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus, native_enum=False, length=20), default=ValidationStatus.PENDING
    )
    lifecycle_status: Mapped[ModelLifecycleStatus] = mapped_column(
        Enum(ModelLifecycleStatus, native_enum=False, length=20),
        default=ModelLifecycleStatus.PROPOSED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lifecycle_events: Mapped[list["ModelLifecycleEvent"]] = relationship(
        back_populates="entry", order_by="ModelLifecycleEvent.timestamp"
    )


class ModelLifecycleEvent(Base):
    __tablename__ = "model_lifecycle_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_registry_entries.id"), index=True)
    from_status: Mapped[ModelLifecycleStatus | None] = mapped_column(
        Enum(ModelLifecycleStatus, native_enum=False, length=20), nullable=True
    )
    to_status: Mapped[ModelLifecycleStatus] = mapped_column(
        Enum(ModelLifecycleStatus, native_enum=False, length=20)
    )
    reason: Mapped[str] = mapped_column(String(1000))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entry: Mapped[ModelRegistryEntry] = relationship(back_populates="lifecycle_events")


event.listen(ModelLifecycleEvent, "before_update", _forbid_mutation)
event.listen(ModelLifecycleEvent, "before_delete", _forbid_mutation)
