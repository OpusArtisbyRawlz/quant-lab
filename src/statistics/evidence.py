"""
Evidence Ledger — provenance layer for Project 07 statistical conclusions.

Every statistical test in Project 07 (bootstrap, Monte-Carlo, multiple-testing,
Deflated Sharpe, Reality Check) must be reconstructable and auditable. The
Evidence Ledger is the single, append-only record of *why we believe* a
statistical conclusion: what was tested, against which frozen strategy baseline,
with which method and parameters, under which assumptions, and what the outcome
and decision were.

Design principles (mirroring the event-sourced substrate used elsewhere in the
repo):

- **Append-only.** A record is an immutable fact. Corrections are new records,
  never mutations.
- **Self-describing.** Each record carries enough provenance (strategy version,
  Project 06 freeze/tag, dataset, date range, seed, method, assumptions) to be
  reproduced without external context.
- **Deterministic.** Given the recorded seed and parameters, the test reproduces
  the same statistic, p-value, and interval.
- **Method-versioned.** Every record names the method and its version so
  historical conclusions remain interpretable if a method later changes.

This module defines the **schema and interface only**. Storage is intentionally
unimplemented; every I/O method raises ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Decision(str, Enum):
    """Terminal decision attached to a statistical conclusion.

    The four outcomes are mutually exclusive and cover the full space of a test's
    verdict — from "the edge is supported" to "the edge is affirmatively rejected",
    with two distinct kinds of "no" in between (a genuine null result versus
    insufficient evidence to decide).

    Members
    -------
    SIGNIFICANT
        The evidence supports a real edge: the null is rejected at the chosen level
        *after* the relevant selection/multiple-testing penalties.
        *Example:* Deflated Sharpe probability = 0.98 with a trials-adjusted
        benchmark, and the bootstrap CI for Sharpe excludes 0.
    NOT_SIGNIFICANT
        The null cannot be rejected — the data are consistent with *no edge*. This
        is a genuine negative result, not a lack of data.
        *Example:* Monte-Carlo p-value = 0.42; the observed Sharpe sits comfortably
        inside the simulated no-edge null distribution.
    INCONCLUSIVE
        The test could not decide because of insufficient power, too-short a track
        record, or unmet preconditions — distinct from a true negative.
        *Example:* minimum track-record length exceeds the available sample, so the
        Deflated Sharpe cannot be evaluated at the target confidence.
    REJECTED
        The result fails a hard integrity gate regardless of its point estimate —
        the conclusion is disqualified rather than merely non-significant.
        *Example:* an assumption is violated (non-stationary regime break within the
        sample), or the strategy fails the Reality Check across the family even
        though its standalone p-value looked strong.
    """

    SIGNIFICANT = "significant"          # edge statistically supported after penalties
    NOT_SIGNIFICANT = "not_significant"  # cannot reject the null — genuine negative
    INCONCLUSIVE = "inconclusive"        # insufficient power / data — cannot decide
    REJECTED = "rejected"                # fails a hard integrity gate — disqualified


class StatisticalMethod(str, Enum):
    """The statistical procedure that produced a record."""

    BOOTSTRAP = "bootstrap"
    MONTE_CARLO = "monte_carlo"
    PERMUTATION = "permutation"
    MULTIPLE_TESTING = "multiple_testing"
    DEFLATED_SHARPE = "deflated_sharpe"
    WHITE_REALITY_CHECK = "white_reality_check"
    HANSEN_SPA = "hansen_spa"


@dataclass(frozen=True)
class EvidenceRecord:
    """One immutable statistical-conclusion record — the atomic unit of the ledger.

    Fields group into: *provenance* (what/where/when), *method* (how), *result*
    (the numbers), and *judgement* (decision + caveats). Optional fields are those
    that only apply to some methods (e.g. ``bootstrap_iterations`` is ``None`` for
    a Deflated-Sharpe record) or are populated only once a test has run.

    Parameters
    ----------
    record_id
        Stable unique id for this record (e.g. a content hash of the provenance +
        method + parameters). Idempotency key for append.
    strategy_version
        Identifier of the strategy under test (e.g. the experiment/export tag).
    project06_freeze_tag
        The frozen Project 06 baseline the test was computed against
        (e.g. ``"project-06-deployment-validation-frozen"``).
    experiment_id
        Upstream experiment identifier (e.g. ``"exp_005_risk_engine_final"``).
    dataset
        Dataset identifier / path the returns were drawn from.
    date_range
        Inclusive ``(start, end)`` date range of the evaluated sample.
    parameters
        Method parameters (block length, correction level, capital level, …).
    random_seed
        RNG seed used; ``None`` for closed-form methods with no randomness.
    notebook
        Notebook that produced the record (e.g. ``"01_bootstrap.ipynb"``).
    source_module
        Module that computed the statistic (e.g. ``"src/statistics/bootstrap.py"``).
    method
        The :class:`StatisticalMethod` used.
    method_version
        Version tag of the method implementation (e.g. ``"stat_v1"``).
    assumptions
        Human-readable assumptions the result relies on. Be specific and
        exhaustive — the assumptions are what make (or break) the conclusion.
        Examples of what to capture:

        - **IID assumption** — whether observations are treated as independent and
          identically distributed (usually *false* for returns; note it).
        - **Stationarity assumption** — whether the return-generating process is
          assumed stable over the sample.
        - **Bootstrap type** — e.g. stationary, circular block, iid.
        - **Block length** — mean/fixed block length used to preserve dependence.
        - **Circular bootstrap** — whether wrap-around was used.
        - **Random seed** — the seed making the draw reproducible (also in
          ``random_seed``).
        - **Number of simulations** — bootstrap/Monte-Carlo iteration count (also in
          the dedicated fields).
        - **Independence assumptions** — e.g. independence of trials for the
          multiple-testing / Deflated-Sharpe penalty, or independence of strategies
          in the Reality-Check family.
        - **Normality** — whether a normal-returns approximation was relied upon.

        Free text, but prefer a structured, itemised description so the record is
        self-explaining in an audit.
    paper_reference
        *(optional)* Citation for the academic paper the method is drawn from
        (e.g. "Bailey & López de Prado (2014), The Deflated Sharpe Ratio").
    research_reference
        *(optional)* Internal research pointer — design doc, ticket, or notebook
        section that motivated or specified this test.
    commit_hash
        *(optional)* Git commit hash of the code that produced the record.
    git_tag
        *(optional)* Git tag of the code/baseline (e.g. a release or freeze tag).
    implementation_version
        *(optional)* Version of the estimator implementation itself (e.g.
        ``"stat_v1"``), distinct from ``method_version`` when the algorithm and its
        code revision are tracked separately.
    hypothesis
        The hypothesis under test, stated plainly (e.g. "true Sharpe > 0").
    test_statistic
        The computed statistic (Sharpe, t-stat, DSR probability, …); ``None``
        until the test has run.
    p_value
        The (possibly corrected) p-value; ``None`` if not applicable.
    confidence_interval
        ``(low, high)`` interval for the estimated quantity; ``None`` if not
        applicable.
    confidence_level
        Nominal coverage of ``confidence_interval`` (e.g. ``0.95``).
    bootstrap_iterations
        Number of bootstrap resamples; ``None`` unless method is bootstrap.
    monte_carlo_iterations
        Number of Monte-Carlo / permutation draws; ``None`` unless applicable.
    multiple_testing_correction
        Name of the family correction applied (e.g. ``"benjamini_hochberg"``);
        ``None`` if uncorrected.
    n_trials
        Number of hypotheses/configurations in the family (the search size);
        drives the multiple-testing and Deflated-Sharpe penalties.
    deflated_sharpe_result
        Deflated-Sharpe probability / verdict, when computed.
    white_reality_check_result
        Reality-Check / SPA p-value or verdict, when computed.
    decision
        The :class:`Decision` reached from the result.
    limitations
        Known limitations / caveats of this specific conclusion.
    timestamp
        UTC time the record was created.
    extra
        Open namespace for method-specific fields not promoted to columns.
    """

    # --- identity + provenance ---
    record_id: str
    strategy_version: str
    project06_freeze_tag: str
    experiment_id: str
    dataset: str
    date_range: tuple[str, str]
    parameters: dict[str, Any]
    random_seed: Optional[int]
    notebook: str
    source_module: str

    # --- method ---
    method: StatisticalMethod
    method_version: str
    assumptions: str
    hypothesis: str

    # --- result ---
    test_statistic: Optional[float] = None
    p_value: Optional[float] = None
    confidence_interval: Optional[tuple[float, float]] = None
    confidence_level: Optional[float] = None
    bootstrap_iterations: Optional[int] = None
    monte_carlo_iterations: Optional[int] = None
    multiple_testing_correction: Optional[str] = None
    n_trials: Optional[int] = None
    deflated_sharpe_result: Optional[float] = None
    white_reality_check_result: Optional[float] = None

    # --- optional code / literature provenance ---
    paper_reference: Optional[str] = None
    research_reference: Optional[str] = None
    commit_hash: Optional[str] = None
    git_tag: Optional[str] = None
    implementation_version: Optional[str] = None

    # --- judgement ---
    decision: Optional[Decision] = None
    limitations: Optional[str] = None
    timestamp: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)


class EvidenceLedger:
    """Append-only store of :class:`EvidenceRecord`.

    Interface only — storage is not implemented in the Project 07 scaffold. A
    later milestone (P07-6) will back this with the same immutable-log +
    rebuildable-projection pattern used elsewhere in the repo.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        """Bind the ledger to a storage location (path/URI); no I/O performed yet."""
        self._path = path

    def append(self, record: EvidenceRecord) -> str:
        """Append one immutable record; idempotent on ``record.record_id``.

        Returns
        -------
        str
            The ``record_id`` that was stored.
        """
        raise NotImplementedError("Evidence Ledger storage not implemented (scaffold).")

    def get(self, record_id: str) -> EvidenceRecord:
        """Return a single record by id."""
        raise NotImplementedError("Evidence Ledger storage not implemented (scaffold).")

    def query(
        self,
        *,
        strategy_version: Optional[str] = None,
        method: Optional[StatisticalMethod] = None,
        decision: Optional[Decision] = None,
    ) -> list[EvidenceRecord]:
        """Return records matching the given filters (all optional)."""
        raise NotImplementedError("Evidence Ledger storage not implemented (scaffold).")

    def to_frame(self) -> "Any":
        """Return the ledger as a flat table (pandas DataFrame) for reporting."""
        raise NotImplementedError("Evidence Ledger storage not implemented (scaffold).")
