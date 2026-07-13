"""CE.2.9 — Abstention Policy.

Reads Probability (via EnsembleOutput), Uncertainty, and Evidence Quality
as already-computed, independent facts — never recomputes or adjusts any
of them, only decides NORMAL / DEGRADED / ABSTAINED (spec §9).

Hard-abstain conditions (any one triggers, publish nothing):
1. Quorum below the absolute minimum.
2. Zero field availability — no usable evidence exists at all.
3. Disagreement beyond the malfunction-pattern threshold (distinguishes a
   genuinely uncertain 50/50 match, which is valid honest output, from an
   internal inconsistency signaling a bug or data corruption).
4. Evidence Quality below its own hard floor.

Degraded conditions (checked only if no hard trigger fired): quorum below
the comfortable threshold, Evidence Quality below the comfortable
threshold, or Uncertainty above its configured ceiling. High disagreement
alone is deliberately not a separate degraded trigger here — it already
propagates into Uncertainty via DISAGREEMENT_WEIGHT (CE.2.6), so checking
Uncertainty's ceiling already covers it without double-counting.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce2_prediction.ensemble import EnsembleOutput
from tbos.ce2_prediction.evidence_quality import EvidenceQualityResult
from tbos.ce2_prediction.uncertainty import UncertaintyResult
from tbos.inf1_config.schemas import EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag


class AbstentionDecision(BaseModel):
    confidence_flag: ConfidenceFlag
    triggered_rules: list[str]
    reasoning: dict[str, float | int]


def evaluate_abstention(
    ensemble_output: EnsembleOutput,
    uncertainty_result: UncertaintyResult,
    evidence_quality_result: EvidenceQualityResult,
    *,
    config: EnsembleConfig,
    total_registered_models: int,
) -> AbstentionDecision:
    if ensemble_output.fully_abstained:
        return AbstentionDecision(
            confidence_flag=ConfidenceFlag.ABSTAINED,
            triggered_rules=["no_usable_model_votes"],
            reasoning={"participating_count": 0, "total_registered_models": total_registered_models},
        )

    participating_count = len(ensemble_output.participating)
    field_availability_rate = evidence_quality_result.components.field_availability_rate
    disagreement = ensemble_output.disagreement or 0.0

    hard_triggers: list[str] = []
    if participating_count < config.quorum_minimum_absolute:
        hard_triggers.append("quorum_below_absolute_minimum")
    if field_availability_rate == 0.0:
        hard_triggers.append("zero_field_availability")
    if disagreement > config.disagreement_malfunction_threshold:
        hard_triggers.append("disagreement_malfunction_pattern")
    if evidence_quality_result.final_evidence_quality < config.evidence_quality_floor:
        hard_triggers.append("evidence_quality_below_floor")

    reasoning = {
        "participating_count": participating_count,
        "total_registered_models": total_registered_models,
        "field_availability_rate": field_availability_rate,
        "disagreement": disagreement,
        "final_evidence_quality": evidence_quality_result.final_evidence_quality,
        "final_uncertainty": uncertainty_result.final_uncertainty,
        "quorum_minimum_absolute": config.quorum_minimum_absolute,
        "quorum_comfortable": config.quorum_comfortable,
        "evidence_quality_floor": config.evidence_quality_floor,
        "evidence_quality_comfortable": config.evidence_quality_comfortable,
        "uncertainty_ceiling_degraded": config.uncertainty_ceiling_degraded,
        "disagreement_malfunction_threshold": config.disagreement_malfunction_threshold,
    }

    if hard_triggers:
        return AbstentionDecision(confidence_flag=ConfidenceFlag.ABSTAINED, triggered_rules=hard_triggers, reasoning=reasoning)

    degraded_triggers: list[str] = []
    if participating_count < config.quorum_comfortable:
        degraded_triggers.append("quorum_below_comfortable")
    if evidence_quality_result.final_evidence_quality < config.evidence_quality_comfortable:
        degraded_triggers.append("evidence_quality_below_comfortable")
    if uncertainty_result.final_uncertainty > config.uncertainty_ceiling_degraded:
        degraded_triggers.append("uncertainty_above_ceiling")

    if degraded_triggers:
        return AbstentionDecision(confidence_flag=ConfidenceFlag.DEGRADED, triggered_rules=degraded_triggers, reasoning=reasoning)

    return AbstentionDecision(confidence_flag=ConfidenceFlag.NORMAL, triggered_rules=[], reasoning=reasoning)
