"""
Bar production-enablement: regression suite + the time-vs-event comparison study.

This is the evidence layer behind promoting (or *not* promoting) event bars to
the production tier. It asserts three things:

1. **Regression / byte-identity** — wiring cross-sectional alignment and
   data-derived default thresholds into the executor leaves the *time*-bar path
   unchanged: same metrics, to the bit, as a direct pipeline run.

2. **Event bars now execute end-to-end** — with a bare bar-type string (no tuned
   threshold), every event bar type samples, aligns, and runs the full pipeline
   through the executor without raising, and is deterministic.

3. **The study is honest** — ``compare_bar_types`` grades each alternative
   against the time baseline on Sharpe / MDD / turnover / robustness, and the
   ``PRODUCTION_BAR_TYPES`` gate matches the study's verdict: a type is
   production-enabled only if the study shows it to be a genuine improvement.

Synthetic data only; deterministic; no network, no disk beyond CostConfig.load.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.protocol import ExperimentSpec
from agents.experiment_runner.cost_model import CostConfig
from agents.experiment_runner.runner import _run_pipeline
from agents.experiment_runner.bar_comparison import compare_bar_types

from src.data.bars import (
    BarEngine,
    SamplingSpec,
    align_cross_section,
    PRODUCTION_BAR_TYPES,
    BAR_TYPES,
)


EVENT_TYPES = [t for t in BAR_TYPES if t != "time"]
ALL_TYPES = list(BAR_TYPES)


def _make_data_dict(n_dates=180, n_tickers=6, seed=7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        prices = 40 * np.cumprod(1 + rng.normal(0.0004, 0.013, n_dates))
        df = pd.DataFrame({
            "Open":   prices * rng.uniform(0.99, 1.00, n_dates),
            "High":   prices * rng.uniform(1.00, 1.02, n_dates),
            "Low":    prices * rng.uniform(0.98, 1.00, n_dates),
            "Close":  prices,
            "Volume": rng.integers(300_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        hypothesis="Short-horizon mean-reversion works.",
        market="US",
        universe="test_universe",
        target="fwd_ret_5",
        features=["mr_ret_5", "low_vol_20"],
        model="quantile_ranking",
        validation_method="walk_forward",
        success_criteria={"sharpe": 0.3},
        expected_improvement="Positive Sharpe",
        project="project_test",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


@pytest.fixture(scope="module")
def cfg() -> CostConfig:
    return CostConfig.load()


# ---------------------------------------------------------------------------
# 1. Regression: the time path is byte-identical through the new wiring
# ---------------------------------------------------------------------------

def test_time_path_is_byte_identical(cfg):
    """Aligning + default-threshold wiring must not perturb the time-bar path.

    A direct pipeline run on the raw daily panel and a run through the engine's
    time-bar output (then alignment, which is the identity for gap-free daily
    bars) must produce identical metric bundles.
    """
    raw = _make_data_dict()
    spec = _spec()

    direct, _ = _run_pipeline(spec, raw, cfg, periods_per_year=252.0)

    bar_result = BarEngine.build(raw, SamplingSpec(type="time"))
    aligned = align_cross_section(bar_result.data)
    through_engine, _ = _run_pipeline(
        spec, aligned, cfg, periods_per_year=bar_result.periods_per_year
    )

    assert through_engine["sharpe"] == direct["sharpe"]
    assert through_engine["mdd"] == direct["mdd"]
    assert through_engine["turnover_annualized"] == direct["turnover_annualized"]
    assert bar_result.periods_per_year == 252.0


# ---------------------------------------------------------------------------
# 2. Event bars execute end-to-end with a bare bar-type string
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", EVENT_TYPES)
def test_event_bar_runs_end_to_end_without_threshold(kind, cfg):
    raw = _make_data_dict()
    spec = _spec()
    bar_result = BarEngine.build(raw, SamplingSpec(type=kind), allow_experimental=True)
    aligned = align_cross_section(bar_result.data)
    metrics, _ = _run_pipeline(
        spec, aligned, cfg, periods_per_year=bar_result.periods_per_year
    )
    assert "sharpe" in metrics
    assert bar_result.periods_per_year > 0


@pytest.mark.parametrize("kind", EVENT_TYPES)
def test_event_bar_pipeline_is_deterministic(kind, cfg):
    raw = _make_data_dict()
    spec = _spec()

    def run():
        br = BarEngine.build(raw, SamplingSpec(type=kind), allow_experimental=True)
        return _run_pipeline(
            spec, align_cross_section(br.data), cfg,
            periods_per_year=br.periods_per_year,
        )[0]

    a, b = run(), run()
    assert a["sharpe"] == b["sharpe"]
    assert a["mdd"] == b["mdd"]


# ---------------------------------------------------------------------------
# 3. The comparison study and the gate decision it justifies
# ---------------------------------------------------------------------------

def test_compare_bar_types_grades_against_time(cfg):
    raw = _make_data_dict()
    study = compare_bar_types(raw, _spec(), ALL_TYPES, baseline="time", cost_config=cfg)

    assert study.baseline == "time"
    assert set(study.results) == set(ALL_TYPES)

    # The baseline grades neutral against itself.
    base_row = study.results["time"]
    for name in ("sharpe", "mdd", "turnover", "robustness_flags"):
        assert base_row.verdicts[name] == "equal"
        assert base_row.deltas[name] == 0.0

    # Every alternative gets a signed delta + a verdict on each criterion.
    for kind in EVENT_TYPES:
        row = study.results[kind]
        for name in ("sharpe", "mdd", "turnover", "robustness_flags"):
            assert name in row.deltas
            assert row.verdicts[name] in {"better", "worse", "equal"}


def test_study_is_deterministic(cfg):
    raw = _make_data_dict()
    a = compare_bar_types(raw, _spec(), ALL_TYPES, cost_config=cfg)
    b = compare_bar_types(raw, _spec(), ALL_TYPES, cost_config=cfg)
    for kind in ALL_TYPES:
        assert a.results[kind].deltas == b.results[kind].deltas
        assert a.results[kind].verdicts == b.results[kind].verdicts


def test_production_gate_matches_study_evidence(cfg):
    """The gate must be *evidence-conditional*: a type is production-enabled only
    if the study shows it is a Pareto improvement over the time baseline.

    Time is always production. Any event type in ``PRODUCTION_BAR_TYPES`` must
    earn its place by improving on the study; any event type NOT enabled must be
    one the study does not vindicate. This keeps promotion honest rather than a
    blanket flip.
    """
    assert "time" in PRODUCTION_BAR_TYPES

    raw = _make_data_dict()
    study = compare_bar_types(raw, _spec(), ALL_TYPES, cost_config=cfg)

    for kind in EVENT_TYPES:
        enabled = kind in PRODUCTION_BAR_TYPES
        if enabled:
            # If we shipped it, the evidence must support it.
            assert study.improves_over_baseline(kind), (
                f"{kind} is production-enabled but the study does not show it "
                f"improving over the time baseline"
            )


def test_no_event_bar_is_a_stable_improvement(cfg):
    """The promotion decision must rest on *stable* evidence, not one lucky seed.

    Across several independent synthetic panels, no event bar type is a Pareto
    improvement over the time baseline on a majority of seeds — the occasional
    win is noise on random-walk data with no embedded alpha. This is precisely
    why the production gate stays at ``{"time"}``: promotion is a one-line flip
    backed by ``compare_bar_types``, but the evidence does not (yet) justify it.
    If a future data source makes some type consistently win, this test will go
    red and force a deliberate re-decision rather than a silent drift.
    """
    seeds = [7, 11, 19, 23, 31, 42, 101, 202]
    wins = {k: 0 for k in EVENT_TYPES}
    for s in seeds:
        raw = _make_data_dict(seed=s)
        study = compare_bar_types(raw, _spec(), ALL_TYPES, cost_config=cfg)
        for kind in EVENT_TYPES:
            if study.improves_over_baseline(kind):
                wins[kind] += 1

    majority = len(seeds) // 2 + 1
    stable = {k: n for k, n in wins.items() if n >= majority}
    assert not stable, (
        f"event bars now show a stable improvement {stable}; the production gate "
        f"decision must be revisited (see PRODUCTION_BAR_TYPES)"
    )
    # Consequently, no event bar is production-enabled on current evidence.
    assert PRODUCTION_BAR_TYPES == frozenset({"time"})


def test_baseline_must_be_in_kinds(cfg):
    raw = _make_data_dict()
    with pytest.raises(ValueError):
        compare_bar_types(raw, _spec(), EVENT_TYPES, baseline="time", cost_config=cfg)
