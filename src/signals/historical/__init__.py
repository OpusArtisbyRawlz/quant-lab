"""
Versioned historical signal library.

Ports each historical project's ORIGINAL signal output into the factory's signal
registry — faithfully and versioned — so recovered strategies execute through the
existing cross-sectional pipeline without inventing substitutes or changing strategy
definitions. Each historical signal returns the project's own precomputed
out-of-fold output (the authoritative historical artifact), not a re-derived
approximation.

Registered historical signals (name → project):
    hist_p04_return_forecast_v1  → Project 04 ML 5-day return forecast (data/processed/v1.csv)
"""

from .p04_return_forecast import (
    SIGNAL_NAME as P04_RETURN_FORECAST_V1,
    p04_return_forecast_series,
)

# name -> callable(panel) -> pd.Series aligned to panel.index
HISTORICAL_SIGNALS = {
    P04_RETURN_FORECAST_V1: p04_return_forecast_series,
}

__all__ = [
    "HISTORICAL_SIGNALS",
    "P04_RETURN_FORECAST_V1",
    "p04_return_forecast_series",
]
