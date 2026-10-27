"""Phase 3 — Full-model purged CPCV on the ACTUAL Project 04 OLS pipeline.

Evaluates the real forecasting model under leakage-controlled combinatorial purged CV, with
independent retraining inside every training split and all feature transforms fit train-only.
Compares the actual OLS blend (and its V1-only / V2-only legs) against the representative
ridge(alpha=10) used in the previous campaign.

Panel object: inner-merge of project_04_features.csv (V1 feats) and project_04_features_v2.csv
(V2 feats) on (Date,Ticker); label fwd_ret_5 (5-trading-day forward -> overlapping labels).
Purging/embargo operate on the UNIQUE-DATE axis (label interval [d, d+5] trading days); date
splits map back to panel rows. CPCV: n_groups=8, k_test=2 -> 28 paths. Deterministic (OLS/ridge
closed form; no RNG except none needed).

No parameter is tuned; this is a robustness evaluation, NOT chronological walk-forward.
"""
from __future__ import annotations
import json, os
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import LinearRegression

from src.statistics.cross_validation import cpcv_splits
from src.portfolio.construction import build_daily_weights_from_panel
from src.backtest.engine import backtest_cross_sectional_strategy
from src.utils.metrics import sharpe_ratio, max_drawdown

ROOT = Path("/Users/rawls/quant-lab"); PROC = ROOT / "data/processed"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"
HORIZON = 5
FEAT_V1 = ["ret_1", "ret_5", "ret_10", "ret_20", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]
FEAT_V2 = ["ret_1", "ret_5", "ret_10", "ret_20", "ret_60", "ret_120", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]


def load_panel():
    a = pd.read_csv(PROC / "project_04_features.csv"); a["Date"] = pd.to_datetime(a["Date"])
    b = pd.read_csv(PROC / "project_04_features_v2.csv"); b["Date"] = pd.to_datetime(b["Date"])
    cols1 = ["Date", "Ticker", "fwd_ret_5"] + FEAT_V1
    cols2 = ["Date", "Ticker"] + [c for c in FEAT_V2 if c not in FEAT_V1]
    df = a[cols1].merge(b[cols2], on=["Date", "Ticker"], how="inner")
    df = df.sort_values(["Date", "Ticker"]).dropna().reset_index(drop=True)
    era = os.environ.get("ERA")  # e.g. "2016" restricts to the deployment OOS window
    if era:
        df = df[df["Date"] >= f"{era}-01-01"].reset_index(drop=True)
    return df


def zscore_per_date(df, col, dates):
    g = pd.Series(df[col].values, index=dates)
    return g.groupby(level=0).transform(lambda x: (x - x.mean()) / (x.std() if x.std() > 0 else 1.0)).values


def daily_ic(signal, label, dates, rank=True):
    """Mean per-date IC (Spearman if rank else Pearson)."""
    d = pd.DataFrame({"s": signal, "y": label, "date": dates})
    def _ic(g):
        if g["s"].std() == 0 or g["y"].std() == 0 or len(g) < 3:
            return np.nan
        if rank:
            return g["s"].rank().corr(g["y"].rank())
        return g["s"].corr(g["y"])
    return d.groupby("date").apply(_ic).dropna()


def fit_predict(model, Xtr, ytr, Xte):
    model.fit(Xtr, ytr)
    return model.predict(Xte)


