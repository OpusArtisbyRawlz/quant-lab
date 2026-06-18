"""
prompt.py — pure prompt assembly for the Idea Generator.

No I/O and no LLM calls here: callers pass in the known signals, recent
lessons, and recent hypotheses, and this returns a prompt string. Keeping it
pure makes the prompt unit-testable and keeps the "LLM output is data"
boundary clean.
"""

from __future__ import annotations

import json
from typing import Iterable

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
) -> str:
    """Assemble the idea-generation prompt."""
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
        f"Recent lessons (avoid repeating mistakes):\n"
        f"{json.dumps(lessons, indent=2)}\n\n"
        f"Prior hypotheses (do NOT duplicate):\n"
        f"{json.dumps(hyps, indent=2)}\n"
    )
