import numpy as np
import pandas as pd


def equal_weight_long_short(
    signal: pd.Series,
    long_quantile: float = 0.2,
    short_quantile: float = 0.2,
    dynamic_cap: pd.Series = None,
    max_weight: float = None,
    cap_mode: str = "static"
) -> pd.Series:
    """
    Build equal-weight long/short weights from a cross-sectional signal
    for a single date.

    Positive weights = longs
    Negative weights = shorts
    Gross exposure = 1.0
    """
    signal = pd.Series(signal).dropna()

    if signal.empty:
        return pd.Series(dtype=float)

    long_cut = signal.quantile(1 - long_quantile)
    short_cut = signal.quantile(short_quantile)

    long_mask = signal >= long_cut
    short_mask = signal <= short_cut

    n_long = long_mask.sum()
    n_short = short_mask.sum()

    weights = pd.Series(0.0, index=signal.index)

    if n_long > 0:
        weights.loc[long_mask] = 0.5 / n_long

    if n_short > 0:
        weights.loc[short_mask] = -0.5 / n_short

    if dynamic_cap is not None or max_weight is not None:

        cap = None

        if cap_mode == "static":
            if max_weight is not None:
                cap = pd.Series(max_weight, index=weights.index)

        elif cap_mode == "override":
            if dynamic_cap is not None:
                cap = dynamic_cap.reindex(weights.index)

        elif cap_mode == "effective":
            if dynamic_cap is not None and max_weight is not None:
                cap = np.minimum(
                    dynamic_cap.reindex(weights.index),
                    max_weight
                )
            elif dynamic_cap is not None:
                cap = dynamic_cap.reindex(weights.index)
            elif max_weight is not None:
                cap = pd.Series(max_weight, index=weights.index)

        # --- apply clipping ---
        if cap is not None:
            weights = weights.clip(lower=-cap, upper=cap)

            # --- renormalize to keep gross = 1 ---
            gross = weights.abs().sum()
            if gross > 0:
                weights = weights / gross

    

    return weights



def signal_weight_long_short(
        signal:pd.Series,
        long_quantile: float = 0.2,
        short_quantile: float = 0.2,
        max_weight: float | None = None,
        dynamic_cap: pd.Series | None = None,
        cap_mode: str = "effective",
        ) -> pd.Series:
     """
    Build signal-weighted long/short weights from a cross-sectional signal
    for a single date.

    Positive weights = longs
    Negative weights = shorts
    Gross exposure = 1.0

    Weights are proportional to signal strength within the selected
    long and short buckets.
    """
     
     signal = pd.Series(signal).dropna()

     if signal.empty:
         return pd.Series(dtype=float)
     
     long_cut = signal.quantile(1-long_quantile)
     short_cut = signal.quantile(short_quantile)

     long_signal = signal.loc[signal >= long_cut].copy()
     short_signal = signal.loc[signal <= short_cut].copy()

     weights = pd.Series(0.0, index=signal.index)

     # Long signal: positive weights proportional to signal
     if not long_signal.empty:
         long_denom = long_signal.abs().sum()

         if long_denom > 0:
             long_weights = 0.5 * (long_signal / long_denom)

             cap = None

             if cap_mode == "effective":
                 if dynamic_cap is not None and max_weight is not None:
                     dyn = dynamic_cap.reindex(long_signal.index)
                     cap = np.minimum(dyn, max_weight).astype(float)

                 elif dynamic_cap is not None:
                     cap = dynamic_cap.reindex(long_signal.index).astype(float)

                 elif max_weight is not None:
                     cap = pd.Series(max_weight, index=long_signal.index).astype(float)

             elif cap_mode == "override":
                 if dynamic_cap is not None:
                     cap = dynamic_cap.reindex(long_signal.index).astype(float)

             elif cap_mode == "static":
                 if max_weight is not None:
                     cap = pd.Series(max_weight, index=long_signal.index).astype(float)

             else:
                 raise ValueError("cap_mode must be 'effective', 'override', or 'static'")
             

             # Apply cap if it exists
             if cap is not None:
                 long_weights = np.minimum(long_weights, cap)

                 if long_weights.sum() > 0:
                     long_weights = long_weights * (0.5 / long_weights.sum())



             weights.loc[long_signal.index] = long_weights





     # Short Signal: negative weights proportional to absolute signal strength
     if not short_signal.empty:
         short_strength = short_signal.abs()
         short_denom = short_strength.sum()
         if short_denom > 0:
             short_weights = 0.5 * short_strength / short_denom
              
             #Apply caps
             cap = None

             if cap_mode == "effective":
                 if dynamic_cap is not None and max_weight is not None:
                     dyn = dynamic_cap.reindex(short_signal.index)
                     cap = np.minimum(dyn, max_weight).astype(float)

                 elif dynamic_cap is not None:
                     cap = dynamic_cap.reindex(short_signal.index).astype(float)

                 elif max_weight is not None:
                     cap = pd.Series(max_weight, index=short_signal.index).astype(float)

             elif cap_mode == "override":
                 if dynamic_cap is not None:
                     cap = dynamic_cap.reindex(short_signal.index).astype(float)

             elif cap_mode == "static":
                 if max_weight is not None:
                     cap = pd.Series(max_weight, index=short_signal.index).astype(float)

             else:
                 raise ValueError("cap_mode must be 'effective', 'override', or 'static'")
             
             if cap is not None:
                 short_weights = np.minimum(short_weights, cap)

             # Optional renormalization after cap
                 if short_weights.sum() > 0:
                   short_weights = short_weights * (0.5 / short_weights.sum())

             short_weights = -short_weights
             weights.loc[short_signal.index] = short_weights

    


     return weights


def build_daily_weights_from_panel(
    df: pd.DataFrame,
    signal_col: str,
    date_col: str = "Date",
    asset_col: str = "Ticker",
    long_quantile: float = 0.2,
    short_quantile: float = 0.2,
    method: str = "equal",
    max_weight: float | None = None,
    dynamic_cap_col: str = None,
    cap_mode: str = "effective"
) -> pd.DataFrame:
    """
    Build daily cross-sectional weights from a panel dataframe.

    Parameters
    ----------
    method : str
        "equal"  -> equal-weight long/short
        "signal" -> signal-weighted long/short

    Returns
    -------
    pd.DataFrame
        Columns: [date_col, asset_col, weight]
    """
    out = []

    for date, grp in df.groupby(date_col):
        signal = grp.set_index(asset_col)[signal_col]

        if dynamic_cap_col is not None:
          dynamic_cap = grp.set_index(asset_col)[dynamic_cap_col].reindex(signal.index)
        else:
          dynamic_cap = None

        if method == "equal":
            weights = equal_weight_long_short(
                signal,
                long_quantile=long_quantile,
                short_quantile=short_quantile,
                max_weight=max_weight,
                dynamic_cap=dynamic_cap,
                cap_mode=cap_mode
            )
        elif method == "signal":
            weights = signal_weight_long_short(
                signal,
                long_quantile=long_quantile,
                short_quantile=short_quantile,
                max_weight=max_weight,
                dynamic_cap=dynamic_cap,
                cap_mode=cap_mode
            )
        else:
            raise ValueError("method must be either 'equal' or 'signal'")

        temp = weights.rename("weight").reset_index()
        temp[date_col] = date
        out.append(temp)

    if not out:
        return pd.DataFrame(columns=[date_col, asset_col, "weight"])

    result = pd.concat(out, ignore_index=True)
    return result[[date_col, asset_col, "weight"]]