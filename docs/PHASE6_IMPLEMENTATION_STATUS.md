# Phase 6 — Research Factory Orchestration: Implementation Status

Living tracker for the Phase 6 build-out. Design is frozen by
[`PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md`](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md)
(spine) and [`PHASE6_RESEARCH_PORTFOLIO.md`](./PHASE6_RESEARCH_PORTFOLIO.md)
(planning layer). This file tracks what has been *implemented* against that plan.

_Last updated: 2026-09-11 — after P6-10 opened for review._

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
| P6-10 | PortfolioPlanner (pure policy) | 🔷 Open for review | `portfolio_planner/` pure module (priority + eig_weighted; round_robin deferred) | PR open |
| P6-11 | Triggers / dependencies / repeats in CampaignManager | ⬜ Not started | (planned) | — |
| P6-12 | Portfolio budget allocation | ⬜ Not started | (planned) | — |
| P6-13 | EIG aggregation (from budget_allocation) | ⬜ Not started | (planned) | — |

Dependency order: **P6-1 → P6-2 → P6-3** form the spine (a continuously running
factory over the existing agents). P6-4 clarifies evaluation authority. P6-5/6 and
the portfolio layer (P6-8…P6-13) layer on and can be reordered.

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
