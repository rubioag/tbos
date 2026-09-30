from datetime import UTC, datetime

from tbos.historical_pipeline.outcome_tracking import (
    PredictionOutcomeRecord,
    PredictionOutcomeStore,
)
from tbos.historical_pipeline.prediction_audit import (
    PredictionAuditRecord,
    PredictionAuditStore,
    build_audit_record_from_report,
    compute_model_votes,
    edge_bucket_label,
    summarize_by_edge_bucket,
    summarize_by_favorite_agreement,
    summarize_by_model,
)
from tests.ce2_prediction.factories import make_bundle

NOW = datetime(2026, 7, 18, tzinfo=UTC)

ALL_MODEL_IDS = {
    "serve_model", "return_model", "surface_model", "form_fatigue_model", "matchup_model",
}


def _report(**overrides) -> dict:
    base = {
        "event_id": "m1",
        "probability_player_a": 0.6,
        "decision": "BET",
        "edge_pct": 7.5,
    }
    base.update(overrides)
    return base


def _votes():
    return compute_model_votes(make_bundle(include_states=True))


def _build(**overrides) -> PredictionAuditRecord:
    return build_audit_record_from_report(_report(**overrides), _votes(), recorded_at=NOW)


def _outcome(
    match_id: str = "m1", *, player_a_id: str = "p1", player_b_id: str = "p2",
    predicted_prob: float = 0.6, actual_winner: str = "p1", bet_result: str | None = "WIN",
    stake_eur: float | None = 10.0, odds_taken: float | None = 2.0,
) -> PredictionOutcomeRecord:
    return PredictionOutcomeRecord(
        match_id=match_id, player_a_id=player_a_id, player_b_id=player_b_id,
        predicted_probability_player_a=predicted_prob, fully_abstained=False,
        participating_model_ids=["serve_model"], decision="BET" if bet_result else "ABSTAIN",
        has_market=bet_result is not None, stake_eur=stake_eur, odds_taken=odds_taken,
        actual_winner_id=actual_winner, actual_score="6-4, 6-3", bet_result=bet_result,
        recorded_at=NOW,
    )


# --- edge_bucket_label ---------------------------------------------------

def test_edge_bucket_negative() -> None:
    assert edge_bucket_label(-3.0) == "<0%"


def test_edge_bucket_boundaries() -> None:
    assert edge_bucket_label(0.0) == "0-5%"
    assert edge_bucket_label(4.99) == "0-5%"
    assert edge_bucket_label(5.0) == "5-10%"
    assert edge_bucket_label(9.99) == "5-10%"
    assert edge_bucket_label(10.0) == "10-15%"
    assert edge_bucket_label(15.0) == "15-20%"
    assert edge_bucket_label(20.0) == ">20%"
    assert edge_bucket_label(50.0) == ">20%"


def test_edge_bucket_none_passthrough() -> None:
    assert edge_bucket_label(None) is None


# --- compute_model_votes (real Models, real ensemble) ---------------------

def test_compute_model_votes_returns_all_five_models() -> None:
    votes = _votes()
    assert {v.model_id for v in votes} == ALL_MODEL_IDS


def test_compute_model_votes_leans_direction_matches_sign() -> None:
    for v in _votes():
        if not v.voted or v.leans == "neutral":
            continue
        if v.leans == "player_a":
            assert v.log_odds_player_a > 0
        elif v.leans == "player_b":
            assert v.log_odds_player_a < 0


def test_compute_model_votes_matchup_votes_via_elo_fallback_with_no_h2h() -> None:
    """With equal default Elo, matchup_model still votes (Elo-only
    fallback, per the earlier Elo integration) — sanity check it's not
    silently dropped from the vote list even with no H2H.
    """
    matchup = next(v for v in _votes() if v.model_id == "matchup_model")
    assert matchup.voted is True


# --- build_audit_record_from_report ---------------------------------------

def test_build_audit_record_favorite_side_from_probability() -> None:
    assert _build(probability_player_a=0.6).favorite_side == "player_a"


def test_build_audit_record_favorite_side_player_b_when_below_half() -> None:
    assert _build(probability_player_a=0.4).favorite_side == "player_b"


def test_build_audit_record_value_bet_side_always_player_a_when_bet() -> None:
    assert _build(decision="BET").value_bet_side == "player_a"


def test_build_audit_record_no_value_bet_when_not_bet() -> None:
    record = _build(decision="ABSTAIN")
    assert record.value_bet_side is None
    assert record.favorite_value_agree is None


def test_build_audit_record_agreement_true_when_favorite_is_player_a_and_bet_placed() -> None:
    record = _build(probability_player_a=0.6, decision="BET")
    assert record.favorite_value_agree is True


