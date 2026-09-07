# Phase 6 — Research Factory Orchestration (Design)

**Status:** design only. No code in this document. This is the architecture and PR
plan for turning the completed, frozen components into an **autonomous Quant
Research Factory** — by *orchestrating existing intelligence*, not adding new
intelligence.

**Frozen / do-not-touch:** the M11 statistical methodology, the M11 engines, the
Bar Engine, and all Chrysos code. Phase 6 only coordinates what exists.

---

## 0. Guiding principles

1. **Orchestrate, don't invent.** Every capability the factory needs already
   exists as an agent or engine. Phase 6 wires them into a continuous loop.
2. **No new permanent agents.** Orchestration lives inside existing coordinators.
   The only new artifacts are (a) one thin, stateless *driver* and (b) declarative
   *campaign types* + a *source registry* — none of which hold research
   intelligence.
3. **A campaign declares WHAT; the agents decide HOW.** A campaign is a small
   declarative spec (type + goal + scope + stopping rule). The Strategist, Idea
   Generator, Designer, Backtester, M11, and Reporter already decide the how.
4. **Preliminary vs authoritative stays explicit.** M11 produces *preliminary*
   evidence during a campaign; **Project 07 (Statistical Integrity) remains the
   authoritative final evaluator**. Replay/campaign results are provisional until
   Project 07 signs off.
5. **Determinism & append-only preserved.** The factory adds no RNG and no
   evidence mutation; it is a resumable, checkpointed loop over pure components.
6. **Quant stays isolated from Chrysos.** No Chrysos imports, config, memory,
   orchestration, or execution paths — ever.

---

## 1. What already exists (verified against the codebase)

| Concern | Existing component | Reused as-is |
| --- | --- | --- |
| Campaign object + state machine | `research_campaign` table + `CampaignManager` (event-sourced, sole writer; states DRAFT/ACTIVE/STALLED/COMPLETED/ARCHIVED/DISCARDED; `goal_spec`, `scope`, `budget_experiments`, `stall_patience`, `stopping_spec`) | ✅ |
| Per-campaign resumable tick | `ResearchLoop.run_tick` — 6 phases `recover → generate → schedule → dispatch → learn → checkpoint`, each bracketed by `loop_checkpoint` (resume skips completed phases) | ✅ extended |
| Hypothesis frontier expansion | `ResearchStrategist.run_tick` (called by the generate phase) | ✅ |
| Idea generation (LLM) | `IdeaGenerator` / `AnthropicIdeaLLM` (keyless `FakeIdeaLLM` in tests) + human approval gate | ✅ |
| Experiment design | `ExperimentDesigner` | ✅ |
| Execution / backtest | `experiment_runner` (the executor; **Bar-Engine, bar-agnostic — frozen**) | ✅ untouched |
| Signal learning | `SignalLibrarian` (M9, inside the executor path) | ✅ untouched |
| Evidence + evaluation | **M11** — 11 engines + projections (frozen) | ✅ consumed |
| Prioritisation / scheduling | `ResearchPrioritizer`, `ResearchScheduler` (`campaign_queue`, `priority_queue`, `retry_queue`, `experiment_queue`, `remaining_budget`), `ExplorationPlanner` | ✅ |
| Reporting | `reporting/` + M11 `research_memory_query` read-models | ✅ |
| Final statistical authority | **Project 07 — Statistical Integrity** (`research/project_07_statistical_integrity`) | ✅ separate |

**The three gaps Phase 6 closes** (nothing else is missing):

