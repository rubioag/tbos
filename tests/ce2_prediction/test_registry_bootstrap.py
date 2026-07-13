from sqlalchemy.orm import Session

from tbos.ce2_prediction.registry_bootstrap import register_all_base_models
from tbos.inf1_config.taxonomy import ModelLifecycleStatus


def test_registers_exactly_five_base_models(session: Session) -> None:
    entries = register_all_base_models(session)
    session.commit()
    assert len(entries) == 5
    assert {e.model_id for e in entries} == {
        "serve_model", "return_model", "surface_model", "form_fatigue_model", "matchup_model",
    }


def test_all_registered_models_start_proposed(session: Session) -> None:
    entries = register_all_base_models(session)
    session.commit()
    assert all(e.lifecycle_status == ModelLifecycleStatus.PROPOSED for e in entries)


def test_required_fields_persisted_correctly(session: Session) -> None:
    entries = register_all_base_models(session)
    session.commit()
    serve_entry = next(e for e in entries if e.model_id == "serve_model")
    assert "player_a_profile.hold_rate_by_surface" in serve_entry.required_fields
