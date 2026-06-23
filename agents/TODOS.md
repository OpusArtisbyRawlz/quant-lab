# Known Limitations — Milestone 2 (Quant Interface Layer)

This file documents known gaps and design decisions deferred from Milestone 2.
Each item is intentional: the code handles the case gracefully (warning, skip,
or fallback) rather than raising. Future milestones can address them as needed.

---

## 1. YAML Config Parsing Requires PyYAML

**File:** `agents/quant_interface/artifact_reader.py` — `_parse_yaml_safe()`

PyYAML is not installed in this project. If an experiment folder contains
`config.yaml` instead of `config.json`, the reader will log a warning:

> `config.yaml: PyYAML not installed — config.yaml cannot be parsed.`

The bundle is still returned with `config=None` and all other fields populated.

**Fix:** `pip install pyyaml` and add to `requirements.txt`.
All existing experiments use `config.json` so this is low priority.

---

## 2. Nested Artifact Traversal Not Supported

**File:** `agents/quant_interface/ingestion.py` — `ingest_all_completed()`

`ingest_all_completed()` only scans the **direct children** of `experiments/completed/`.
Experiment folders whose artifacts live in subdirectories (e.g. a `results/` subfolder
inside the experiment directory) are not traversed.

**Observed cases:**
- `exp_005_risk_engine_v1` — artifacts in subdirectory, skipped
- `exp_006_failure_analysis` — artifacts in subdirectory, skipped

**Fix:** Add optional recursive traversal with depth limit, or define a convention
(e.g. flatten all artifacts into the root of each experiment folder).

---

## 3. Experiment Type Taxonomy Is Heuristic

**File:** `agents/quant_interface/artifact_reader.py` — `detect_experiment_type()`

Type detection is based on metric key-set intersection and config model-name hints.
It is a best-effort heuristic, not ground truth. Known edge cases:

- An experiment reporting both `sharpe` and `auc` will be classified as
  `classification` (classification keys take priority over portfolio keys).
- A portfolio experiment whose `config.json` contains `"model": "exposure_weighted"`
  will be classified as `risk_overlay` due to the config name hint.
- Experiments with no metrics, no config, and only a summary text will be `unknown`.

**Fix options:**
- Add an explicit `type` field to `config.json` per experiment.
- Allow human/agent override via `upsert_experiment({"experiment_type": "..."})`.
- Add a `--force-type` flag to `ingest_one()`.

---

## 4. Classification and Regression Metrics Not Mapped to Named Columns

**File:** `agents/quant_interface/ingestion.py` — `_upsert_from_bundle()`

By design, `sharpe`, `mdd`, `cagr`, `vol`, and `calmar` columns in the
`experiments` table are left `NULL` for classification and regression experiments.
All native metrics are stored in the `raw_metrics` JSON column instead.

This means queries like `ORDER BY sharpe DESC` will exclude classification and
regression experiments. Agents that need to rank across all experiment types must
parse `raw_metrics` and use the appropriate metric for each type.

**Fix:** Add type-specific metric columns to the schema, or add a `primary_metric_value`
float column populated with the most relevant metric per type (AUC for classification,
R² for regression, Sharpe for portfolio, Calmar for risk overlay).

---

## 5. Empty Experiments Folder in exp_004

`exp_004_return_forecast_alpha` was skipped during real ingestion because all
files present were empty (0 bytes). This is correct behaviour — the bundle is
flagged `is_empty` and the ingest result is `status="skipped"`.

No code change needed. The experiment should be re-run or its artifacts manually
populated before ingestion.

---

## 6. Signal Library Promotion Is Manual Only

**File:** `agents/quant_interface/ingestion.py` — `get_unpromoted_variants()`, `mark_variant_promoted()`

Strategy variants ingested from `strategy_comparison.csv` are stored in
`strategy_variants` with `promoted_to_library=0`. Promotion to `signal_library`
requires an explicit call to `mark_variant_promoted()`.

No automated promotion logic exists yet. A Critic Agent or human decision is
required to evaluate each variant and trigger promotion.

**Future:** Milestone 3 (Critic Agent) should consume `get_unpromoted_variants()`
and apply keep/reject/retest logic before writing to `signal_library`.

**Update (M9):** Automated, context-aware promotion now exists. The
`SignalLibrarian` (`agents/signal_librarian/`) runs after the Ledger and drives a
real `observed → candidate → promoted → retired` lifecycle on `signal_library`,
keyed on context cells (`feature × market × universe × regime × bar_type`).
Promotion requires multi-context confirmation. The manual
`strategy_variants → mark_variant_promoted()` path above is independent and still
manual; unifying the two is unscheduled. See
`docs/M9_CONTEXT_SIGNAL_INTELLIGENCE.md`.

