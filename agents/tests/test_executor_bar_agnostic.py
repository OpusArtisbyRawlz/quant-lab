"""
BE-2 — Architectural guard: the M7 Executor must stay bar-type-agnostic.

The executor's *entire* relationship with market sampling is:

    bar_result = BarEngine.build(raw_data, sampling_spec)
    data_dict  = bar_result.data
    # ...continue the pipeline exactly as before

All dispatch, branching, validation, and per-bar construction lives inside the
Bar Engine (``src/data/bars/``). The executor must never:

* branch on a bar type / sampling clock (``if bar_type == "volume"`` etc.), or
* import an individual bar implementation module
  (``from src.data.bars.time import ...``), or
* import anything from the engine that is not part of its **public** surface.

These are enforced structurally by parsing every module in the executor package
(``agents/experiment_runner/``) with the ``ast`` module, so a regression fails
CI rather than slipping through review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.data.bars import BAR_TYPES
from src.data.bars import __all__ as BARS_PUBLIC


# ---------------------------------------------------------------------------
# The executor package under audit
# ---------------------------------------------------------------------------

EXECUTOR_DIR = Path(__file__).resolve().parent.parent / "experiment_runner"
EXECUTOR_MODULES = sorted(
    p for p in EXECUTOR_DIR.glob("*.py") if p.name != "__init__.py"
)

# Tokens that, when compared against, betray bar-type branching in the executor.
_SAMPLING_NAME_TOKENS = ("bar_type", "sampling_spec", "sampling_type", "bartype")
_SAMPLING_LITERALS = frozenset(BAR_TYPES) | {"identity"}

BARS_PACKAGE = "src.data.bars"


def _module_id() -> list[str]:
    return [p.name for p in EXECUTOR_MODULES]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


# ---------------------------------------------------------------------------
# 1. No branching on bar type / sampling clock anywhere in the executor
# ---------------------------------------------------------------------------

def _names_in(node: ast.AST) -> set[str]:
    """Lower-cased identifiers referenced by a Name or Attribute expression."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id.lower())
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr.lower())
    return out


@pytest.mark.parametrize("path", EXECUTOR_MODULES, ids=_module_id())
def test_executor_never_branches_on_bar_type(path: Path):
    tree = _parse(path)
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]

        # (a) comparing something whose name looks like a bar-type selector
        names = set().union(*(_names_in(op) for op in operands))
        if any(tok in n for n in names for tok in _SAMPLING_NAME_TOKENS):
            offenders.append(f"line {node.lineno}: comparison involving {sorted(names & {n for n in names if any(t in n for t in _SAMPLING_NAME_TOKENS)})}")
            continue

        # (b) comparing against a known sampling-type string literal
        for op in operands:
            if isinstance(op, ast.Constant) and op.value in _SAMPLING_LITERALS:
                offenders.append(f"line {node.lineno}: comparison against sampling literal {op.value!r}")

    assert not offenders, (
        f"{path.name} branches on bar type — this logic belongs inside the "
        f"Bar Engine, not the executor:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 2. No import of an individual bar implementation module
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", EXECUTOR_MODULES, ids=_module_id())
def test_executor_imports_only_public_bar_engine(path: Path):
    tree = _parse(path)
    violations: list[str] = []

    for node in ast.walk(tree):
        # `import src.data.bars.time` / `import src.data.bars.time as t`
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(BARS_PACKAGE + "."):
                    violations.append(
                        f"line {node.lineno}: `import {alias.name}` reaches into a "
                        f"bar implementation module; import from the package instead"
                    )

        # `from src.data.bars[.x] import ...`
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == BARS_PACKAGE:
                # public package import — every name must be in the public surface
                for alias in node.names:
                    if alias.name != "*" and alias.name not in BARS_PUBLIC:
                        violations.append(
                            f"line {node.lineno}: imports non-public `{alias.name}` "
                            f"from {BARS_PACKAGE}"
                        )
            elif mod.startswith(BARS_PACKAGE + "."):
                violations.append(
                    f"line {node.lineno}: `from {mod} import ...` reaches into a "
                    f"bar implementation submodule; use the public {BARS_PACKAGE} interface"
                )

    assert not violations, (
        f"{path.name} depends on Bar Engine internals:\n  " + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# 3. Positive assertion: the executor DOES depend on the public interface,
#    and it flows through BarEngine.build(...).
# ---------------------------------------------------------------------------

def test_runner_uses_public_bar_engine_build():
    runner = EXECUTOR_DIR / "runner.py"
    tree = _parse(runner)

    imports_barengine = any(
        isinstance(n, ast.ImportFrom)
        and n.module == BARS_PACKAGE
        and any(a.name == "BarEngine" for a in n.names)
        for n in ast.walk(tree)
    )
    assert imports_barengine, "runner.py must import BarEngine from the public package"

    calls_build = any(
        isinstance(n, ast.Attribute)
        and n.attr == "build"
        and isinstance(n.value, ast.Name)
        and n.value.id == "BarEngine"
        for n in ast.walk(tree)
    )
    assert calls_build, "runner.py must sample via BarEngine.build(...)"
