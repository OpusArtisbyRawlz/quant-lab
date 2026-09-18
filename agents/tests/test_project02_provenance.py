"""
Project 02 vendored-snapshot provenance integrity (offline).

Verifies the vendored historical snapshot matches its recorded provenance: the
notebook and artifact hashes in provenance.json equal the files on disk, the notebook
is unmodified since import, and the dual-source roles are declared. No network — this
guards against silent drift of the vendored copy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_P02 = _REPO_ROOT / "research" / "project_02_volatility_regime"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance() -> dict:
    return json.loads((_P02 / "provenance.json").read_text())


def test_structure_present():
    for rel in ("README.md", "SUMMARY.md", "provenance.json",
                "notebooks/spy_volatility_regime_model.ipynb",
                "artifacts/vol_regime_calibrated_oof.csv",
                "modernized"):
        assert (_P02 / rel).exists(), rel


def test_notebook_hash_matches_provenance():
    prov = _provenance()
    nb = _P02 / prov["imported_notebook"]["path"]
    assert _sha256(nb) == prov["imported_notebook"]["sha256"]


def test_artifact_hash_matches_provenance():
    prov = _provenance()
    art = _P02 / prov["imported_artifact"]["path"]
    assert _sha256(art) == prov["imported_artifact"]["sha256"]


def test_dual_source_roles_declared():
    prov = _provenance()
    assert prov["canonical_source"] == "external_git_repo"
    assert prov["local_copy_role"] == "vendored_historical_snapshot"
    assert prov["modified_after_import"] is False
    assert prov["authoritative_repo_url"].endswith("spy-risk-volatility-model")
    assert prov["authoritative_repo_commit"]


def test_output_mapping_documented():
    prov = _provenance()
    mapping = prov["output_mapping"]
    assert mapping["artifact_column"] == "p_high_vol_calibrated"
    assert mapping["downstream_name"] == "p_high_vol_calibrated"
    assert any("project_04" in c for c in mapping["downstream_consumers"])
    assert any("project_05" in c for c in mapping["downstream_consumers"])


def test_notebook_is_valid_ipynb_json():
    nb = _P02 / "notebooks" / "spy_volatility_regime_model.ipynb"
    doc = json.loads(nb.read_text())
    assert "cells" in doc                      # a real notebook, imported intact
