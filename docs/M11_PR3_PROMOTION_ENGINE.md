# M11 PR-3 — Promotion Engine (promotion_v1)

The third implementation slice of the frozen **M11 Research Intelligence** design.
It consumes the PR-1 evidence log and the PR-2 Bayesian posterior and produces a
deterministic **lifecycle recommendation** for every hypothesis.

**It is a pure read / process / project layer.** It recomputes no statistics,
makes no lifecycle transition, promotes nothing, executes nothing. It reads
PR-2's posterior projection (plus cheap provenance from the PR-1 log), applies a
pure versioned policy, and writes one rebuildable recommendation row per
hypothesis.

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §3.1 (promotion predicates) and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` §§2, 6, 10 (M11-3 slice).

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/promotion.py` | new | Pure `promotion_v1` policy: `PromotionPolicy` (every §3.1/§10 gate constant), `PromotionInputs`, and `recommend()` — the AND-of-axes ladder. No DB, no RNG, no wall-clock. |
| `agents/research_intelligence/promotion_engine.py` | new | Pure fold: read PR-2 `hypothesis_state` + PR-1 `evidence_event` provenance → apply the policy → write `promotion_recommendation`. |
| `agents/storage/promotion_store.py` | new | Storage for the `promotion_recommendation` projection (upsert / read / list / delete). |
| `agents/storage/db.py` | modified | New `promotion_recommendation` table; `SCHEMA_VERSION` 14 → 15; indexes. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Exports `PromotionEngine` and the `promotion` module. |
| `agents/tests/test_promotion_policy.py` | new | 15 pure-policy tests. |
| `agents/tests/test_promotion_engine.py` | new | 15 DB-projection tests. |
| `docs/M11_PR3_PROMOTION_ENGINE.md` | new | This document (design + verification report). |

No changes to M7, M9, M10, the Bar Engine, the human approval gate, or deployment
logic. No existing rows are mutated. No migration beyond the additive table.

## Inputs consumed (nothing recomputed)

Per §"do not recompute evidence that already exists":

- **From PR-2 `hypothesis_state`** (verbatim): posterior mean / sd / credible
  interval, `n_eff`, and the four axes — Q (`q_stat_prob` π_h, `q_precision`),
  R (`r_sign`, `r_disp`, `r_replicas`), G (`g_count`, `g_coverage`),
  V (`v_net_sharpe`, `v_ci_low`, `v_ci_high`).
