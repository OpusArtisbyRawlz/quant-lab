# M11 PR-5 — Multiple-Testing / False-Discovery-Rate Control (fdr_v1)

The fifth implementation slice of the frozen **M11 Research Intelligence** design.
It implements methodology **§7 (multiple-testing correction)** — deterministic
false-discovery control over the whole active population of hypotheses.

**It is a module/engine, not a new agent** (like the Bayesian Posterior, Holdout,
and Promotion engines), and it is **decision-free**: it computes the FDR
projection; the Promotion Engine *consumes* it (Bayesian admission gates
Validated+, BH `q ≤ 0.05` gates Production Candidate) and never computes FDR.

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §7 (+ §3.1, §10) and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/fdr.py` | new | Pure `fdr_v1` policy: `FdrPolicy`, §7.1 `bayesian_fdr_admit`, §7.2 `hypothesis_pvalue` (weighted Stouffer) + `benjamini_hochberg` (BH/BY). No DB, no RNG. |
| `agents/research_intelligence/fdr_engine.py` | new | Population-level pure fold: read all lfdr (PR-2) + development evidence (PR-1) → admission set D + BH q-values → `fdr_evaluation`. |
| `agents/storage/fdr_store.py` | new | Storage for the `fdr_evaluation` projection. |
| `agents/storage/db.py` | modified | New `fdr_evaluation` table; `SCHEMA_VERSION` 16 → 17; indexes. Additive only. |
| `agents/research_intelligence/promotion.py` | modified | Consume `bayes_fdr_admitted` (§7.1 gate on Validated) and `q_value` (§7.2 gate on ProdC); refresh unavailable messages. |
| `agents/research_intelligence/promotion_engine.py` | modified | Read `fdr_evaluation` (read-only) and thread admission + q-value into `PromotionInputs`. |
| `agents/research_intelligence/__init__.py` | modified | Export `FdrEngine` and the `fdr` module. |
| `agents/tests/test_fdr_policy.py` | new | 15 pure-policy tests. |
| `agents/tests/test_fdr_engine.py` | new | 12 population/consumption tests. |
| `agents/tests/test_promotion_{policy,engine}.py` | modified | Reflect the §7.1 Validated gate + full engine flow (2 new pure gate tests). |
| `docs/M11_PR5_FDR.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10, the Bar Engine, approval, or deployment. No existing
rows mutated. No migration beyond the additive table.

## §7.1 — Bayesian FDR (primary)

Each hypothesis carries `lfdr_h = Pr(θ_h ≤ S0) = 1 − π_h`, already produced by the
stat_v1 posterior (PR-2 `hypothesis_state.lfdr`) — **not recomputed**. The
population is ranked ascending by lfdr and the **largest set D** whose average lfdr
≤ α (0.10) is admitted. Because the list is sorted ascending, the running average
is non-decreasing, so D is a prefix (deterministic, ties broken by hypothesis_id).
**Only hypotheses in D are eligible for Validated+ promotion.**

## §7.2 — Benjamini–Hochberg (frequentist cross-check)

A one-sided per-hypothesis p-value `p_h` is formed from per-cell frequentist
statistics combined by **weighted Stouffer**:

- Per context cell, the decay-weighted inverse-variance combination of the
  **deflated** per-experiment Sharpes gives a frequentist estimate/se **with no
  prior**: `mean_c = Σω_i·Ŝ_i / Σω_i`, `se_c = 1/√(Σω_i)`, `z_c = (mean_c − S0)/se_c`,
  `ω_c = Σω_i` — reusing the exact stat_v1 per-experiment weights `ω_i` (`_measure`).
- `Z_h = Σ_c √ω_c·z_c / √(Σ_c ω_c)`, `p_h = 1 − Φ(Z_h)`.

p-values are BH-adjusted over the whole population: `q_(k) = min_{j≥k} M·p_(j)/j`,
clamped to ≤ 1. **BY** (multiply by `Σ 1/j`) is a `variant` config switch for
high-overlap campaigns. The **Production-Candidate gate requires both** Bayesian
admission (via the Validated ladder) **and** `q_h ≤ 0.05` — belt and suspenders.

The admitting α, population sizes, and variant are snapshotted on every
`fdr_evaluation` row for auditability.

## Output — `fdr_evaluation` (new, additive, rebuildable)

A droppable cache, one row per hypothesis (PK `hypothesis_id`), versioned
`fdr_v1`: `lfdr`, `bayes_admitted`, `bayes_avg_lfdr`, `p_value`, `q_value`,
`bh_admitted`, `population_size`, `bh_population`, `alpha`, `q_max`, `variant`,
`method`, `last_rebuilt_at`.

