# Phase 6 — Research Portfolio & Extended Campaign Model (Design)

**Status:** design only. No code. A **planning-layer** extension to
[`PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md`](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md)
(PR #46). It enriches the *campaign* model (triggers, dependencies, priorities,
expected information gain, repeat policies) and adds a lightweight **Research
Portfolio** above campaigns for organising and scheduling many concurrent
campaigns.

**Hard constraints (unchanged):**
- **Planning abstraction only** — this changes *what gets scheduled and when*, never
  *how experiments run*.
- **No new agents.** New behaviour lives in the existing `CampaignManager` +
  `ResearchScheduler` + the Phase-6 `FactoryRunner`, plus one **pure** planning
  policy module (a function, not an agent).
- **Execution model untouched.** M11 engines, Bar Engine, executor, and the M11
  methodology stay frozen; determinism + append-only preserved.
- **Quant ⟂ Chrysos** isolation preserved.

> Naming note: "**Research Portfolio**" (a set of research *campaigns*) is distinct
> from the existing *strategy* portfolio (`experiment_type = 'portfolio'`, a
> long/short book). This document only means the former.

---

## 1. Where it sits

```
Research Portfolio        ← NEW planning object: organises + schedules campaigns
   │  (PortfolioPlanner: pure selection policy — which campaigns are runnable now,
   │   in what order, under concurrency/budget limits)
   ▼
Campaign  (+ triggers, dependencies, priority, EIG, repeat)   ← EXTENDED
   ▼
ResearchScheduler.campaign_queue  ← consumes the portfolio-admitted set (extended)
   ▼
FactoryRunner → ResearchLoop.run_tick → agents + M11 assess   ← UNCHANGED (Phase 6)
```

The portfolio is a **layer above campaigns and below the FactoryRunner**. It decides
*organisation and attention*; the FactoryRunner still drives ticks and the loop
still executes exactly as designed in Phase 6.

---

## 2. Extended campaign model

All additions are **additive columns / JSON specs** on `research_campaign` (plus a
`portfolio_id`). Existing campaigns with none of these behave exactly as today
(back-compat: absent spec ⇒ current behaviour).

| Field | Type | Meaning |
| --- | --- | --- |
| `priority` | REAL | First-class static priority (today it lives inside `goal_spec.priority`; promote it to a column, falling back to `goal_spec` for old rows). |
| `trigger_spec` | JSON | When the campaign becomes ACTIVE (see §3). Default `{"kind":"manual"}` = today's behaviour. |
| `depends_on` | JSON list | Campaign ids that must reach a required state before this one is runnable (DAG, §4). Default `[]`. |
| `expected_information_gain` | REAL (cached) | Campaign-level EIG for dynamic ranking (§5), re-derived from M11 signals. |
| `eig_spec` | JSON | How EIG is aggregated (which signal, weighting). Default = mean live-hypothesis EVOI. |
| `repeat_spec` | JSON | Whether/how the campaign repeats after completion (§6). Default `{"mode":"once"}`. |
| `portfolio_id` | TEXT (FK, nullable) | Portfolio membership (§7). Null = standalone campaign. |

`goal_spec`, `scope`, `state`, `budget_*`, `stall_patience`, `stopping_spec` are
reused unchanged.

### 2.1 Triggers, dependencies, priority, EIG, repeat — at a glance

- **Triggers** decide *entry* (DRAFT → ACTIVE) and *re-entry* (repeat).
- **Dependencies** gate *runnability* (a DAG edge from prerequisite → dependent).
- **Priority** is the *static* ordering knob; **EIG** is the *dynamic* one; the
  portfolio's scheduling policy (§8) says how to combine them.
- **Repeat** turns a campaign into a standing/monitoring activity.

---

## 3. Triggers

`trigger_spec.kind` ∈:

