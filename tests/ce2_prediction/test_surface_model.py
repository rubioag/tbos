from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.surface_model import SurfaceModel
from tbos.inf1_config.taxonomy import Surface

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile


def test_surface_model_produces_estimate_for_both_players() -> None:
    output = SurfaceModel().estimate(make_bundle())
    assert output.abstained is False
    assert "surface_adjustment" in output.estimate["player_a"]


def test_surface_model_estimate_never_contains_probability_or_p_win_key() -> None:
    output = SurfaceModel().estimate(make_bundle())
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_surface_model_is_deterministic() -> None:
    assert_deterministic(SurfaceModel(), make_bundle())


def test_surface_model_abstains_on_surface_debut() -> None:
    clay_only = make_profile("p1", hold_rate={"CLAY": 0.8}, service_points_won={"CLAY": 0.65})
    bundle = make_bundle(player_a_profile=clay_only, match_context=make_match_context(Surface.HARD))
    output = SurfaceModel().estimate(bundle)
    assert output.abstained is True
    assert "surface debut" in output.abstain_reason


def test_surface_model_zero_adjustment_when_only_one_surface_on_record() -> None:
    """No comparative baseline exists yet — adjustment defaults to 0, but
    evidence_quality reflects the weak comparative basis honestly.
    """
    single_surface = make_profile("p1", hold_rate={"HARD": 0.80}, service_points_won={"HARD": 0.65})
    output = SurfaceModel().estimate(make_bundle(player_a_profile=single_surface))
    assert output.estimate["player_a"]["surface_adjustment"] == 0.0
    assert output.own_evidence_quality < 0.75


def test_surface_model_positive_adjustment_when_surface_is_players_strength() -> None:
    multi_surface = make_profile(
        "p1",
        hold_rate={"HARD": 0.90, "CLAY": 0.60},
        service_points_won={"HARD": 0.75, "CLAY": 0.55},
    )
    output = SurfaceModel().estimate(make_bundle(player_a_profile=multi_surface, match_context=make_match_context(Surface.HARD)))
    assert output.estimate["player_a"]["surface_adjustment"] > 0


def test_surface_model_negative_adjustment_when_surface_is_players_weakness() -> None:
    multi_surface = make_profile(
        "p1",
        hold_rate={"HARD": 0.50, "CLAY": 0.85},
        service_points_won={"HARD": 0.45, "CLAY": 0.80},
    )
    output = SurfaceModel().estimate(make_bundle(player_a_profile=multi_surface, match_context=make_match_context(Surface.HARD)))
    assert output.estimate["player_a"]["surface_adjustment"] < 0


def test_surface_model_abstains_when_opponent_profile_missing() -> None:
    bundle = ModelInputBundle(
        match_id="m", player_a_id="p1", player_b_id="p2",
        as_of=make_bundle().as_of, player_a_profile=make_profile("p1"),
    )
    output = SurfaceModel().estimate(bundle)
    assert output.abstained is True


def test_surface_model_never_uses_market_data() -> None:
    assert SurfaceModel().estimate(make_bundle()).market_data_used is False
