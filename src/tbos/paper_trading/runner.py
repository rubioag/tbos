"""Paper Trading run management — thin wrapper over repository.py giving
the orchestration layer (engine.py) a clean start/record/finalize API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from tbos.paper_trading import repository
from tbos.paper_trading.schemas import PROTOCOL_VERSION, PaperTradingBetRecord, PaperTradingRun
from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, PaperTradingStatus


def start_run(session: Session, *, config_version_id: uuid.UUID, as_of: datetime) -> PaperTradingRun:
    run = PaperTradingRun(
        run_id=uuid.uuid4(), protocol_version=PROTOCOL_VERSION, start_date=as_of,
        config_version_id_at_start=config_version_id, status=PaperTradingStatus.ACTIVE,
    )
    repository.create_run(session, run)
    return run


def record_cycle_result(
    session: Session,
    run_id: uuid.UUID,
    *,
    match_id: str,
    confidence_flag: ConfidenceFlag,
    action_type: ActionType | None,
    clv_value: float | None,
    as_of: datetime,
    structural_error: bool = False,
    error_detail: str | None = None,
) -> PaperTradingBetRecord:
    bet = PaperTradingBetRecord(
        run_id=run_id, match_id=match_id, confidence_flag=confidence_flag, action_type=action_type,
        clv_value=clv_value, structural_error=structural_error, error_detail=error_detail, recorded_at=as_of,
    )
    repository.record_bet(session, bet)
    return bet
