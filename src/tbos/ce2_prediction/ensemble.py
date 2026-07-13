"""CE.2.5 — Ensemble Aggregator.

The only place in TBOS authorized to translate domain estimates into a
probability (Probability-First Principle). Combines participating Models'
log-odds contributions via a weighted average in log-odds space, then
converts back to a probability at the very end.

Deferred to a later phase (documented, not stubbed): correlation-aware
weight discounting (spec §6) needs a historical correlation matrix that
only IL.3 Edge Attribution can supply, and IL.3 doesn't exist yet. Models
are treated as independent for v1 — which is also true by construction,
since Serve/Return/Surface/Form/Matchup were each explicitly scoped to
minimize domain overlap. Weighting uses only `own_evidence_quality` for
the same reason: calibration-by-situation history (INF.3/IL.3) isn't wired
into a queryable form yet.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce2_prediction.contract import ModelOutput
from tbos.ce2_prediction.domain_mapping import UnknownDomainError, map_to_log_odds, sigmoid
from tbos.inf1_config.taxonomy import ExecutionMode

ENSEMBLE_VERSION = "1.0.0"


class ModelContribution(BaseModel):
    model_id: str
    domain: str
    weight: float
    mapped_log_odds: float
    own_uncertainty: float
    own_evidence_quality: float


class AbstainedModel(BaseModel):
    model_id: str
    domain: str
    reason: str


class EnsembleOutput(BaseModel):
    match_id: str
    fully_abstained: bool
    log_odds: float | None
    probability_player_a: float | None
    participating: list[ModelContribution]
    abstained: list[AbstainedModel]
    disagreement: float | None
    ensemble_version: str


def _fully_abstained_output(match_id: str, abstained: list[AbstainedModel]) -> EnsembleOutput:
    return EnsembleOutput(
        match_id=match_id, fully_abstained=True, log_odds=None, probability_player_a=None,
        participating=[], abstained=abstained, disagreement=None, ensemble_version=ENSEMBLE_VERSION,
    )


def combine_models(match_id: str, outputs: list[ModelOutput]) -> EnsembleOutput:
    abstained: list[AbstainedModel] = []
    contributions: list[tuple[str, str, float, float, float, float]] = []

    for out in outputs:
        if out.execution_mode != ExecutionMode.LIVE:
            # Structural rejection, not a convention: a SHADOW/BACKTEST
            # output is schema-ineligible for real combination, per CE.2.8.
            abstained.append(
                AbstainedModel(
                    model_id=out.model_id, domain=out.domain,
                    reason=f"execution_mode={out.execution_mode.value} is not eligible for live combination",
                )
            )
            continue
        if out.abstained:
            abstained.append(
                AbstainedModel(model_id=out.model_id, domain=out.domain, reason=out.abstain_reason or "unspecified")
            )
            continue
        try:
            log_odds = map_to_log_odds(out.domain, out.estimate)
        except UnknownDomainError as exc:
            abstained.append(AbstainedModel(model_id=out.model_id, domain=out.domain, reason=str(exc)))
            continue

        weight = out.own_evidence_quality
        contributions.append((out.model_id, out.domain, weight, log_odds, out.own_uncertainty, out.own_evidence_quality))

    if not contributions:
        return _fully_abstained_output(match_id, abstained)

    total_weight = sum(w for _, _, w, _, _, _ in contributions)
    if total_weight <= 0:
        # Every participating Model reported zero evidence_quality — there
        # is nothing meaningful to weight by; treat as no usable votes.
        return _fully_abstained_output(match_id, abstained)

    normalized = [
        (model_id, domain, weight / total_weight, log_odds, own_unc, own_eq)
        for model_id, domain, weight, log_odds, own_unc, own_eq in contributions
    ]

    final_log_odds = sum(w * lo for _, _, w, lo, _, _ in normalized)
    probability = sigmoid(final_log_odds)
    disagreement = sum(w * (lo - final_log_odds) ** 2 for _, _, w, lo, _, _ in normalized) ** 0.5

    participating = [
        ModelContribution(
            model_id=model_id, domain=domain, weight=weight, mapped_log_odds=log_odds,
            own_uncertainty=own_unc, own_evidence_quality=own_eq,
        )
        for model_id, domain, weight, log_odds, own_unc, own_eq in normalized
    ]

    return EnsembleOutput(
        match_id=match_id, fully_abstained=False, log_odds=final_log_odds,
        probability_player_a=probability, participating=participating, abstained=abstained,
        disagreement=disagreement, ensemble_version=ENSEMBLE_VERSION,
    )
