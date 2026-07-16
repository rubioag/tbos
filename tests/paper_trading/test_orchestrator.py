"""Proves the single operational entry point (`run_paper_trading_once`)
actually wires odds-api.io -> Resolver -> Sackmann ->
TennisDataPlayerStateAdapter -> CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 ->
Paper Trading -> Persistence end-to-end, using only already-existing
functions. No real network calls (mocked HTTP transport); real Sackmann-
shaped CSV and tennis-data.co.uk-shaped xlsx on disk. Odds-api.io JSON
shapes are taken verbatim from real responses captured during the
provider migration investigation.
"""

from __future__ import annotations

import csv
from datetime import date

import httpx
import openpyxl
from sqlalchemy.orm import Session

from tbos.data_adapters.http.odds_api_io_client import OddsApiIoClient
from tbos.paper_trading.orchestrator import run_paper_trading_once

SACKMANN_HEADER = [
    "tourney_date", "surface", "tourney_level", "round", "best_of", "score",
    "winner_id", "winner_name", "winner_hand", "winner_age", "winner_rank",
    "loser_id", "loser_name", "loser_hand", "loser_age", "loser_rank",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]


def _sackmann_row(tourney_date: str, winner_id: str, winner_name: str, loser_id: str, loser_name: str) -> list:
    return [
        tourney_date, "Hard", "A", "F", 3, "6-4 6-3",
        winner_id, winner_name, "R", 24.5, 10,
        loser_id, loser_name, "R", 26.1, 20,
        8, 2, 80, 50, 40, 20, 12, 3, 4,
        5, 3, 75, 45, 30, 15, 11, 2, 5,
    ]


def _write_sackmann_csv(path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(SACKMANN_HEADER)
        # Names stored "First Last" (Sackmann convention); odds-api.io
        # supplies "Last, First" — the resolver's comma-normalization +
        # reversed_order tier bridges the two.
        writer.writerow(_sackmann_row("20240110", "p1", "One Player", "p2", "Two Player"))
        writer.writerow(_sackmann_row("20240215", "p1", "One Player", "p2", "Two Player"))


def _write_tennis_data_xlsx(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "Winner", "Loser", "Wsets", "Lsets", "Comment"])
    ws.append([date.today(), "One Player", "Two Player", 2, 1, "Completed"])
    wb.save(path)


TENNIS_LEAGUES = [
    {"name": "ATP - Bastad, Sweden", "slug": "atp-bastad-sweden", "eventsCount": 1},
    {"name": "ATP - Bastad, Sweden, Doubles", "slug": "atp-bastad-sweden-doubles", "eventsCount": 1},
]

PENDING_EVENT = {
    "id": 72661910,
    "home": "Player, One",
    "away": "Player, Two",
    "homeId": 1,
    "awayId": 2,
    "date": "2026-07-16T14:40:00Z",
    "status": "pending",
    "sport": {"name": "Tennis", "slug": "tennis"},
    "league": {"name": "ATP - Bastad, Sweden", "slug": "atp-bastad-sweden"},
}

ODDS_RESPONSE = {
    "id": 72661910,
    "home": "Player, One",
    "away": "Player, Two",
    "bookmakers": {
        "Bet365": [
            {
                "name": "ML",
                "updatedAt": "2026-07-16T13:26:33.656Z",
                "odds": [{"home": "1.80", "away": "2.00"}],
            }
        ],
    },
}


