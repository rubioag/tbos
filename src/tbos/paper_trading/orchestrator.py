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
- MatchContext.surface is now published when resolvable (see
  tournament_surface.py), but every OTHER MatchContext field
  (tournament_id, round, indoor_outdoor, weather_*, altitude_m, best_of)
  is a placeholder — no real source for them exists, and none of the
  five Models currently read them (checked: only `match_context.surface`
  appears in any Model's required_fields). Only `scheduled_start` is
  real (odds-api.io's own event date). If a future Model ever reads one
  of the placeholder fields, this will need real data, not this
  convention silently extended.
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
from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawMatchContextRecord,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    SourceMetadata,
    SourceUnavailableError,
    StatsSourceAdapter,
)
from tbos.data_adapters.http.odds_api_io_adapter import OddsApiIoAdapter
from tbos.data_adapters.http.odds_api_io_client import OddsApiIoClient
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore
from tbos.data_adapters.sackmann.adapter import SackmannStatsAdapter
from tbos.data_adapters.sackmann.elo import EloRatings
from tbos.data_adapters.sackmann.loader import SackmannMatchLoader
from tbos.data_adapters.sackmann.tournament_surface import (
    build_tournament_surface_lookup,
    resolve_league_surface,
)
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
# Provider-specific quota optimization (odds-api.io free tier: 100
# requests/hour): discover_upcoming_tennis_events() calls list_events()
# once per league, so a large catalog exhausts quota on discovery alone —
# real, observed live: the league catalog grew from 13 to 157 between two
# runs the same day (ITF/UTR/etc. leagues appearing), and that second run
# hit 0/100 before a single odds call. Allowlist, not a denylist, and
# based on real league name prefixes captured from actual odds-api.io
# responses (ATP/WTA/WTA125K/Challenger — the only tiers TBOS targets;
# see the provider-migration investigation) — never event IDs, so it
# stays correct as the catalog's specific leagues change day to day.
ALLOWED_LEAGUE_NAME_PREFIXES = ("ATP - ", "WTA - ", "WTA 125K - ", "Challenger - ")
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


class _StaticMatchContextAdapter(StatsSourceAdapter):
    """Wraps one already-built RawMatchContextRecord so it can be
    published through the existing, unmodified ingestion.ingest_match_context()
    — reuses CE.1's real field-mapping instead of duplicating it here.
    fetch_player_profile/fetch_player_state are never used through this
    path and always abstain.
    """

    source_id = "tournament_surface_lookup"

    def __init__(self, match_id: str, record: RawMatchContextRecord) -> None:
        self._match_id = match_id
        self._record = record

    def fetch_player_profile(self, player_id: str) -> RawPlayerStatsRecord:
        raise EntityNotFoundError("_StaticMatchContextAdapter only supplies MatchContext")

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        raise EntityNotFoundError("_StaticMatchContextAdapter only supplies MatchContext")

    def fetch_match_context(self, match_id: str) -> RawMatchContextRecord:
        if match_id != self._match_id:
            raise EntityNotFoundError(f"no static MatchContext for {match_id!r}")
        return self._record


def _build_match_context_record(
    match_id: str, surface: Surface, scheduled_start: datetime, *,
    collected_at: datetime, source_trust_score: float,
) -> RawMatchContextRecord:
    """`surface` (real, from tournament_surface.py) and `scheduled_start`
    (real, odds-api.io's own event date) are genuine. `best_of=BO3` is a
    real competition-format fact, not a guess: every tournament this
    system currently discovers (ATP 250/500, Challenger, WTA, WTA 125K)
    plays best-of-3 — only the 4 Grand Slams' men's draw is best-of-5,
    and none of those appear in odds-api.io's free-tier catalog today.
    If Slam coverage is ever added, this fixed BO3 would need revisiting.
    Every remaining field (tournament_id, round, indoor_outdoor,
    weather_*, altitude_m) has no real source anywhere in this system
    yet and is filled with the same documented "not derivable"
    placeholder convention SackmannStatsAdapter already uses for
    travel_distance_km/timezone_shift_hours — never read by any
    currently active Model (verified: only match_context.surface appears
    in any Model's required_fields).

    `collected_at` must be when the surface fact was actually derived
    (i.e. `as_of`/now), not `scheduled_start` (the match's future kickoff
    time). Real bug found live: stamping collected_at with a future
    timestamp made CE.1's own validation correctly reject the whole
    record as "collected_at is future-dated", nulling out every field
    including a perfectly valid, already-known surface.
    """
    metadata = SourceMetadata(
        source_id="tournament_surface_lookup", collected_at=collected_at,
        parser_version="1.0.0", source_priority_rank=1, source_trust_score=source_trust_score,
    )
    return RawMatchContextRecord(
        match_id=match_id, tournament_id="unknown", round="unknown", surface=surface.value,
        indoor_outdoor="unknown", weather_temp_c=0.0, weather_wind_kph=0.0,
        weather_humidity_pct=0.0, altitude_m=0.0, scheduled_start=scheduled_start,
        best_of=BestOf.BO3.value, metadata=metadata,
    )


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
        elo_rating=_env(1500.0), elo_rating_by_surface=_env({"HARD": 1500.0}),
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
    before_tier_filter = len(singles_leagues)
    singles_leagues = [
        league for league in singles_leagues
        if league.get("name", "").startswith(ALLOWED_LEAGUE_NAME_PREFIXES)
    ]
    logger.info(
        "tier filter applied (ATP/WTA/WTA125/Challenger only)",
        extra={
            "leagues_before_filter": before_tier_filter,
            "leagues_after_filter": len(singles_leagues),
            "requests_saved_estimate": before_tier_filter - len(singles_leagues),
        },
    )
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
    tournament_surface_lookup: dict[str, Surface],
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

    surface = resolve_league_surface(league, tournament_surface_lookup)
    if surface is not None:
        event_date_raw = event.get("date")
        scheduled_start = (
            datetime.fromisoformat(event_date_raw.replace("Z", "+00:00"))
            if event_date_raw else as_of
        )
        match_context_record = _build_match_context_record(
            event_id, surface, scheduled_start, collected_at=as_of, source_trust_score=0.85,
        )
        match_context_adapter = _StaticMatchContextAdapter(event_id, match_context_record)
        ingestion.ingest_match_context(session, match_context_adapter, event_id, **ingest_kwargs)
        logger.info(
            "resolved tournament surface",
            extra={"event_id": event_id, "league": league, "surface": surface.value},
        )
    else:
        logger.info(
            "no tournament surface available, MatchContext left unpublished",
            extra={"event_id": event_id, "league": league},
        )
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

    # Real bug found live: CE.2's anti-lookahead guarantee
    # (get_snapshot_as_of: published_at <= as_of) is correct for
    # backtesting, but this `as_of` is captured once at run start, before
    # any of this match's CE.1 snapshots are published. Snapshot.published_at
    # is the real DB insert wall-clock, always later — so a same-run
    # snapshot (e.g. a freshly-resolved MatchContext) could never satisfy
    # `published_at <= as_of` and was silently invisible to CE.2, with no
    # error, just missing_fields. The evaluation instant for a live run
    # must be "now, after this match's ingestion is committed" — captured
    # here, after ingest_match_context's session.commit() above — not the
    # run-start `as_of`. This does not weaken the anti-lookahead guarantee:
    # it still refuses any snapshot published after evaluation time, there
    # just aren't any, since evaluation happens immediately after ingestion.
    evaluation_as_of = datetime.now(UTC)
    bet = execute_paper_trading_cycle(
        session, run_id,
        match_id=event_id, player_a_id=player_a_id, player_b_id=player_b_id,
        as_of=evaluation_as_of,
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
    tournament_surface_lookup = build_tournament_surface_lookup(sackmann_matches)
    logger.info(
        "tournament surface lookup built",
        extra={"tournaments_with_known_surface": len(tournament_surface_lookup)},
    )

    # Built once per process from full history (never recomputed mid-run,
    # never persisted) — deterministically reconstructible from Sackmann
    # history alone. See elo.py module docstring.
    elo_ratings = EloRatings.from_matches(sackmann_matches)
    logger.info("Elo ratings built from Sackmann history")

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
    profile_adapter = SackmannStatsAdapter(sackmann_matches, elo_ratings=elo_ratings)
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
                odds_client=odds_client, tournament_surface_lookup=tournament_surface_lookup,
                ensemble_config=EnsembleConfig(),
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
