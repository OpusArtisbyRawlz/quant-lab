"""
Versioned historical signal library.

Ports each historical project's ORIGINAL portfolio construction into the factory's
signal registry — faithfully and versioned — so recovered strategies execute through
the existing cross-sectional pipeline without inventing substitutes or changing
strategy definitions. Each historical signal reproduces the project's own
authoritative construction (recovered from the original notebook), not a re-derived
approximation.

Registered historical signals (name → project):
    hist_p04_ls20_v1  → Project 04 authoritative LS20 book (combined_signal, rank 0.80/0.20)
    hist_p04_ls30_v1  → Project 04 authoritative LS30 book (combined_signal, rank 0.70/0.30)
"""

from .p04_return_forecast import (
    LS20_SIGNAL_NAME as P04_LS20_V1,
    LS30_SIGNAL_NAME as P04_LS30_V1,
    p04_ls20_series,
    p04_ls30_series,
)

# name -> callable(panel) -> pd.Series aligned to panel.index
HISTORICAL_SIGNALS = {
    P04_LS20_V1: p04_ls20_series,
    P04_LS30_V1: p04_ls30_series,
}

__all__ = [
    "HISTORICAL_SIGNALS",
    "P04_LS20_V1",
    "P04_LS30_V1",
    "p04_ls20_series",
    "p04_ls30_series",
]