- **G1 — No `assess` phase.** The M11 engine DAG is not run inside the loop (the
  M11 audit's #1 finding). Experiments produce evidence but nothing folds it into
  the M11 projections per tick.
- **G2 — No campaign _type_.** Campaigns carry a free-text `theme`/`goal_spec` but
  no typed *kind* that selects which idea **source** feeds the generate phase.
- **G3 — No continuous multi-campaign driver.** `run_tick` runs one campaign once;
  nothing selects the next runnable campaign and ticks the factory forever.

---

## 2. Overall architecture

```
                         ┌───────────────────────────────────────────────┐
                         │  FactoryRunner  (thin, stateless driver)        │
                         │  loop: pick next runnable campaign → run_tick   │
                         │        → advance campaign state → repeat        │
                         └───────────────┬───────────────────────────────┘
                                         │ selects via
                         ResearchScheduler.campaign_queue()  (deterministic order)
                                         │
        ┌────────────────────────────────▼──────────────────────────────────┐
        │  ResearchLoop.run_tick(campaign_id)   (resumable, checkpointed)     │
        │                                                                    │
        │  recover → GENERATE → schedule → dispatch → learn → ASSESS → report │
        │               │                                        │           │
        │        HypothesisSource                          M11 engine DAG     │
        │      (selected by campaign_type)                (preliminary)       │
        └────────────────────────────────────────────────────────────────────┘
              │                    │                 │              │
       Strategist / Idea    Designer + Executor   M11 projections   Reporter
       sources (paper,      (Bar Engine, M9)      (frozen)          read-models
       github, replay, …)                              │
                                                       ▼
                                     Project 07 — Statistical Integrity
                                     (AUTHORITATIVE final evaluation, separate)
```

**Three additive pieces, zero new agents:**

- **A `assess` (and small `report`) phase** inside the existing `ResearchLoop`.
- **`campaign_type` + a `HypothesisSource` registry** — the generate phase asks the
  registry for the source bound to the campaign's type; the Strategist is the
  default source, so existing behaviour is unchanged.
- **`FactoryRunner`** — a thin coordinator (a module/function, *not* an agent) that
  drives continuous ticks across campaigns. It holds no research logic; it only
  selects → ticks → advances state.

---

## 3. Orchestration flow (one factory iteration)

1. **Select.** `FactoryRunner` asks `ResearchScheduler.campaign_queue()` for the
   next runnable ACTIVE campaign (deterministic order → replayable).
2. **Tick.** `ResearchLoop.run_tick(campaign_id)` runs the resumable phase
   sequence:
   - **recover** — resume any half-finished tick from `loop_checkpoint`.
   - **generate** — resolve the campaign's `HypothesisSource` (by `campaign_type`)
     and expand the frontier into `pending` ideas (human approval gate preserved).
   - **schedule** — `ResearchScheduler` orders the runnable ideas (evidence-aware
     via M11 where wired).
   - **dispatch** — the **unchanged M7 executor** runs approved experiments
     (Bar-Engine, bar-agnostic).
   - **learn** — M9 signal learning (already inside the executor path).
   - **assess** *(new)* — record evidence + run the **M11 engine DAG** in
     dependency order (§7), producing the preliminary projections + decision
     records.
   - **report** *(new, thin)* — refresh the Reporter read-models for the campaign.
   - **checkpoint** — close the tick.
3. **Advance.** `FactoryRunner` asks `CampaignManager` to advance the campaign
   state: STALLED if `stall_patience` ticks made no progress; COMPLETED when the
   `stopping_spec` is met; otherwise stays ACTIVE.
4. **Repeat** with the next campaign. Continuous, bounded by global stop
   conditions (§13).

---

## 4. Campaign lifecycle

Reuses the existing `CampaignManager` state machine — Phase 6 adds only the typed
*kind* and the source binding:

```
DRAFT ──approve/activate──► ACTIVE ──stopping_spec met──► COMPLETED ──► ARCHIVED
   │                          │  ▲                                        
   │                          │  └──progress──┐                            
   └──discard──► DISCARDED    └──no progress ×stall_patience──► STALLED ──resume──► ACTIVE
```

- **Definition (declarative WHAT):** `{campaign_type, goal_spec, scope, stopping_spec,
  budget_experiments, exploration_fraction, stall_patience}`. All already columns on
  `research_campaign`; Phase 6 adds `campaign_type`.
- **Activation** goes through the human approval gate (unchanged).
- **Progress** = new evidence / new promotions this tick (readable from the M11
  projections). Absence for `stall_patience` ticks ⇒ STALLED.
- **Completion** = `stopping_spec` satisfied (§13).
- **Archival** freezes the campaign; all evidence/decision records are preserved
  (append-only).

---

## 5. Experiment lifecycle (unchanged core, M11-terminated)

```
idea (pending) ─approval─► approved ─dispatch─► RunResult (executor, Bar Engine)
      │                                              │
   Designer builds the spec                          ▼
                                        evidence_event (append-only, PR-1)
                                                     │  assess phase
                            M11 DAG ► posterior ► promotion / holdout / fdr /
                                       retirement / budget / generalisation /
                                       failure ► decision_record   (PRELIMINARY)
                                                     │
                                          Project 07 (AUTHORITATIVE, later)
```

The experiment path (design → execute → critique → ledger → M9 learn) is untouched.
Phase 6 only appends the M11 assess step so every finished experiment terminates in
evidence + a preliminary decision, then feeds Project 07 for the final word.

---

## 6. Interaction between existing agents

| Agent | Existing role | Phase-6 responsibility (additive) |
| --- | --- | --- |
| **Research Strategist** | frontier expansion; consumes M11 (PR-8, `use_evidence`) | default `HypothesisSource`; unchanged when evidence absent |
| **Idea Generator** | LLM ideas + approval gate | invoked by sources that produce raw ideas (incl. future paper/GitHub sources) |
| **Research Agent / Designer** | turns an approved idea into an experiment spec | unchanged |
| **Backtester (executor)** | runs the spec (Bar Engine) | **unchanged, frozen** |
| **M11 Research Intelligence** | evidence + evaluation | run by the `assess` phase in dependency order; **frozen** |
| **Reporter** | read-only boards | refreshed by the `report` step; consumes M11 `research_memory_query` |
| **Scheduler / Prioritizer / Quota** | order campaigns/ideas, enforce budget | select the next campaign; evidence-aware where wired |
| **CampaignManager** | campaign state machine | owns `campaign_type` + lifecycle transitions |

No agent is replaced; three gain a small additional responsibility (Strategist as a
source, Loop as assess/report host, CampaignManager as type owner).

---

## 7. The `assess` phase — M11 engine DAG (fills audit G1)

A fixed, checkpointed dependency order (from the M11 audit), run per campaign tick
over the experiments produced this tick (and their hypotheses):

```
EvidenceProjector          (posterior + Q/R/G/V)
   → HoldoutEngine         (§5)
   → FdrEngine             (§7, population)
   → RetirementEngine      (§3.2)
   → PromotionEngine       (consumes holdout + fdr)
   → BudgetEngine          (consumes retirement)
   → GeneralisationProjector
   → FailureClassifier
   → ExplanationWriter     (consumes promotion + retirement + failure)
```

- Each sub-step is an existing engine, invoked, not modified. The phase is bracketed
  by `loop_checkpoint` like every other phase → resumable and idempotent (the
  engines are already idempotent rebuildable folds).
- **Preliminary tag.** The assess phase writes M11 projections that are explicitly
  *preliminary*; the campaign never treats an M11 "Production Candidate" as final —
  that is Project 07's call (§9).
- **Scope.** Per-tick, assess may run `rebuild_all` (simplest, deterministic) or a
  scoped rebuild of the affected hypotheses (a later optimisation — see §14).

---

## 8. Campaign types + `HypothesisSource` (fills audit G2, the plug-in seam)

A **`campaign_type`** column selects a **`HypothesisSource`** — the single interface
future campaigns plug into. A source's only job is to *produce candidate ideas /
hypotheses* for the generate phase; everything downstream is shared.

```
HypothesisSource (protocol):
    propose(campaign) -> list[idea/hypothesis]      # WHAT to try next
```

| campaign_type | Source (who) | Status |
| --- | --- | --- |
| `strategy_evolution` | `ResearchStrategist` (default) | exists today |
| `bar_type_comparison` | bar-type sweep over `scope.bar_types` | thin, near-term |
| `overlay_combination` | overlay-combo enumerator | thin, near-term |
| `counterfactual_replay` | replay of abandoned/prior experiments (§10) | near-term |
| `literature_review` | paper reader → Idea Generator | future adapter |
| `github_mining` | repo miner → Idea Generator | future adapter |

The registry maps `campaign_type → HypothesisSource`. The generate phase does
`source = registry[campaign.campaign_type]; ideas = source.propose(campaign)`.
**Adding a future campaign = registering one source**; the loop, scheduler, M11,
and Reporter are untouched. This is exactly the "campaign declares WHAT; agents
decide HOW" contract.

Future sources that read the outside world (papers, GitHub) are **input adapters**
behind this interface; they feed the *existing* Idea Generator + approval gate — no
new intelligence, no new agent, and no bypass of the human gate.

---

## 9. Project 07 separation (authoritative vs preliminary)

- **M11 (in the factory) = preliminary.** During a campaign, M11 produces the
  posterior/promotion/holdout/FDR evidence continuously. These drive *research
  decisions* (what to fund/expand/retire) but are labelled provisional.
- **Project 07 = authoritative final evaluation.** A campaign's outputs are only
  *confirmed* after Project 07's Statistical Integrity evaluation. Replay campaigns
  may surface promising results before Project 07 runs; those remain preliminary.
- **Explicit boundary.** The factory never imports or embeds Project 07 logic and
  never marks an M11 result "final". The hand-off is a queue: campaign → preliminary
  evidence → Project 07 (separate, on its own cadence) → authoritative verdict. This
  keeps the two evaluation authorities cleanly separated and independently evolvable.

---

## 10. Replay workflow (counterfactual / abandoned strategies)

Replay is just a `HypothesisSource` (`counterfactual_replay`) that proposes
*re-runs* of prior/abandoned experiment specs under new conditions (e.g. new bar
types, regimes, overlays). It reuses the whole pipeline:

```
replay source → (prior spec, new scope) → Designer → executor (Bar Engine)
   → evidence_event (append-only, new experiment_id) → M11 assess (PRELIMINARY)
   → Project 07 (AUTHORITATIVE, later)
```

- Original experiments are never mutated; a replay is a **new** append-only
  experiment. Determinism holds (same inputs ⇒ same evidence).
- Replay evidence is preliminary until Project 07; the design keeps that label on
  the campaign's outputs.

---

## 11. Failure handling

- **Experiment failure** (executor error / rejected result): already handled by the
  critic/ledger; the M11 `FailureClassifier` records a `failure_reason`. The tick
  continues; the idea is not re-queued unless the retry policy says so
  (`ResearchScheduler.retry_queue`).
- **Source failure** (e.g. a future paper/GitHub adapter is unreachable): the
  generate phase yields zero ideas and records the reason; the tick proceeds with
  whatever is already queued. External-source errors never crash the factory.
- **Assess-phase failure** (an engine raises): the phase's checkpoint is not
  completed, so the next tick re-runs it (idempotent). Because engines are pure
  rebuildable folds, a partial assess is safe to repeat.
- **Campaign stall**: `stall_patience` ticks with no progress ⇒ STALLED (not an
  error — a first-class state); the driver moves on and can resume later.

---

## 12. Recovery, persistence, determinism

- **Recovery** is the existing `loop_checkpoint` mechanism, extended to the new
  phases: a crash mid-tick resumes the latest unfinished tick and skips completed
  phases. The added `assess`/`report` phases follow the same contract.
- **Persistence** is entirely in the existing SQLite store: `research_campaign` +
  `campaign_state_events` (campaign lifecycle), `loop_checkpoint` (tick progress),
  `evidence_event` (append-only truth), and the 11 M11 projections (rebuildable).
  The factory adds **no new mutable state** beyond `campaign_type` and (optionally) a
  tiny driver cursor that is itself derivable from the logs.
- **Determinism** is inherited: deterministic campaign selection (scheduler total
  order), deterministic generate (per source), the frozen deterministic executor,
  and the byte-identical M11 folds (audit §3). Same experiments ⇒ same evidence ⇒
  same decisions.

---

## 13. Stopping conditions

Reuse `research_campaign.stopping_spec` (already present). A campaign stops
(→ COMPLETED) when its declarative rule is met; the driver evaluates it from the
projections after each tick. Supported rule shapes (all readable from existing
state, no new computation):

- **Budget** — `budget_spent ≥ budget_experiments` (0 = unbounded).
- **Goal reached** — e.g. "N hypotheses at ≥ Validated" (from
  `promotion_recommendation`) or "coverage ≥ x" (from `generalisation_matrix`).
- **Exhaustion** — the source proposes nothing new for `stall_patience` ticks
  (→ STALLED, then COMPLETED if configured).
- **Global factory stops** — max wall-time / max ticks / operator halt for the
  `FactoryRunner` itself, so continuous mode is bounded and safe.

---

## 14. Scalability & expected bottlenecks

Carried forward from the M11 audit §9 — the factory makes them continuous, so they
matter more:

1. **Redundant per-tick re-folding.** Holdout/FDR/Budget/Generalisation each re-run
   `rows_to_evidence` + `_measure`. Under a continuous loop this repeats every tick.
   *Mitigation (later):* a per-tick shared fold cache, or scoped rebuilds of only the
   hypotheses touched this tick instead of `rebuild_all`.
2. **Whole-population recompute.** `rebuild_all` is O(hypotheses × experiments) per
   engine per tick. *Mitigation:* dirty-set / incremental assess keyed on the tick's
   affected hypotheses.
3. **N+1 store reads** in per-hypothesis loops. *Mitigation:* batch reads.
4. **FDR is intrinsically population-level** — it must see the whole active set;
   keep it a full pass but run it once per tick, not per hypothesis.
5. **External sources (future)** — paper/GitHub adapters add network latency and
   rate limits; isolate them behind the source interface with their own backoff so
   they never block the deterministic core.

None affect correctness; they set the order of the optimisation PRs.

---

## 15. Opportunities for simplification

- **One orchestrator, not many.** Put the assess DAG and continuous driving into the
  *existing* `ResearchLoop` + a thin `FactoryRunner`; do **not** add per-campaign or
  per-engine agents.
- **Assess DAG as data.** Express the M11 engine order as a small ordered list the
  assess phase iterates — one place to read the pipeline, trivial to test.
- **Sources as a registry, not subclasses of agents.** A `campaign_type → source`
  dict keeps future campaigns to "register a function".
- **Retire the vestige.** Fold the audit's cleanup (unused `context_cell_posterior`
  consumer, vestigial `hypothesis_state.stage`, centralised constants) into the
  first orchestration PR opportunistically — small, boundary-safe.
