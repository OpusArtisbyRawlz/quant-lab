# Phase 6 — P6-1: Assess Phase Integration

Implements the first PR of the approved Phase 6 plan
([orchestration design](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md), §7 + §16
P6-1): wire the completed, **frozen** M11 Research Intelligence DAG into the
existing `ResearchLoop` as a new `assess` phase. This closes the M11 audit's #1
readiness gap (the engines were previously invoked only manually).

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/storage/loop_store.py` | modified | Add `PHASE_ASSESS = "assess"` between `learn` and `checkpoint`; extend `PHASES`. |
| `agents/research_loop/loop.py` | modified | `LoopConfig.assess` (default `True`); `_do_assess` phase (record evidence + fold the M11 DAG); `_assess_dag()` (the pipeline expressed as an ordered list); wire into `run_tick`. |
| `agents/tests/test_loop_assess_phase.py` | new | 7 tests: presence, evidence capture + M11 folds, checkpointing, replay determinism, idempotence, config-off. |
| `docs/PHASE6_P6-1_ASSESS_PHASE.md` | new | This note. |

**Only the `ResearchLoop` (M10) is touched** — the additive orchestration hook the
Phase 6 design explicitly sanctions. M7, M9, the executor, the Bar Engine, and the
M11 engines/methodology are unchanged.

## The assess phase

Runs between `learn` and `checkpoint`, bracketed by `loop_checkpoint` like every
other phase:

1. **Record evidence** — for each of the campaign's nodes that ran an experiment
   (`hypothesis_node.experiment_id`), call `EvidenceRecorder.record` (idempotent
   `INSERT … ON CONFLICT DO NOTHING`; nodes whose experiment is not yet in the
   ledger are captured on a later tick).
2. **Fold the M11 DAG** in the fixed dependency order (expressed as data in
   `_assess_dag()`): EvidenceProjector → Holdout → FDR → Retirement → Promotion →
   Budget → Generalisation → Failure → Explanation.

The fold is **population-level** (the projections are shared across campaigns, and
FDR is inherently population-wide), so it is a global `rebuild_all` — deterministic
and idempotent. **No statistical recomputation or methodology change happens in the
loop**; it only invokes the frozen engines in order.

## Guarantees preserved

- **Checkpointing / recovery / resume-skip** — the assess phase uses the same
  `_phase` wrapper, so a resumed tick skips a completed assess and a crashed assess
  is safe to re-run (the engines are pure rebuildable folds).
- **Deterministic replay** — same evidence in any insertion order ⇒ byte-identical
  M11 projections after the tick (tested).
- **Append-only** — evidence capture is idempotent append-only; the assess phase
  writes only the rebuildable M11 projections; no historical evidence is mutated.
- **Back-compat** — `LoopConfig.assess=False` gives the pre-Phase-6 execute loop
  (no M11 assessment); existing loop tests pass unchanged (phases are referenced by
  name, not count).

## Verification

- New: `test_loop_assess_phase.py` (7) — presence in the tick, evidence recorded +
  `hypothesis_state`/`promotion_recommendation`/`decision_record` produced, assess
  checkpointed, replay determinism across insertion order, idempotence across two
  ticks, and config-off skips the DAG.
- Existing `test_research_loop.py` (10) pass unchanged.
- AST/boundary/import-closure guards: **68 passed**.
- Full suite: **1211 passed, 1 skipped** (pre-existing); +7 new.

## Not in this PR (next per the plan)

P6-2 campaign types + `HypothesisSource` registry; P6-3 `FactoryRunner` + report
step; then the portfolio layer (P6-8…P6-13). This PR only adds the assess phase.