---

## 7. research_campaign Is a Rebuildable Projection (M10 PR-1)

**File:** `agents/storage/campaign_store.py`; `agents/campaign_manager/manager.py`

The campaign layer is event-sourced. `campaign_state_events` is append-only and
the **single source of truth** (it carries no FK, mirroring M9's
`signal_lifecycle_events`, so it outlives the row). `research_campaign` is a
rebuildable *projection*:

- **Authoritative state** = `reconstruct_state_from_events()` (latest event's
  `to_state`); `research_campaign.state` is only a cache. `transition()` judges
  legality against the log, never the cached column.
- **Authoritative config** is carried in the genesis event's evidence, so the
  row's static fields are reconstructible.
- **Authoritative progress** = `count_campaign_experiments()`
  (`pending_ideas.campaign_id` joined to a non-null `experiment_id`);
  `budget_spent` is a cache.

`CampaignManager.reconcile()` / `reconcile_all()` repair the projection from the
log after an interrupted transition (event appended, cache update missed) or a
deleted/missing row; `rebuild_from_events()` recreates the row outright. Startup
reconciliation should call `reconcile_all()`. This is intentional, recoverable
design — not debt.

The loop that keeps caches fresh and ties campaigns to the idea pipeline arrives
in later M10 PRs (PR-3 linkage, PR-7 `run_tick` STEP 0 recovery).

---

## 8. Hypothesis Tree Is Append-Only and Storage-Reconstructible (M10 PR-2)

**File:** `agents/storage/hypothesis_store.py`;
`agents/hypothesis_manager/manager.py`

`hypothesis_node` and `hypothesis_edge` are append-only. A node is an immutable,
fully-auditable record; it is never updated in place except for two write-once
link stamps (`idea_id`, `experiment_id`) applied when an idea/experiment is
created from it elsewhere — the hypothesis content itself is never mutated. Every
non-root node records its primary `parent_id`, `root_id`, `depth`, and the
`origin_operator` that produced it; every parent→child relationship is also an
explicit `hypothesis_edge` carrying the operator. `combine` is the one
multi-parent operator (a DAG): it writes one `combine` edge per merged parent
into a single child whose primary parent is the first.

`HypothesisTreeManager` is the sole writer; `reconstruct_tree` /
`reconstruct_forest` / `lineage` rebuild the structure purely from storage, with
tests proving lossless reconstruction and operator preservation.

**Not yet wired:** nodes are not yet generated by the IdeaGenerator or linked
into the campaign loop — that arrives in PR-3 (campaign/idea linkage) and PR-4
(ResearchStrategist drives the operators). The `signals` inheritance on `evolve`
is a convenience default, not a feasibility check; signal validity is still
enforced downstream by the existing M6 validator.

---

## 9. Campaign Attribution Is Derived, Not Stored (M10 PR-3)

**File:** `agents/storage/campaign_attribution.py`;
`agents/storage/campaign_store.py` (`link_idea_to_campaign`,
`campaign_id_for_idea`)

Every M10 artefact — hypothesis, approved idea, experiment, lesson, M9
observation — is attributable to its originating campaign, but attribution is
**derived at read time**, never stored on the artefact. The only stored anchors
are `pending_ideas.campaign_id` and `hypothesis_node.campaign_id` (both additive,
write-once). Everything else is reached by following keys that already exist:
ideas → `experiment_id` → experiments → `lessons_learned.experiment_id` /
`signal_context_observation.experiment_id`.

Consequences (all intentional, and tested in `test_campaign_attribution.py`):

- **Reconstructible from storage.** `campaign_attribution` reads only existing
  link columns; no projection or cache backs attribution.
- **Survives rebuilds.** Because the anchors live on the ideas/hypotheses and
  not on `research_campaign`, deleting and `rebuild_from_events()`-ing the
  campaign row leaves `attribution_summary` / `lineage_for_experiment`
  unchanged.
- **Non-campaign experiments untouched.** An ad-hoc idea has `campaign_id` NULL,
  so `campaign_for_experiment()` returns None and the experiment never appears
  in any campaign's artefacts — M7/M8/M9 paths are unaffected.
- **Observations queryable independently.** `observations_for_campaign()` is a
  campaign-scoped view over the global `signal_context_observation` table; it
  never modifies or duplicates the global rows (M9 requirement 4).

