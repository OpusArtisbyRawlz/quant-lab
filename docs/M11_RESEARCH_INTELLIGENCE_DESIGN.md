# M11 — Research Intelligence: Architectural Design (No Implementation)

**Status:** design-only. No code in this PR. This document is the design
verification + architecture proposal for M11.

> **ARCHITECTURE FROZEN (M11-0).** The component boundaries, storage tables,
> event/evidence flow, agent-extension seams, and PR breakdown in this document
> are locked. Subsequent M11 work implements against this contract; changes to
> the *architecture* require an explicit design revision. The **quantitative
> methodology** that fills in `statistics.py`, the promotion predicates, and the
> decay/holdout/correction policies is specified separately and normatively in
> [`M11_STATISTICAL_METHODOLOGY.md`](./M11_STATISTICAL_METHODOLOGY.md).

**Thesis.** M10 made the platform *automatically execute experiments*. M11 makes
it *automatically get better at research* — not by changing models or execution,
but by accumulating statistical **evidence** and letting that evidence drive
research **decisions**: which hypotheses to fund, promote, retire, and remember.

**Non-negotiable constraint.** M11 is a pure **read-and-decide** layer bolted on
top of the existing event-sourced substrate. It changes **no** M7 execution, **no**
Bar Engine, **no** human-approval gate, **no** deployment logic. It only *reads*
what experiments already produce and *writes* new append-only evidence + decision
logs that the existing decision agents consume through knobs they already expose.

---

## Part A — Design Verification: existing extension points

This is the "study the codebase first" deliverable. Every M11 capability maps to
a seam that already exists. Nothing below requires touching execution.

### The substrate M11 builds on (verified)

The storage layer (`agents/storage/db.py`, `SCHEMA_VERSION = 12`) is consistently
**event-sourced with rebuildable projections**, and evolves only **additively**
(`_ADDITIVE_COLUMNS` + `apply_additive_migrations`, db.py:487–561 — never drop or
rename). Two patterns already coexist and are exactly the two M11 needs:

- **Append-only truth logs** → droppable projection. Precedents:
  `signal_context_observation` (immutable facts, db.py:219) → `signal_context_performance`
  (rebuildable cache, db.py:240, PK `(feature,market,universe,regime,bar_type,attribution_method)`);
  `campaign_state_events` → `research_campaign.state`; `signal_lifecycle_events`
  (db.py:262, carries `from_state,to_state,reason_code,context_scope,evidence_n`);
  `scheduler_event`; `loop_checkpoint` (append-only, resumable).
- **Deterministic re-derivation.** `context_store.rebuild_context_cache` must
  reproduce identical numbers from observations; regimes are labelled by a
  **versioned** classifier (`regime_label.method`, db.py:277) so they are
  reproducible and re-labelable.

**This is the template for every M11 store:** an immutable evidence-event log +
a rebuildable projection, sole-writer, deterministic ids, versioned method tags.

### Per-component extension-point map

