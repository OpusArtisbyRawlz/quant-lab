# Project 06 — Deployment Validation

Deployment-readiness validation for the Project 05 risk-engine final portfolio.
Where earlier projects **build** and **risk-manage** a strategy, Project 06 asks
the deployment question: **does this strategy survive real-world implementation
frictions — transaction costs, turnover, rebalancing cadence, liquidity, market
impact, and finite capacity — and at what capital scale?**

> **Scope note.** This project validates *deployment economics*. It does **not**
> perform statistical-significance testing (multiple-testing correction, deflated
> Sharpe, bootstrap/Monte-Carlo confidence intervals, reality-check / SPA). That
> inferential layer is **Project 07 (Statistical Integrity)** and is deliberately
> out of scope here.

---

## 1. Purpose

Take a strategy that already looks good on paper (the Project 05 final weighted
multi-strategy portfolio) and determine whether it is **deployable**:

- How much of the gross edge survives realistic transaction costs?
- How does performance trade off against rebalance frequency and turnover?
- What is the capacity ceiling under a real liquidity / market-impact model?
- How robust is the strategy to operational frictions (missed rebalances,
  execution delay, cost shocks)?
- Are the headline deployment metrics **reproducible and regression-locked** so
  future code changes cannot silently move them?

---

## 2. Architecture overview

The analytics live in reusable, unit-tested library modules under `src/analysis/`.
Notebooks are thin drivers: they load a strategy's `returns` / `weights` /
`equity`, call the library, and render decision tables. The **golden-master
regression test** re-runs the full battery on the reference strategy and asserts
the key metrics against a committed baseline.

```
strategy outputs (returns, weights, equity)
        │
        ▼
src/analysis/  ── deployment.py         (validation battery + decision grids)
                  deployment_stress.py  (capacity + operational stress)
                  liquidity.py          (dollar-vol → ADV → participation → impact → capacity)
                  turnover.py           (turnover / rolling / spikes / summary)
                  robustness.py         (rebalance × cost grid per market)
                  regimes.py, rolling.py, signal_sweep.py (supporting analytics)
        │
        ▼
notebooks/     ── 05, 08, 09, 10  (supporting studies)
                  11_deployment_report.ipynb  ◄── primary deliverable
        │
        ▼
results/       ── us_deployment_*.csv (+ decision pivots)   [gitignored outputs]
                  deployment_reference_metrics.json          [tracked golden baseline]
        │
        ▼
tests/         ── deployment_reference.py       (golden generator)
                  test_deployment_regression.py (8 golden-master assertions)
```

---

## 3. Directory layout

```
research/project_06_deployment_validation/
├── README.md                         ← this file
├── notebooks/
│   ├── 05_robustness_checks.ipynb
│   ├── 08_transaction_cost_stress.ipynb
│   ├── 09_rebalance_frequency.ipynb
│   ├── 10_rebalance_transaction_costs.ipynb
│   ├── 11_deployment_report.ipynb    ← primary deliverable
│   └── archive/
│       └── 11_deployment_validation.ipynb   (superseded v1 of NB 11)
├── results/
│   ├── deployment_reference_metrics.json    (tracked golden baseline)
│   └── us_deployment_*.csv, *decision*.csv  (generated; gitignored)
└── tests/
    ├── deployment_reference.py
    └── test_deployment_regression.py
```

Analytics modules live outside the project, in `src/analysis/` (importable and
reused across the repo).

---

## 4. Notebooks

| Notebook | Purpose | Key outputs |
| --- | --- | --- |
| `05_robustness_checks.ipynb` | Robustness / overfitting checks on the Project 05 drawdown-overlay: parameter sensitivity (k, clip ranges, DD floor, rolling windows), component ablation (drawdown-only vs vol-only vs combined), subperiod and crisis-regime isolation (COVID, 2022 bear, 2025 low-vol), and cross-universe portability (LS20). | inline tables / narrative |
| `08_transaction_cost_stress.ipynb` | Sweep one-way transaction costs `[0,2,5,10,20,50]` bps across India / Brazil / Japan on the daily-rebalance stack. | `results/*cost*` |
| `09_rebalance_frequency.ipynb` | Turnover vs. performance as a function of rebalance cadence. | `results/rebalance_frequency_results.csv` |
| `10_rebalance_transaction_costs.ipynb` | Joint **rebalance-frequency × transaction-cost** decision grid; best cadence per cost level per market. | `results/best_rebalance_by_transaction_cost.csv`, `deployment_rebalance_summary.csv` |
| `11_deployment_report.ipynb` | **Primary deliverable.** Full deployment validation of the US Project 05 final portfolio: validation battery, turnover profile, cost stress on the deployed weight path, rebalance analysis, decision pivot, capacity under the real liquidity model, rolling turnover, rolling cost drag, and operational stress tests. | `results/us_deployment_*.csv` |

