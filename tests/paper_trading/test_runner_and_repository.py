import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, PaperTradingStatus
from tbos.paper_trading import repository, runner
from tbos.paper_trading.lifecycle import InvalidRunTransition

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_start_run_creates_active_run(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()
    row = repository.get_run(session, run.run_id)
    assert row is not None
    assert row.status == "ACTIVE"


def test_record_cycle_result_persists_bet(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    runner.record_cycle_result(
        session, run.run_id, match_id="match_1", confidence_flag=ConfidenceFlag.NORMAL,
        action_type=ActionType.BET_NOW, clv_value=0.02, as_of=NOW,
    )
    session.commit()

    bets = repository.list_bets_for_run(session, run.run_id)
    assert len(bets) == 1
    assert bets[0].payload["action_type"] == "BET_NOW"


def test_transition_run_updates_status(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()

    repository.transition_run(session, run.run_id, PaperTradingStatus.FAILED, reason="test")
    session.commit()

    row = repository.get_run(session, run.run_id)
    assert row.status == "FAILED"


def test_transition_run_rejects_invalid_transition(session: Session) -> None:
    run = runner.start_run(session, config_version_id=uuid.uuid4(), as_of=NOW)
    session.commit()
    repository.transition_run(session, run.run_id, PaperTradingStatus.PASSED, reason="ok")
    session.commit()

    with pytest.raises(InvalidRunTransition):
        repository.transition_run(session, run.run_id, PaperTradingStatus.ACTIVE, reason="reopen")
