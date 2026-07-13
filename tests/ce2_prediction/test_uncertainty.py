from datetime import datetime, timedelta, timezone

from tbos.ce1_data.envelope import FieldEnvelope, FreshnessInfo
from tbos.ce2_prediction.ensemble import EnsembleOutput, ModelContribution
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.uncertainty import UncertaintyResult, compute_uncertainty
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, FreshnessStatus, InformationReliability

from tests.ce2_prediction.factories import make_bundle, make_profile

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fully_abstained() -> EnsembleOutput:
    return EnsembleOutput(
        match_id="m", fully_abstained=True, log_odds=None, probability_player_a=None,
        participating=[], abstained=[], disagreement=None, ensemble_version="1.0.0",
    )


def _ensemble_output(
    *, own_uncertainties: list[float], weights: list[float] | None = None, disagreement: float = 0.1
) -> EnsembleOutput:
    n = len(own_uncertainties)
    weights = weights or [1.0 / n] * n
    participating = [
        ModelContribution(
            model_id=f"model_{i}", domain=f"domain_{i}", weight=weights[i], mapped_log_odds=0.0,
            own_uncertainty=own_uncertainties[i], own_evidence_quality=0.7,
        )
        for i in range(n)
    ]
    return EnsembleOutput(
        match_id="m", fully_abstained=False, log_odds=0.2, probability_player_a=0.55,
        participating=participating, abstained=[], disagreement=disagreement, ensemble_version="1.0.0",
    )


def test_fully_abstained_ensemble_yields_maximum_uncertainty() -> None:
    result = compute_uncertainty(_fully_abstained(), total_registered_models=5)
    assert result.final_uncertainty == 1.0
    assert result.components.participating_count == 0


def test_final_uncertainty_always_bounded_zero_to_one() -> None:
    result = compute_uncertainty(
        _ensemble_output(own_uncertainties=[1.0, 1.0], disagreement=10.0), total_registered_models=2
    )
    assert 0.0 <= result.final_uncertainty <= 1.0


def test_own_uncertainty_weighted_average_matches_manual_computation() -> None:
    result = compute_uncertainty(
        _ensemble_output(own_uncertainties=[0.2, 0.8], weights=[0.75, 0.25], disagreement=0.0),
        total_registered_models=2,
    )
    assert result.components.avg_own_uncertainty == 0.75 * 0.2 + 0.25 * 0.8


def test_lower_quorum_increases_uncertainty_holding_everything_else_constant() -> None:
    full_quorum = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2, 0.2, 0.2, 0.2, 0.2]), total_registered_models=5)
    low_quorum = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2]), total_registered_models=5)
    assert low_quorum.components.quorum_penalty > full_quorum.components.quorum_penalty
    assert low_quorum.final_uncertainty > full_quorum.final_uncertainty


def test_full_quorum_has_zero_quorum_penalty() -> None:
    result = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2] * 5), total_registered_models=5)
    assert result.components.quorum_penalty == 0.0


def test_higher_disagreement_increases_final_uncertainty() -> None:
    low_disagreement = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2, 0.2], disagreement=0.0), total_registered_models=2)
    high_disagreement = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2, 0.2], disagreement=0.9), total_registered_models=2)
    assert high_disagreement.final_uncertainty > low_disagreement.final_uncertainty


def test_uncertainty_never_reads_probability() -> None:
    """Structural guard: UncertaintyResult has no probability-named field
    anywhere — Uncertainty Aggregator only ever reads it as an opaque
    upstream fact it must not touch or reflect back.
    """
    assert "probability" not in UncertaintyResult.model_fields
    assert "probability" not in UncertaintyResult.model_json_schema()["$defs"]["UncertaintyComponents"]["properties"]


def _stale_freshness() -> FreshnessInfo:
    return FreshnessInfo(
        collected_at=NOW - timedelta(days=30), age_seconds=30 * 86400, threshold_seconds=60,
        status=FreshnessStatus.STALE,
    )


def _fresh_freshness() -> FreshnessInfo:
    return FreshnessInfo(collected_at=NOW, age_seconds=1.0, threshold_seconds=60, status=FreshnessStatus.FRESH)


def _env_with_freshness(value: object, freshness: FreshnessInfo) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT, freshness=freshness,
    )


def test_all_stale_bundle_has_higher_freshness_penalty_than_all_fresh() -> None:
    stale_profile = make_profile("p1")
    stale_profile.ranking = _env_with_freshness(10, _stale_freshness())

    fresh_profile = make_profile("p1")
    fresh_profile.ranking = _env_with_freshness(10, _fresh_freshness())

    stale_bundle = make_bundle(player_a_profile=stale_profile)
    fresh_bundle = make_bundle(player_a_profile=fresh_profile)

    ensemble = _ensemble_output(own_uncertainties=[0.2])
    stale_result = compute_uncertainty(ensemble, total_registered_models=1, bundle=stale_bundle)
    fresh_result = compute_uncertainty(ensemble, total_registered_models=1, bundle=fresh_bundle)

    assert stale_result.components.freshness_penalty > fresh_result.components.freshness_penalty
    assert stale_result.final_uncertainty > fresh_result.final_uncertainty


def test_no_bundle_provided_yields_zero_freshness_penalty() -> None:
    result = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2]), total_registered_models=1, bundle=None)
    assert result.components.freshness_penalty == 0.0


def test_bundle_fields_without_freshness_info_dont_count_as_stale() -> None:
    bundle = make_bundle()  # factories.env() sets freshness=None everywhere
    result = compute_uncertainty(_ensemble_output(own_uncertainties=[0.2]), total_registered_models=1, bundle=bundle)
    assert result.components.freshness_penalty == 0.0
