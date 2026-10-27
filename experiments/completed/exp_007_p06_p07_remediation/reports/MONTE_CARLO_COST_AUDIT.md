# MONTE CARLO COST AUDIT — Dynamic Replay on the Corrected Base

**Experiment:** `exp_007_p06_p07_remediation` · Phase 5 · data: `data/mc_cost_aware_A.csv`,
`exp_007_nb03_dynamic_replay/*` (rerun), `exp_007_garch_volatility_persistence/overlay_replay_A_vs_B.csv`

---

## 1. Methodology (preserved)
The dynamic-replay experiment `exp_007_nb03_dynamic_replay` was **re-run with its logic unchanged** on the
corrected inputs. Method A rebuilds the pre-overlay base `port_pre` from the three Project-04 raw strategies
(shared-index stationary block bootstrap, block 20, N=10,000, seed 20261027), then **recomputes every
exposure layer from the simulated states** (strategy-level smooth-DD ×3 → weight → portfolio overlay),
applying exposure with the 1-day execution lag. Method B directly resamples the shipped risk-controlled
gross series. Method A never uses the defective recovery (it reconstructs from source), so its *logic* was
already canonical — only its fidelity check and Method B consumed the corrected candidate series.

## 2. The reconstruction fidelity test now passes (Phase-5 precondition)
The replay's STEP-2 fidelity check compares its canonical reconstruction against the candidate gross series.
This is where the defect had surfaced inside the replay itself:

| candidate | OLD max\|diff\| vs shipped gross | OLD recon CAGR vs shipped | NEW max\|diff\| | NEW recon vs shipped |
|---|---:|---|---:|---|
| V1 | 6.9e-16 | 0.3770 / 0.3770 | 6.9e-16 | 0.3770 / 0.3770 |
| DD Only | **0.0167** | 0.3721 / **0.4071** | **5.5e-16** | 0.3721 / 0.3721 |
| Combined | 0.0162 | 0.3853 / 0.4256 | **0.0112** (warm-up only) | 0.3853 / 0.3874 |

V1 and DD Only now reconcile to machine precision. **Combined's residual (0.0112) is confined entirely to
the first 252 days** (indices 2–250) — a pre-window **vol-multiplier warm-up convention** difference
between the NB03 `simulation` module (pre-window multiplier = 1.0, DD-smooth still applied) and the
tournament `vol_multiplier` (pre-window NaN → the *combined* exposure filled to 1.0 after the clip). It is
**not** the lineage defect (DD Only has no vol term and reconciles exactly) and is immaterial after year 1.
Per the mandate it is **reported, not forced**; Combined's Method-A path stats are therefore **PROVISIONAL**.

## 3. Gross path distributions (Method A, corrected, block 20)

| candidate | median MDD | p5 MDD (worst) | P(MDD<−20%) | P(MDD<−30%) | median CAGR | median Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| V1 | −0.346 | −0.481 | 0.999 | **0.783** | 0.356 | 2.01 |
| DD Only | **−0.286** | −0.379 | 0.992 | **0.378** | 0.348 | 2.13 |
| Combined | −0.306 | −0.437 | 0.993 | 0.539 | 0.358 | 2.10 |

DD Only roughly **halves** the simulated probability of a >30% drawdown vs V1 (0.38 vs 0.78). Method B
(direct resample) is consistently more pessimistic on tail MDD than Method A, as documented — A lets the
overlay de-risk dynamically into drawdowns, which B cannot.

## 4. Cost-aware net results (bounded sensitivity)
**Limitation (reported, not worked around):** the synthetic paths are *return-level*; there is no position
book along a simulated path, so book turnover / per-name execution cost cannot be recovered. We apply each
candidate's historical mean one-way cost drag as a **constant per-day haircut** (bounded proxy) and also a
2× upper scenario. True per-path trading cost would vary with simulated turnover — flagged.

| candidate | net median CAGR (10bps) | net median Sharpe (10bps) | net P(MDD<−30%) (10bps) | net Sharpe (20bps) |
|---|---:|---:|---:|---:|
| V1 | 0.336 | 1.91 | 0.825 | 1.82 |
| DD Only | 0.331 | **2.04** | **0.487** | 1.94 |
| Combined | 0.339 | 2.01 | 0.614 | 1.92 |

Drawdown is near-invariant to the small drag; CAGR/Sharpe shift down almost uniformly. **DD Only's tail-
drawdown advantage survives net of cost** and is the robust, cost-insensitive, simulation-supported result.
Borrow/financing is near common-mode across candidates (≤0.06 Sharpe at 300bps/yr on ~0.25 short notional,
`COST_AND_CAPITAL_SENSITIVITY.csv`) and does not alter any ranking.

## 5. Conclusions supported by the corrected MC pipeline
- **VALID:** DD Only materially and robustly reduces drawdown (median and tail) vs V1, in and out of
  sample, gross and net of bounded cost.
- **VALID:** Method-A vs Method-B drawdown ordering and the "B is more conservative on tail MDD" reading.
- **PROVISIONAL:** Combined Method-A CAGR/Sharpe path stats (year-1 vol-mult warm-up convention); Combined
  shows no drawdown or return edge that would change any decision.
- **Not simulated:** position-level execution cost on synthetic paths — bounded scenarios used instead.
