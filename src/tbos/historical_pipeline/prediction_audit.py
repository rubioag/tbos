"""Permanent audit trail for CE.2 per-model signal quality and CE.4
edge/favorite-vs-value-bet behavior — built to answer, once enough
matches accumulate, questions like "is form_fatigue_model degrading
performance?" or "are value bets against the model's own favorite less
profitable?" without re-deriving anything retroactively.

Captured at PREDICTION time (via `compute_model_votes`, called on the
live `ModelInputBundle` a pipeline run already built), not reconstructed
after the fact from a saved snapshot — avoids the schema-drift fragility
that made the De Jong/Baez match unre-derivable after the Elo fields
were added to PlayerProfile.

Does not modify or wrap CE.2's frozen `run_prediction` entry point.
`compute_model_votes` runs the same real Model classes and the same real
`combine_models` aggregator in parallel, simply keeping the per-model
`ModelContribution` data `run_prediction` already computes internally
but doesn't expose in `PredictionOutput`.

Same append-only JSONL discipline, same "raw report dict is the only
source of truth" discipline as `pending_trades.py` — `favorite_side`,
`value_bet_side`, and `edge_bucket` are all derived directly from a raw
pipeline report's own fields (`probability_player_a`, `decision`,
`edge_pct`), never hand-typed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from tbos.ce2_prediction.ensemble import combine_models
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.registry_bootstrap import BASE_MODEL_CLASSES
from tbos.historical_pipeline.backtest import MatchPrediction, brier_score, log_loss
from tbos.historical_pipeline.outcome_tracking import PredictionOutcomeStore

EDGE_BUCKETS = ("<0%", "0-5%", "5-10%", "10-15%", "15-20%", ">20%")


def edge_bucket_label(edge_pct: float | None) -> str | None:
    if edge_pct is None:
        return None
    if edge_pct < 0:
        return "<0%"
    if edge_pct < 5:
        return "0-5%"
    if edge_pct < 10:
        return "5-10%"
    if edge_pct < 15:
        return "10-15%"
    if edge_pct < 20:
        return "15-20%"
    return ">20%"


class ModelVote(BaseModel):
    model_id: str
    domain: str
    voted: bool
    leans: str | None  # "player_a" | "player_b" | "neutral" | None (never voted)
    log_odds_player_a: float | None
    own_uncertainty: float | None
    own_evidence_quality: float | None
    abstain_reason: str | None


def compute_model_votes(
    bundle: ModelInputBundle, model_classes: list[type] | None = None,
) -> list[ModelVote]:
    """Runs every base Model against `bundle` and keeps each one's own
    log-odds contribution (via the same real `combine_models` aggregator
    CE.2 already uses) — the per-model detail `run_prediction` computes
    but discards.
    """
    classes = model_classes if model_classes is not None else BASE_MODEL_CLASSES
    outputs = [cls().estimate(bundle) for cls in classes]
    ensemble = combine_models(bundle.match_id, outputs)
    contrib_by_id = {c.model_id: c for c in ensemble.participating}
    abstained_by_id = {a.model_id: a for a in ensemble.abstained}

    votes: list[ModelVote] = []
    for cls in classes:
        model_id = cls.model_id
        if model_id in contrib_by_id:
            c = contrib_by_id[model_id]
            if c.mapped_log_odds > 0:
                leans = "player_a"
            elif c.mapped_log_odds < 0:
                leans = "player_b"
            else:
                leans = "neutral"
            votes.append(ModelVote(
                model_id=model_id, domain=c.domain, voted=True, leans=leans,
                log_odds_player_a=c.mapped_log_odds, own_uncertainty=c.own_uncertainty,
                own_evidence_quality=c.own_evidence_quality, abstain_reason=None,
            ))
        else:
            abstained = abstained_by_id.get(model_id)
            reason = abstained.reason if abstained is not None else "did not vote"
            votes.append(ModelVote(
                model_id=model_id, domain=cls.domain, voted=False, leans=None,
                log_odds_player_a=None, own_uncertainty=None, own_evidence_quality=None,
                abstain_reason=reason,
            ))
    return votes


class PredictionAuditRecord(BaseModel):
    match_id: str
    favorite_side: str | None  # "player_a" | "player_b" | None (fully abstained)
    value_bet_side: str | None  # "player_a" | None (pipeline convention: BET always backs player_a)
    favorite_value_agree: bool | None  # None if no bet was placed or no favorite exists
    edge_pct: float | None
    edge_bucket: str | None
    model_votes: list[ModelVote]
    recorded_at: datetime


def build_audit_record_from_report(
    report: dict, model_votes: list[ModelVote], *, recorded_at: datetime,
) -> PredictionAuditRecord:
    match_id = str(report["event_id"])
    prob_a = report.get("probability_player_a")
    favorite_side = None if prob_a is None else ("player_a" if prob_a >= 0.5 else "player_b")

    value_bet_side = "player_a" if report.get("decision") == "BET" else None
    favorite_value_agree = (
        None if value_bet_side is None or favorite_side is None else value_bet_side == favorite_side
    )

    edge_pct = report.get("edge_pct")
    return PredictionAuditRecord(
        match_id=match_id, favorite_side=favorite_side, value_bet_side=value_bet_side,
        favorite_value_agree=favorite_value_agree, edge_pct=edge_pct,
        edge_bucket=edge_bucket_label(edge_pct), model_votes=model_votes, recorded_at=recorded_at,
    )


class PredictionAuditStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, PredictionAuditRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = PredictionAuditRecord.model_validate_json(line)
                if record.match_id not in self._index:
                    self._index[record.match_id] = record

    def get(self, match_id: str) -> PredictionAuditRecord | None:
        return self._index.get(match_id)

    def all(self) -> list[PredictionAuditRecord]:
        return list(self._index.values())

    def append(self, record: PredictionAuditRecord) -> None:
        if record.match_id in self._index:
            return  # already recorded — append-only, never duplicate/overwrite
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
        self._index[record.match_id] = record


# --- Aggregate audit reports -------------------------------------------


def _settled_bets(audit_store: PredictionAuditStore, outcome_store: PredictionOutcomeStore):
    for audit in audit_store.all():
        outcome = outcome_store.get(audit.match_id)
        if outcome is None or outcome.bet_result is None:
            continue
        if outcome.stake_eur is None or outcome.odds_taken is None:
            continue
        yield audit, outcome


def _betting_stats(outcomes: list) -> dict:
    wins = sum(1 for o in outcomes if o.bet_result == "WIN")
    losses = sum(1 for o in outcomes if o.bet_result == "LOSS")
    voids = sum(1 for o in outcomes if o.bet_result == "VOID")
    total_staked = sum(o.stake_eur for o in outcomes)
    total_returned = 0.0
    for o in outcomes:
        if o.bet_result == "WIN":
            total_returned += o.stake_eur * o.odds_taken
        elif o.bet_result == "VOID":
            total_returned += o.stake_eur
    roi_pct = ((total_returned - total_staked) / total_staked * 100.0) if total_staked > 0 else None
    predictions = [
        MatchPrediction(
            match_id=o.match_id, predicted_probability_player_a=o.predicted_probability_player_a,
            actual_outcome_player_a=1 if o.actual_winner_id == o.player_a_id else 0,
            fully_abstained=False, participating_model_ids=o.participating_model_ids,
        )
        for o in outcomes
    ]
    return {
        "n": len(outcomes), "wins": wins, "losses": losses, "voids": voids, "roi_pct": roi_pct,
        "log_loss": log_loss(predictions), "brier_score": brier_score(predictions),
    }


def summarize_by_edge_bucket(
    audit_store: PredictionAuditStore, outcome_store: PredictionOutcomeStore,
) -> dict[str, dict]:
    """Among settled bets only: WIN/LOSS count, ROI, log loss, Brier —
    grouped by the edge bucket recorded at prediction time.
    """
    grouped: dict[str, list] = {}
    for audit, outcome in _settled_bets(audit_store, outcome_store):
        if audit.edge_bucket is None:
            continue
        grouped.setdefault(audit.edge_bucket, []).append(outcome)
    return {bucket: _betting_stats(outcomes) for bucket, outcomes in grouped.items()}


def summarize_by_favorite_agreement(
    audit_store: PredictionAuditStore, outcome_store: PredictionOutcomeStore,
) -> dict[str, dict]:
    """Among settled bets only: same stats, grouped by whether the value
    bet agreed with the model's own >=50% favorite.
    """
    grouped: dict[str, list] = {"agree": [], "disagree": []}
    for audit, outcome in _settled_bets(audit_store, outcome_store):
        if audit.favorite_value_agree is None:
            continue
        key = "agree" if audit.favorite_value_agree else "disagree"
        grouped[key].append(outcome)
    return {key: _betting_stats(outcomes) for key, outcomes in grouped.items() if outcomes}


def summarize_by_model(
    audit_store: PredictionAuditStore, outcome_store: PredictionOutcomeStore,
) -> dict[str, dict]:
    """For every match with a recorded outcome (not just settled bets —
    directional correctness doesn't require a market), per model_id:
    how often that model's own leaned side matched the real winner.
    """
    per_model: dict[str, list[bool]] = {}
    for audit in audit_store.all():
        outcome = outcome_store.get(audit.match_id)
        if outcome is None:
            continue
        actual_a_won = outcome.actual_winner_id == outcome.player_a_id
        for vote in audit.model_votes:
            if not vote.voted or vote.leans == "neutral":
                continue
            correct = (vote.leans == "player_a") == actual_a_won
            per_model.setdefault(vote.model_id, []).append(correct)

    return {
        model_id: {
            "n": len(results), "correct": sum(results),
            "accuracy_pct": (sum(results) / len(results) * 100.0) if results else None,
        }
        for model_id, results in per_model.items()
    }
