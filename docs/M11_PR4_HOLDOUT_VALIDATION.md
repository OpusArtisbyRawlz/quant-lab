# M11 PR-4 — Holdout Validation (holdout_v1)

The fourth implementation slice of the frozen **M11 Research Intelligence**
design. It implements methodology **§5 (holdout methodology)**: a deterministic
out-of-sample validation that a hypothesis must pass to be eligible for Production
Candidate.

**It is a pure read / process / project layer, fully separate from the Promotion
Engine.** The **Holdout Engine computes** holdout evidence; the **Promotion Engine
consumes** it and never computes it. Holdout recomputes no development statistics
beyond running the existing `stat_v1` engine on the two calendar windows, mutates
no evidence, and makes no promotion decision.

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §5 and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` §§2, 6.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/holdout.py` | new | Pure `holdout_v1` policy: `HoldoutPolicy` (every §5 constant), the §5.1 calendar partition `partition_is_oos`, and the §5.2 gate `evaluate_holdout`. No DB, no RNG, no wall-clock. |
| `agents/research_intelligence/holdout_engine.py` | new | Pure fold: read the evidence log → calendar-split → two `stat_v1` posteriors → evaluate the gate → write `holdout_evaluation`. |
| `agents/storage/holdout_store.py` | new | Storage for the `holdout_evaluation` projection (upsert / read / list / delete). |
| `agents/storage/db.py` | modified | New `holdout_evaluation` table; `SCHEMA_VERSION` 15 → 16; index. Additive only. |
| `agents/research_intelligence/evidence_projector.py` | modified | Extract the row→evidence conversion into a shared module-level `rows_to_evidence()` (behaviour-preserving) so HoldoutEngine reuses the exact same mapping — single source of truth, no drift. |
| `agents/research_intelligence/promotion_engine.py` | modified | **Consume** `holdout_evaluation` (read-only): thread `holdout_pass` into `PromotionInputs`. Absent evaluation ⇒ unavailable, exactly as before PR-4. |
| `agents/research_intelligence/__init__.py` | modified | Export `HoldoutEngine` and the `holdout` module. |
| `agents/tests/test_holdout_policy.py` | new | 14 pure-policy tests. |
| `agents/tests/test_holdout_engine.py` | new | 16 DB-projection + consumption-seam tests. |
| `docs/M11_PR4_HOLDOUT_VALIDATION.md` | new | This document. |
| `docs/M11_IMPLEMENTATION_STATUS.md` | new | PR-1…PR-7 status tracker. |

No changes to M7, M9, M10, the Bar Engine, the human approval gate, or deployment
logic. No existing rows are mutated. No migration beyond the additive table.

## §5.1 — deterministic calendar partition

Per **(market, universe)**, the observed span of a hypothesis's development
evidence is split once by calendar boundary: the earliest ⌊(1−π)·span⌋ days are
**in-sample (IS)**, the most-recent π (default 0.30) is **out-of-sample (OOS)**.
Classification is by an experiment's own window:

- `date_end ≤ boundary` → IS
- `date_start > boundary` → OOS
- straddles the boundary, or missing dates → **IS**

A straddling experiment used pre-boundary data, so it is never counted as a clean
OOS test — the OOS posterior contains only experiments fully inside the holdout
window (leakage-safe). The split is a pure, deterministic, insertion-order-
independent function of the immutable log; M11 **re-runs nothing**, it only tags by
date.

**Boundary grain (documented deviation-of-convenience).** §5.1 says "per (market,
universe)". The engine computes the boundary per **(hypothesis, market, universe)**
— from that hypothesis's own evidence timeline in each cell — so `rebuild_hypothesis`
is self-contained and no hypothesis's split depends on another's experiments (no
hidden cross-hypothesis coupling). Still fully deterministic; a global
per-(market,universe) boundary would couple unrelated hypotheses' rebuilds.

## §5.2 — two posteriors, compared

Two **separate** `stat_v1` posteriors are computed by reusing
`statistics.assess_hypothesis` on the IS and OOS evidence sets respectively — **no
new estimator, no new math**. Because the two sets are disjoint, the posteriors are
independent, so the difference θ_IS − θ_OOS ~ N(μ_IS − μ_OOS, σ_IS² + σ_OOS²). The
holdout **passes** iff all four conditions hold (closed-form, deterministic):

| # | Condition | Meaning |
| --- | --- | --- |
| (a) | `sign(μ_OOS) = sign(μ_IS)` (both ≠ 0) | the edge survives OOS |
| (b) | `Pr(θ_OOS > S0) ≥ 0.90` | OOS effect is real |
| (c) | `μ_OOS/μ_IS ≥ r_min (0.50)` | not too much decay |
| (d) | `Pr(θ_IS − θ_OOS > Δ_max) ≤ 0.10` | no overfit blow-off |

The realised **haircut** `μ_IS/μ_OOS` is recorded. Large IS→OOS decay (the overfit
signature) trips (c)/(d) even when the OOS effect is still positive.

Each window's posterior is estimated **independently, with its own decay clock**
(the natural reading of §5.2 "maintain separate posteriors"), rather than one
platform-wide clock that would down-weight the older IS window relative to OOS.

**Constants.** §10 pins π = 0.30, r_min = 0.50, S0 = 0.0; §5.2 pins OOS-exceedance
≥ 0.90 and overlap-prob ≤ 0.10. **Δ_max is not enumerated in §10** — it is a
`HoldoutPolicy` knob (default **0.5 = S★**, confirmed with the reviewer) per the §9
discipline that policy objects hold every constant.

