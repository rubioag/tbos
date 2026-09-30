from datetime import UTC, datetime

from tbos.historical_pipeline.outcome_tracking import (
    PredictionOutcomeRecord,
    PredictionOutcomeStore,
    compute_betting_metrics,
    compute_coverage_report,
    compute_cumulative_metrics,
    model_favorite_won,
    render_validation_table,
    to_match_prediction,
    value_bet_won,
)

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def _record(
    match_id: str = "m1", *, predicted_prob: float | None = 0.46, actual_winner: str = "p2",
    fully_abstained: bool = False, has_market: bool = False,
    decision: str = "NO BET (market unavailable)", ev: float | None = None,
    bet_result: str | None = None, stake_eur: float | None = None, odds_taken: float | None = None,
    player_a_name: str = "Player One", player_b_name: str = "Player Two",
) -> PredictionOutcomeRecord:
    return PredictionOutcomeRecord(
        match_id=match_id, player_a_id="p1", player_b_id="p2",
        player_a_name=player_a_name, player_b_name=player_b_name,
        predicted_probability_player_a=predicted_prob, fully_abstained=fully_abstained,
        participating_model_ids=["serve_model"], decision=decision, has_market=has_market, ev=ev,
        stake_eur=stake_eur, odds_taken=odds_taken,
        actual_winner_id=actual_winner, actual_score="6-4, 6-2",
        bet_result=bet_result, recorded_at=NOW,
    )


def test_append_persists_and_is_readable_after_reload(tmp_path) -> None:
    path = tmp_path / "outcomes.jsonl"
    store = PredictionOutcomeStore(path)
    store.append(_record())

    reloaded = PredictionOutcomeStore(path)
    assert reloaded.get("m1") is not None
    assert reloaded.get("m1").actual_score == "6-4, 6-2"


def test_append_is_idempotent_never_overwrites(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(actual_winner="p2"))
    store.append(_record(actual_winner="p1"))  # different content, same match_id
    assert store.get("m1").actual_winner_id == "p2"  # first write wins


def test_to_match_prediction_maps_actual_outcome_correctly() -> None:
    record = _record(actual_winner="p2")  # player_b won -> player_a lost
    prediction = to_match_prediction(record)
    assert prediction.actual_outcome_player_a == 0

    record_a_won = _record(match_id="m2", actual_winner="p1")
    prediction_a = to_match_prediction(record_a_won)
    assert prediction_a.actual_outcome_player_a == 1


def test_cumulative_metrics_include_no_market_matches(tmp_path) -> None:
    """Explicit requirement: a no-market match must still count toward
    prediction-quality metrics, never be silently dropped.
    """
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(has_market=False))
    report = compute_cumulative_metrics(store)
    assert report.sample_size == 1
    assert report.accuracy is not None


def test_cumulative_metrics_excludes_fully_abstained_from_accuracy(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(fully_abstained=True, predicted_prob=None, decision="ABSTAIN"))
    report = compute_cumulative_metrics(store)
    assert report.sample_size == 1
    assert report.coverage == 0.0
    assert report.accuracy is None


def test_old_record_without_new_fields_still_parses(tmp_path) -> None:
    """Backward compatibility: a record written before player_a_name,
    ev, and bet_result existed (e.g. the real De Jong vs Baez row) must
    still load without those fields present in the JSONL line.
    """
    path = tmp_path / "outcomes.jsonl"
    old_line = (
        '{"match_id":"72661910","player_a_id":"207411","player_b_id":"202104",'
        '"predicted_probability_player_a":0.46,"fully_abstained":false,'
        '"participating_model_ids":["serve_model"],"decision":"NO BET (market unavailable)",'
        '"has_market":false,"actual_winner_id":"202104","actual_score":"6-4, 6-2",'
        '"recorded_at":"2026-07-16T19:37:11.211347Z"}\n'
    )
    path.write_text(old_line, encoding="utf-8")
    store = PredictionOutcomeStore(path)
    record = store.get("72661910")
    assert record is not None
    assert record.player_a_name == ""
    assert record.ev is None
    assert record.bet_result is None


