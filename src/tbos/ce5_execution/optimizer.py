"""CE.5 — Execution Optimizer. Chooses which book(s) fill the target
stake, greedily preferring best available odds, splitting across books
when a single book's liquidity is insufficient. Never proposes filling
more than the target stake (Execution Intent Principle: this optimizes
*how*, the total economic exposure was already fixed by CE.4).
"""

from __future__ import annotations

from pydantic import BaseModel


class BookQuote(BaseModel):
    book_id: str
    odds: float
    available_liquidity: float


class ExecutionSplit(BaseModel):
    book_id: str
    odds: float
    stake_portion: float


def optimize_execution(target_stake: float, quotes: list[BookQuote]) -> list[ExecutionSplit]:
    splits: list[ExecutionSplit] = []
    remaining = target_stake

    for quote in sorted(quotes, key=lambda q: -q.odds):
        if remaining <= 0:
            break
        portion = min(remaining, max(0.0, quote.available_liquidity))
        if portion > 0:
            splits.append(ExecutionSplit(book_id=quote.book_id, odds=quote.odds, stake_portion=portion))
            remaining -= portion

    return splits
