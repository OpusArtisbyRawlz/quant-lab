# Roadmap

Milestone roadmap for the multi-agent quant-research system. Completed
milestones are summarised; upcoming ones are planned, not yet implemented.

## Completed

- **M1 — Storage foundation.** SQLite single source of truth; experiments,
  agent_conversations, lessons_learned, signal_library tables; folder-based
  experiment IDs.
- **M2 — Quant Interface Layer.** Clean `src/` ↔ `agents/` boundary; composable
  signal-combo → portfolio → metrics pipeline.
- **M3 — Experiment Spec Runner.** Spec → backtest → artifact folder → SQLite
  ingest; `data_dict` testing seam; `src/` import boundary enforced by test.
- **M4 — First agent loop.** Deterministic Commander → Designer → Runner →
  Critic → Ledger; two-layer Critic thresholds; full conversation logging.
- **M5 — Statistical integrity & cost realism.** Gross + net metrics, turnover
  (annualized + average-period), transaction-cost/slippage models, robustness
  flags (subperiod / parameter / cost fragility); Critic evaluates net by
  default; schema v4 additive migrations.

## Upcoming

### M6 — Gated LLM Idea Generator (next)

LLM proposes hypotheses/signal combos; a deterministic validator checks
signals/schema/feasibility; **human approval is required before anything runs**.

- Architectural rule: **"LLM output is data, not commands."** The LLM proposes
  only; validator + human approval + deterministic runner stay in control.
- No autonomous endless loop; bounded batch, one human gate per idea.
- All proposed/accepted/rejected ideas logged to `agent_conversations`; approved
  runs flow to the ledger.
- Critic judges with M5 net metrics + robustness checks.

### Roadmap backlog (unscheduled, ordered by dependency)

1. **Horizon-correct returns** (pays down **TD-1**). Explicit holding-period or
   per-day book returns with a matching annualisation basis; full re-baseline of
   stored gross metrics. Should land **before** the formal-statistics milestone.

2. **Rolling robustness suite.** Requested for M5, deferred here. Extend
   `robustness.py` with rolling-window deployability metrics, mirroring the
   judgement already used extensively in **Project 04**:
   - mean rolling Sharpe
   - median rolling Sharpe
   - % positive rolling windows
   - worst rolling Sharpe
   - mean rolling CAGR
   - worst rolling CAGR

3. **Formal overfitting statistics.** Deflated Sharpe, multiple-testing
   correction, purged/embargoed CV. Depends on (1) horizon-correct returns.

4. **Signal-library lifecycle** (pays down **TD-4**). Real promote/combine/retire
   driven by Critic decisions over accumulated net-validated signals.

5. **Retry/repair loop.** Act on `retest` decisions within `max_retest_attempts`
   (deterministic data re-fetch / spec adjustment).

6. **Orchestration & scale.** Multi-cycle scheduling, parallel experiment
   execution, feature/data caching, auto-generated research reports.
