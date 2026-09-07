# M11 — Final Integration Audit

**Status:** verification only. No new functionality was added; no code changed
(the audit found no genuine bug requiring a fix). This is the readiness review of
the complete Research Intelligence layer before real research campaigns.

_Audited: 2026-09-07, at `main` = merge of PR #44 (M11-1 … M11-7 all merged).
Baseline: **1204 passed, 1 skipped**; AST/boundary/import-closure guards: 68 passed._

---

## 1. Architecture summary

M11 is a **deterministic, append-only evidence engine** layered on the M7/M9/M10
substrate. It never changes execution: it reads what experiments produce and writes
new append-only evidence + rebuildable projections that decision agents consume.

```
evidence_event (append-only truth)
   │
   ├─ EvidenceProjector ─► hypothesis_state, context_cell_posterior   (stat_v1 posterior + Q/R/G/V)
   ├─ HoldoutEngine     ─► holdout_evaluation                         (holdout_v1, §5)
   ├─ FdrEngine         ─► fdr_evaluation                             (fdr_v1, §7)
   ├─ RetirementEngine  ─► retirement_evaluation                      (retirement_v1, §3.2)
   ├─ PromotionEngine   ─► promotion_recommendation                   (promotion_v1, §3.1; consumes holdout+fdr)
   ├─ BudgetEngine      ─► budget_allocation                          (budget_v1, §4; consumes retirement)
   ├─ GeneralisationProjector ─► generalisation_matrix                (§2.3 breakdown)
   ├─ FailureClassifier ─► failure_reason                             (failure_v1, M11-5)
   └─ ExplanationWriter ─► decision_record                            (M11-7; consumes promotion+retirement+failure)
                                     │
   Strategist (use_evidence) ◄──────┘  research_memory_query (pure read-models / boards)
```

**11 projections, all rebuildable from the one append-only log.** Every computed
quantity carries a `method` version tag; no RNG, no wall-clock in any decision
path. Determinism is by event-time ordering and pure folds.

## 2. Implemented capabilities (verified)

| Stage | Module | Table | Verified |
| --- | --- | --- | --- |
| Evidence capture | `evidence_recorder` / `evidence_store` | `evidence_event` | append-only, idempotent on (experiment_id, evidence_source) |
| Bayesian posterior | `statistics` / `evidence_projector` | `hypothesis_state`, `context_cell_posterior` | Q/R/G/V axes, credible intervals |
| Holdout | `holdout` / `holdout_engine` | `holdout_evaluation` | §5 gate; overfit fails, robust passes |
| FDR | `fdr` / `fdr_engine` | `fdr_evaluation` | §7.1 Bayesian set + §7.2 BH q |
| Retirement | `retirement` / `retirement_engine` | `retirement_evaluation` | §3.2 Refuted; stateless reopen |
| Promotion | `promotion` / `promotion_engine` | `promotion_recommendation` | AND-of-axes; consumes holdout+FDR |
| Evidence budget | `budget` / `budget_engine` | `budget_allocation` | EVOI + hard a_max ceiling; retired ⇒ 0 |
| Decision consumption | `decision` + Strategist | (reads projections) | `use_evidence` flag, back-compatible |
| Failure taxonomy | `failure` / `failure_engine` | `failure_reason` | fixed reason codes |
| Generalisation | `statistics.generalisation_breakdown` / `generalisation_engine` | `generalisation_matrix` | per-dimension survival |
| Explainability | `explanation` / `explanation_engine` | `decision_record` | promote/retire/reject |
| Reporter | `research_memory_query` | (read-models) | boards + standing questions |

**End-to-end lifecycle (verified):** a strong 3-market hypothesis flows to
**Production Candidate** (all gates + holdout + FDR); a sub-break-even hypothesis
is **Retired-Refuted** and its rejected experiments classified; every stage
produces its projection and its `decision_record`.

## 3. Replay & determinism (verified)

- The complete pipeline over the **same evidence in different insertion orders**
  produces **byte-identical** rows across all 9 downstream projections (excluding
  `last_rebuilt_at`/`created_at` surrogates). Verified programmatically.
- Every projection is a **pure fold** of the immutable log; a drop + rebuild
  reproduces identical state (per-engine tests).
- No RNG anywhere; scipy closed-forms are deterministic; decay clock is event-time.

## 4. Cross-module consistency (verified — no diverging definitions)

