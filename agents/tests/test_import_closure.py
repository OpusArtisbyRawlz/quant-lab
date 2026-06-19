"""
Import-closure guard for the experiment-runner research engine.

This is a deliberately minimal, dependency-light test whose sole job is to fail
loudly if the `src/` modules that `agents/experiment_runner` imports at module
load time ever go missing again (the exact failure mode that slipped through
M3-M8 because these files were untracked / git-ignored and there was no CI).

If any import below raises ModuleNotFoundError, the whole research engine is
un-importable on a fresh checkout, so this test must stay green.
"""

from __future__ import annotations

import importlib

import pytest

# Modules whose *import* transitively pulls in the full src/ closure
# (signals.combine -> signals.library; pipelines.cross_sectional ->
#  features.price, targets.forward_returns, data.panel; utils.metrics).
RUNNER_MODULES = [
    "agents.experiment_runner.runner",
    "agents.experiment_runner.robustness",
]

# The src/ closure those two modules require. Listed explicitly so a missing
# leaf is reported by name rather than as an opaque downstream import error.
REQUIRED_SRC_MODULES = [
    "src.signals.combine",
    "src.signals.library",
    "src.pipelines.cross_sectional",
    "src.features.price",
    "src.targets.forward_returns",
    "src.data.panel",
    "src.utils.metrics",
]


@pytest.mark.parametrize("module_name", RUNNER_MODULES)
def test_experiment_runner_module_imports(module_name):
    """runner.py / robustness.py must import with no missing dependency."""
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - failure path
        pytest.fail(
            f"{module_name} is un-importable on this checkout: missing "
            f"dependency {exc.name!r}. The src/ research engine is incomplete."
        )


@pytest.mark.parametrize("module_name", REQUIRED_SRC_MODULES)
def test_required_src_module_present(module_name):
    """Each src/ module in the runner's import closure must be importable."""
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - failure path
        pytest.fail(
            f"Required research-engine module {module_name!r} is missing "
            f"(import error: {exc.name!r}). Restore it before merging."
        )


def test_apply_signal_combo_is_callable():
    """The specific symbol the runner uses must resolve, not just the module."""
    from src.signals.combine import apply_signal_combo
    assert callable(apply_signal_combo)


def test_run_market_alpha_pipeline_is_callable():
    from src.pipelines.cross_sectional import run_market_alpha_pipeline
    assert callable(run_market_alpha_pipeline)


def test_build_market_panel_is_callable():
    from src.data.panel import build_market_panel
    assert callable(build_market_panel)
