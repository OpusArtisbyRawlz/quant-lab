# Phase 6 — P6-4: Project 07 hand-off (preliminary → authoritative)

Implements P6-4 of the approved plan
([orchestration design](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md) §9): the
explicit, neutral boundary between the Quant Research Factory's **preliminary**
M11 evidence and Project 07 — Statistical Integrity, the **authoritative** final
evaluator. Formalises the invariant that M11 factory output is never the last word.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/storage/db.py` | modified | New `project07_evaluation` table (Project 07's authoritative verdict, one row per campaign); SCHEMA 23→24. Additive only. |
| `agents/storage/handoff_store.py` | new | The hand-off surface: `pending_handoffs` (derived queue), `record_evaluation` (Project 07's write), `get_evaluation`/`list_evaluations`, `evaluation_status`. |
| `agents/tests/test_project07_handoff.py` | new | 13 tests (derived queue, upsert write/read, status axis, isolation). |
| `docs/PHASE6_P6-4_PROJECT07_HANDOFF.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · the Phase 6 tracker. |

**Scope:** one additive table + one new read/write helper module. No FactoryRunner,
ResearchLoop, scheduler, or CampaignManager change — the hand-off queue is
**derived**, so producing work to hand off is just completing campaigns, which the
factory already does. The frozen M11 engines/methodology, executor, and Bar Engine
are untouched. No new agent. No Chrysos coupling.

## The boundary (derived, no new write-path on the factory side)

- **`pending_handoffs()`** — the DERIVED queue: `{COMPLETED campaigns} − {evaluated
  campaigns}`, ordered by `campaign_id`. Nothing is stored or mutated, so it is
  replay-safe and idempotent. The factory never enqueues; it produces hand-off work
  simply by completing campaigns.
- **`record_evaluation()`** — the **only** writer of `project07_evaluation`. Called
  by Project 07 (on its own cadence) to upsert its authoritative verdict. The factory
  never calls it. `verdict` is opaque here (JSON); `method` is Project 07's tag.
- **`evaluation_status()`** — a campaign's position on the axis:
  `in_progress` (not yet COMPLETED) → `preliminary` (COMPLETED, awaiting Project 07)
  → `authoritative` (Project 07 has ruled).

## Isolation

`handoff_store` imports only the campaign store and the DB layer. It does **not**
import Project 07 (the factory must not depend on the authoritative evaluator) and
has no Chrysos coupling — asserted by tests that parse the module's import list, and
by a test that the FactoryRunner never touches `project07_evaluation`.

## Guarantees

- **Additive & replay-safe** — a new `CREATE TABLE IF NOT EXISTS`; the derived queue
  reads existing state only. Deterministic replay, append-only, and checkpoint/resume
  are untouched.
- **Authority is explicit** — the table's presence encodes "M11 is preliminary until
  Project 07 writes a verdict"; the status axis reads directly off that.
- **One writer** — only `record_evaluation` (Project 07) writes the table.

## Verification

- New `test_project07_handoff.py` (13): derived queue lists completed-unevaluated
  and excludes active/draft/evaluated and is ordered; upsert write/read roundtrips an
  opaque verdict; status axis in_progress/preliminary/authoritative; isolation (no
  Project 07/Chrysos import; FactoryRunner never writes the table).
- Full suite: **1243 passed, 1 skipped** (+13). AST/boundary/import-closure guards:
  **68 passed**. No frozen module changed; no Chrysos coupling.
