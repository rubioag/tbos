import pytest

from tbos.ce2_prediction.domain_mapping import (
    UnknownDomainError,
    logit,
    map_to_log_odds,
    sigmoid,
)


def test_sigmoid_and_logit_are_inverses() -> None:
    for p in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert sigmoid(logit(p)) == pytest.approx(p, abs=1e-6)


def test_logit_of_half_is_zero() -> None:
    assert logit(0.5) == pytest.approx(0.0)


def test_logit_clamps_extreme_probabilities() -> None:
    # must not raise ZeroDivisionError / math domain error at p=0 or p=1
    assert logit(0.0) < logit(1e-3)
    assert logit(1.0) > logit(1 - 1e-3)


def test_serve_mapping_favors_player_a_when_a_holds_more() -> None:
    estimate = {"player_a": {"hold_probability": 0.8}, "player_b": {"hold_probability": 0.6}}
    assert map_to_log_odds("serve", estimate) > 0


def test_serve_mapping_favors_player_b_when_b_holds_more() -> None:
    estimate = {"player_a": {"hold_probability": 0.5}, "player_b": {"hold_probability": 0.9}}
    assert map_to_log_odds("serve", estimate) < 0


def test_return_mapping_direction() -> None:
    estimate = {"player_a": {"return_points_won_pct": 0.4}, "player_b": {"return_points_won_pct": 0.3}}
    assert map_to_log_odds("return", estimate) > 0


def test_surface_mapping_direction() -> None:
    estimate = {"player_a": {"surface_adjustment": 0.1}, "player_b": {"surface_adjustment": -0.05}}
    assert map_to_log_odds("surface", estimate) > 0


def test_form_fatigue_mapping_direction() -> None:
    estimate = {"player_a": {"net_adjustment": 0.05}, "player_b": {"net_adjustment": -0.1}}
    assert map_to_log_odds("form_fatigue", estimate) > 0


def test_matchup_mapping_direction() -> None:
    estimate = {"h2h_win_rate_player_a": 0.75}
    assert map_to_log_odds("matchup", estimate) > 0


def test_matchup_mapping_below_half_is_negative() -> None:
    estimate = {"h2h_win_rate_player_a": 0.2}
    assert map_to_log_odds("matchup", estimate) < 0


def test_unknown_domain_raises() -> None:
    with pytest.raises(UnknownDomainError):
        map_to_log_odds("nonexistent_domain", {})