| Component | File | What it does today | M11 hook (no behavioural change to existing path) |
| --- | --- | --- | --- |
| **ResearchStrategist** | `research_strategist/strategist.py` | Evolves the hypothesis tree. Fires operators on a **binary** heuristic: `_confirmed` = `n_experiments >= min_n AND contribution_score > threshold` (:485); `_refuted` mirror (:494); `_generalises` hard-codes `len(markets) >= 2` (:522). | Replace the three predicates `_confirmed`/`_refuted`/`_generalises` with reads of the new **evidence projection**. `StrategistConfig.exploration_fraction` is already an unused hook (:81). |
| **ResearchPrioritizer** | `research_prioritizer/prioritizer.py` | Ranks pending ideas by a **fixed weighted sum** over an explainable `ScoreBreakdown` (:287): `w_eig/w_novelty/w_memory/w_campaign/w_cost`. `_eig = 1/(1+n_prior)` (:318); `_memory_score` is keyword sentiment (:339, flagged "deliberately simple"). | **Most direct target.** Add the **four separated axes** ($Q$ statistical quality, $R$ reproducibility, $G$ generalisation, $V$ economic value) as distinct `ScoreBreakdown` components + weights on `PrioritizerConfig`, plus the evidence-budget cap — never a single "confidence" component. `ScoreBreakdown` is already built for extension and fully explainable. |
| **ResearchScheduler** | `research_scheduler/scheduler.py` | Orders campaigns `(-priority, campaign_id)` (:199); budget gate `remaining_budget` (:283); diversity `max_per_context`. | Weight `campaign_queue` by **aggregate campaign evidence**, not just `goal_spec.priority`. Evidence/stage metadata rides on the `Candidate` already passed to the planner (:369). |
| **ExplorationPlanner** | `research_quota/quota.py` | Pure quota: reserve `ceil(frac*window)` explore slots, fill by value; `accept` budget predicate; `max_per_context`. | Consume the **evidence budget** $b_h$ (EVOI-allocated, hard per-hypothesis ceiling $a_{\max}$) as a per-hypothesis admission cap via the `accept` callback (:119); reserve slots by uncertainty/stage instead of binary explore/exploit. Stays pure. |
| **ResearchLoop** | `research_loop/loop.py` | Six-phase resumable tick `recover→generate→schedule→dispatch→learn→checkpoint` (:135). `_stamp_node_experiment` links experiment→node (:299). | Add a **new deterministic phase `assess`** (or extend `_do_learn`, :314) after `learn`: recompute evidence, run promotion/retirement transitions, write explanations. Bracketed by `loop_checkpoint` like every other phase → resumable. |
| **SignalLibrarian** | `signal_librarian/librarian.py` | Post-Ledger, no-LLM. Classifies regime, appends observations, rebuilds cache, computes `_generalization_class` (:291: universal/market_specific/…), `_lifecycle_state` (:315: observed→candidate→promoted/retired). Docstring: *"Formal statistical confirmation is deferred to M11"* (:28). | The **anchor point.** M11's evidence recompute extends `record_experiment` (:114) / `backfill` (:176); `_write_promotion_memory` (:361) is the robustness-memory write hook. Promotion here is currently cross-context-consistency only — M11 adds the statistical layer the docstring promised. |
| **Context Store** | `storage/context_store.py` | `signal_context_performance` projection: counts, averages, `keep_rate`, `contribution_score`, `min_n_met`. No dispersion/CI/stability. | Add statistical columns (see §Part B) computed in `rebuild_context_cache` (:233) from the **already-retained** per-experiment net metrics in observations. |
| **Lessons Store** | `storage/lessons_store.py` | `lessons_learned`: free-text `finding/implication` + coarse `confidence` enum (high/med/low). | Untouched as-is; M11's **failure taxonomy** is a *structured* sibling (reason codes), not a rewrite of prose lessons. |
| **Hypothesis Tree** | `hypothesis_manager/manager.py`, `storage/hypothesis_store.py` | Append-only nodes/edges; six operators (`OP_REFINE/VARY_BAR/CROSS_MARKET/ADD_FILTER/COMBINE/NEGATE`). **No status/confirmation/stage column on a node.** | Do **not** mutate nodes. Add an append-only `hypothesis_evidence_event` log + a rebuildable `hypothesis_state` projection carrying stage + evidence (mirrors `signal_lifecycle_events`). |
| **Campaign Reporter** | `reporting/` | Renders read-only boards from stored state. | Add M11 read-models: confidence/stage boards, retirement log, generalisation matrix, research-memory Q&A — all pure projections. |

### The three gaps M11 fills (verified absent today)

1. **No statistical evidence.** The system stores counts, averages, a boolean
   `min_n_met`, and a string `confidence` enum — **no** t-stat, CI, effect size,
   dispersion, stability, or reproducibility metric anywhere. Robustness exists
   only as an opaque JSON `robustness_flags` array on `experiments` (db.py:67),
   never parsed into memory. Net/turnover/cost figures live in artifact
   `metrics.json`, **not** in queryable DB columns (`update_metrics` whitelists
   only `{sharpe,mdd,cagr,vol,calmar}`, ledger_store.py:69).
2. **No promotion stage.** A hypothesis node has no lifecycle state; "confirmed"
   is implicit via its linked experiment's keep/reject.
3. **No structured failure reason or research-memory query surface.**

---

## Part B — Proposed M11 Architecture

### 1. Architecture overview

M11 is a **deterministic evidence engine** sitting between "an experiment
finished" and "the decision agents choose what to do next". Data flow:

