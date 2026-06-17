"""Tests for agents/critic/critic.py and agents/critic/thresholds.py."""

import tomllib
import pytest
import tempfile
from pathlib import Path

from agents.protocol import CritiqueResult, ExperimentSpec
from agents.critic.critic import Critic
from agents.critic.thresholds import CriticThresholds
from agents.experiment_runner.runner import RunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        hypothesis="Test",
        market="US",
        universe="u",
        target="fwd_ret_5",
        features=["mr_ret_5"],
        model="quantile_ranking",
        validation_method="walk_forward",
        success_criteria={"sharpe": 0.5},
        expected_improvement="Positive Sharpe",
        project="p",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


def _success_result(experiment_id="exp_001", **metrics_overrides) -> RunResult:
    metrics = {"sharpe": 1.2, "mdd": -0.15, "cagr": 0.20, "vol": 0.12, "calmar": 2.0}
    metrics.update(metrics_overrides)
    return RunResult(
        experiment_id=experiment_id,
        status="success",
        metrics=metrics,
        artifact_path=None,
    )


def _failed_result(experiment_id="exp_001") -> RunResult:
    return RunResult(
        experiment_id=experiment_id,
        status="failed",
        metrics={},
        artifact_path=None,
        error="ValueError: No objects to concatenate",
    )


def _make_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "critic.toml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# CriticThresholds.load_defaults
# ---------------------------------------------------------------------------

def test_load_defaults_returns_thresholds_object(tmp_path):
    p = _make_toml(tmp_path, """
[thresholds]
minimum_sharpe = 0.5
maximum_mdd = -0.40
minimum_calmar = 1.0
minimum_cagr = 0.05
[decision_policy]
policy = "strict"
max_retest_attempts = 1
""")
    t = CriticThresholds.load_defaults(p)
    assert isinstance(t, CriticThresholds)


def test_load_defaults_reads_sharpe(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe = 0.7\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p)
    assert t.minimum_sharpe == pytest.approx(0.7)


def test_load_defaults_reads_mdd(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nmaximum_mdd = -0.30\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p)
    assert t.maximum_mdd == pytest.approx(-0.30)


def test_load_defaults_reads_policy(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\n[decision_policy]\npolicy=\"majority\"\nmax_retest_attempts=2\n")
    t = CriticThresholds.load_defaults(p)
    assert t.policy == "majority"
    assert t.max_retest_attempts == 2


def test_load_defaults_missing_file_returns_empty_thresholds(tmp_path):
    t = CriticThresholds.load_defaults(tmp_path / "nonexistent.toml")
    assert t.minimum_sharpe is None


def test_load_defaults_sources_marked_config(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe = 0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p)
    assert t.sources["minimum_sharpe"] == "config"


def test_load_defaults_missing_threshold_source_is_none(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p)
    assert t.sources.get("minimum_sharpe") == "none"


# ---------------------------------------------------------------------------
# CriticThresholds.merge
# ---------------------------------------------------------------------------

def test_merge_spec_overrides_sharpe(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p).merge({"sharpe": 0.9})
    assert t.minimum_sharpe == pytest.approx(0.9)


def test_merge_spec_source_is_spec(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p).merge({"sharpe": 0.9})
    assert t.sources["minimum_sharpe"] == "spec"


def test_merge_config_threshold_unchanged_when_not_in_spec(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\nmaximum_mdd=-0.40\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p).merge({"sharpe": 0.9})
    assert t.maximum_mdd == pytest.approx(-0.40)
    assert t.sources["maximum_mdd"] == "config"


