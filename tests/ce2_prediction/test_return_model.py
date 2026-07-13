from datetime import datetime, timezone

from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.return_model import ReturnModel
from tbos.inf1_config.taxonomy import Surface

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile


def test_return_model_produces_estimate_for_both_players() -> None:
    output = ReturnModel().estimate(make_bundle())
    assert output.abstained is False
    assert "player_a" in output.estimate
    assert "player_b" in output.estimate
    assert 0.0 <= output.estimate["player_a"]["return_points_won_pct"] <= 1.0


def test_return_model_estimate_never_contains_probability_or_p_win_key() -> None:
    output = ReturnModel().estimate(make_bundle())
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_return_model_is_deterministic() -> None:
    assert_deterministic(ReturnModel(), make_bundle())


def test_return_model_abstains_when_opponent_profile_missing() -> None:
    bundle = ModelInputBundle(match_id="m", player_a_id="p1", player_b_id="p2", as_of=datetime.now(timezone.utc), player_a_profile=make_profile("p1"))
    output = ReturnModel().estimate(bundle)
    assert output.abstained is True


def test_return_model_abstains_on_surface_debut_no_history() -> None:
    profile_clay_only = make_profile("p1", first_serve={"CLAY": 0.6}, service_points_won={"CLAY": 0.65},
                                      return_points_won={"CLAY": 0.35}, break_conversion={"CLAY": 0.38})
    bundle = make_bundle(player_a_profile=profile_clay_only, match_context=make_match_context(Surface.HARD))
    output = ReturnModel().estimate(bundle)
    assert output.abstained is True


def test_return_model_stronger_server_lowers_returner_performance() -> None:
    weak_server = make_profile("p2", first_serve={"HARD": 0.40}, service_points_won={"HARD": 0.40})
    strong_server = make_profile("p2", first_serve={"HARD": 0.75}, service_points_won={"HARD": 0.80})

    output_vs_weak = ReturnModel().estimate(make_bundle(player_b_profile=weak_server))
    output_vs_strong = ReturnModel().estimate(make_bundle(player_b_profile=strong_server))

    assert (
        output_vs_strong.estimate["player_a"]["return_points_won_pct"]
        < output_vs_weak.estimate["player_a"]["return_points_won_pct"]
    )


def test_return_model_clamps_extreme_inputs_to_valid_range() -> None:
    dominant_returner = make_profile("p1", return_points_won={"HARD": 0.99}, break_conversion={"HARD": 0.99})
    weak_server = make_profile("p2", first_serve={"HARD": 0.01}, service_points_won={"HARD": 0.01})
    output = ReturnModel().estimate(make_bundle(player_a_profile=dominant_returner, player_b_profile=weak_server))
    assert 0.0 <= output.estimate["player_a"]["return_points_won_pct"] <= 1.0
    assert 0.0 <= output.estimate["player_a"]["break_conversion_rate"] <= 1.0


def test_return_model_never_uses_market_data() -> None:
    output = ReturnModel().estimate(make_bundle())
    assert output.market_data_used is False


def test_return_model_does_not_import_serve_model() -> None:
    """Structural independence check: Return Model's module must not
    import Serve Model or read its output — only shared neutral utilities.
    """
    import tbos.ce2_prediction.return_model as mod

    assert "serve_model" not in mod.__file__
    source = open(mod.__file__, encoding="utf-8").read()
    assert "serve_model" not in source
