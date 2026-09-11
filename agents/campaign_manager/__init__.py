"""campaign_manager — Milestone 10 research-campaign lifecycle agent."""

from .manager import (
    CampaignManager,
    CampaignError,
    PortfolioError,
    TransitionResult,
    is_legal_transition,
    is_legal_portfolio_transition,
    TRIGGER_MANUAL,
    TRIGGER_DEPENDENCY,
    TRIGGER_SCHEDULE,
    TRIGGER_EVENT,
    REPEAT_ONCE,
    REPEAT_INTERVAL,
    REPEAT_UNTIL,
)

__all__ = [
    "CampaignManager",
    "CampaignError",
    "PortfolioError",
    "TransitionResult",
    "is_legal_transition",
    "is_legal_portfolio_transition",
    "TRIGGER_MANUAL",
    "TRIGGER_DEPENDENCY",
    "TRIGGER_SCHEDULE",
    "TRIGGER_EVENT",
    "REPEAT_ONCE",
    "REPEAT_INTERVAL",
    "REPEAT_UNTIL",
]
