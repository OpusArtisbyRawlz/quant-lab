"""campaign_manager — Milestone 10 research-campaign lifecycle agent."""

from .manager import (
    CampaignManager,
    CampaignError,
    PortfolioError,
    TransitionResult,
    is_legal_transition,
    is_legal_portfolio_transition,
)

__all__ = [
    "CampaignManager",
    "CampaignError",
    "PortfolioError",
    "TransitionResult",
    "is_legal_transition",
    "is_legal_portfolio_transition",
]
