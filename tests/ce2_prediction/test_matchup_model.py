from datetime import datetime, timezone

from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.matchup_model import MatchupModel
from tbos.inf1_config.taxonomy import Surface

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(date_str: str, surface: str = "HARD", result: str = "WIN", opponent_id: str = "p2") -> dict:
    return {"opponent_id": opponent_id, "date": date_str, "surface": surface, "result": result}


def test_matchup_model_abstains_on_zero_h2h() -> None:
    output = MatchupModel().estimate(make_bundle())
    assert output.abstained is True
    assert "no prior head-to-head" in output.abstain_reason


def test_matchup_model_produces_estimate_with_h2h_history() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.abstained is False
    assert output.estimate["h2h_sample_size"] == 1.0


def test_matchup_model_estimate_never_contains_probability_or_p_win_key() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_matchup_model_is_deterministic() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01"), _record("2024-01-01", result="LOSS")])
    assert_deterministic(MatchupModel(), make_bundle(player_a_profile=profile))


def test_matchup_model_ignores_h2h_records_against_other_opponents() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01", opponent_id="someone_else")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.abstained is True


def test_matchup_model_all_wins_gives_high_win_rate() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01", result="WIN"), _record("2025-01-01", result="WIN")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.estimate["h2h_win_rate_player_a"] > 0.9


def test_matchup_model_all_losses_gives_low_win_rate() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01", result="LOSS"), _record("2025-01-01", result="LOSS")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.estimate["h2h_win_rate_player_a"] < 0.1


def test_matchup_model_more_recent_meeting_weighted_more_heavily() -> None:
    """A recent win + an old loss should tilt the weighted win rate above
    a naive 50/50 average — recency matters, per spec.
    """
    profile = make_profile(
        "p1",
        h2h_records=[
            _record("2025-12-01", result="WIN"),  # recent, near AS_OF via bundle default (2026-01-01)
            _record("2015-01-01", result="LOSS"),  # ancient
        ],
    )
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.estimate["h2h_win_rate_player_a"] > 0.5


def test_matchup_model_surface_mismatch_discounts_weight() -> None:
    same_surface = make_profile("p1", h2h_records=[_record("2025-06-01", surface="HARD", result="WIN")])
    diff_surface = make_profile("p1", h2h_records=[_record("2025-06-01", surface="CLAY", result="WIN")])

    out_same = MatchupModel().estimate(make_bundle(player_a_profile=same_surface, match_context=make_match_context(Surface.HARD)))
    out_diff = MatchupModel().estimate(make_bundle(player_a_profile=diff_surface, match_context=make_match_context(Surface.HARD)))

    assert out_diff.estimate["effective_weight"] < out_same.estimate["effective_weight"]


def test_matchup_model_small_sample_has_high_uncertainty() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.own_uncertainty >= 0.3


def test_matchup_model_larger_sample_has_lower_uncertainty_than_single_meeting() -> None:
    single = make_profile("p1", h2h_records=[_record("2025-06-01")])
    many = make_profile(
        "p1",
        h2h_records=[_record(f"202{i}-01-01") for i in range(5)],
    )
    out_single = MatchupModel().estimate(make_bundle(player_a_profile=single))
    out_many = MatchupModel().estimate(make_bundle(player_a_profile=many))
    assert out_many.own_uncertainty < out_single.own_uncertainty


def test_matchup_model_abstains_when_match_context_missing() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    bundle = ModelInputBundle(
        match_id="m", player_a_id="p1", player_b_id="p2", as_of=AS_OF, player_a_profile=profile
    )
    output = MatchupModel().estimate(bundle)
    assert output.abstained is True


def test_matchup_model_never_uses_market_data() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    assert MatchupModel().estimate(make_bundle(player_a_profile=profile)).market_data_used is False
