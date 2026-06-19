"""
prompt.py — pure prompt assembly for the Idea Generator.

No I/O and no LLM calls here: callers pass in the known signals, recent
lessons, and recent hypotheses, and this returns a prompt string. Keeping it
pure makes the prompt unit-testable and keeps the "LLM output is data"
boundary clean.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .context_advisor import ContextAdvice

_INSTRUCTIONS = """\
You are a quantitative research idea generator. Propose research ideas as
STRUCTURED DATA ONLY. You do not run anything; a human reviews every idea.

Rules:
- Use ONLY signals from the allowed list. Do not invent signal names.
- Do not propose ideas that duplicate the listed prior hypotheses.
- Output a single JSON object, no prose, no code, no execution instructions:

{
  "ideas": [
    {
      "hypothesis": "<one sentence>",
      "suggested_signals": ["<signal>", ...],
      "rationale": "<why this is worth testing>"
    }
  ]
}
"""


def build_prompt(
    known_signals: Iterable[str],
    recent_lessons: list[dict],
    recent_hypotheses: Iterable[str],
    *,
    n: int,
    advice: "ContextAdvice | None" = None,
) -> str:
    """Assemble the idea-generation prompt.

    When `advice` is supplied (Milestone 9), the prompt also surfaces
    context-aware guidance: which signals to target in this batch's context,
    which generalise broadly, an exploration quota of under-tested signals to
    keep probing, and relevant research memory. The guidance is advisory — the
    rules above still bind the LLM to the allowed signal list.
    """
    signals = ", ".join(sorted(known_signals))
    lessons = [
        {
            "finding": l.get("finding", ""),
            "implication": l.get("implication", ""),
            "confidence": l.get("confidence", ""),
        }
        for l in recent_lessons[:20]
    ]
    hyps = list(recent_hypotheses)[:30]

    return (
        f"{_INSTRUCTIONS}\n"
        f"Propose up to {n} ideas.\n\n"
        f"Allowed signals: {signals}\n\n"
        f"{_render_advice(advice)}"
        f"Recent lessons (avoid repeating mistakes):\n"
        f"{json.dumps(lessons, indent=2)}\n\n"
        f"Prior hypotheses (do NOT duplicate):\n"
        f"{json.dumps(hyps, indent=2)}\n"
    )


def _render_advice(advice: "ContextAdvice | None") -> str:
    """Render context-aware guidance, or empty string when none is supplied."""
    if advice is None:
        return ""

    def _hints(hints) -> list[dict]:
        return [
            {
                "signal": h.feature_name,
                "contribution_score": h.contribution_score,
                "n_experiments": h.n_experiments,
                "lifecycle_state": h.lifecycle_state,
                "generalization_class": h.generalization_class,
                "note": h.note,
            }
            for h in hints
        ]

    ctx = {
        "market": advice.market,
        "universe": advice.universe,
        "regime": advice.regime,
    }
    memory = [
        {"finding": m.get("finding", ""), "implication": m.get("implication", "")}
        for m in advice.memory[:10]
    ]
    return (
        "Context-aware guidance (advisory; performance is NEVER aggregated "
        "globally — each signal is scored per market/universe/regime cell):\n"
        f"Batch context: {json.dumps(ctx)}\n"
        "Signals that perform in THIS context (exploit):\n"
        f"{json.dumps(_hints(advice.targeted), indent=2)}\n"
        "Signals that generalise across many contexts:\n"
        f"{json.dumps(_hints(advice.generalizers), indent=2)}\n"
        f"Reserve at least {advice.explore_quota} of your ideas for these "
        "under-tested signals (exploration quota — keep probing, don't only "
        f"exploit):\n{json.dumps(advice.exploration)}\n"
        "Research memory:\n"
        f"{json.dumps(memory, indent=2)}\n\n"
    )
