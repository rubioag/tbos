from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tbos.ce2_prediction.prediction_engine import PredictionOutput
from tbos.ce3_edge import repository
from tbos.ce3_edge.engine import build_edge_description
from tbos.ce3_edge.schemas import EdgeDescription
from tbos.inf1_config.taxonomy import ConfidenceFlag, EdgeLifecycle, EdgeSourceCategory, InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prediction(*, probability: float | None = 0.6, uncertainty: float | None = 0.1) -> PredictionOutput:
    return PredictionOutput(
        match_id="match_1", confidence_flag=ConfidenceFlag.NORMAL if probability else ConfidenceFlag.ABSTAINED,
        probability_player_a=probability, log_odds=0.4, uncertainty=uncertainty, evidence_quality=0.7,
        participating_models=["serve_model"], abstained_models=[], triggered_abstention_rules=[],
        ensemble_version="1.0.0",
    )


def test_build_edge_description_produces_consistent_pipeline_output() -> None:
    edge = build_edge_description(
        _prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.0, as_of=NOW,
    )
    assert edge is not None
    assert edge.probability_used == 0.6
    assert edge.fair_odds == 1 / 0.6
    assert edge.ev_distribution.expected == 0.6 * 2.0 - 1.0
    assert edge.edge_robustness.score >= 0.0
    assert edge.edge_persistence.persistence_class is not None
    assert edge.edge_lifecycle == EdgeLifecycle.UNKNOWN  # default category is MODEL -> classify_lifecycle -> UNKNOWN


def test_build_edge_description_returns_none_when_no_probability() -> None:
    edge = build_edge_description(
        _prediction(probability=None, uncertainty=None), instrument_type=InstrumentType.MONEYLINE,
        book_id="book_a", offered_odds=2.0, as_of=NOW,
    )
    assert edge is None


def test_edge_description_never_has_a_ranking_field() -> None:
    """Structural guard for Decision Independence: no rank/priority/score-
    for-selection field exists anywhere in the schema.
    """
    forbidden_names = {"rank", "priority", "selection_score", "recommended"}
    assert forbidden_names.isdisjoint(EdgeDescription.model_fields.keys())


def test_edge_source_category_defaults_to_model() -> None:
    edge = build_edge_description(
        _prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.0, as_of=NOW,
    )
    assert edge.edge_source_category == EdgeSourceCategory.MODEL


def test_publish_and_retrieve_edge_description(session: Session) -> None:
    edge = build_edge_description(
        _prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.0, as_of=NOW,
    )
    repository.publish_edge_description(session, edge)
    session.commit()

    fetched = repository.get_edge_description(session, edge.edge_id)
    assert fetched is not None
    assert fetched.payload["fair_odds"] == edge.fair_odds


def test_list_for_match_returns_all_published_instruments_unordered(session: Session) -> None:
    for instrument, odds in [(InstrumentType.MONEYLINE, 2.0), (InstrumentType.HANDICAP, 1.9)]:
        edge = build_edge_description(
            _prediction(), instrument_type=instrument, book_id="book_a", offered_odds=odds, as_of=NOW,
        )
        repository.publish_edge_description(session, edge)
    session.commit()

    rows = repository.list_for_match(session, "match_1")
    assert len(rows) == 2
    assert {r.instrument_type for r in rows} == {"MONEYLINE", "HANDICAP"}
