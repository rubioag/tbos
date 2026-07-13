"""CE.4 — Capital Allocation. How much capital this decision deploys vs
how much stays intentionally reserved system-wide — a stated decision,
never a byproduct (spec: Capital Allocation as first-class output).
"""

from __future__ import annotations

from pydantic import BaseModel


class CapitalAllocation(BaseModel):
    deployed: float
    reserved_system_wide: float
    reasoning: str
    capped: bool


def allocate_capital(
    *, bankroll_total: float, current_deployed: float, proposed_stake: float
) -> CapitalAllocation:
    available = max(0.0, bankroll_total - current_deployed)
    capped = proposed_stake > available
    deployed = min(proposed_stake, available)
    reserved = bankroll_total - current_deployed - deployed

    reasoning = (
        f"proposed_stake={proposed_stake:.2f} vs available={available:.2f}; "
        + ("capped to available capital" if capped else "fully funded from available capital")
    )
    return CapitalAllocation(deployed=deployed, reserved_system_wide=reserved, reasoning=reasoning, capped=capped)
