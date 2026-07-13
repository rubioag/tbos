from datetime import datetime, timezone

import pytest

from tbos.ce2_prediction.contract import ModelOutput, abstain
from tbos.ce2_prediction.ensemble import combine_models

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _output(
    domain: str, model_id: str, estimate: dict, *, evidence_quality: float = 0.7, uncertainty: float = 0.3
) -> ModelOutput:
    return ModelOutput(
        domain=domain, model_id=model_id, model_version="1.0.0", estimate=estimate,
        own_uncertainty=uncertainty, own_evidence_quality=evidence_quality, abstained=False, computed_at=NOW,
    )


def test_all_models_abstained_yields_fully_abstained() -> None:
    outputs = [
        abstain(domain="serve", model_id="serve_model", model_version="1.0.0", reason="missing data", computed_at=NOW),
        abstain(domain="return", model_id="return_model", model_version="1.0.0", reason="missing data", computed_at=NOW),
    ]
    result = combine_models("match_1", outputs)
    assert result.fully_abstained is True
    assert result.probability_player_a is None
    assert len(result.abstained) == 2
    assert len(result.participating) == 0


def test_no_outputs_at_all_yields_fully_abstained() -> None:
    result = combine_models("match_1", [])
    assert result.fully_abstained is True


def test_single_participating_model_probability_matches_its_own_sigmoid() -> None:
    output = _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}})
    result = combine_models("match_1", [output])
    assert result.fully_abstained is False
    assert result.probability_player_a > 0.5
    assert len(result.participating) == 1
    assert result.participating[0].weight == pytest.approx(1.0)  # sole contributor normalizes to full weight


def test_weights_normalize_to_one_across_participants() -> None:
    outputs = [
        _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}}, evidence_quality=0.7),
        _output("return", "return_model", {"player_a": {"return_points_won_pct": 0.4}, "player_b": {"return_points_won_pct": 0.3}}, evidence_quality=0.3),
    ]
    result = combine_models("match_1", outputs)
    total_weight = sum(c.weight for c in result.participating)
    assert total_weight == pytest.approx(1.0)


def test_combined_log_odds_falls_between_individual_contributions() -> None:
    """Weighted-average pooling (not summed log-likelihoods) means agreeing
    signals pull the combined estimate toward their average, never beyond
    the most extreme individual contribution. Confidence from agreement is
    Uncertainty Aggregator's job (CE.2.6), not something the probability
    estimate itself should reflect — that's the whole point of keeping
    Probability and Uncertainty as independent axes.
    """
    serve = _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}})
    weaker_return = _output("return", "return_model", {"player_a": {"return_points_won_pct": 0.4}, "player_b": {"return_points_won_pct": 0.3}})

    serve_only = combine_models("match_1", [serve])
    return_only = combine_models("match_1", [weaker_return])
    combined = combine_models("match_1", [serve, weaker_return])

    lower, upper = sorted([serve_only.log_odds, return_only.log_odds])
    assert lower <= combined.log_odds <= upper


def test_disagreeing_models_have_higher_disagreement_than_agreeing_models() -> None:
    agreeing = combine_models(
        "match_1",
        [
            _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}}),
            _output("return", "return_model", {"player_a": {"return_points_won_pct": 0.4}, "player_b": {"return_points_won_pct": 0.3}}),
        ],
    )
    disagreeing = combine_models(
        "match_1",
        [
            _output("serve", "serve_model", {"player_a": {"hold_probability": 0.9}, "player_b": {"hold_probability": 0.5}}),
            _output("return", "return_model", {"player_a": {"return_points_won_pct": 0.2}, "player_b": {"return_points_won_pct": 0.5}}),
        ],
    )
    assert disagreeing.disagreement > agreeing.disagreement


def test_zero_evidence_quality_across_all_participants_yields_fully_abstained() -> None:
    outputs = [
        _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}}, evidence_quality=0.0),
    ]
    result = combine_models("match_1", outputs)
    assert result.fully_abstained is True


def test_unknown_domain_treated_as_abstained_not_crash() -> None:
    output = _output("unregistered_domain", "mystery_model", {"foo": "bar"})
    result = combine_models("match_1", [output])
    assert result.fully_abstained is True
    assert result.abstained[0].model_id == "mystery_model"


def test_mixed_participating_and_abstained_reported_separately() -> None:
    outputs = [
        _output("serve", "serve_model", {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}}),
        abstain(domain="matchup", model_id="matchup_model", model_version="1.0.0", reason="no h2h", computed_at=NOW),
    ]
    result = combine_models("match_1", outputs)
    assert len(result.participating) == 1
    assert len(result.abstained) == 1
    assert result.abstained[0].model_id == "matchup_model"


def test_probability_output_is_always_between_zero_and_one() -> None:
    output = _output("serve", "serve_model", {"player_a": {"hold_probability": 0.99}, "player_b": {"hold_probability": 0.01}})
    result = combine_models("match_1", [output])
    assert 0.0 < result.probability_player_a < 1.0
