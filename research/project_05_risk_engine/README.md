# Project 05 — Drawdown-Aware Risk Engine

## Overview

This project develops a portfolio-level risk overlay that dynamically adjusts exposure based on drawdown. The objective is to improve risk-adjusted performance while preserving the underlying alpha generated from earlier strategy development.

The system applies a smooth drawdown-based exposure function and uses a structured, database-backed experimentation framework to identify optimal parameters.

---

## Methodology

The workflow consists of three key components:

### 1. Base Portfolio Construction
- Multi-strategy portfolio built from Project 04 outputs
- Weighted combination of long-short strategies
- Produces baseline return series (`multi_ret`) and equity curve (`multi_eq`)

---

### 2. Drawdown-Based Exposure Control

- Compute running drawdown from the equity curve:
- Apply a smooth exposure function:
- Key parameters:
- `k` → sensitivity to drawdown (higher = smoother response)
- `floor` → minimum exposure level

- Exposure is lagged by one period to avoid look-ahead bias
- Portfolio returns are scaled using the exposure series

---

### 3. Parameter Optimization (SQL-backed)

- Grid search performed over:
- `k ∈ {2, 3, 4, 5, 6}`
- `floor ∈ {0.50, 0.55, 0.60, 0.65, 0.70}`

- Each experiment:
- Runs the risk overlay
- Computes performance metrics
- Stores results in a SQLite database (`risk_parameter_experiments`)

- Best parameters selected based on Calmar ratio:

```sql
SELECT k, floor
FROM risk_parameter_experiments
ORDER BY calmar DESC
LIMIT 1

Key Findings

* The drawdown-based overlay significantly improves risk-adjusted performance
* Maximum drawdown reduced by ~28%
* Volatility reduced with minimal impact on CAGR
* Calmar ratio improved by ~35%

Observations:

* Higher smoothing (k ≈ 6) performs better → avoids overreacting to drawdowns
* Lower floor (≈ 0.50) performs better → excessive exposure restriction hurts returns
* Optimal configuration suggests light-touch risk control

⸻

Interpretation

The results indicate that:

* The underlying alpha is robust
* Aggressive risk management reduces performance
* Smooth, gradual exposure adjustments preserve returns while controlling downside risk

The consistency between SQL parameter optimization and final portfolio results validates the reliability of the research pipeline.
  