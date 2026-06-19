from src.signals.library import get_signal_series


def apply_signal_combo(
    panel,
    signal_names,
    long_quantile=0.8,
    short_quantile=0.2,
):
    panel = panel.copy()

    signal_parts = []

    for signal_name in signal_names:
        raw_signal = get_signal_series(panel, signal_name)

        ranked_signal = raw_signal.groupby(panel["Date"]).rank(pct=True)

        signal_parts.append(ranked_signal)

    panel["signal"] = sum(signal_parts) / len(signal_parts)

    panel["signal_rank"] = panel.groupby("Date")["signal"].rank(pct=True)

    panel["long"] = panel["signal_rank"] >= long_quantile
    panel["short"] = panel["signal_rank"] <= short_quantile

    panel["weight"] = 0.0
    panel.loc[panel["long"], "weight"] = 1
    panel.loc[panel["short"], "weight"] = -1

    panel["weight"] = panel.groupby("Date")["weight"].transform(
        lambda x: x / x.abs().sum() if x.abs().sum() > 0 else x
    )

    return panel
