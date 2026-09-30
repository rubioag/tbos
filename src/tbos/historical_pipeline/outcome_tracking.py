"""Append-only ledger of real predictions vs. real recorded outcomes —
closes the gap `paper_trading/schemas.py` documents as deferred
("calibration needs settled match outcomes, not wired to simulation
across settled bets"). Same JSONL, append-only, never-rewritten
discipline as `PlayerNameMappingStore` (INF.2 event-sourcing pattern).

Deliberately independent of whether a market/odds existed for the match:
a prediction's correctness is a fact about the prediction and the real
result, not about whether TBOS could have bet on it. `has_market` is
recorded per outcome so cumulative prediction-quality metrics (accuracy,
log loss, Brier, ECE) can include every recorded prediction, while
market-dependent metrics (ROI, yield, EV) can filter to `has_market=True`
only — never conflating the two, per the explicit instruction that a
no-market match must never be silently dropped from prediction-quality
tracking nor silently included in ROI.

Metric computation reuses `historical_pipeline.backtest`'s already-tested
functions unmodified — a recorded outcome converts 1:1 into a
`MatchPrediction`, the same type the walk-forward backtest produces, so
"cumulative live-prediction accuracy" and "backtest accuracy" are
computed by the exact same code path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from tbos.historical_pipeline.backtest import BacktestReport, MatchPrediction, summarize


class PredictionOutcomeRecord(BaseModel):
    match_id: str
    player_a_name: str = ""  # display name, e.g. "Jesper de Jong" — "" for pre-existing records
    player_b_name: str = ""
    player_a_id: str
    player_b_id: str
    predicted_probability_player_a: float | None  # None only if fully_abstained
    fully_abstained: bool
    participating_model_ids: list[str]
    decision: str  # "BET" | "NO BET (market unavailable)" | "ABSTAIN"
    has_market: bool  # False => excluded from ROI/yield/EV/bankroll, still in prediction quality
    ev: float | None = None  # only set when a real market existed and CE.3 computed one
    stake_eur: float | None = None  # only set when decision == "BET"
    odds_taken: float | None = None  # the actual price backed, only set when decision == "BET"
    actual_winner_id: str
    actual_score: str  # e.g. "6-4, 6-2" — real, as reported, never inferred
    bet_result: str | None = None  # "WIN" | "LOSS" | "VOID" | None (no bet placed)
    recorded_at: datetime


class PredictionOutcomeStore:
    """Points at a single JSONL file. Loads existing records into memory
    once; `append()` writes through to disk immediately and updates the
    in-memory index. One record per match_id — a match's real outcome is
    a permanent fact once recorded, not a value to silently overwrite.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, PredictionOutcomeRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = PredictionOutcomeRecord.model_validate_json(line)
                if record.match_id not in self._index:
                    self._index[record.match_id] = record

    def get(self, match_id: str) -> PredictionOutcomeRecord | None:
        return self._index.get(match_id)

    def all(self) -> list[PredictionOutcomeRecord]:
        return list(self._index.values())

    def append(self, record: PredictionOutcomeRecord) -> None:
        if record.match_id in self._index:
            return  # already recorded — append-only, never duplicate/overwrite
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
        self._index[record.match_id] = record


def to_match_prediction(record: PredictionOutcomeRecord) -> MatchPrediction:
    actual_outcome_player_a = 1 if record.actual_winner_id == record.player_a_id else 0
    return MatchPrediction(
        match_id=record.match_id,
        predicted_probability_player_a=record.predicted_probability_player_a,
        actual_outcome_player_a=actual_outcome_player_a,
        fully_abstained=record.fully_abstained,
        participating_model_ids=record.participating_model_ids,
    )


