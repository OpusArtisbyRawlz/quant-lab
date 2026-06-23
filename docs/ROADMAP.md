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
- **M6 — Gated LLM Idea Generator.** LLM proposes hypotheses/signal combos; a
  deterministic validator checks signals/schema/feasibility; human approval is
  required before anything runs. "LLM output is data, not commands."
- **M7 — Idea Executor.** Approved ideas flow approved → spec → M5 runner →
  Critic → Ledger with provenance stamping, atomic claim, and ledger-gated
  completion; real-data re-validation (pays down TD-7).
- **M8 — Research reporting.** Read-only programmatic reporting API
  (`summaries` → `markdown` → `report`) with static guards forbidding any write
  SQL or execution-module imports from the reporting layer.
- **M9 — Context-aware signal intelligence.** Signal performance is never
  aggregated globally: the atomic unit is the context cell
  (`feature × market × universe × regime × bar_type`). A post-Ledger
  SignalLibrarian decomposes each experiment into context observations, rebuilds
  a context-performance cache, and drives a real signal lifecycle
  (observed → candidate → promoted → retired) with multi-context-confirmed
  promotion (pays down **TD-4**). The IdeaGenerator consumes both global and
  context-filtered performance with an exploration quota. Schema v7. See
  `docs/M9_CONTEXT_SIGNAL_INTELLIGENCE.md`.

## In progress

- **M10 — Autonomous research loop.** A deterministic decision layer stacked
  *above* the unchanged M7 execution core and M9 learning core: it decides *what
  to test next and why*, never pulling the execution trigger or bypassing the
  human approval gate. Delivered incrementally by PR:
  - **PR-1 (done) — Research Campaign foundation.** Schema v8 adds
    `campaign_state_events` (append-only, FK-less, the **source of truth**) and
    `research_campaign` (a rebuildable projection), plus an additive
    `pending_ideas.campaign_id` link. The `CampaignManager` agent owns the
    campaign state machine
    (DRAFT → ACTIVE → {STALLED ↔ ACTIVE} → {COMPLETED | ARCHIVED | DISCARDED};
    ARCHIVED may revive to ACTIVE) and is the sole writer of the campaign tables.
    State is event-sourced: legality is judged against the log, the projection
    row's `state`/`budget_spent` are caches, the genesis event carries the full
    config, and `reconcile()` / `reconcile_all()` / `rebuild_from_events()` make
    the row deletable and fully reconstructible from events + experiments after
    an interrupted transition.
  - **PR-2 (done) — Hypothesis evolution tree.** Schema v9 adds two append-only
    tables: `hypothesis_node` (one immutable, fully-auditable row per
    hypothesis; the root has `parent_id` NULL, every other node records its
    primary parent, root, depth, and the operator that produced it) and
    `hypothesis_edge` (the immutable parent→child relationship labelled with the
    evolution operator). The six operators are `refine`, `vary_bar`,
    `cross_market`, `add_filter`, `combine`, `negate`; `combine` writes one edge
    per merged parent into a single child (a DAG). The `HypothesisTreeManager`
    is the sole writer, and an entire tree/forest is reconstructible from
    storage (`reconstruct_tree` / `reconstruct_forest` / `lineage`). Touches
    only `agents/`; no execution, approval, or experiment-storage changes.

## Upcoming

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

4. **Signal-library lifecycle** (pays down **TD-4**). ✅ Delivered in **M9** as a
   context-aware lifecycle (promote/retire driven by multi-context-confirmed net
   performance over context cells, not a single global aggregate).

5. **Retry/repair loop.** Act on `retest` decisions within `max_retest_attempts`
   (deterministic data re-fetch / spec adjustment).

6. **Orchestration & scale.** Multi-cycle scheduling, parallel experiment
   execution, feature/data caching, auto-generated research reports.
