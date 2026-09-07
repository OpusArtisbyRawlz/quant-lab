# M11 PR-11 — Explainability & Reporter (M11-7)

The final planned M11 slice — the design's **M11-7**: the `decision_record`
explainability log, the `research_memory_query` pure reader, and the read-only
Reporter read-models. All are **pure modules / read functions, not new agents**,
and consume the existing M11 projections — they **recompute no statistic**.

Follows `docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md` (M11-7: `decision_record`,
`research_memory_query`, read-only Reporter boards).

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/explanation.py` | new | Pure decision-record builders (promote / retire / reject). No DB, no RNG. |
| `agents/research_intelligence/explanation_engine.py` | new | `ExplanationWriter`: pure fold of the M11 projections → `decision_record`. |
| `agents/storage/decision_record_store.py` | new | Storage for the `decision_record` projection. |
| `agents/research_intelligence/research_memory_query.py` | new | Pure read-models: stage board, retirement log, generalisation board, standing questions, decision-record lookups. |
| `agents/storage/db.py` | modified | New `decision_record` table; `SCHEMA_VERSION` 21 → 22; indexes. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Export `ExplanationWriter`, `explanation`, `research_memory_query`. |
| `agents/tests/test_explanation.py` | new | 10 builder/engine tests. |
| `agents/tests/test_research_memory_query.py` | new | 10 read-model tests. |
| `docs/M11_PR11_EXPLAINABILITY.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10, the Bar Engine, the executor, the existing `reporting/`
agent, approval, or deployment. No existing rows mutated.

## `decision_record` — the explainability log

A rebuildable projection, one row per **(decision_type, subject)**, explaining a
decision by re-shaping the rows the existing engines produced:

- **promote** (subject = hypothesis) — from `promotion_recommendation`: chosen
  stage/tier, the four axes + gate detail, confidence (π_h), and the supporting /
  contradictory experiment ids.
- **retire** (subject = hypothesis) — from `retirement_evaluation` (retired only):
  state + reason + the deciding posterior snapshot.
- **reject** (subject = experiment) — from `failure_reason`: the reason code + the
  full failure signal set.

Supporting / contradictory experiment ids are read straight from the evidence log
(split by the sign of net Sharpe) — **provenance, not a recomputed statistic**. The
projector is a pure, idempotent, replay-stable fold that prunes decisions whose
subject has left the projections.

**Deferred:** the design's fourth decision type, **prioritise**, needs the
Prioritizer M11 integration deferred in PR-8 (ideas carry no hypothesis link), so
it is not emitted here.

## `research_memory_query` — pure read-models

Answers standing research questions and renders read-only boards **purely from the
projections** — it re-runs nothing: `stage_board`, `retirement_log`,
`generalisation_board`, `surviving_hypotheses` ("what survives?"),
`market_transfer` ("which markets transfer?"), `overfit_experiments` ("what
overfits?"), `failure_summary`, and `explanations_for` (the decision records about
a subject).

**Reporter placement (documented interpretation).** The design suggests adding
these read-models to the `reporting/` Campaign Reporter (an M10 module). To honour
"do not modify M10 / prefer additive modules over invasive rewrites", they are
delivered as **M11-owned pure read functions** instead — the `reporting/` agent can
adopt them later without being edited now. No `reporting/` code is touched.

## Architectural properties

- **No new agents** — a writer module (pure fold) + a reader module; the research
  agents can consume them.
- **Reuse / single source of truth** — every field comes from an existing
  projection; nothing is recomputed. The writer imports only stores + the pure
  builders; the reader imports only stores.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`).
- **Deterministic / replay-safe** — pure builders + readers; deterministic fold;
  rebuild idempotent + prunes.
- **Append-only evidence** — `evidence_event` never mutated; `decision_record` is a
  rebuildable projection.
- **Boundary-clean** — imports only M11 stores/projections/policies; no
  M7/M9/M10/executor/`reporting/` code. AST/boundary guards green.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **decision_record for promote/retire/reject** | `test_writer_emits_promote_retire_reject`; per-source `policy_version` (`test_versioning_from_source_engines`). |
| **Supporting/contradictory provenance** | `test_supporting_contradictory_split_by_sign`. |
| **research_memory_query answers from projections** | `test_research_memory_query.py` (10): boards, standing questions, empty-DB. |
| **Reuse; no recompute** | writer/reader consume existing projection rows only; no statistical computation added. |
| **Deterministic replay** | `test_replay_deterministic_across_insertion_order`, `test_rebuild_is_idempotent`, `test_readers_are_deterministic`. |
| **Append-only / no mutation** | `test_evidence_events_are_never_mutated`. |
| **No new agents; M7/M9/M10/Bar Engine/executor/reporting unchanged** | diff limited to the M11 package + the additive table. |
| **AST / boundary guards preserved** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **quant-lab / chrysos separation** | no Chrysos references; no cross-repo dependency. |
| **Full regression suite passing** | **1204 passed, 1 skipped** (pre-existing). +20 new tests; prior 1184 unchanged. |

## Critical self-review (findings addressed)

- **Replay** — pure builders/readers; deterministic fold (ordered store reads,
  sorted provenance); idempotent rebuild + pruning.
- **Evidence mutation** — none; reads projections + evidence, writes only
  `decision_record`.
- **Hidden coupling** — none; imports only M11 stores/projections/policies; the
  `reporting/` agent is untouched (read-models are M11-owned).
- **Statistical leakage / duplication** — none; every value is consumed from an
  existing projection; supporting/contradictory ids are provenance, not a
  recomputed statistic.
- **New agents** — none.

## Explicitly NOT in this PR

`prioritise` decision records + Prioritizer/Scheduler decision consumption
(deferred from PR-8), robustness memory into `research_memory` (deferred from PR-9),
and any edit to the `reporting/` agent. **This PR explains and reports existing
decisions only; it makes no new decision.**

---

## M11 status after this PR

With PR-11 the frozen M11 design's planned slices (M11-1…M11-7) are implemented.
Known **deferred** follow-ups, each documented at the PR where it arose:
- Prioritizer/Scheduler decision consumption (PR-8) — needs a hypothesis→idea/
  candidate linkage.
- Robustness memory into `research_memory` (PR-9) — M9-owned/M10-consumed table.
- `prioritise` decision records (PR-11) — depend on the Prioritizer integration.
