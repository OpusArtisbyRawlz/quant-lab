# Phase 6 — P6-9: Research Portfolio (persistence + lifecycle/state machine)

Implements **P6-9** of the approved portfolio plan
([research portfolio design](./PHASE6_RESEARCH_PORTFOLIO.md) §7, §10, §11): the
`research_portfolio` persistence model and its event-sourced lifecycle. **Only**
persistence + the state machine — no planner (P6-10), no scheduler change, no
consumption of priority/EIG/triggers/deps/repeat.

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/storage/db.py` | modified | Additive `research_portfolio` table + sibling append-only `portfolio_state_events`; `portfolio_id` event index; SCHEMA 25→26. |
| `agents/storage/portfolio_store.py` | new | Low-level DAL mirroring `campaign_store`: insert/read/list projection, append/reconstruct/list events, membership by `portfolio_id`. State constants (ACTIVE/PAUSED/ARCHIVED) + policy constants. |
| `agents/campaign_manager/manager.py` | modified | The portfolio **state machine** — the design assigns it to this existing coordinator (no new agent): `create_portfolio`, `transition_portfolio` (+ `pause`/`resume`/`archive`), `portfolio_state`, `rebuild_portfolio_from_events`, `reconcile_portfolio`(`_all`), `campaigns_in_portfolio`; `_PORTFOLIO_TRANSITIONS` + `is_legal_portfolio_transition` + `PortfolioError`. |
| `agents/campaign_manager/__init__.py` | modified | Export `PortfolioError`, `is_legal_portfolio_transition`. |
| `agents/tests/test_research_portfolio.py` | new | 18 tests (see Verification). |
| `docs/PHASE6_P6-9_RESEARCH_PORTFOLIO.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

## Design — reuse, don't parallelise

The portfolio layer mirrors the campaign layer's event-sourcing discipline exactly,
so there is one architecture, not two:

- **Two tables, same shape as the campaign layer.** `portfolio_state_events` is the
  append-only **source of truth** (sibling of `campaign_state_events`, carries no
  FK); `research_portfolio` is a **rebuildable projection** whose `state` column is a
  cache of the latest event's `to_state`. The genesis event's evidence carries the
  full config, so the row is fully reconstructible from the log alone.
- **The CampaignManager owns the state machine** (per design §10) — no new manager,
  no new agent. It is the sole writer of both tables. Every accepted transition
  appends the event **first**, then refreshes the projection; a crash between the two
  is repaired by `reconcile_portfolio` (log = ground truth).
- **Lifecycle = exactly the three approved states.** `ACTIVE ⇄ PAUSED`, either
  `→ ARCHIVED`; `ARCHIVED` is terminal. No states or transitions are invented.
  Same-state transitions are idempotent no-ops (no event).
- **Membership reuses `research_campaign.portfolio_id`** (the P6-8 column) — no join
  table, no new linkage.

## Guarantees

- **Append-only / event-sourced.** State lives in the event log; the projection is a
  cache that can be dropped and rebuilt (`rebuild_portfolio_from_events`).
- **Idempotent & replay-safe.** Re-running the same operations reproduces the same
  state and event sequence; rebuild adds no rows/events; same-state transitions emit
  nothing. (Tested.)
- **Additive migration.** A pre-P6-9 DB gains both tables via `create_all_tables`
  (`CREATE TABLE IF NOT EXISTS`); no existing table or column changes.
- **No behaviour change elsewhere.** FactoryRunner and ResearchScheduler are
  untouched; M11/M7/M9/M10/Bar Engine/executor and the Project 07 boundary are
  untouched. `scheduling_policy`/`budget_spec` are stored but **not consumed** (that
  is P6-10/P6-12). No Chrysos coupling.

## Verification

- New `test_research_portfolio.py` (18): create + defaults + duplicate rejection;
  legal transitions; transition-map matches design; illegal-transition rejection
  (incl. unknown portfolio, and state unchanged after rejection); reconstruction from
  events (cache ignored); rebuild-after-delete; reconcile repairs stale cache;
  idempotent no-op + idempotent rebuild; campaign association by `portfolio_id`;
  empty portfolio; multiple campaigns under one portfolio; replay determinism; legacy
  DB migration.
- Full suite: **1280 passed, 1 skipped** (+18). AST/boundary/import-closure guards:
  **68 passed**. No frozen module changed; no Chrysos coupling.
