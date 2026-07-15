"""CLI is thin argument-parsing glue over paper_trading.orchestrator
(already covered end-to-end in tests/paper_trading/test_orchestrator.py).
These tests only prove the parser wiring is correct — no DB, no network.
"""

from __future__ import annotations

from tbos.cli import build_parser


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
