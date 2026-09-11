# Phase 6 — P6-11: Trigger-aware planning (eligibility owned by CampaignManager)

Implements **P6-11** of the approved portfolio plan
([research portfolio design](./PHASE6_RESEARCH_PORTFOLIO.md) §3, §4, §6, §10):
trigger/dependency/repeat **evaluation** moves into the CampaignManager (its single
owner) as pure predicates, and the PortfolioPlanner **obtains eligibility from it**
instead of computing its own — so there is no duplicated trigger logic. The planner
stays pure; ResearchScheduler and FactoryRunner are untouched.

## Scope decisions (confirmed with reviewer)

The design's `schedule` triggers and `interval` repeat *cooldown* depend on the
FactoryRunner's **logical tick clock** (ruled untouched here and not yet a stored
primitive); `event` triggers and `until` repeats need a projection-predicate catalog
the design only exemplifies. To avoid inventing policy, P6-11 evaluates the
**clock-free, fully-specified** cases and explicitly defers the rest:

- **Triggers:** `manual` (satisfied once ACTIVE — operator/approval activates it) and
  `dependency` (satisfied iff `depends_on` is satisfied) are evaluated now.
  `schedule`/`event` are **deferred**: such a campaign is trigger-satisfied iff
  already ACTIVE (its activation counts; no auto-firing here), so nothing regresses.
- **Repeats:** `once` (never repeat-eligible) and `interval` (eligible while under the
  clock-free `max_repeats` cap) now; the interval **cooldown timing** and the `until`
  predicate are **deferred**.

Firing transitions (DRAFT→ACTIVE on a trigger, COMPLETED→DRAFT on a repeat) are a
separate, clock-bearing concern for a later PR — P6-11 adds only pure evaluation.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/campaign_manager/manager.py` | modified | Pure eligibility API (the owner): `dependencies_satisfied`, `trigger_satisfied`, `repeat_eligible`, `is_eligible`; trigger-kind + repeat-mode constants. |
| `agents/campaign_manager/__init__.py` | modified | Export the trigger/repeat constants. |
| `agents/storage/campaign_store.py` | modified | `normalized_depends_on` — the single source of dependency normalisation (bare-id + `{campaign_id, required_state}` forms, default COMPLETED), shared by the manager (satisfaction) and planner (ordering edges). |
| `agents/portfolio_planner/planner.py` | modified | Runnable filter now delegates to `CampaignManager.is_eligible`; dependency-aware ordering reads `campaign_store.normalized_depends_on`. The planner's private runnable/dependency logic is removed (no duplication). Outputs unchanged for the implemented cases. |
| `agents/tests/test_trigger_aware_planning.py` | new | 20 tests (see Verification). |
| `docs/PHASE6_P6-11_TRIGGER_AWARE_PLANNING.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

**No storage/schema change. ResearchScheduler + FactoryRunner untouched.**

## Ownership boundaries (preserved)

- **CampaignManager** — the sole owner of trigger/dependency/repeat evaluation. All
  four predicates are pure reads over event-derived state; none mutate or fire.
- **PortfolioPlanner** — remains a pure planning module: it asks the CampaignManager
  `is_eligible(campaign_id)` for the runnable set and only *orders* the result
  (priority / eig_weighted, then the stable dependency-aware refinement). It never
  executes, mutates, allocates budget, evaluates experiments, or bypasses the
  CampaignManager.

## Guarantees

- **No duplicated evaluation.** Dependency normalisation lives once
  (`normalized_depends_on`); satisfaction/trigger/repeat evaluation lives once (the
  CampaignManager). The planner re-derives nothing.
- **Deterministic & replay-safe.** Every predicate is a pure function of stored
  state; the plan is unchanged given the same state (tested: identical replay output;
  planning mutates nothing).
- **Append-only / event-sourced + Project 07 boundary preserved.** All reads; no new
  write path; the preliminary→authoritative hand-off is untouched. No Chrysos
  coupling.

## Verification

- New `test_trigger_aware_planning.py` (20): trigger satisfied/not-satisfied (manual,
  dependency, deferred schedule/event, unknown-raises); repeat allowed/blocked (once,
  interval under/at cap, unbounded, until-deferred, pre-completion); planner obtains
  eligibility from the owner; dependency chains (stage-at-a-time) + dependency-aware
  ordering among co-runnable; priority ordering; archived/stalled excluded; multiple/
  empty portfolios; deterministic replay / identical output; planning purity.
- Full suite: **1326 passed, 1 skipped** (+20; P6-10's 26 planner tests still green
  after the refactor). AST/boundary/import-closure guards: **68 passed**. No frozen
  module changed; ResearchScheduler/FactoryRunner untouched; no Chrysos coupling.
