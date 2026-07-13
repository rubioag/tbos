from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.form_fatigue_model import FormFatigueModel
from tbos.ce2_prediction.input_bundle import ModelInputBundle

from tests.ce2_prediction.factories import make_bundle, make_state


def test_form_fatigue_model_produces_estimate_for_both_players() -> None:
    output = FormFatigueModel().estimate(make_bundle(include_states=True))
    assert output.abstained is False
    assert "net_adjustment" in output.estimate["player_a"]


def test_form_fatigue_model_estimate_never_contains_probability_or_p_win_key() -> None:
    output = FormFatigueModel().estimate(make_bundle(include_states=True))
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_form_fatigue_model_is_deterministic() -> None:
    assert_deterministic(FormFatigueModel(), make_bundle(include_states=True))


def test_form_fatigue_model_abstains_when_state_missing() -> None:
    bundle = make_bundle()  # include_states=False by default -> no PlayerState at all
    output = FormFatigueModel().estimate(bundle)
    assert output.abstained is True


def test_form_fatigue_model_heavy_recent_load_reduces_net_adjustment() -> None:
    fresh = make_state("p1", matches_last_14d=1, sets_played_last_14d=2)
    heavy_load = make_state("p1", matches_last_14d=8, sets_played_last_14d=22)

    output_fresh = FormFatigueModel().estimate(make_bundle(player_a_state=fresh, include_states=True))
    output_loaded = FormFatigueModel().estimate(make_bundle(player_a_state=heavy_load, include_states=True))

    assert (
        output_loaded.estimate["player_a"]["net_adjustment"]
        < output_fresh.estimate["player_a"]["net_adjustment"]
    )


def test_form_fatigue_model_injury_penalizes_by_severity() -> None:
    healthy = make_state("p1", injury_flags=[])
    minor_injury = make_state("p1", injury_flags=[{"body_part": "ankle", "severity": "MINOR"}])
    severe_injury = make_state("p1", injury_flags=[{"body_part": "shoulder", "severity": "SEVERE"}])

    healthy_out = FormFatigueModel().estimate(make_bundle(player_a_state=healthy, include_states=True))
    minor_out = FormFatigueModel().estimate(make_bundle(player_a_state=minor_injury, include_states=True))
    severe_out = FormFatigueModel().estimate(make_bundle(player_a_state=severe_injury, include_states=True))

    assert healthy_out.estimate["player_a"]["injury_penalty"] == 0.0
    assert 0.0 < minor_out.estimate["player_a"]["injury_penalty"] < severe_out.estimate["player_a"]["injury_penalty"]
    assert (
        severe_out.estimate["player_a"]["net_adjustment"]
        < minor_out.estimate["player_a"]["net_adjustment"]
        < healthy_out.estimate["player_a"]["net_adjustment"]
    )


def test_form_fatigue_model_unknown_injury_severity_defaults_to_zero_penalty() -> None:
    state = make_state("p1", injury_flags=[{"body_part": "wrist", "severity": "UNKNOWN_TYPO"}])
    output = FormFatigueModel().estimate(make_bundle(player_a_state=state, include_states=True))
    assert output.estimate["player_a"]["injury_penalty"] == 0.0


def test_form_fatigue_model_form_deviation_passed_through_directly() -> None:
    positive_form = make_state("p1", deviation_from_baseline=0.15)
    output = FormFatigueModel().estimate(make_bundle(player_a_state=positive_form, include_states=True))
    assert output.estimate["player_a"]["form_deviation"] == 0.15


def test_form_fatigue_model_does_not_read_match_context_surface() -> None:
    """No surface interaction — the same PlayerState inputs must yield the
    same estimate regardless of what surface the match is on.
    """
    from tests.ce2_prediction.factories import make_match_context
    from tbos.inf1_config.taxonomy import Surface

    state_a = make_state("p1", deviation_from_baseline=0.1)
    hard = FormFatigueModel().estimate(
        make_bundle(player_a_state=state_a, include_states=True, match_context=make_match_context(Surface.HARD))
    )
    clay = FormFatigueModel().estimate(
        make_bundle(player_a_state=state_a, include_states=True, match_context=make_match_context(Surface.CLAY))
    )
    assert hard.estimate == clay.estimate


def test_form_fatigue_model_never_uses_market_data() -> None:
    assert FormFatigueModel().estimate(make_bundle(include_states=True)).market_data_used is False
