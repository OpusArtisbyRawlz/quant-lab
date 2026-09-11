# Phase 6 — P6-8: Extended campaign fields (portfolio-planning inputs)

Implements **P6-8** of the approved portfolio plan
([research portfolio design](./PHASE6_RESEARCH_PORTFOLIO.md) §2, §14): the first
brick of the portfolio layer — additive `research_campaign` columns that carry
triggers, dependencies, priority, EIG, repeat policy, and portfolio membership.
**Additive and fully back-compatible**: a campaign carrying none of these behaves
exactly as before P6-8. P6-8 only *stores* the fields; they are consumed by later
PRs (P6-10 planner, P6-11 triggers/deps/repeats, P6-12/13 budget/EIG).

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/storage/db.py` | modified | Seven additive columns on `research_campaign` (CREATE + `_ADDITIVE_COLUMNS`); `portfolio_id` index; SCHEMA 24→25. |
| `agents/storage/campaign_store.py` | modified | `insert_campaign` writes the new columns; `_row_to_campaign` JSON-decodes the new spec columns; effective-value accessors (`campaign_priority`, `campaign_trigger_spec`, `campaign_repeat_spec`, `campaign_depends_on`) + default constants. |
| `agents/campaign_manager/manager.py` | modified | `create_campaign` accepts the seven optional fields, threads them through the genesis-event config + projection (so they are reconstructible from the log). |
| `agents/tests/test_portfolio_fields.py` | new | 7 tests (fresh + legacy schema, back-compat, round-trip, reconstruct-from-events, scheduler unchanged). |
| `docs/PHASE6_P6-8_EXTENDED_CAMPAIGN_FIELDS.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

## The extended fields (all optional; absent ⇒ current behaviour)

| Field | Type | Default (effective) |
| --- | --- | --- |
| `priority` | REAL | `goal_spec.priority`, else `0.0` |
| `trigger_spec` | JSON | `{"kind": "manual"}` |
| `depends_on` | JSON list | `[]` |
| `expected_information_gain` | REAL (cached) | NULL (not yet derived) |
| `eig_spec` | JSON | NULL (⇒ mean live-hypothesis EVOI) |
| `repeat_spec` | JSON | `{"mode": "once"}` |
| `portfolio_id` | TEXT (nullable) | NULL (standalone campaign) |

The stored column stays NULL for legacy/standalone campaigns; the **effective**
value (with its documented default) is computed in one canonical place —
`campaign_store.campaign_priority/…` — rather than baked into a SQL default, so a
row reconstructed from the event log and a freshly inserted row agree.

## Guarantees

- **Back-compat.** Creating a campaign the old way leaves every new column NULL and
  the effective accessors return today's behaviour (priority still falls back to
  `goal_spec.priority`). The `ResearchScheduler.campaign_queue` ordering is
  **unchanged** — the new `priority` column is not consumed yet (P6-10). Tested.
- **Legacy migration.** A pre-P6-8 `research_campaign` gains the columns via
  `apply_additive_migrations`; the JSON columns take their spec defaults; existing
  rows are preserved. Tested.
- **Deterministic / reconstructible.** The fields live in the genesis event's
  config, so `rebuild_from_events` restores them exactly — append-only and
  replay-safe. Tested.
- **No new intelligence, no new agent.** Storage + accessors only; no scheduler,
  loop, runner, M11, Bar Engine, or executor change. No Chrysos coupling.

## Verification

- New `test_portfolio_fields.py` (7). Full suite: **1262 passed, 1 skipped** (+7).
  AST/boundary/import-closure guards: **68 passed**. No frozen module changed.