`link_idea_to_campaign` only sets `campaign_id` when it is currently NULL, so an
idea's campaign attribution is never silently re-pointed. The module is
read-only and touches no execution, approval, or evaluation code.

## 10. ResearchStrategist + First-Class `bar_type` (M10 PR-4)

**File:** `agents/research_strategist/` (`strategist.py`, `__init__.py`);
`agents/protocol.py` (`SUPPORTED_BAR_TYPES`, `normalize_bar_type`,
`ExperimentSpec.bar_type`, `ProposedIdea.bar_type`); `agents/storage/db.py`
(schema v10); `agents/idea_generator/{approval_queue,spec_builder}.py`;
`agents/quant_interface/ingestion.py`; `agents/hypothesis_manager/manager.py`.

**`bar_type` is a first-class typed field, not free text.** It is carried end to
end — `hypothesis_node.bar_type` → `pending_ideas.bar_type` →
`ExperimentSpec.bar_type` → `config.json` → `experiments.bar_type` — via
additive `NOT NULL DEFAULT 'time'` migrations (schema v10). Supported values are
exactly `time, volume, dollar, tick, volume_imbalance, dollar_imbalance`;
`normalize_bar_type` rejects anything else and maps `None`/`""` to `time`. This
is deliberate so the Alternative Bars campaign needs **no further migration** the
day a bar-construction engine is added.

**Deferral (intentional, not debt):** the bar-construction engine belongs to a
later milestone. The schema and interfaces are complete now; the runner
currently realizes only `time` bars, so non-time ideas are representable,
queueable, and fully auditable but not yet executable.

**The strategist is a deterministic decision layer.** No LLM. Each tick it reads
campaign state + budget (`CampaignManager`), M9 context evidence
(`context_store`, read-only), and the hypothesis frontier
(`HypothesisTreeManager`), then derives bounded `Proposal`s. On `apply` it writes
children into the hypothesis tree and enqueues them as `pending` ideas in the
existing approval queue, campaign-tagged. It never executes, schedules, approves,
or evaluates — the human gate and the M7/M9 cores are untouched. Auto-triggers:
`vary_bar`, `cross_market`, `combine`, `negate`; `refine`/`add_filter` are
interface-complete via `apply`. Explosion safeguards: ACTIVE + not
budget-exhausted, `max_depth`, frontier dedup, terminal `negate` children, one
move per signal/market/universe lineage per tick, `max_proposals_per_tick`.

## 11. ResearchPrioritizer Is Deterministic and Read-Only (M10 PR-5)

**File:** `agents/research_prioritizer/` (`prioritizer.py`, `__init__.py`)

The prioritizer ranks `pending` ideas by an explainable *Research Value* score
and enforces an exploration quota. It is **deterministic** (a fixed, normalised
weighted blend of five `[0,1]` components) and **read-only**: it reads ideas via
`approval_queue.list_pending` plus M9 (`context_store`), campaign
(`campaign_store`), and memory (`memory_store`) evidence, and returns an ordering
with a per-idea `ScoreBreakdown`. It never executes, schedules, approves, or
mutates ideas; it adds no schema; the M7 execution path, the M9 learning path,
and the human approval gate are untouched — ranking only changes the *order* a
human sees.

Components (each `[0,1]`, all surfaced in the breakdown for auditability):

- **Expected Information Gain** — `1/(1+n)` in the prior-experiment count of the
  idea's target M9 context cell (signal, market, universe, bar_type). Thin
  evidence ⇒ high EIG.
- **Novelty** — batch-structural anti-redundancy: `1/(1+d)` in the number of
  sibling candidates sharing the idea's (signal, market, universe, bar_type)
  key. Deliberately distinct from EIG (DB evidence) so the two never collapse
  into one number.
- **Memory Score** — neutral `0.5`, nudged by supportive vs cautionary
  research-memory entries matching the idea's scope. Keyword-based on purpose;
  semantic handling stays under **TD-5**.
- **Campaign Priority** — the owning campaign's `goal_spec.priority`; a neutral
  default for off-campaign ideas.
- **Cost** — estimated research cost (bar-type construction complexity + signal
  count), folded in as *cheapness* (`1 - normalised_cost`). This is a ranking
  estimate only and is unrelated to the execution/backtest cost model.

