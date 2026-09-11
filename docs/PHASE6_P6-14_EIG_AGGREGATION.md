# Phase 6 — P6-14: EIG aggregation (derive + cache)

Implements **P6-14** (corrected sequence: P6-12 = dependency/cycles, P6-13 = budget,
**P6-14 = EIG aggregation**): derive a campaign-level Expected Information Gain by
**aggregating the already-computed M11 `budget_allocation.evoi`** over the campaign's
live hypotheses (design §5), and cache it on the campaign. No new statistic, no M11
methodology change (the M11 tables are *read*, never modified).

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/campaign_manager/manager.py` | modified | `compute_eig` (pure aggregation), `refresh_eig` / `refresh_all_eig` (derive + cache), `_campaign_hypothesis_ids`; EIG-aggregate constants. Reads `evidence_store` + `budget_store`. |
| `agents/storage/campaign_store.py` | modified | `set_expected_information_gain` — cache writer for the P6-8 column. |
| `agents/tests/test_eig_aggregation.py` | new | 17 tests (see Verification). |
| `docs/PHASE6_P6-14_EIG_AGGREGATION.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

**No M11 engine/methodology change. No ResearchScheduler / FactoryRunner change. No
schema change (the `expected_information_gain` column already exists from P6-8).**

## Derivation (reuse existing M11 signals, §5)

```
EIG(campaign) = aggregate over the campaign's LIVE hypotheses of budget_allocation.evoi
```

- **Which hypotheses:** a campaign's hypotheses are those attributed to it in
  `evidence_event` (which carries both `campaign_id` and `hypothesis_id`); the id space
  is the single `hypothesis_node.node_id` shared by `evidence_event`,
  `hypothesis_state`, and `budget_allocation`, so the join is exact.
- **Live only:** a hypothesis contributes only if it has a `budget_allocation` row and
  is not `retired` (retired ⇒ EVOI 0 already; they drop out of the set). An empty live
  set ⇒ EIG `0.0`, so a played-out campaign decays to 0 — exactly §5's behaviour.
- **Aggregate:** `eig_spec.aggregate` ∈ `mean` (default) / `sum` / `max`.
  `promotion_headroom` is named in §5 but never defined, so it is **deferred** — an
  unknown/deferred aggregate falls back to `mean` (no invented statistic).

## Ownership (confirmed with reviewer)

`compute_eig` is a **pure** read; `refresh_eig` writes the cached column through
`campaign_store`, so the **CampaignManager remains the sole writer of
`research_campaign`** — mirroring the existing `refresh_progress` derive-and-cache.
The PortfolioPlanner stays pure and simply **reads** the cached column (P6-13's
`eig_proportional` mode and any eig-weighted scheduling), closing the loop:
`M11 EVOI → refresh_eig → cached EIG → portfolio budget/ordering`.

The cache is re-derivable each planning pass; wiring `refresh_eig` into an actual
run pass (FactoryRunner) is a separate future seam — FactoryRunner is untouched here.

## Guarantees

- **Deterministic & replay-safe.** `compute_eig` sorts hypothesis ids and is a pure
  function of stored state; identical across independently-built DBs, and **stable
  across a projection rebuild** (it derives from `budget_allocation`, not the cached
  row). Tested.
- **Pure compute.** `compute_eig` never writes; only `refresh_eig` caches. No M11
  projection or historical evidence is mutated. Tested.
- **Isolation preserved.** Quant-only; no Chrysos coupling; the Project 07 hand-off
  boundary and append-only/event-sourced state are untouched.

## Verification

- New `test_eig_aggregation.py` (17): mean/sum/max; default mean; unknown aggregate →
  mean; retired excluded; no-budget-row excluded; empty & all-retired → 0; per-campaign
  scoping; unknown campaign raises; `refresh_eig` caches; `refresh_all_eig` sorted;
  stale-cache update; compute purity; deterministic replay; compute stable across
  rebuild; end-to-end feeding P6-13's `eig_proportional` budget.
- Full suite: **1381 passed, 1 skipped** (+17). AST/boundary/import-closure guards:
  **68 passed**. No frozen M11 engine/methodology changed; ResearchScheduler/
  FactoryRunner untouched; no Chrysos coupling.