- **From the PR-1 `evidence_event` log** (provenance only — a distinct-count and a
  set-membership check, no statistics): the independent-replica count `m_h`
  (distinct development-source `experiment_id`s with a usable performance metric,
  matching the posterior's `m` exactly) and whether any **unresolved critical
  robustness flag** is present.

## The lifecycle ladder (methodology §3.1)

Promotion is an **AND of per-axis gates**, evaluated independently — there is **no
weighted sum**. The recommended stage is the highest tier reached by walking the
ladder contiguously from Candidate; the walk stops at the first gate that fails.

| Tier | Gate (all conditions AND-ed) |
| --- | --- |
| **Candidate** | base state (no gate) |
| **Promising** | π ≥ 0.90 · prec ≥ 0.30 · μ_net > 0 · n_eff ≥ 2 |
| **Validated** | π ≥ 0.95 · prec ≥ 0.60 · ρ_sign ≥ 0.80 · ρ_disp ≥ 0.60 · m ≥ k_min(3) · G_cnt ≥ 2 · CI_low ≥ 0 · no unresolved critical robustness flag |
| **Production Candidate** | π ≥ 0.975 · **q_h ≤ 0.05** · R_cnt ≥ 0.75 · G_cnt ≥ 3 · G_cov ≥ 0.50 · CI_low ≥ S\*(0.5) · **holdout pass** |
| **Archived** | modelled terminal-success value; **never auto-derived** here |

All thresholds are `PromotionPolicy` constants taken directly from methodology
§3.1/§10 — none invented.

## Two scoping decisions (reviewed and confirmed)

Both were raised before implementation and resolved conservatively; neither
invents a threshold or bypasses a spec-mandated gate.

1. **Cap at Validated.** The Production-Candidate gate mandates a **holdout pass**
   (§5) and a **Benjamini–Hochberg FDR `q_h ≤ 0.05`** (§7.2). Those subsystems are
   later PRs and produce no output yet, so both inputs are **unavailable**. A
   mandatory gate input that is unavailable is treated as **not satisfied** —
   conservative, so it can only ever hold a hypothesis *back*, never over-promote
   it. In practice the engine therefore recommends **at most Validated** until §5
   and §7.2 land. The `recommend()` unit tests prove the ProdC gate logic is
   correct and that supplying the two inputs *does* let a perfect hypothesis reach
   Production Candidate — i.e. only availability caps PR-3, nothing is hard-coded
   shut.

2. **Archived is never auto-derived.** Archived means "reached Production
   Candidate *and accepted/superseded downstream*" — a downstream acceptance
   signal, not a posterior predicate. It is a modelled lifecycle value (it has an
   ordinal) but this pure engine never assigns it.

**Hysteresis** (§3.1's demote-at-τ−0.10 band) is intentionally **not** in PR-3:
it applies to a *maintained* authoritative stage, and this engine holds none — it
computes the upward-gate attainable stage from a posterior snapshot. The
hysteretic transition applier belongs to the loop-integrated `assess` phase, which
is out of scope here (the instruction "do not modify the M10 research loop" is
respected — no loop wiring is added).

**"Critical" robustness flags.** §3.1 requires "no unresolved critical
robustness_flag" but does not enumerate which flags are critical. The default
critical set is the **entire** upstream vocabulary produced by
`agents/experiment_runner/robustness.py` — `subperiod_instability`,
`parameter_fragility`, `cost_fragility` — a documented `PromotionPolicy` knob, not
an invented threshold. The strings are re-declared in `promotion.py` (not imported
from the execution module) to keep the M11 boundary clean (§9: "M11 imports from
stores and protocol, never execution internals").

## Output — `promotion_recommendation` (new, additive, rebuildable)

A droppable cache, one row per hypothesis (PK `hypothesis_id`), versioned
`promotion_v1`, re-derivable from the immutable log at any time. Columns map to
the requested projection fields:

| Requested field | Column(s) |
| --- | --- |
| posterior estimate | `posterior_mean` |
| posterior uncertainty | `posterior_sd`, `ci_low`, `ci_high` |
| confidence score | `confidence_score` (Q-axis exceedance π_h) + `q_precision` |
| reproducibility score | `r_sign`, `r_disp`, `r_replicas`, `replica_count` (reported component-wise per §2 — never collapsed) |
| generalisation score | `g_count`, `g_coverage` (component-wise per §2) |
| economic value score | `v_net_sharpe`, `v_ci_low`, `v_ci_high` |
| overall promotion score | `promotion_tier` — the **ordinal ladder position** (0=Candidate … 3=Production Candidate), NOT a weighted axis sum |
| recommended lifecycle state | `recommended_stage` |
| audit | `gate_detail` (JSON: per-tier pass/fail + failure reasons + unavailable inputs), `has_critical_flag`, `method`, `last_rebuilt_at` |

The four axes remain **separately stored and separately reported**; the only
scalar is `promotion_tier`, which is the AND-gate ladder result, not a collapse of
Q/R/G/V.

## Architectural properties

- **Additive only** — one new table + a version bump; reconciled onto legacy DBs by
  `create_all_tables` (`CREATE TABLE IF NOT EXISTS`).
- **Pure / deterministic** — no RNG, no wall-clock in the policy; the fold reads a
  deterministic, order-independent PR-2 projection and order-independent log
  provenance.
- **Replay-deterministic & idempotent** — the recommendation is a function of the
  immutable log; re-folding yields byte-identical rows (upsert on `hypothesis_id`).
- **Rebuildable** — dropping `promotion_recommendation` and rebuilding reproduces
  identical state.
- **Recommendation-only** — never mutates `hypothesis_state` (its `'Candidate'`
  stays), never changes an authoritative stage, never touches historical evidence.
- **Boundary-clean** — imports only from `agents/storage` and the M11 package;
  nothing from execution internals, the Bar Engine, or the loop.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Replay determinism** | `test_projection_is_replay_deterministic_across_insertion_order` (same evidence, different insertion order ⇒ identical recommendation); `test_recommendation_is_a_pure_function`; `test_rebuild_is_idempotent`. |
| **Event sourcing preserved** | `test_evidence_events_are_never_mutated` (byte-identical `evidence_event` snapshot across two folds); recommendation is a droppable projection re-derived from the log. |
| **Bayesian outputs unchanged** | `test_recommendation_does_not_touch_hypothesis_state` (PR-2's projection, incl. its stage, is untouched); the full PR-2 suite (`test_bayesian_statistics.py`, `test_evidence_projector.py`) still passes unchanged. |
| **M7 unchanged** | No files under `agents/experiment_runner/` or execution paths modified; diff limited to the M11 package + `storage`. |
| **M9 unchanged** | No writes to `signal_context_performance` / `signal_context_observation`; M11 keeps its own `context_cell_posterior` (PR-2) and `promotion_recommendation` (PR-3) tables. |
| **M10 unchanged** | No change to `research_loop` / scheduler / prioritizer; no `assess` phase wired (deferred). |
| **Bar Engine unchanged** | No Bar Engine or `BarResult` code touched. |
| **Boundary guards green** | Bar-agnostic AST guard + boundary/executor tests: **53 passed** (`-k "bar_agnostic or boundary or executor"`). |
| **Full test suite passing** | **1011 passed, 1 skipped** (pre-existing skip). +30 new tests (15 policy + 15 engine); the prior 981 all still green. |

### Determinism / methodology checks demonstrated by tests

- Single weak experiment ⇒ **Candidate** (`test_single_weak_experiment_stays_candidate`,
  `test_weak_hypothesis_is_candidate`).
- Multiple independent positive experiments raise confidence and the tier
  (`test_multiple_independent_positive_experiments_increase_confidence`).
- Contradictory evidence lowers confidence and reproducibility
  (`test_contradictory_evidence_lowers_confidence`).
- Uncertainty shrinks as evidence accumulates
  (`test_uncertainty_shrinks_as_evidence_accumulates`).
- Strong hypothesis is **capped at Validated**; ProdC blocked only by unavailable
  holdout/FDR (`test_strong_hypothesis_capped_at_validated`), and becomes reachable
  once those inputs are supplied (`test_production_candidate_reachable_once_holdout_and_fdr_supplied`).
- AND-of-axes with no compensation
  (`test_single_weak_axis_blocks_promotion_no_compensation`,
  `test_low_confidence_blocks_even_with_strong_value`).
- Unresolved critical robustness flag caps below Validated
  (`test_unresolved_critical_robustness_flag_caps_below_validated`).
- Deterministic rebuild from an empty database
  (`test_deterministic_rebuild_from_empty_database`).
- Evidence events never mutated (`test_evidence_events_are_never_mutated`).
- `promotion_v1` / `stat_v1` versioning respected (`test_versioning_is_respected`).

## Explicitly NOT in this PR

Retirement track (Refuted/Saturated/Redundant/Decayed), evidence budget / EVOI,
Benjamini–Hochberg FDR (§7.2), the holdout partition and gate (§5), the `assess`
loop phase and `hypothesis_evidence_event` transition log, hysteretic demotion,
Archived auto-derivation, and any Strategist/Prioritizer/Scheduler/Quota
consumption — all later PRs. **This PR recommends lifecycle stages only.**