- **Reuse `stopping_spec`/`stall_patience`** rather than inventing new campaign
  controls.

---

## 16. Recommended implementation PR breakdown

Each PR is additive, independently reviewable, keeps the frozen components frozen,
preserves the AST/boundary guards, and stops for review.

- **P6-1 — Assess phase (fills audit G1).** Add an `assess` phase to `ResearchLoop`
  that runs the M11 engine DAG in the fixed dependency order, checkpointed like the
  others. Default-on for ACTIVE campaigns; a no-op when there is no new evidence.
  Proves: end-to-end evidence → decisions per tick; determinism/replay preserved.
- **P6-2 — Campaign types + source registry (fills audit G2).** Add `campaign_type`
  (additive column) + a `HypothesisSource` protocol + registry; bind
  `strategy_evolution → ResearchStrategist` as the default so existing behaviour is
  byte-identical. Prove back-compat.
- **P6-3 — FactoryRunner + report step (fills audit G3).** A thin, resumable,
  bounded driver that selects the next runnable campaign, runs a tick, advances
  campaign state via `CampaignManager` (stall/stopping), and refreshes the Reporter
  read-models. No new agent.
- **P6-4 — Project 07 hand-off.** Make the preliminary→authoritative boundary
  explicit: tag M11 campaign outputs preliminary and queue completed campaigns for
  Project 07, without importing Project 07 logic.
