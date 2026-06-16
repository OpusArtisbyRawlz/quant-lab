"""
spec_validator.py — validates an ExperimentSpec before execution.

All checks are rule-based. Nothing is executed or imported from src/ at
validation time — the validator is safe to call without live data.

Returns a ValidationResult with separate error (hard-stop) and warning
(soft, run proceeds) lists so callers can decide how strict to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents.protocol import ExperimentSpec

# ---------------------------------------------------------------------------
# Known signal names — derived from src/signals/library.py.
# Update this set whenever a new signal is added to get_signal_series().
# ---------------------------------------------------------------------------

KNOWN_SIGNALS: frozenset[str] = frozenset({
    "mr_ret_5", "mr_ret_10", "mr_ret_20",
    "mom_ret_5", "mom_ret_10", "mom_ret_20",
    "trend_ma_10", "trend_ma_20",
    "low_vol_5", "low_vol_20",
    "mr_blend", "mom_blend", "mr_lowvol_blend",
})

KNOWN_VALIDATION_METHODS: frozenset[str] = frozenset({
    "walk_forward", "expanding_window", "hold_out", "cross_val", "none",
})


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)    # hard failures — run will not proceed
    warnings: list[str] = field(default_factory=list)  # soft — run proceeds with caveats


def validate_spec(
    spec: ExperimentSpec,
    data_root: Path,
    completed_dir: Path | None = None,
    skip_data_check: bool = False,
) -> ValidationResult:
    """
    Validate an ExperimentSpec before handing it to the runner.

    Parameters
    ----------
    spec : ExperimentSpec
        The spec to validate.
    data_root : Path
        Root directory for market data (e.g. data/raw/).
        Used to check that the universe directory and ticker files exist.
    completed_dir : Path, optional
        Completed experiments directory. If supplied and spec.experiment_id
        is non-empty, warns if that ID already exists on disk.
    skip_data_check : bool
        If True, skip universe directory existence checks. Used when the
        caller supplies data_dict directly (e.g. in tests).

    Returns
    -------
    ValidationResult
        .valid  = True  iff errors is empty.
        .errors = hard failures (unknown signal, missing data dir, etc.)
        .warnings = soft issues (unknown validation method, duplicate ID, etc.)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Required string fields -----------------------------------------------
    for field_name in ("hypothesis", "market", "universe", "target", "model"):
        if not getattr(spec, field_name, "").strip():
            errors.append(f"spec.{field_name} is required and must be non-empty.")

    # --- features must be a non-empty list of known signals -------------------
    if not spec.features:
        errors.append("spec.features must contain at least one signal name.")
    else:
        unknown = [f for f in spec.features if f not in KNOWN_SIGNALS]
        if unknown:
            errors.append(
                f"Unknown signal(s) in spec.features: {unknown}. "
                f"Known signals: {sorted(KNOWN_SIGNALS)}"
            )

    # --- success_criteria should have at least one key ------------------------
    if not spec.success_criteria:
        warnings.append("spec.success_criteria is empty — no numeric targets defined.")

    # --- validation_method ----------------------------------------------------
    if spec.validation_method and spec.validation_method not in KNOWN_VALIDATION_METHODS:
        warnings.append(
            f"Unknown validation_method {spec.validation_method!r}. "
            f"Known: {sorted(KNOWN_VALIDATION_METHODS)}"
        )

    # --- Data directory exists ------------------------------------------------
    universe_dir = data_root / spec.universe
    if skip_data_check:
        pass  # caller supplied data_dict; no disk check needed
    elif not universe_dir.exists():
        errors.append(
            f"Universe data directory not found: {universe_dir}. "
            "Download or symlink market data before running."
        )
    else:
        csv_files = list(universe_dir.glob("*.csv"))
        if not csv_files:
            errors.append(f"No CSV files found in universe directory: {universe_dir}")

    # --- Duplicate experiment ID ----------------------------------------------
    if completed_dir and spec.experiment_id:
        candidate = completed_dir / spec.experiment_id
        if candidate.exists():
            warnings.append(
                f"experiment_id {spec.experiment_id!r} already exists at "
                f"{candidate}. Ingestion will upsert (overwrite) the existing row."
            )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
