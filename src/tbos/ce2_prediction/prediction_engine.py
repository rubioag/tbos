"""CE.2.9 — end-to-end integration: the actual `Prediction Engine` entry
point tying together every CE.2 piece built so far:

    CE.1 snapshot -> Model Registry (ACTIVE only) -> 5 Models
    -> Ensemble Aggregator -> Uncertainty Aggregator
    -> Evidence Quality Aggregator -> Abstention Policy -> PredictionOutput

Only Models with lifecycle_status=ACTIVE in the INF.1 Model Registry are
ever invoked — this is the real production gate, not a shortcut taken
here. A Model stuck at PROPOSED/VALIDATED simply doesn't vote.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from tbos.ce2_prediction.abstention_policy import evaluate_abstention
from tbos.ce2_prediction.ensemble import AbstainedModel, combine_models
from tbos.ce2_prediction.evidence_quality import compute_evidence_quality
from tbos.ce2_prediction.input_bundle import load_input_bundle
from tbos.ce2_prediction.registry_bootstrap import MODEL_CLASS_BY_ID
from tbos.ce2_prediction.uncertainty import compute_uncertainty
from tbos.inf1_config import repository as inf1_repository
from tbos.inf1_config.schemas import EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag


class PredictionOutput(BaseModel):
    match_id: str
    confidence_flag: ConfidenceFlag
    probability_player_a: float | None
    log_odds: float | None
    uncertainty: float | None
    evidence_quality: float | None
    participating_models: list[str]
    abstained_models: list[AbstainedModel]
    triggered_abstention_rules: list[str]
    ensemble_version: str


def run_prediction(
    session: Session,
    *,
    match_id: str,
    player_a_id: str,
    player_b_id: str,
    as_of: datetime,
    ensemble_config: EnsembleConfig,
) -> PredictionOutput:
    bundle = load_input_bundle(session, match_id=match_id, player_a_id=player_a_id, player_b_id=player_b_id, as_of=as_of)

    active_entries = inf1_repository.list_active_models(session)
    outputs = [
        MODEL_CLASS_BY_ID[entry.model_id]().estimate(bundle)
        for entry in active_entries
        if entry.model_id in MODEL_CLASS_BY_ID
    ]

    ensemble_output = combine_models(match_id, outputs)
    total_registered = len(active_entries) or 1
    uncertainty_result = compute_uncertainty(ensemble_output, total_registered_models=total_registered, bundle=bundle)
    evidence_quality_result = compute_evidence_quality(ensemble_output, bundle=bundle)

    decision = evaluate_abstention(
        ensemble_output, uncertainty_result, evidence_quality_result,
        config=ensemble_config, total_registered_models=total_registered,
    )

    return PredictionOutput(
        match_id=match_id,
        confidence_flag=decision.confidence_flag,
        probability_player_a=ensemble_output.probability_player_a,
        log_odds=ensemble_output.log_odds,
        uncertainty=uncertainty_result.final_uncertainty,
        evidence_quality=evidence_quality_result.final_evidence_quality,
        participating_models=[c.model_id for c in ensemble_output.participating],
        abstained_models=ensemble_output.abstained,
        triggered_abstention_rules=decision.triggered_rules,
        ensemble_version=ensemble_output.ensemble_version,
    )