**Exploration quota.** Each idea is bucketed `explore` (EIG ≥
`explore_eig_threshold`) or `exploit`. When a cutoff `top_k` is given, the
prioritizer reserves `ceil(exploration_fraction * top_k)` of those slots for the
best explore ideas before filling the rest by value, so exploit ideas — however
high-scoring — cannot crowd exploration out of the selection window. Ordering is
a total order with `idea_id` tie-breaks, so identical inputs always produce an
identical ranking.


## 12. ResearchScheduler Is a Deterministic, Auditable Planner (M10 PR-6)

**Files:** `agents/research_scheduler/` (`scheduler.py`, `__init__.py`),
`agents/storage/scheduler_store.py`, `scheduler_event` table (schema v11).

The scheduler is the deterministic *ordering / planning* layer above the
unchanged M7 execution core and M9 learning core. It decides **which already
human-approved ideas run next, in what order**, enforces per-campaign and global
budgets, and schedules retries — but it never approves, claims, specs, or
executes anything. Dispatch candidates come **only** from
`approval_queue.list_approved`, so no idea can be planned without first clearing
the human approval gate, and the scheduler's only write is to the append-only
`scheduler_event` log.

**`scheduler_event` is the source of truth (and the sole-writer pattern).** Every
scheduler decision is one immutable row: `dispatched` / `succeeded` / `failed` /
`retry_scheduled` / `exhausted`, carrying the idea, campaign, attempt number, and
supporting evidence (plan rank, research value). `scheduler_store` is the only
writer. Because the log is append-only and records the attempt number, every
derived quantity — dispatch ordering, budget accounting, retry eligibility,
recovery — is a pure function of stored state, so the scheduler is fully
deterministic and resumable (restart + recompute ⇒ identical plan).

**Four derived queues (all read-only projections of stored state):**

- **`campaign_queue`** — runnable campaigns (event-derived state ACTIVE and not
  budget-exhausted), ordered by descending `goal_spec.priority` then ascending
  `campaign_id` (a total order).
- **`priority_queue`** — approved ideas ranked by the PR-5 Research Value score,
  with in-flight ideas excluded.
- **`experiment_queue`** — the concrete dispatch plan: due retries first (oldest
  failure first), then fresh ideas grouped by `campaign_queue` order and ranked
  within each group, then ad-hoc ideas — respecting per-campaign remaining budget
  (`budget − produced − in_flight`) and an optional global cap.
- **`retry_queue`** — ideas whose latest event is `failed` and whose dispatch
  count is below `max_attempts` (`max_retries + 1`); past that the idea is
  `exhausted`.

**Recovery / reconciliation.** `reconcile()` resolves every orphaned open
dispatch from ground-truth stored state: an `executed` idea ⇒ `succeeded`; a
`rejected` idea ⇒ `failed`; anything still approved/executing (an interrupted
run) ⇒ `failed` with reason `interrupted`, making it retry-eligible. Campaign
projections are reconciled by delegating to `CampaignManager.reconcile_all()`.
`reconcile()` is idempotent (it only acts on currently-open dispatches).

The M7 execution path, the M9 learning path, and the human approval flow are
untouched — the scheduler only changes *order and timing*, never *whether* an
idea runs.


## 13. ResearchLoop Is a Deterministic, Resumable Orchestrator (M10 PR-7)

**Files:** `agents/research_loop/` (`loop.py`, `__init__.py`),
`agents/storage/loop_store.py`, `loop_checkpoint` table (schema v12).

The loop is the top-level orchestrator that ties the M10 decision layer into a
single resumable *tick* over one campaign. Each tick walks a fixed six-phase
sequence — **recover → generate → schedule → dispatch → learn → checkpoint** —
and brackets every phase with append-only `loop_checkpoint` rows
(`started` / `completed`). It is pure orchestration over already-built
components; `loop_store` is the sole writer of the checkpoint log.

**Resumability / idempotency primitive.** Each phase is skipped when a
`completed` checkpoint already exists for that `(tick_id, phase)`, so a crashed
tick resumes exactly where it stopped and never repeats a phase's side effects
(idea generation, scheduling, execution). The `tick_id` is deterministic and
derived purely from the checkpoint log: the latest unfinished tick is resumed,
otherwise the next sequential id (`<campaign_id>#tNNNN`) starts. This makes the
whole tick history reconstructible from storage.

**The six phases:**

- **recover** — cross-tick reconciliation before planning: the unchanged M7
  `recover_incomplete_executions` repairs ledger-write crashes (an `executing`
  idea with a linked experiment is re-ledgered, never re-run) and
  `ResearchScheduler.reconcile()` resolves orphaned dispatches. Both idempotent.
