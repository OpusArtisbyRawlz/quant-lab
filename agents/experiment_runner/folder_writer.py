"""
folder_writer.py — creates and populates experiment artifact folders.

Experiment ID convention: exp_{NNN:03d}_{slug}
  NNN  — sequential integer, derived from the highest existing exp_NNN prefix
          in completed_dir (not from the database, so it works even after a
          DB wipe).
  slug — lowercased, underscore-joined combination of spec.project and
          spec.model, truncated to 40 characters.

Example: exp_007_project06_quantile_ranking

If spec.experiment_id is pre-set by the caller, that value is used as-is
and no auto-increment occurs.

On failure the runner calls write_error_txt() to leave a recoverable
audit trail. The partial folder is then ingested with status="failed".
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agents.protocol import ExperimentSpec

_ID_PATTERN = re.compile(r"^exp_(\d{3})", re.IGNORECASE)


def make_experiment_id(spec: ExperimentSpec, completed_dir: Path) -> str:
    """
    Return a new unique experiment ID.

    If spec.experiment_id is non-empty, returns it unchanged.
    Otherwise scans completed_dir for the highest exp_NNN prefix and
    returns the next sequential ID with a slug derived from the spec.
    """
    if spec.experiment_id:
        return spec.experiment_id

    next_num = _next_sequence_number(completed_dir)
    slug = _make_slug(spec)
    return f"exp_{next_num:03d}_{slug}"


def create_experiment_folder(experiment_id: str, completed_dir: Path) -> Path:
    """
    Create the experiment folder. Raises if it already exists.

    Returns the created Path.
    """
    folder = completed_dir / experiment_id
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def write_config_json(folder: Path, spec: ExperimentSpec, experiment_id: str) -> None:
    """Serialise ExperimentSpec → config.json inside the experiment folder."""
    record = asdict(spec)
    record["experiment_id"] = experiment_id
    record["generated_at"] = datetime.now(timezone.utc).isoformat()
    (folder / "config.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )


def write_results_summary(
    folder: Path,
    metrics: dict,
    spec: ExperimentSpec,
    experiment_id: str,
) -> None:
    """Auto-generate results_summary.md from metrics and spec."""
    lines = [
        f"# {experiment_id}",
        "",
        f"**Hypothesis:** {spec.hypothesis}",
        f"**Market:** {spec.market}  |  **Universe:** {spec.universe}",
        f"**Features:** {', '.join(spec.features)}",
        f"**Model:** {spec.model}",
        "",
        "## Metrics",
        "",
    ]

    for key in ("sharpe", "mdd", "cagr", "vol", "calmar"):
        val = metrics.get(key)
        formatted = f"{val:.4f}" if val is not None else "N/A"
        lines.append(f"- **{key.upper()}**: {formatted}")

    if spec.success_criteria:
        lines += ["", "## Success Criteria", ""]
        for criterion, threshold in spec.success_criteria.items():
            actual = metrics.get(criterion)
            if actual is not None:
                met = "✓" if actual >= threshold else "✗"
                lines.append(f"- {criterion}: target {threshold} | actual {actual:.4f} {met}")
            else:
                lines.append(f"- {criterion}: target {threshold} | actual N/A")

    if spec.notes:
        lines += ["", "## Notes", "", spec.notes]

    (folder / "results_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_error_txt(folder: Path, error: str) -> None:
    """Write error.txt into the experiment folder for failed runs."""
    (folder / "error.txt").write_text(
        f"Run failed at {datetime.now(timezone.utc).isoformat()}\n\n{error}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_sequence_number(completed_dir: Path) -> int:
    """Return the next experiment sequence number (max existing + 1, min 1)."""
    if not completed_dir.exists():
        return 1

    max_num = 0
    for entry in completed_dir.iterdir():
        if not entry.is_dir():
            continue
        m = _ID_PATTERN.match(entry.name)
        if m:
            max_num = max(max_num, int(m.group(1)))

    return max_num + 1


def _make_slug(spec: ExperimentSpec) -> str:
    """Build a filesystem-safe slug from spec.project and spec.model."""
    raw = f"{spec.project}_{spec.model}" if spec.project else spec.model
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return slug[:40]