```
                 (unchanged M7 execution)
ResearchLoop.dispatch ──► RunResult.metrics + CritiqueResult + node link
                                   │
                                   ▼
        ┌──────────────────────────────────────────────┐
        │  M11 EVIDENCE ENGINE  (new: assess phase)      │
        │                                                │
        │  EvidenceRecorder ─► evidence_event (log)      │  append-only truth
        │        │                                       │
        │        ▼                                       │
        │  EvidenceProjector ─► hypothesis_evidence      │  rebuildable cache
        │                       signal_context_perf(+)   │  Bayesian posterior
        │                       generalisation_matrix    │  (θ mean/sd + CI) and
        │                                                │  four separated axes:
        │                                                │  Q quality · R reproduce
        │                                                │  G generalise · V value
        │        │                                       │
        │        ├─► EvidenceBudget ─► budget_alloc       │  EVOI, ceiling a_max
        │        ├─► PromotionEngine ─► stage transitions│  evidence-gated
        │        ├─► RetirementEngine ─► retire + freeze  │  evidence-gated
        │        ├─► FailureClassifier ─► reason codes    │  deterministic taxonomy
        │        └─► ExplanationWriter ─► decision_record │  every decision explained
        └──────────────────────────────────────────────┘
                                   │
        reads (through existing knobs) ▼
   Strategist   Prioritizer   Scheduler   Quota   Reporter
   (_confirmed) (Q/R/G/V)     (campaign)  (budget)(boards)
```

**Core principle: separate _measuring_ evidence from _acting_ on it.**
`EvidenceProjector` only computes numbers. `Promotion/Retirement/Failure` engines
apply **pure, versioned decision policies** to those numbers. The existing agents
merely *read* the projection. This keeps every actor deterministic and testable in
isolation, and makes the whole layer reconstructible from the event log.

### 2. New components