def run_model(df, splits, which, embargo_tag):
    """which in {'combined','v1','v2','ridge'}; returns per-path records + pooled series."""
    dates_all = df["Date"].values
    y = df["fwd_ret_5"].values
    recs = []
    pooled_ic = []
    port_stats = []
    for sp in splits:
        tr_dates = set(uniq[sp.train]); te_dates = set(uniq[sp.test])
        tr = df["Date"].isin(tr_dates).values
        te = df["Date"].isin(te_dates).values
        dte = df.loc[te, "Date"].values
        if which == "combined":
            p1 = fit_predict(LinearRegression(), df.loc[tr, FEAT_V1], y[tr], df.loc[te, FEAT_V1])
            p2 = fit_predict(LinearRegression(), df.loc[tr, FEAT_V2], y[tr], df.loc[te, FEAT_V2])
            sub = pd.DataFrame({"sv1": -p1, "sv2": p2, "date": dte})  # V1 sign-flipped
            sub["z1"] = sub.groupby("date")["sv1"].transform(lambda x: (x - x.mean()) / (x.std() or 1))
            sub["z2"] = sub.groupby("date")["sv2"].transform(lambda x: (x - x.mean()) / (x.std() or 1))
            sig = (sub["z1"] + sub["z2"]).values
        elif which == "v1":
            sig = -fit_predict(LinearRegression(), df.loc[tr, FEAT_V1], y[tr], df.loc[te, FEAT_V1])
        elif which == "v2":
            sig = fit_predict(LinearRegression(), df.loc[tr, FEAT_V2], y[tr], df.loc[te, FEAT_V2])
        elif which == "ridge":
            from sklearn.linear_model import Ridge
            sig = fit_predict(Ridge(alpha=10.0), df.loc[tr, FEAT_V2], y[tr], df.loc[te, FEAT_V2])
        ric = daily_ic(sig, y[te], dte, rank=True)
        pic = daily_ic(sig, y[te], dte, rank=False)
        pooled_ic.append(ric)
        rec = {"combo": "|".join(map(str, sp.combo)), "which": which, "embargo": embargo_tag,
               "n_test_dates": int(len(set(dte))), "n_purged": int(sp.n_purged),
               "n_embargoed": int(sp.n_embargoed),
               "mean_rank_ic": float(ric.mean()), "mean_pearson_ic": float(pic.mean()),
               "ic_std": float(ric.std())}
        # reconstructed OOS LS20 portfolio (only for combined, embargo==5) — labeled reconstruction
        if which == "combined" and embargo_tag == 5:
            pdf = df.loc[te, ["Date", "Ticker", "fwd_ret_5"]].copy()
            pdf["combined_signal"] = sig
            w = build_daily_weights_from_panel(pdf, signal_col="combined_signal")
            port = backtest_cross_sectional_strategy(w, pdf, return_col="fwd_ret_5")
            if len(port) > 20:
                rec["recon_oos_sharpe"] = float(sharpe_ratio(port["portfolio_return"]))
                rec["recon_oos_mdd"] = float(max_drawdown(port["equity_curve"]))
                port_stats.append((rec["recon_oos_sharpe"], rec["recon_oos_mdd"]))
        recs.append(rec)
    allic = pd.concat(pooled_ic)
    per_path = np.array([r["mean_rank_ic"] for r in recs])
    summary = {"which": which, "embargo": embargo_tag, "n_paths": len(recs),
               "pooled_mean_rank_ic": float(allic.mean()), "pooled_median_rank_ic": float(allic.median()),
               "per_path_mean_rank_ic": float(per_path.mean()),
               "per_path_ic_dispersion": float(per_path.std()),
               "frac_paths_positive": float((per_path > 0).mean()),
               "mean_pearson_ic": float(np.mean([r["mean_pearson_ic"] for r in recs]))}
    if port_stats:
        ps = np.array(port_stats)
        summary["recon_oos_sharpe_mean"] = float(ps[:, 0].mean())
        summary["recon_oos_sharpe_frac_pos"] = float((ps[:, 0] > 0).mean())
        summary["recon_oos_mdd_median"] = float(np.median(ps[:, 1]))
    return recs, summary


df = load_panel()
uniq = np.sort(df["Date"].unique())
n = len(uniq)
print(f"panel rows={len(df)} unique_dates={n} tickers={df['Ticker'].nunique()} "
      f"range={pd.Timestamp(uniq[0]).date()}..{pd.Timestamp(uniq[-1]).date()}")

all_recs, all_sum = [], []
# model comparison at embargo=5
splits5 = cpcv_splits(n, n_groups=8, k_test=2, horizon=HORIZON, embargo=5)
for which in ["combined", "v1", "v2", "ridge"]:
    r, s = run_model(df, splits5, which, 5)
    all_recs += r; all_sum.append(s)
    print(f"[embargo5] {which:9s} pooled_rankIC={s['pooled_mean_rank_ic']:.4f} "
          f"per_path={s['per_path_mean_rank_ic']:.4f}±{s['per_path_ic_dispersion']:.4f} "
          f"frac+={s['frac_paths_positive']:.2f}")
# embargo sensitivity for the actual combined model
for emb in [0, 10, 21]:
    sp = cpcv_splits(n, n_groups=8, k_test=2, horizon=HORIZON, embargo=emb)
    r, s = run_model(df, sp, "combined", emb)
    all_recs += r; all_sum.append(s)
    print(f"[embargo{emb:<2d}] combined pooled_rankIC={s['pooled_mean_rank_ic']:.4f} frac+={s['frac_paths_positive']:.2f}")

tag = f"_era{os.environ['ERA']}" if os.environ.get("ERA") else ""
csv_name = f"CPCV_MODEL_RESULTS{tag}.csv"
pd.DataFrame(all_recs).to_csv(OUT / "reports" / csv_name, index=False)
(OUT / f"reports/_p3_cpcv_summary{tag}.json").write_text(json.dumps(all_sum, indent=2))
print(f"wrote {csv_name} (", len(all_recs), "rows )")
