# Phase 6 — P6-10: PortfolioPlanner (pure planning policy)

Implements **P6-10** of the approved portfolio plan
([research portfolio design](./PHASE6_RESEARCH_PORTFOLIO.md) §8): the **pure**
`PortfolioPlanner` — a module/function (**not an agent**) that turns stored portfolio
+ campaign state into a **deterministic execution plan**. It **executes nothing,
mutates no state, allocates no budget, runs no experiments**, and **does not touch the
ResearchScheduler or FactoryRunner** (wiring `campaign_queue` to the planner is a
later, separate change).

## Scope decisions (confirmed before coding)

Three design tensions were resolved with the reviewer rather than by inventing policy:

1. **Policies:** implement `priority` and `eig_weighted` now. `round_robin` needs a
   least-recently-ticked / logical-tick cursor that is **not** an approved P6-10 input
   and is not yet stored, so it is **deferred** — a `round_robin` portfolio falls back
   to deterministic `priority` ordering (documented), with no new schema.
2. **`eig_weighted`:** the design's undefined `-priority_tier` term is read as the raw
   static `priority` → order `(-priority, -EIG, campaign_id)`. No bucketing invented.
3. **Triggers/repeats:** the planner is **state-based only**. "Trigger fired" ⇔ the
   campaign is `ACTIVE`; it does **not** evaluate schedule/event trigger predicates or
   repeat re-entry — those stay in the CampaignManager (§3/§6, P6-11).

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/portfolio_planner/planner.py` · `__init__.py` | new | `PortfolioPlanner` (pure) + `PortfolioPlan` (result dataclass). |
| `agents/tests/test_portfolio_planner.py` | new | 26 tests (see Verification). |
| `docs/PHASE6_P6-10_PORTFOLIO_PLANNER.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

**No storage/schema change. No scheduler/runner/manager change.**

## The plan (reuse, don't duplicate)

For each **ACTIVE** portfolio (`plan_all` iterates them, ordered by `portfolio_id`;
`plan(portfolio_id)` does one):

1. **Runnable filter** — member campaigns (via the existing
   `research_campaign.portfolio_id`) that are `ACTIVE`, **not budget-exhausted**
   (reusing `CampaignManager.current_state` / `budget_exhausted` — no parallel state
   logic), and whose **dependencies are satisfied**. A dependency (`depends_on`, §4:
   accepts the P6-8 bare-id form and the `{campaign_id, required_state}` dict form,
   default `COMPLETED`) is satisfied iff the target campaign's event-derived state
   equals its required state.
2. **Order** by the portfolio's `scheduling_policy` over the P6-8 fields, then a
   **stable dependency-aware refinement** (deterministic Kahn's algorithm seeded by
   the policy order) so a runnable prerequisite precedes a runnable dependent while
   policy order is preserved otherwise. Every key ends on `campaign_id` ⇒ a total
   order. EIG is read from the cached `expected_information_gain` column (populated by
   P6-13; absent ⇒ 0.0, so `eig_weighted` degrades gracefully to priority today).
3. **Admit** up to `concurrency_limit` (0 = unbounded) — an admission count cap, not
   budget allocation.

A non-ACTIVE (PAUSED/ARCHIVED) or unknown portfolio yields an **empty** plan.
Standalone campaigns (no `portfolio_id`) are out of scope — they keep today's
scheduler behaviour, which the planner never touches.

## Guarantees

- **Pure & replay-safe.** Every input (state, priority, EIG, dependencies,
  concurrency) is a pure function of stored state; ties break on `campaign_id`; no
  wall-clock, no randomness. Same state ⇒ identical plan (tested: two DBs built
  identically produce identical output; repeated planning mutates nothing).
- **Lifecycle-respecting.** DRAFT/STALLED/COMPLETED/ARCHIVED campaigns and
  PAUSED/ARCHIVED portfolios admit nothing.
- **Isolation preserved.** No Chrysos import; append-only/event-sourced state and the
  Project 07 hand-off boundary are untouched (the planner reads, never writes).

## Verification

- New `test_portfolio_planner.py` (26): single/multiple portfolios; priority ordering
  + equal-priority stability + goal_spec fallback; `eig_weighted` (priority-then-EIG,
  missing-EIG=0); `round_robin` fallback; concurrency limit + unbounded; dependency
  filtering + satisfied-admits + dependency-aware ordering + dict/default-state forms;
  trigger filtering (DRAFT excluded); paused/completed/archived campaigns excluded;
  repeat_spec doesn't change the plan; paused/archived/unknown portfolios empty; empty
  portfolio; standalone campaigns ignored; replay determinism / identical output;
  purity (no mutation); legacy compatibility.
- Full suite: **1306 passed, 1 skipped** (+26). AST/boundary/import-closure guards:
  **68 passed**. No frozen module changed; ResearchScheduler/FactoryRunner untouched;
  no Chrysos coupling.
