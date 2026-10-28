"""
``src.statistics`` — Project 07 statistical-integrity toolkit.

Deterministic, evidence-recording statistical tests that judge whether a
strategy's performance is real rather than an artifact of luck, overfitting, or
multiple testing. Consumed by the ``research/project_07_statistical_integrity/``
notebooks.

Submodules
----------
bootstrap
    Block / stationary bootstrap resampling and metric confidence intervals.
monte_carlo
    Monte-Carlo null-path simulation and permutation testing.
significance
    Multiple-testing corrections (FDR / Bonferroni / Holm) and Sharpe t-statistics.
deflated_sharpe
    Probabilistic / Deflated Sharpe Ratio and minimum track-record length.
white_reality_check
    White's Reality Check and Hansen's SPA data-snooping tests.
evidence
    The Evidence Ledger: provenance schema and append-only interface.
report
    Aggregate per-test results into a gated statistical-integrity verdict.

Result objects
--------------
Every statistical procedure in this package returns a **typed, frozen dataclass**
(``BootstrapResult``, ``MonteCarloResult``, ``MultipleTestingResult``,
``DeflatedSharpeResult``, ``RealityCheckResult``, ``IntegrityVerdict``) rather than
a plain ``dict``. This is a deliberate design choice:

- **Reproducibility** — the result carries its own inputs (seed, iterations,
  method), so a result is self-describing and re-derivable, not an anonymous bag of
  numbers.
- **Type safety** — fields and their types are declared once; typos and missing
  keys are caught by tooling instead of failing at runtime deep in a report.
- **Auditability** — a fixed schema maps cleanly onto an ``EvidenceRecord``, so
  provenance capture is mechanical and complete rather than ad-hoc.
- **Easier report generation** — the Decision/report layer consumes stable
  attribute names, so aggregation and rendering never guess dictionary keys.
- **Future extensibility** — new fields can be added with defaults without breaking
  existing callers, and ``frozen=True`` makes results immutable once computed.

Scaffold status: interfaces and documentation are complete; algorithm bodies
raise ``NotImplementedError`` pending implementation.

Note: this is ``src.statistics`` (a subpackage of ``src``); it does not shadow
the Python standard-library ``statistics`` module.
"""
from __future__ import annotations

__all__ = [
    "bootstrap",
    "monte_carlo",
    "significance",
    "deflated_sharpe",
    "white_reality_check",
    "evidence",
    "report",
]
