"""Paper Trading — orchestrator. Drives one CE.1(existing snapshots) ->
CE.2 -> CE.3 -> CE.4 -> CE.5 -> CE.6 cycle for a single match/instrument
and records the outcome. Any exception anywhere in the cycle is caught
and recorded as a structural_error — never left to crash the run, and
never silently swallowed either (spec: structural errors are a hard
zero-tolerance signal for the Approval Gate).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce1_data.schemas import MatchContext
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce3_edge.engine import build_edge_description
from tbos.ce4_decision.engine import build_action_plan
from tbos.ce5_execution.engine import run_execution
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import ExecutionRecord
from tbos.ce6_clv.engine import build_clv_record
from tbos.inf1_config.schemas import EnsembleConfig, RiskConfig
from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, InstrumentType, PaperTradingStatus
from tbos.paper_trading import repository, runner
from tbos.paper_trading.kpis import compute_kpis
from tbos.paper_trading.schemas import PaperTradingBetRecord, PaperTradingKPISnapshot


def execute_paper_trading_cycle(
    session: Session,
    run_id: uuid.UUID,
    *,
    match_id: str,
    player_a_id: str,
    player_b_id: str,
    as_of: datetime,
    ensemble_config: EnsembleConfig,
    risk_config: RiskConfig,
    instrument_type: InstrumentType,
    book_id: str,
    offered_odds: float,
    quotes: list[BookQuote],
    closing_time_policy: dict[str, str],
    bankroll_total: float,
    current_deployed: float,
) -> PaperTradingBetRecord:
    try:
        prediction = run_prediction(
            session, match_id=match_id, player_a_id=player_a_id, player_b_id=player_b_id,
            as_of=as_of, ensemble_config=ensemble_config,
        )

        if prediction.confidence_flag == ConfidenceFlag.ABSTAINED:
            return runner.record_cycle_result(
                session, run_id, match_id=match_id, confidence_flag=prediction.confidence_flag,
                action_type=None, clv_value=None, as_of=as_of,
            )

        edge = build_edge_description(
            prediction, instrument_type=instrument_type, book_id=book_id, offered_odds=offered_odds, as_of=as_of,
        )
        if edge is None:
            return runner.record_cycle_result(
                session, run_id, match_id=match_id, confidence_flag=prediction.confidence_flag,
                action_type=None, clv_value=None, as_of=as_of,
            )

        plan = build_action_plan(
            edge, bankroll_total=bankroll_total, current_deployed=current_deployed,
            risk_config=risk_config, as_of=as_of,
        )

        clv_value = None
        if plan.action_type == ActionType.BET_NOW:
            outcome = run_execution(plan, target_odds=edge.offered_odds, quotes=quotes, as_of=as_of)
            if isinstance(outcome, ExecutionRecord):
                clv_value = _try_compute_clv(
                    session, outcome, match_id=match_id, edge_source_category=edge.edge_source_category,
                    closing_time_policy=closing_time_policy,
                )

        return runner.record_cycle_result(
            session, run_id, match_id=match_id, confidence_flag=prediction.confidence_flag,
            action_type=plan.action_type, clv_value=clv_value, as_of=as_of,
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure becomes a recorded structural_error
        return runner.record_cycle_result(
            session, run_id, match_id=match_id, confidence_flag=ConfidenceFlag.ABSTAINED,
            action_type=None, clv_value=None, as_of=as_of, structural_error=True, error_detail=str(exc),
        )


def _try_compute_clv(
    session: Session, outcome: ExecutionRecord, *, match_id: str, edge_source_category, closing_time_policy: dict[str, str],
) -> float | None:
    snapshot = ce1_repository.get_latest_snapshot(session, "MatchContext", match_id)
    if snapshot is None:
        return None
    match_context = MatchContext.model_validate(snapshot.fields)
    clv_record = build_clv_record(
        session, outcome, match_id=match_id, match_context=match_context,
        edge_source_category=edge_source_category, closing_time_policy=closing_time_policy,
    )
    return clv_record.clv_value if clv_record is not None else None


def evaluate_and_maybe_fail(session: Session, run_id: uuid.UUID, *, as_of: datetime) -> PaperTradingKPISnapshot:
    """Computes current KPIs; if a hard-fail condition is present
    (structural errors), transitions the run to FAILED immediately —
    otherwise the run stays ACTIVE, KPIs are just a checkpoint.
    """
    bets = [PaperTradingBetRecord.model_validate(row.payload) for row in repository.list_bets_for_run(session, run_id)]
    kpis = compute_kpis(run_id, bets, evaluated_at=as_of)

    if kpis.structural_errors_count > 0:
        run_row = repository.get_run(session, run_id)
        if run_row is not None and PaperTradingStatus(run_row.status) == PaperTradingStatus.ACTIVE:
            repository.transition_run(
                session, run_id, PaperTradingStatus.FAILED,
                reason=f"{kpis.structural_errors_count} structural error(s) detected — hard-fail, zero tolerance",
            )

    return kpis
