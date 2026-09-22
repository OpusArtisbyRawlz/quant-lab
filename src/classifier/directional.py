"""
directional.py — single-asset directional classifier (general capability).

Faithfully reproduces Project 03's research semantics (a single-asset SPY N-day
direction classifier), parameterised so it is not a P03-only hack: the asset, feature
set, horizon, model, chronological split and seed all come from the spec. It produces a
probability series P(up) and classification metrics — it never translates classification
performance into synthetic portfolio returns.

Authoritative recipe (research/project_03_directional_alpha/notebooks/03_model_training.ipynb,
cells 4/6/8/10/37): features {ret_5, ret_10, ret_20, ma_dist_20, rv20, volume_ratio},
target = (fwd_ret_N > 0), chronological 80/20 split, models:
  * logistic       — Pipeline(StandardScaler, LogisticRegression(max_iter=1000))
  * random_forest  — RandomForestClassifier(n_estimators=200, max_depth=4, random_state=42)
  * naive_up       — always-predict-up reference baseline
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Feature builders keyed by name (single-asset, causal).
def _build_features(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df["ret_1d"] = df["close"].pct_change()
    df[f"fwd_ret_{horizon}"] = df["close"].shift(-horizon) / df["close"] - 1
    df["target"] = (df[f"fwd_ret_{horizon}"] > 0).astype(int)
    df["ret_5"] = df["close"].pct_change(5)
    df["ret_10"] = df["close"].pct_change(10)
    df["ret_20"] = df["close"].pct_change(20)
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma_dist_20"] = (df["close"] - df["ma20"]) / df["ma20"]
    df["rv20"] = df["ret_1d"].rolling(20).std()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["vol_ma20"]
    return df


def _fit_predict(model: str, X_train, y_train, X_test) -> np.ndarray:
    if model == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        clf = Pipeline([("scaler", StandardScaler()),
                        ("model", LogisticRegression(max_iter=1000))]).fit(X_train, y_train)
        return clf.predict_proba(X_test)[:, 1]
    if model == "random_forest":
        from sklearn.ensemble import RandomForestClassifier
        clf = RandomForestClassifier(n_estimators=200, max_depth=4,
                                     random_state=42).fit(X_train, y_train)
        return clf.predict_proba(X_test)[:, 1]
    if model == "naive_up":
        return np.ones(len(X_test), dtype=float)   # always-up reference
    raise ValueError(f"Unknown classifier model: {model!r}")


def run_directional_classifier(
    csv_path: Path, *, features: list[str], horizon: int = 5,
    model: str = "logistic", split_fraction: float = 0.8, dayfirst: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run one single-asset directional classifier. Returns (predictions, metrics).

    ``predictions`` has index Date and columns [prob, target, fwd_ret_N] for the
    out-of-sample (chronological) test segment. ``metrics`` carries the classification
    battery (roc_auc, accuracy, brier, log_loss, precision, recall, confusion matrix,
    prevalence, baseline accuracy, n_train, n_test).
    """
    from sklearn.metrics import (accuracy_score, roc_auc_score, brier_score_loss,
                                  log_loss, precision_score, recall_score,
                                  confusion_matrix)
    df = pd.read_csv(csv_path, parse_dates=["Date"], dayfirst=dayfirst).set_index("Date")
    df = _build_features(df, horizon)
    dm = df.dropna(subset=features + ["target"]).copy()
    X, y = dm[features], dm["target"]
    split_idx = int(len(dm) * split_fraction)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    prob = _fit_predict(model, X_train, y_train, X_test)
    pred = (prob >= 0.5).astype(int)
    yt = y_test.to_numpy()
    baseline_acc = float(accuracy_score(yt, np.ones(len(yt), dtype=int)))

    # AUC/brier/log_loss are undefined for the constant naive baseline.
    constant = len(np.unique(prob)) == 1
    tn, fp, fn, tp = confusion_matrix(yt, pred, labels=[0, 1]).ravel()
    metrics: dict[str, Any] = {
        "model": model,
        "roc_auc": None if constant else float(roc_auc_score(yt, prob)),
        "auc": None if constant else float(roc_auc_score(yt, prob)),
        "accuracy": float(accuracy_score(yt, pred)),
        "precision": float(precision_score(yt, pred, zero_division=0)),
        "recall": float(recall_score(yt, pred, zero_division=0)),
        "brier": None if constant else float(brier_score_loss(yt, prob)),
        "log_loss": None if constant else float(log_loss(yt, np.clip(prob, 1e-15, 1 - 1e-15))),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "prevalence": float(y_test.mean()),
        "baseline_accuracy_up": baseline_acc,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }
    preds = pd.DataFrame(
        {"prob": prob, "target": yt, f"fwd_ret_{horizon}": dm.iloc[split_idx:][f"fwd_ret_{horizon}"].to_numpy()},
        index=dm.index[split_idx:],
    )
    return preds, metrics
