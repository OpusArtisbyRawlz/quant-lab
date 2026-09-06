# M11 PR-10 — Generalisation Matrix (stat_v1)

The tenth M11 slice — the design's **M11-6 (generalisation)**: the
`generalisation_matrix` projection that persists, per (hypothesis × dimension), the
§2.3 survival breakdown behind the G-axis. It is the **explainable per-dimension
detail** behind the `g_count` / `g_coverage` scalars PR-2 already stores on
`hypothesis_state`.

**It is a pure module/engine, not a new agent** (like the other projectors). It
**duplicates no existing math**: the per-dimension coverage is factored into a
single shared function that both the G-axis and this projection use, so the matrix
aggregates back to the exact scalars promotion already consumes — **no promotion
input changes**.

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §2.3 and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` (M11-6, `generalisation_matrix`).

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/statistics.py` | modified | Extract the per-dimension coverage into a shared pure `generalisation_breakdown` (+ `DimensionCoverage`, `GENERALISATION_DIMENSIONS`); refactor `_generalisation` to use it. **Behaviour-preserving.** |
| `agents/research_intelligence/generalisation_engine.py` | new | Pure fold: evidence → cells → `generalisation_breakdown` → `generalisation_matrix`. |
| `agents/storage/generalisation_store.py` | new | Storage for the `generalisation_matrix` projection. |
| `agents/storage/db.py` | modified | New `generalisation_matrix` table; `SCHEMA_VERSION` 20 → 21; index. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Export `GeneralisationProjector`. |
| `agents/tests/test_generalisation_policy.py` | new | 6 pure-breakdown tests. |
| `agents/tests/test_generalisation_engine.py` | new | 10 engine/replay/boundary tests. |
| `docs/M11_PR10_GENERALISATION.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10, the Bar Engine, the executor, approval, or deployment.
No existing rows mutated. `hypothesis_state` is untouched (read-through only).

## §2.3 — the breakdown (single source of truth)

A cell *passes* when its posterior clears the cell bar (`exceed_prob ≥ τ_π`, 0.90).
For each of the five dimensions — **market, universe, regime, bar_type, period** —
`generalisation_breakdown` counts the distinct *passing* values against the
distinct *available* values:

    coverage_dim = #distinct passing values in dim / #distinct available values in dim

`_generalisation` now derives `G^cnt` (passing-cell count) and `G^cov` (mean of the
five `coverage_dim`) from this same function — so the matrix and the
`hypothesis_state` scalars can never diverge (verified byte-for-byte). Structural
dims come from the cell tuple; the period dim from the distinct date windows of
experiments in passing cells.

## Output — `generalisation_matrix` (new, additive, rebuildable)

A droppable cache, PK `(hypothesis_id, dimension)`, versioned `stat_v1`: `passing`,
`available`, `coverage`, plus the hypothesis-level `g_count` / `g_coverage` echoed
on every dimension row (Reporter convenience + cross-check). All rows for a
hypothesis are replaced atomically on rebuild; hypotheses without development
evidence, and departed hypotheses, are pruned. Example: a hypothesis strong in two
markets but failing a third shows `market: passing=2/3` while `regime: 2/2` — the
pair that "keeps that visible" (§2.3), which robustness memory (later) will phrase.

## Why this does not change promotion / prioritisation behaviour

Promotion (PR-3) already consumes `g_count` / `g_coverage` from `hypothesis_state`.
This PR only **refactors** their computation (behaviour-preserving) and adds a
**detail** projection; the scalars are identical, so no promotion or prioritiser
input changes. The matrix is available for finer prioritisation and the Reporter
(M11-7) to read, additively.

## Architectural properties

- **Module, not an agent** — a per-hypothesis pure fold. No new agent.
- **No math duplication** — the per-dimension coverage lives in one shared function
  reused by the G-axis and this projection.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`);
  the `statistics.py` change is an additive, behaviour-preserving extraction.
- **Deterministic / replay-safe** — pure breakdown; deterministic fold; rebuild
  idempotent + prunes.
- **Append-only evidence** — `evidence_event` never mutated; `hypothesis_state`
  untouched; the matrix is a rebuildable projection.
- **Boundary-clean** — imports only the M11 evidence/statistics primitives; no
  M7/M9/M10/executor code. AST/boundary guards green.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Deterministic breakdown** | `test_generalisation_policy.py` (6): dimensions, coverage semantics, τ_π passing, determinism. |
| **No duplication / single source** | `test_coverage_matches_the_g_axis_scalar`; `test_matrix_aggregates_match_hypothesis_state` (matrix ↔ `hypothesis_state` byte-for-byte). |
| **Deterministic replay** | `test_replay_deterministic_across_insertion_order`, `test_rebuild_is_idempotent`, `test_deterministic_rebuild_from_empty_database`. |
| **Append-only / no mutation** | `test_evidence_events_are_never_mutated`; `test_does_not_touch_hypothesis_state`. |
| **PR-2 behaviour preserved (refactor)** | `test_bayesian_statistics.py` + `test_evidence_projector.py` + `test_promotion_engine.py` pass unchanged (g_count/g_coverage identical ⇒ promotion unchanged). |
| **No new agents; M7/M9/M10/Bar Engine/executor unchanged** | diff limited to the M11 package + the additive table. |
| **AST / boundary guards preserved** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **quant-lab / chrysos separation** | no Chrysos references; no cross-repo dependency. |
| **Full regression suite passing** | **1184 passed, 1 skipped** (pre-existing). +16 new tests; prior 1168 unchanged. |

## Critical self-review (findings addressed)

- **Replay** — pure breakdown; deterministic fold; idempotent rebuild + pruning.
- **Evidence mutation** — none; reads `evidence_event`, writes only the matrix.
- **Hidden coupling** — none; the `statistics.py` extraction is M11-internal and
  behaviour-preserving; no execution/M9/M10 code.
- **Statistical leakage** — development-source only; reuses the stat_v1 τ_π; no OOS.
- **Duplication** — deliberately avoided by factoring the coverage into one shared
  function (the whole point of the refactor).
- **New agents** — none.

## Explicitly NOT in this PR

`decision_record` + `research_memory_query` + Reporter boards (M11-7), robustness
memory into `research_memory` (deferred from PR-9), and any Prioritizer/Scheduler
consumption of the matrix. **This PR persists the generalisation detail only; it
changes no decision.**
