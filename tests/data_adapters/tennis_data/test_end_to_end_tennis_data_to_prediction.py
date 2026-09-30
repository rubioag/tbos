"""Proves TennisDataPlayerStateAdapter's output flows through CE.1's
existing ingestion pipeline into a real CE.2 prediction, with zero
changes to any contract, schema, or CE.1/CE.2 code — the adapter is the
only new thing, everything downstream is unmodified.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.data_adapters import ingestion
from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawMatchContextRecord,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    SourceMetadata,
    StatsSourceAdapter,
)
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore
from tbos.data_adapters.reference_adapters import InMemoryStatsAdapter
from tbos.data_adapters.tennis_data.adapter import TennisDataPlayerStateAdapter
from tbos.data_adapters.tennis_data.models import TennisDataMatchRow
from tbos.inf1_config.schemas import DataIngestionConfig, EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag
from tests.ce2_prediction.factories import make_bundle
from tests.data_adapters.player_resolution.fixtures import real_player_matches

CONFIG_VERSION_ID = uuid.uuid4()
DJOKOVIC_ID = "104925"
ALCARAZ_ID = "207989"


def _metadata(now: datetime) -> SourceMetadata:
    return SourceMetadata(source_id="ref", collected_at=now, parser_version="1.0.0", source_priority_rank=1, source_trust_score=0.9)


def _profile(player_id: str, now: datetime) -> RawPlayerStatsRecord:
    return RawPlayerStatsRecord(
        player_id=player_id, ranking=5, first_serve_pct_by_surface={"HARD": 0.62},
        service_points_won_pct_by_surface={"HARD": 0.65}, aces_per_match_by_surface={"HARD": 8.0},
        hold_rate_by_surface={"HARD": 0.8}, return_points_won_pct_by_surface={"HARD": 0.35},
        break_points_converted_pct_by_surface={"HARD": 0.38}, style_tags=["baseline"], career_stage="PEAK",
        h2h_records=[], elo_rating=1500.0, elo_rating_by_surface={"HARD": 1500.0}, metadata=_metadata(now),
    )


def _stale_base_state(player_id: str, now: datetime) -> RawPlayerStateRecord:
    """Stands in for a real SackmannStatsAdapter output: real values for
    the fields tennis-data.co.uk never touches, deliberately stale
    matches_last_14d/days_since_last_match that the enrichment must
    override.
    """
    return RawPlayerStateRecord(
        player_id=player_id, injury_flags=[], matches_last_14d=0, sets_played_last_14d=0,
        travel_distance_km=42.0, timezone_shift_hours=2.0, deviation_from_baseline=0.05,
        days_since_last_match=650, metadata=_metadata(now),
    )


def _context(match_id: str, now: datetime) -> RawMatchContextRecord:
    return RawMatchContextRecord(
        match_id=match_id, tournament_id="t1", round="QF", surface="HARD", indoor_outdoor="OUTDOOR",
        weather_temp_c=24.0, weather_wind_kph=5.0, weather_humidity_pct=40.0, altitude_m=50.0,
        scheduled_start=now, best_of="BO3", metadata=_metadata(now),
    )


class _FakeSackmannBase(StatsSourceAdapter):
    source_id = "fake_sackmann_base"

    def __init__(self, now: datetime) -> None:
        self._now = now

    def fetch_player_profile(self, player_id: str):
        raise EntityNotFoundError("not used in this test")

    def fetch_match_context(self, match_id: str):
        raise EntityNotFoundError("not used in this test")

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        return _stale_base_state(player_id, self._now)


def test_tennis_data_enriched_state_flows_through_to_a_real_prediction(session: Session, tmp_path) -> None:
    as_of = datetime.now(UTC) + timedelta(minutes=1)

    store = PlayerNameMappingStore(tmp_path / "mappings.jsonl")
    resolver = PlayerNameResolver(real_player_matches(), store)
    # TennisDataPlayerStateAdapter computes "today" via datetime.now(UTC)
    # internally (not injectable, same pattern SackmannStatsAdapter
    # already uses) — match_date must be derived the same way, not via
    # date.today() (local time), to avoid a timezone/midnight-rollover
    # off-by-one between test-write time and test-run time.
    match_date = datetime.now(UTC).date() - timedelta(days=3)
    recent_rows = [
        TennisDataMatchRow(
            match_date=match_date, winner_name="Djokovic N.", loser_name="Alcaraz C.",
            winner_sets=2, loser_sets=1, comment="Completed",
        ),
    ]
    tennis_data_adapter = TennisDataPlayerStateAdapter(_FakeSackmannBase(as_of), recent_rows, resolver)

    profile_adapter = InMemoryStatsAdapter(
        profiles={DJOKOVIC_ID: _profile(DJOKOVIC_ID, as_of), ALCARAZ_ID: _profile(ALCARAZ_ID, as_of)},
        contexts={"match_1": _context("match_1", as_of)},
    )

    config = DataIngestionConfig()
    ingestion.ingest_player_profile(session, profile_adapter, DJOKOVIC_ID, config=config, config_version_id=CONFIG_VERSION_ID, now=as_of)
    ingestion.ingest_player_profile(session, profile_adapter, ALCARAZ_ID, config=config, config_version_id=CONFIG_VERSION_ID, now=as_of)
    ingestion.ingest_match_context(session, profile_adapter, "match_1", config=config, config_version_id=CONFIG_VERSION_ID, now=as_of)

    # This is the only call that matters for this test: the SAME existing
    # ingestion function, given the new adapter — no CE.1 code changed.
    snapshot_a = ingestion.ingest_player_state(session, tennis_data_adapter, DJOKOVIC_ID, config=config, config_version_id=CONFIG_VERSION_ID, now=as_of)
    snapshot_b = ingestion.ingest_player_state(session, tennis_data_adapter, ALCARAZ_ID, config=config, config_version_id=CONFIG_VERSION_ID, now=as_of)
    session.commit()

    assert snapshot_a is not None
    # Enriched (tennis-data.co.uk) value, not the stale base value.
    assert snapshot_a.fields["matches_last_14d"]["value"] == 1
    assert snapshot_a.fields["days_since_last_match"]["value"] == 3
    # Untouched field, taken straight from the base (Sackmann-shaped) record.
    assert snapshot_a.fields["travel_distance_km"]["value"] == 42.0
    assert snapshot_a.fields["deviation_from_baseline"]["value"] == 0.05
    assert snapshot_b is not None

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id=DJOKOVIC_ID, player_b_id=ALCARAZ_ID,
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )

    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)
    assert prediction.probability_player_a is not None
    assert 0.0 < prediction.probability_player_a < 1.0
