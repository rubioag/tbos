from datetime import datetime, timezone

from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.serve_model import ServeModel
from tbos.inf1_config.taxonomy import Surface

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile


def test_serve_model_produces_estimate_for_both_players() -> None:
    output = ServeModel().estimate(make_bundle())
    assert output.abstained is False
    assert "player_a" in output.estimate
    assert "player_b" in output.estimate
    assert 0.0 <= output.estimate["player_a"]["hold_probability"] <= 1.0
    assert 0.0 <= output.estimate["player_b"]["hold_probability"] <= 1.0


def test_serve_model_estimate_never_contains_probability_or_p_win_key() -> None:
    """Structural spot-check of the domain/probability separation for this
    specific Model's output shape.
    """
    output = ServeModel().estimate(make_bundle())
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_serve_model_is_deterministic() -> None:
    assert_deterministic(ServeModel(), make_bundle())


def test_serve_model_abstains_when_opponent_profile_missing() -> None:
    bundle = ModelInputBundle(match_id="m", player_a_id="p1", player_b_id="p2", as_of=datetime.now(timezone.utc), player_a_profile=make_profile("p1"))
    output = ServeModel().estimate(bundle)
    assert output.abstained is True
    assert "player_b_profile" in output.abstain_reason


def test_serve_model_abstains_on_surface_debut_no_history() -> None:
    """Player has stats only for CLAY; match is on HARD — must abstain,
    never silently substitute a different surface's numbers.
    """
    profile_clay_only = make_profile("p1", hold_rate={"CLAY": 0.8}, service_points_won={"CLAY": 0.65},
                                      aces={"CLAY": 8.0}, return_points_won={"CLAY": 0.35},
                                      break_conversion={"CLAY": 0.38}, first_serve={"CLAY": 0.6})
    bundle = make_bundle(player_a_profile=profile_clay_only, match_context=make_match_context(Surface.HARD))
    output = ServeModel().estimate(bundle)
    assert output.abstained is True
    assert "HARD" in output.abstain_reason


def test_serve_model_stronger_returner_lowers_server_hold_probability() -> None:
    weak_returner = make_profile("p2", return_points_won={"HARD": 0.20}, break_conversion={"HARD": 0.10})
    strong_returner = make_profile("p2", return_points_won={"HARD": 0.55}, break_conversion={"HARD": 0.60})

    output_vs_weak = ServeModel().estimate(make_bundle(player_b_profile=weak_returner))
    output_vs_strong = ServeModel().estimate(make_bundle(player_b_profile=strong_returner))

    assert (
        output_vs_strong.estimate["player_a"]["hold_probability"]
        < output_vs_weak.estimate["player_a"]["hold_probability"]
    )


def test_serve_model_clamps_extreme_inputs_to_valid_range() -> None:
    dominant_server = make_profile("p1", hold_rate={"HARD": 0.99}, service_points_won={"HARD": 0.99})
    weak_returner = make_profile("p2", return_points_won={"HARD": 0.01}, break_conversion={"HARD": 0.01})
    output = ServeModel().estimate(make_bundle(player_a_profile=dominant_server, player_b_profile=weak_returner))
    assert 0.0 <= output.estimate["player_a"]["hold_probability"] <= 1.0
    assert 0.0 <= output.estimate["player_a"]["service_points_won_pct"] <= 1.0


def test_serve_model_records_contribution_lineage() -> None:
    output = ServeModel().estimate(make_bundle())
    assert len(output.contribution_lineage) > 0
    assert all(entry.weight > 0 for entry in output.contribution_lineage)


def test_serve_model_never_uses_market_data() -> None:
    output = ServeModel().estimate(make_bundle())
    assert output.market_data_used is False
