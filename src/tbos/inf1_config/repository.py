"""Repository for INF.1 — the only code path allowed to write config/model
registry rows. Enforces: append-only config versions, valid lifecycle
transitions, and "only one ACTIVE version per model_id" (Model Registry §5).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.inf1_config.models import ConfigVersion, ModelLifecycleEvent, ModelRegistryEntry
from tbos.inf1_config.schemas import ConfigVersionBundle, ModelRegistryEntryCreate
from tbos.inf1_config.taxonomy import ModelLifecycleStatus, ValidationStatus

_ALLOWED_TRANSITIONS: dict[ModelLifecycleStatus, set[ModelLifecycleStatus]] = {
    ModelLifecycleStatus.PROPOSED: {ModelLifecycleStatus.VALIDATED},
    ModelLifecycleStatus.VALIDATED: {ModelLifecycleStatus.ACTIVE, ModelLifecycleStatus.DEPRECATED},
    ModelLifecycleStatus.ACTIVE: {ModelLifecycleStatus.DEPRECATED},
    ModelLifecycleStatus.DEPRECATED: {ModelLifecycleStatus.RETIRED},
    ModelLifecycleStatus.RETIRED: set(),
}


class InvalidLifecycleTransition(RuntimeError):
    pass


class ModelNotValidated(RuntimeError):
    pass


class DuplicateActiveModel(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Config Registry
# ---------------------------------------------------------------------------


def publish_config_version(
    session: Session, bundle: ConfigVersionBundle, approved_by: str
) -> ConfigVersion:
    """Always creates a brand new immutable row. Never updates a prior one."""
    row = ConfigVersion(bundle=bundle.model_dump(mode="json"), approved_by=approved_by)
    session.add(row)
    session.flush()
    return row


def get_config_version(session: Session, config_version_id: uuid.UUID) -> ConfigVersion | None:
    stmt = select(ConfigVersion).where(ConfigVersion.config_version_id == config_version_id)
    return session.execute(stmt).scalar_one_or_none()


def get_latest_config_version(session: Session) -> ConfigVersion | None:
    # Ordered by the autoincrement PK, not created_at — timestamp resolution
    # is not reliable for ordering under rapid successive publishes.
    stmt = select(ConfigVersion).order_by(ConfigVersion.id.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------


def register_model(session: Session, entry: ModelRegistryEntryCreate) -> ModelRegistryEntry:
    row = ModelRegistryEntry(
        model_id=entry.model_id,
        domain=entry.domain,
        version=entry.version,
        owner=entry.owner,
        required_fields=entry.required_fields,
        optional_fields=entry.optional_fields,
        validation_status=ValidationStatus.PENDING,
        lifecycle_status=ModelLifecycleStatus.PROPOSED,
    )
    session.add(row)
    session.flush()
    return row


def record_validation_result(
    session: Session, entry_id: uuid.UUID, *, passed: bool, schema_compliant: bool
) -> ModelRegistryEntry:
    entry = session.get(ModelRegistryEntry, entry_id)
    if entry is None:
        raise ValueError(f"unknown model registry entry {entry_id}")
    entry.validation_status = ValidationStatus.PASS if passed else ValidationStatus.FAIL
    entry.output_schema_compliance = schema_compliant
    session.flush()
    return entry


def transition_model_lifecycle(
    session: Session, entry_id: uuid.UUID, to_status: ModelLifecycleStatus, reason: str
) -> ModelRegistryEntry:
    entry = session.get(ModelRegistryEntry, entry_id)
    if entry is None:
        raise ValueError(f"unknown model registry entry {entry_id}")

    current = ModelLifecycleStatus(entry.lifecycle_status)
    if to_status not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransition(f"{current} -> {to_status} is not a valid transition")

    if to_status == ModelLifecycleStatus.VALIDATED and entry.validation_status != ValidationStatus.PASS:
        raise ModelNotValidated(
            f"model {entry.model_id} v{entry.version} has not passed the compatibility battery"
        )

    if to_status == ModelLifecycleStatus.ACTIVE:
        existing_active = session.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.model_id == entry.model_id,
                ModelRegistryEntry.lifecycle_status == ModelLifecycleStatus.ACTIVE,
                ModelRegistryEntry.id != entry.id,
            )
        ).scalar_one_or_none()
        if existing_active is not None:
            raise DuplicateActiveModel(
                f"model_id={entry.model_id} already has an ACTIVE version ({existing_active.version})"
            )

    session.add(
        ModelLifecycleEvent(
            entry_id=entry.id, from_status=current, to_status=to_status, reason=reason
        )
    )
    entry.lifecycle_status = to_status
    session.flush()
    return entry


def get_active_model(session: Session, model_id: str) -> ModelRegistryEntry | None:
    stmt = select(ModelRegistryEntry).where(
        ModelRegistryEntry.model_id == model_id,
        ModelRegistryEntry.lifecycle_status == ModelLifecycleStatus.ACTIVE,
    )
    return session.execute(stmt).scalar_one_or_none()


def list_active_models(session: Session) -> list[ModelRegistryEntry]:
    stmt = select(ModelRegistryEntry).where(
        ModelRegistryEntry.lifecycle_status == ModelLifecycleStatus.ACTIVE
    )
    return list(session.execute(stmt).scalars().all())