- **`manual`** (default) — an operator/approval activates it (today's path).
- **`schedule`** — activate on a logical cadence: `{"every_ticks":N}` or
  `{"at_tick":T}`. The FactoryRunner exposes a monotonic **logical tick clock**
  (not wall-clock) so schedule triggers stay deterministic/replayable; wall-clock
  cadence (for real time) is recorded but the *decision* uses the logical clock.
- **`event`** — activate when a **pure predicate over the stored projections** holds,
  e.g. `{"on":"hypothesis_reached","stage":"Validated"}` (spawn a follow-up
  campaign), `{"on":"strategy_retired"}` (spawn a counterfactual-replay campaign),
  `{"on":"papers_ingested","min":k}`. Event predicates read M11 projections + logs —
  no new computation, no side effects.
- **`dependency`** — activate when `depends_on` is satisfied (§4). Shorthand for the
  common "run B after A".

Triggers are evaluated by the **CampaignManager** (which owns state transitions) via
the pure planner; firing a trigger is an **idempotent** DRAFT→ACTIVE transition
(re-evaluating a fired trigger is a no-op). Trigger evaluations are logged in
`campaign_state_events` for audit/recovery.

---

## 4. Dependencies

- `depends_on` is a list of `{campaign_id, required_state}` (default required state
  `COMPLETED`). A campaign is **runnable** only when every dependency is in (or past)
  its required state.
- The dependency graph is a **DAG**; cycles are rejected at portfolio/campaign
  definition time (a topological check). This keeps ordering total and deterministic.
- Dependencies compose with triggers: a `dependency` trigger fires when deps clear;
  an `event`/`schedule` trigger still additionally respects `depends_on` for
  runnability.
- Dependencies enable pipelines like: *Literature Review* → (ideas) → *Strategy
  Evolution* → (survivors) → *Overlay Combination*, each a campaign, wired by
  `depends_on` — no code, just planning data.

---

## 5. Expected Information Gain (EIG) — reuse, don't recompute

Campaign EIG is an **aggregation of existing M11 signals**, not a new statistic:

```
EIG(campaign) = aggregate over the campaign's live hypotheses of
                budget_allocation.evoi        (PR-7, per-hypothesis EVOI)
   default aggregate = mean;  eig_spec may choose sum / max / promotion-headroom.
```

- It reuses the **already-computed** `budget_allocation.evoi` (which is itself the
  §4 EVOI: high for uncertain-but-promising hypotheses near a gate, ~0 for
  saturated/refuted). Summing/averaging per campaign gives a campaign-level "how much
  learning is left here" — exactly what a portfolio needs to steer attention.
- Retired hypotheses contribute 0 (already so in `budget_allocation`), so a
  played-out campaign's EIG naturally decays → the portfolio down-weights it.
- EIG is **cached** on the campaign (re-derived each planning pass from the
  projections) and is a **pure function of stored state** ⇒ deterministic. No new
  agent, no new methodology, no duplication of the M11 math.

---

## 6. Repeat policies

`repeat_spec.mode` ∈:

- **`once`** (default) — COMPLETED is terminal (today's behaviour).
- **`interval`** — after COMPLETED, wait `cooldown` (logical ticks) then re-enter via
  its trigger, up to `max_repeats` (null = unbounded). For standing activities:
  continuous literature monitoring, periodic bar-type re-sweeps.
- **`until`** — repeat until a stop predicate over the projections holds (e.g.
  "until no new survivors for M repeats").

Mechanics: on COMPLETED, the CampaignManager consults `repeat_spec`; if a repeat is
due it transitions COMPLETED → DRAFT (a first-class, audited transition) and the
trigger re-activates it. The **repeat counter + last-repeat logical tick are stored**
(derivable from `campaign_state_events`), so repeats are deterministic and
recoverable. Each repeat produces **new append-only** evidence/experiments; nothing
historical is mutated.

---

## 7. The Research Portfolio object

A lightweight planning container. Additive table `research_portfolio`:

| Column | Meaning |
| --- | --- |
| `portfolio_id` PK | identity |
| `name` | human label |
| `objective` (JSON) | what the portfolio is for (organisational) |
| `scheduling_policy` | `priority` \| `round_robin` \| `eig_weighted` (§8) |
| `concurrency_limit` INT | max campaigns ACTIVE at once (0 = unbounded) |
| `budget_spec` (JSON) | how the global research budget is split across member campaigns (§9) |
| `state` | `ACTIVE` \| `PAUSED` \| `ARCHIVED` |
| `stopping_spec` (JSON) | portfolio-level stop (e.g. all members COMPLETED) |
| `created_at` / `updated_at` | audit |

- **Membership** is `research_campaign.portfolio_id` (one portfolio per campaign;
  a join table is the fallback if M:N is ever needed — not now).
- Portfolio state is **event-sourced** with the same discipline as campaigns
  (reuse `campaign_state_events` with a `portfolio` subject, or a sibling
  `portfolio_state_events`), so it is recoverable and auditable.
- The portfolio is **purely a planning/organising object** — it never executes, never
  holds research logic, and can be dropped/rebuilt from campaign membership.

---

## 8. Scheduling: the PortfolioPlanner (pure policy)

One new **pure module** — `PortfolioPlanner` (a function, **not an agent**) — turns
portfolio + campaign specs + M11 signals into the **admitted, ordered set of
runnable campaigns**. The existing `ResearchScheduler.campaign_queue` consumes it,
replacing "all ACTIVE non-exhausted campaigns by priority" with "portfolio-admitted
campaigns by the portfolio's policy":

```
PortfolioPlanner.plan(portfolio) -> ordered list of runnable campaign_ids:
  1. runnable = campaigns whose triggers have fired AND dependencies satisfied
                AND state ACTIVE AND not budget-exhausted
  2. admit up to concurrency_limit, choosing by scheduling_policy:
       priority      → (-priority, campaign_id)
       eig_weighted  → (-priority_tier, -EIG, campaign_id)   # static tier, then dynamic EIG
       round_robin   → least-recently-ticked first (fairness)
  3. return the admitted ids in deterministic order
```

- **Deterministic & replayable:** every input (triggers, deps, priority, EIG,
  last-ticked cursor) is a pure function of stored state; ties break on
  `campaign_id`; the logical tick clock replaces wall-clock in decisions. Same state
  ⇒ same plan (matches the M11/Phase-6 determinism guarantee).
- **Additive to the scheduler:** the scheduler keeps its idea/experiment queues
  exactly as-is; only its *campaign selection* now defers to the planner. Standalone
  campaigns (no `portfolio_id`) fall through to today's behaviour, so nothing
  regresses.

---

## 9. Budget allocation across concurrent campaigns

`budget_spec` splits the global research budget (experiment slots per window) across
the admitted campaigns — the campaign-level analogue of the §4 per-hypothesis
budget, and it reuses the same anti-monopoly idea:

- **By policy:** equal (round-robin), priority-proportional, or **EIG-proportional**
  (attention flows to campaigns with the most learning left), with a **per-campaign
  ceiling** so no single campaign monopolises the factory — mirroring the M11
  budget's `a_max`.
- The per-campaign share caps the campaign's `budget_experiments` for the window; the
  existing `remaining_budget`/`experiment_queue` machinery enforces it unchanged.
- Retired-heavy / low-EIG campaigns naturally receive less — the portfolio
  *reallocates its own attention*, exactly as the per-hypothesis budget does one
  level down.

---

## 10. Interaction with existing components (all additive)

| Component | Added responsibility | New agent? |
| --- | --- | --- |
| `CampaignManager` | evaluate triggers, dependency-gating, and repeat transitions; own `portfolio_id`; portfolio state machine | No |
| `ResearchScheduler` | its `campaign_queue` defers campaign selection to `PortfolioPlanner` | No |
| `PortfolioPlanner` | **pure** selection/ordering policy over stored state + M11 EVOI | **No** (a module/function) |
| `FactoryRunner` (P6-3) | drive ticks over the portfolio-admitted set; advance the logical tick clock | No |
| M11 engines / executor / Bar Engine | — | **untouched, frozen** |

No agent is added; three existing coordinators gain planning responsibility, plus one
pure planning function.

---

## 11. Determinism, persistence, recovery

- **Persistence:** additive columns on `research_campaign`; a new
  `research_portfolio` table; portfolio state events. `evidence_event` and the M11
  projections are unchanged. Nothing here is a new *mutable* research artifact — the
  portfolio and the extended fields are planning inputs, and cached EIG is
  re-derivable.
- **Determinism:** triggers/deps/priority/EIG/repeat are all pure functions of stored
  state + a logical tick clock ⇒ the plan is replayable; re-running the same state
  reproduces the same schedule and the same evidence.
- **Recovery:** portfolio + campaign transitions are event-sourced and idempotent;
  the FactoryRunner resumes from `loop_checkpoint` (Phase 6) and re-derives the plan.
  A crash mid-plan re-plans identically.

---

## 12. Failure handling

- **Bad dependency graph (cycle / missing campaign):** rejected at definition
  (topological validation) — never reaches the scheduler.
- **Trigger predicate error / external event source down:** the trigger simply does
  not fire that pass (logged); no campaign is force-activated; the factory proceeds
  with already-runnable campaigns.
- **Over-subscription:** `concurrency_limit` + per-campaign budget ceiling bound the
  active set; excess campaigns wait (deterministic order preserved).
- **Repeat storms:** `cooldown` + `max_repeats` bound re-entry; a repeating campaign
  that keeps stalling ends in STALLED, not an infinite loop.

---

## 13. Scalability & bottlenecks

- Planning is **O(campaigns)** per pass with a small constant (read cached EIG, check
  triggers/deps) — cheap next to the per-tick M11 assess. Thousands of campaigns are
  fine; the cost centre remains the M11 folds (Phase-6 §14).
- **EIG refresh** reuses `budget_allocation` (already computed by the assess phase),
  so no extra statistical work; the planner only aggregates.
- **Dependency DAG** evaluation is a topological pass — memoise per planning pass.
- Watch item: `event` triggers that scan large projections each pass — index the
  predicates' key columns (stages, retirement state) and evaluate incrementally.

---

## 14. Opportunities for simplification

- **One planning policy, expressed as data.** Keep `PortfolioPlanner` a single pure
  function whose behaviour is driven by `scheduling_policy` + specs — no policy
  subclasses, no per-portfolio agents.
- **Reuse, don't reinvent:** EIG = aggregated M11 EVOI; budget ceiling = the §4
  `a_max` idea one level up; state machine + event log = the campaign pattern reused
  for portfolios.
- **Default to today.** Every new field defaults to current behaviour, so the
  extension is invisible until a portfolio/spec opts in.
- **Logical clock, not wall-clock,** for all scheduling decisions — keeps everything
  replayable with no special-casing.

---

## 15. Recommended PR breakdown (extends the Phase-6 plan)

Sequenced after the Phase-6 spine (P6-1 assess → P6-2 campaign types → P6-3
FactoryRunner). Each is additive, back-compatible, and stops for review.

- **P6-8 — Extended campaign fields.** Additive columns (`priority`, `trigger_spec`,
  `depends_on`, `expected_information_gain`, `eig_spec`, `repeat_spec`,
  `portfolio_id`) + defaults = current behaviour. Prove back-compat (existing
  campaigns/scheduler unchanged).
- **P6-9 — Research Portfolio object.** `research_portfolio` table + portfolio state
  machine (reuse the campaign event-sourcing pattern). No scheduling change yet.
- **P6-10 — PortfolioPlanner (pure).** The selection/ordering policy over triggers,
  deps, priority, EIG, concurrency; `ResearchScheduler.campaign_queue` defers to it;
  standalone campaigns unchanged.
- **P6-11 — Triggers, dependencies, repeats in CampaignManager.** Trigger evaluation
  (manual/schedule/event/dependency), dependency-gated runnability, repeat
  transitions — all idempotent + event-sourced.
- **P6-12 — Portfolio budget allocation.** `budget_spec` splits the window budget
  across admitted campaigns with a per-campaign ceiling; enforced via the existing
  `remaining_budget`.
- **P6-13 — EIG aggregation.** Derive campaign EIG from `budget_allocation.evoi`;
  cache on the campaign each planning pass.

**Dependency order:** P6-8 → P6-9 → P6-10 form the portfolio spine; P6-11/12/13 layer
on and can be reordered. All presuppose the Phase-6 spine (P6-1…P6-3).

---

## 16. Non-goals (explicit)

- No new agents; no change to the execution model, M11 engines/methodology, Bar
  Engine, or executor.
- Not implementing the future campaign bodies (literature/GitHub/replay) — they plug
  in as Phase-6 `HypothesisSource`s and are *organised* by this portfolio layer.
- Not replacing or embedding Project 07 — portfolio outputs remain **preliminary**
  until Project 07's authoritative evaluation.
- No Chrysos coupling of any kind.

---

### One-line summary

Add a **planning-only** layer: campaigns gain **triggers, dependencies, priority,
EIG, and repeat policies**; a lightweight **Research Portfolio** organises many
campaigns and, via one **pure `PortfolioPlanner`** consumed by the existing
scheduler, decides *which run now and how much attention each gets* — reusing the M11
EVOI for EIG, reusing the campaign state-machine pattern, adding **no agents** and
**no execution changes**.
