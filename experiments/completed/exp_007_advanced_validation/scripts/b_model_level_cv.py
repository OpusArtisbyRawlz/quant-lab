"""Stage B — MODEL-LEVEL purged/embargoed CV + CPCV on the Project-04 forecasting object.

Object: supervised panel data/processed/project_04_features_v2.csv — 13 features -> label fwd_ret_5
(forward 5-trading-day return, an OVERLAPPING label: obs at date d uses d+1..d+5). This is the
canonical object for purging. We validate a REPRESENTATIVE linear forecaster (ridge, closed-form)
— explicitly NOT a byte-for-byte copy of P04's production model; the purpose is to (a) exercise the
purge/embargo machinery on a genuine overlapping-label problem and (b) measure how much apparent
skill is leakage vs generalisation. Skill metric = pooled OOS rank IC (Spearman).

Purging is at the DATE level (unit of observation = trading date; tickers pooled cross-sectionally),
horizon = 5 dates, with embargo sensitivity. CPCV gives a distribution of OOS IC across paths.

Outputs: data/model_cv_*.csv ; this is a research generalisation test (not a live-trading replica).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[4]
import sys; sys.path.insert(0, str(ROOT))
from src.statistics.cross_validation import PurgedKFold, cpcv_splits

NEW = Path(__file__).resolve().parents[1]
FEAT = ROOT / "data/processed/project_04_features_v2.csv"
LABEL = "fwd_ret_5"
HORIZON = 5
RIDGE_ALPHA = 10.0
SEED = 20261028


def load():
    df = pd.read_csv(FEAT, parse_dates=["Date"]).dropna().sort_values(["Date", "Ticker"]).reset_index(drop=True)
    feats = [c for c in df.columns if c not in ("Date", "Ticker", LABEL)]
    # standardise features once (demonstration forecaster; cross-sectional ranks would be an
    # alternative — kept simple & deterministic). Winsorise label lightly for ridge stability.
    X = df[feats].to_numpy(float)
    X = (X - X.mean(0)) / (X.std(0) + 1e-12)
    y = df[LABEL].to_numpy(float)
    dates = df["Date"].to_numpy()
    return df, X, y, dates, feats


def ridge_fit_predict(Xtr, ytr, Xte, alpha):
    # closed-form ridge with intercept (center y, no penalty on intercept)
    mu = ytr.mean()
    yc = ytr - mu
    p = Xtr.shape[1]
    A = Xtr.T @ Xtr + alpha * np.eye(p)
    w = np.linalg.solve(A, Xtr.T @ yc)
    return Xte @ w + mu


def date_folds(dates, n_splits, embargo_dates):
    uniq = np.array(sorted(pd.unique(dates)))
    nd = len(uniq)
    folds = list(PurgedKFold(n_splits, embargo=embargo_dates).split(nd, horizon=HORIZON))
    date_pos = {d: i for i, d in enumerate(uniq)}
    row_pos = np.array([date_pos[d] for d in dates])
    out = []
    for f in folds:
        test_mask = np.isin(row_pos, f.test)
        train_mask = np.isin(row_pos, f.train)
        out.append((train_mask, test_mask, len(f.test), f.n_purged, f.n_embargoed, nd))
    return out, uniq


def main():
    df, X, y, dates, feats = load()
    print(f"panel: {len(df)} rows, {len(feats)} features, label={LABEL} (horizon {HORIZON}), "
          f"{pd.unique(dates).size} dates")

    # ---- B2/B3: purged K-fold with embargo sensitivity, vs a LEAKY (non-purged) baseline ----
    rows = []
    for embargo in [0, 5, 10, 21]:
        folds, uniq = date_folds(dates, n_splits=6, embargo_dates=embargo)
        ics, purged, emb = [], [], []
        for (tr, te, ntest, npur, nemb, nd) in folds:
            pred = ridge_fit_predict(X[tr], y[tr], X[te], RIDGE_ALPHA)
            ic = spearmanr(pred, y[te]).statistic
            ics.append(ic); purged.append(npur); emb.append(nemb)
        rows.append({"scheme": f"purged_embargo_{embargo}", "n_splits": 6,
                     "mean_OOS_IC": float(np.mean(ics)), "std_OOS_IC": float(np.std(ics)),
                     "min_OOS_IC": float(np.min(ics)), "max_OOS_IC": float(np.max(ics)),
                     "mean_dates_purged_per_fold": float(np.mean(purged)),
                     "mean_dates_embargoed_per_fold": float(np.mean(emb))})
    # leaky baseline: plain K-fold on rows (no purge, no embargo, shuffled) to size the leakage
    rng = np.random.default_rng(SEED)
    idx = rng.permutation(len(df)); k = 6
    leak_ics = []
    for f in range(k):
        te = idx[f * len(df) // k:(f + 1) * len(df) // k]; tr = np.setdiff1d(idx, te)
        pred = ridge_fit_predict(X[tr], y[tr], X[te], RIDGE_ALPHA)
        leak_ics.append(spearmanr(pred, y[te]).statistic)
    rows.append({"scheme": "shuffled_kfold_LEAKY", "n_splits": 6,
                 "mean_OOS_IC": float(np.mean(leak_ics)), "std_OOS_IC": float(np.std(leak_ics)),
                 "min_OOS_IC": float(np.min(leak_ics)), "max_OOS_IC": float(np.max(leak_ics)),
                 "mean_dates_purged_per_fold": 0.0, "mean_dates_embargoed_per_fold": 0.0})
    kfold_tbl = pd.DataFrame(rows)
    kfold_tbl.to_csv(NEW / "data/model_cv_purged_kfold.csv", index=False)
    print("\n=== B2/B3 purged K-fold (OOS rank IC), embargo sensitivity + leaky baseline ===")
    print(kfold_tbl.round(4).to_string(index=False))

    # ---- B4: CPCV distribution of OOS IC across combinatorial paths ----
    uniq = np.array(sorted(pd.unique(dates)))
    nd = len(uniq)
    N_GROUPS, K_TEST, EMB = 8, 2, 5
    splits = cpcv_splits(nd, N_GROUPS, K_TEST, horizon=HORIZON, embargo=EMB)
    date_pos = {d: i for i, d in enumerate(uniq)}
    row_pos = np.array([date_pos[d] for d in dates])
    cpcv_ics, purged = [], []
    for s in splits:
        tr = np.isin(row_pos, s.train); te = np.isin(row_pos, s.test)
        pred = ridge_fit_predict(X[tr], y[tr], X[te], RIDGE_ALPHA)
        cpcv_ics.append(spearmanr(pred, y[te]).statistic); purged.append(s.n_purged)
    cpcv_ics = np.array(cpcv_ics)
    from math import comb
    cpcv_tbl = pd.DataFrame([{
        "n_groups": N_GROUPS, "k_test": K_TEST, "n_paths": len(splits),
        "C(N,k)": comb(N_GROUPS, K_TEST), "embargo_dates": EMB,
        "mean_dates_purged_per_split": float(np.mean(purged)),
        "mean_OOS_IC": float(cpcv_ics.mean()), "std_OOS_IC": float(cpcv_ics.std()),
        "p05_OOS_IC": float(np.percentile(cpcv_ics, 5)), "median_OOS_IC": float(np.median(cpcv_ics)),
        "p95_OOS_IC": float(np.percentile(cpcv_ics, 95)),
        "frac_paths_IC_positive": float(np.mean(cpcv_ics > 0))}])
    cpcv_tbl.to_csv(NEW / "data/model_cv_cpcv.csv", index=False)
    print("\n=== B4 model-level CPCV (OOS IC across paths) ===")
    print(cpcv_tbl.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
