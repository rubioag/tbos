# TBOS — Tennis Betting Operating System

[![tests](https://github.com/rubioag/tbos/actions/workflows/tests.yml/badge.svg)](https://github.com/rubioag/tbos/actions/workflows/tests.yml)


A quantitative analysis pipeline for professional tennis matches, built as a personal
engineering project. It ingests odds and historical match data from public sources,
estimates match probabilities, computes expected value against bookmaker prices, sizes
hypothetical positions under risk constraints, and tracks closing line value — all in
**paper trading only**.

> **Status: personal project, in active development. Not a product, not a service, and
> not financial advice.** No money is placed. No profitability, accuracy or return figures
> are claimed anywhere in this repository, because none have been measured.

---

## Why this repository is worth thirty seconds

The interesting part is not the tennis. It is how the system behaves when the data is
incomplete — which, with free-tier sports data, is most of the time.

Every stage degrades explicitly rather than guessing. When the odds provider's free tier
supplies no liquidity depth, the field is set to zero and documented as *not derivable*,
which makes the execution stage conservatively cancel the plan — instead of inventing a
plausible number and producing a confident, wrong answer. The same convention is applied
to every unavailable input, and each one is written down in the module that relies on it.

`src/tbos/paper_trading/orchestrator.py` opens with a list of the pipeline's current
limitations, labelled as real gaps rather than oversights, so that nobody — including
its author six months later — mistakes a placeholder for a measurement.

---

## Pipeline

```
odds-api.io ──┐
Sackmann ─────┼──► Resolver ──► CE.1 ──► CE.2 ──► CE.3 ──► CE.4 ──► CE.5 ──► CE.6
tennis-data ──┘                 data    predict   edge    decide   execute   CLV
```

| Stage | Responsibility |
|---|---|
| **CE.1 — Data** | Ingestion pipeline, envelope and schema validation, persistence |
| **CE.2 — Prediction** | Five models (serve, return, matchup, surface, form/fatigue), ensemble, uncertainty, abstention policy, determinism checks, validation battery |
| **CE.3 — Edge** | Fair odds, expected value, sensitivity and robustness analysis, edge lifecycle |
| **CE.4 — Decision** | Stake sizing, capital constraints, ruin-risk limits, bias controls |
| **CE.5 — Execution** | Execution planning, liquidity checks, cancellation rules, monitoring |
| **CE.6 — CLV** | Closing line capture and closing line value |
| **INF.1-3** | Config and model taxonomy · append-only event ledger with replay · calibration and decision-quality review |

Cross-cutting: `data_adapters` (four external sources plus a deterministic player-name
resolver), `historical_pipeline`, and `paper_trading`.

### Deterministic player resolution

The three data sources name the same player differently. A deterministic resolver maps
each provider's name to a single canonical Sackmann `player_id` through ordered matching
tiers, including an abbreviated-name tier. Unresolved names fail loudly instead of being
matched approximately — a wrong join here would silently corrupt every downstream stage.

---

## What is verified, and what is not

**Verified**

- The pipeline runs end to end: `tbos paper-run` executes one complete paper trading cycle.
- The odds provider migration was driven by evidence, not preference. The previous
  provider's free tier was confirmed by full catalogue dump to contain no ATP/WTA 250
  tournaments at all; the replacement was confirmed by live API call to list them with
  real event counts. Both findings are recorded in the commit and in the orchestrator.
- **726 tests pass** across every module, in about four seconds, with no network access
  and no database server required. Regression tests include one making the adapter tests
  independent of the wall clock, after they proved time-sensitive.

**Not verified, and not claimed**

- Model accuracy, calibration quality, profitability, ROI, hit rate. Unmeasured.
- Behaviour at scale. Only run on small datasets.
- Production readiness. Never deployed.
- **Static analysis is configured but not yet satisfied.** `ruff` and `mypy` are set up
  with strict rules in `pyproject.toml`, and the codebase does not currently pass either
  of them. CI runs the test suite only. Bringing both to zero is tracked work, not a
  claim being made here.

---

## Stack

Python 3.13 · FastAPI · Pydantic · SQLAlchemy 2.0 · Alembic · PostgreSQL · SQLite ·
Celery · Redis · httpx · Docker Compose
Tooling: pytest, pytest-asyncio, pytest-cov. `ruff` and `mypy` are configured with strict
settings but not yet enforced — see the note above.

## Running it

```bash
pip install -e ".[dev]"
docker compose up -d        # postgres + redis
cp .env.example .env        # add your own API keys
tbos paper-run
```

```bash
pytest          # 726 tests, no network or database server required
```

An `odds-api.io` API key is required for live runs. No key is included in this repository
and none has ever been committed.

---

## Development method

This project was built with AI-assisted development. The author specified the
architecture and the constraints, directed the model, and reviewed, debugged and
verified the output — the test suite, the documented limitations and the evidence-driven
provider migration are the record of that verification step. It is stated here rather
than left to be discovered, because how the code was produced is part of what the
repository is evidence of.

## Scope

Personal project. Paper trading only. No money is placed, no advice is given, and no
results are claimed. Data comes from public sources under their own terms.