## Promotion consumption (gate wiring)

The Promotion Engine reads `fdr_evaluation` (read-only) and threads two inputs into
the pure policy: `bayes_fdr_admitted` (§7.1) and `q_value` (§7.2). Absent evaluation
⇒ both `None` ⇒ the dependent gate is *unavailable* (conservative, never
over-promotes) — identical treatment to the holdout input. The standard assess
flow is now **EvidenceProjector → HoldoutEngine → FdrEngine → PromotionEngine**.

With all engines run, **Production Candidate becomes reachable for the first time**
in the M11 build: a strong hypothesis across ≥3 cells, FDR-admitted with `q ≤ 0.05`
and a passing holdout, now clears every gate.

## Architectural properties

- **Module, not an agent** — a population-level pure fold; the research agents
  orchestrate it. No new agent introduced.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`).
- **Deterministic / replay-safe** — all ranks tie-break by hypothesis_id; p-values
  order-independent; population rebuild idempotent and prunes stale rows.
- **Append-only evidence** — `evidence_event` never mutated; the evaluation is a
  rebuildable projection.
- **No statistical leakage** — FDR reads only development-source evidence and the
  development posterior; no holdout/OOS data enters the FDR computation.
- **Boundary-clean** — engines communicate only through storage projections; no
  engine-to-engine imports; no execution internals imported.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Deterministic multiple-testing correction as specified** | §7.1 `bayesian_fdr_admit` (prefix admission), §7.2 Stouffer p + BH/BY q — `test_fdr_policy.py` (15), incl. `test_bh_matches_hand_computed_example`, `test_by_is_more_conservative_than_bh`. |
| **Replay deterministic** | `test_projection_is_replay_deterministic_across_insertion_order`, `test_admission_is_a_prefix_and_deterministic`, `test_pvalue_is_order_independent`, `test_rebuild_is_idempotent`. |
| **Evidence append-only** | `test_evidence_events_are_never_mutated`. |
| **M7 / Bar Engine unchanged** | No `experiment_runner/` or execution files modified. |
| **M9 unchanged** | `test_fdr_does_not_touch_posterior_or_m9`; no `signal_context_*` writes. |
| **M10 unchanged** | No `research_loop`/scheduler changes; no `assess` phase wired. |
| **Promotion/Holdout/Posterior/Evidence APIs** | Only the methodology-required consumption changed: promotion gains the §7.1 admission gate + §7.2 q-gate (both consumed, not computed). Posterior/Holdout/Evidence APIs untouched. |
| **Boundary guards green** | bar-agnostic AST + boundary/executor + import-closure: **66 passed**. |
| **Full regression suite passing** | **1070 passed, 1 skipped** (pre-existing). +29 new tests; prior 1041 still green (2 pre-existing promotion tests updated to run the FdrEngine, per the required §7.1 integration). |

### Statistical / behavioural checks demonstrated

- Strong hypothesis admitted; null (lfdr≈0.5) rejected from D; null p-value ≈ 0.5
  (`test_strong_hypothesis_admitted_null_rejected`).
- α controls admission size; BY ≥ BH conservatism; BH hand-checked example.
- Validated requires FDR admission (`test_validated_requires_fdr_admission`,
  `test_missing_fdr_admission_makes_validated_unavailable`,
  `test_not_fdr_admitted_blocks_validated`).
- A fully-qualified hypothesis reaches **Production Candidate**
  (`test_fully_qualified_hypothesis_reaches_production_candidate`).
- Empty-DB deterministic rebuild; stale-row pruning on population change.

## Critical self-review (findings addressed)

- **Statistical leakage** — FDR consumes only development-source evidence + the
  development posterior; holdout/OOS never enters (verified by source + the
  development-sources guard). Frequentist p reuses the same deflated/decayed
  per-experiment weights as the posterior (no divergent estimator).
- **Replay** — every ordering tie-broken by hypothesis_id; p is order-independent;
  rebuild idempotent + prunes departed hypotheses.
- **Coupling / hidden state** — the two engines share only the `fdr_evaluation`
  projection; no engine-to-engine import. `fdr.py` reuses `statistics._measure`
  (same-package internal; the canonical per-experiment measurement) rather than
  duplicating the deflation/decay math — a conscious low-churn choice.
- **New agents** — none. FdrEngine is a population module; the research agents
  orchestrate it.

## Explicitly NOT in this PR

The retirement track (§3.2), evidence budget/EVOI (§4), the `assess` loop phase +
transition log, hysteretic demotion, live-paper reconciliation, and decision-agent
consumption beyond promotion — all later PRs. **This PR computes FDR only;
promotion consumes it.**
