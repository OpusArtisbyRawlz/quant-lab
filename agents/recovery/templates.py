"""
Historical Strategy Recovery — campaign templates.

Reusable, deterministic builders for the three recovery campaigns. A template is just
a dict of ``CampaignManager.create_campaign`` kwargs (campaign_type +
scope) — it adds no logic and creates nothing by itself. The CLI (`quant recovery
create`) or an operator passes a template to the existing CampaignManager, which is
the sole writer. Campaigns are created in DRAFT; nothing runs until explicitly
activated and launched.

Three templates, matching the recovery plan:
  - baseline  : recover the historical strategies at their native (time) bars.
  - altbar    : sweep the alt-bar-eligible baselines over time/volume/dollar bars.
  - blend     : recover the blended strategies (e.g. LS20+LS30).
"""

from __future__ import annotations

from typing import Any

from agents.recovery import manifest

TEMPLATE_BASELINE = "baseline"
TEMPLATE_ALTBAR = "altbar"
TEMPLATE_BLEND = "blend"
ALL_TEMPLATES = (TEMPLATE_BASELINE, TEMPLATE_ALTBAR, TEMPLATE_BLEND)

# The alternative-bar clocks swept by the altbar campaign (design: time vs volume vs
# dollar bars). Kept explicit and ordered for determinism.
ALT_BAR_CLOCKS = ["time", "volume", "dollar"]

_HISTORICAL_RECOVERY = "historical_recovery"


def build_template(kind: str) -> dict[str, Any]:
    """Return the create_campaign kwargs for a recovery template. Raises ValueError
    for an unknown template kind."""
    if kind == TEMPLATE_BASELINE:
        return {
            "theme": "Historical Strategy Recovery — baseline (Projects 03-06)",
            "campaign_type": _HISTORICAL_RECOVERY,
            "goal_spec": {"priority": 5},
            "priority": 5.0,
            "scope": {"recovery_kind": manifest.KIND_BASELINE},
        }
    if kind == TEMPLATE_ALTBAR:
        return {
            "theme": "Historical Strategy Recovery — alternative bars (time/volume/dollar)",
            "campaign_type": _HISTORICAL_RECOVERY,
            "goal_spec": {"priority": 4},
            "priority": 4.0,
            "scope": {"recovery_kind": manifest.KIND_BASELINE,
                      "bar_types": list(ALT_BAR_CLOCKS)},
        }
    if kind == TEMPLATE_BLEND:
        return {
            "theme": "Historical Strategy Recovery — blend (LS20+LS30 blends)",
            "campaign_type": _HISTORICAL_RECOVERY,
            "goal_spec": {"priority": 3},
            "priority": 3.0,
            "scope": {"recovery_kind": manifest.KIND_BLEND},
        }
    raise ValueError(f"unknown recovery template: {kind!r} (expected one of "
                     f"{ALL_TEMPLATES})")


def expected_strategy_ids(kind: str) -> list[str]:
    """The strategy_ids a template's campaign would enumerate — the pre-launch
    'what will this recover?' answer, derived purely from the manifest."""
    if kind in (TEMPLATE_BASELINE, TEMPLATE_ALTBAR):
        strategies = manifest.strategies_for_kind(manifest.KIND_BASELINE)
    elif kind == TEMPLATE_BLEND:
        strategies = manifest.strategies_for_kind(manifest.KIND_BLEND)
    else:
        raise ValueError(f"unknown recovery template: {kind!r}")
    return [s["strategy_id"] for s in strategies]
