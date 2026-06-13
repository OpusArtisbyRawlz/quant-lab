"""
Tests for variant_ranker.py.

All tests use plain dicts (the format returned by get_variants_for_experiment)
rather than a live database, so no DB fixture is needed.
"""

import pytest
from agents.quant_interface.variant_ranker import rank_variants, top_variant, summarise


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def variants():
    """Representative set with realistic metrics and a few NULLs."""
    return [
        {"strategy_name": "Alpha",   "sharpe": 1.55, "calmar": 0.65, "mdd": -0.655, "cagr": 0.43, "vol": 0.25, "avg_exposure": None},
        {"strategy_name": "Beta",    "sharpe": 1.50, "calmar": 0.60, "mdd": -0.644, "cagr": 0.39, "vol": 0.23, "avg_exposure": 0.90},
        {"strategy_name": "Gamma",   "sharpe": 1.42, "calmar": 0.55, "mdd": -0.625, "cagr": 0.37, "vol": 0.22, "avg_exposure": 0.80},
        {"strategy_name": "Delta",   "sharpe": 1.10, "calmar": 0.40, "mdd": -0.690, "cagr": 0.25, "vol": 0.29, "avg_exposure": 0.70},
        {"strategy_name": "Epsilon", "sharpe": None, "calmar": None, "mdd": None,   "cagr": None, "vol": None, "avg_exposure": None},
    ]


# ---------------------------------------------------------------------------
# rank_variants — basic ordering
# ---------------------------------------------------------------------------

def test_rank_by_sharpe_descending(variants):
    ranked = rank_variants(variants, by="sharpe")
    sharpes = [v["sharpe"] for v in ranked if v["sharpe"] is not None]
    assert sharpes == sorted(sharpes, reverse=True)


def test_rank_by_calmar_descending(variants):
    ranked = rank_variants(variants, by="calmar")
    calmars = [v["calmar"] for v in ranked if v["calmar"] is not None]
    assert calmars == sorted(calmars, reverse=True)


def test_rank_by_mdd_default(variants):
    """Default for MDD is descending (ascending=False): least-negative (best) first.
    -0.625 > -0.644 > -0.655 > -0.690 so descending puts -0.625 first."""
    ranked = rank_variants(variants, by="mdd")
    mdds = [v["mdd"] for v in ranked if v["mdd"] is not None]
    assert mdds == sorted(mdds, reverse=True)  # -0.625, -0.644, -0.655, -0.690


def test_rank_by_mdd_ascending_override(variants):
    """Caller can override: ascending=True puts most-negative first (worst drawdown first)."""
    ranked = rank_variants(variants, by="mdd", ascending=True)
    mdds = [v["mdd"] for v in ranked if v["mdd"] is not None]
    assert mdds == sorted(mdds)  # -0.690, -0.655, -0.644, -0.625


def test_rank_by_cagr(variants):
    ranked = rank_variants(variants, by="cagr")
    cagrs = [v["cagr"] for v in ranked if v["cagr"] is not None]
    assert cagrs == sorted(cagrs, reverse=True)


def test_null_metric_rows_always_last(variants):
    ranked = rank_variants(variants, by="sharpe")
    null_positions = [i for i, v in enumerate(ranked) if v["sharpe"] is None]
    assert all(p == len(ranked) - 1 for p in null_positions)


def test_rank_returns_all_variants(variants):
    ranked = rank_variants(variants, by="sharpe")
    assert len(ranked) == len(variants)


# ---------------------------------------------------------------------------
# rank_variants — constraints
# ---------------------------------------------------------------------------

def test_constraint_min_sharpe(variants):
    ranked = rank_variants(variants, by="calmar", constraints={"min_sharpe": 1.45})
    names = [v["strategy_name"] for v in ranked]
    assert "Alpha" in names
    assert "Beta" in names
    assert "Gamma" not in names
    assert "Delta" not in names


def test_constraint_max_mdd(variants):
    """max_mdd=-0.65 means mdd must be >= -0.65 (less loss than -0.65)."""
    ranked = rank_variants(variants, by="sharpe", constraints={"max_mdd": -0.65})
    mdds = [v["mdd"] for v in ranked]
    assert all(m >= -0.65 for m in mdds)
    assert not any(v["strategy_name"] == "Delta" for v in ranked)  # mdd=-0.69 fails


def test_constraint_min_calmar(variants):
    ranked = rank_variants(variants, by="sharpe", constraints={"min_calmar": 0.60})
    calmars = [v["calmar"] for v in ranked]
    assert all(c >= 0.60 for c in calmars)


def test_constraint_max_vol(variants):
    ranked = rank_variants(variants, by="sharpe", constraints={"max_vol": 0.24})
    vols = [v["vol"] for v in ranked]
    assert all(v <= 0.24 for v in vols)


