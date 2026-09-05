# M11 PR-7 — Evidence Budget (budget_v1)

The seventh implementation slice of the frozen **M11 Research Intelligence**
design. It implements methodology **§4 (evidence budget)** — the EVOI-proportional
allocation of future experiment slots with a hard per-hypothesis anti-monopoly
ceiling.

**It is a pure policy/module, not an agent.** The existing ExplorationPlanner /
`research_quota` consume the per-hypothesis budget `b_h` through their **existing**
`accept` seam via a decoupled adapter — **no M10 agent is modified** (scope
confirmed with the reviewer: the design's M11-3b module, not the M11-4 agent
edits).

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §4 (+ §10) and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` (M11-3b).

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/budget.py` | new | Pure `budget_v1` policy: `evoi`, `allocate` (hard ceiling + floor, retired ⇒ 0), and `budget_admission` (the quota `accept` adapter). No DB, no RNG. |
| `agents/research_intelligence/budget_engine.py` | new | Population fold: posterior + retirement → EVOI → allocation → `budget_allocation`. |
| `agents/storage/budget_store.py` | new | Storage for the `budget_allocation` projection (+ `budget_map` for the quota seam). |
| `agents/storage/db.py` | modified | New `budget_allocation` table; `SCHEMA_VERSION` 18 → 19; indexes. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Export `BudgetEngine` and the `budget` module. |
| `agents/tests/test_budget_policy.py` | new | 17 pure-policy tests. |
| `agents/tests/test_budget_engine.py` | new | 14 engine/replay/consumption tests. |
| `docs/M11_PR7_EVIDENCE_BUDGET.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10 (Strategist/Prioritizer/Scheduler/Quota), the Bar Engine,
the executor, approval, or deployment. No existing rows mutated. No migration
beyond the additive table.

## §4.1 — EVOI

For each hypothesis, EVOI proxies how much one more experiment would move a
decision:

    EVOI_h = φ((μ_h − g)/√(σ_h² + sē²)) · σ_h · π_h^prom

- `μ_h`, `σ_h` — consumed verbatim from the PR-2 posterior (`hypothesis_state`).
- `sē²` — mean per-experiment se², the only quantity not stored; derived from the
  **same** development evidence + `_measure` the posterior used (no posterior
  recomputation).
- `g` — the nearest effect-space gate threshold (nearest of {S0, S★} to μ_h).
- `π_h^prom = Pr(θ_h > S★) = Φ((μ_h − S★)/σ_h)`.

EVOI is high for uncertain-but-promising hypotheses on a threshold, near zero for
saturated (tiny σ) or refuted (π→0) ones — the "spend more on promising, less on
saturated" policy §4 demands.

## §4.2 — allocation with a hard ceiling

Over the live set (retired ⇒ 0), shares are EVOI-proportional, then clipped to
`[a_min, a_max]` and converted to integer slots:

    a_h = clip(EVOI_h / Σ EVOI, a_min, a_max) ;  b_h = ⌊a_h · B_window⌋

- **`a_max = 0.25` (§10) is the hard anti-monopoly ceiling** — no hypothesis may
  take more than a quarter of a window, however promising. Guaranteed for every
  hypothesis (tested).
- **`a_min` is the exploration floor.** §10 lists it as "config" (no fixed value);
  the default here is **0.01**, a `BudgetPolicy` knob.
- **"renormalised" — realized as down-normalise only.** The hard ceiling means
  renormalisation can only ever scale shares *down* (scaling up would re-breach
  `a_max`). When the clipped shares already sum to ≤ 1 — e.g. few hypotheses, where
  the ceiling caps total allocation below the window — they are preserved and the
  remainder is left as **exploration headroom**, deliberately *not* inflated up to
  the ceiling. Inflating low-EVOI incumbents to fill the window would contradict
  §4 ("less on saturated", "a_min preserves exploration"); leaving headroom routes
  the spare window to genuinely new/exploratory work. Only when clipped shares
  exceed 1 are they scaled down (staying ≤ a_max). This is a documented
  interpretation of §4.2's `clip(...), renormalised` and is flagged for review.

## §4.3 — consumption through the existing quota seam (no agent changed)

`budget.budget_admission(budget_map, key_fn)` returns an
`accept(candidate) -> bool` gate that enforces `b_h` through the
`ExplorationPlanner.plan(..., accept=…)` callback the quota **already** exposes.
The adapter is fully generic — it imports nothing from `research_quota` and takes a
`key_fn` mapping a candidate to its hypothesis_id — so consumption needs **zero**
edits to the Prioritizer/Scheduler/Quota/Strategist. A hypothesis with `b_h = 0`
(including retired) admits none; unmapped candidates pass. Proven end-to-end
against the real `ExplorationPlanner`
(`test_budget_consumed_through_existing_quota_accept_seam`).

## Output — `budget_allocation` (new, additive, rebuildable)

A droppable cache, one row per hypothesis (PK `hypothesis_id`), versioned
`budget_v1`: `evoi`, `share_raw`, `a_frac`, `b_experiments`, `capped`, `retired`,
the EVOI inputs (`mu`, `sigma`, `mean_se2`, `promise`, `nearest_gate`), and the
allocation snapshot (`window`, `population_size`, `a_max`, `a_min`), plus `method`
/ `last_rebuilt_at`.

## Inputs consumed

Per §4 the allocation reads **posteriors** (μ, σ, derived π^prom, sē²) and the
**retirement** determination (retired ⇒ 0 — the one explicit non-posterior input
§4 uses). Q/R/G/V, holdout, FDR and promotion outputs are available in the
projections but §4's EVOI formula does not weight by them, so — to avoid inventing
usage the frozen spec does not define — the allocator uses posterior + retirement
exactly as specified.

## Architectural properties

- **Module, not an agent** — a population pure fold + a pure adapter; the existing
  agents orchestrate/consume it. No new agent, no new orchestration layer.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`).
