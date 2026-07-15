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

---

# Addendum — Prior Specification & Review Clarifications

*Implementation unchanged. Documentation expanded only.* This addendum answers
the pre-merge review questions. It documents behaviour already present in
`agents/research_intelligence/statistics.py` (`StatPolicy`, version `stat_v1`); no
production code was modified.

## 1. Prior specification

The posterior engine uses a single, fixed, skeptical Normal prior on the latent
per-cell effect `θ` (a deflated, per-year Sharpe). All values live on the
immutable `StatPolicy` dataclass (version `stat_v1`):

| Quantity | Symbol | Value | Source |
| --- | --- | --- | --- |
| Prior mean | `μ₀` | `0.0` | `StatPolicy.mu0` |
| Prior standard deviation | `σ₀` | `0.5` | `StatPolicy.sigma0` |
| Prior variance | `σ₀²` | `0.25` | `sigma0 ** 2` |
| Prior precision | `φ₀ = 1/σ₀²` | `4.0` | `StatPolicy.phi0` property |

- **Why this prior.** Centering at `μ₀ = 0` encodes the honest research default
  that a freshly proposed hypothesis has **no edge** until evidence says
  otherwise. `σ₀ = 0.5` places ~95% of prior mass in roughly `[−1, +1]` Sharpe,
  treating |Sharpe| > 1 effects as *a priori* implausible without support — a
  deliberate guard against overfitting and selection-driven optimism in a
  high-multiple-testing research loop.
- **Intentionally skeptical.** Yes. The prior mean sits exactly at the null
  break-even (`S0 = 0`), so the posterior only moves away from "no effect" in
  proportion to the strength and precision of accumulated evidence. Small or
  noisy samples are pulled back toward zero.
- **Fixed for `stat_v1`.** Yes. `μ₀` and `σ₀` are constants on the immutable
  `StatPolicy`; the same prior applies to every hypothesis and every context
  cell. Changing either constant bumps the policy `version`, so historical
  projections remain reproducible under the version that produced them.

## 2. Design rationale — why a fixed skeptical prior first

A single fixed prior is the right **first** implementation because:

- It is **auditable and reproducible** — one documented pair of constants fully
  determines the shrinkage behaviour, so any projection can be rebuilt and
  explained from the log alone.
- It is **conservative by construction** — in a research loop that generates many
  candidate hypotheses, a skeptical prior is the correct default bias: it
  demands evidence before conceding an edge and resists false discoveries.
- It has **no free parameters to fit** — it introduces no data-dependent
  estimation step (and therefore no additional leakage surface) into the very
  first measurement engine.

This is an **implementation decision, not an architectural limitation.** The
architecture (evidence capture → immutable log → pure fold → rebuildable
projections) is deliberately agnostic to *how* the prior is chosen. The fixed
prior is simply the simplest correct model to ship first; richer priors are a
change of the statistical model only.

## 3. Future evolution — replacing the prior without touching the architecture

Because the prior enters **only** the posterior computation, later methodology
versions can replace it while the surrounding architecture stays fixed. Each of
the following is a `stat_vN` change confined to the engine:

- **Hierarchical Bayes** — learn a global hyper-prior over `θ` and let each cell
  shrink toward it (the cell→hypothesis DL pooling is already a hierarchical
  step; a full hierarchical prior generalises it).
- **Empirical Bayes** — estimate `μ₀`/`σ₀` from the pool of past hypotheses'
  effects instead of fixing them.
- **Market-specific priors** — a distinct `(μ₀, σ₀)` per market.
- **Signal-family priors** — priors keyed by feature/signal family (e.g.
  momentum vs. mean-reversion).
- **Regime-aware priors** — priors conditioned on the context cell's `regime`.
- **Cross-market priors** — borrow strength across markets via a shared parent
  distribution.

In every case, **only the statistical model changes.** Evidence capture
(`evidence_event`), the immutable log, the projection tables, and the pure-fold
projector are unchanged; a new engine version simply computes a different
posterior from the same inputs and writes the same projection shape.

## 4. Compatibility — what a future `stat_v2` would NOT require

Replacing the prior in a future `stat_v2` would **not** require:

- **Schema changes** — `hypothesis_state` / `context_cell_posterior` already
  carry a `method` column recording the engine version; no column depends on the
  choice of prior.
- **Evidence re-ingestion** — the prior is applied at *fold* time, not at
  capture time; the immutable `evidence_event` log is untouched and simply
  re-read.