- `fdr.lfdr == 1 − hypothesis_state.q_stat_prob` ✓
- `promotion_recommendation.confidence_score == hypothesis_state.q_stat_prob` ✓
- `generalisation_matrix.g_count == hypothesis_state.g_count` (single-source
  `generalisation_breakdown`) ✓
- `decision_record(promote).confidence == promotion_recommendation.confidence` ✓
- **Aligned bars agree across policies:** π-confirm/Promising/τ_π = 0.90;
  ε_ref/refute = 0.05; S0 = 0.0 and S★ = 0.5 identical across all policies; α = 0.10.
- **Single-source computations:** `rows_to_evidence` (evidence→ExperimentEvidence),
  `_measure` (per-experiment deflated Sharpe/se/weight), `generalisation_breakdown`
  are each defined once and reused by every consumer — no divergent re-implementation.

## 5. Schema audit

- `SCHEMA_VERSION = 22`; `schema_version` table + `apply_additive_migrations` +
  `_ADDITIVE_COLUMNS` present; every table created via `CREATE TABLE IF NOT EXISTS`
  (safe on legacy DBs). Every M11 table has indexes.
- **Append-only guarantee:** `evidence_event` is written only by
  `INSERT … ON CONFLICT DO NOTHING`; **no `UPDATE`/`DELETE` on `evidence_event`
  anywhere** in the codebase. All other M11 tables are droppable rebuildable caches.
- **Findings (not bugs; noted for cleanup):**
  1. `context_cell_posterior` is **populated but has no downstream consumer** — the
     holdout/FDR/generalisation engines re-fold evidence rather than read it. It is
     a valid detail projection (a future Reporter could surface it) but is currently
     unread.
  2. `hypothesis_state.stage` is **vestigial** — always `'Candidate'` (PR-2 is
     decision-free); the authoritative recommended stage lives in
     `promotion_recommendation`. No consumer reads it as authoritative
     (`stage_board` reads `promotion_recommendation`), so it is harmless but
     misleading.
  3. `budget_allocation` is consumed only by the `budget_admission` adapter (used in
     tests) — no live agent consumes `b_h` yet (Scheduler/Quota wiring deferred).

## 6. Decision audit (traced)

- **Hstar** (strong, 3 markets): holdout pass, FDR-admitted, all axes cleared →
  `promotion_recommendation = Production Candidate`; `decision_record(promote)` with
  36 supporting / 0 contradictory experiment ids, `policy_version = promotion_v1`.
- **Hbad** (net Sharpe < 0): `retirement_evaluation = Retired-Refuted`;
  `decision_record(retire)` with the deciding posterior; 8 `failure_reason` rows
  (`no_edge`) → 8 `decision_record(reject)`; also a `decision_record(promote)` at
  `Candidate` (both lifecycle tracks recorded, composed downstream).
- Explanations are internally consistent with the projections that produced them
  (confidence, reason codes, and policy versions all trace back correctly).

## 7. Architectural audit

- **Boundaries clean:** M11 imports only from `agents/storage` + `agents/protocol`
  and within its own package; **no execution internals, Bar Engine, or M9/M10 agent
  code is imported** by any M11 module. The Strategist (PR-8) is the only M10 agent
  touched — additively, default-off. The `reporting/` agent is untouched.
- **No duplicated computation** — the three shared primitives above are the single
  source of truth; promotion/g-axis/FDR all consume, never recompute, the posterior.
- **Minor duplication (intentional, documented):**
  - The robustness-flag strings (`subperiod_instability`, `parameter_fragility`,
    `cost_fragility`) are **mirrored** in `promotion.py` and `failure.py` (and the
    upstream `experiment_runner/robustness.py`) rather than imported — a deliberate
    choice to keep M11 from importing execution internals. Three copies.
  - Each policy dataclass re-declares shared constants (`S0`, `S_star`). They agree
    today (verified) but there is **no single source**, so a future edit could
    diverge silently.
- **No accidental coupling or boundary violation found.**

## 8. Technical debt / intentionally deferred (isolated & documented)

All deferrals are recorded at the PR where they arose and are cleanly isolated
(nothing half-wired):