class CoverageReport(BaseModel):
    """How much of the real calendar TBOS can actually cover — kept
    deliberately separate from accuracy/ROI, which only describe
    performance on matches TBOS already chose to analyze. A model can be
    accurate on a tiny sliver of matches and still be operationally
    useless if its coverage is low; this report exists so that question
    is never conflated with "is TBOS accurate when it does predict."
    """

    total_matches: int
    fully_analyzed: int  # CE.2 produced a real probability (fully_abstained == False)
    abstained_insufficient_data: int  # CE.2 itself never produced a probability
    abstained_ev: int  # CE.2 succeeded, but CE.3/CE.4 declined (edge/EV <= 0)
    bet_placed: int
    no_bet_market_unavailable: int
    coverage_pct: float | None  # fully_analyzed / total_matches * 100


def compute_coverage_report(store: PredictionOutcomeStore) -> CoverageReport:
    records = store.all()
    total = len(records)
    fully_analyzed = sum(1 for r in records if not r.fully_abstained)
    abstained_insufficient_data = sum(1 for r in records if r.fully_abstained)
    abstained_ev = sum(1 for r in records if not r.fully_abstained and r.decision == "ABSTAIN")
    bet_placed = sum(1 for r in records if r.decision == "BET")
    no_bet_market_unavailable = sum(
        1 for r in records if r.decision == "NO BET (market unavailable)"
    )
    coverage_pct = (fully_analyzed / total * 100.0) if total > 0 else None

    return CoverageReport(
        total_matches=total, fully_analyzed=fully_analyzed,
        abstained_insufficient_data=abstained_insufficient_data, abstained_ev=abstained_ev,
        bet_placed=bet_placed, no_bet_market_unavailable=no_bet_market_unavailable,
        coverage_pct=coverage_pct,
    )


def compute_cumulative_metrics(store: PredictionOutcomeStore) -> BacktestReport:
    """Includes every recorded outcome regardless of `has_market` — a
    no-market match is a real prediction with a real result, and must
    count toward prediction-quality metrics per the explicit requirement
    that it be excluded only from ROI/yield/EV/bankroll, never from
    accuracy/log-loss/Brier/ECE.
    """
    predictions = [to_match_prediction(r) for r in store.all()]
    return summarize("cumulative live predictions", predictions)


class BettingReport(BaseModel):
    starting_bankroll: float
    total_bets: int
    wins: int
    losses: int
    voids: int
    total_staked: float
    total_returned: float
    net_profit: float
    roi_pct: float | None  # net_profit / total_staked * 100 — None if total_staked == 0
    yield_pct: float | None  # same definition as roi_pct in flat-stake paper trading; kept as a
    # distinct field because "yield" and "ROI" can diverge under variable staking or a fixed-unit
    # convention — not the case here (Kelly-sized stakes, same total_staked base), so the two values
    # are currently identical by construction, not by coincidence.
    ending_bankroll: float


def compute_betting_metrics(
    store: PredictionOutcomeStore, *, starting_bankroll: float = 100.0,
) -> BettingReport:
    """Only `has_market=True` records with `decision == "BET"` and a
    settled `bet_result` count — per the explicit requirement that
    no-market matches (and matches never bet on) are excluded from ROI/
    yield/bankroll entirely, not zero-filled. A `bet_result` of "WIN"/
    "LOSS" assumes the recorded bet always backed player_a (the only
    side TBOS's pipeline ever prices and stakes — see
    three_match_analysis.py's `best_quote` convention).
    """
    bets = [
        r for r in store.all()
        if r.has_market and r.decision == "BET" and r.bet_result is not None
        and r.stake_eur is not None and r.odds_taken is not None
    ]

    wins = sum(1 for r in bets if r.bet_result == "WIN")
    losses = sum(1 for r in bets if r.bet_result == "LOSS")
    voids = sum(1 for r in bets if r.bet_result == "VOID")

    total_staked = sum(r.stake_eur for r in bets)
    total_returned = 0.0
    for r in bets:
        if r.bet_result == "WIN":
            total_returned += r.stake_eur * r.odds_taken
        elif r.bet_result == "VOID":
            total_returned += r.stake_eur  # stake refunded, no profit/loss
        # LOSS: nothing returned

    net_profit = total_returned - total_staked
    roi_pct = (net_profit / total_staked * 100.0) if total_staked > 0 else None

    return BettingReport(
        starting_bankroll=starting_bankroll,
        total_bets=len(bets), wins=wins, losses=losses, voids=voids,
        total_staked=total_staked, total_returned=total_returned, net_profit=net_profit,
        roi_pct=roi_pct, yield_pct=roi_pct,
        ending_bankroll=starting_bankroll + net_profit,
    )


