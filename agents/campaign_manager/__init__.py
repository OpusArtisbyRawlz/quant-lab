"""campaign_manager — Milestone 10 research-campaign lifecycle agent."""

from .manager import (
    CampaignManager,
    CampaignError,
    TransitionResult,
    is_legal_transition,
)

__all__ = [
    "CampaignManager",
    "CampaignError",
    "TransitionResult",
    "is_legal_transition",
]
