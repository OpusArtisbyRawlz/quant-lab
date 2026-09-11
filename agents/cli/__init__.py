"""quant CLI — a thin terminal interface over the existing Research Factory.

This package is an INTERFACE LAYER only. It adds no research logic, no agents, no
orchestration, no persistence, and no state — every command delegates to the
existing services (CampaignManager, PortfolioPlanner, FactoryRunner, ResearchLoop,
and the reporting read-models). See docs/QUANT_CLI.md.
"""

from .main import main

__all__ = ["main"]
