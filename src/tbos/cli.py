"""TBOS operational CLI. Single entry point: `tbos paper-run` runs one
real Paper Trading cycle end-to-end (see paper_trading.orchestrator for
the actual pipeline — this module is argument parsing, logging setup,
and a human-readable summary only, zero pipeline logic of its own).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tbos.db import ensure_schema, get_engine
from tbos.paper_trading.orchestrator import run_paper_trading_once


class _ExtraFieldsFormatter(logging.Formatter):
    """Every structured `extra={...}` call in the pipeline stays visible
    on the console — required so each step is "claramente registrado",
    not just a bare message string.
    """

    _STANDARD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in self._STANDARD_KEYS and k != "message"
        }
        if not extras:
            return base
        extras_str = " ".join(f"{k}={v!r}" for k, v in extras.items())
        return f"{base} | {extras_str}"


def _configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ExtraFieldsFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("tbos")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False


def _cmd_paper_run(args: argparse.Namespace) -> int:
    _configure_logging(args.verbose)
    from sqlalchemy.orm import sessionmaker

    ensure_schema()
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = session_factory()
    try:
        report = run_paper_trading_once(
            session,
            sackmann_dir=Path(args.sackmann_dir),
            tennis_data_dir=Path(args.tennis_data_dir),
            resolver_store_path=Path(args.resolver_store),
            bankroll_total=args.bankroll,
            aggressiveness_threshold=args.aggressiveness,
            approved_by=args.operator,
            reviewer_id=args.operator,
        )
    finally:
        session.close()

    _print_report(report)
    return 0


def _print_report(report) -> None:  # noqa: ANN001 - OrchestrationReport, avoids import cycle in type position only
    print()
    print("=== TBOS Paper Trading — run summary ===")
    print(f"run_id: {report.run_id}")
    print(f"config_version_id: {report.config_version_id}")
    print(f"tennis events checked (odds-api.io, upcoming/pre-match only): {report.events_checked}")
    print(f"matches processed: {len(report.matches_processed)}")
    print(f"events skipped: {len(report.skipped_events)}")

    if not report.matches_processed and not report.skipped_events:
        print()
        print(
            "No hay datos para ejecutar Paper Trading — "
            "0 partidos de tenis pendientes en odds-api.io ahora mismo."
        )

    for outcome in report.matches_processed:
        print(
            f"  match={outcome.match_id} players=({outcome.player_a_id}, {outcome.player_b_id}) "
            f"confidence={outcome.confidence_flag} action={outcome.action_type} "
            f"structural_error={outcome.structural_error}"
        )
    for skipped in report.skipped_events:
        print(
            f"  SKIPPED league={skipped.league} event_id={skipped.event_id} "
            f"reason={skipped.reason}"
        )

    print()
    print("KPIs:")
    print(f"  coverage_rate: {report.kpis.coverage_rate}")
    print(f"  abstention_rate: {report.kpis.abstention_rate}")
    print(f"  structural_errors_count: {report.kpis.structural_errors_count}")
    print(f"  clv_mean: {report.kpis.clv_mean}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tbos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_run = subparsers.add_parser(
        "paper-run",
        help="Run one real Paper Trading cycle: odds-api.io -> Resolver -> Sackmann -> "
             "TennisDataPlayerStateAdapter -> CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 -> "
             "Paper Trading -> Persistence.",
    )
    paper_run.add_argument(
        "--sackmann-dir", default="data/sackmann",
        help="Directory with Sackmann ATP/WTA CSVs (default: data/sackmann)",
    )
    paper_run.add_argument(
        "--tennis-data-dir", default="data/tennis_data",
        help="Directory with tennis-data.co.uk xlsx files (default: data/tennis_data)",
    )
    paper_run.add_argument(
        "--resolver-store", default="data/player_name_mappings.jsonl",
        help="Append-only player-name resolution cache (default: data/player_name_mappings.jsonl)",
    )
    paper_run.add_argument(
        "--bankroll", type=float, default=10_000.0,
        help="Paper bankroll total (default: 10000.0, no real money)",
    )
    paper_run.add_argument(
        "--aggressiveness", type=float, default=0.3,
        help="RiskConfig.aggressiveness_threshold, 0-1 (default: 0.3)",
    )
    paper_run.add_argument(
        "--operator", default="operator",
        help="Identity recorded as config approver / model-bootstrap reviewer (default: operator)",
    )
    paper_run.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging")
    paper_run.set_defaults(func=_cmd_paper_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