- **Deterministic / replay-safe** — sorted iteration throughout; EVOI closed-form;
  rebuild idempotent, order-independent, prunes departed hypotheses.
- **Append-only evidence** — `evidence_event` never mutated; the allocation is a
  rebuildable projection.
- **No recomputation / no leakage** — μ/σ consumed verbatim; only sē² derived from
  the same per-experiment measurements; development-source only.
- **Boundary-clean** — imports no M10 agent, no execution module, no other engine
  beyond its documented inputs; the adapter imports nothing from `research_quota`.
  Executor untouched; AST/boundary guards green.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Deterministic & replayable allocation** | `test_allocation_is_deterministic_and_order_independent`, `test_projection_is_replay_deterministic_across_insertion_order`, `test_rebuild_is_idempotent`, `test_deterministic_rebuild_from_empty_database`. |
| **Anti-monopoly (no disproportionate share)** | `test_a_max_ceiling_never_exceeded_even_for_a_dominant_hypothesis`, `test_a_max_ceiling_never_exceeded_across_population`. |
| **Exploration + exploitation per methodology** | EVOI ranking (`test_saturated_gets_less_than_promising`); a_min floor + exploration headroom (`test_a_min_floor_applied_to_tiny_evoi`, down-normalise test). |
| **Inputs: posterior + retirement** | `test_retired_hypothesis_gets_zero_budget`; EVOI from μ/σ/π^prom/sē². |
| **Append-only / no mutation** | `test_evidence_events_are_never_mutated`; `test_budget_does_not_touch_posterior_retirement_or_promotion`. |
| **No recompute of existing statistics** | posterior consumed verbatim (same test); only sē² derived via shared `_measure`. |
| **M7 / M9 / M10 / Bar Engine / executor unchanged** | No agent/execution files modified; consumption via the existing `accept` seam. |
| **No new agent; existing quota consumes it** | `test_budget_consumed_through_existing_quota_accept_seam` (real `ExplorationPlanner`, adapter enforces `b_h`, quota unmodified). |
| **Boundary / AST guards green** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **Full regression suite passing** | **1125 passed, 1 skipped** (pre-existing). +31 new tests; prior 1094 unchanged. |
| **Reproducible budget decisions** | idempotent + replay + empty-DB rebuild tests above. |

## Critical self-review (findings addressed)

- **Replay** — all iteration sorted; EVOI/allocation closed-form; rebuild
  idempotent, order-independent, prunes departed hypotheses.
- **Evidence mutation** — none; budget writes only its own projection.
- **Hidden coupling** — none; imports only its documented inputs
  (`hypothesis_state`, `retirement`, evidence for sē²); the quota adapter imports
  nothing from `research_quota`.
- **Statistical leakage** — none; posterior consumed verbatim; development-source
  only; no OOS/holdout.
- **Complexity** — the initial water-fill renormalisation over-inflated saturated
  hypotheses with few live hypotheses; replaced with clip + down-normalise +
  exploration headroom (simpler and truer to §4's intent).
- **Reuse** — reuses `_measure` / `rows_to_evidence` / `hypothesis_state_store` /
  `retirement_store` and the quota's existing `accept` seam; no duplicated math,
  no new orchestration.
- **New agents** — none.

## Explicitly NOT in this PR

Decision-consumption edits to Strategist/Prioritizer/Scheduler (M11-4), budget-
freeze wiring into a retirement transition log, EVOI use of holdout/FDR/promotion
beyond the §4 formula, and the `assess` loop phase — all later/​separate work.
**This PR allocates the evidence budget and exposes it for the existing quota
seam; it changes no agent.**