- **M7 changes** — experiment execution is upstream of and independent from the
  measurement engine.
- **M9 changes** — the M11-owned `context_cell_posterior` keeps the M9 learning
  boundary intact regardless of the prior.
- **M10 changes** — the research-loop wiring does not depend on the posterior
  math.
- **Promotion-policy changes** — promotion/retirement are decision layers that
  *read* projections; they are already decoupled from how the posterior is
  computed (and are out of scope until PR-3).

Only the **posterior computation** changes; a rebuild under the new version
re-folds the existing log into updated projections.

## 5. Mathematical summary

For a single context cell, the effect `θ` is updated by Normal-Normal conjugate
updating in **precision** (inverse-variance) form. Symbols:

- `θ` — latent true effect for the cell (deflated per-year Sharpe).
- `μ_prior = μ₀ = 0.0` — prior mean.
- `τ_prior = φ₀ = 1/σ₀² = 4.0` — prior precision.
- For each experiment *i* in the cell:
  - `Sᵢ` — deflated Sharpe (Lo se + K-selection deflation).
  - `seᵢ` — its standard error; `φᵢ = 1/seᵢ²` its raw precision.
  - `dᵢ = 2^{−Δᵢ/H}` — decay weight (event-time; `Δᵢ` = experiments elapsed).
  - `λ` — off-regime discount (`lambda_regime`, `1.0` = off).
  - `ωᵢ = dᵢ · λ · φᵢ` — the **effective evidence precision** contributed by *i*.
- `τ_data = Σᵢ ωᵢ` — total data precision.
- `μ_data = (Σᵢ ωᵢ Sᵢ) / (Σᵢ ωᵢ)` — precision-weighted mean effect.

**Posterior precision**

    τ_post = τ_prior + τ_data = φ₀ + Σᵢ ωᵢ

**Posterior mean**

    μ_post = (τ_prior·μ_prior + Σᵢ ωᵢ·Sᵢ) / τ_post

**Posterior variance / sd**

    σ_post² = 1 / τ_post           σ_post = √(1 / τ_post)

(These are exactly `phi_post = policy.phi0 + Σ ω_i`, `num = φ₀·μ₀ + Σ ωᵢ·Sᵢ`,
`mu = num / phi_post` in `_cell_posterior`. Cells then pool into the hypothesis
via DerSimonian–Laird `τ²`.)

**How repeated independent evidence accumulates.** Each experiment adds its own
`ωᵢ` to the precision sum, so `τ_post` grows monotonically with every additional
piece of evidence. The posterior mean is a precision-weighted average of the
prior and all data, so consistent repeated evidence pulls `μ_post` toward the
true effect and away from the skeptical `μ₀ = 0`.

**How uncertainty decreases.** Since `σ_post² = 1/τ_post` and `τ_post` only
increases as evidence arrives, the posterior variance strictly **shrinks** with
more (or more precise, or more recent) evidence. With one weak experiment,
`τ_data` is small relative to `φ₀ = 4.0`, so the posterior stays close to the
prior and remains wide (high uncertainty); with many consistent experiments,
`τ_data ≫ φ₀` and the posterior becomes both confident and data-dominated. At
`H = ∞` (`ωᵢ = φᵢ`) this reduces to exact un-decayed conjugate pooling.

## 6. Unit-test confirmation

The existing tests already demonstrate each requested property:

| Property | Test(s) |
| --- | --- |
| Convergence toward repeated evidence | `test_posterior_converges_toward_injected_effect`, `test_monotonicity_more_supporting_evidence_raises_pi_and_mu` (`test_bayesian_statistics.py`) |
| One experiment retains high uncertainty | `test_posterior_converges_toward_injected_effect` — the `few` (n=3) case has strictly larger `posterior_sd` than the `many` (n=200) case, i.e. sparse evidence stays wide near the prior |
| Identical evidence is idempotent | `test_rebuild_is_idempotent` (`test_evidence_projector.py`) — re-fold yields byte-identical state and no duplicate cell rows |
| Replay reconstructs identical posterior state | `test_projection_is_replay_deterministic_across_insertion_order` (`test_evidence_projector.py`); `test_assessment_is_order_independent` (`test_bayesian_statistics.py`) |

Full suite at the time of this addendum: **981 passed, 1 skipped** (pre-existing
skip).

---

**Implementation unchanged. Documentation expanded only.**
