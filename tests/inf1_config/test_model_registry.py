import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config import repository
from tbos.inf1_config.schemas import ModelRegistryEntryCreate
from tbos.inf1_config.taxonomy import ModelLifecycleStatus


def _register(session: Session, model_id: str = "serve_model", version: str = "1.0.0"):
    return repository.register_model(
        session,
        ModelRegistryEntryCreate(
            model_id=model_id,
            domain="serve",
            version=version,
            owner="quant-team",
            required_fields=["player_a.serve_stats.first_serve_pct"],
        ),
    )


def test_new_model_starts_as_proposed(session: Session) -> None:
    entry = _register(session)
    session.commit()
    assert entry.lifecycle_status == ModelLifecycleStatus.PROPOSED
    assert entry.validation_status.value == "PENDING"


def test_cannot_validate_without_passing_battery(session: Session) -> None:
    entry = _register(session)
    session.commit()

    with pytest.raises(repository.ModelNotValidated):
        repository.transition_model_lifecycle(
            session, entry.id, ModelLifecycleStatus.VALIDATED, reason="attempt without validation"
        )


def test_full_promotion_path_proposed_to_active(session: Session) -> None:
    entry = _register(session)
    session.commit()

    repository.record_validation_result(session, entry.id, passed=True, schema_compliant=True)
    repository.transition_model_lifecycle(
        session, entry.id, ModelLifecycleStatus.VALIDATED, reason="passed compatibility battery"
    )
    repository.transition_model_lifecycle(
        session, entry.id, ModelLifecycleStatus.ACTIVE, reason="shadow metrics acceptable, human approved"
    )
    session.commit()

    assert repository.get_active_model(session, "serve_model").version == "1.0.0"


def test_invalid_transition_rejected(session: Session) -> None:
    entry = _register(session)
    session.commit()

    with pytest.raises(repository.InvalidLifecycleTransition):
        repository.transition_model_lifecycle(
            session, entry.id, ModelLifecycleStatus.ACTIVE, reason="skip validation"
        )


def test_only_one_active_version_per_model_id(session: Session) -> None:
    v1 = _register(session, version="1.0.0")
    session.commit()
    repository.record_validation_result(session, v1.id, passed=True, schema_compliant=True)
    repository.transition_model_lifecycle(session, v1.id, ModelLifecycleStatus.VALIDATED, reason="ok")
    repository.transition_model_lifecycle(session, v1.id, ModelLifecycleStatus.ACTIVE, reason="ok")
    session.commit()

    v2 = _register(session, version="2.0.0")
    session.commit()
    repository.record_validation_result(session, v2.id, passed=True, schema_compliant=True)
    repository.transition_model_lifecycle(session, v2.id, ModelLifecycleStatus.VALIDATED, reason="ok")

    with pytest.raises(repository.DuplicateActiveModel):
        repository.transition_model_lifecycle(
            session, v2.id, ModelLifecycleStatus.ACTIVE, reason="promote v2 while v1 still active"
        )


def test_failed_validation_blocks_promotion_forever(session: Session) -> None:
    entry = _register(session)
    session.commit()
    repository.record_validation_result(session, entry.id, passed=False, schema_compliant=False)

    with pytest.raises(repository.ModelNotValidated):
        repository.transition_model_lifecycle(
            session, entry.id, ModelLifecycleStatus.VALIDATED, reason="retry despite failure"
        )
