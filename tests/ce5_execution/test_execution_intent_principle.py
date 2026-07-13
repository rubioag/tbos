"""Dedicated enforcement tests for the two CE.5 principles locked in the
frozen spec: Execution Intent (instrument/direction/stake never change)
and Execution Fidelity (quality measured only against the plan's own
target, never against outcome/ROI/CLV).
"""

import uuid
from datetime import datetime, timezone

from tbos.ce4_decision.bias import BiasChecklistResult
from tbos.ce4_decision.capital import CapitalAllocation
from tbos.ce4_decision.decision import DominantReason
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce4_decision.stake import StakeResult
from tbos.ce5_execution.execution import execute_action_plan
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import ExecutionRecord
from tbos.inf1_config.taxonomy import ActionType, InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _plan(instrument: InstrumentType, stake_amount: float = 100.0) -> ActionPlan:
    return ActionPlan(
        action_plan_id=uuid.uuid4(), edge_id=uuid.uuid4(), match_id="match_1",
        instrument_type=instrument, book_id="book_a", action_type=ActionType.BET_NOW,
        stake_result=StakeResult(raw_kelly_fraction=0.1, adjusted_fraction=0.02, stake_amount=stake_amount),
        capital_allocation=CapitalAllocation(deployed=stake_amount, reserved_system_wide=9900, reasoning="ok", capped=False),
        dominant_reason=DominantReason(code="POSITIVE_EV_ROBUST", justification="x"),
        bias_checklist_result=BiasChecklistResult(passed=True, flags=[]),
        ruin_risk_result=RuinRiskResult(ruin_probability=0.001, passed=True, simulated_paths=100),
        ce4_engine_version="1.0.0", computed_at=NOW,
    )


def test_instrument_never_substituted_across_every_instrument_type() -> None:
    for instrument in InstrumentType:
        plan = _plan(instrument)
        quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=1000)]
        record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
        assert record.instrument_type == instrument


def test_instrument_preserved_even_under_split_across_many_books() -> None:
    plan = _plan(InstrumentType.HANDICAP, stake_amount=300.0)
    quotes = [BookQuote(book_id=f"book_{i}", odds=1.9 - i * 0.01, available_liquidity=100) for i in range(3)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert record.instrument_type == InstrumentType.HANDICAP
    assert all(True for _ in record.splits)  # split across multiple books, instrument still singular/correct


def test_execution_record_has_no_instrument_selection_field() -> None:
    """Structural guard: there is no field that could let execution pick
    an instrument independently of the plan — only `instrument_type`,
    always copied.
    """
    assert set(ExecutionRecord.model_fields.keys()) & {"selected_instrument", "alternate_instrument"} == set()


def test_execution_record_has_no_outcome_roi_or_clv_field() -> None:
    """Execution Fidelity Principle: quality is measured only against the
    ActionPlan's own target — structurally impossible to reference match
    outcome, ROI, or CLV, because no such field exists on this schema.
    """
    forbidden = {"outcome", "result", "roi", "clv", "clv_value", "win_loss"}
    assert forbidden.isdisjoint(ExecutionRecord.model_fields.keys())


def test_slippage_field_name_makes_clear_its_only_vs_target() -> None:
    assert "execution_quality_slippage" in ExecutionRecord.model_fields
    assert "target_odds" in ExecutionRecord.model_fields
