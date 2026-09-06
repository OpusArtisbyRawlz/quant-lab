# M11 PR-9 — Failure Taxonomy (failure_v1)

The ninth M11 slice — the failure-taxonomy half of the design's **M11-5**: a
deterministic, structured classification of failed/rejected experiments into fixed
**reason codes**, the structured sibling to the prose `lessons_learned` (which is
untouched).

**It is a pure module/engine, not a new agent** (like the Holdout, FDR, Budget
engines). Fully M11-owned: it reads only the PR-1 `evidence_event` log and writes
its own rebuildable projection.

**Scope confirmed with the reviewer:** PR-9 ships the **FailureClassifier +
`failure_reason`** only. M11-5's other half — "robustness memory" written into the
M9-owned, M10-consumed `research_memory` table — is **deferred** (it would change
what the M9 librarian's table hands the M10 Prioritizer/idea-generator, and it
overlaps M11-6 generalisation).

Follows `docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` (M11-5, `failure_reason` +
`FailureClassifier`).

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/failure.py` | new | Pure `failure_v1` policy: fixed reason-code taxonomy + `classify`. No DB, no RNG. |
| `agents/research_intelligence/failure_engine.py` | new | Pure fold: `evidence_event` → signals → `classify` → `failure_reason`. |
| `agents/storage/failure_store.py` | new | Storage for the `failure_reason` projection. |
| `agents/storage/db.py` | modified | New `failure_reason` table; `SCHEMA_VERSION` 19 → 20; index. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Export `FailureClassifier` and the `failure` module. |
| `agents/tests/test_failure_policy.py` | new | 16 pure-policy tests. |
| `agents/tests/test_failure_engine.py` | new | 11 engine/replay/boundary tests. |
| `docs/M11_PR9_FAILURE_TAXONOMY.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10, the Bar Engine, the executor, approval, or deployment.
No existing rows mutated. `lessons_learned` untouched.

## The taxonomy (`failure_v1`)

An experiment is a **failure** iff the critic **rejected** it, or it has **no
economic edge** (net Sharpe ≤ S0). A kept, positive experiment is not a failure
(even with a robustness caveat). A single **primary** reason code is chosen by a
fixed priority (most fundamental first); the full signal set is preserved in the
`evidence` JSON for audit.

| Priority | Reason code | Trigger |
| --- | --- | --- |
| 1 | `insufficient_evidence` | too few return periods to trust the result (`periods < min_periods`) |
| 2 | `no_edge` | net Sharpe ≤ S0 |
| 3 | `cost_fragility` | `cost_fragility` robustness flag |
| 4 | `subperiod_instability` | `subperiod_instability` flag |
| 5 | `parameter_fragility` | `parameter_fragility` flag |
| 6 | `rejected_other` | rejected with no specific signal |

Signals come from the fields the PR-1 recorder already captures on `evidence_event`
(critic decision, net Sharpe, sample size `T`, robustness flags) — **nothing is
recomputed**. `min_periods` (the insufficient-evidence threshold) is not enumerated
in the frozen docs, so it is a `FailurePolicy` knob (default 252 = one year daily).
The robustness-flag vocabulary is mirrored (not imported) from
`experiment_runner/robustness.py`, keeping the M11 boundary clean — the same choice
as `promotion.py`.

## Output — `failure_reason` (new, additive, rebuildable)

A droppable cache, one row per failed experiment (PK `experiment_id`), versioned
`failure_v1`: `reason_code`, `evidence` (JSON: the full signal set + all flags,
sorted), `method`, `created_at`. Keyed by `experiment_id` for idempotent,
replay-stable rebuilds (a deviation-of-convenience from the design's illustrative
`id PK, experiment_id` surrogate key, chosen for deterministic rebuilds). The
classifier folds every experiment in the log; non-failures and departed experiments
are pruned.

## Architectural properties

- **Module, not an agent** — a per-experiment pure fold; the research agents can
  orchestrate/consume it. No new agent.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`).
- **Deterministic / replay-safe** — pure classifier; deterministic signal
  aggregation and iteration (sorted); rebuild idempotent + prunes.
- **Append-only evidence** — `evidence_event` never mutated; `failure_reason` is a
  rebuildable projection; `lessons_learned` is never touched.
- **Boundary-clean** — imports only `evidence_store` + `failure_store` + the policy;
  no M7/M9/executor/other-engine code. AST/boundary guards green.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Deterministic taxonomy** | `test_failure_policy.py` (16), incl. each reason, priority ordering, config, purity. |
| **Deterministic replay** | `test_replay_deterministic_across_insertion_order`, `test_classify_is_idempotent`, `test_deterministic_rebuild_from_empty_database`. |
| **Append-only guarantees** | `test_evidence_events_are_never_mutated`; `test_does_not_touch_lessons_learned`. |
| **No recompute** | signals read from `evidence_event` as captured; classifier computes only the reason code. |
| **No new agents** | only a policy module + a pure fold engine added. |
| **M7 / M9 / M10 / Bar Engine / executor unchanged** | diff limited to the M11 package + the additive table. |
| **AST / boundary guards preserved** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **quant-lab / chrysos separation** | no Chrysos references; no cross-repo dependency. |
| **Full regression suite passing** | **1168 passed, 1 skipped** (pre-existing). +27 new tests; prior 1141 unchanged. |

### Behavioural checks demonstrated

- Kept/positive → not a failure; net Sharpe ≤ 0 → `no_edge` even when kept.
- Each reason code fires; priority `insufficient_evidence > no_edge > cost >
  subperiod > parameter > rejected_other`.
- Flags aggregated (union) across an experiment's evidence rows.
- Non-failure rows and stale (departed-experiment) rows are pruned on rebuild.

## Critical self-review (findings addressed)

- **Replay** — pure classifier; sorted aggregation + iteration; idempotent rebuild
  with pruning.
- **Evidence mutation** — none; the classifier only reads `evidence_event` and
  writes its own projection; `lessons_learned` untouched.
- **Hidden coupling** — none; imports only `evidence_store`/`failure_store`/policy;
  no execution/M9/other-engine code.
- **Statistical leakage** — n/a; a taxonomy over already-captured signals, no OOS
  data and no posterior recomputation.
- **Complexity / reuse** — minimal; reuses the evidence readers; mirrors the flag
  vocabulary rather than importing it (boundary-clean).
- **New agents** — none.

## Explicitly NOT in this PR

Robustness memory into `research_memory` (deferred — M9-owned/M10-consumed table),
the `generalisation_matrix` (M11-6), `decision_record` + `research_memory_query` +
Reporter boards (M11-7), and the Prioritizer/Scheduler decision consumption
(deferred in PR-8). **This PR classifies failures only.**