def test_constraint_null_value_excluded(variants):
    """A variant with NULL in the constrained column is excluded."""
    ranked = rank_variants(variants, by="sharpe", constraints={"min_avg_exposure": 0.75})
    names = [v["strategy_name"] for v in ranked]
    assert "Epsilon" not in names   # avg_exposure=None
    assert "Alpha" not in names     # avg_exposure=None


def test_multiple_constraints_combined(variants):
    ranked = rank_variants(
        variants, by="calmar",
        constraints={"min_sharpe": 1.40, "max_mdd": -0.63},
    )
    for v in ranked:
        assert v["sharpe"] >= 1.40
        assert v["mdd"] >= -0.63


def test_constraints_returning_empty(variants):
    ranked = rank_variants(variants, by="sharpe", constraints={"min_sharpe": 9.99})
    assert ranked == []


def test_unknown_constraint_raises(variants):
    with pytest.raises(ValueError, match="Unknown constraint key"):
        rank_variants(variants, by="sharpe", constraints={"min_alpha": 1.0})


def test_unknown_metric_raises(variants):
    with pytest.raises(ValueError, match="Unknown ranking metric"):
        rank_variants(variants, by="information_ratio")


# ---------------------------------------------------------------------------
# top_variant
# ---------------------------------------------------------------------------

def test_top_variant_by_sharpe(variants):
    best = top_variant(variants, by="sharpe")
    assert best is not None
    assert best["strategy_name"] == "Alpha"


def test_top_variant_by_calmar(variants):
    best = top_variant(variants, by="calmar")
    assert best is not None
    assert best["strategy_name"] == "Alpha"


def test_top_variant_lowest_drawdown(variants):
    """Ascending=True (default for MDD): least-negative MDD wins (smallest loss)."""
    best = top_variant(variants, by="mdd")
    assert best is not None
    # Gamma has mdd=-0.625, the least-negative of all variants
    assert best["strategy_name"] == "Gamma"


def test_top_variant_with_constraint(variants):
    # max_mdd=-0.64 means mdd must be >= -0.64 (i.e. drawdown no worse than -0.64)
    # Alpha mdd=-0.655: -0.655 < -0.64 → FAILS
    # Beta  mdd=-0.644: -0.644 < -0.64 → FAILS
    # Gamma mdd=-0.625: -0.625 >= -0.64 → PASSES
    # Only Gamma passes; best calmar among passing = Gamma (calmar=0.55)
    best = top_variant(variants, by="calmar", constraints={"max_mdd": -0.64})
    assert best is not None
    assert best["strategy_name"] == "Gamma"


def test_top_variant_returns_none_when_no_candidates(variants):
    best = top_variant(variants, by="sharpe", constraints={"min_sharpe": 99.0})
    assert best is None


def test_top_variant_returns_none_on_empty_list():
    assert top_variant([], by="sharpe") is None


def test_top_variant_returns_none_all_null():
    nulls = [{"strategy_name": "X", "sharpe": None, "calmar": None,
              "mdd": None, "cagr": None, "vol": None, "avg_exposure": None}]
    assert top_variant(nulls, by="sharpe") is None


# ---------------------------------------------------------------------------
# summarise
# ---------------------------------------------------------------------------

def test_summarise_default_metrics(variants):
    stats = summarise(variants)
    assert "sharpe" in stats
    assert "calmar" in stats
    assert "mdd" in stats


def test_summarise_sharpe_values(variants):
    stats = summarise(variants, metrics=["sharpe"])
    s = stats["sharpe"]
    assert s is not None
    assert s["min"] == pytest.approx(1.10)
    assert s["max"] == pytest.approx(1.55)
    assert s["count"] == 4   # Epsilon has NULL


def test_summarise_null_column_returns_none(variants):
    stats = summarise(variants, metrics=["avg_exposure"])
    # Beta=0.90, Gamma=0.80, Delta=0.70; Alpha and Epsilon are NULL
    s = stats["avg_exposure"]
    assert s is not None
    assert s["count"] == 3


def test_summarise_all_null_column_returns_none():
    rows = [{"sharpe": None}, {"sharpe": None}]
    stats = summarise(rows, metrics=["sharpe"])
    assert stats["sharpe"] is None


def test_summarise_mean(variants):
    stats = summarise(variants, metrics=["sharpe"])
    expected_mean = (1.55 + 1.50 + 1.42 + 1.10) / 4
    assert stats["sharpe"]["mean"] == pytest.approx(expected_mean)


# ---------------------------------------------------------------------------
# Ingestion neutrality — ranker does not touch ingestion
# ---------------------------------------------------------------------------

def test_ranker_does_not_import_ingestion():
    """variant_ranker must not depend on ingestion or storage modules."""
    import importlib, sys
    mod = importlib.import_module("agents.quant_interface.variant_ranker")
    src = mod.__file__
    with open(src) as f:
        text = f.read()
    assert "from agents.quant_interface.ingestion" not in text
    assert "from agents.storage" not in text
