"""End-to-end: real CE.1 snapshots -> CE.2 Prediction Layer -> CE.3 Edge
Description Engine, across multiple instruments for the same match.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce3_edge import repository as ce3_repository
from tbos.ce3_edge.engine import build_edge_description
from tbos.inf1_config.schemas import EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag, InstrumentType

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile, make_state

CONFIG_VERSION_ID = uuid.uuid4()


def _publish_full_data(session: Session, *, as_of: datetime) -> None:
    h2h = [{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_a", fields=make_profile("player_a", h2h_records=h2h), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_b", fields=make_profile("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_a", fields=make_state("player_a"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_b", fields=make_state("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="MatchContext", entity_id="match_1", fields=make_match_context(), config_version_id=CONFIG_VERSION_ID)
    session.commit()


def test_full_ce2_to_ce3_pipeline(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)

    published = []
    for instrument, book, odds in [
        (InstrumentType.MONEYLINE, "book_a", 1.90),
        (InstrumentType.MONEYLINE, "book_b", 2.05),
        (InstrumentType.HANDICAP, "book_a", 1.85),
    ]:
        edge = build_edge_description(
            prediction, instrument_type=instrument, book_id=book, offered_odds=odds, as_of=as_of,
        )
        assert edge is not None
        ce3_repository.publish_edge_description(session, edge)
        published.append(edge)
    session.commit()

    rows = ce3_repository.list_for_match(session, "match_1")
    assert len(rows) == 3

    # Different offered odds against the same probability produce
    # genuinely different EV/robustness — the pipeline isn't just echoing
    # a constant regardless of market input.
    evs = {e.offered_odds: e.ev_distribution.expected for e in published}
    assert len(set(evs.values())) > 1


def test_ce3_never_influences_ce2_output(session: Session) -> None:
    """Market Independence, exercised end-to-end: building multiple
    EdgeDescriptions against wildly different offered odds must never
    change the underlying probability CE.2 already computed.
    """
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)
    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    original_probability = prediction.probability_player_a

    for odds in (1.2, 5.0, 50.0):
        edge = build_edge_description(
            prediction, instrument_type=InstrumentType.MONEYLINE, book_id="book_x", offered_odds=odds, as_of=as_of,
        )
        assert edge.probability_used == original_probability
    assert prediction.probability_player_a == original_probability
