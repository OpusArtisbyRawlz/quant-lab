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
  - **PR-6 (done) — ResearchScheduler + queues.** Schema v11 adds the
    append-only `scheduler_event` log (`dispatched / succeeded / failed /
    retry_scheduled / exhausted`), the **source of truth** for every scheduler
    decision; `agents/storage/scheduler_store.py` is its sole writer. The new
    `agents/research_scheduler` is the deterministic ordering/planning layer above
    the unchanged M7 execution core and M9 learning core: it decides *which
    already-approved ideas run next and in what order*, but never approves,
    claims, specs, or executes — dispatch candidates come only from
    `approval_queue.list_approved`, so nothing is planned without clearing the
    human gate, and its only write is to `scheduler_event`. Four queues are pure
    projections of stored state: `campaign_queue` (ACTIVE, non-budget-exhausted
    campaigns ordered by `goal_spec.priority` then `campaign_id`), `priority_queue`
    (approved ideas ranked by PR-5 Research Value, in-flight excluded),
    `experiment_queue` (the dispatch plan: due retries first, then fresh ideas by
    campaign order then rank, respecting per-campaign `budget − produced −
    in_flight` and an optional global cap), and `retry_queue` (failed ideas with
    dispatch count below `max_retries + 1`, exhausted past it). `reconcile()`
    recovers interrupted runs from ground-truth stored state (executed ⇒
    succeeded, rejected ⇒ failed, still-pending ⇒ failed/`interrupted` and
    retry-eligible) and delegates campaign reconciliation to
    `CampaignManager.reconcile_all()`; it is idempotent. Because the log is
    append-only and carries the attempt number, every decision is reconstructible
    from storage. Touches only `agents/`.
  - **PR-7 (done) — Deterministic research loop.** Schema v12 adds the
    append-only `loop_checkpoint` log; `agents/storage/loop_store.py` is its sole
    writer. The new `agents/research_loop` is the top-level orchestrator that ties
    the M10 decision layer into a single resumable *tick* over one campaign,
    walking a fixed six-phase sequence — **recover → generate → schedule →
    dispatch → learn → checkpoint** — with every phase bracketed by
    `started` / `completed` checkpoints. It is pure orchestration: it **may**
    generate (ResearchStrategist), prioritize + schedule (ResearchScheduler /
    ResearchPrioritizer), dispatch *already-approved* ideas through the unchanged
    M7 executor (which runs the M9 learning path), and checkpoint; it **may not**
    auto-approve ideas, execute unapproved ideas, modify experiment results, or
    change M7 runner logic. Each phase is skipped when its `completed` checkpoint
    already exists, so a crashed tick resumes exactly where it stopped without
    repeating side effects; the deterministic `tick_id`
    (`<campaign_id>#tNNNN`, resume-latest-unfinished-else-next) is derived purely
    from the checkpoint log, making every tick reconstructible from storage.
    Recovery is covered for crash-before-dispatch, crash-after-dispatch
    (idempotent, no double execution), crash-after-ledger-write (R1 repair, no
    duplicate experiment), and cold-restart reconciliation. Touches only
    `agents/`.
  - **PR-8 (done) — Exploration quota + anti-mode-collapse safeguards.** No
    schema change — pure selection/ordering policy over already-stored state.
    The new storage-free `agents/research_quota` `ExplorationPlanner` reserves
    `ceil(exploration_fraction × window)` of every dispatch window for the best
    **explore** ideas *before* exploit ideas fill it, so high-value exploit ideas
    can never consume all approval slots; an idea is `explore` when its target M9
    context cell is under-sampled (PR-5 EIG ≥ threshold), `exploit` otherwise. A
    context-diversity cap (`SchedulerConfig.max_per_context`, default 2) stops one
    `signal × market × universe × bar_type` context from dominating a tick
    (retries exempt). The ResearchStrategist gains a frontier-expansion bound
    (`max_children_per_frontier`, default 3) that retires a hypothesis node from
    the frontier once it has spawned that many children, bounding repeated
    expansion of the same node. Campaign-level explore/exploit accounting
    (`ResearchScheduler.exploration_stats`) is derived purely from the
    append-only `scheduler_event` log, so it is reconstructible and survives a
    restart. The bucket is surfaced on `DispatchItem` and recorded in each
    `dispatched` event; the loop reports per-tick explore/exploit counts in its
    schedule-phase checkpoint. It never approves, executes, or evaluates anything,
    adds no adaptive/self-modifying weights, and leaves the M7 execution path, the
    M9 learning path, the human approval gate, and the PR-7 loop structure
    untouched. Touches only `agents/`.
  - **PR-9 (done) — CampaignReporter.** A strictly read-only reporting surface
    over the M10 loop, added to the existing `agents/reporting/` package. The new
    `campaign_report_store.py` mirrors `context_report_store.py`: it issues no SQL
    of its own and composes the storage read APIs (`campaign_store`,
    `campaign_attribution`, `scheduler_store`, `hypothesis_store`, `context_store`,
    `signal_store`, `lessons_store`) into frozen dataclasses for eight reports —
    campaign overview, deterministic campaign ranking, stalled-campaign board,
    exploration-vs-exploitation accounting, productive contexts, recently-learned
    knowledge, signal lifecycle board, and the hypothesis evolution tree. Campaign
    state is derived via `campaign_store.reconstruct_state_from_events` (event log,
    not projection row); exploration accounting reads the same `scheduler_event`
    evidence as `ResearchScheduler.exploration_stats`, so a report can never
    disagree with the live scheduler. `campaign_report.py` renders the markdown
    campaign board. No schema change, no writes, no execution-module imports
    (enforced by the globbed reporting guard tests). Touches only `agents/` and
    `docs/`.

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
