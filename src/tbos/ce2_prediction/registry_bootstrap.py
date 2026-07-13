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
from tbos.inf1_config import repository as inf1_repository
from tbos.inf1_config.models import ModelRegistryEntry
from tbos.inf1_config.schemas import ModelRegistryEntryCreate

BASE_MODEL_CLASSES: list[type[Model]] = [
    ServeModel, ReturnModel, SurfaceModel, FormFatigueModel, MatchupModel,
]


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
