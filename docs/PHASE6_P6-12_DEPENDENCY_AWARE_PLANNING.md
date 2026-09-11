# Phase 6 — P6-12: Dependency-aware planning + cycle rejection

Implements **P6-12** (this increment): completes dependency-aware portfolio planning
and adds the §4 **dependency-cycle rejection** the design requires ("the dependency
graph is a DAG; cycles are rejected… a topological check"). The PortfolioPlanner
stays a pure planner; the CampaignManager remains the sole owner of eligibility /
trigger / repeat / dependency **satisfaction** (P6-11). No scheduler, runner, or
schema change.

## Reorder note (approved)

The design doc labelled P6-12 = *Portfolio budget allocation* and P6-13 = *EIG
aggregation*. Per the design's own allowance that "P6-11/12/13 layer on and can be
reordered," and with reviewer approval, this dependency/cycle work takes the **P6-12**
slot; **budget allocation → P6-13** and **EIG aggregation → P6-14**. The tracker
records the new sequencing.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/portfolio_planner/planner.py` | modified | Cycle-rejecting dependency-aware ordering: `_topo_order` now returns `(emitted, excluded)`; new `detect_cycles(portfolio_id)` public API; shared `_intra_prereqs` / `_unschedulable` helpers. `PortfolioPlan` gains `excluded_cycles`. |
| `agents/tests/test_dependency_aware_planning.py` | new | 17 tests (see Verification). |
| `docs/PHASE6_P6-12_DEPENDENCY_AWARE_PLANNING.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker (with the reorder). |

**No CampaignManager / ResearchScheduler / FactoryRunner change. No schema change.**

## Behaviour

For each ACTIVE portfolio, over the eligible set (obtained from
`CampaignManager.is_eligible` — the planner re-derives no eligibility/dependency
satisfaction):

1. **Order** by policy (priority / eig_weighted), then a **stable dependency-aware
   refinement** (deterministic Kahn's algorithm seeded by policy order) so a runnable
   prerequisite precedes a runnable dependent, policy order preserved otherwise.
2. **Reject cycles (§4):** any campaign that sits in a dependency cycle — or that
   transitively depends on one — cannot be validly ordered, so it is **excluded** from
   the admitted plan (never force-ordered) and reported in
   `PortfolioPlan.excluded_cycles`. The acyclic remainder still plans.
3. **Admit** up to `concurrency_limit`, applied after dependency ordering.

`detect_cycles(portfolio_id)` exposes the pure §4 topological check over a portfolio's
member graph (edges restricted to intra-portfolio members; an external prerequisite is
not part of the portfolio's graph), returning the sorted unschedulable set.

Dependency normalisation continues to come from the single source
`campaign_store.normalized_depends_on` (no duplicated dependency logic).

## Guarantees

- **Deterministic & replay-safe.** Ordering is a pure function of stored state; ties
  break on `campaign_id`; cycle exclusion is sorted. Same state ⇒ identical
  `admitted` + `excluded_cycles` (tested across two independently-built DBs).
- **Pure planner.** No execution, state mutation, budget allocation, or experiment
  evaluation; ownership boundaries from P6-11 intact (tested: planning + cycle
  detection change no campaign state).
- **Isolation preserved.** No Chrysos coupling; append-only/event-sourced state and
  the Project 07 hand-off boundary untouched (reads only).

## Verification

- New `test_dependency_aware_planning.py` (17): linear chains; branching graphs;
  independent campaigns; 2-node & 3-node cycles excluded; campaign depending on a
  cycle excluded; `detect_cycles` API (cycle, DAG-empty, external-dep ignored);
  multiple portfolios; archived/stalled excluded; paused portfolio; empty portfolio;
  deterministic ordering + replay determinism; planning purity; concurrency limit
  after dependency ordering.
- Full suite: **1343 passed, 1 skipped** (+17; P6-10/P6-11's 46 planner tests still
  green after the refactor). AST/boundary/import-closure guards: **68 passed**. No
  frozen module changed; CampaignManager/ResearchScheduler/FactoryRunner untouched;
  no Chrysos coupling.
