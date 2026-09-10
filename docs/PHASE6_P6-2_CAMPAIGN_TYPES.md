# Phase 6 — P6-2: Campaign Types & HypothesisSource Registry

Implements P6-2 of the approved Phase 6 plan
([orchestration design](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md) §8): a campaign
declares **WHAT** research to perform via a `campaign_type`; a data-driven
**HypothesisSource** registry decides which source proposes ideas; the existing
agents decide **HOW**. Additive and back-compatible — no new agent, no execution
change.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/storage/db.py` | modified | `research_campaign.campaign_type` (`TEXT NOT NULL DEFAULT 'strategy_evolution'`) on the CREATE **and** in `_ADDITIVE_COLUMNS`; `SCHEMA_VERSION` 22 → 23. |
| `agents/storage/campaign_store.py` | modified | `insert_campaign` writes `campaign_type`. |
| `agents/campaign_manager/manager.py` | modified | `create_campaign(campaign_type=…)` → genesis-event config → the existing `_write_projection` materialisation path. |
| `agents/research_loop/sources.py` | new | `HypothesisSource` protocol, `StrategistSource` (default), `default_registry`. |
| `agents/research_loop/loop.py` | modified | Build `self.sources` (default registry + injected); `_do_generate` routes by `campaign_type`. |
| `agents/tests/test_campaign_types.py` | new | 9 tests (storage, migration, routing). |
| `docs/PHASE6_P6-2_CAMPAIGN_TYPES.md` | new | This note. |

**Scope:** only the M10 campaign/loop layer + schema — the additive orchestration
hooks the Phase 6 design sanctions. The frozen M11 engines/methodology, the
executor, the Bar Engine, and the M7/M9 execution paths are untouched. (The other
planning fields — trigger/dependency/priority/EIG/repeat/portfolio — belong to
P6-8+ per the design and are **not** in this PR.)

## Behaviour

- **Declarative WHAT.** `campaign_type` (default `strategy_evolution`) selects a
  `HypothesisSource`. The generate phase does
  `source = self.sources[campaign.campaign_type]; source.propose(campaign_id)`.
- **Default = pre-Phase-6.** `strategy_evolution` binds to `StrategistSource`, a
  pass-through over the existing `ResearchStrategist.run_tick` — byte-identical to
  before. Existing loop tests pass unchanged.
- **Extensible / data-driven.** Future types (`bar_type_comparison`,
  `counterfactual_replay`, `literature_review`, `github_mining`, …) plug in by
  registering a source via the `sources=` constructor arg; the loop, engines, and
  scheduler are untouched.
- **Unknown type is safe.** No registered source ⇒ the generate phase yields zero
  ideas with a `skipped_reason` — it never errors.

## Guarantees preserved

- **Additive migration only.** Legacy `research_campaign` rows gain `campaign_type`
  via `_ADDITIVE_COLUMNS` with the default backfilled (tested on a hand-built legacy
  DB). Fresh DBs get it from the CREATE.
- **Replay / determinism / append-only / checkpointing** — unchanged: sources must
  be deterministic; `campaign_type` flows through the event-sourced genesis config
  and the single `_write_projection` path, so it survives `reconcile` (tested).
- **Human approval gate** — untouched; sources still enqueue `pending` ideas.

## Verification

- New `test_campaign_types.py` (9): default/explicit type, reconcile-survival,
  **legacy-DB additive migration**, `default_registry` wiring, default→strategist
  routing, registered-source routing, unknown-type safety, injected-source merge.
- Full suite: **1220 passed, 1 skipped** (pre-existing; +9). AST/boundary/
  import-closure guards: **68 passed**. No frozen module changed; no Chrysos refs.

## Next per the plan

P6-3 `FactoryRunner` + report step; then the portfolio layer (P6-8…P6-13).
