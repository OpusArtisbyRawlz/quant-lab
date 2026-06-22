# M9 — Context-Aware Signal Intelligence

## Problem

Through M8 the system could tell you *whether* a signal worked, but it answered
that question with a **single global number** per signal (an average net Sharpe
across every experiment that used it). That number silently merges incompatible
contexts: a signal that is excellent in Indian high-volatility regimes and
useless in US low-volatility ones collapses to a mediocre, uninterpretable mean.
The research questions the system actually needs to answer are contextual:

> Which signals work best in India / US? In NIFTY50 vs. SP500? In high-vol vs.
> low-vol regimes? Which signals **generalise** across markets, and which are
> context-bound?

A global average cannot answer any of these, and `promote_or_combine` (TD-4) was
a dead label because there was no context-aware evidence to promote on.

## Core principle

**Signal performance is never aggregated globally as a stored primary.** The
atomic unit of knowledge is the **context cell**:

```
(feature_name × market × universe × regime × bar_type)
```

Every statistic, attribution, and lifecycle decision retains its context. Global
or per-market numbers exist only as **honest read-time roll-ups** over the same
underlying context observations, so a coarse number can never disagree with the
cell-level provenance behind it.

Example record: `Signal: momentum_20, Market: India, Universe: NIFTY50, Regime:
high_vol, Sharpe: 1.8` — distinct from the same signal's US/low_vol cell.

## Architecture

Two storage layers keep provenance lossless while serving reporting efficiently:

1. **`signal_context_observation`** — append-only provenance. One row per
   experiment × feature × attribution_method (idempotent on that key). This is
   the source of truth; it is never overwritten destructively.
2. **`signal_context_performance`** — a rebuildable cache. A 1:1 roll-up at the
   full context grain, materialised by `rebuild_context_cache`. Droppable and
   reproducible from the observations at any time.

Supporting tables: `regime_label` (per-experiment regime under a versioned
method), `signal_lifecycle_events` (immutable transition audit), and
`research_memory` (context-scoped findings for the IdeaGenerator).

### Regime classification

Deterministic and versioned (`vol_threshold_v1`): `vol < 0.15 → low_vol`,
`vol ≥ 0.30 → high_vol`, else `mid_vol`; missing volatility → the `all`
sentinel. The `method` string is persisted so labels are reproducible and can be
re-derived if the thresholds change, rather than drifting with the corpus the
way population terciles would.

### Bar type

`bar_type` is a first-class context dimension defaulted to `'time'`. Volume /
dollar / tick bars are future work but the grain already carries the dimension,
so no migration is needed to start using them.

## The SignalLibrarian

A deterministic (no-LLM) agent that runs **after** the Ledger, fully isolated:
its hook in `idea_executor` is wrapped so that a librarian failure can never roll
back a completed, ledgered execution. For each experiment it:

1. Classifies and records the regime.
2. Decomposes the experiment into one context observation per feature.
3. Upserts each feature into `signal_library` and links the experiment.
4. Rebuilds the context-performance cache.
5. Re-evaluates each touched signal's **generalization class** and **lifecycle
   state**, emitting a lifecycle event on any change.
6. Distils a context-scoped `research_memory` row for promoted signals.

### Lifecycle & overfitting guards (Q5)

States: `observed → candidate → promoted → retired`.

- **Promotion requires multi-context confirmation**: ≥2 distinct markets *or* ≥2
  distinct regimes clearing the bar. A single lucky context never promotes.
- **Minimum-n per cell** (`min_n`, default 2) flags thin evidence so coarse
  numbers are never read as solid.
- **Exploration quota**: the IdeaGenerator reserves a fraction of each batch for
  under-tested signals, so the system keeps probing instead of compounding on
  whatever looked good first.
- **Relative/consistency bar, not absolute** (TD-1 honesty): absolute net Sharpe
  is not investability-grade (overlapping 5-day returns), so promotion is gated
  on cross-context consistency. Formal statistics are deferred to M11.

Generalization classes: `universal` (≥2 markets), `market_specific` (one market,
≥2 regimes/universes), `regime_specific`, `universe_specific`, `unproven`.

## IdeaGenerator consumption (Q4, pays down TD-3)

`context_advisor.build_context_advice` composes the read APIs into batch
guidance:

- **Targeted (exploit)** — best signals *within* the batch's context.
- **Generalizers** — signals proven across ≥2 contexts globally.
- **Exploration** — under-tested known signals, sized by the exploration quota.
- **Memory** — recent context-scoped findings.

`build_prompt` renders this as advisory guidance; the existing rules still bind
the LLM to the allowed signal list, so "LLM output is data" is preserved.

## Reporting

`context_report_store` issues **no SQL of its own** — it delegates to
`context_store` and `signal_store` — so it trivially passes M8's read-only
static guards. Three new report sections: Signal Generalization (context-aware),
Signal Performance by Context, and Signal Lifecycle Events.

## Schema

Bumped to **v7** via additive, idempotent migration. New tables listed above;
`signal_library` gains `lifecycle_state`, `generalization_class`, `promoted_at`,
`retired_at`, `last_evaluated_at`. Fresh databases get the columns from the
CREATE statements; pre-v7 databases get them reconciled by
`apply_additive_migrations`.

## Boundaries respected

- M1–M8 functionality unchanged; the librarian is purely additive and isolated.
- `src/` import boundary untouched (M9 touches only `agents/` and `docs/`).
- No global aggregate is ever a stored primary.