`archive/11_deployment_validation.ipynb` is the earlier, narrower version of the
report, retained for provenance.

---

## 5. `src/analysis/` modules

| Module | Responsibility |
| --- | --- |
| `deployment.py` | `run_deployment_validation` orchestrator; `transaction_cost_stress`, `rebalance_analysis`, `rebalance_cost_grid`; decision helpers `select_best_per_group`, `pivot_metric_table`. |
| `deployment_stress.py` | `capacity_analysis` across capital levels; `transaction_cost_drag` through time; `operational_stress_tests` (baseline, missed rebalance, execution delay, cost shocks); `skip_every_nth_rebalance`. |
| `liquidity.py` | Real liquidity / market-impact chain: dollar volume → ADV → participation rate → temporary market impact → slippage; `capacity_ceiling` from a participation cap. |
| `turnover.py` | `compute_turnover`, `rolling_turnover`, `rolling_turnover_summary`, `turnover_spikes`, `summarize_turnover`, `build_turnover_report`. |
| `robustness.py` | `run_market_robustness` — the rebalance-frequency × transaction-cost grid for one market. |
| `regimes.py` | `classify_drawdown_regime` and `regime_analysis` — performance conditional on drawdown state. |
| `rolling.py` | `rolling_metrics` — rolling annualised return / volatility / Sharpe. |
| `signal_sweep.py` | Signal-sweep helper used by the cross-market studies. |

---

## 6. Reproduce the deployment report

From the repository root, with the project virtualenv:

```bash
cd research/project_06_deployment_validation/notebooks
PYTHONPATH=../../.. jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=300 11_deployment_report.ipynb
```

Inputs consumed (already committed):

- `experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv`
- `experiments/completed/exp_005_risk_engine_final/final_daily_weights.csv`
- `data/raw/project_04_universe/*.csv` (per-asset OHLCV for the liquidity model)

Outputs are written to `results/` (the `us_deployment_*.csv` set is gitignored;
the golden baseline JSON is tracked).

---

## 7. Regression tests

The headline deployment metrics are locked by a golden-master test at
`RTOL = 1e-9`. It recomputes gross/net Sharpe, CAGR, MDD, Calmar, turnover,
participation, and capacity on the reference strategy and compares them to the
committed baseline.

Run the test:

```bash
PYTHONPATH=. python -m pytest \
  research/project_06_deployment_validation/tests/test_deployment_regression.py -q
```

Regenerate the golden baseline **intentionally** (only when a metric change is
expected and reviewed):

```bash
PYTHONPATH=. python research/project_06_deployment_validation/tests/deployment_reference.py
```

---

## 8. Outputs produced

- `results/deployment_reference_metrics.json` — tracked golden baseline (gross &
  net headline metrics, turnover profile, capacity at $1M / $5M, capacity ceiling).
- `results/us_deployment_*.csv` — turnover summary, cost stress, rebalance,
  best-rebalance-by-cost, decision pivot, capacity estimates & ceiling, rolling
  turnover (summary + spikes), cost-drag (summary / net-equity / cumulative),
  operational stress tests. *(Generated; gitignored.)*
- Cross-market study CSVs (India / Brazil / Japan cost & rebalance grids).

---

## 9. Limitations

- **Single primary strategy.** The deployment report validates one strategy (the
  Project 05 US final portfolio). The cross-market notebooks (08/10) cover
  India/Brazil/Japan but are supporting studies, not the regression-locked path.
- **Deployment approximation.** Operational stress scenarios treat the *gross*
  return series as invariant to execution changes and express frictions through
  turnover and transaction cost; they do not re-simulate fills tick-by-tick.
- **Impact model.** The liquidity/market-impact model is a participation-based
  temporary-impact approximation, not a calibrated live-execution model.
- **No statistical-significance testing.** Robustness conclusions here are
  descriptive (stability across parameters/regimes), not inferential. Formal
  significance — multiple-testing correction, deflated Sharpe, bootstrap/Monte
  Carlo confidence intervals, White's Reality Check / SPA — is **Project 07**.

---

## 10. Relationship to Project 07

Project 06 answers *"is this deployable and at what scale?"* Project 07
(Statistical Integrity) answers *"is the edge statistically real once we account
for how hard we searched?"* The two are complementary: a strategy should clear
**both** the deployment gate (here) and the statistical gate (Project 07) before
it is promoted toward live capital.