## Output — `holdout_evaluation` (new, additive, rebuildable)

A droppable cache, one row per hypothesis (PK `hypothesis_id`), versioned
`holdout_v1`, re-derivable from the immutable log at any time. Columns: IS/OOS
posteriors (`is_mean/sd/n`, `oos_mean/sd/n`), `oos_exceed_prob`, `retention`,
`overlap_prob`, `haircut`, the four per-condition audit flags
(`cond_sign/exceed/retention/overlap`), `holdout_pass`, the policy constants used
(`holdout_fraction`, `retention_min`, `delta_max`), `method`, `last_rebuilt_at`.

A hypothesis with no usable IS/OOS split (e.g. a single date window) is **not
evaluable** — no row is written, and promotion treats holdout as unavailable.

## Boundary: Holdout separate from Promotion

- **HoldoutEngine** depends only on the evidence log + `stat_v1`; it does **not**
  read `hypothesis_state` or promotion state, and computes holdout for every
  hypothesis that has an IS/OOS split (no dependency on promotion eligibility → no
  backwards coupling).
- **PromotionEngine** consumes the result **only through the `holdout_evaluation`
  storage projection** (`holdout_store.get_holdout`) — it does not import
  HoldoutEngine and never computes holdout. Absent evaluation ⇒ `holdout_pass=None`
  (unavailable), identical to pre-PR-4 behaviour.
- The two engines communicate solely through a storage projection — the same
  immutable-log + rebuildable-projection template as every other M11 slice.

Production Candidate still requires the §7.2 BH-FDR `q_h ≤ 0.05`, which is a later
PR, so a passing holdout **alone** does not reach Production Candidate — the gate
remains correctly capped.

## Architectural properties

- **Additive only** — one new table + a version bump; `CREATE TABLE IF NOT EXISTS`.
- **Deterministic / replay-safe** — partition, evidence conversion, posteriors, and
  gate are all pure and insertion-order independent (no RNG, no wall-clock).
- **Append-only evidence** — `evidence_event` is never mutated; the evaluation is a
  rebuildable projection.
- **No peeking** — computing the OOS gate never alters the PR-2 development
  posterior (`hypothesis_state` is untouched).
- **Idempotent** — upsert on `hypothesis_id`; re-folding yields identical rows.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Deterministic holdout evaluation** | `test_projection_is_replay_deterministic_across_insertion_order`, `test_partition_is_deterministic`, `test_evaluate_is_a_pure_function`, `test_rebuild_is_idempotent`. |
| **Append-only evidence** | `test_evidence_events_are_never_mutated` (byte-identical `evidence_event` snapshot across two folds). |
| **Replay-safe** | `test_deterministic_rebuild_from_empty_database` (drop projection → rebuild → identical). |
| **Holdout fails a constructed overfit** (§9) | `test_constructed_overfit_fails_holdout`; `test_overfit_fails_on_retention_and_overlap`. A robust, well-evidenced strategy passes: `test_robust_strategy_passes_holdout`. |
| **Holdout Engine separate from Promotion Engine** | HoldoutEngine imports no promotion code; PromotionEngine consumes only via `holdout_store`. `test_promotion_consumes_holdout_evidence`, `test_promotion_without_holdout_marks_it_unavailable`, `test_holdout_pass_alone_does_not_reach_production_candidate`. |
| **No peeking (development posterior intact)** | `test_holdout_does_not_touch_development_posterior`. |
| **M7 / Bar Engine unchanged** | No files under `agents/experiment_runner/` or execution paths modified. |
| **M9 unchanged** | `test_holdout_does_not_touch_m9_signal_cache`; no writes to `signal_context_*`. |
| **M10 unchanged** | No `research_loop`/scheduler/prioritizer changes; no `assess` phase wired. |
| **Boundary guards green** | bar-agnostic AST + boundary/executor + import-closure: **66 passed** (`-k "bar_agnostic or boundary or executor or import_closure"`). |
| **PR-2 behaviour preserved** | The `rows_to_evidence` extraction is behaviour-preserving: `test_evidence_projector.py` + `test_bayesian_statistics.py` (27) still pass. |
| **Full test suite passing** | **1041 passed, 1 skipped** (pre-existing skip). +30 new tests (14 policy + 16 engine); prior 1011 unchanged. |

## Critical review performed (findings addressed)

- **Replay / order-independence** — partition unions per-cell splits then re-sorts
  via `rows_to_evidence`; posteriors are order-independent (PR-2). Verified by the
  insertion-order replay test.
- **Statistical consistency** — OOS exceedance uses the same `Φ((μ−S0)/σ)` as the
  Q axis; the overlap uses the exact independent-normal difference distribution
  (disjoint IS/OOS sets ⇒ independence); retention and haircut match §5.2. A
  genuinely robust strategy can pass and an overfit cannot (both demonstrated).
- **Hidden coupling** — the two engines share only a storage projection; no
  engine-to-engine import; boundary computed per-hypothesis to avoid
  cross-hypothesis rebuild coupling.
- **Complexity** — reused `assess_hypothesis` and `rows_to_evidence` rather than
  reimplementing; the only new math is the closed-form §5.2 gate.

## Explicitly NOT in this PR

BH-FDR (§7.2), the retirement track, evidence budget/EVOI, live-paper source
reconciliation, the `assess` loop phase and transition log, hysteretic demotion,
and any auto-promotion — all later PRs. **This PR computes holdout evidence only;
promotion merely consumes it.**
