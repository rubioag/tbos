from datetime import UTC, datetime

import pytest

from tbos.historical_pipeline.outcome_tracking import PredictionOutcomeStore
from tbos.historical_pipeline.pending_trades import (
    PendingPaperTrade,
    PendingPaperTradeStore,
    TradeValidationError,
    build_pending_trade_from_report,
    list_open_trades,
    settle_pending_trade,
    validate_trade_against_report,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _report(**overrides) -> dict:
    """A real-shaped raw pipeline report dict (matches
    three_match_analysis.py's report keys) for a valid BET on player_a.
    """
    base = {
        "event_id": "72665072",
        "player_a_id": "126239",
        "player_b_id": "126774",
        "probability_player_a": 0.45553107082953526,
        "implied_probability_player_a": 1.0 / 2.64,
        "participating_models": [
            "serve_model", "return_model", "surface_model", "form_fatigue_model", "matchup_model",
        ],
        "ev": 0.2026020269899731,
        "edge_pct": 7.674319204165647,
        "kelly_fraction": 0.12353782133534943,
        "stake_eur": 1.3572135201846514,
        "decision": "BET",
        "raw_quotes": [
            {"book_id": "Bet365", "selection": "player_a", "odds": 2.50},
            {"book_id": "Bet365", "selection": "player_b", "odds": 1.53},
            {"book_id": "Betfair Exchange", "selection": "player_a", "odds": 2.64},
            {"book_id": "Betfair Exchange", "selection": "player_b", "odds": 1.60},
        ],
    }
    base.update(overrides)
    return base


def _trade(
    match_id: str = "m1", *, player_a_id: str = "p1", player_b_id: str = "p2",
) -> PendingPaperTrade:
    return PendingPaperTrade(
        match_id=match_id, player_a_name="Player A", player_b_name="Player B",
        player_a_id=player_a_id, player_b_id=player_b_id,
        predicted_probability_player_a=0.51, participating_model_ids=["serve_model"],
        ev=0.2, edge_pct=10.0, kelly_fraction=0.1, odds_taken=2.5, stake_eur=1.5,
        placed_at=NOW,
    )


def _settle(pending, outcomes, *, match_id="m1", winner="p1", score="6-4, 6-3"):
    return settle_pending_trade(
        pending, outcomes, match_id=match_id, actual_winner_id=winner,
        actual_score=score, recorded_at=NOW,
    )


def _build(report: dict, *, a: str = "A", b: str = "B") -> PendingPaperTrade:
    return build_pending_trade_from_report(report, player_a_name=a, player_b_name=b, placed_at=NOW)


def test_append_and_reload(tmp_path) -> None:
    path = tmp_path / "pending.jsonl"
    store = PendingPaperTradeStore(path)
    store.append(_trade())

    reloaded = PendingPaperTradeStore(path)
    assert reloaded.get("m1") is not None
    assert reloaded.get("m1").odds_taken == 2.5


def test_append_is_idempotent(tmp_path) -> None:
    store = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    store.append(_trade(player_a_id="p1"))
    store.append(_trade(player_a_id="different"))  # same match_id, different content
    assert store.get("m1").player_a_id == "p1"  # first write wins


def test_list_open_trades_excludes_settled(tmp_path) -> None:
    pending = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    pending.append(_trade(match_id="m1"))
    pending.append(_trade(match_id="m2"))

    _settle(pending, outcomes, match_id="m1")

    open_trades = list_open_trades(pending, outcomes)
    assert {t.match_id for t in open_trades} == {"m2"}


def test_settle_pending_trade_win_when_player_a_wins(tmp_path) -> None:
    pending = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    pending.append(_trade(player_a_id="p1"))

    record = _settle(pending, outcomes, winner="p1")
    assert record is not None
    assert record.bet_result == "WIN"
    assert record.decision == "BET"
    assert record.has_market is True


def test_settle_pending_trade_loss_when_player_b_wins(tmp_path) -> None:
    pending = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    pending.append(_trade(player_a_id="p1", player_b_id="p2"))

    record = _settle(pending, outcomes, winner="p2")
    assert record is not None
    assert record.bet_result == "LOSS"


def test_settle_pending_trade_returns_none_for_unknown_match(tmp_path) -> None:
    pending = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    record = _settle(pending, outcomes, match_id="ghost", score="6-4")
    assert record is None


def test_settle_pending_trade_is_idempotent(tmp_path) -> None:
    pending = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    pending.append(_trade(player_a_id="p1"))

    first = _settle(pending, outcomes, winner="p1")
    # Second settlement attempt with different (wrong) data must not overwrite the first.
    second = _settle(pending, outcomes, winner="p2", score="0-6, 0-6")
    assert second.bet_result == first.bet_result == "WIN"
    assert second.actual_score == first.actual_score == "6-4, 6-3"


def test_build_from_report_derives_correct_trade() -> None:
    trade = _build(_report())
    assert trade.match_id == "72665072"
    assert trade.player_a_id == "126239"
    assert trade.odds_taken == 2.64  # best of the two player_a quotes, recomputed independently
    assert trade.stake_eur == 1.3572135201846514


def test_build_from_report_rejects_non_bet_decision() -> None:
    with pytest.raises(TradeValidationError, match="not \"BET\""):
        _build(_report(decision="ABSTAIN"))


def test_build_from_report_rejects_missing_required_field() -> None:
    report = _report()
    del report["ev"]
    with pytest.raises(TradeValidationError, match="missing required field"):
        _build(report)


def test_build_from_report_rejects_odds_implied_probability_mismatch() -> None:
    """The real bug class this guards against: odds and implied
    probability computed from two different quotes/sides.
    """
    report = _report(implied_probability_player_a=0.9)  # doesn't match 1/2.64
    with pytest.raises(TradeValidationError, match="mismatch"):
        _build(report)


def test_validate_passes_for_matching_trade_and_report() -> None:
    report = _report()
    validate_trade_against_report(_build(report), report)  # must not raise


def test_validate_rejects_player_side_mismatch() -> None:
    """(1) the recommended player matches bet_side — the exact real
    incident: a trade built for Molcan (player_b) while the report's
    player_a was actually Dzumhur.
    """
    report = _report()
    trade = _build(report)
    swapped = trade.model_copy(
        update={"player_a_id": report["player_b_id"], "player_b_id": report["player_a_id"]}
    )
    with pytest.raises(TradeValidationError, match="bet side"):
        validate_trade_against_report(swapped, report)


def test_validate_rejects_odds_belonging_to_wrong_player() -> None:
    """(2) the odds belong to that same player."""
    report = _report()
    trade = _build(report)
    wrong_odds = trade.model_copy(update={"odds_taken": 1.60})  # player_b's odds, not player_a's
    with pytest.raises(TradeValidationError, match="odds do not belong"):
        validate_trade_against_report(wrong_odds, report)


def test_validate_rejects_probability_from_wrong_side() -> None:
    """(3) the probability corresponds to the same side."""
    report = _report()
    trade = _build(report)
    wrong_prob = trade.model_copy(
        update={"predicted_probability_player_a": 1.0 - report["probability_player_a"]}
    )
    with pytest.raises(TradeValidationError, match="probability does not match"):
        validate_trade_against_report(wrong_prob, report)


def test_validate_rejects_ev_from_different_record() -> None:
    """(4) stake, EV, and edge all belong to the same record."""
    report = _report()
    trade = _build(report)
    wrong_ev = trade.model_copy(update={"ev": 0.9999})
    with pytest.raises(TradeValidationError, match="does not belong to this same record"):
        validate_trade_against_report(wrong_ev, report)


def test_validate_rejects_stake_from_different_record() -> None:
    report = _report()
    trade = _build(report)
    wrong_stake = trade.model_copy(update={"stake_eur": 999.0})
    with pytest.raises(TradeValidationError, match="does not belong to this same record"):
        validate_trade_against_report(wrong_stake, report)


def test_append_from_report_persists_only_on_success(tmp_path) -> None:
    store = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    trade = store.append_from_report(_report(), player_a_name="A", player_b_name="B", placed_at=NOW)
    assert store.get("72665072") is not None
    assert store.get("72665072").odds_taken == trade.odds_taken


def test_append_from_report_saves_nothing_on_validation_failure(tmp_path) -> None:
    store = PendingPaperTradeStore(tmp_path / "pending.jsonl")
    with pytest.raises(TradeValidationError):
        store.append_from_report(
            _report(decision="NO BET (market unavailable)"),
            player_a_name="A", player_b_name="B", placed_at=NOW,
        )
    assert store.all() == []
