"""
Versioned historical signal library — Project 04 return-forecast (v1).

Verifies the ported P04 signal is registered in the executor's signal registry and
returns Project 04's authoritative historical forecast (`pred_flipped` from
data/processed/v1.csv) aligned to the panel — a faithful port, no re-derivation.
"""

from __future__ import annotations

import pandas as pd

from agents.experiment_runner.spec_validator import KNOWN_SIGNALS
from src.signals.library import get_signal_series
from src.signals.historical import HISTORICAL_SIGNALS, P04_RETURN_FORECAST_V1
from src.signals.historical import p04_return_forecast as p04


def test_p04_signal_registered_everywhere():
    assert P04_RETURN_FORECAST_V1 == "hist_p04_return_forecast_v1"
    assert P04_RETURN_FORECAST_V1 in KNOWN_SIGNALS          # spec validation
    assert P04_RETURN_FORECAST_V1 in HISTORICAL_SIGNALS     # historical registry


def test_p04_signal_uses_flipped_prediction():
    # Faithful to the project's portfolio construction (signal_v1 = pred_flipped).
    assert p04._FORECAST_COLUMN == "pred_flipped"


def test_get_signal_series_dispatches_to_historical():
    panel = pd.DataFrame({
        "Date": pd.to_datetime(["2016-01-04", "2016-01-04"]),
        "ticker": ["AAPL", "AMZN"],
    })
    s = get_signal_series(panel, P04_RETURN_FORECAST_V1)
    assert list(s.index) == list(panel.index)              # index-aligned
    assert s.notna().all()                                 # covered in-window


def test_forecast_matches_source_artifact():
    src = pd.read_csv(p04.SOURCE_ARTIFACT, parse_dates=["Date"])
    row = src.iloc[0]
    panel = pd.DataFrame({"Date": [row["Date"]], "ticker": [str(row["Ticker"]).upper()]})
    val = get_signal_series(panel, P04_RETURN_FORECAST_V1).iloc[0]
    assert abs(val - float(row["pred_flipped"])) < 1e-12   # verbatim, not approximated


def test_out_of_window_is_nan_not_fabricated():
    panel = pd.DataFrame({"Date": pd.to_datetime(["1990-01-02"]), "ticker": ["AAPL"]})
    s = get_signal_series(panel, P04_RETURN_FORECAST_V1)
    assert s.isna().all()                                  # no fabricated values


def test_unknown_signal_still_raises():
    import pytest
    with pytest.raises(ValueError):
        get_signal_series(pd.DataFrame({"Date": [], "ticker": []}), "does_not_exist")
