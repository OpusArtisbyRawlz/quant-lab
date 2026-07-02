# BE-1 — Bar Engine: Migration Notes & Verification Report

Branch: `feat/m11-bar-engine-be1`
Scope: **infrastructure only, identity mode only.** No behavioural, statistical,
or strategy change. No M7/M9/approval/reporting/replay/campaign changes.

---

## 1. What shipped

A new, self-contained module `src/data/bars/` implementing a deterministic,
pure, stateless market-sampling engine designed around a future-proof
`SamplingSpec` configuration object. Time (identity) sampling only.

New files:
- `src/data/bars/base.py`
- `src/data/bars/validation.py`
- `src/data/bars/time.py`
- `src/data/bars/builder.py`
- `src/data/bars/__init__.py`
- `src/data/bars/README.md`
- `agents/tests/test_bar_engine.py`

**No existing file was modified.** The engine is not yet wired into the M7
executor — that is BE-2. BE-1 is pure additive infrastructure.

## 2. Migration notes

- **Nothing to migrate for callers.** No public interface changed; the engine is
  additive and unreferenced by production code paths in BE-1.
- **ExperimentSpec/config still store only `bar_type` (a string).** This is
  intentional and acceptable per the BE-1 refinement: the *engine* is
  spec-shaped, but upstream config need not change yet. `SamplingSpec.from_bar_type`
  and string-accepting `build(...)` bridge the string world to the spec world, so
  BE-2 can adopt specs incrementally.
- **Test placement.** `test_bar_engine.py` lives under `agents/tests/` even
  though it imports **only** from `src` (no agent dependency). Reason: the
  project's single CI entry point is `python -m pytest agents/tests/`; there is
  no top-level `tests/` root. A later PR may relocate these under a dedicated
  `tests/` root with its own CI step.
- **Known real-bar integration risks (deferred to later PRs, not BE-1):**
  1. Cross-sectional alignment — the alpha pipeline ranks per shared `Date`
     (`panel.groupby("Date")`); event-driven bars are per-ticker irregular.
  2. Annualisation — `periods_per_year=252` is hardcoded in `cost_model.py`;
     real bars have a realised cadence. `BarResult.periods_per_year` is the
     forward-looking hook that will carry this through.

## 3. Verification report

### 3.1 Identity equivalence (the headline acceptance test)

`test_time_bars_reproduce_pipeline_exactly` routes deterministic synthetic OHLCV
(6 tickers × 80 business days, fixed seed) through two paths and asserts the
resulting alpha panels are **byte-identical** via `pd.testing.assert_frame_equal`:

```
panel_before = run_market_alpha_pipeline(raw)
panel_after  = run_market_alpha_pipeline(BarEngine.build(raw, SamplingSpec("time")).data)
assert_frame_equal(panel_before, panel_after)   # PASSES
```

This proves identity mode reproduces today's pipeline exactly — the contract for
zero-behaviour-change integration in BE-2.

`test_identity_data_equals_input_framewise` further asserts the engine's output
frames equal the input frames one-for-one.

### 3.2 Contract coverage (21 tests)

| Property | Test |
| --- | --- |
| Identity reproduces pipeline exactly | `test_time_bars_reproduce_pipeline_exactly` |
| Output frames == input frames | `test_identity_data_equals_input_framewise` |
| No mutation of caller data | `test_build_does_not_mutate_input` |
| Determinism (same in → same out) | `test_build_is_deterministic` |
| str / spec / None equivalence | `test_api_accepts_str_spec_and_none` |
| Bad spec argument rejected | `test_bad_spec_type_argument_rejected` |
| Unknown type rejected | `test_sampling_spec_rejects_unknown_type` |
| Spec immutable + params read-only | `test_sampling_spec_is_immutable_and_params_readonly` |
| `from_bar_type` defaults to time | `test_from_bar_type_defaults_to_time` |
| Unimplemented types raise | `test_unimplemented_bar_types_raise` (parametrized) |
| Only time implemented in BE-1 | `test_time_is_the_only_implemented_type_in_be1` |
| Annualisation default + override | `test_periods_per_year_default_and_override` |
| Result shape + diagnostics | `test_result_shape_and_diagnostics` |
| Structural validation raises | `test_validate_rejects_empty_and_missing_columns`, `test_validate_rejects_non_datetime_index` |
| Quality issues warn, don't raise | `test_validate_flags_unsorted_index_as_warning_not_error` |

### 3.3 Suite results

```
agents/tests/test_bar_engine.py   ....................    21 passed
agents/tests/ (full)              797 passed in 10.39s
```

776 pre-existing tests + 21 new = **797 passed, 0 failed, 0 regressions.**

## 4. Boundaries preserved

Untouched in BE-1: M7 execution logic, M9 learning, human approval gate,
reporting semantics, deterministic replay, campaign architecture. The engine is
inserted nowhere yet — it only *exists*, ready for the approved execution seam
in BE-2.

---

**BE-1 complete. Stopping for review before BE-2.**
