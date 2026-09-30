"""Pending Paper Trades — bets placed on a real match whose result isn't
known yet. Same append-only JSONL discipline as
`outcome_tracking.PredictionOutcomeRecord`.

A pending trade always backs `player_a` — the same structural convention
`three_match_analysis.py`'s `best_quote` logic already enforces (a "BET"
decision only ever prices and stakes player_a's side). This module does
not re-decide anything; it only persists what CE.4 already decided and,
once the real result is known, settles it into the existing
`PredictionOutcomeStore` via the exact same schema every other recorded
outcome uses — no separate metrics path, no separate calibration logic.

Settlement is idempotent: `PredictionOutcomeStore.append` already refuses
to overwrite an existing match_id, so calling `settle_pending_trade`
twice for the same match is a safe no-op, not a double-count.

Real bug found in this session (2026-07-17): a trade was reported and
nearly saved as "BET Molcan @ 3.00" when the raw pipeline output's
`decision == "BET"` actually priced and staked player_a = Dzumhur, not
Molcan (player_b) — the odds, probability, EV, edge, and stake all
belonged to Dzumhur's side; Molcan was never priced at 3.00 anywhere in
the real market data. Caught only by manual cross-check against the raw
JSON. `build_pending_trade_from_report` exists specifically to make that
class of bug structurally impossible going forward: every field is
derived from ONE raw report dict, never hand-assembled from separately
supplied values that could silently drift apart or get mismatched.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from tbos.historical_pipeline.outcome_tracking import (
    PredictionOutcomeRecord,
    PredictionOutcomeStore,
)


class TradeValidationError(ValueError):
    """Raised when a pending trade's fields don't all trace back to the
    same raw pipeline report and the same recommended side — the save is
    aborted, nothing is persisted.
    """


class PendingPaperTrade(BaseModel):
    match_id: str
    player_a_name: str
    player_b_name: str
    player_a_id: str
    player_b_id: str
    predicted_probability_player_a: float  # exact CE.2 ensemble output, never rounded
    participating_model_ids: list[str]
    ev: float
    edge_pct: float
    kelly_fraction: float
    odds_taken: float  # the real price backed, always player_a's side
    stake_eur: float
    placed_at: datetime


class PendingPaperTradeStore:
    """Points at a single JSONL file. One record per match_id — a placed
    trade's terms (odds, stake, EV) are a permanent fact once recorded,
    never rewritten even after settlement (the settlement itself lives
    as a separate, later fact in PredictionOutcomeStore).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, PendingPaperTrade] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                trade = PendingPaperTrade.model_validate_json(line)
                if trade.match_id not in self._index:
                    self._index[trade.match_id] = trade

    def get(self, match_id: str) -> PendingPaperTrade | None:
        return self._index.get(match_id)

    def all(self) -> list[PendingPaperTrade]:
        return list(self._index.values())

    def append(self, trade: PendingPaperTrade) -> None:
        if trade.match_id in self._index:
            return  # already recorded — append-only, never duplicate/overwrite
        with self._path.open("a", encoding="utf-8") as f:
            f.write(trade.model_dump_json() + "\n")
        self._index[trade.match_id] = trade

    def append_from_report(
        self, report: dict, *, player_a_name: str, player_b_name: str, placed_at: datetime,
    ) -> PendingPaperTrade:
        """Preferred entry point for saving a new pending trade: builds
        via `build_pending_trade_from_report` (raw-JSON-only, validated)
        and appends only if that succeeds. Raises `TradeValidationError`
        and persists nothing if validation fails.
        """
        trade = build_pending_trade_from_report(
            report, player_a_name=player_a_name, player_b_name=player_b_name, placed_at=placed_at,
        )
        self.append(trade)
        return trade


def build_pending_trade_from_report(
    report: dict, *, player_a_name: str, player_b_name: str, placed_at: datetime,
) -> PendingPaperTrade:
    """The only sanctioned way to construct a `PendingPaperTrade` for
    saving. Every numeric field (odds, probability, stake, EV, edge,
    kelly) is read directly from `report` — the same raw dict a pipeline
    run (e.g. `three_match_analysis.py`) already produces — never passed
    in separately, so there is no way for one field to belong to a
    different match or a different side than the rest. `odds_taken` is
    independently recomputed from `report["raw_quotes"]` rather than
    trusted from any pre-computed field, since that's the exact value
    that was wrong in the real Molcan/Dzumhur incident.

    Raises `TradeValidationError` (aborts, saves nothing) if:
    - `report["decision"] != "BET"` — nothing to save, not a bet.
    - the recomputed best player_a price doesn't match what the report's
      own `implied_probability_player_a` implies (cross-check against a
      second, independently-stored field from the same report).
    - any required raw field is missing.
    """
    decision = report.get("decision")
    if decision != "BET":
        raise TradeValidationError(
            f"report decision is {decision!r}, not \"BET\" — refusing to save a non-bet as a trade"
        )

    required_fields = [
        "event_id", "player_a_id", "player_b_id", "probability_player_a",
        "participating_models", "ev", "edge_pct", "kelly_fraction", "stake_eur", "raw_quotes",
    ]
    missing = [f for f in required_fields if report.get(f) is None]
    if missing:
        raise TradeValidationError(f"report is missing required field(s) for a trade: {missing}")

    player_a_quotes = [q for q in report["raw_quotes"] if q.get("selection") == "player_a"]
    if not player_a_quotes:
        raise TradeValidationError(
            "report has no player_a quotes in raw_quotes — cannot determine odds_taken"
        )
    best_odds = max(q["odds"] for q in player_a_quotes)

    implied = report.get("implied_probability_player_a")
    if implied is not None:
        recomputed_implied = 1.0 / best_odds
        if abs(recomputed_implied - implied) > 1e-6:
            raise TradeValidationError(
                f"odds/implied-probability mismatch: best player_a odds {best_odds} implies "
                f"{recomputed_implied:.6f}, but report's implied prob is {implied:.6f} "
                "— must come from the same quote; refusing to save"
            )

    trade = PendingPaperTrade(
        match_id=str(report["event_id"]),
        player_a_name=player_a_name, player_b_name=player_b_name,
        player_a_id=str(report["player_a_id"]), player_b_id=str(report["player_b_id"]),
        predicted_probability_player_a=report["probability_player_a"],
        participating_model_ids=report["participating_models"],
        ev=report["ev"], edge_pct=report["edge_pct"], kelly_fraction=report["kelly_fraction"],
        odds_taken=best_odds, stake_eur=report["stake_eur"],
        placed_at=placed_at,
    )
    # Defense in depth — re-derive and re-check everything independently.
    validate_trade_against_report(trade, report)
    return trade


