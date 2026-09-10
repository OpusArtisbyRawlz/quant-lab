# Phase 6 — P6-5: Self-registering sources + near-term campaign types

Implements **P6-5** of the approved plan
([orchestration design](./PHASE6_RESEARCH_FACTORY_ORCHESTRATION.md) §8, §10, §16):
turns the P6-2 `HypothesisSource` registry into a **self-registration** architecture
and adds the three near-term sources — `bar_type_comparison`, `overlay_combination`,
`counterfactual_replay` — each a small, deterministic `propose`. **No loop, scheduler,
or runner change.**

## What this PR adds

| File | Kind | Change |
| --- | --- | --- |
| `agents/research_loop/sources/` (was `sources.py`) | new package | Registry core: generic `HypothesisSource` protocol, `Proposal`, `SourceContext`, `@register`, `registered_types`, `build_registry`, and shared thin-adapter helpers (`enqueue_proposal`, `existing_specs`, `campaign_scope`). `StrategistSource` self-registers `strategy_evolution`. |
| `agents/research_loop/sources/bar_type.py` · `overlay.py` · `replay.py` | new | The three near-term sources, each `@register`-ing itself. |
| `agents/research_loop/loop.py` | modified | One line: build the registry via `default_registry(strategist, db_path=…)`. The loop still resolves `registry[campaign_type]` and is agnostic to which source answers. |
| `agents/tests/test_source_registry.py` | new | 12 tests (self-registration, deterministic build, generic interface, each source's sweep/convergence/no-op, loop routing). |
| `agents/tests/test_campaign_types.py` | modified | P6-2 registry test updated: `strategy_evolution` is still the strategist pass-through; the registry now also carries the self-registered sources. |
| `docs/PHASE6_P6-5_NEAR_TERM_SOURCES.md` · `docs/PHASE6_IMPLEMENTATION_STATUS.md` | doc | This note · tracker. |

## The four insistences, held

- **Generic interface.** Every source implements the same one-method protocol
  (`propose(campaign_id) -> list[Proposal]`) and returns uniform `Proposal` records.
  The loop treats them identically; nothing source-specific leaks into orchestration.
- **Sources register themselves.** A source module calls `@register("<type>")` and is
  imported by the package `__init__` — the loop/scheduler/runner name **no** source.
  Adding a research source = a new module + one decorator. Proven by a test that
  registers a type at runtime and finds it in `build_registry` without editing any
  orchestration.
- **Replay & determinism guaranteed.** Each source proposes a pure function of stored
  state: candidates are enumerated in a total (sorted) order, and already-proposed
  `(bar_type, hypothesis)` pairs are skipped, so a source **converges** (proposes each
  candidate once) and re-ticking the same state proposes nothing new. Replay only
  *appends* new pending ideas (fresh idea_ids → fresh experiment_ids); originals are
  never mutated (design §10).
- **Factory agnostic to origin.** The generate phase does
  `registry[campaign.campaign_type].propose(...)` — it neither imports the concrete
  sources nor knows whether a hypothesis came from the strategist, a bar-type sweep,
  or a replay.

## The near-term sources (thin, config-driven, no new intelligence)

All three read their base spec / dimensions from the campaign's `scope`, reuse the
existing enqueue path (`approval_queue` + `link_idea_to_campaign`), and leave every
idea `pending` (human gate intact).

- **`bar_type_comparison`** — sweep `scope.base` across `scope.bar_types` (default: all
  supported clocks); one idea per clock.
- **`overlay_combination`** — enumerate overlay combinations (`itertools.combinations`
  up to `scope.max_overlay_combo`) of `scope.overlays`; the combo is recorded in the
  hypothesis text (applying it is the downstream Designer's job).
- **`counterfactual_replay`** — re-run each `scope.replay` spec under its target bar
  types as **new** append-only ideas. Auto-sourcing prior specs from the ledger (the
  full replay "body") is deferred per Non-goal §18; the specs are taken from scope,
  keeping the source thin and fully deterministic.

## Verification

- New `test_source_registry.py` (12) + updated P6-2 test. Full suite: **1255 passed,
  1 skipped** (+12). AST/boundary/import-closure guards: **68 passed**. No frozen M11
  engine/methodology, Bar Engine, or executor change; no Chrysos coupling.