| Component | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/evidence_recorder.py` | writer | On each finished experiment, extract the full metric bundle (net block, robustness_flags, turnover/cost), the critic decision, the regime label, and the hypothesis-node link; append **one immutable `evidence_event`**. Sole writer. |
| `.../evidence_projector.py` | pure projector | Fold the event log into projections: per-hypothesis evidence, extended context performance (statistical columns), generalisation matrix. Must be **replay-deterministic** (identical output from identical log). |
| `.../statistics.py` | pure lib | **Bayesian** estimators: Normal–Normal posterior per cell (skeptical prior), hierarchical cell→hypothesis pooling, closed-form credible intervals, and the **four separated axes** $Q,R,G,V$ (no single confidence). Versioned (`method="stat_v1"`). No RNG, or fixed-seed only. |
| `.../promotion_engine.py` | pure policy | Decide promotion stage transitions as an **AND of per-axis gates** over $(Q,R,G,V,\text{holdout})$ — never a weighted sum. Evidence-gated, hysteretic. Emits transition events + explanation. |
| `.../retirement_engine.py` | pure policy | **First-class retirement track:** enter `Retired-{Refuted,Saturated,Redundant,Decayed}` from any live stage on posterior predicates. Freezes evidence budget, preserves history, reopenable only on genuinely new evidence. |
| `.../evidence_budget.py` | pure policy | Allocate future experiment slots per hypothesis by **expected value of information (EVOI)** with a hard per-hypothesis ceiling $a_{\max}$ and exploration floor; retired ⇒ 0. Feeds the quota/scheduler. Versioned (`budget_v1`). |
| `.../failure_classifier.py` | pure policy | Map a failed/rejected experiment to a **reason code** from a fixed taxonomy using existing signals (robustness_flags, sample size, cost drag, subperiod signs, sensitivity spread). |
| `.../explanation.py` | writer | Render a `decision_record` for every prioritisation/promotion/retirement/rejection: evidence used, confidence, supporting + contradictory experiments. |
| `.../research_memory_query.py` | pure reader | Answer standing questions ("what momentum signals survive?", "which markets transfer?", "what parameter ranges overfit?") purely from projections — no re-running. |

All live under a new package `agents/research_intelligence/` so the boundary is
explicit and importable by decision agents but not by execution agents.

### 3. Which existing agents are extended (and how minimally)

- **SignalLibrarian** — `record_experiment`/`backfill` additionally call
  `EvidenceRecorder.record` and `EvidenceProjector.refresh`. Its existing regime
  classification and observation writes are unchanged.
- **ResearchLoop** — one new phase `assess` between `learn` and `checkpoint`,
  which runs the projector + promotion/retirement/failure engines and writes
  explanations. Checkpointed like every other phase.
- **ResearchStrategist** — `_confirmed`/`_refuted`/`_generalises` read the
  posterior + axis vector instead of the raw `contribution_score` heuristic. Same
  call shape, richer signal. Promotion/retirement stage gates whether a node is
  `_expandable`; retired nodes stop expanding.
- **ResearchPrioritizer** — four **separate** `ScoreBreakdown` components — $Q$,
  $R$, $G$, $V$ — plus the evidence-budget cap; `_eig` becomes EVOI and
  `_memory_score` reads robustness memory. **No single confidence component.**
  Output stays fully explainable (each axis shown separately).
- **ResearchScheduler / ExplorationPlanner** — campaign priority and quota
  reservation become evidence/stage-aware, and the quota's `accept` enforces the
  per-hypothesis **evidence-budget ceiling** $b_h$, via metadata already threaded
  on `Candidate`.
- **Campaign Reporter** — new read-only boards. No decision logic.

No other agent changes. Commander, Critic, Designer, Ledger, Experiment Runner,
Bar Engine, approval queue: **untouched**.

### 4. Database / storage additions (all additive)

New tables, following the established immutable-log + rebuildable-projection
pattern (bump `SCHEMA_VERSION`; add via `_ADDITIVE_COLUMNS` where columns are
added to existing tables):

**Append-only truth logs**
- `evidence_event` — one row per finished experiment contributing evidence:
  `id PK, experiment_id, node_id, feature_scope, market, universe, regime,
  bar_type, gross_sharpe, net_sharpe, net_calmar, turnover_annualized,
  cost_drag_annualized, robustness_flags(JSON), critic_decision, method,
  created_at`. This is the queryable capture the DB lacks today.
- `hypothesis_evidence_event` — stage-relevant transitions:
  `id PK, node_id, from_stage, to_stage, reason_code, evidence_snapshot(JSON),
  method, created_at`. Mirrors `signal_lifecycle_events`.
- `decision_record` — explainability log: `id PK, decision_type
  (prioritise/promote/retire/reject), subject_id, chosen(JSON),
  evidence_used(JSON), confidence, supporting_experiment_ids(JSON),
  contradictory_experiment_ids(JSON), policy_version, created_at`.
- `failure_reason` — `id PK, experiment_id, reason_code, evidence(JSON),
  method, created_at` (structured sibling to prose `lessons_learned`).

**Rebuildable projections** (droppable caches, re-derivable from the logs)
- `hypothesis_state` — PK `node_id`. Stores the **posterior** and the **four
  separated axes** (never a single confidence): `stage` (promotion *or*
  retirement state), `posterior_mean, posterior_sd, ci_low, ci_high`,
  `q_stat_prob (π_h), q_precision`, `r_sign, r_disp, r_replicas, stability`,
  `g_count, g_coverage`, `v_net_sharpe, v_ci_low`, `n_eff, n_supporting,
  n_contradicting`, `evoi, budget_alloc, budget_frozen`, `last_rebuilt_at,
  method`. See `M11_STATISTICAL_METHODOLOGY.md` §§2–4 for each field.
- `signal_context_performance` **extended** (additive columns): posterior
  `mu, sigma, ci_low, ci_high`, `post_exceed_prob`, `t_stat`, `q_value`,
  `stability_score, reproducibility_score`.
- `generalisation_matrix` — per hypothesis × dimension (market/universe/regime/
  bar_type/period): survival counts, for the generalisation score and Reporter.

**Robustness memory** is expressed as scoped `research_memory` rows
(existing table) written by the projector, e.g. `scope_key = feature@low_vol`,
`finding = "survives only in low-volatility regime"`.

### 5. Event flow (deterministic, resumable)

```
loop.run_tick(campaign):
  recover → generate → schedule → dispatch → learn → ASSESS → checkpoint
                                                        │
   ASSESS (new phase, guarded by loop_checkpoint):      │
     1. For each experiment dispatched this tick:        │
          EvidenceRecorder.record(experiment_id)  ──► evidence_event (idempotent on experiment_id)
     2. EvidenceProjector.refresh(affected nodes/contexts) ──► projections (pure fold)
     3. PromotionEngine.evaluate(nodes) ──► hypothesis_evidence_event + decision_record   (AND-of-axes)
     4. RetirementEngine.evaluate(nodes) ──► events + budget_frozen   (Refuted/Saturated/Redundant/Decayed)
     5. EvidenceBudget.allocate(live nodes) ──► budget_alloc (EVOI, ceiling a_max) + decision_record
     6. FailureClassifier.classify(failed/rejected) ──► failure_reason
     7. ExplanationWriter.flush() ──► decision_record
