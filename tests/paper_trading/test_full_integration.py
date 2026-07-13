"""Full pipeline: CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 -> CE.6 driven by
Paper Trading, through KPI computation and the Approval Gate.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce5_execution.optimizer import BookQuote
from tbos.historical_pipeline import market_history
from tbos.inf1_config.schemas import EnsembleConfig, RiskConfig
from tbos.inf1_config.taxonomy import ActionType, ApprovalDecision, ConfidenceFlag, InstrumentType, PaperTradingStatus
from tbos.paper_trading import approval, repository as pt_repository, runner
from tbos.paper_trading.engine import evaluate_and_maybe_fail, execute_paper_trading_cycle
from tbos.paper_trading.kpis import compute_kpis
from tbos.paper_trading.schemas import PaperTradingBetRecord

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile, make_state

CONFIG_VERSION_ID = uuid.uuid4()
CLOSING_POLICY = {"MONEYLINE": "match_start"}


def _publish_full_data(session: Session, *, as_of: datetime) -> None:
    h2h = [{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_a", fields=make_profile("player_a", h2h_records=h2h), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_b", fields=make_profile("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_a", fields=make_state("player_a"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_b", fields=make_state("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="MatchContext", entity_id="match_1", fields=make_match_context(), config_version_id=CONFIG_VERSION_ID)
    session.commit()


def test_full_ce1_to_paper_trading_pipeline(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    market_context_snapshot = ce1_repository.get_latest_snapshot(session, "MatchContext", "match_1")
    from tbos.ce1_data.schemas import MatchContext
    match_context = MatchContext.model_validate(market_context_snapshot.fields)
    market_history.append_tick(
        session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a",
        odds=2.3, tick_timestamp=match_context.scheduled_start.value - timedelta(minutes=5),
    )
    session.commit()

    run = runner.start_run(session, config_version_id=CONFIG_VERSION_ID, as_of=as_of)
    session.commit()

    quotes = [BookQuote(book_id="book_a", odds=2.5, available_liquidity=10_000)]
    bet = execute_paper_trading_cycle(
        session, run.run_id, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(), risk_config=RiskConfig(aggressiveness_threshold=0.1),
        instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.5, quotes=quotes,
        closing_time_policy=CLOSING_POLICY, bankroll_total=10_000.0, current_deployed=0.0,
    )
    session.commit()

    assert bet.structural_error is False

    kpis = evaluate_and_maybe_fail(session, run.run_id, as_of=as_of)
    session.commit()
    assert kpis.sample_size == 1

    row = pt_repository.get_run(session, run.run_id)
    assert row.status == PaperTradingStatus.ACTIVE.value  # single healthy cycle, no hard-fail triggered


def test_approval_flow_with_low_thresholds_reaches_approve_live(session: Session) -> None:
    """Simulates a run that has cleared enough (synthetic) volume by
    directly seeding bet records, then exercises the full Approval Gate
    decision path end to end.
    """
    run = runner.start_run(session, config_version_id=CONFIG_VERSION_ID, as_of=datetime.now(timezone.utc))
    session.commit()

    for i in range(10):
        runner.record_cycle_result(
            session, run.run_id, match_id=f"m{i}", confidence_flag=ConfidenceFlag.NORMAL,
            action_type=ActionType.BET_NOW, clv_value=0.02, as_of=datetime.now(timezone.utc),
        )
    session.commit()

    bets = [PaperTradingBetRecord.model_validate(r.payload) for r in pt_repository.list_bets_for_run(session, run.run_id)]
    kpis = compute_kpis(run.run_id, bets, evaluated_at=datetime.now(timezone.utc))

    criteria = approval.evaluate_approval_criteria(
        kpis, min_sample_size=10, min_clv_sample_for_significance=5, min_coverage_rate=0.0,
    )
    assert criteria.all_met is True

    approval.record_decision(
        session, run.run_id, criteria, decision=ApprovalDecision.APPROVE_LIVE,
        human_reviewer_id="alice", notes="criteria met", as_of=datetime.now(timezone.utc),
    )
    pt_repository.transition_run(session, run.run_id, PaperTradingStatus.PASSED, reason="approved by alice")
    session.commit()

    row = pt_repository.get_run(session, run.run_id)
    assert row.status == "PASSED"