- **P6-5 — Near-term sources.** `bar_type_comparison`, `overlay_combination`,
  `counterfactual_replay` sources (each a small `propose`); no loop/engine changes.
- **P6-6 — Scale pass (optional, when needed).** Shared per-tick fold cache /
  incremental assess / batch reads, per §14. Behaviour-preserving.
- **P6-7+ — Future external sources.** `literature_review`, `github_mining` input
  adapters behind the source interface, feeding the existing Idea Generator +
  approval gate. Introduced only when prioritised.

**Dependency order:** P6-1 → P6-2 → P6-3 form the spine (a continuously running
factory over the existing agents). P6-4 clarifies authority. P6-5+ plug in campaigns
without touching the spine.

---

## 17. Isolation guarantees (Quant ⟂ Chrysos)

- No `chrysos-doc-agent` imports, configuration, memory, scheduling, or execution
  paths enter any Phase-6 module. The factory lives entirely in `quant-lab`.
- The `FactoryRunner` and campaign types are Quant-domain concepts; they never
  reference PhotonAssay, Slack, or Chrysos storage.
- The two projects continue to evolve independently, as established in Phase 0.

---

## 18. Non-goals (explicitly out of scope for Phase 6)

- Changing the M11 methodology or engines, the Bar Engine, or the executor.
- Implementing the future campaigns themselves (literature/GitHub/replay bodies).
- Replacing Project 07 or embedding its logic in the factory.
- Adding new permanent agents or a second orchestration layer.

---

### One-line summary

Phase 6 = **the existing `ResearchLoop` gains an `assess` phase (run the frozen M11
DAG) and a `report` step; campaigns gain a `type` that selects a pluggable
`HypothesisSource`; a thin `FactoryRunner` drives campaigns continuously** — turning
the audited M11 components into an autonomous factory with zero new agents and a
clean, explicit boundary to Project 07 and Chrysos.