```

Idempotency: every writer keys on natural ids (`experiment_id`, `node_id`,
transition tuple) with `ON CONFLICT DO NOTHING/UPDATE`, so re-running a
half-completed `assess` phase (crash recovery) reproduces identical state — same
guarantee `loop_checkpoint` already gives the other five phases.

### 6. Evidence flow (how a number becomes a decision)

```
per-experiment net metrics + robustness_flags + regime + node link
        │  (immutable)  evidence_event
        ▼
Bayesian posterior per (hypothesis, context)  [statistics.py, method-versioned]
   θ_c ~ N(μ_c, σ_c²) updated per experiment; hierarchical pool → θ_h ~ N(μ_h, σ_h²)
        │  (point estimate μ_h ALWAYS paired with credible interval CI_h)
        ▼
   FOUR SEPARATED AXES (never summed into one score):
        ├─ Q  Statistical Quality  = posterior P(θ_h>break-even) + precision, with CI
        ├─ R  Reproducibility      = independent-trial sign/dispersion agreement + replicas + stability
        ├─ G  Generalisation       = breadth × coverage over markets/universes/regimes/bar_types/periods
        └─ V  Economic Value       = posterior net-Sharpe magnitude after costs/turnover/drawdown, with CI
        ▼
PromotionEngine  — AND of per-axis gates (never a weighted sum)  → promote/demote
RetirementEngine — first-class track: Refuted / Saturated / Redundant / Decayed → retire + freeze budget
EvidenceBudget   — EVOI-proportional allocation with hard per-hypothesis ceiling a_max
        ▼
Strategist / Prioritizer / Scheduler / Quota read the axis vector + stage + budget through existing knobs
        ▼
