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
  - **PR-3 (done) — Campaign attribution linkage.** Every hypothesis, approved
    idea, experiment, lesson, and M9 observation is attributable to its
    originating campaign, with attribution **derived at read time** from link
    keys that already exist (`pending_ideas.campaign_id` / `.experiment_id` and
    `hypothesis_node.campaign_id` / `.idea_id`) — no campaign_id column is added
    to experiments, lessons, or observations, so execution, approval, and
    evaluation are untouched. `campaign_store.link_idea_to_campaign` is a
    write-once tag; the new read-only `campaign_attribution` module provides
    forward (`*_for_campaign`, `attribution_summary`) and reverse
    (`campaign_for_experiment`, `lineage_for_experiment`) views. Because the
    anchors live on the ideas/hypotheses rather than the campaign row,
    attribution survives deleting and rebuilding the `research_campaign`
    projection, and non-campaign experiments simply resolve to no campaign.
  - **PR-4 (done) — ResearchStrategist + first-class `bar_type` plumbing.**
    Schema v10 makes `bar_type` a typed, first-class field carried end to end:
    `hypothesis_node.bar_type` (PR-2) → `pending_ideas.bar_type` →
    `ExperimentSpec.bar_type` → `config.json` → `experiments.bar_type`, all
    additive `NOT NULL DEFAULT 'time'` migrations — never hidden in free text,
    so the Alternative Bars campaign is executable as soon as a bar engine is
    added (no further migration needed). Supported values are exactly `time,
    volume, dollar, tick, volume_imbalance, dollar_imbalance`
    (`agents.protocol.SUPPORTED_BAR_TYPES` / `normalize_bar_type`). The new
    `agents/research_strategist` is a deterministic (no-LLM) decision layer
    above the unchanged M7 execution core and M9 learning core: each tick it
    reads campaign state + budget, M9 context evidence, and the hypothesis
    frontier, then derives a bounded set of `Proposal`s and, on `apply`, writes
    children into the hypothesis tree and enqueues them as `pending` ideas in
    the existing human approval queue (the gate is preserved — it never
    executes, schedules, approves, or evaluates). Auto-triggers cover
    `vary_bar`, `cross_market`, `combine`, and `negate`; `refine`/`add_filter`
    are interface-complete via `apply`. Explosion safeguards: campaign must be
    ACTIVE and not budget-exhausted, `max_depth`, frontier dedup, terminal
    `negate` children, one move per signal/market/universe lineage per tick, and
    `max_proposals_per_tick`. Touches only `agents/`.
  - **PR-5 (done) — ResearchPrioritizer + Research Value scoring.** A
    deterministic, explainable ranking layer (`agents/research_prioritizer`)
    over the existing approval queue. It scores `pending` ideas by *Research
    Value* — a fixed, normalised weighted blend of five `[0,1]` components, each
    surfaced in a per-idea `ScoreBreakdown`: **Expected Information Gain**
    (`1/(1+n)` in the target M9 context cell's prior-experiment count),
    **Novelty** (batch-structural anti-redundancy, `1/(1+d)` in sibling ideas
    sharing the idea's signal/market/universe/bar key), **Memory Score**
    (supportive vs cautionary research-memory alignment, neutral 0.5),
    **Campaign Priority** (`goal_spec.priority`, neutral default off-campaign),
    and **Cost** (bar-type construction complexity + signal count, folded in as
    cheapness). Ordering is a total order with `idea_id` tie-breaks, so identical
    inputs always yield identical rankings. An **exploration quota** reserves
    `ceil(exploration_fraction * top_k)` of the selection window for the best
    explore-bucket ideas (`EIG ≥ explore_eig_threshold`), so high-scoring
    exploit ideas cannot crowd exploration out of the top_k. Read-only: it never
    executes, schedules, approves, or mutates ideas; the human gate and the
    M7/M9 paths are untouched. Touches only `agents/`.

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
