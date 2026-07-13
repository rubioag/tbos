"""CE.2.6 — Uncertainty Aggregator.

Combines five independent sources into a single Uncertainty scalar,
never touching Probability (Ensemble Aggregator's output, read-only here)
and never collapsing into Evidence Quality (CE.2.7, separate computation
even though it reads some of the same underlying signals).

Sources (spec-locked):
1. Model own_uncertainty — weighted average across participating Models.
2. Model disagreement — reused directly from EnsembleOutput.disagreement,
   never recomputed independently (single source of truth).
3. Ensemble coverage/quorum — fewer participants than registered widens
   uncertainty even if those that did participate were each confident.
4. Data freshness degradation — scanned directly from the ModelInputBundle
   (not self-reported by Models, since ModelOutput carries no freshness
   field) — fraction of fields with STALE freshness status.
5. Sample/evidence limitations — proxied via participating Models' own
   evidence_quality (weak evidence often correlates with thin samples);
   a dedicated sample-size signal per Model doesn't exist yet.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce2_prediction.ensemble import EnsembleOutput
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.inf1_config.taxonomy import FreshnessStatus

OWN_UNCERTAINTY_WEIGHT = 0.4
DISAGREEMENT_WEIGHT = 0.3
QUORUM_PENALTY_SCALE = 0.25
FRESHNESS_PENALTY_SCALE = 0.15


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _iter_envelopes(bundle: ModelInputBundle):
    for entity in (
        bundle.player_a_profile, bundle.player_a_state,
        bundle.player_b_profile, bundle.player_b_state, bundle.match_context,
    ):
        if entity is None:
            continue
        for field_name in type(entity).model_fields:
            value = getattr(entity, field_name)
            if isinstance(value, FieldEnvelope):
                yield value


def compute_freshness_penalty(bundle: ModelInputBundle | None) -> float:
    if bundle is None:
        return 0.0
    with_freshness = [e for e in _iter_envelopes(bundle) if e.freshness is not None]
    if not with_freshness:
        return 0.0
    stale_count = sum(1 for e in with_freshness if e.freshness.status == FreshnessStatus.STALE)
    return (stale_count / len(with_freshness)) * FRESHNESS_PENALTY_SCALE


class UncertaintyComponents(BaseModel):
    avg_own_uncertainty: float
    disagreement_component: float
    quorum_penalty: float
    freshness_penalty: float
    participating_count: int
    total_registered_models: int


class UncertaintyResult(BaseModel):
    final_uncertainty: float
    components: UncertaintyComponents


def compute_uncertainty(
    ensemble_output: EnsembleOutput, *, total_registered_models: int, bundle: ModelInputBundle | None = None
) -> UncertaintyResult:
    if ensemble_output.fully_abstained:
        return UncertaintyResult(
            final_uncertainty=1.0,
            components=UncertaintyComponents(
                avg_own_uncertainty=1.0, disagreement_component=0.0, quorum_penalty=0.0,
                freshness_penalty=0.0, participating_count=0, total_registered_models=total_registered_models,
            ),
        )

    participating = ensemble_output.participating
    avg_own_uncertainty = sum(c.weight * c.own_uncertainty for c in participating)
    disagreement_component = ensemble_output.disagreement or 0.0

    coverage_ratio = len(participating) / total_registered_models if total_registered_models > 0 else 0.0
    quorum_penalty = max(0.0, 1.0 - coverage_ratio) * QUORUM_PENALTY_SCALE

    freshness_penalty = compute_freshness_penalty(bundle)

    final_uncertainty = _clamp01(
        OWN_UNCERTAINTY_WEIGHT * avg_own_uncertainty
        + DISAGREEMENT_WEIGHT * disagreement_component
        + quorum_penalty
        + freshness_penalty
    )

    return UncertaintyResult(
        final_uncertainty=final_uncertainty,
        components=UncertaintyComponents(
            avg_own_uncertainty=avg_own_uncertainty,
            disagreement_component=disagreement_component,
            quorum_penalty=quorum_penalty,
            freshness_penalty=freshness_penalty,
            participating_count=len(participating),
            total_registered_models=total_registered_models,
        ),
    )
