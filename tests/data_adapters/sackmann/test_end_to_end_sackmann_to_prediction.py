"""Proves the actual goal: zero paid stats API. Sackmann-derived stats
(via ingestion.py, contract unchanged) + a MatchContext published the way
it would arrive from the odds provider in real operation -> a genuine
CE.2 prediction with only The Odds API as the mandatory online dependency.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.data_adapters import ingestion
from tbos.data_adapters.sackmann.adapter import SackmannStatsAdapter
from tbos.inf1_config.schemas import DataIngestionConfig, EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag

from tests.ce2_prediction.factories import make_bundle, make_match_context
from tests.data_adapters.sackmann.fixtures import all_matches

CONFIG_VERSION_ID = uuid.uuid4()


def test_sackmann_derived_stats_flow_through_to_a_real_prediction(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    adapter = SackmannStatsAdapter(all_matches())
    config = DataIngestionConfig()

    assert ingestion.ingest_player_profile(session, adapter, "p1", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_profile(session, adapter, "p2", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_state(session, adapter, "p1", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_state(session, adapter, "p2", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None

    # MatchContext does NOT come from Sackmann (by design) — this simulates
    # what would arrive from The Odds API's event metadata in real operation.
    ce1_repository.publish_snapshot(
        session, entity_type="MatchContext", entity_id="match_1", fields=make_match_context(),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )

    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)
    assert prediction.probability_player_a is not None
    assert 0.0 < prediction.probability_player_a < 1.0
    assert len(prediction.participating_models) >= 3


def test_sackmann_adapter_never_reached_over_network() -> None:
    """Structural sanity check: SackmannStatsAdapter has no HTTP/requests
    dependency anywhere in its module — it is purely local computation.
    """
    import tbos.data_adapters.sackmann.adapter as adapter_module

    with open(adapter_module.__file__, encoding="utf-8") as f:
        source = f.read()
    assert "requests" not in source
    assert "httpx" not in source
    assert "urllib" not in source
