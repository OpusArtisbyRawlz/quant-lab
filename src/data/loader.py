"""
Market data loader.

Moved from research/project_06_failure_analysis/notebooks/07_cross_market_research_engine.ipynb.
Preserves existing download behavior exactly; callers that referenced df["ret"]
should update to df["ret_1"].
"""

import pandas as pd
import yfinance as yf


def download_market_data(config: dict, start: str = "2010-01-01") -> dict[str, pd.DataFrame]:
    """
    Download OHLCV data for every ticker in config["tickers"].

    Parameters
    ----------
    config : dict
        A market config entry from MARKET_CONFIGS, e.g. MARKET_CONFIGS["india"].
        Must contain a "tickers" key.
    start : str
        Start date passed to yf.download (default "2010-01-01").

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of ticker -> DataFrame with columns:
        Open, High, Low, Close, Volume, ticker, ret_1.
        Index is Date (DatetimeIndex, sorted ascending).
        Tickers with empty downloads are skipped with a printed warning.
    """
    data: dict[str, pd.DataFrame] = {}

    for ticker in config["tickers"]:
        df = yf.download(
            ticker,
            start=start,
            auto_adjust=True,
            progress=False,
        )

        if df.empty:
            print(f"Missing data: {ticker}")
            continue

        df = df.reset_index()

        # Flatten MultiIndex columns produced by some yfinance versions
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()

        df["ticker"] = ticker
        df["ret_1"] = df["Close"].pct_change()

        data[ticker] = df

    return data