every transition emits a decision_record (posterior, CI, four axes, EVOI, budget, supporting/contradictory)
```

Learning is **Bayesian posterior updating**: each experiment sharpens θ; decay is
exponential forgetting; retirement is where the posterior concludes an edge is
absent, saturated, redundant, or faded. Full detail: `M11_STATISTICAL_METHODOLOGY.md`.

Lifecycle (evidence-gated, never heuristic) — **two first-class tracks**:
`Candidate → Promising → Validated → Production Candidate → Archived` (promotion)
and, from any live stage, `→ Retired-{Refuted|Saturated|Redundant|Decayed}`
(retirement, terminal, budget frozen, history preserved).
Each edge has an explicit, versioned evidence predicate (e.g. *Validated* requires
confidence ≥ τ_c **and** reproducibility across ≥ k independent experiments **and**
generalisation across ≥ m contexts **and** no unresolved robustness flag). Thresholds
live in one config object shared by promotion and the strategist's `_confirmed`, so
all actors agree on the evidence bar.

### 7. How learning accumulates

- **Monotone, append-only evidence.** Each experiment adds an immutable
  `evidence_event`; projections only ever integrate more evidence, so confidence
  and generalisation scores sharpen over time without rewriting history.
- **Budget follows evidence.** Uncertain-but-promising and conflicting-evidence
  hypotheses attract more of the Prioritizer/Quota budget; saturated, repeatedly
  refuted, or duplicated ones are down-weighted or retired (budget frozen). The
  system literally *reallocates its own attention* as evidence changes.
- **Institutional memory.** After thousands of experiments, `research_memory` +
  `generalisation_matrix` + `hypothesis_state` answer standing questions
  ("what momentum survives?", "which markets transfer?", "what parameter ranges
  overfit?") by **reading projections**, never re-running experiments.
- **Robustness knowledge is reusable.** "Only works in low volatility / only on
  futures / dies on costs / only survives weekly bars" become scoped memory rows
  that the Prioritizer consults before funding a similar idea again.
- **Full replay.** Drop every projection and rebuild from the event logs → bit-
  identical state (the `rebuild_context_cache` discipline, extended).

### 8. Failure modes and mitigations

| Failure mode | Risk | Mitigation |
| --- | --- | --- |
| **Overfitting the evidence layer itself** (promoting on a lucky seed/campaign) | High — this is the whole point of M11 not to do | Promotion requires reproducibility across *independent* experiments + generalisation across contexts, not a single strong result. Directly mirrors the Bar-Engine production-gate lesson (`docs/BAR_ENGINE_PRODUCTION.md`): a single-seed win is noise. |
| **Small samples** | Confidence spuriously high at low n | Confidence is an explicit function of n; `min_n_met` stays a hard gate; low-n ideas route to the *explore* quota, not promotion. |
| **Regime/label drift** | Evidence rebuilt under a new classifier disagrees with old | Every metric carries a `method` version; re-labelling is explicit and re-derivable; projections are always rebuilt as a set. |
| **Duplicate concepts inflating evidence** | Same idea counted twice | Duplication detection (novelty component already exists) feeds retirement/saturation; evidence is keyed by context cell, not by idea text. |
| **Contradictory evidence oscillating a stage** | Stage flapping Candidate↔Promising | Transitions are hysteretic (promote and demote thresholds differ) and logged; demotion is a first-class, explained event. |
| **Assess-phase crash** | Partial evidence written | Idempotent writers keyed on natural ids + `loop_checkpoint` phase guard → safe replay. |
| **Silent metric loss** | Net/robustness live in artifacts, not DB | `EvidenceRecorder` captures them into `evidence_event` at record time from `RunResult.metrics`. |

### 9. Determinism guarantees

- **No LLM, no wall-clock, no RNG** in any decision path. Estimators are
  closed-form or fixed-seed; policies are pure threshold functions.
- **Method versioning** on every computed quantity (`stat_v1`, `promotion_v1`)
  so historical decisions are reproducible and re-decidable.
- **Event-sourced:** truth is the append-only logs; every projection is a pure
  fold and is droppable/rebuildable to bit-identical state.
- **Idempotent writes** keyed on natural ids; replaying a tick changes nothing.
- **Testable in isolation:** `statistics.py`, each engine, and the projector are
  pure functions with synthetic-data unit tests (the M10 testing discipline).
- **Boundary preserved:** M11 imports from stores and `protocol`, never from
  execution internals; execution/Bar-Engine/approval code is unchanged, so their
  determinism proofs (e.g. byte-identical time path) still hold.

### 10. Recommended PR breakdown

Each PR is independently reviewable, additive, deterministic, and stops for
approval — the cadence used through BE-1…BE-4 and production enablement.

- **M11-0 — Design verification (this document).** No code.
- **M11-1 — Evidence capture.** `evidence_event` table + `EvidenceRecorder`;
  wire into `SignalLibrarian.record_experiment`/`backfill`. Proves the full
  metric bundle (net, robustness, cost) is now queryable. No decisions yet;
  existing behaviour unchanged.
- **M11-2 — Bayesian statistics + projection.** `statistics.py` (`stat_v1`):
  Normal–Normal posteriors, hierarchical pooling, credible intervals, the four
  separated axes $Q,R,G,V$; `EvidenceProjector`; extend
  `signal_context_performance` with posterior columns; `hypothesis_state`
  projection. Posterior-convergence + replay-determinism tests.
- **M11-3 — Promotion & retirement engines.** Promotion ladder (AND-of-axes,
  hysteretic) **and first-class retirement track** (Refuted/Saturated/Redundant/
  Decayed) + `hypothesis_evidence_event`; new `assess` loop phase (checkpointed).
  Budget-freeze on retirement; history preserved; reopen-on-new-evidence.
- **M11-3b — Evidence budget.** `evidence_budget.py` (`budget_v1`): EVOI
  allocation with hard ceiling $a_{\max}$; enforced through the quota `accept`
  seam. Tests: ceiling never exceeded, retired ⇒ 0, EVOI ranking.
- **M11-4 — Decision consumption.** Extend Strategist predicates and Prioritizer
  `ScoreBreakdown` (four separate axis components) and Scheduler/Quota to read the
  axis vector + stage + budget. Prove the old heuristic path is recovered when
  evidence is absent (back-compat).
- **M11-5 — Failure taxonomy + robustness memory.** `failure_reason` +
  `FailureClassifier`; scoped `research_memory` writes for robustness facts.
- **M11-6 — Generalisation.** `generalisation_matrix` + breadth scoring feeding
  promotion and prioritisation.
- **M11-7 — Explainability + Reporter.** `decision_record` for every decision;
  `research_memory_query`; new read-only campaign boards.

Dependency order: 1→2→3 are the spine; 4 consumes them; 5/6/7 layer on and can be
reordered. Each ships with synthetic-data unit tests and preserves every M10
boundary.

---

## Appendix — invariants M11 must never violate

1. No changes to M7 execution, the Bar Engine, human approval, or deployment.
2. Executor stays bar-agnostic; the AST guard remains green.
3. Storage evolves additively; existing tables/columns keep their meaning.
4. Every projection is rebuildable from append-only logs to identical state.
5. Every M11 decision is explainable from stored evidence — no opaque scores.
6. `ProposedIdea.scores` stay advisory; evidence gates research *budget*, not the
   approval/validation/execution path.
