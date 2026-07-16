"""Single operational entry point wiring together everything already
built, in the order the user specified:

    odds-api.io -> Resolver -> Sackmann -> TennisDataPlayerStateAdapter
    -> CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 -> Paper Trading -> Persistence

Odds provider migrated from The Odds API to odds-api.io: verified via
real API calls that The Odds API's free tier does not cover ATP/WTA
250-level tournaments at all (Bastad, Gstaad, Umag, Iasi, Athens absent
from its catalog — confirmed both by full catalog dump and by
UNKNOWN_SPORT errors on every plausible sport_key guess), while
odds-api.io's `/v3/leagues?sport=tennis` lists all five with real,
non-zero event counts, and `/v3/odds` returns real pre-match moneyline
prices for at least one of the two free-tier-allowed bookmakers (Bet365,
Betfair Exchange). Same `OddsSourceAdapter` contract, only the client and
adapter implementation changed — nothing else in this file's downstream
pipeline (CE.1 ingestion, CE.2-CE.6) needed to change.

This module contains ZERO new business logic beyond that adapter swap.
Every step below calls an existing, already-tested function from its own
module — CE.1 ingestion, CE.2-CE.6 via `execute_paper_trading_cycle`, the
three data adapters, and the resolver. This file only sequences those
calls and logs each step, per the explicit requirement to register what
happened and degrade honestly rather than fabricate.

Known, documented simplifications (not bugs — real gaps in what the
pipeline currently exposes, listed so they aren't mistaken for oversights):

- `PaperTradingBetRecord` does not surface the actual stake placed, so
  `current_deployed` cannot be tracked across matches within one run from
  the public Paper Trading API alone. Each match is evaluated against a
  fresh `current_deployed=0.0` — a real limitation of the current
  Paper Trading contract, not invented data.
- odds-api.io's free tier restricts callers to at most 2 bookmakers
  (Bet365, Betfair Exchange) and supplies no book liquidity/depth data
  for either. `BookQuote.available_liquidity` is set to 0.0 for every
  quote (the same "not derivable, documented" convention
  SackmannStatsAdapter already uses for travel_distance_km/
  timezone_shift_hours) — CE.5 will therefore conservatively cancel most
  BET_NOW plans for insufficient liquidity until a real
  liquidity-providing source exists. This is intentional: an honest
  "unknown" beats a fabricated depth number.
- No StatsSourceAdapter/OddsSourceAdapter can supply MatchContext for a
  real upcoming match (Sackmann is historical-only, odds-api.io's
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
from tbos.data_adapters.http.odds_api_io_adapter import OddsApiIoAdapter
from tbos.data_adapters.http.odds_api_io_client import OddsApiIoClient
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

TOUR_SUBDIRS = ("atp", "wta")
# Real, deterministic filter — not a heuristic: odds-api.io names doubles
# leagues with this exact ", Doubles" suffix (confirmed live, e.g. "ATP -
# Bastad, Sweden, Doubles"). TBOS's contract is 2-player singles only.
DOUBLES_LEAGUE_SUFFIX = ", Doubles"
# odds-api.io only reports pre-match/scheduled events under this status
# (confirmed live: "live" and "settled" are the other two values seen).
UPCOMING_EVENT_STATUS = "pending"


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
    league: str
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


def discover_upcoming_tennis_events(client: OddsApiIoClient) -> list[dict]:
    """Real, live discovery — no cached/assumed list of leagues.
    odds-api.io models tennis as one sport with many `league` slugs (one
    per tournament, singles and doubles separate) rather than The Odds
    API's one-sport_key-per-tournament model. Returns one dict per
    singles event, each already tagged with its league name, restricted
    to `status="pending"` (not yet started — pre-match).
    """
    try:
        leagues = client.list_leagues(sport="tennis")
    except (EntityNotFoundError, SourceUnavailableError) as exc:
        # Real gap found running this live: a rate-limit/outage failure
        # on this very first call used to crash the whole CLI with an
        # unhandled traceback instead of degrading — the same "no data
        # available" outcome the zero-events path already reports
        # cleanly. A provider being unreachable is not a reason to
        # fabricate a crash any more than it's a reason to fabricate data.
        logger.warning(
            "could not list tennis leagues, treating as no events available",
            extra={"error": str(exc)},
        )
        return []

    singles_leagues = [
        league for league in leagues
        if league.get("eventsCount", 0) > 0
        and not league.get("name", "").endswith(DOUBLES_LEAGUE_SUFFIX)
    ]
    league_names = [league_["name"] for league_ in singles_leagues]
    logger.info(
        "tennis leagues with scheduled events found",
        extra={"count": len(singles_leagues), "leagues": league_names},
    )

    events: list[dict] = []
    for league in singles_leagues:
        league_slug = league["slug"]
        try:
            league_events = client.list_events(sport="tennis", league=league_slug)
        except (EntityNotFoundError, SourceUnavailableError) as exc:
            logger.warning(
                "could not fetch events for league, skipping",
                extra={"league": league_slug, "error": str(exc)},
            )
            continue
        for event in league_events:
            if event.get("status") != UPCOMING_EVENT_STATUS:
                continue
            event["league"] = league["name"]
            events.append(event)
    return events


def _process_event(
    session: Session, *, event: dict, run_id: uuid.UUID, config_version_id: uuid.UUID,
    ingestion_config: DataIngestionConfig,
    resolver: PlayerNameResolver, profile_adapter: SackmannStatsAdapter,
    state_adapter: TennisDataPlayerStateAdapter, odds_client: OddsApiIoClient,
    ensemble_config: EnsembleConfig, risk_config: RiskConfig,
    bankroll_total: float, as_of: datetime,
) -> MatchOutcome | SkippedEvent:
    league = event["league"]
    raw_event_id = event.get("id")
    event_id = str(raw_event_id) if raw_event_id is not None else None
    home_name, away_name = event.get("home"), event.get("away")

    if not event_id or not home_name or not away_name:
        return SkippedEvent(
            league=league, event_id=event_id, reason="event missing id/home/away",
        )

    try:
        player_a_id = resolver.resolve(home_name)
        player_b_id = resolver.resolve(away_name)
    except EntityNotFoundError as exc:
        logger.warning(
            "player name resolution abstained, skipping event",
            extra={"event_id": event_id, "error": str(exc)},
        )
        return SkippedEvent(
            league=league, event_id=event_id, reason=f"name resolution failed: {exc}",
        )

    # odds-api.io event ids are globally unique and directly queryable —
    # unlike The Odds API, no match_id -> (sport_key, event) registry is
    # needed here.
    odds_adapter = OddsApiIoAdapter(odds_client)

    # Real bug found running this orchestrator against production data:
    # calling both ingestion.ingest_odds() (which calls adapter.fetch_odds
    # internally) AND a second, separate adapter.fetch_odds() call right
    # after burned odds-api.io's 100-requests/hour free-tier quota twice
    # as fast as necessary, exhausting it partway through a single real
    # run (~380 real events on the day this was found — most got skipped
    # with "rate limit hit" once quota ran out). Fix: fetch once here and
    # skip the separate CE.1 MarketSnapshot publish entirely —
    # execute_paper_trading_cycle takes offered_odds/quotes as direct
    # parameters, it never reads MarketSnapshot back from CE.1, so that
    # publish was pure (unread) audit trail, not a functional dependency.
    # Re-implementing ingestion.ingest_odds()'s field-mapping here instead
    # of calling it would duplicate CE.1 logic, which is explicitly out
    # of scope — dropping the redundant call is the correct minimal fix.
    try:
        quotes = odds_adapter.fetch_odds(event_id, InstrumentType.MONEYLINE)
    except (EntityNotFoundError, SourceUnavailableError) as exc:
        logger.warning(
            "no usable moneyline quotes, skipping event",
            extra={"event_id": event_id, "error": str(exc)},
        )
        return SkippedEvent(league=league, event_id=event_id, reason=f"no quotes: {exc}")

    ingest_kwargs = {
        "config": ingestion_config, "config_version_id": config_version_id, "now": as_of,
    }
    ingestion.ingest_player_profile(session, profile_adapter, player_a_id, **ingest_kwargs)
    ingestion.ingest_player_profile(session, profile_adapter, player_b_id, **ingest_kwargs)
    ingestion.ingest_player_state(session, state_adapter, player_a_id, **ingest_kwargs)
    ingestion.ingest_player_state(session, state_adapter, player_b_id, **ingest_kwargs)
    session.commit()

    player_a_quotes = [q for q in quotes if q.selection == "player_a"]
    if not player_a_quotes:
        return SkippedEvent(
            league=league, event_id=event_id, reason="no player_a moneyline quotes",
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
            "quotes_fetched": len(quotes),
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
    odds_client: OddsApiIoClient | None = None,
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
        odds_client = OddsApiIoClient.from_env()
    try:
        run = runner.start_run(session, config_version_id=config_version_id, as_of=as_of)
        session.commit()
        logger.info("paper trading run started", extra={"run_id": str(run.run_id)})

        events = discover_upcoming_tennis_events(odds_client)
        if not events:
            logger.info(
                "no upcoming tennis events found — no data to run Paper Trading on right now"
            )

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