def validate_trade_against_report(trade: PendingPaperTrade, report: dict) -> None:
    """Independent re-check that every field on an already-built `trade`
    still traces back to `report`, for the same side. Used internally by
    `build_pending_trade_from_report`; also callable directly to audit a
    trade built or loaded another way. Raises `TradeValidationError` on
    the first mismatch found — does not silently fix or partially save.
    """
    report_decision = report.get("decision")
    if report_decision != "BET":
        raise TradeValidationError(f"report decision is {report_decision!r}, not \"BET\"")

    report_event_id = report.get("event_id")
    if trade.match_id != str(report_event_id):
        raise TradeValidationError(
            f"match_id {trade.match_id!r} != report event_id {report_event_id!r}"
        )

    # (1) the recommended player matches bet_side (player_a, per the pipeline's
    # fixed convention — "BET" only ever prices/stakes player_a's side).
    report_player_a_id = report.get("player_a_id")
    if trade.player_a_id != str(report_player_a_id):
        raise TradeValidationError(
            f"trade.player_a_id={trade.player_a_id!r} != report player_a_id={report_player_a_id!r} "
            "— the saved bet side does not match the recommended side"
        )
    report_player_b_id = report.get("player_b_id")
    if trade.player_b_id != str(report_player_b_id):
        raise TradeValidationError(
            f"trade.player_b_id={trade.player_b_id!r} != report player_b_id={report_player_b_id!r}"
        )

    # (2) the odds belong to that same player (player_a).
    player_a_quotes = [q for q in report.get("raw_quotes", []) if q.get("selection") == "player_a"]
    if not player_a_quotes:
        raise TradeValidationError("report has no player_a quotes to validate odds_taken against")
    best_odds = max(q["odds"] for q in player_a_quotes)
    if trade.odds_taken != best_odds:
        raise TradeValidationError(
            f"trade.odds_taken={trade.odds_taken} != recomputed best player_a odds={best_odds} "
            "— odds do not belong to the recommended player"
        )

    # (3) the probability corresponds to the same side.
    report_prob = report.get("probability_player_a")
    if report_prob is None or trade.predicted_probability_player_a != report_prob:
        raise TradeValidationError(
            f"trade.predicted_probability_player_a={trade.predicted_probability_player_a} != "
            f"report probability_player_a={report_prob} — probability does not match the bet side"
        )

    # (4) stake, EV, and edge all belong to the same record.
    for field, trade_value in (
        ("ev", trade.ev), ("edge_pct", trade.edge_pct),
        ("kelly_fraction", trade.kelly_fraction), ("stake_eur", trade.stake_eur),
    ):
        report_value = report.get(field)
        if report_value is None or trade_value != report_value:
            raise TradeValidationError(
                f"trade.{field}={trade_value} != report[{field!r}]={report_value} "
                "— field does not belong to this same record"
            )


def list_open_trades(
    pending_store: PendingPaperTradeStore, outcome_store: PredictionOutcomeStore,
) -> list[PendingPaperTrade]:
    """Pending trades that have not yet been settled — i.e. no matching
    match_id exists in the outcome store."""
    return [t for t in pending_store.all() if outcome_store.get(t.match_id) is None]


def settle_pending_trade(
    pending_store: PendingPaperTradeStore, outcome_store: PredictionOutcomeStore, *,
    match_id: str, actual_winner_id: str, actual_score: str, recorded_at: datetime,
) -> PredictionOutcomeRecord | None:
    """Returns the settled record, or None if no such pending trade
    exists. If the match was already settled, returns the existing
    record unchanged (idempotent, never re-settles or overwrites).
    """
    trade = pending_store.get(match_id)
    if trade is None:
        return None

    existing = outcome_store.get(match_id)
    if existing is not None:
        return existing

    bet_result = "WIN" if actual_winner_id == trade.player_a_id else "LOSS"
    record = PredictionOutcomeRecord(
        match_id=trade.match_id,
        player_a_name=trade.player_a_name, player_b_name=trade.player_b_name,
        player_a_id=trade.player_a_id, player_b_id=trade.player_b_id,
        predicted_probability_player_a=trade.predicted_probability_player_a,
        fully_abstained=False,
        participating_model_ids=trade.participating_model_ids,
        decision="BET", has_market=True,
        ev=trade.ev, stake_eur=trade.stake_eur, odds_taken=trade.odds_taken,
        actual_winner_id=actual_winner_id, actual_score=actual_score,
        bet_result=bet_result,
        recorded_at=recorded_at,
    )
    outcome_store.append(record)
    return record
