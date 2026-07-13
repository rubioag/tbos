"""Proves the adapter contract actually connects all the way through:
external (reference) adapter -> ingestion -> CE.1 snapshots -> CE.2
prediction. This is the real point of building adapters at all.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.data_adapters import ingestion
from tbos.data_adapters.contracts import RawMatchContextRecord, RawPlayerStateRecord, RawPlayerStatsRecord, SourceMetadata
from tbos.data_adapters.reference_adapters import InMemoryStatsAdapter

from tbos.inf1_config.schemas import DataIngestionConfig, EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag

from tests.ce2_prediction.factories import make_bundle

CONFIG_VERSION_ID = uuid.uuid4()


def _metadata(now: datetime) -> SourceMetadata:
    return SourceMetadata(source_id="ref", collected_at=now, parser_version="1.0.0", source_priority_rank=1, source_trust_score=0.9)


def _profile(player_id: str, now: datetime, *, h2h: list[dict] | None = None) -> RawPlayerStatsRecord:
    return RawPlayerStatsRecord(
        player_id=player_id, ranking=5, first_serve_pct_by_surface={"HARD": 0.62},
        service_points_won_pct_by_surface={"HARD": 0.65}, aces_per_match_by_surface={"HARD": 8.0},
        hold_rate_by_surface={"HARD": 0.8}, return_points_won_pct_by_surface={"HARD": 0.35},
        break_points_converted_pct_by_surface={"HARD": 0.38}, style_tags=["baseline"], career_stage="PEAK",
        h2h_records=h2h or [], metadata=_metadata(now),
    )


def _state(player_id: str, now: datetime) -> RawPlayerStateRecord:
    return RawPlayerStateRecord(
        player_id=player_id, injury_flags=[], matches_last_14d=3, sets_played_last_14d=7,
        travel_distance_km=100.0, timezone_shift_hours=1.0, deviation_from_baseline=0.0,
        days_since_last_match=4, metadata=_metadata(now),
    )


def _context(match_id: str, now: datetime) -> RawMatchContextRecord:
    return RawMatchContextRecord(
        match_id=match_id, tournament_id="t1", round="QF", surface="HARD", indoor_outdoor="OUTDOOR",
        weather_temp_c=24.0, weather_wind_kph=5.0, weather_humidity_pct=40.0, altitude_m=50.0,
        scheduled_start=now, best_of="BO3", metadata=_metadata(now),
    )


def test_reference_adapter_data_flows_through_to_a_real_prediction(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)

    stats_adapter = InMemoryStatsAdapter(
        profiles={
            "player_a": _profile("player_a", as_of, h2h=[{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]),
            "player_b": _profile("player_b", as_of),
        },
        states={"player_a": _state("player_a", as_of), "player_b": _state("player_b", as_of)},
        contexts={"match_1": _context("match_1", as_of)},
    )

    config = DataIngestionConfig()
    assert ingestion.ingest_player_profile(session, stats_adapter, "player_a", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_profile(session, stats_adapter, "player_b", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_state(session, stats_adapter, "player_a", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_player_state(session, stats_adapter, "player_b", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    assert ingestion.ingest_match_context(session, stats_adapter, "match_1", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of) is not None
    session.commit()

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )

    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)
    assert prediction.probability_player_a is not None
    assert 0.0 < prediction.probability_player_a < 1.0
    assert len(prediction.participating_models) >= 3


def test_missing_adapter_data_yields_abstained_prediction_not_a_crash(session: Session) -> None:
    """No data ingested at all — the system must abstain honestly, never
    error out or fabricate a prediction from nothing.
    """
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="never_ingested_match", player_a_id="ghost_a", player_b_id="ghost_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    assert prediction.confidence_flag == ConfidenceFlag.ABSTAINED
