import pandas as pd


def build_market_panel(data_dict: dict) -> pd.DataFrame:
    frames = []

    for ticker, df in data_dict.items():
        temp = df.copy()

        temp["Date"] = temp.index
        temp["ticker"] = ticker

        frames.append(temp)

    panel = pd.concat(frames)

    panel = panel.reset_index(drop=True).sort_values(["Date", "ticker"])

    panel = panel[
        [
            "Date",
            "ticker",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]
    ]

    return panel
