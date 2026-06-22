"""
Market configurations for cross-market research.

Each config contains:
  name       — human-readable label
  benchmark  — benchmark index ticker (yfinance symbol)
  tickers    — list of constituent tickers to download

Moved from research/project_06_failure_analysis/notebooks/07_cross_market_research_engine.ipynb.
Do not change tickers or benchmarks without updating the corresponding experiment records.
"""

MARKET_CONFIGS = {
    "india": {
        "name": "India",
        "benchmark": "^NSEI",
        "tickers": [
            "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
            "SBIN.NS", "LT.NS", "ITC.NS", "BHARTIARTL.NS", "AXISBANK.NS",
            "KOTAKBANK.NS", "HINDUNILVR.NS", "MARUTI.NS", "SUNPHARMA.NS",
            "TITAN.NS", "BAJFINANCE.NS", "ASIANPAINT.NS", "ULTRACEMCO.NS",
            "WIPRO.NS", "HCLTECH.NS",
        ],
    },
    "brazil": {
        "name": "Brazil",
        "benchmark": "^BVSP",
        "tickers": [
            "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "ABEV3.SA",
            "B3SA3.SA", "WEGE3.SA", "BBAS3.SA", "RENT3.SA", "LREN3.SA",
            "PRIO3.SA", "SUZB3.SA", "GGBR4.SA", "RADL3.SA", "EQTL3.SA",
        ],
    },
    "japan": {
        "name": "Japan",
        "benchmark": "^N225",
        "tickers": [
            "7203.T", "6758.T", "8306.T", "9984.T", "9432.T",
            "6861.T", "8035.T", "4063.T", "6098.T", "7267.T",
            "7974.T", "8058.T", "6501.T", "8001.T", "4568.T",
            "8316.T", "8766.T", "7741.T", "3382.T", "6954.T",
        ],
    },
}
