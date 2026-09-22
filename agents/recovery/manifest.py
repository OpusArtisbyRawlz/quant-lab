"""
Historical-strategy manifest loader + enumeration/verification.

Pure and deterministic: reads the curated ``historical_strategies.json`` and returns
normalized strategy records. No research logic, no execution, no state — this is the
single source of truth for *which* historical strategies exist, so enumeration can be
verified (step 4) before anything runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MANIFEST_PATH = Path(__file__).parent / "historical_strategies.json"

# Recovery scope: Projects 02-06 (01 does not exist; 07 is the authoritative evaluator,
# not a strategy source). Project 02's volatility-regime model was recovered from the
# external repo OpusArtisbyRawlz/spy-risk-volatility-model and vendored under
# research/project_02_volatility_regime/ (status: recovered_source; replay pending
# reproducibility verification).
RECOVERY_PROJECTS = (
    "project_02_volatility_regime",
    "project_03_directional_alpha",
    "project_04_return_forecast_alpha",
    "project_05_risk_engine",
    "project_06_deployment_validation",
)

KIND_BASELINE = "baseline"
KIND_BLEND = "blend"
KIND_OVERLAY = "overlay"
KIND_DEPLOYMENT = "deployment"
KIND_PORTFOLIO = "portfolio"   # composite multi-strategy portfolio (PortfolioSpec)
KIND_CLASSIFIER = "classifier" # single-asset directional classifier (ClassifierSpec)
ALL_KINDS = (KIND_BASELINE, KIND_BLEND, KIND_OVERLAY, KIND_DEPLOYMENT,
             KIND_PORTFOLIO, KIND_CLASSIFIER)

_REQUIRED_FIELDS = ("strategy_id", "project", "kind", "hypothesis", "signals",
                    "market", "universe", "bar_type")


class ManifestError(RuntimeError):
    """Raised when the manifest is malformed or internally inconsistent."""


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the manifest. Raises ManifestError on a
    malformed file, a missing required field, a duplicate strategy_id, an unknown
    kind, or an out-of-scope project."""
    p = Path(path) if path is not None else _MANIFEST_PATH
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {p}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc

    strategies = data.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ManifestError("manifest has no 'strategies' list")

    seen: set[str] = set()
    for s in strategies:
        for field in _REQUIRED_FIELDS:
            if field not in s:
                raise ManifestError(
                    f"strategy {s.get('strategy_id', '?')} missing field {field!r}")
        sid = s["strategy_id"]
        if sid in seen:
            raise ManifestError(f"duplicate strategy_id: {sid}")
        seen.add(sid)
        if s["kind"] not in ALL_KINDS:
            raise ManifestError(f"{sid}: unknown kind {s['kind']!r}")
        if s["project"] not in RECOVERY_PROJECTS:
            raise ManifestError(
                f"{sid}: out-of-scope project {s['project']!r} "
                f"(recovery scope is {RECOVERY_PROJECTS})")
        if not isinstance(s["signals"], list) or not s["signals"]:
            raise ManifestError(f"{sid}: 'signals' must be a non-empty list")
    return data


def enumerate_strategies(path: Path | None = None) -> list[dict[str, Any]]:
    """All manifest strategies, sorted by strategy_id (deterministic)."""
    return sorted(load_manifest(path)["strategies"], key=lambda s: s["strategy_id"])


def strategies_for_kind(kind: str, path: Path | None = None) -> list[dict[str, Any]]:
    """Manifest strategies of a given kind, sorted by strategy_id."""
    return [s for s in enumerate_strategies(path) if s["kind"] == kind]


def alt_bar_eligible(path: Path | None = None) -> list[dict[str, Any]]:
    """Strategies flagged eligible for the Alternative Bar sweep, sorted."""
    return [s for s in enumerate_strategies(path) if s.get("alt_bar_eligible")]


def projects_covered(path: Path | None = None) -> dict[str, int]:
    """Count of strategies per project (deterministic ordering by project)."""
    out: dict[str, int] = {p: 0 for p in RECOVERY_PROJECTS}
    for s in enumerate_strategies(path):
        out[s["project"]] = out.get(s["project"], 0) + 1
    return dict(sorted(out.items()))


def verify_enumeration(path: Path | None = None) -> dict[str, Any]:
    """Step-4 verification: confirm the manifest enumerates strategies for every
    in-scope project and report full coverage. Returns a structured report; sets
    ``complete`` False (never raises for coverage) so callers can gate a launch on it.
    A *malformed* manifest still raises ManifestError (that is a hard error)."""
    strategies = enumerate_strategies(path)
    coverage = projects_covered(path)
    missing = [p for p, n in coverage.items() if n == 0]
    by_kind = {k: len(strategies_for_kind(k, path)) for k in ALL_KINDS}
    return {
        "total": len(strategies),
        "coverage": coverage,
        "missing_projects": missing,
        "by_kind": by_kind,
        "strategy_ids": [s["strategy_id"] for s in strategies],
        "complete": not missing,
    }
