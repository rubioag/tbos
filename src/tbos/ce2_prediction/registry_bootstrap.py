"""CE.2.8 — registers the five base Models into the INF.1 Model Registry.
Nothing here bypasses INF.1's own rules: every entry starts PROPOSED,
same as any Model would (Registry §4/§5, already locked and tested).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.form_fatigue_model import FormFatigueModel
from tbos.ce2_prediction.matchup_model import MatchupModel
from tbos.ce2_prediction.return_model import ReturnModel
from tbos.ce2_prediction.serve_model import ServeModel
from tbos.ce2_prediction.surface_model import SurfaceModel
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.validation_battery import run_validation_battery
from tbos.inf1_config import repository as inf1_repository
from tbos.inf1_config.models import ModelRegistryEntry
from tbos.inf1_config.schemas import ModelRegistryEntryCreate
from tbos.inf1_config.taxonomy import ModelLifecycleStatus

BASE_MODEL_CLASSES: list[type[Model]] = [
    ServeModel, ReturnModel, SurfaceModel, FormFatigueModel, MatchupModel,
]

MODEL_CLASS_BY_ID: dict[str, type[Model]] = {cls.model_id: cls for cls in BASE_MODEL_CLASSES}


def register_all_base_models(session: Session, *, owner: str = "quant-team") -> list[ModelRegistryEntry]:
    entries = []
    for model_cls in BASE_MODEL_CLASSES:
        entry = inf1_repository.register_model(
            session,
            ModelRegistryEntryCreate(
                model_id=model_cls.model_id,
                domain=model_cls.domain,
                version=model_cls.version,
                owner=owner,
                required_fields=model_cls.required_fields,
                optional_fields=model_cls.optional_fields,
            ),
        )
        entries.append(entry)
    return entries


def bootstrap_and_activate_all(
    session: Session, representative_bundle: ModelInputBundle, *, reviewer_id: str, owner: str = "quant-team"
) -> list[ModelRegistryEntry]:
    """Convenience path for initial system bring-up and test environments:
    register, run the compatibility battery, and promote straight through
    to ACTIVE if it passes. This is a documented shortcut, not a
    replacement for the real production promotion path (Shadow Mode
    evaluation + INF.3 calibration review over real historical data,
    CE.2.8/Backtesting) — appropriate only before that data exists.
    """
    entries = register_all_base_models(session, owner=owner)
    session.commit()

    activated = []
    for entry, model_cls in zip(entries, BASE_MODEL_CLASSES, strict=True):
        battery = run_validation_battery(model_cls, representative_bundle)
        inf1_repository.record_validation_result(
            session, entry.id, passed=battery.overall_pass, schema_compliant=battery.overall_pass
        )
        if not battery.overall_pass:
            continue
        inf1_repository.transition_model_lifecycle(
            session, entry.id, ModelLifecycleStatus.VALIDATED, reason="passed v1 compatibility battery"
        )
        inf1_repository.transition_model_lifecycle(
            session, entry.id, ModelLifecycleStatus.ACTIVE,
            reason=f"v1 bootstrap activation, approved by {reviewer_id}",
        )
        activated.append(entry)
    session.commit()
    return activated
