import pandas as pd


def standardize_signal(df, signal_col, date_col="Date"):
    """
    Cross-sectional z-score standardization per date.
    """
    df = df.copy()

    df["signal_z"] = df.groupby(date_col)[signal_col].transform(
        lambda x: (x - x.mean()) / x.std()
    )

    return df