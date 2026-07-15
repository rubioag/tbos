"""Single operational entry point wiring together everything already
built, in the order the user specified:

    The Odds API -> Resolver -> Sackmann -> TennisDataPlayerStateAdapter
    -> CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 -> Paper Trading -> Persistence

This module contains ZERO new business logic. Every step below calls an
existing, already-tested function from its own module — CE.1 ingestion,
CE.2-CE.6 via `execute_paper_trading_cycle`, the three data adapters, and
the resolver. This file only sequences those calls and logs each step,
per the explicit requirement to register what happened and degrade
honestly rather than fabricate.

Known, documented simplifications (not bugs — real gaps in what the
pipeline currently exposes, listed so they aren't mistaken for oversights):

- `PaperTradingBetRecord` does not surface the actual stake placed, so
  `current_deployed` cannot be tracked across matches within one run from
  the public Paper Trading API alone. Each match is evaluated against a
  fresh `current_deployed=0.0` — a real limitation of the current
  Paper Trading contract, not invented data.
- The Odds API supplies no book liquidity/depth data. `BookQuote.
  available_liquidity` is set to 0.0 for every quote (the same "not
  derivable, documented" convention SackmannStatsAdapter already uses for
  travel_distance_km/timezone_shift_hours) — CE.5 will therefore
  conservatively cancel most BET_NOW plans for insufficient liquidity
  until a real liquidity-providing source exists. This is intentional:
  an honest "unknown" beats a fabricated depth number.
- No StatsSourceAdapter/OddsSourceAdapter can supply MatchContext for a
  real upcoming match (Sackmann is historical-only, The Odds API's
  adapter doesn't implement fetch_match_context). MatchContext is left
  unpublished; CE.2/CE.6 already degrade gracefully when it's absent
  (verified by existing tests) — this is not new behavior.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce5_execution.optimizer import BookQuote
from tbos.data_adapters import ingestion
from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.odds_api_adapter import OddsApiAdapter, OddsApiEventRef
from tbos.data_adapters.http.odds_api_client import OddsApiClient
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore
from tbos.data_adapters.sackmann.adapter import SackmannStatsAdapter
from tbos.data_adapters.sackmann.loader import SackmannMatchLoader
from tbos.data_adapters.tennis_data.adapter import TennisDataPlayerStateAdapter
from tbos.data_adapters.tennis_data.loader import TennisDataLoader
from tbos.inf1_config import repository as inf1_repository
from tbos.inf1_config.schemas import (
    BankrollConfig,
    ConfigVersionBundle,
    DataIngestionConfig,
    EnsembleConfig,
    RiskConfig,
)
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    InstrumentType,
    Surface,
)
from tbos.paper_trading import runner
from tbos.paper_trading.engine import evaluate_and_maybe_fail, execute_paper_trading_cycle
from tbos.paper_trading.schemas import PaperTradingKPISnapshot

logger = logging.getLogger("tbos.paper_trading.orchestrator")

TENNIS_SPORT_GROUP = "Tennis"
TOUR_SUBDIRS = ("atp", "wta")


def _load_all_tours(base_dir: Path, loader_cls: type) -> tuple[list, int]:
    """Both the Wayback downloader (Sackmann) and the tennis-data.co.uk
    convention this CLI follows write into per-tour `atp/`/`wta/`
    subdirectories under the given base directory — never flat, since
    ATP and WTA yearly files can share the same basename (e.g. both
    tours' 2026 tennis-data.co.uk export is literally named "2026.xlsx").
    Falls back to treating `base_dir` itself as flat if neither tour
    subdirectory exists, for direct/manual data placement.
    """
    tour_dirs = [base_dir / tour for tour in TOUR_SUBDIRS if (base_dir / tour).is_dir()]
    if not tour_dirs:
        tour_dirs = [base_dir]

    rows: list = []
    files_loaded = 0
    for tour_dir in tour_dirs:
        loader = loader_cls(tour_dir)
        rows.extend(loader.load_all())
        files_loaded += loader.loaded_file_count()
    return rows, files_loaded


class MatchOutcome(BaseModel):
    match_id: str
    player_a_id: str
    player_b_id: str
    confidence_flag: str
    action_type: str | None
    structural_error: bool


class SkippedEvent(BaseModel):
    sport_key: str
    event_id: str | None
    reason: str


class OrchestrationReport(BaseModel):
    run_id: uuid.UUID
    config_version_id: uuid.UUID
    events_checked: int
    matches_processed: list[MatchOutcome]
    skipped_events: list[SkippedEvent]
    kpis: PaperTradingKPISnapshot


def ensure_config_version(
    session: Session, *, bankroll_total: float, aggressiveness_threshold: float, approved_by: str,
) -> uuid.UUID:
    """Reuses the latest published ConfigVersion if one already exists —
    ConfigVersion rows are immutable/append-only (INF.1), so this avoids
    minting a new one on every CLI invocation.
    """
    existing = inf1_repository.get_latest_config_version(session)
    if existing is not None:
        logger.info(
            "reusing existing config version",
            extra={"config_version_id": str(existing.config_version_id)},
        )
        return existing.config_version_id

    bundle = ConfigVersionBundle(
        bankroll=BankrollConfig(total_capital=bankroll_total),
        risk=RiskConfig(aggressiveness_threshold=aggressiveness_threshold),
    )
    published = inf1_repository.publish_config_version(session, bundle, approved_by)
    session.commit()
    logger.info(
        "published new config version",
        extra={"config_version_id": str(published.config_version_id)},
    )
    return published.config_version_id


def _env(value: object) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )


def _representative_bundle(as_of: datetime) -> ModelInputBundle:
    """Plausible-but-synthetic bundle used only to run CE.2's v1
    compatibility battery at model bring-up — the same documented
    shortcut `bootstrap_and_activate_all` itself describes as appropriate
    "before [real historical validation] data exists" (no Shadow
    Mode/backtest pipeline is wired yet). Not used for any real
    prediction — only to prove each Model's schema/determinism contract
    once, at startup.
    """
    profile = PlayerProfile(
        player_id=_env("bootstrap"), ranking=_env(10),
        first_serve_pct_by_surface=_env({"HARD": 0.62}),
        service_points_won_pct_by_surface=_env({"HARD": 0.65}),
        aces_per_match_by_surface=_env({"HARD": 8.0}),
        hold_rate_by_surface=_env({"HARD": 0.80}),
        return_points_won_pct_by_surface=_env({"HARD": 0.35}),
        break_points_converted_pct_by_surface=_env({"HARD": 0.38}),
        style_tags=_env(["baseline"]), career_stage=_env("PEAK"), h2h_records=_env([]),
    )
    state = PlayerState(
        player_id=_env("bootstrap"), injury_flags=_env([]),
        matches_last_14d=_env(3), sets_played_last_14d=_env(7),
        travel_distance_km=_env(0.0), timezone_shift_hours=_env(0.0),
        deviation_from_baseline=_env(0.0), days_since_last_match=_env(4),
    )
    match_context = MatchContext(
        match_id=_env("bootstrap"), tournament_id=_env("t1"), round=_env("QF"),
        surface=_env(Surface.HARD), indoor_outdoor=_env("OUTDOOR"),
        weather_temp_c=_env(24.0), weather_wind_kph=_env(5.0), weather_humidity_pct=_env(40.0),
        altitude_m=_env(50.0), scheduled_start=_env(as_of), best_of=_env(BestOf.BO3),
    )
    return ModelInputBundle(
        match_id="bootstrap", player_a_id="bootstrap_a", player_b_id="bootstrap_b", as_of=as_of,
        player_a_profile=profile, player_b_profile=profile,
        player_a_state=state, player_b_state=state,
        match_context=match_context,
    )


def ensure_models_active(session: Session, *, as_of: datetime, reviewer_id: str) -> None:
    active = inf1_repository.list_active_models(session)
    if active:
        logger.info(
            "models already active, skipping bootstrap", extra={"active_count": len(active)},
        )
        return
    bundle = _representative_bundle(as_of)
    activated = bootstrap_and_activate_all(session, bundle, reviewer_id=reviewer_id)
    logger.info(
        "bootstrapped and activated models", extra={"activated_count": len(activated)},
    )


def discover_active_tennis_events(client: OddsApiClient) -> list[dict]:
    """Real, live discovery — no cached/assumed list of sport_keys.
    Returns one dict per event, each already tagged with its sport_key.
    """
    sports = client.list_sports(all_sports=True)
    active_tennis_keys = [
        s["key"] for s in sports if s.get("group") == TENNIS_SPORT_GROUP and s.get("active")
    ]
    logger.info(
        "active tennis tournaments found",
        extra={"count": len(active_tennis_keys), "sport_keys": active_tennis_keys},
    )

    events: list[dict] = []
    for sport_key in active_tennis_keys:
        try:
            sport_events = client.get_odds(sport_key)
        except (EntityNotFoundError, SourceUnavailableError) as exc:
            logger.warning(
                "could not fetch odds for active sport_key, skipping",
                extra={"sport_key": sport_key, "error": str(exc)},
            )
            continue
        for event in sport_events:
            event["sport_key"] = sport_key
            events.append(event)
    return events


def _process_event(
    session: Session, *, event: dict, run_id: uuid.UUID, config_version_id: uuid.UUID,
    ingestion_config: DataIngestionConfig,
    resolver: PlayerNameResolver, profile_adapter: SackmannStatsAdapter,
    state_adapter: TennisDataPlayerStateAdapter, odds_client: OddsApiClient,
    ensemble_config: EnsembleConfig, risk_config: RiskConfig,
    bankroll_total: float, as_of: datetime,
) -> MatchOutcome | SkippedEvent:
    sport_key = event["sport_key"]
    event_id = event.get("id")
    home_team, away_team = event.get("home_team"), event.get("away_team")

    if not event_id or not home_team or not away_team:
        return SkippedEvent(
            sport_key=sport_key, event_id=event_id, reason="event missing id/home_team/away_team",
        )

    try:
        player_a_id = resolver.resolve(home_team)
        player_b_id = resolver.resolve(away_team)
    except EntityNotFoundError as exc:
        logger.warning(
            "player name resolution abstained, skipping event",
            extra={"event_id": event_id, "error": str(exc)},
        )
        return SkippedEvent(
            sport_key=sport_key, event_id=event_id, reason=f"name resolution failed: {exc}",
        )

    registry = {
        event_id: OddsApiEventRef(
            sport_key=sport_key, event_id=event_id,
            player_a_name=home_team, player_b_name=away_team,
        )
    }
    odds_adapter = OddsApiAdapter(odds_client, registry)

    ingest_kwargs = {
        "config": ingestion_config, "config_version_id": config_version_id, "now": as_of,
    }
    ingestion.ingest_player_profile(session, profile_adapter, player_a_id, **ingest_kwargs)
    ingestion.ingest_player_profile(session, profile_adapter, player_b_id, **ingest_kwargs)
    ingestion.ingest_player_state(session, state_adapter, player_a_id, **ingest_kwargs)
    ingestion.ingest_player_state(session, state_adapter, player_b_id, **ingest_kwargs)
    market_snapshots = ingestion.ingest_odds(
        session, odds_adapter, event_id, InstrumentType.MONEYLINE, **ingest_kwargs,
    )
    session.commit()

    try:
        quotes = odds_adapter.fetch_odds(event_id, InstrumentType.MONEYLINE)
    except (EntityNotFoundError, SourceUnavailableError) as exc:
        logger.warning(
            "no usable moneyline quotes, skipping event",
            extra={"event_id": event_id, "error": str(exc)},
        )
        return SkippedEvent(sport_key=sport_key, event_id=event_id, reason=f"no quotes: {exc}")

    player_a_quotes = [q for q in quotes if q.selection == "player_a"]
    if not player_a_quotes:
        return SkippedEvent(
            sport_key=sport_key, event_id=event_id, reason="no player_a moneyline quotes",
        )

    best_quote = max(player_a_quotes, key=lambda q: q.odds)
    # No liquidity/depth data from this provider — see module docstring.
    book_quotes = [
        BookQuote(book_id=q.book_id, odds=q.odds, available_liquidity=0.0) for q in player_a_quotes
    ]

    logger.info(
        "processing match",
        extra={
            "match_id": event_id, "player_a_id": player_a_id, "player_b_id": player_b_id,
            "book_id": best_quote.book_id, "offered_odds": best_quote.odds,
            "market_snapshots_published": len(market_snapshots),
        },
    )

    bet = execute_paper_trading_cycle(
        session, run_id,
        match_id=event_id, player_a_id=player_a_id, player_b_id=player_b_id, as_of=as_of,
        ensemble_config=ensemble_config, risk_config=risk_config,
        instrument_type=InstrumentType.MONEYLINE,
        book_id=best_quote.book_id, offered_odds=best_quote.odds, quotes=book_quotes,
        closing_time_policy={}, bankroll_total=bankroll_total, current_deployed=0.0,
    )
    session.commit()

    logger.info(
        "match cycle complete",
        extra={
            "match_id": event_id, "confidence_flag": bet.confidence_flag.value,
            "action_type": bet.action_type.value if bet.action_type else None,
            "structural_error": bet.structural_error,
        },
    )

    return MatchOutcome(
        match_id=event_id, player_a_id=player_a_id, player_b_id=player_b_id,
        confidence_flag=bet.confidence_flag.value,
        action_type=bet.action_type.value if bet.action_type else None,
        structural_error=bet.structural_error,
    )


def run_paper_trading_once(
    session: Session, *,
    sackmann_dir: Path, tennis_data_dir: Path, resolver_store_path: Path,
    bankroll_total: float = 10_000.0, aggressiveness_threshold: float = 0.3,
    approved_by: str = "operator", reviewer_id: str = "operator",
    odds_client: OddsApiClient | None = None,
) -> OrchestrationReport:
    as_of = datetime.now(UTC)
    logger.info("paper-run starting", extra={"as_of": as_of.isoformat()})

    config_version_id = ensure_config_version(
        session, bankroll_total=bankroll_total,
        aggressiveness_threshold=aggressiveness_threshold, approved_by=approved_by,
    )
    ensure_models_active(session, as_of=as_of, reviewer_id=reviewer_id)

    config_row = inf1_repository.get_config_version(session, config_version_id)
    ingestion_config = (
        ConfigVersionBundle.model_validate(config_row.bundle).data_ingestion
        if config_row is not None else DataIngestionConfig()
    )

    logger.info("loading Sackmann match history", extra={"data_dir": str(sackmann_dir)})
    sackmann_matches, sackmann_files = _load_all_tours(sackmann_dir, SackmannMatchLoader)
    logger.info(
        "Sackmann history loaded",
        extra={"files": sackmann_files, "matches": len(sackmann_matches)},
    )

    logger.info(
        "loading tennis-data.co.uk recent activity", extra={"data_dir": str(tennis_data_dir)},
    )
    tennis_data_rows, tennis_data_files = _load_all_tours(tennis_data_dir, TennisDataLoader)
    logger.info(
        "tennis-data.co.uk activity loaded",
        extra={"files": tennis_data_files, "rows": len(tennis_data_rows)},
    )

    store = PlayerNameMappingStore(resolver_store_path)
    resolver = PlayerNameResolver(sackmann_matches, store)
    profile_adapter = SackmannStatsAdapter(sackmann_matches)
    state_adapter = TennisDataPlayerStateAdapter(profile_adapter, tennis_data_rows, resolver)

    if odds_client is None:
        odds_client = OddsApiClient.from_env()
    try:
        run = runner.start_run(session, config_version_id=config_version_id, as_of=as_of)
        session.commit()
        logger.info("paper trading run started", extra={"run_id": str(run.run_id)})

        events = discover_active_tennis_events(odds_client)
        if not events:
            logger.info("no active tennis events found — no data to run Paper Trading on right now")

        matches_processed: list[MatchOutcome] = []
        skipped_events: list[SkippedEvent] = []
        for event in events:
            outcome = _process_event(
                session, event=event, run_id=run.run_id, config_version_id=config_version_id,
                ingestion_config=ingestion_config,
                resolver=resolver, profile_adapter=profile_adapter, state_adapter=state_adapter,
                odds_client=odds_client, ensemble_config=EnsembleConfig(),
                risk_config=RiskConfig(aggressiveness_threshold=aggressiveness_threshold),
                bankroll_total=bankroll_total, as_of=as_of,
            )
            if isinstance(outcome, MatchOutcome):
                matches_processed.append(outcome)
            else:
                skipped_events.append(outcome)
    finally:
        odds_client.close()

    kpis = evaluate_and_maybe_fail(session, run.run_id, as_of=as_of)
    session.commit()
    logger.info(
        "paper-run finished",
        extra={
            "run_id": str(run.run_id), "events_checked": len(events),
            "matches_processed": len(matches_processed), "skipped_events": len(skipped_events),
            "structural_errors": kpis.structural_errors_count,
        },
    )

    return OrchestrationReport(
        run_id=run.run_id, config_version_id=config_version_id, events_checked=len(events),
        matches_processed=matches_processed, skipped_events=skipped_events, kpis=kpis,
    )
