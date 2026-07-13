import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config.schemas import EnsembleConfig, RiskConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag, InstrumentType, PaperTradingStatus
from tbos.paper_trading import engine as pt_engine
from tbos.paper_trading import repository, runner

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_cycle_with_no_ingested_data_records_abstained_not_crash(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    bet = pt_engine.execute_paper_trading_cycle(
        session, run.run_id, match_id="ghost_match", player_a_id="ghost_a", player_b_id="ghost_b",
        as_of=NOW, ensemble_config=EnsembleConfig(), risk_config=RiskConfig(aggressiveness_threshold=0.1),
        instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.0, quotes=[],
        closing_time_policy={}, bankroll_total=10_000.0, current_deployed=0.0,
    )
    session.commit()

    assert bet.confidence_flag == ConfidenceFlag.ABSTAINED
    assert bet.structural_error is False


def test_cycle_catches_unexpected_exception_and_records_structural_error(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated pipeline failure")

    monkeypatch.setattr(pt_engine, "run_prediction", _boom)

    bet = pt_engine.execute_paper_trading_cycle(
        session, run.run_id, match_id="match_1", player_a_id="a", player_b_id="b",
        as_of=NOW, ensemble_config=EnsembleConfig(), risk_config=RiskConfig(aggressiveness_threshold=0.1),
        instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.0, quotes=[],
        closing_time_policy={}, bankroll_total=10_000.0, current_deployed=0.0,
    )
    session.commit()

    assert bet.structural_error is True
    assert "simulated pipeline failure" in bet.error_detail


def test_evaluate_and_maybe_fail_transitions_run_on_structural_error(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    runner.record_cycle_result(
        session, run.run_id, match_id="m", confidence_flag=ConfidenceFlag.ABSTAINED, action_type=None,
        clv_value=None, as_of=NOW, structural_error=True, error_detail="boom",
    )
    session.commit()

    kpis = pt_engine.evaluate_and_maybe_fail(session, run.run_id, as_of=NOW)
    session.commit()

    assert kpis.structural_errors_count == 1
    row = repository.get_run(session, run.run_id)
    assert row.status == "FAILED"


def test_evaluate_and_maybe_fail_leaves_healthy_run_active(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    runner.record_cycle_result(
        session, run.run_id, match_id="m", confidence_flag=ConfidenceFlag.NORMAL, action_type=None,
        clv_value=None, as_of=NOW,
    )
    session.commit()

    pt_engine.evaluate_and_maybe_fail(session, run.run_id, as_of=NOW)
    session.commit()

    row = repository.get_run(session, run.run_id)
    assert row.status == "ACTIVE"


def test_already_failed_run_not_transitioned_again(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()
    repository.transition_run(session, run.run_id, PaperTradingStatus.FAILED, reason="manual")
    session.commit()

    runner.record_cycle_result(
        session, run.run_id, match_id="m", confidence_flag=ConfidenceFlag.ABSTAINED, action_type=None,
        clv_value=None, as_of=NOW, structural_error=True, error_detail="boom",
    )
    session.commit()

    # must not raise InvalidRunTransition even though structural errors exist
    pt_engine.evaluate_and_maybe_fail(session, run.run_id, as_of=NOW)
