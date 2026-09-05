# M11 — Implementation Status (PR-1 … PR-7)

Living tracker for the Milestone 11 "Research Intelligence" build-out. It
summarises each PR's responsibility, its interfaces (tables, engines, policy
versions), and completion state. The **architecture** is frozen by
`M11_RESEARCH_INTELLIGENCE_DESIGN.md` (M11-0) and the **methodology** by
`M11_STATISTICAL_METHODOLOGY.md`; this file tracks what has been *implemented*
against that contract.

_Last updated: 2026-09-06 — after PR-7 opened for review._

## Status at a glance

| PR | Title | State | Policy version | New storage | On main |
| --- | --- | --- | --- | --- | --- |
| PR-1 | Evidence Capture & Provenance | ✅ Merged | — | `evidence_event` | yes (#34) |
| PR-2 | Bayesian Posterior Updating | ✅ Merged | `stat_v1` | `hypothesis_state`, `context_cell_posterior` | yes (#35) |
| PR-3 | Promotion Engine | ✅ Merged | `promotion_v1` | `promotion_recommendation` | yes (#36) |
| PR-4 | Holdout Validation | ✅ Merged | `holdout_v1` | `holdout_evaluation` | yes (#37) |
| PR-5 | Multiple-Testing (FDR) | ✅ Merged | `fdr_v1` | `fdr_evaluation` | yes (#38) |
| PR-6 | Retirement Engine | ✅ Merged | `retirement_v1` | `retirement_evaluation` | yes (#39) |
| PR-7 | Evidence Budget | 🔷 Open for review | `budget_v1` | `budget_allocation` | PR open |

> Note: the PR numbering here follows this implementation sequence
> (PR-1…PR-7 as requested by the reviewer). It does not map one-to-one onto the
> design doc's illustrative §10 breakdown (M11-1…M11-7), which groups the work
> differently (e.g. it pairs promotion + retirement). The responsibilities below
> are the authoritative per-PR scope for this build.

---

## PR-1 — Evidence Capture & Provenance ✅

- **Responsibility:** capture one immutable, fully-provenanced `evidence_event`
  per (experiment × evidence source) from a finished experiment. Records evidence;
  decides nothing.
- **Interfaces:** table `evidence_event` (append-only truth log, natural key
  `(experiment_id, evidence_source)`); `agents/storage/evidence_store.py`
  (`record_evidence` + readers); `agents/research_intelligence/evidence_recorder.py`.
- **Consumed by:** PR-2 (posteriors), PR-3 (replica/flag provenance), PR-4
  (IS/OOS split).
- **State:** merged; additive, idempotent, event-sourced.

## PR-2 — Bayesian Posterior Updating ✅

- **Responsibility:** fold the evidence log into per-hypothesis posteriors and the
  four separated axes (Q/R/G/V), with credible intervals. Measurement only.
- **Interfaces:** `statistics.py` (`stat_v1`: Lo se, deflation, decay,
  Normal–Normal conjugate posterior, DerSimonian–Laird pooling, credible
  intervals, four axes); `evidence_projector.py` (`EvidenceProjector`, and the
  shared `rows_to_evidence()` helper); tables `hypothesis_state`,
  `context_cell_posterior`.
- **Consumed by:** PR-3 (posterior + axes), PR-4 (reuses `assess_hypothesis`,
  `rows_to_evidence`).
- **State:** merged. Runtime dep: **scipy** (declared in `requirements.txt`).

## PR-3 — Promotion Engine ✅

- **Responsibility:** deterministic lifecycle **recommendation** per hypothesis —
  Candidate → Promising → Validated → Production Candidate (Archived modelled, never
  auto-derived). AND-of-per-axis gates (never a weighted sum); recommendation only,
  nothing auto-promoted.
- **Interfaces:** `promotion.py` (`promotion_v1` policy + `recommend`);
  `promotion_engine.py` (`PromotionEngine`); table `promotion_recommendation`.
- **Consumes:** PR-2 `hypothesis_state` (verbatim) + PR-1 provenance (replica
  count, robustness flags); **PR-4 `holdout_evaluation`** and **PR-5
  `fdr_evaluation`** (both read-only).
- **Gate inputs now complete:** Validated requires §7.1 Bayesian-FDR admission;
  Production Candidate requires holdout pass (§5) + `q ≤ 0.05` (§7.2). With every
  engine run, Production Candidate is reachable (PR-5).
- **State:** merged (gate wiring extended by PR-4 and PR-5 as required by §5/§7).

## PR-4 — Holdout Validation ✅

- **Responsibility:** methodology §5. Deterministic calendar partition of a
  hypothesis's evidence into IS/OOS, two separate `stat_v1` posteriors, and the
  four §5.2 gate conditions (sign / OOS-exceedance / retention / overlap) with the
  recorded haircut. Computes holdout evidence; the Promotion Engine consumes it and
  never computes it.
- **Interfaces:** `holdout.py` (`holdout_v1` policy, `partition_is_oos`,
  `evaluate_holdout`); `holdout_engine.py` (`HoldoutEngine`); table
  `holdout_evaluation`; `holdout_store.py`.
- **Consumes:** PR-1 `evidence_event`; reuses PR-2 `assess_hypothesis` /
  `rows_to_evidence`.
- **Consumed by:** PR-3 `PromotionEngine` (via `holdout_store`).
- **Key constant:** Δ_max = 0.5 (= S★), a `HoldoutPolicy` knob (not enumerated in
  §10).
- **State:** merged (#37). Additive, deterministic, replay-safe, separate from
  Promotion.

## PR-5 — Multiple-Testing / False-Discovery Control 🔷

- **Responsibility:** methodology §7. §7.1 Bayesian FDR admission set D (from the
  stat_v1 lfdr) as primary; §7.2 Benjamini–Hochberg `q_h` (one-sided Stouffer-
  combined frequentist p-values) as the cross-check, over the whole active
  population. Supplies both promotion inputs: §7.1 admission gates Validated+, and
  `q_h ≤ 0.05` gates Production Candidate.
- **Interfaces:** `fdr.py` (`fdr_v1` policy: `bayesian_fdr_admit`,
  `hypothesis_pvalue`, `benjamini_hochberg`); `fdr_engine.py` (`FdrEngine`,
  population-level); table `fdr_evaluation`; `fdr_store.py`.
- **Consumes:** PR-2 `hypothesis_state.lfdr`; PR-1 `evidence_event` (reuses
  `_measure` / `rows_to_evidence`). **Module, not an agent.**
- **Consumed by:** `PromotionEngine` (via `fdr_store`): `bayes_fdr_admitted` +
  `q_value`.
- **Milestone:** Production Candidate becomes reachable for the first time (all
  gate inputs now exist). Full assess flow: EvidenceProjector → HoldoutEngine →
  FdrEngine → PromotionEngine.
- **State:** merged (#38). Additive, deterministic, replay-safe, no statistical
  leakage (development-source only).

## PR-6 — Retirement Engine ✅ (#39)

- **Responsibility:** methodology §3.2. First-class retirement track as a stateless
  fold of the current posterior. PR-6 fires **Retired-Refuted** only
  (`π ≤ ε_ref 0.05` **and** `CI_high < S★ 0.5`); Retired-Decayed (needs
  platform-wide decay), Retired-Saturated (needs EVOI/§4), and Retired-Redundant
  (needs a novelty subsystem) are **modelled but deferred**, each reported with its
  reason. Reopen-on-new-evidence is automatic (stateless recompute).
- **Interfaces:** `retirement.py` (`retirement_v1` policy, `evaluate_retirement`);
  `retirement_engine.py` (`RetirementEngine`); table `retirement_evaluation`;
  `retirement_store.py`.
- **Consumes:** PR-2 `hypothesis_state` (π_h, CI_high) — verbatim, nothing
  recomputed. **Module, not an agent.** Imports no other engine and no execution
  module; the two lifecycle tracks compose downstream.
- **Deferred to PR-7:** budget-freeze on retirement (§4).
- **State:** open for review (this PR). Additive, deterministic, replay-safe,
  append-only evidence, separate from Promotion.

## PR-7 — Evidence Budget 🔷

- **Responsibility:** methodology §4 — EVOI-proportional evidence budget with the
  hard per-hypothesis ceiling `a_max` (0.25, anti-monopoly), exploration floor
  `a_min`, retired ⇒ 0. A **pure module, not an agent**.
- **Interfaces:** `budget.py` (`budget_v1` policy: `evoi`, `allocate`,
  `budget_admission`); `budget_engine.py` (`BudgetEngine`, population-level); table
  `budget_allocation`; `budget_store.py` (+ `budget_map`).
- **Consumes:** PR-2 `hypothesis_state` (μ, σ; π^prom derived) + PR-6
  `retirement_evaluation` (retired ⇒ 0) + development evidence (sē² via `_measure`).
  Nothing recomputed.
- **Consumed by:** the existing ExplorationPlanner / `research_quota` via their
  **existing** `accept` seam (`budget_admission` adapter) — **no M10 agent edited**
  (scope: the design's M11-3b module; M11-4 agent-wiring deferred).
- **Notes:** `a_min` default 0.01 (§10 "config"); "renormalised" realized as
  down-normalise-only with exploration headroom (documented interpretation).
- **State:** open for review (this PR). Additive, deterministic, replay-safe,
  append-only evidence, no agent changes.

## Decision consumption (M11-4) ⬜ (planned, later)

- Wire Strategist predicates + Prioritizer `ScoreBreakdown` (Q/R/G/V) +
  Scheduler/Quota to read the axis vector + stage + budget, proving the old
  heuristic path is recovered when evidence is absent. Deferred — it edits M10
  agents, out of scope for PR-7's "no M10 changes".

---

## Cross-cutting invariants (hold across all PRs)

- No changes to M7 execution, M9 learning, the M10 research loop, the Bar Engine,
  the human-approval gate, or deployment.
- Storage evolves additively; every projection is a rebuildable pure fold of the
  append-only logs (bit-identical rebuild).
- Every computed quantity carries a `method` version tag; no RNG, no wall-clock in
  any decision path.
- Engines communicate only through storage projections (no engine-to-engine
  coupling); execution internals are never imported by M11.
