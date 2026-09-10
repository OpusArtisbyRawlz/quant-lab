# Phase 6 — P6-3: FactoryRunner

Implements P6-3 of the approved plan
([orchestration design](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md) §3, §16): the
thin, **stateless** driver that turns the existing components into a continuously
running Research Factory. Closes the M11 audit's G3 (no continuous multi-campaign
driver).

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/research_loop/factory_runner.py` | new | `FactoryRunner` (the driver) + `FactoryReport`. |
| `agents/campaign_manager/manager.py` | modified | `CampaignManager.advance` — evaluate a campaign's stop conditions after a tick and transition (P6-3: budget exhaustion → COMPLETED), reusing the existing `complete` transition. |
| `agents/tests/test_factory_runner.py` | new | 10 tests (order, determinism, stop conditions, bounds, resume, statelessness). |
| `docs/PHASE6_P6-3_FACTORY_RUNNER.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · the Phase 6 tracker. |

**Scope:** only the M10 orchestration layer — a new thin driver module + one
additive method on the campaign owner (`CampaignManager`). The `ResearchScheduler`
and the `ResearchLoop` core are **reused unchanged**. The frozen M11
engines/methodology, executor, and Bar Engine are untouched. No new agent. No
Chrysos coupling.

## The driver (reuse, don't duplicate)

`FactoryRunner.run(max_ticks, max_rounds)` loops:

1. **Advance** — evaluate stop conditions on every live campaign (so a campaign
   *already* budget-exhausted, and thus excluded from the runnable set, still
   reaches a terminal state). Delegated to `CampaignManager.advance`.
2. **Discover** — `ResearchScheduler.campaign_queue()` returns runnable campaigns
   (already filters to ACTIVE + not-budget-exhausted, orders by priority, and will
   honour dependencies once P6-8 adds them). The runner adds **no** scheduling.
3. **Round** — one `ResearchLoop.run_tick()` per runnable campaign in that order;
   after each tick, `advance` the campaign.
4. **Repeat**, bounded by `max_ticks` (required for unbounded campaigns to
   terminate) / `max_rounds`, stopping when no campaign is runnable.

It holds **no state of its own** — everything durable lives in the existing stores
(`loop_checkpoint`, `campaign_state_events`, the M11 projections). One shared
`CampaignManager` is threaded through the scheduler and loop so discovery, ticking,
and advancement agree.

## Guarantees

- **Deterministic order** — campaigns are ticked in `campaign_queue`'s total order
  (priority, then campaign_id); `advance` is a pure function of stored state. Same
  state ⇒ same tick sequence (tested; creation-order independent).
- **Resume / no duplicated execution** — the runner is stateless; on restart it
  re-discovers the runnable set and `run_tick` resumes a half-finished tick and
  never re-runs a completed one, so no tick is executed twice (tested: a second run
  adds only new tick_ids; the earlier completed ticks persist unchanged).
- **Append-only / event-sourced** — no evidence mutated; stop transitions go
  through the campaign event log via the existing `complete`.
- **Bounded & safe** — `max_ticks`/`max_rounds` bound continuous mode; a DRAFT
  (non-ACTIVE) campaign is never force-completed (illegal transition guarded in
  `advance`).

## Deferred (per the plan, not this PR)

Stall detection (`stall_patience`) and rich `stopping_spec` goal predicates are
**P6-8** (portfolio). `advance` evaluates only the deterministic, already-stored
budget condition now; dependency-gated runnability arrives when P6-8 extends the
scheduler's runnable set — the runner picks it up automatically. The report step
(refresh Reporter read-models) can fold in with P6-8.

## Verification

- New `test_factory_runner.py` (10): priority-order round-robin, creation-order
  independence, empty-factory stop, pre-exhausted → COMPLETED, DRAFT not
  force-completed, `advance` idempotence/state-safety, `max_rounds` bound,
  restart-without-re-running-completed-ticks, statelessness (no new tables), report.
- Full suite: **1230 passed, 1 skipped** (pre-existing; +10). AST/boundary/
  import-closure guards: **68 passed**. No frozen module changed; no Chrysos refs.
