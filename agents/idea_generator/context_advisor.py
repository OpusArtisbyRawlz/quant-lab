"""
context_advisor — turns Milestone 9 context-aware signal intelligence into
guidance the IdeaGenerator can act on.

The advisor is read-only and pure-ish: it composes the read APIs of
context_store, signal_store, and memory_store into a `ContextAdvice` value, and
build_prompt renders that advice into the prompt. It answers two questions the
IdeaGenerator needs:

  * Which signals are worth *targeting* in the batch's context (market/universe/
    regime)?  -> context-filtered leaderboard.
  * Which signals *generalise* across contexts vs. are context-bound?  -> global
    roll-up plus lifecycle standing.

It also reserves an **exploration quota**: a fraction of each batch is steered
toward signals with thin or no evidence, so the system keeps probing the space
instead of compounding on whatever looked good first (the overfitting guard from
the approved design's Q5). The advisor never decides anything itself — it hands
the LLM both the exploit list and the explore list and lets a human approve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents.storage.db import DB_PATH
from agents.storage import context_store as cs
from agents.storage import signal_store as ss
from agents.storage import memory_store as ms


@dataclass(frozen=True)
class SignalHint:
    """One signal recommendation, with the evidence behind it."""
    feature_name: str
    contribution_score: float | None
    n_experiments: int
    lifecycle_state: str
    generalization_class: str | None
    note: str


@dataclass
class ContextAdvice:
    """Structured guidance for one idea-generation batch."""
    market: str | None = None
    universe: str | None = None
    regime: str | None = None
    targeted: list[SignalHint] = field(default_factory=list)     # exploit
    generalizers: list[SignalHint] = field(default_factory=list)  # broad winners
    exploration: list[str] = field(default_factory=list)          # under-tested
    memory: list[dict] = field(default_factory=list)
    explore_quota: int = 0


def _hint(feature_name: str, cell: dict | None, sig: dict | None,
          note: str) -> SignalHint:
    return SignalHint(
        feature_name=feature_name,
        contribution_score=(cell or {}).get("contribution_score"),
        n_experiments=(cell or {}).get("n_experiments", 0),
        lifecycle_state=(sig or {}).get("lifecycle_state", "observed"),
        generalization_class=(sig or {}).get("generalization_class"),
        note=note,
    )


def build_context_advice(
    known_signals: list[str],
    *,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    n: int = 3,
    min_n: int = 2,
    top: int = 8,
    explore_fraction: float = 0.34,
    db_path: Path = DB_PATH,
) -> ContextAdvice:
    """Assemble batch guidance from context performance, lifecycle, and memory.

    `known_signals` anchors the explore list so we only ever suggest signals the
    spec validator already accepts (no invented names). The context filters
    (market/universe/regime) scope the *targeted* leaderboard; the *generalizers*
    list is deliberately global so the LLM also sees what works broadly.
    """
    # Exploit: best signals *within* this context, evidence-sufficient first.
    targeted_cells = cs.context_performance(
        market=market, universe=universe, regime=regime,
        min_n=min_n, db_path=db_path)
    sig_cache: dict[str, dict | None] = {}

    def _sig(feat: str) -> dict | None:
        if feat not in sig_cache:
            sig_cache[feat] = ss.get_signal(feat, db_path=db_path)
        return sig_cache[feat]

    targeted: list[SignalHint] = []
    seen_targeted: set[str] = set()
    for c in targeted_cells:
        feat = c["feature_name"]
        if feat in seen_targeted:
            continue
        seen_targeted.add(feat)
        targeted.append(_hint(
            feat, c, _sig(feat),
            note=f"works in {c['market']}/{c['universe']}/{c['regime']}"))
        if len(targeted) >= top:
            break

    # Generalizers: best signals globally (per-signal roll-up across all cells).
    global_rows = cs.roll_up(["feature_name"], db_path=db_path)
    generalizers: list[SignalHint] = []
    for r in global_rows:
        feat = r["feature_name"]
        breadth = cs.distinct_context_count(
            feat, min_n=min_n, threshold=0.0, db_path=db_path)
        if breadth < 2:
            continue  # only signals proven in 2+ contexts count as generalizers
        generalizers.append(_hint(
            feat, r, _sig(feat),
            note=f"generalises across {breadth} contexts"))
        if len(generalizers) >= top:
            break

    # Explore: known signals with the thinnest evidence get priority. This is
    # the exploration quota — we always reserve room for under-tested signals.
    evidence = {
        feat: cs.distinct_context_count(feat, min_n=1, db_path=db_path)
        for feat in known_signals
    }
    exploration = sorted(known_signals, key=lambda f: (evidence.get(f, 0), f))
    explore_quota = max(1, round(n * explore_fraction)) if known_signals else 0

    return ContextAdvice(
        market=market,
        universe=universe,
        regime=regime,
        targeted=targeted,
        generalizers=generalizers,
        exploration=exploration[: max(explore_quota * 2, top)],
        memory=ms.memory_for_idea_generator(db_path=db_path, limit=20),
        explore_quota=explore_quota,
    )
