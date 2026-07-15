"""
Milestone 11 — Research Intelligence.

A pure *read-and-decide* evidence layer over the existing agent seams. It changes
research **decisions**, not models or execution. See
``docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`` (frozen M11-0 baseline) and
``docs/M11_STATISTICAL_METHODOLOGY.md``.

PR-1 (this package's first slice) ships only the durable **evidence capture**
layer: ``EvidenceRecorder`` turns a finished experiment into one immutable,
fully-provenanced ``evidence_event``. It records evidence and nothing else — no
promotion, retirement, confidence, or deployment decision is made here.
"""

from __future__ import annotations

from .evidence_recorder import EvidenceRecorder

__all__ = ["EvidenceRecorder"]
