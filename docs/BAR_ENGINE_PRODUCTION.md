# Bar Engine — Production Enablement

This is the capstone of the Bar Engine work. The three prerequisites for taking
event bars off the experimental shelf are done and merged:

1. **Cross-sectional alignment** (`align_cross_section`) — irregular event bars
   onto a common grid; identity for gap-free daily time bars.
2. **Realised periods-per-year** (`event_periods_per_year`) — event bars carry a
   measured annualisation cadence; time bars keep 252.
3. **Intraday ingestion** (`load_intraday`) — sub-daily observations so event
   bars can close *within* a session.

Production Enablement adds the last two pieces needed to *run* event bars through
the real executor, and — crucially — an **evidence gate** that decides whether
they should be enabled for routine research at all.

## What shipped

### 1. Data-derived default thresholds (`src/data/bars/defaults.py`)

The executor hands the engine only a bare `bar_type` string — it has no tuned
`threshold` and, by design, must never acquire one (that would make it
bar-aware). Event builders need a threshold, so when none is supplied the engine
derives a **pooled default from the data itself**, targeting
`TARGET_BARS_PER_TICKER` (50) bars per ticker:

```
tick    : rows-per-bar   = Σ rows        / (n_tickers * target)
volume  : Σ Volume       / (n_tickers * target)
dollar  : Σ Close*Volume / (n_tickers * target)
```

Imbalance variants reuse their base weight's scale. An explicit
`params["threshold"]` always wins (`resolve_threshold`), so tuned runs are
untouched. Pure and deterministic.

### 2. Unconditional alignment in the executor (`runner.py`)

`runner.py` now applies `align_cross_section(bar_result.data)` after
`BarEngine.build`, **unconditionally**. For gap-free daily time bars this is the
identity, so the production path stays **byte-identical** (proven by
`test_time_path_is_byte_identical`). For event bars it forward-fills onto the
union grid so the peer-ranking pipeline works. The executor still never inspects
the clock — alignment is bar-agnostic and guard-safe.

### 3. The comparison harness (`bar_comparison.py`)

`compare_bar_types(raw_data, spec, kinds, *, baseline="time")` runs the *identical*
backtest pipeline once per bar type and grades each against the time baseline on
four criteria — **Sharpe** (higher better), **MDD**, **turnover**, and
**robustness-flag count** (lower better) — returning signed deltas and a
per-criterion verdict. `improves_over_baseline(kind)` is true only for a **Pareto
improvement** (no criterion worse, at least one better).

The harness lives in the executor package but stays bar-agnostic in the way the
AST guard enforces: it *iterates* over a caller-supplied list of bar-type
strings and keys results by them; it never branches on a bar-type literal.

## The evidence and the decision

Running the study across eight independent synthetic panels:

| Bar type | Pareto-improvement over time (of 8 seeds) |
| --- | --- |
| `tick` | 0 |
| `volume` | 1 |
| `dollar` | 0 |
| `tick_imbalance` | 0 |
| `volume_imbalance` | 1 |
| `dollar_imbalance` | 1 |

No event bar type improves on the time baseline on a **majority** of seeds. The
occasional single-seed win is noise: the synthetic panels are random walks with
no embedded cross-sectional alpha, so an apparent Sharpe edge on one seed does
not reproduce. Event bars *do* consistently cut turnover (far fewer, larger
bars), but at the cost of a worse or unchanged drawdown and no reliable Sharpe
gain.

**Decision: the production gate stays `PRODUCTION_BAR_TYPES = frozenset({"time"})`.**

This is the literal reading of "measure whether the alternative bars actually
improve … and *only then* enable them." On the available (synthetic) evidence
they do not, so nothing is promoted. What changed is that promotion is now a
**one-line flip backed by a reproducible study** rather than a leap of faith:
the moment a real data source makes some type consistently win,
`test_no_event_bar_is_a_stable_improvement` goes red and forces a deliberate
re-decision instead of silent drift.

## Regression protection

`agents/tests/test_bar_production.py`:

- `test_time_path_is_byte_identical` — alignment + default-threshold wiring do
  not perturb the time-bar metrics.
- `test_event_bar_runs_end_to_end_without_threshold` / `…_is_deterministic` —
  every event type samples, aligns and runs through the executor with a bare
  bar-type string, deterministically.
- `test_compare_bar_types_grades_against_time` / `test_study_is_deterministic` —
  the harness grades correctly and reproducibly.
- `test_production_gate_matches_study_evidence` — any type in
  `PRODUCTION_BAR_TYPES` must be vindicated by the study (honest gate).
- `test_no_event_bar_is_a_stable_improvement` — pins the evidence-based decision
  to keep event bars gated.

The M7 AST guard (`test_executor_bar_agnostic.py`) still passes with the new
`bar_comparison.py` module in the executor package: no bar-type branching, only
public Bar Engine imports.
