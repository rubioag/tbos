from datetime import datetime, timezone

from tbos.ce1_data.envelope import FieldEnvelope, Provenance, ReliabilityInfo
from tbos.ce2_prediction.ensemble import EnsembleOutput, ModelContribution
from tbos.ce2_prediction.evidence_quality import EvidenceQualityResult, compute_evidence_quality
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, InformationReliability

from tests.ce2_prediction.factories import make_bundle, make_profile

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fully_abstained() -> EnsembleOutput:
    return EnsembleOutput(
        match_id="m", fully_abstained=True, log_odds=None, probability_player_a=None,
        participating=[], abstained=[], disagreement=None, ensemble_version="1.0.0",
    )


def _ensemble_output(*, own_evidence_qualities: list[float], weights: list[float] | None = None) -> EnsembleOutput:
    n = len(own_evidence_qualities)
    weights = weights or [1.0 / n] * n
    participating = [
        ModelContribution(
            model_id=f"model_{i}", domain=f"domain_{i}", weight=weights[i], mapped_log_odds=0.0,
            own_uncertainty=0.3, own_evidence_quality=own_evidence_qualities[i],
        )
        for i in range(n)
    ]
    return EnsembleOutput(
        match_id="m", fully_abstained=False, log_odds=0.2, probability_player_a=0.55,
        participating=participating, abstained=[], disagreement=0.1, ensemble_version="1.0.0",
    )


def test_fully_abstained_ensemble_yields_zero_evidence_quality() -> None:
    result = compute_evidence_quality(_fully_abstained(), bundle=make_bundle())
    assert result.final_evidence_quality == 0.0


def test_own_evidence_quality_weighted_average_matches_manual_computation() -> None:
    result = compute_evidence_quality(
        _ensemble_output(own_evidence_qualities=[0.4, 0.9], weights=[0.5, 0.5]), bundle=make_bundle()
    )
    assert result.components.avg_own_evidence_quality == 0.65


def test_composite_always_bounded_zero_to_one() -> None:
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[1.0]), bundle=make_bundle())
    assert 0.0 <= result.final_evidence_quality <= 1.0


def test_all_fields_present_gives_full_availability_rate() -> None:
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(include_states=True))
    assert result.components.field_availability_rate == 1.0


def test_missing_fields_lower_availability_rate() -> None:
    bundle = ModelInputBundle(
        match_id="m", player_a_id="p1", player_b_id="p2", as_of=NOW, player_a_profile=make_profile("p1")
    )
    with_missing = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=bundle)
    fully_present = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(include_states=True))
    assert with_missing.components.field_availability_rate < fully_present.components.field_availability_rate


def test_entirely_absent_entity_counts_all_its_fields_as_unavailable() -> None:
    """Regression guard for the real bug this test suite caught: a
    None entity (e.g. player_b_profile never loaded from CE.1) must
    count as every one of its fields being unavailable — not be silently
    skipped, which would have reported a misleadingly perfect availability
    rate for a bundle missing half its data.
    """
    bundle = ModelInputBundle(
        match_id="m", player_a_id="p1", player_b_id="p2", as_of=NOW, player_a_profile=make_profile("p1")
    )
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=bundle)
    assert result.components.field_availability_rate < 1.0


def _env_with_reliability(value: object, trust: float) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
        reliability=ReliabilityInfo(source_trust_score=trust, source_id="test_source"),
    )


def test_source_reliability_averages_only_envelopes_that_have_it() -> None:
    profile = make_profile("p1")
    profile.ranking = _env_with_reliability(10, 0.9)
    profile.career_stage = _env_with_reliability("PEAK", 0.5)
    # every other field on this profile has reliability=None by default from factories.env()

    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=profile))
    assert result.components.source_reliability_avg == 0.7  # avg of 0.9 and 0.5, not diluted by the None ones


def test_no_reliability_data_anywhere_yields_zero_reliability_component() -> None:
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle())
    assert result.components.source_reliability_avg == 0.0


def _env_with_provenance(value: object) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
        provenance=Provenance(source_id="s", collected_at=NOW, parser_version="1.0.0", source_priority_rank=1),
    )


def test_provenance_completeness_counts_only_fields_with_provenance() -> None:
    profile = make_profile("p1")
    profile.ranking = _env_with_provenance(10)
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=profile))
    assert 0.0 < result.components.provenance_completeness_rate < 1.0


def test_no_provenance_anywhere_yields_zero_provenance_rate() -> None:
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle())
    assert result.components.provenance_completeness_rate == 0.0


def test_conflicted_fields_reduce_composite_evidence_quality() -> None:
    profile_clean = make_profile("p1")
    profile_conflicted = make_profile("p1")
    profile_conflicted.ranking = FieldEnvelope(
        value=10, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT, has_conflict=True,
    )

    clean_result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=profile_clean))
    conflicted_result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=profile_conflicted))

    assert conflicted_result.components.conflict_rate > clean_result.components.conflict_rate
    assert conflicted_result.final_evidence_quality < clean_result.final_evidence_quality


def test_freshness_validity_is_higher_for_fresh_than_stale_data() -> None:
    """Same freshness metadata Uncertainty Aggregator reads, opposite
    semantic direction: here FRESH increases quality, whereas in
    Uncertainty STALE increases the penalty — two independent computations
    over the same input, verified by direction here.
    """
    from tbos.ce1_data.envelope import FreshnessInfo
    from tbos.inf1_config.taxonomy import FreshnessStatus

    fresh_env = FieldEnvelope(
        value=10, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
        freshness=FreshnessInfo(collected_at=NOW, age_seconds=1.0, threshold_seconds=60, status=FreshnessStatus.FRESH),
    )
    stale_env = FieldEnvelope(
        value=10, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
        freshness=FreshnessInfo(collected_at=NOW, age_seconds=999999.0, threshold_seconds=60, status=FreshnessStatus.STALE),
    )

    fresh_profile = make_profile("p1")
    fresh_profile.ranking = fresh_env
    stale_profile = make_profile("p1")
    stale_profile.ranking = stale_env

    fresh_result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=fresh_profile))
    stale_result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle(player_a_profile=stale_profile))

    assert fresh_result.components.freshness_validity_rate > stale_result.components.freshness_validity_rate


def test_il1_signal_quality_is_zero_placeholder_not_fabricated() -> None:
    result = compute_evidence_quality(_ensemble_output(own_evidence_qualities=[0.7]), bundle=make_bundle())
    assert result.components.il1_signal_quality == 0.0


def test_evidence_quality_never_reads_probability_or_uncertainty() -> None:
    assert "probability" not in EvidenceQualityResult.model_fields
    assert "uncertainty" not in EvidenceQualityResult.model_fields