def test_render_validation_table_marks_correct_prediction(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(predicted_prob=0.7, actual_winner="p1"))  # predicted p1, p1 won
    table = render_validation_table(store)
    assert "✅" in table
    assert "Player One vs Player Two" in table
    assert "70.0%" in table


def test_render_validation_table_marks_incorrect_prediction(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(predicted_prob=0.7, actual_winner="p2"))  # predicted p1, p2 won
    table = render_validation_table(store)
    assert "❌" in table


def test_render_validation_table_shows_no_market_and_no_bet(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(has_market=False, decision="NO BET (market unavailable)"))
    table = render_validation_table(store)
    data_row = table.splitlines()[2]
    columns = [c.strip() for c in data_row.split("|")]
    assert "No" in columns  # both "Market" and "Bet Placed" columns should read "No"
    assert columns.count("No") == 2


def test_render_validation_table_shows_ev_and_bet_result_when_present(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(has_market=True, decision="BET", ev=0.1632, bet_result="WIN"))
    table = render_validation_table(store)
    assert "0.1632" in table
    assert "WIN" in table


def test_render_validation_table_handles_fully_abstained_row(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(fully_abstained=True, predicted_prob=None, decision="ABSTAIN"))
    table = render_validation_table(store)
    assert "—" in table


def test_render_validation_table_is_chronologically_ordered(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    later = _record(match_id="m2", player_a_name="Later Match")
    later.recorded_at = NOW.replace(day=17)
    earlier = _record(match_id="m1", player_a_name="Earlier Match")
    earlier.recorded_at = NOW
    # Append in reverse chronological order — the table must still sort correctly.
    store.append(later)
    store.append(earlier)

    table = render_validation_table(store)
    assert table.index("Earlier Match") < table.index("Later Match")


def test_betting_metrics_win_computes_correct_profit(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(
        _record(
            has_market=True, decision="BET", bet_result="WIN",
            stake_eur=1.51, odds_taken=2.32, actual_winner="p1",
        )
    )
    report = compute_betting_metrics(store, starting_bankroll=100.0)
    assert report.total_bets == 1
    assert report.wins == 1
    assert report.total_staked == 1.51
    expected_return = 1.51 * 2.32
    assert abs(report.total_returned - expected_return) < 1e-9
    assert abs(report.net_profit - (expected_return - 1.51)) < 1e-9
    assert abs(report.ending_bankroll - (100.0 + report.net_profit)) < 1e-9
    assert report.roi_pct == report.yield_pct


def test_betting_metrics_loss_stakes_lost(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(
        _record(has_market=True, decision="BET", bet_result="LOSS", stake_eur=2.0, odds_taken=1.9),
    )
    report = compute_betting_metrics(store)
    assert report.losses == 1
    assert report.total_returned == 0.0
    assert report.net_profit == -2.0


def test_betting_metrics_void_refunds_stake_no_profit(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(
        _record(has_market=True, decision="BET", bet_result="VOID", stake_eur=3.0, odds_taken=1.5),
    )
    report = compute_betting_metrics(store)
    assert report.voids == 1
    assert report.total_returned == 3.0
    assert report.net_profit == 0.0


def test_betting_metrics_excludes_no_market_and_no_bet_records(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(match_id="m1", has_market=False, decision="NO BET (market unavailable)"))
    store.append(_record(match_id="m2", has_market=True, decision="ABSTAIN"))
    report = compute_betting_metrics(store)
    assert report.total_bets == 0
    assert report.total_staked == 0.0
    assert report.roi_pct is None
    assert report.ending_bankroll == report.starting_bankroll


def test_betting_metrics_roi_pct_matches_hand_computed_value(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(
        _record(has_market=True, decision="BET", bet_result="WIN", stake_eur=10.0, odds_taken=2.0),
    )
    report = compute_betting_metrics(store)
    # staked 10, returned 20, profit 10 -> ROI = 10/10*100 = 100%
    assert abs(report.roi_pct - 100.0) < 1e-9


def test_model_favorite_won_true_when_favorite_side_matches_actual() -> None:
    # predicted_prob=0.46 -> favorite is player_b; actual_winner default "p2" (player_b)
    record = _record(predicted_prob=0.46, actual_winner="p2")
    assert model_favorite_won(record) is True


def test_model_favorite_won_false_when_favorite_side_loses() -> None:
    record = _record(predicted_prob=0.46, actual_winner="p1")  # favorite p2, but p1 won
    assert model_favorite_won(record) is False


def test_model_favorite_won_none_when_fully_abstained() -> None:
    record = _record(fully_abstained=True, predicted_prob=None)
    assert model_favorite_won(record) is None


def test_value_bet_won_true_when_bet_side_wins() -> None:
    # decision=BET always backs player_a per pipeline convention
    record = _record(decision="BET", has_market=True, actual_winner="p1")
    assert value_bet_won(record) is True


def test_value_bet_won_false_when_bet_side_loses() -> None:
    record = _record(decision="BET", has_market=True, actual_winner="p2")
    assert value_bet_won(record) is False


def test_value_bet_won_none_when_no_bet_placed() -> None:
    record = _record(decision="NO BET (market unavailable)")
    assert value_bet_won(record) is None


def test_favorite_and_value_bet_can_diverge() -> None:
    """The Dzumhur-vs-Molcan real case this system caught: model favorite
    (player_a, prob >= 0.5) and the actually-placed value bet CAN be the
    same side (both are always player_a in this pipeline's convention),
    but a record with predicted_prob < 0.5 and decision=BET represents
    exactly the scenario a human summary mislabeled once — verify both
    functions independently agree the favorite is player_b while the bet
    still backed player_a.
    """
    record = _record(predicted_prob=0.492, decision="BET", has_market=True, actual_winner="p1")
    # player_b (0.508) was the real favorite, and p1 won -> favorite lost.
    assert model_favorite_won(record) is False
    assert value_bet_won(record) is True  # but the value bet (player_a) still won


# --- compute_coverage_report -----------------------------------------------

def test_coverage_report_empty_store(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    report = compute_coverage_report(store)
    assert report.total_matches == 0
    assert report.coverage_pct is None


def test_coverage_report_classifies_insufficient_data_abstention(tmp_path) -> None:
    """Resolver-failure / quorum-failure case: CE.2 never produced a
    probability at all — fully_abstained=True.
    """
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(fully_abstained=True, predicted_prob=None, decision="ABSTAIN"))
    report = compute_coverage_report(store)
    assert report.total_matches == 1
    assert report.fully_analyzed == 0
    assert report.abstained_insufficient_data == 1
    assert report.abstained_ev == 0
    assert report.coverage_pct == 0.0


def test_coverage_report_classifies_ev_abstention(tmp_path) -> None:
    """CE.2 succeeded (real probability), but CE.4 declined due to
    edge/EV <= 0 — fully_abstained=False, decision=ABSTAIN.
    """
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(fully_abstained=False, predicted_prob=0.54, decision="ABSTAIN"))
    report = compute_coverage_report(store)
    assert report.fully_analyzed == 1
    assert report.abstained_insufficient_data == 0
    assert report.abstained_ev == 1
    assert report.coverage_pct == 100.0


def test_coverage_report_counts_bet_and_no_bet(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_record(match_id="m1", fully_abstained=False, decision="BET", has_market=True))
    store.append(
        _record(match_id="m2", fully_abstained=False, decision="NO BET (market unavailable)")
    )
    report = compute_coverage_report(store)
    assert report.bet_placed == 1
    assert report.no_bet_market_unavailable == 1
    assert report.fully_analyzed == 2
    assert report.abstained_ev == 0


def test_coverage_report_mixed_sample_matches_hand_computation(tmp_path) -> None:
    store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(
        _record(match_id="m1", fully_abstained=True, predicted_prob=None, decision="ABSTAIN")
    )
    store.append(_record(match_id="m2", fully_abstained=False, decision="ABSTAIN"))
    store.append(_record(match_id="m3", fully_abstained=False, decision="BET", has_market=True))
    store.append(
        _record(match_id="m4", fully_abstained=False, decision="NO BET (market unavailable)")
    )

    report = compute_coverage_report(store)
    assert report.total_matches == 4
    assert report.fully_analyzed == 3
    assert report.abstained_insufficient_data == 1
    assert report.abstained_ev == 1
    assert report.bet_placed == 1
    assert report.no_bet_market_unavailable == 1
    assert abs(report.coverage_pct - 75.0) < 1e-9