def test_build_audit_record_agreement_false_when_favorite_is_player_b_but_bet_on_player_a() -> None:
    record = _build(probability_player_a=0.4, decision="BET")
    assert record.favorite_value_agree is False


def test_build_audit_record_edge_bucket_derived_from_report() -> None:
    assert _build(edge_pct=12.0).edge_bucket == "10-15%"


# --- PredictionAuditStore --------------------------------------------------

def test_store_append_and_reload(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    store = PredictionAuditStore(path)
    store.append(_build())

    reloaded = PredictionAuditStore(path)
    assert reloaded.get("m1") is not None
    assert len(reloaded.get("m1").model_votes) == 5


def test_store_append_is_idempotent(tmp_path) -> None:
    store = PredictionAuditStore(tmp_path / "audit.jsonl")
    store.append(_build(edge_pct=1.0))
    store.append(_build(edge_pct=99.0))
    assert store.get("m1").edge_pct == 1.0  # first write wins


# --- summarize_by_edge_bucket ----------------------------------------------

def test_summarize_by_edge_bucket_groups_settled_bets(tmp_path) -> None:
    audit_store = PredictionAuditStore(tmp_path / "audit.jsonl")
    outcome_store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")

    audit_store.append(_build(event_id="m1", edge_pct=3.0))
    audit_store.append(_build(event_id="m2", edge_pct=8.0))
    outcome_store.append(_outcome(match_id="m1", bet_result="WIN"))
    outcome_store.append(_outcome(match_id="m2", bet_result="LOSS"))

    report = summarize_by_edge_bucket(audit_store, outcome_store)
    assert report["0-5%"]["n"] == 1
    assert report["0-5%"]["wins"] == 1
    assert report["5-10%"]["n"] == 1
    assert report["5-10%"]["losses"] == 1


def test_summarize_by_edge_bucket_excludes_unsettled(tmp_path) -> None:
    audit_store = PredictionAuditStore(tmp_path / "audit.jsonl")
    outcome_store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    audit_store.append(_build(event_id="m1"))
    # No matching outcome recorded at all -> must be excluded, not crash.
    assert summarize_by_edge_bucket(audit_store, outcome_store) == {}


# --- summarize_by_favorite_agreement ---------------------------------------

def test_summarize_by_favorite_agreement_splits_correctly(tmp_path) -> None:
    audit_store = PredictionAuditStore(tmp_path / "audit.jsonl")
    outcome_store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")

    # agree: favorite=player_a, bet=player_a
    audit_store.append(_build(event_id="m1", probability_player_a=0.6, decision="BET"))
    # disagree: favorite=player_b, bet=player_a
    audit_store.append(_build(event_id="m2", probability_player_a=0.4, decision="BET"))
    outcome_store.append(_outcome(match_id="m1", bet_result="WIN"))
    outcome_store.append(_outcome(match_id="m2", bet_result="LOSS"))

    report = summarize_by_favorite_agreement(audit_store, outcome_store)
    assert report["agree"]["n"] == 1
    assert report["agree"]["wins"] == 1
    assert report["disagree"]["n"] == 1
    assert report["disagree"]["losses"] == 1


# --- summarize_by_model -----------------------------------------------------

def test_summarize_by_model_scores_directional_correctness(tmp_path) -> None:
    audit_store = PredictionAuditStore(tmp_path / "audit.jsonl")
    outcome_store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    votes = _votes()
    record = build_audit_record_from_report(_report(event_id="m1"), votes, recorded_at=NOW)
    audit_store.append(record)
    # actual winner = player_a -> a model that voted "player_a" is correct.
    outcome_store.append(_outcome(match_id="m1", actual_winner="p1"))

    report = summarize_by_model(audit_store, outcome_store)
    for model_id, stats in report.items():
        assert stats["n"] == 1
        matching_vote = next(v for v in votes if v.model_id == model_id)
        if matching_vote.voted and matching_vote.leans == "player_a":
            assert stats["correct"] == 1
        elif matching_vote.voted and matching_vote.leans == "player_b":
            assert stats["correct"] == 0


def test_summarize_by_model_skips_matches_without_outcome(tmp_path) -> None:
    audit_store = PredictionAuditStore(tmp_path / "audit.jsonl")
    outcome_store = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    audit_store.append(_build(event_id="m1"))
    assert summarize_by_model(audit_store, outcome_store) == {}


def test_prediction_audit_record_serializes_round_trip() -> None:
    record = _build()
    reparsed = PredictionAuditRecord.model_validate_json(record.model_dump_json())
    assert reparsed == record