def test_merge_mdd_key_maps_to_maximum_mdd(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    t = CriticThresholds.load_defaults(p).merge({"mdd": -0.25})
    assert t.maximum_mdd == pytest.approx(-0.25)


def test_merge_unrecognised_key_ignored(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    # should not raise
    t = CriticThresholds.load_defaults(p).merge({"win_rate": 0.6})
    assert t.minimum_sharpe is None  # not affected


def test_merge_does_not_mutate_original(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    orig = CriticThresholds.load_defaults(p)
    orig.merge({"sharpe": 0.99})
    assert orig.minimum_sharpe == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Critic.run — pipeline failure → retest
# ---------------------------------------------------------------------------

def test_critic_failed_run_returns_retest(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    c = Critic(p)
    result = c.run(_failed_result(), _spec())
    assert result.decision == "retest"


def test_critic_failed_run_passed_is_false(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_failed_result(), _spec())
    assert result.passed is False


def test_critic_failed_run_drawdown_flag_false(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_failed_result(), _spec())
    assert result.drawdown_flag is False


# ---------------------------------------------------------------------------
# Critic.run — passing experiment
# ---------------------------------------------------------------------------

def test_critic_good_result_returns_keep(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\nmaximum_mdd=-0.40\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(), _spec())
    assert result.decision == "keep"


def test_critic_good_result_passed_is_true(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(), _spec())
    assert result.passed is True


def test_critic_drawdown_flag_set_when_mdd_breaches(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nmaximum_mdd=-0.10\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    # mdd = -0.15 < -0.10 → flag
    result = Critic(p).run(_success_result(mdd=-0.15), _spec())
    assert result.drawdown_flag is True


def test_critic_no_drawdown_flag_when_mdd_within_limit(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nmaximum_mdd=-0.40\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(mdd=-0.15), _spec())
    assert result.drawdown_flag is False


# ---------------------------------------------------------------------------
# Critic.run — failing experiment
# ---------------------------------------------------------------------------

def test_critic_low_sharpe_returns_reject(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(sharpe=0.2), _spec())
    assert result.decision == "reject"


def test_critic_spec_sharpe_overrides_config(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    # spec requires sharpe >= 1.5; actual = 1.2 → reject
    spec = _spec(success_criteria={"sharpe": 1.5})
    result = Critic(p).run(_success_result(sharpe=1.2), spec)
    assert result.decision == "reject"


def test_critic_spec_sharpe_lower_than_config_uses_spec(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    # spec requires only 0.3; actual 1.2 → keep
    spec = _spec(success_criteria={"sharpe": 0.3})
    result = Critic(p).run(_success_result(sharpe=1.2), spec)
    assert result.decision == "keep"


def test_critic_empty_success_criteria_uses_config_only(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    spec = _spec(success_criteria={})
    result = Critic(p).run(_success_result(sharpe=1.2), spec)
    assert result.decision == "keep"


# ---------------------------------------------------------------------------
# CritiqueResult structure
# ---------------------------------------------------------------------------

def test_critic_returns_critique_result_type(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(), _spec())
    assert isinstance(result, CritiqueResult)


def test_critic_thresholds_used_in_result(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(), _spec())
    assert "minimum_sharpe" in result.thresholds_used


def test_critic_thresholds_used_records_source(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    spec = _spec(success_criteria={"sharpe": 0.8})
    result = Critic(p).run(_success_result(), spec)
    assert result.thresholds_used["minimum_sharpe"]["source"] == "spec"


def test_critic_experiment_id_in_result(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result("exp_042"), _spec())
    assert result.experiment_id == "exp_042"


def test_critic_notes_non_empty(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\n[decision_policy]\npolicy=\"strict\"\nmax_retest_attempts=1\n")
    result = Critic(p).run(_success_result(), _spec())
    assert result.notes


# ---------------------------------------------------------------------------
# Majority policy
# ---------------------------------------------------------------------------

def test_critic_majority_policy_keep_when_half_pass(tmp_path):
    # sharpe passes, mdd fails → majority (1/2 = exactly half → reject with majority > half)
    # need 3 thresholds to test majority: 2/3 pass
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=0.5\nmaximum_mdd=-0.10\nminimum_calmar=1.0\n[decision_policy]\npolicy=\"majority\"\nmax_retest_attempts=1\n")
    # sharpe=1.2 ✓  mdd=-0.15 ✗  calmar=2.0 ✓  → 2/3 pass → keep
    result = Critic(p).run(_success_result(mdd=-0.15), _spec())
    assert result.decision == "keep"
    assert result.passed is True


def test_critic_majority_policy_reject_when_majority_fail(tmp_path):
    p = _make_toml(tmp_path, "[thresholds]\nminimum_sharpe=2.0\nmaximum_mdd=-0.10\nminimum_calmar=5.0\n[decision_policy]\npolicy=\"majority\"\nmax_retest_attempts=1\n")
    # sharpe=1.2 ✗  mdd=-0.15 ✗  calmar=2.0 ✗  → 0/3 pass → reject
    result = Critic(p).run(_success_result(), _spec())
    assert result.decision == "reject"


# ---------------------------------------------------------------------------
# Default config file (checked-in)
# ---------------------------------------------------------------------------

def test_critic_default_config_loads_without_error():
    """The checked-in critic_defaults.toml must load without raising."""
    t = CriticThresholds.load_defaults()
    assert t.minimum_sharpe is not None
    assert t.policy in ("strict", "majority")


# ---------------------------------------------------------------------------
# Milestone 5 — net metric basis + robustness downgrade
# ---------------------------------------------------------------------------

def _net_result(experiment_id="exp_005", gross_sharpe=1.2, net_sharpe=0.6,
                flags=None) -> RunResult:
    """A success result carrying both gross flat keys and a nested net block."""
    metrics = {
        "sharpe": gross_sharpe, "mdd": -0.15, "cagr": 0.20, "vol": 0.12, "calmar": 2.0,
        "net": {
            "sharpe": net_sharpe, "mdd": -0.18, "cagr": 0.10, "vol": 0.12,
            "calmar": round(0.10 / 0.18, 4),
        },
        "robustness_flags": flags or [],
    }
    return RunResult(experiment_id=experiment_id, status="success",
                     metrics=metrics, artifact_path=None)


def _basis_toml(tmp_path, basis="net", downgrade="true"):
    return _make_toml(
        tmp_path,
        f'[thresholds]\nminimum_sharpe=1.0\n'
        f'[evaluation]\nmetric_basis="{basis}"\ndowngrade_on_robustness_flags={downgrade}\n'
        f'[decision_policy]\npolicy="strict"\nmax_retest_attempts=1\n',
    )


def test_default_config_metric_basis_is_net():
    t = CriticThresholds.load_defaults()
    assert t.metric_basis == "net"


def test_critic_evaluates_net_by_default(tmp_path):
    # Gross sharpe 1.2 passes the 1.0 threshold, but NET sharpe 0.6 fails it.
    p = _basis_toml(tmp_path, basis="net")
    result = Critic(p).run(_net_result(gross_sharpe=1.2, net_sharpe=0.6), _spec(success_criteria={}))
    assert result.decision == "reject"  # judged on net, which fails


def test_critic_gross_basis_uses_flat_keys(tmp_path):
    # Same result, gross basis → gross sharpe 1.2 passes the 1.0 threshold.
    p = _basis_toml(tmp_path, basis="gross")
    result = Critic(p).run(_net_result(gross_sharpe=1.2, net_sharpe=0.6), _spec(success_criteria={}))
    assert result.decision == "keep"


def test_critic_net_basis_falls_back_to_gross_when_net_absent(tmp_path):
    # Pre-M5 result has no "net" block; net basis must fall back to gross keys.
    p = _basis_toml(tmp_path, basis="net")
    result = Critic(p).run(_success_result(sharpe=1.5), _spec(success_criteria={}))
    assert result.decision == "keep"


def test_robustness_flags_downgrade_keep_to_retest(tmp_path):
    # Net passes (sharpe 1.5 >= 1.0) but robustness flags present → retest.
    p = _basis_toml(tmp_path, basis="net", downgrade="true")
    result = Critic(p).run(
        _net_result(net_sharpe=1.5, flags=["cost_fragility"]), _spec(success_criteria={})
    )
    assert result.decision == "retest"
    assert "cost_fragility" in result.notes


def test_robustness_downgrade_disabled_keeps_decision(tmp_path):
    p = _basis_toml(tmp_path, basis="net", downgrade="false")
    result = Critic(p).run(
        _net_result(net_sharpe=1.5, flags=["cost_fragility"]), _spec(success_criteria={})
    )
    assert result.decision == "keep"
    assert "cost_fragility" in result.notes  # still noted, just not downgraded


def test_thresholds_used_records_metric_basis(tmp_path):
    p = _basis_toml(tmp_path, basis="net")
    result = Critic(p).run(_net_result(net_sharpe=1.5), _spec(success_criteria={}))
    assert result.thresholds_used.get("metric_basis") == "net"
