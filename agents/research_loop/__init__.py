"""
research_loop — Milestone 10 PR-7.

The ``ResearchLoop`` is the deterministic top-level orchestrator that ties the
M10 decision layer together into a single, resumable *tick*. Each tick walks a
fixed six-phase sequence over one campaign:

    recover → generate → schedule → dispatch → learn → checkpoint

and writes a per-phase checkpoint to the append-only ``loop_checkpoint`` log so
the whole tick is reconstructible from storage and resumable after a crash.

The loop is pure orchestration over already-built components. It **may**
generate (ResearchStrategist), prioritize + schedule (ResearchScheduler, which
uses the ResearchPrioritizer), dispatch the *already-approved* ideas through the
unchanged M7 executor (which runs the M9 learning path), and checkpoint. It
**may not** approve ideas, execute unapproved ideas, modify experiment results,
or change the M7 runner logic — those invariants are inherited unchanged from
M6/M7/M9 and asserted by the loop's tests.
"""

from .loop import (
    ResearchLoop,
    LoopConfig,
    TickReport,
    PhaseResult,
)

__all__ = [
    "ResearchLoop",
    "LoopConfig",
    "TickReport",
    "PhaseResult",
]
