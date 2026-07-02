# BE-2 — Bar Engine: M7 Executor Integration

Branch: `feat/m11-bar-engine-be2`
Scope: wire the Bar Engine into the M7 executor at the approved seam, with a
structural guard that keeps the executor bar-type-agnostic forever. Identity
mode only — no behavioural change.

---

## 1. What changed

`agents/experiment_runner/runner.py`:

- Imports **only** the public `BarEngine` from `src.data.bars`.
- Inserts a single sampling step (**5b**) between data loading (step 5) and the
  backtest pipeline (step 6):

  ```python
  bar_result = BarEngine.build(data_dict, spec.bar_type)
  data_dict  = bar_result.data
  # ...continue the pipeline exactly as before
  ```

  Sampling failures are caught and recorded like any other pipeline failure
  (error.txt + failed ingest + `status="failed"`).

That is the executor's **entire** relationship with market sampling. There is no
`if bar_type == …`, no per-clock branching, no import of any individual bar
implementation. `spec.bar_type` is a plain string; the engine coerces it to a
`SamplingSpec` internally and owns all dispatch, validation, and construction.

## 2. The boundary is enforced structurally, not by convention

New test `agents/tests/test_executor_bar_agnostic.py` parses **every** module in
`agents/experiment_runner/` with `ast` and fails CI on any of:

1. **Branching on a bar type / sampling clock** — any comparison whose operand
   name looks like a sampling selector (`bar_type`, `sampling_spec`, …) or whose
   comparator is a known sampling literal (`BAR_TYPES` + `"identity"`).
2. **Reaching into a bar implementation** — `import src.data.bars.<sub>` or
   `from src.data.bars.<sub> import …`.
3. **Importing a non-public engine name** — anything from `src.data.bars` not in
   the package's `__all__`.

It also positively asserts `runner.py` imports `BarEngine` and samples via
`BarEngine.build(...)`.

### Negative controls (proving the guard bites)

| Planted violation | Result |
| --- | --- |
| `if "volume" == "volume": …` in `cost_model.py` | guard **FAILS** (`comparison against sampling literal 'volume'`) |
| `from src.data.bars.time import build_time_bars` in `cost_model.py` | guard **FAILS** (reaches into implementation submodule) |

Both were injected, observed to fail, and reverted.

## 3. Verification report

### 3.1 Zero behavioural change through the real executor

The pre-existing executor test suite runs actual backtests through
`run_experiment` and asserts against hardcoded expected metrics (Sharpe, MDD,
turnover, net metrics, robustness). Routing every one of those runs through
`BarEngine.build` in identity mode leaves **all** of those assertions passing
unchanged — the empirical proof of byte-identical behaviour end-to-end.

### 3.2 Suite results

```
agents/tests/test_executor_bar_agnostic.py   17 passed
agents/tests/ (full)                         814 passed in 10.38s
```

797 (post-BE-1) + 17 new = **814 passed, 0 failed, 0 regressions.**

## 4. Boundaries preserved

Untouched: M9 learning, human approval gate, reporting semantics, deterministic
replay, campaign architecture, cost model, annualisation source. The only
production edit is the two-line sampling seam in `runner.py` plus its import.

### Deferred (not BE-2)

- Real event bars (tick/volume/dollar/imbalance) and their cross-sectional
  alignment — still `NotImplementedError` inside the engine.
- Threading `bar_result.periods_per_year` into the cost model (annualisation
  currently sourced from `cost_config.periods_per_year=252`; identity time
  returns the same 252, so no change today). The hook exists on `BarResult` for
  when realised-cadence bars land.

---

**BE-2 complete. The executor is bar-type-agnostic and structurally guarded.**