def model_favorite_won(record: PredictionOutcomeRecord) -> bool | None:
    """True/False if the model's own >=50% favorite matched the real
    winner; None if there's nothing to compare (fully abstained).
    """
    if record.fully_abstained or record.predicted_probability_player_a is None:
        return None
    favorite_is_a = record.predicted_probability_player_a >= 0.5
    actual_a_won = record.actual_winner_id == record.player_a_id
    return favorite_is_a == actual_a_won


def value_bet_won(record: PredictionOutcomeRecord) -> bool | None:
    """True/False if the actually-placed value bet (always player_a per
    the pipeline's `best_quote` convention) won; None if no bet was
    placed on this match.
    """
    if record.decision != "BET":
        return None
    return record.actual_winner_id == record.player_a_id


def _predicted_winner_name(record: PredictionOutcomeRecord) -> str:
    if record.fully_abstained or record.predicted_probability_player_a is None:
        return "—"
    name_a = record.player_a_name or record.player_a_id
    name_b = record.player_b_name or record.player_b_id
    return name_a if record.predicted_probability_player_a >= 0.5 else name_b


def _actual_winner_name(record: PredictionOutcomeRecord) -> str:
    if record.actual_winner_id == record.player_a_id:
        return record.player_a_name or record.player_a_id
    return record.player_b_name or record.player_b_id


def render_validation_table(store: PredictionOutcomeStore) -> str:
    """The official validation history table — regenerated fresh from the
    full ledger every call (rendering, not recomputation: every record in
    the JSONL is a permanent, already-written fact; this only formats
    them). Ordered by `recorded_at`, oldest first, so the table reads as
    a chronological audit trail. Never mutates the store.
    """
    records = sorted(store.all(), key=lambda r: r.recorded_at)

    header = (
        "| Date | Match | TBOS Probability | Predicted Winner | Actual Winner | "
        "Correct | Market | Bet Placed | EV | Bet Result |"
    )
    separator = "|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, separator]

    for r in records:
        name_a = r.player_a_name or r.player_a_id
        name_b = r.player_b_name or r.player_b_id
        match_label = f"{name_a} vs {name_b}"
        date_str = r.recorded_at.date().isoformat()

        if r.fully_abstained or r.predicted_probability_player_a is None:
            prob_str, correct_str = "—", "—"
        else:
            predicted_a_wins = r.predicted_probability_player_a >= 0.5
            prob = (
                r.predicted_probability_player_a if predicted_a_wins
                else 1.0 - r.predicted_probability_player_a
            )
            prob_str = f"{prob * 100:.1f}%"
            actual_a_won = r.actual_winner_id == r.player_a_id
            correct_str = "✅" if predicted_a_wins == actual_a_won else "❌"

        market_str = "Sí" if r.has_market else "No"
        bet_placed_str = "Sí" if r.decision == "BET" else "No"
        ev_str = f"{r.ev:.4f}" if r.ev is not None else "—"
        bet_result_str = r.bet_result or "—"

        rows.append(
            f"| {date_str} | {match_label} | {prob_str} | {_predicted_winner_name(r)} | "
            f"{_actual_winner_name(r)} | {correct_str} | {market_str} | {bet_placed_str} | "
            f"{ev_str} | {bet_result_str} |"
        )

    return "\n".join(rows)