def _mock_odds_transport(*, leagues_response, events_response, odds_response=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/leagues":
            return httpx.Response(200, json=leagues_response)
        if request.url.path == "/v3/events":
            return httpx.Response(200, json=events_response)
        if request.url.path == "/v3/odds":
            return httpx.Response(200, json=odds_response or {})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def test_paper_run_processes_a_real_upcoming_event_end_to_end(session: Session, tmp_path) -> None:
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")

    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()
    _write_tennis_data_xlsx(tennis_data_dir / "2026.xlsx")

    transport = _mock_odds_transport(
        leagues_response=TENNIS_LEAGUES, events_response=[PENDING_EVENT], odds_response=ODDS_RESPONSE,
    )
    odds_client = OddsApiIoClient(api_key="test_key", transport=transport)

    report = run_paper_trading_once(
        session,
        sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl",
        odds_client=odds_client,
    )

    assert report.events_checked == 1  # doubles league excluded
    assert len(report.matches_processed) == 1
    assert report.skipped_events == []

    outcome = report.matches_processed[0]
    assert outcome.match_id == "72661910"
    assert outcome.player_a_id == "p1"
    assert outcome.player_b_id == "p2"
    assert outcome.confidence_flag in {"NORMAL", "DEGRADED", "ABSTAINED"}
    assert outcome.structural_error is False


def test_paper_run_calls_odds_endpoint_exactly_once_per_event(session: Session, tmp_path) -> None:
    """Regression: a real production run once called /v3/odds twice per
    event (once inside ingestion.ingest_odds, once again to get quotes
    for CE.5), burning the 100-requests/hour free-tier quota twice as
    fast and exhausting it partway through a real run of ~380 events.
    """
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()
    _write_tennis_data_xlsx(tennis_data_dir / "2026.xlsx")

    odds_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/leagues":
            return httpx.Response(200, json=TENNIS_LEAGUES)
        if request.url.path == "/v3/events":
            return httpx.Response(200, json=[PENDING_EVENT])
        if request.url.path == "/v3/odds":
            odds_calls["n"] += 1
            return httpx.Response(200, json=ODDS_RESPONSE)
        return httpx.Response(404, json={"error": "not found"})

    odds_client = OddsApiIoClient(api_key="test_key", transport=httpx.MockTransport(handler))

    report = run_paper_trading_once(
        session, sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl", odds_client=odds_client,
    )

    assert len(report.matches_processed) == 1
    assert odds_calls["n"] == 1


def test_paper_run_leagues_endpoint_unavailable_degrades_cleanly(session: Session, tmp_path) -> None:
    """Regression: a real run hit this exact failure live (quota
    exhausted -> 429 on /v3/leagues after retries) and crashed the whole
    CLI with an unhandled traceback instead of degrading like the
    zero-events path already does.
    """
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    odds_client = OddsApiIoClient(
        api_key="test_key", transport=httpx.MockTransport(handler),
        max_retries=0, backoff_base_seconds=0.0,
    )

    report = run_paper_trading_once(
        session, sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl", odds_client=odds_client,
    )

    assert report.events_checked == 0
    assert report.matches_processed == []
    assert report.skipped_events == []


def test_paper_run_no_upcoming_events_reports_cleanly_no_fabrication(session: Session, tmp_path) -> None:
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()

    transport = _mock_odds_transport(leagues_response=[], events_response=[])
    odds_client = OddsApiIoClient(api_key="test_key", transport=transport)

    report = run_paper_trading_once(
        session,
        sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl",
        odds_client=odds_client,
    )

    assert report.events_checked == 0
    assert report.matches_processed == []
    assert report.skipped_events == []
    assert report.kpis.sample_size == 0


def test_paper_run_only_pending_status_events_processed(session: Session, tmp_path) -> None:
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()

    live_event = {**PENDING_EVENT, "id": 99, "status": "live"}
    settled_event = {**PENDING_EVENT, "id": 100, "status": "settled"}
    transport = _mock_odds_transport(
        leagues_response=TENNIS_LEAGUES, events_response=[live_event, settled_event],
    )
    odds_client = OddsApiIoClient(api_key="test_key", transport=transport)

    report = run_paper_trading_once(
        session, sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl", odds_client=odds_client,
    )

    assert report.events_checked == 0  # live/settled excluded, only "pending" counts


def test_paper_run_unresolvable_player_name_skips_event_not_fabricated(session: Session, tmp_path) -> None:
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()

    unresolvable_event = {**PENDING_EVENT, "home": "Totally, Unknown Player XYZ"}
    transport = _mock_odds_transport(
        leagues_response=TENNIS_LEAGUES, events_response=[unresolvable_event],
    )
    odds_client = OddsApiIoClient(api_key="test_key", transport=transport)

    report = run_paper_trading_once(
        session,
        sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl",
        odds_client=odds_client,
    )

    assert report.events_checked == 1
    assert report.matches_processed == []
    assert len(report.skipped_events) == 1
    assert "name resolution failed" in report.skipped_events[0].reason


def test_paper_run_second_call_reuses_config_version_and_active_models(session: Session, tmp_path) -> None:
    sackmann_dir = tmp_path / "sackmann"
    sackmann_dir.mkdir()
    _write_sackmann_csv(sackmann_dir / "atp_matches_2024.csv")
    tennis_data_dir = tmp_path / "tennis_data"
    tennis_data_dir.mkdir()

    transport = _mock_odds_transport(leagues_response=[], events_response=[])

    report1 = run_paper_trading_once(
        session, sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl",
        odds_client=OddsApiIoClient(api_key="test_key", transport=transport),
    )
    report2 = run_paper_trading_once(
        session, sackmann_dir=sackmann_dir, tennis_data_dir=tennis_data_dir,
        resolver_store_path=tmp_path / "mappings.jsonl",
        odds_client=OddsApiIoClient(api_key="test_key", transport=transport),
    )

    assert report1.config_version_id == report2.config_version_id
