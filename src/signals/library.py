def get_signal_series(panel, signal_name):
    if signal_name == "mr_ret_5":
        return -panel["ret_5"]
    elif signal_name == "mr_ret_10":
        return -panel["ret_10"]
    elif signal_name == "mr_ret_20":
        return -panel["ret_20"]
    elif signal_name == "mom_ret_5":
        return panel["ret_5"]
    elif signal_name == "mom_ret_10":
        return panel["ret_10"]
    elif signal_name == "mom_ret_20":
        return panel["ret_20"]
    elif signal_name == "trend_ma_10":
        return panel["ma_10_ratio"]
    elif signal_name == "trend_ma_20":
        return panel["ma_20_ratio"]
    elif signal_name == "low_vol_5":
        return -panel["vol_5"]
    elif signal_name == "low_vol_20":
        return -panel["vol_20"]
    elif signal_name == "mr_blend":
        return (-panel["ret_5"] - panel["ret_10"] - panel["ret_20"]) / 3
    elif signal_name == "mom_blend":
        return (panel["ret_5"] + panel["ret_10"] + panel["ret_20"]) / 3
    elif signal_name == "mr_lowvol_blend":
        return (-panel["ret_5"] - panel["ret_10"] - panel["vol_20"]) / 3
    else:
        raise ValueError(f"Unknown signal_name: {signal_name}")
