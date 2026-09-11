# Phase 6 — Research Factory Orchestration: Implementation Status

Living tracker for the Phase 6 build-out. Design is frozen by
[`PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md`](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md)
(spine) and [`PHASE6_RESEARCH_PORTFOLIO.md`](./PHASE6_RESEARCH_PORTFOLIO.md)
(planning layer). This file tracks what has been *implemented* against that plan.

_Last updated: 2026-09-11 — after P6-14 opened for review._

## Status at a glance

| PR | Title | State | New/changed | On main |
| --- | --- | --- | --- | --- |
| P6-1 | Assess phase (M11 DAG in the loop) | ✅ Merged | `loop.assess`, `PHASE_ASSESS` | yes (#48) |
| P6-2 | Campaign types + HypothesisSource registry | ✅ Merged | `research_campaign.campaign_type`, `research_loop/sources.py` | yes (#49) |
| P6-3 | FactoryRunner | ✅ Merged | `research_loop/factory_runner.py`, `CampaignManager.advance` | yes (#50) |
| P6-4 | Project 07 hand-off (preliminary→authoritative) | ✅ Merged | `project07_evaluation`, `storage/handoff_store.py` | yes (#51) |
| P6-5 | Near-term sources (bar-type/overlay/replay) | ✅ Merged | self-registering `research_loop/sources/` package + 3 sources | yes (#52) |
| P6-6 | Scale pass (shared fold cache / incremental assess) | ⬜ Not started | (planned) | — |
| P6-8 | Extended campaign fields (trigger/dependency/priority/EIG/repeat/portfolio_id) | ✅ Merged | 7 additive `research_campaign` columns + accessors | yes (#53) |
| P6-9 | Research Portfolio object | ✅ Merged | `research_portfolio` + `portfolio_state_events` + `portfolio_store` + CampaignManager portfolio state machine | yes (#54) |
| P6-10 | PortfolioPlanner (pure policy) | ✅ Merged | `portfolio_planner/` pure module (priority + eig_weighted; round_robin deferred) | yes (#55) |
| P6-11 | Triggers / dependencies / repeats in CampaignManager | ✅ Merged | CampaignManager eligibility API + planner delegates | yes (#56) |
| P6-12 | Dependency-aware planning + cycle rejection | ✅ Merged | planner cycle rejection (`detect_cycles`, `excluded_cycles`) | yes (#57) |
| P6-13 | Portfolio budget allocation _(was P6-12)_ | ✅ Merged | planner `allocate_budget` reusing frozen M11 `budget.allocate` | yes (#58) |
| P6-14 | EIG aggregation (from budget_allocation) _(was P6-13)_ | 🔷 Open for review | CampaignManager `compute_eig`/`refresh_eig` + cache writer | PR open |

Dependency order: **P6-1 → P6-2 → P6-3** form the spine (a continuously running
factory over the existing agents). P6-4 clarifies evaluation authority. P6-5/6 and
the portfolio layer (P6-8…P6-14) layer on and can be reordered.

**Reorder (approved):** P6-12 is now *Dependency-aware planning + cycle rejection*;
the design doc's original P6-12 (*Portfolio budget allocation*) → **P6-13** and P6-13
(*EIG aggregation*) → **P6-14**. Sanctioned by the design's "P6-11/12/13 … can be
reordered" clause; the design doc's §16 breakdown keeps the original labels.

---

## P6-1 — Assess phase ✅ (#48)

- **Responsibility:** run the frozen M11 engine DAG inside `ResearchLoop` as an
  `assess` phase (record evidence → EvidenceProjector → Holdout → FDR → Retirement →
  Promotion → Budget → Generalisation → Failure → Explanation), checkpointed.
- **Scope:** only `ResearchLoop`/`loop_store` (sanctioned orchestration hook). M11
  engines invoked, not modified.

## P6-2 — Campaign types + HypothesisSource registry ✅ (#49)

- **Responsibility:** campaigns declare WHAT via `campaign_type`; a data-driven
  `HypothesisSource` registry routes the generate phase; existing agents decide HOW.
- **Scope:** additive `campaign_type` column (CREATE + `_ADDITIVE_COLUMNS`, SCHEMA
  22→23); `research_loop/sources.py`; `_do_generate` routing. Default
  `strategy_evolution` = pre-Phase-6 behaviour.

## P6-3 — FactoryRunner 🔷

- **Responsibility:** thin, stateless, resumable driver — discover runnable
  campaigns (scheduler), tick them in deterministic order (loop), advance stop
  conditions (CampaignManager), bounded & terminating; no duplicated execution on
  restart.
- **Interfaces:** `research_loop/factory_runner.py` (`FactoryRunner`,
  `FactoryReport`); `CampaignManager.advance` (budget-exhaustion → COMPLETED,
  reusing `complete`).
- **Reuse:** the `ResearchScheduler` and `ResearchLoop` core are unchanged; the
  runner holds no state (progress lives in existing stores).
- **Deferred here:** stall detection + rich `stopping_spec` predicates (P6-8); the
  report step (P6-8); dependency-gated runnability arrives when P6-8 extends the
  scheduler and the runner picks it up automatically.
- **State:** merged (#50).

## P6-4 — Project 07 hand-off (preliminary → authoritative) 🔷

- **Responsibility:** make the evaluation-authority boundary explicit — M11 factory
  output is *preliminary*; Project 07 is the *authoritative* evaluator. A DERIVED
  hand-off queue (COMPLETED campaigns not yet evaluated) and a Project-07-only write
  path for its verdict.
- **Interfaces:** `project07_evaluation` table (SCHEMA 23→24, additive);
  `storage/handoff_store.py` — `pending_handoffs`, `record_evaluation`,
  `get_evaluation`/`list_evaluations`, `evaluation_status`.
- **Reuse:** no FactoryRunner/loop/scheduler/CampaignManager change; the queue is
  derived from existing campaign state. The factory never writes the table.
- **Isolation:** `handoff_store` imports only the campaign store + DB; no Project 07
  or Chrysos import (asserted by tests).
- **State:** merged (#51).

## P6-5 — Self-registering sources + near-term campaign types 🔷

- **Responsibility:** make the `HypothesisSource` registry **self-registering** and
  add the three near-term sources (`bar_type_comparison`, `overlay_combination`,
  `counterfactual_replay`) — each a thin, deterministic `propose`.
- **Interfaces:** `research_loop/sources/` package — `@register` decorator,
  `build_registry(SourceContext)`, generic `HypothesisSource`/`Proposal`, shared
  `enqueue_proposal`/`existing_specs` helpers; three source modules that self-register.
- **Reuse:** the loop resolves `registry[campaign_type].propose()` and names no
  source (one-line wiring change to thread `db_path`); sources reuse the existing
  enqueue + approval-gate path; scheduler/runner untouched.
- **Determinism/replay:** sources enumerate in sorted order and skip already-proposed
  `(bar_type, hypothesis)` pairs (converge, no re-proposals); replay only appends new
  ideas, never mutates originals.
- **Deferred:** external adapters (`literature_review`, `github_mining`) → P6-7;
  auto-sourcing replay specs from the ledger → future (Non-goal §18).
- **State:** merged (#52).

## P6-8 — Extended campaign fields 🔷 (portfolio spine, brick 1)

- **Responsibility:** additive `research_campaign` columns carrying the portfolio
  planning inputs — `priority`, `trigger_spec`, `depends_on`,
  `expected_information_gain`, `eig_spec`, `repeat_spec`, `portfolio_id`. Store only;
  consumption is P6-10/11/12/13.
- **Interfaces:** db.py schema (SCHEMA 24→25) + `portfolio_id` index; `campaign_store`
  insert/parse + effective-value accessors (`campaign_priority`, `campaign_trigger_spec`,
  `campaign_repeat_spec`, `campaign_depends_on`); `CampaignManager.create_campaign`
  optional params threaded through the genesis event.
- **Back-compat:** absent ⇒ NULL/spec-default ⇒ current behaviour; scheduler ordering
  unchanged (new `priority` column not consumed yet); legacy DBs migrate additively;
  fields reconstructible from the event log.
- **State:** merged (#53).

## P6-9 — Research Portfolio object 🔷 (portfolio spine, brick 2)

- **Responsibility:** the `research_portfolio` persistence model + its event-sourced
  lifecycle (ACTIVE/PAUSED/ARCHIVED). Persistence + state machine only.
- **Interfaces:** additive `research_portfolio` + `portfolio_state_events` tables
  (SCHEMA 25→26); `storage/portfolio_store.py` (DAL mirroring campaign_store);
  CampaignManager portfolio methods (`create_portfolio`, `pause/resume/archive`,
  `portfolio_state`, `rebuild_portfolio_from_events`, `reconcile_portfolio`,
  `campaigns_in_portfolio`) + `is_legal_portfolio_transition`/`PortfolioError`.
- **Reuse:** the CampaignManager owns the state machine (design §10 — no new agent);
  event-sourcing discipline is identical to campaigns; membership is the existing
  `research_campaign.portfolio_id`.
- **Not consumed yet:** `scheduling_policy`/`budget_spec` stored but not acted on
  (P6-10 planner / P6-12 budget); FactoryRunner + ResearchScheduler unchanged.
- **State:** merged (#54).

## P6-10 — PortfolioPlanner 🔷 (portfolio spine, brick 3)

- **Responsibility:** a **pure** planner (module/function, no agent) producing a
  deterministic execution plan — the admitted, ordered runnable campaign_ids per
  ACTIVE portfolio. Reads only; executes/mutates/allocates nothing.
- **Interfaces:** `agents/portfolio_planner/` — `PortfolioPlanner.plan(portfolio_id)`
  / `plan_all()` → `PortfolioPlan`.
- **Policy:** runnable = ACTIVE + not budget-exhausted + dependencies satisfied
  (reusing CampaignManager state/budget derivation); order by `priority` or
  `eig_weighted` (`-priority, -EIG, campaign_id`), then a stable dependency-aware
  refinement; admit up to `concurrency_limit`.
- **Scope decisions (confirmed with reviewer):** `round_robin` deferred → priority
  fallback (needs a logical-tick cursor not yet stored); `eig_weighted` uses raw
  priority then EIG (no invented tiers); triggers/repeats handled **state-based only**
  (predicate/re-entry logic stays in CampaignManager/P6-11).
- **Untouched:** ResearchScheduler + FactoryRunner behaviour; no schema change;
  Project 07 boundary; append-only/event-sourced state.
- **State:** merged (#55).

## P6-11 — Trigger-aware planning 🔷 (portfolio spine, brick 4)

- **Responsibility:** move trigger/dependency/repeat **evaluation** into the
  CampaignManager (sole owner) as pure predicates; the PortfolioPlanner obtains
  eligibility from it (no duplicated trigger logic). Planner stays pure.
- **Interfaces:** `CampaignManager.is_eligible` / `trigger_satisfied` /
  `dependencies_satisfied` / `repeat_eligible` (+ trigger/repeat constants);
  `campaign_store.normalized_depends_on` (single dependency-normalisation source);
  planner runnable filter delegates to `is_eligible`.
- **Scope decisions (confirmed with reviewer):** `manual` + `dependency` triggers and
  `once` + `interval` (count-capped) repeats evaluated now; `schedule`/`event`
  triggers, interval-cooldown, and `until` predicates deferred (need the logical-tick
  clock / predicate catalog). Firing transitions deferred to a clock-bearing PR.
- **Untouched:** ResearchScheduler + FactoryRunner; no schema change; append-only +
  Project 07 boundary.
- **State:** merged (#56).

## P6-12 — Dependency-aware planning + cycle rejection 🔷 (portfolio spine, brick 5)

- **Responsibility:** complete dependency-aware ordering and add §4 dependency-cycle
  rejection — cyclic campaigns (and any depending on a cycle) are excluded from the
  plan, never force-ordered. Planner stays pure; CampaignManager still owns
  eligibility/dependency satisfaction.
- **Interfaces:** `PortfolioPlanner.detect_cycles(portfolio_id)`; `PortfolioPlan`
  gains `excluded_cycles`; `_topo_order` returns `(emitted, excluded)`.
- **Reuse:** dependency normalisation stays the single `normalized_depends_on` source;
  eligibility comes from `CampaignManager.is_eligible`.
- **Untouched:** CampaignManager (no new logic), ResearchScheduler, FactoryRunner; no
  schema change; append-only + Project 07 boundary.
- **Reorder:** takes the P6-12 slot; budget → P6-13, EIG → P6-14 (approved).
- **State:** merged (#57).

## P6-13 — Portfolio budget allocation 🔷 (portfolio spine, brick 6)

- **Responsibility:** deterministic portfolio-level budget split across admitted
  campaigns (§9), reusing the frozen M11 `budget.allocate` (water-filling + `a_max`
  ceiling + integer floor) — no budget logic duplicated, no scoring invented.
- **Interfaces:** `PortfolioPlanner.allocate_budget(portfolio_id)` /
  `allocate_budget_all()` → `BudgetAllocation`; `budget_spec` = `{total, mode,
  a_max?, a_min?}`, mode ∈ equal / priority_proportional / eig_proportional.
- **Resolved (reviewer):** eig_proportional reads the cached EIG column, degrading to
  uniform until P6-14; shares clamped to the campaign's own `budget_experiments`
  (>0); unused budget kept as explicit headroom (never force-spent).
- **Untouched:** CampaignManager, ResearchScheduler, FactoryRunner; M11 methodology
  (its allocator is called, not modified); no schema change; append-only + Project 07
  boundary. Enforcement of shares is a separate future seam (pure allocation only).
- **State:** merged (#58).

## P6-14 — EIG aggregation 🔷 (portfolio spine, brick 7 — final)

- **Responsibility:** derive campaign-level EIG by aggregating M11
  `budget_allocation.evoi` over a campaign's live hypotheses (§5) and cache it on the
  campaign; closes the loop feeding P6-13's eig_proportional budget / eig-weighted
  ordering.
- **Interfaces:** `CampaignManager.compute_eig` (pure) / `refresh_eig` /
  `refresh_all_eig`; `campaign_store.set_expected_information_gain` cache writer.
- **Reuse:** reads existing `evidence_store` + `budget_store`; the id space is the
  shared `hypothesis_node.node_id`. No new statistic; `eig_spec.aggregate` ∈
  mean(default)/sum/max; promotion_headroom deferred → mean fallback.
- **Ownership:** CampaignManager stays the sole `research_campaign` writer (mirrors
  refresh_progress); PortfolioPlanner only reads the cached column.
- **Untouched:** M11 methodology (read-only), ResearchScheduler, FactoryRunner; no
  schema change; append-only + Project 07 boundary.
- **State:** open for review (this PR).

---

## Invariants (hold across all Phase-6 PRs)

- No new permanent agents; existing coordinators gain thin responsibilities.
- Frozen: M11 engines/methodology, Bar Engine, executor. Only sanctioned additive
  orchestration hooks in M10 (loop / campaign_manager / campaign schema).
- Deterministic replay + append-only/event-sourced state preserved; checkpoint /
  resume compatibility maintained.
- Project 07 remains the authoritative statistical evaluator; M11 factory output is
  preliminary (formalised in P6-4).
- Complete separation between quant-lab and chrysos-doc-agent (no Chrysos imports,
  config, memory, tooling, or references).