| Deferred | Origin | Isolation |
| --- | --- | --- |
| **Assess loop-phase orchestration** — the engines are invoked manually; no `assess` phase in the M10 `ResearchLoop` runs the DAG per tick | all PRs (recommendation-only) | engines are independent; nothing auto-runs them |
| Prioritizer/Scheduler decision consumption + `prioritise` decision records | PR-8 / PR-11 | needs an idea→hypothesis linkage that does not exist |
| Robustness memory into `research_memory` | PR-9 | M9-owned/M10-consumed table; not written |
| Retired-Decayed / Saturated / Redundant | PR-6 | modelled but never fired (Decayed needs platform-wide decay) |
| Hysteretic demotion; persistent `budget_frozen` state | PR-3 / PR-7 | stateless recommendation model; retired ⇒ 0 budget already holds |
| `context_cell_posterior` consumer; `hypothesis_state.stage` cleanup | PR-2 | populated-but-unread / vestigial |

## 9. Performance audit (at thousands of hypotheses)

The layer is correct and deterministic but **not yet optimised for scale**:

1. **Redundant re-folding (top concern).** `EvidenceProjector`, `HoldoutEngine`,
   `FdrEngine`, `BudgetEngine`, and `GeneralisationProjector` each independently
   re-read a hypothesis's evidence and re-run `rows_to_evidence` + `_measure`. The
   same per-experiment measurement is recomputed up to ~5× per full rebuild.
2. **Whole-population recompute per tick.** Every `rebuild_all` recomputes *all*
   hypotheses; there is no incremental/dirty-set path, so cost is O(hypotheses ×
   experiments) per engine per tick regardless of what changed.
3. **N+1 query patterns.** Per-hypothesis `get_*` lookups in loops (promotion reads
   holdout/fdr/retirement per hypothesis; `FailureClassifier` issues one evidence
   query per experiment). Fine for hundreds; chatty at tens of thousands.

None of these are correctness issues; they are throughput considerations for large
campaigns.

## 10. Remaining risks

- **Orchestration is manual.** There is no single entry point that runs the engine
  DAG in dependency order (EvidenceProjector → Holdout/FDR → Retirement → Promotion
  → Budget → Generalisation → Failure → Explanation). A caller that runs them out of
  order, or omits one, gets stale/missing projections. This is the **single biggest
  readiness gap** — not a bug, but an integration requirement.
- Performance items in §9 if first campaigns are large.
- Deferred consumption (Prioritizer/Scheduler, robustness memory) means the budget
  and some memory are computed but not yet acted on by the decision agents.

## 11. Readiness assessment

**Correctness / determinism / append-only integrity: READY.** The statistical
pipeline is internally consistent, byte-for-byte replayable, boundary-clean, and
fully covered (1204 tests). A hypothesis flows end-to-end through every stage with
consistent, explainable decisions.

**Operational readiness for large autonomous campaigns: NEARLY READY**, gated on
(a) a canonical orchestration entry point and (b) the scale considerations in §9.

## 12. Recommendations before the first research campaign

1. **Add a thin orchestration entry point** (a pure function / the deferred `assess`
   loop-phase) that runs the engine DAG in the fixed dependency order and is
   checkpointed like M10's other phases. Small, additive; removes the manual-order
   risk. *(Recommended as the next PR — not part of this audit.)*
2. **Decide the deferred consumption items** for campaign scope: is the evidence
   budget meant to gate the Scheduler/Quota in v1 (needs the idea→hypothesis
   linkage), or is compute-only acceptable initially?
3. **If first campaigns are large**, fold once per tick and share `measured` across
   Holdout/FDR/Budget/Generalisation (a shared per-hypothesis fold cache), and add
   an incremental/dirty-set rebuild path.
4. **Housekeeping (optional, low risk):** either surface `context_cell_posterior`
   via a Reporter board or stop populating it; drop or repurpose the vestigial
   `hypothesis_state.stage`; centralise `S0`/`S★`/`α` in one shared constants
   module referenced by the policy objects.
5. **Keep the quant-lab / chrysos-agent separation** as established in Phase 0 — no
   Chrysos code entered M11 (verified: no Chrysos/PhotonAssay/Slack references).

---

### Audit verdict

M11 is a **correct, deterministic, replayable, append-only** Research Intelligence
layer with clean boundaries and full test coverage. **No bugs were found.** It is
ready for correctness-sensitive use now; before large autonomous campaigns, add the
orchestration entry point (Recommendation 1) and revisit the scale items (§9).
