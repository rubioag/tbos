from tbos.ce2_prediction.abstention_policy import evaluate_abstention
from tbos.ce2_prediction.ensemble import EnsembleOutput, ModelContribution
from tbos.ce2_prediction.evidence_quality import EvidenceQualityComponents, EvidenceQualityResult
from tbos.ce2_prediction.uncertainty import UncertaintyComponents, UncertaintyResult
from tbos.inf1_config.schemas import EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag

CONFIG = EnsembleConfig()  # defaults: quorum_min=2, quorum_comfortable=4, eq_floor=0.3, eq_comfortable=0.6, unc_ceiling=0.35, disagreement_malfunction=5.0


def _fully_abstained_ensemble() -> EnsembleOutput:
    return EnsembleOutput(
        match_id="m", fully_abstained=True, log_odds=None, probability_player_a=None,
        participating=[], abstained=[], disagreement=None, ensemble_version="1.0.0",
    )


def _ensemble(n_participating: int, disagreement: float = 0.1) -> EnsembleOutput:
    participating = [
        ModelContribution(model_id=f"m{i}", domain=f"d{i}", weight=1.0 / n_participating, mapped_log_odds=0.1, own_uncertainty=0.2, own_evidence_quality=0.7)
        for i in range(n_participating)
    ]
    return EnsembleOutput(
        match_id="m", fully_abstained=False, log_odds=0.1, probability_player_a=0.52,
        participating=participating, abstained=[], disagreement=disagreement, ensemble_version="1.0.0",
    )


def _uncertainty(value: float) -> UncertaintyResult:
    return UncertaintyResult(
        final_uncertainty=value,
        components=UncertaintyComponents(
            avg_own_uncertainty=value, disagreement_component=0.1, quorum_penalty=0.0,
            freshness_penalty=0.0, participating_count=2, total_registered_models=5,
        ),
    )


def _evidence_quality(value: float, *, field_availability_rate: float = 1.0) -> EvidenceQualityResult:
    return EvidenceQualityResult(
        final_evidence_quality=value,
        components=EvidenceQualityComponents(
            avg_own_evidence_quality=value, field_availability_rate=field_availability_rate,
            source_reliability_avg=0.5, provenance_completeness_rate=0.5, freshness_validity_rate=0.5,
            conflict_rate=0.0, il1_signal_quality=0.0,
        ),
    )


def test_fully_abstained_ensemble_is_abstained() -> None:
    decision = evaluate_abstention(_fully_abstained_ensemble(), _uncertainty(1.0), _evidence_quality(0.0), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "no_usable_model_votes" in decision.triggered_rules


def test_quorum_below_absolute_minimum_is_abstained() -> None:
    decision = evaluate_abstention(_ensemble(1), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "quorum_below_absolute_minimum" in decision.triggered_rules


def test_zero_field_availability_is_abstained() -> None:
    decision = evaluate_abstention(_ensemble(3), _uncertainty(0.2), _evidence_quality(0.7, field_availability_rate=0.0), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "zero_field_availability" in decision.triggered_rules


def test_malfunction_disagreement_is_abstained() -> None:
    decision = evaluate_abstention(_ensemble(3, disagreement=10.0), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "disagreement_malfunction_pattern" in decision.triggered_rules


def test_genuine_uncertain_match_with_sane_disagreement_is_not_abstained_for_that_alone() -> None:
    """A real 50/50 match should show meaningful disagreement/uncertainty
    and still be a valid, publishable (if degraded) output — never treated
    as a malfunction just for being genuinely close.
    """
    decision = evaluate_abstention(_ensemble(3, disagreement=0.3), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag != ConfidenceFlag.ABSTAINED


def test_evidence_quality_below_floor_is_abstained() -> None:
    decision = evaluate_abstention(_ensemble(3), _uncertainty(0.2), _evidence_quality(0.1), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "evidence_quality_below_floor" in decision.triggered_rules


def test_quorum_below_comfortable_but_above_minimum_is_degraded() -> None:
    decision = evaluate_abstention(_ensemble(3), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.DEGRADED
    assert "quorum_below_comfortable" in decision.triggered_rules


def test_evidence_quality_below_comfortable_but_above_floor_is_degraded() -> None:
    decision = evaluate_abstention(_ensemble(4), _uncertainty(0.2), _evidence_quality(0.45), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.DEGRADED
    assert "evidence_quality_below_comfortable" in decision.triggered_rules


def test_uncertainty_above_ceiling_is_degraded() -> None:
    decision = evaluate_abstention(_ensemble(4), _uncertainty(0.5), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.DEGRADED
    assert "uncertainty_above_ceiling" in decision.triggered_rules


def test_all_conditions_comfortable_is_normal() -> None:
    decision = evaluate_abstention(_ensemble(4), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.NORMAL
    assert decision.triggered_rules == []


def test_reasoning_includes_actual_values_and_thresholds_compared() -> None:
    decision = evaluate_abstention(_ensemble(4), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.reasoning["participating_count"] == 4
    assert decision.reasoning["quorum_minimum_absolute"] == CONFIG.quorum_minimum_absolute
    assert decision.reasoning["final_evidence_quality"] == 0.7


def test_hard_abstain_takes_priority_over_degraded_conditions() -> None:
    """Low quorum alone would be degraded, but combined with a malfunction
    disagreement it must escalate to full abstention, not degraded.
    """
    decision = evaluate_abstention(_ensemble(1, disagreement=10.0), _uncertainty(0.2), _evidence_quality(0.7), config=CONFIG, total_registered_models=5)
    assert decision.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "quorum_below_absolute_minimum" in decision.triggered_rules
    assert "disagreement_malfunction_pattern" in decision.triggered_rules
