"""
report — assembles the full human-readable research report.

generate_research_report() pulls every section from the programmatic API
(summaries.py), renders each with markdown.py, and joins them into one document.
write_research_report() is a thin convenience that writes the string to a file —
the ONLY filesystem write in the package, and only ever to a caller-supplied
report path (never the database).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agents.storage.db import DB_PATH
from . import summaries as s
from . import markdown as md


def generate_research_report(db_path: Path = DB_PATH) -> str:
    """Build the complete markdown research report as a string."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: list[str] = []

    sections.append("# Research Report")
    sections.append(f"_Generated {generated_at}_")

    sections.append("## Research Summary")
    sections.append(md.render_overview(s.research_overview(db_path)))

    sections.append("## Idea Funnel")
    sections.append(md.render_funnel(s.idea_funnel_summary(db_path)))

    sections.append("## Best Source Models")
    sections.append(md.render_source_models(s.source_model_summary(db_path)))

    sections.append("## Best Markets")
    sections.append(md.render_groups(s.market_summary(db_path), "Market"))

    sections.append("## Best Universes")
    sections.append(md.render_groups(s.universe_summary(db_path), "Universe"))

    sections.append("## Best Market / Universe / Model Combinations")
    sections.append(md.render_combos(s.combo_summary(db_path)))

    sections.append("## Critic Decisions")
    sections.append(md.render_decisions(s.critic_decision_summary(db_path)))

    sections.append("## Net Sharpe Distribution")
    sections.append(md.render_net_sharpe(s.net_sharpe_distribution(db_path)))

    sections.append("## Common Rejection Reasons")
    sections.append(md.render_counts(
        s.rejection_reason_summary(db_path), "Rejection reason"))

    sections.append("## Common Lesson Categories")
    sections.append(md.render_counts(
        s.lesson_summary(db_path), "Lesson category"))

    sections.append("## Robustness Flags")
    sections.append(md.render_counts(
        s.robustness_summary(db_path), "Robustness flag"))

    return "\n\n".join(sections) + "\n"


def write_research_report(path: Path, db_path: Path = DB_PATH) -> Path:
    """Render the report and write it to `path`. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_research_report(db_path), encoding="utf-8")
    return path
