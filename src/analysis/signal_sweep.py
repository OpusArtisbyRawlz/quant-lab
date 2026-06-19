from itertools import combinations

import pandas as pd

from src.pipelines.cross_sectional import run_market_alpha_pipeline
from src.signals.combine import apply_signal_combo


def run_signal_combo_sweep(
    market_data,
    signal_universe,
    evaluate_func,
    holding_days=5,
    cost_levels=None,
    combo_sizes=(1, 2, 3),
):
    if cost_levels is None:
        cost_levels = [0.0005]

    base_panel = run_market_alpha_pipeline(market_data)

    combo_results = []

    for combo_size in combo_sizes:
        for combo in combinations(signal_universe, combo_size):

            test_panel = apply_signal_combo(
                base_panel,
                signal_names=list(combo),
            )

            result = evaluate_func(
                test_panel,
                holding_days=holding_days,
                cost_levels=cost_levels,
            )

            result["Signal Combo"] = " + ".join(combo)
            result["Combo Size"] = combo_size

            combo_results.append(result)

    return pd.concat(combo_results, ignore_index=True)