- **generate** — `ResearchStrategist.run_tick` expands the hypothesis frontier
  into new **pending** ideas. Runs only when the campaign is ACTIVE. Nothing is
  auto-approved.
- **schedule** — `ResearchScheduler.dispatch` ranks the approved pool (via the
  PR-5 prioritizer), respects budgets, and appends `dispatched` events. No
  execution.
- **dispatch** — executes the scheduled in-flight ideas through the **unchanged
  M7 executor** (claim → spec → M5 runner → Critic → Ledger → M9 Librarian) and
  records each outcome as a `succeeded` / `failed` scheduler event. Re-running is
  idempotent: a resolved idea leaves the in-flight set, and an already-`executed`
  idea is only recorded, never re-run.
- **learn** — refreshes the campaign's derived progress via
  `CampaignManager.reconcile` (the M9 signal learning already happened inside the
  executor). Idempotent.
- **checkpoint** — terminal marker that makes the tick `completed` and therefore
  reconstructible.

**Invariants preserved (asserted by tests).** The loop never auto-approves
(generated ideas stay `pending`); it never executes an unapproved idea (the
scheduler selects only `approved` ideas and the executor refuses anything not
`approved`); it never modifies experiment results or M7 runner logic (it
delegates to the executor unchanged). Recovery is tested for crash-before-
dispatch, crash-after-dispatch (idempotent, no double execution), crash-after-
ledger-write (R1 repair, no duplicate experiment), and cold-restart
reconciliation.


## 14. Exploration Quota + Anti-Mode-Collapse Safeguards (M10 PR-8)

**Files:** `agents/research_quota/` (`quota.py`, `__init__.py`) — the new pure,
storage-free `ExplorationPlanner`; wired into `agents/research_scheduler/
scheduler.py`; frontier bound added to `agents/research_strategist/strategist.py`;
per-tick accounting surfaced in `agents/research_loop/loop.py`. **No schema
change** — PR-8 is policy over already-stored state.

PR-8 stops the autonomous loop from collapsing onto a single high-value exploit
context. Five safeguards, all deterministic and reconstructible from storage:

1. **Exploit vs explore classification.** Reuses the PR-5 prioritizer's
   `ScoreBreakdown.bucket` (`explore` when the target M9 context cell's EIG ≥
   `explore_eig_threshold`, i.e. an under-sampled cell; else `exploit`). The
   scheduler surfaces it on `DispatchItem.bucket` and records it in the
   `dispatched` event's evidence.
2. **Exploration quota enforcement.** The `ExplorationPlanner` reserves
   `ceil(exploration_fraction × window)` of each dispatch window for the best
   explore candidates *before* exploit ideas fill the window, so high-value
   exploit ideas can never consume every slot. The fraction defaults to the
   prioritizer's `exploration_fraction` so scheduler and prioritizer share one
   policy; `SchedulerConfig.exploration_fraction` overrides.
3. **Context-diversity safeguard.** No more than
   `SchedulerConfig.max_per_context` (default 2) *fresh* ideas sharing one M9
   context key (`signal × market × universe × bar_type`) enter a single dispatch
   window; retries are exempt. Prevents one context dominating a tick.
4. **Frontier-expansion control.** `StrategistConfig.max_children_per_frontier`
   (default 3) retires a hypothesis node from the frontier once it has spawned
   that many children, bounding repeated expansion of the same node across ticks.
   The child count is read from the persisted tree, so the bound is deterministic.
5. **Campaign-level exploration accounting.** `ResearchScheduler.exploration_stats
   (campaign_id=…)` derives explore/exploit/total counts purely from the
   append-only `scheduler_event` log, so the accounting is reconstructible and a
   fresh scheduler instance after a restart reports identical numbers.

**Invariants preserved (asserted by tests).** PR-8 is pure selection/ordering
policy: it never approves, executes, or evaluates anything, adds no schema, and
leaves the M7 execution path, the M9 learning path, the human approval gate, and
the PR-7 loop structure untouched. The exploration quota and context-diversity
caps only change *which approved ideas a human-approved pool dispatches first*,
never *whether* an idea runs. Tests cover: exploit cannot consume all slots; the
quota is respected across window sizes and fractions; explore selections map to
under-sampled contexts; repeated frontier expansion is bounded; rankings stay
deterministic; and quota accounting survives a simulated restart. No adaptive or
self-modifying weights are introduced — all parameters are fixed config.
