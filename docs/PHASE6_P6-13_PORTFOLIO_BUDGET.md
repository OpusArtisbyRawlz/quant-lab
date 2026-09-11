# Phase 6 — P6-13: Portfolio budget allocation

Implements **P6-13** (corrected sequence: P6-12 = dependency/cycles, **P6-13 =
portfolio budget allocation**, P6-14 = EIG aggregation): deterministic portfolio-level
budget allocation across a portfolio's admitted campaigns (design §9), by **reusing the
frozen M11 Evidence Budget allocator** — no budget logic duplicated, no scoring
invented, M11 methodology unchanged.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/portfolio_planner/planner.py` | modified | `PortfolioPlanner.allocate_budget(portfolio_id)` / `allocate_budget_all()`; `BudgetAllocation` result; budget-mode constants; `_budget_weight`. Imports the frozen M11 `budget` pure allocator. |
| `agents/portfolio_planner/__init__.py` | modified | Export `BudgetAllocation`. |
| `agents/tests/test_portfolio_budget.py` | new | 21 tests (see Verification). |
| `docs/PHASE6_P6-13_PORTFOLIO_BUDGET.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

**No CampaignManager / ResearchScheduler / FactoryRunner change. No schema change.
M11 methodology untouched (its `budget.allocate` is *called*, never modified).**

## Design — reuse M11, don't recompute

`budget.allocate` (M11 PR-7) is a pure, deterministic water-filling allocator:
EVOI-proportional shares, clipped to the hard `a_max` anti-monopoly ceiling and
`a_min` floor, renormalised down-only, floored to integer experiment slots. §9 asks
for exactly this one level up ("mirroring the M11 budget's `a_max`"), so P6-13 **calls
that same function** with per-campaign *weights* instead of re-deriving any of it:

- `equal` → uniform weights;
- `priority_proportional` → weights = campaign priority (P6-8 accessor);
- `eig_proportional` → weights = cached `expected_information_gain` (P6-8 column,
  populated by **P6-14**; 0 until then ⇒ M11's "no signal → uniform" path, so it
  degrades gracefully to equal). **P6-13 never aggregates raw EVOI** — that stays
  P6-14's job, keeping the P6-13/P6-14 boundary clean.

Allocation runs over the **P6-12 admitted set** (eligible, acyclic, concurrency-
limited), so ineligible / paused / archived / **cyclic** campaigns receive nothing.

## Resolved ambiguities (confirmed with reviewer)

- **EIG before P6-14:** consume the cached EIG column now; degrade to uniform until
  P6-14 populates it (no raw-EVOI aggregation here).
- **Portfolio vs campaign budget:** each share is clamped to the campaign's own
  `budget_experiments` when that is > 0 (`0` = unbounded); slots freed by clamping
  become **explicit headroom** (not redistributed).
- **Unused budget (design default):** preserved as explicit `headroom` — budget is
  never force-spent (the `a_max` ceiling + integer floor + clamping naturally leave
  slack).
- **Proportional vs capped (§9):** both — proportional by policy, then the `a_max`
  ceiling and the campaign's own cap. `budget_spec` keys: `total`, `mode`, optional
  `a_max`/`a_min` (defaulting to the M11 policy values).

## Guarantees

- **Deterministic & replay/rebuild-safe.** Pure function of stored state; the M11
  allocator sorts ids and ties break deterministically. Identical allocation across
  two independently-built DBs and after dropping+rebuilding the projection rows from
  the event log (tested).
- **Pure — no mutation.** `allocate_budget` never writes: campaign `budget_experiments`
  and lifecycle state are untouched, and no historical evidence is mutated (tested).
  Enforcement (feeding shares to the scheduler/campaign budget) is a separate future
  seam, not P6-13.
- **Isolation preserved.** Quant-only; no Chrysos coupling; append-only/event-sourced
  state and the Project 07 hand-off boundary untouched.

## Verification

- New `test_portfolio_budget.py` (21): one campaign (uncapped full / default-`a_max`
  headroom); equal / priority-proportional / eig-proportional (incl. degrade-to-
  uniform before P6-14); campaign cap clamp → headroom; portfolio `a_max` ceiling;
  zero / no-`budget_spec` / insufficient budget; ineligible+lifecycle → zero; cyclic →
  zero; zero-value campaign; multiple portfolios independent; paused portfolio;
  determinism, replay determinism, rebuild equivalence, purity; legacy priority.
- Full suite: **1364 passed, 1 skipped** (+21). AST/boundary/import-closure guards:
  **68 passed**. No frozen module changed; CampaignManager/ResearchScheduler/
  FactoryRunner untouched; no Chrysos coupling.
