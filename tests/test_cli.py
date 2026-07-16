"""CLI is thin argument-parsing glue over paper_trading.orchestrator
(already covered end-to-end in tests/paper_trading/test_orchestrator.py).
These tests only prove the parser wiring is correct — no DB, no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from tbos.cli import _print_report, build_parser
from tbos.paper_trading.orchestrator import MatchOutcome, OrchestrationReport, SkippedEvent
from tbos.paper_trading.schemas import PaperTradingKPISnapshot


def test_paper_run_parses_with_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["paper-run"])
    assert args.command == "paper-run"
    assert args.sackmann_dir == "data/sackmann"
    assert args.tennis_data_dir == "data/tennis_data"
    assert args.resolver_store == "data/player_name_mappings.jsonl"
    assert args.bankroll == 10_000.0
    assert args.aggressiveness == 0.3
    assert args.operator == "operator"
    assert args.verbose is False
    assert callable(args.func)


def test_paper_run_parses_overrides() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "paper-run",
        "--sackmann-dir", "/custom/sackmann",
        "--tennis-data-dir", "/custom/tennis_data",
        "--resolver-store", "/custom/mappings.jsonl",
        "--bankroll", "5000",
        "--aggressiveness", "0.5",
        "--operator", "alice",
        "-v",
    ])
    assert args.sackmann_dir == "/custom/sackmann"
    assert args.tennis_data_dir == "/custom/tennis_data"
    assert args.resolver_store == "/custom/mappings.jsonl"
    assert args.bankroll == 5000.0
    assert args.aggressiveness == 0.5
    assert args.operator == "alice"
    assert args.verbose is True


def test_no_command_requires_subcommand() -> None:
    import pytest

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_print_report_with_skipped_events_does_not_crash(capsys) -> None:
    """Regression: a real production run crashed here with
    `AttributeError: 'SkippedEvent' object has no attribute 'sport_key'`
    after SkippedEvent's field was renamed to `league` (odds-api.io
    migration) without updating this print function to match.
    """
    now = datetime.now(UTC)
    report = OrchestrationReport(
        run_id=uuid.uuid4(), config_version_id=uuid.uuid4(), events_checked=2,
        matches_processed=[
            MatchOutcome(
                match_id="1", player_a_id="p1", player_b_id="p2",
                confidence_flag="ABSTAINED", action_type=None, structural_error=False,
            )
        ],
        skipped_events=[
            SkippedEvent(league="ATP - Bastad, Sweden", event_id="2", reason="no quotes"),
        ],
        kpis=PaperTradingKPISnapshot(
            run_id=uuid.uuid4(), evaluated_at=now, sample_size=1,
            coverage_rate=0.0, abstention_rate=1.0, action_type_distribution={},
            structural_errors_count=0, clv_sample_size=0, clv_mean=None, clv_positive_rate=None,
            calibration_brier_score=None, roi_directional=None, max_drawdown_simulated=None,
        ),
    )

    _print_report(report)

    output = capsys.readouterr().out
    assert "SKIPPED league=ATP - Bastad, Sweden event_id=2" in output
