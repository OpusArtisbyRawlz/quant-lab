# M11 PR-2 — Bayesian Posterior Updating

The second implementation slice of the frozen **M11 Research Intelligence**
design (`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`), implementing the normative
statistical spec (`docs/M11_STATISTICAL_METHODOLOGY.md`, `stat_v1`). It folds the
immutable **evidence log** (PR-1's `evidence_event`) into rebuildable Bayesian
**posterior projections**.

**It is decision-free.** It *measures* — a posterior plus the four separated
evidence axes — and writes `stage='Candidate'`. Promotion, retirement, evidence
budgets, FDR admission, and holdout gating are later PRs that *read* these
projections.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/statistics.py` | new | Pure `stat_v1` engine: likelihood, deflation, decay, conjugate posterior, DL pooling, credible intervals, four axes. No DB, no RNG, no wall-clock. |
| `agents/research_intelligence/evidence_projector.py` | new | Pure fold of `evidence_event` → `hypothesis_state` + `context_cell_posterior`. |
| `agents/storage/hypothesis_state_store.py` | new | Storage for the two projection tables (upsert / replace / read). |
| `agents/storage/db.py` | modified | New `hypothesis_state` + `context_cell_posterior` tables; `SCHEMA_VERSION` 13 → 14; indexes. Additive only. |
| `agents/storage/evidence_store.py` | modified | Adds `distinct_hypothesis_ids` reader (for `rebuild_all`). |
| `agents/research_intelligence/__init__.py` | modified | Exports `EvidenceProjector` and `statistics`. |
| `agents/tests/test_bayesian_statistics.py` | new | 17 pure-engine tests (methodology §§1–2, §9). |
| `agents/tests/test_evidence_projector.py` | new | 10 DB-level projection tests. |
| `docs/M11_PR2_BAYESIAN_POSTERIOR.md` | new | This document. |

No changes to M7, M9, M10, the Bar Engine, the human approval gate, or
deployment logic. No existing rows are mutated. No lifecycle decision is written.

## The measurement engine (`stat_v1`)

A pure function library — deterministic, no randomness, no wall-clock. Normal
distribution primitives (`Φ`, `φ`, `Φ⁻¹`) come from `scipy.stats.norm`
(closed-form, deterministic).

- **§1.1 likelihood** — Sharpe standard error via Lo (2002):
  `se = sqrt((1 + 0.5·S_per²)/T)·sqrt(N)`, with per-period Sharpe `S_per = S/√N`.
- **Deflation** — selection penalty for `K` configurations:
  `S_deflated = S − se·Φ⁻¹(1 − 1/K)` (no penalty at `K=1`).
- **§6 decay** — exponential forgetting `d(Δ) = 2^{−Δ/H}` over **event time**
  (experiments elapsed), `H=200`; `H=∞` ⇒ no decay.
- **§1.3 posterior** — skeptical prior `N(0, 0.5²)`; Normal-Normal conjugate
  update per context cell, then hierarchical cell → hypothesis pooling.
- **§1.4 pooling** — DerSimonian–Laird `τ²` for between-cell heterogeneity
  (single cell ⇒ `τ²=0`).
- **§1.5 credible intervals** — every estimate paired with a `γ`-level interval
  (`z_{0.05}=1.645`), symmetric about the posterior mean.
- **§2 four axes (never collapsed)** — Quality (exceedance `π` + precision),
  Reproducibility (sign / dispersion / replicas / stability), Generalisation
  (count / coverage of passing cells), Value (posterior net-Sharpe + CI).

### Methodology reconciliation (§1.3 ↔ §6)

The spec's decay-weight text left the evidence-weight double-countable. This PR
fixes the canonical form as `ω_i ≡ d(Δ_i)·λ·φ_i` (full evidence weight, where
`φ_i = 1/se_i²`), giving `φ_post = φ0 + Σ ω_i`. At `H=∞` this recovers **exactly**
the un-decayed Normal-Normal conjugate pooling — asserted by
`test_no_decay_limit_equals_plain_conjugate_pooling`.

## Projection tables (new, additive)

Both are **rebuildable caches** — droppable and reconstructible from the evidence
log at any time.

- **`hypothesis_state`** (PK `hypothesis_id`) — one posterior projection per
  hypothesis: `stage` (always `'Candidate'` in this PR), `posterior_mean`/`_sd`,
  `ci_low`/`_high`, `tau2`, `n_eff`, `n_supporting`/`n_contradicting`, the four
  axes (`q_*`, `r_*`, `g_*`, `v_*`), `lfdr`, `method`, `last_rebuilt_at`.
- **`context_cell_posterior`** (PK `hypothesis_id + market + universe + regime +
  bar_type`) — the per-cell posterior that pools into the hypothesis:
  `post_mu`/`post_sigma`, `post_ci_low`/`_high`, `post_exceed_prob`, `n_eff`,
  `m`, `method`, `last_rebuilt_at`.

This PR introduces an **M11-owned** `context_cell_posterior` rather than
extending M9's `signal_context_performance`, so the M9 learning boundary is
untouched (its INSERT-OR-REPLACE roll-up would otherwise clobber added columns).

## The fold (`EvidenceProjector`)

A **pure fold** — the projection is a deterministic function of the immutable
log, so a full rebuild is idempotent and replay-stable.

- Reads a hypothesis's `evidence_event` rows, keeping only **development
  sources** (`in_sample`, `validation`, `embargo`, `walk_forward`).
  **Holdout / live-paper are excluded** so out-of-sample data never leaks into
  development-stage learning (they get their own posteriors in a later PR).
- Orders evidence by `(date_end, date_start, experiment_id)` and assigns the
  decay clock `Δ` from that run-order (most recent `Δ=0`). This makes the
  projection **insertion-order-independent**: the same evidence in any DB
  insertion order yields byte-identical projections.
- Reads metrics from `evidence_event.metrics` JSON with fallbacks: `net_sharpe`
  (else `sharpe`), `T`/`n_periods` (else policy default 252), `N`/
  `periods_per_year` (else 252), `K`/`n_configs` (else 1), `stability`. Rows with
  no usable performance number are skipped.
- Writes `hypothesis_state` (upsert) + `context_cell_posterior` (replace),
  returning `None` when a hypothesis has no usable development evidence.
- `rebuild_all()` folds every hypothesis in the log.

## Architectural properties

- **Additive only** — two new tables + a version bump; new-table creation is
  reconciled onto legacy DBs by `create_all_tables` (`CREATE TABLE IF NOT
  EXISTS`).
- **Pure / deterministic** — no RNG, no wall-clock in the math; the decay clock
  is event-time and insertion-order-independent.
- **Idempotent** — re-folding produces byte-identical state and no duplicate
  cell rows.
- **Rebuildable** — dropping a projection table and re-creating it is safe; the
  fold reconstructs it from the evidence log.
- **Decision-free** — `stage` stays `'Candidate'`; `lfdr` is stored as a
  cross-check only. No promotion/retirement/budget/admission logic exists here.
- **Read-only against M7/M9/M10** — the projector reads `evidence_event` and
  writes only its own projection tables.

## Required proofs → tests

**Pure engine** (`agents/tests/test_bayesian_statistics.py`, 17):
Lo se formula; deflation reduces estimate; decay halves each half-life;
posterior converges toward injected effect; no-decay limit == manual conjugate
pooling; monotonicity (more evidence raises `π` and `μ`); credible-interval
symmetry and width; single-cell `τ²=0`; pooling shrinks between divergent cells;
value-change leaves reproducibility sign untouched (axis independence);
conflicting evidence drops reproducibility sign; generalisation counts passing
cells; negative effect ⇒ low exceedance / high lfdr; order-independence; decay
downweights older evidence; empty evidence raises.

**DB projection** (`agents/tests/test_evidence_projector.py`, 10):
rebuild writes `hypothesis_state`; rebuild writes cell posteriors; stage stays
`'Candidate'` even under overwhelming evidence (decision-free); rebuild is
idempotent (no duplicate cells); projection is replay-deterministic across
insertion order; holdout evidence excluded from the development posterior;
`rebuild_all` covers every hypothesis; hypothesis without usable evidence is
skipped; projection does not touch the M9 signal cache; projection tables exist
and are rebuildable.

Full regression suite: **981 passed, 1 skipped** (pre-existing skip).

## Explicitly NOT in this PR

No promotion or retirement lifecycle, no evidence-budget controls, no
false-discovery-rate admission, no holdout π-gating, no live-paper reconciliation,
and no prioritizer / strategist / scheduler / deployment consumption of these
projections. **This PR measures posteriors only.**
