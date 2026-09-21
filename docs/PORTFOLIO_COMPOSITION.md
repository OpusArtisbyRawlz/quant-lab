# Multi-strategy portfolio composition (general factory capability)

A first-class, additive capability to combine several existing strategy return streams
into one portfolio return stream — without a new engine, agent, scheduler, or recovery
path. Single-strategy execution is unchanged (the portfolio path activates only when a
spec carries a `PortfolioSpec`).

## Abstraction

`src/portfolio/composite.py` — `PortfolioSpec` / `PortfolioChild`:

- `portfolio_id`, `children`, `weights`, `weighting` (`"fixed"` only for now — no optimiser)
- optional **per-child** overlay (`overlay`) and **per-child weight-level** overlay (`weight_overlay`)
- optional **portfolio-level** overlay (applied only *after* child composition)
- `rebalance` convention, effective date range, `provenance`
- deterministic ordering (children composed sorted by `child_id`)
- nested composites (a child may itself be a `PortfolioSpec`)

## Execution model (reuses the existing pipeline)

Children execute through the **normal** cross-sectional pipeline; the portfolio layer
only weights and combines their return streams:

```
run_experiment(spec)                      # single entry point, unchanged for single strategies
  └─ _run_pipeline
       └─ if spec.portfolio: _run_portfolio_pipeline
            for each child (deterministic order):
              leaf:   apply_signal_combo → [weight_overlay] → _portfolio_returns
              nested: recurse
              then [per-child return overlay]
            combine_returns(Σ wᵢ·rᵢ)      # src/portfolio/composite.py
            [portfolio-level overlay]      # src/risk, applied AFTER composition
            metrics (gross; composites are gross — net/turnover recorded null, not faked)
```

No child signal is recomputed in the portfolio layer; leaf books reuse
`apply_signal_combo` / `_portfolio_returns`, and overlays reuse `src/risk`. The composite
enters the same evidence / M11 / Project 07 path as any other evaluated object.

## Historical acceptance test — P05 final weighted multi-strategy portfolio

Reproduced **exactly** through the real factory (`exp_011`), recovered via the normal
campaign (manifest → idea `idea_008` → hypothesis node → approval → experiment → evidence
→ M11 → Project 07 `preliminary`):

| Metric | Notebook (authoritative) | Factory replay | Δ |
| --- | --- | --- | --- |
| Sharpe | **2.09** | **2.0901** | < 1e-3 |
| MDD | **-0.367** | **-0.3669** | < 1e-3 |
| CAGR | **0.377** | **0.3770** | 0 |
| Vol | **0.159** | **0.1592** | < 1e-3 |
| Calmar | **1.026** | **1.0274** | rounding |
| Return-series correlation | — | **1.000** | — |

**Fidelity verdict: VERIFIED (exact).** Source of truth: `01_drawdown_overlay.ipynb`
(cells 62/69/73/77) + `exp_005_risk_engine_final/{config.json, final_project05_summary.csv}`.

### Authoritative construction (ported verbatim)

```
weights = {ls20+sqrt_partial_norm: 0.5, blend_60_40: 0.3, ls30: 0.2}   # config.json
per child:  strategy-level smooth-DD (floor 0.55, k 5) on the child's return
combine:    Σ wᵢ · child_ddᵢ                                            # cell 73
portfolio:  portfolio-level smooth-DD (floor 0.55, k 5) on the combined return  # cell 77
```

Children as factory objects (no stored-CSV shortcuts):
- `ls30` = `hist_p04_ls30_v1` (recovered P04 book)
- `blend_60_40` = nested composite `0.6·hist_p04_ls20_v1 + 0.4·hist_p04_ls30_v1` (exact: the stored `blend_60_40` series equals this return-blend, max abs diff 0)
- `ls20+sqrt_partial_norm` = `hist_p04_ls20_v1` with a **weight-level vol-regime overlay** (`src/risk/weight_overlay.py`): `weight × (0.5 + 0.5·√(1−p_high_vol)_lag1)`, renormalised gross-1, using the **recovered Project 02** OOF `p_high_vol_calibrated` (P04 notebook cells 40/167/172). Reproduces the `1.544` variant exactly.

## Provenance chain

composite `p05_final_portfolio` → children (`ls20+sqrt_partial_norm`, `blend_60_40`,
`ls30`) → recovered P04 signals (`hist_p04_ls20_v1`, `hist_p04_ls30_v1`) + recovered P02
OOF → experiments `exp_007/exp_008` (P04) and the P02 vendored snapshot → historical
notebooks `04_portfolio_research.ipynb`, `01_drawdown_overlay.ipynb`,
`spy_volatility_regime_model.ipynb`.

## Recovery markers

| Object | FOUND | EXECUTABLE | REPLAYED | FIDELITY VERIFIED | M11 | PROJECT07 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| p05_final_portfolio | ✅ | ✅ | ✅ (`exp_011`) | ✅ (2.0901) | ✅ | preliminary |

This composite is now a normal factory object whose return series can serve as the
**Project 06 deployment base** (next PR).
