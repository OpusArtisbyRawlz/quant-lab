# Project 07 — Statistical Integrity

Determine whether the performance of a strategy that has passed **Project 06
(Deployment Validation)** is **statistically real** — that is, unlikely to be an
artifact of luck, overfitting, or the number of hypotheses tested — before any
capital decision is made.

> **Status: scaffold only.** This directory currently contains documentation,
> notebook skeletons, and module interfaces. No statistical algorithm is
> implemented yet; module function bodies raise `NotImplementedError`.

---

## 1. Purpose

Project 06 answers *"is this strategy deployable, and at what scale?"* Project 07
answers the prior, harder question: *"is the edge even real?"* A strategy can pass
every deployment gate — capacity, cost, turnover — and still be noise that a
large search happened to surface. This project supplies the inferential layer that
separates genuine signal from selection artifacts.

## 2. Why statistical integrity matters

Systematic research is a search process, and search inflates apparent
performance:

- **Luck.** A single backtest Sharpe has wide sampling error; a high point
  estimate can arise from a short, autocorrelated, fat-tailed sample.
- **Overfitting.** Parameter tuning fits the noise in the historical path.
- **Multiple testing.** Running thousands of configurations guarantees extreme
  Sharpes by chance; the more we look, the higher the bar must be.

Ignoring these produces confident deployment of strategies that do not survive
live trading. Project 07 makes the search cost explicit and applies the standard
tools for controlling it.

## 3. Relationship to Project 06

- **Consumes, never modifies, Project 06.** Project 07 reads the frozen Project 06
  baseline (tag `project-06-deployment-validation-frozen`) and the reference
  strategy outputs it validated. It changes nothing in Projects 01–06.
- **Complementary gates.** A strategy should clear **both** the deployment gate
  (Project 06) *and* the statistical gate (Project 07) before promotion toward
  live capital.
- **Provenance link.** Every statistical conclusion records the Project 06
  freeze/tag it was computed against, via the Evidence Ledger (§8).

## 4. Scope

**In scope:** sampling-uncertainty quantification (bootstrap), null-distribution
simulation (Monte Carlo / permutation), multiple-testing correction (FDR /
family-wise), overfitting-aware Sharpe deflation (PSR / Deflated Sharpe), and
data-snooping tests over a strategy family (White's Reality Check / Hansen's SPA),
plus an auditable Evidence Ledger and an aggregate statistical report.

**Out of scope:** strategy construction, risk overlays, execution, capacity, and
cost modelling (Projects 01–06); live/paper trading; portfolio optimization.

## 5. Inputs

- Reference strategy returns / weights / equity from the Project 05 final export
  (`experiments/completed/exp_005_risk_engine_final/`), as validated by Project 06.
- The **trial record** — the set of hypotheses/configurations evaluated during
  research (count and, where available, the per-trial return series) — required to
  quantify the multiple-testing penalty.
- Run configuration: block length, resample counts, RNG seed, correction method,
  significance level.

## 6. Outputs

- Per-test result tables under `results/` (e.g. bootstrap confidence intervals,
  Monte-Carlo p-values, FDR-adjusted decisions, Deflated-Sharpe probabilities,
  Reality-Check p-values). CSV/JSON, gitignored by repo convention except any
  committed golden baselines.
- A consolidated **statistical integrity report** (notebook 06) with an explicit
  per-strategy verdict.
- An append-only **Evidence Ledger** (§8) capturing the full provenance of every
  test.

## 7. Notebooks

| Notebook | Purpose |
| --- | --- |
| `01_bootstrap.ipynb` | Quantify sampling uncertainty of performance metrics via block/stationary bootstrap; produce confidence intervals for Sharpe, Calmar, CAGR, MDD. |
| `02_permutation.ipynb` | Randomization/permutation significance of the observed Sharpe (sign-flip null, one-sided empirical p-value). |
| `03_monte_carlo.ipynb` | Simulate null distributions (Monte-Carlo) to obtain empirical p-values for observed performance. |
| `04_multiple_testing.ipynb` | Apply multiple-testing corrections (Benjamini–Hochberg FDR, Bonferroni, Holm) across the family of evaluated hypotheses. |
| `05_deflated_sharpe.ipynb` | Compute the Probabilistic and Deflated Sharpe Ratio and minimum track-record length, penalizing for trials and non-normality. |
| `06_white_reality_check.ipynb` | Test for data-snooping across the strategy family via White's Reality Check and Hansen's SPA. |
| `07_statistical_report.ipynb` | Aggregate all tests into a single statistical-integrity report with an explicit verdict per strategy. |
| `08_evidence_ledger.ipynb` | Demonstrate and audit the Evidence Ledger — the provenance record for every statistical conclusion. |

## 8. Modules (`src/statistics/`)

| Module | Responsibility |
| --- | --- |
| `bootstrap.py` | Block / stationary bootstrap resampling and metric confidence intervals. |
| `monte_carlo.py` | Monte-Carlo null-path simulation and permutation testing. |
| `significance.py` | Multiple-testing corrections and test statistics (FDR, Bonferroni, Holm, Sharpe t-stat). |
| `deflated_sharpe.py` | Probabilistic / Deflated Sharpe Ratio and minimum track-record length (Bailey–López de Prado). |
| `white_reality_check.py` | White's Reality Check and Hansen's Superior Predictive Ability test. |
| `evidence.py` | The Evidence Ledger: schema (`EvidenceRecord`) and the append-only record/query interface. |
| `report.py` | Assemble per-test results into a consolidated report and verdict. |

All bodies currently raise `NotImplementedError`; signatures, type hints, and
documentation are complete.

## 9. Expected workflow

1. Load the frozen Project 06 reference strategy and the trial record.
2. **Bootstrap** the headline metrics → confidence intervals (NB 01).
3. **Monte-Carlo / permutation** → empirical p-values under the null (NB 02).
4. **Deflated Sharpe** → probability the true Sharpe > 0 given the number of
   trials and the return distribution (NB 04).
5. **Multiple-testing correction** across the hypothesis family → adjusted
   significance (NB 03).
6. **Reality Check / SPA** → guard against data-snooping across the family
   (NB 05).
7. **Aggregate** into the statistical report and a verdict (NB 06).
8. **Record** every step in the Evidence Ledger with full provenance (NB 07).

Each step is deterministic given its recorded RNG seed, and every conclusion is
reconstructable from the Evidence Ledger.

## 10. Statistical roadmap

The tests are ordered so each stage consumes what the previous one establishes:

```
Project 06 (Deployment Validation)   ← frozen, validated strategy enters here
            ↓
Bootstrap                            ← how uncertain is the metric at all?
            ↓
Monte Carlo                          ← is it distinguishable from a no-edge null?
            ↓
Deflated Sharpe                      ← does it survive the search (trials) penalty?
            ↓
Multiple Testing                     ← does it survive across the whole family?
            ↓
White Reality Check                  ← does the best-of-family beat the benchmark?
            ↓
Evidence Ledger                      ← record provenance of every result above
            ↓
Statistical Report                   ← reduce all evidence to one gated verdict
```

**Why each stage depends on the previous one:**

- **Deployment → Bootstrap.** Only a strategy that already passed deployment
  validation is worth testing; the bootstrap first asks the most basic question —
  how wide is the sampling error around its metrics.
- **Bootstrap → Monte Carlo.** Once we can quantify sampling spread, we compare
  the observed metric to an explicit *no-edge* null to get a p-value; the bootstrap
  machinery (block resampling) is reused to respect autocorrelation.
- **Monte Carlo → Deflated Sharpe.** A single p-value ignores that the strategy
  was *selected* from many trials; the Deflated Sharpe deflates significance by the
  number of trials and non-normality.
- **Deflated Sharpe → Multiple Testing.** Deflation handles one strategy's
  selection penalty; multiple-testing correction generalises this to the whole
  family of p-values (FDR/FWER).
- **Multiple Testing → Reality Check.** Corrections assume the p-values are given;
  the Reality Check / SPA test the *joint* null over the family directly with a
  bootstrap, robust to correlated strategies.
- **Reality Check → Evidence Ledger.** Every result above is only trustworthy if
  its provenance is recorded; the ledger captures it immutably.
- **Evidence Ledger → Statistical Report.** The report reads the ledger and
  reduces all recorded evidence to a single gated verdict.

## 11. Architecture

```
Compute Layer                       pure, deterministic estimators
    bootstrap
    monte_carlo
    deflated_sharpe
    significance
    white_reality_check
            ↓        (each emits a typed result + an EvidenceRecord)
Evidence Layer                      immutable provenance of every result
    EvidenceRecord
    EvidenceLedger
            ↓        (report reads the ledger)
Decision Layer                      gated verdict per strategy
    Statistical Report
```

**Layer responsibilities:**

- **Compute Layer** — stateless, seeded, unit-testable statistical procedures.
  Each returns a typed result dataclass and knows nothing about storage or
  decisions. This is where all mathematics lives.
- **Evidence Layer** — the append-only Evidence Ledger. It records *what was
  computed, how, and under which assumptions*, binding every result to its
  provenance. It makes conclusions auditable and reproducible; it contains no
  statistics.
- **Decision Layer** — reads the ledger and applies a **conjunction of gates** to
  produce one verdict per strategy. A strategy is statistically supported only if
  it clears every applicable test; no single strong result can mask a weak one.

## 12. Learning objectives

This README doubles as a structured learning guide. Work through the notebooks in
order; each entry states the concept, why the method exists, the problem it solves,
when to use it, its key assumptions and limitations, and what you must understand
before moving on.

### NB 01 — Bootstrap
- **Concept taught:** resampling to estimate the sampling distribution of a metric.
- **Why it exists:** closed-form standard errors don't exist for most performance
  metrics (Calmar, max drawdown) and are wrong for autocorrelated Sharpe.
- **Problem it solves:** "how uncertain is this Sharpe/Calmar/MDD?" — turns a point
  estimate into a confidence interval.
- **When to use:** whenever you report a metric and need an honest error bar.
- **Assumptions:** approximate stationarity; block length captures the dependence
  structure.
- **Limitations:** understates uncertainty if block length is too short; assumes
  the past dependence structure persists.
- **Before moving on:** understand sampling distributions, percentile vs BCa
  intervals, and why block (not iid) resampling is required for returns.

### NB 02 — Monte Carlo & Permutation
- **Concept taught:** building a null distribution by simulation to obtain an
  empirical p-value.
- **Why it exists:** to answer significance without assuming a parametric null.
- **Problem it solves:** "could this performance arise from no edge at all?"
- **When to use:** when you need a p-value for a metric with no tractable null
  distribution, or to test a signal→return relationship (permutation).
- **Assumptions:** the null model is a faithful "no-edge" analogue; draws are
  exchangeable under the null.
- **Limitations:** the p-value is only as good as the null model; ignores the
  multiple-trials problem.
- **Before moving on:** understand null hypotheses, one- vs two-sided tests, and
  how a permutation destroys the signal→return link.

### NB 03 — Multiple Testing
- **Concept taught:** controlling error across a *family* of hypotheses (FDR / FWER).
- **Why it exists:** testing many configurations guarantees false positives at any
  fixed per-test threshold.
- **Problem it solves:** "how many of my 'significant' strategies are real?"
- **When to use:** whenever more than one hypothesis/configuration was evaluated.
- **Assumptions:** the p-value family is correctly specified; BH assumes weak
  dependence.
- **Limitations:** conservative under strong dependence; requires the true trial
  count, which is easy to under-report.
- **Before moving on:** understand FDR vs FWER, and why the trial count is itself
  evidence.

### NB 04 — Deflated Sharpe
- **Concept taught:** deflating a Sharpe by the selection process (PSR/DSR).
- **Why it exists:** the maximum Sharpe across many trials is upward-biased even
  under a true null.
- **Problem it solves:** "is this Sharpe real once I account for how hard I searched
  and for fat tails?"
- **When to use:** on any strategy chosen as the best (or near-best) of a search.
- **Assumptions:** returns' skew/kurtosis are estimated well enough; trial count and
  cross-trial variance are known.
- **Limitations:** needs the number of *effective* trials; sensitive to
  higher-moment estimates at small n.
- **Before moving on:** understand PSR, expected-maximum under the null, and
  minimum track-record length.

### NB 05 — White's Reality Check & Hansen's SPA
- **Concept taught:** a joint test that the best strategy in a family beats a
  benchmark, accounting for the whole search.
- **Why it exists:** per-strategy tests and even FDR can miss the *data-snooping*
  bias of choosing the best of many correlated strategies.
- **Problem it solves:** "does my best backtest beat the benchmark, or did I just
  mine it?"
- **When to use:** when a strategy was selected as the best of a family evaluated
  on the same data.
- **Assumptions:** stationary bootstrap over time; the family and benchmark are
  fixed in advance.
- **Limitations:** low power with very large or highly correlated families; SPA
  needed when the family contains poor strategies.
- **Before moving on:** understand the stationary bootstrap and why SPA improves on
  the Reality Check.

### NB 06 — Statistical Report
- **Concept taught:** reducing many test results to one auditable verdict via gates.
- **Why it exists:** decisions need a single, explainable answer, not five p-values.
- **Problem it solves:** "given all the tests, do we believe the edge?"
- **When to use:** after notebooks 01–05 have produced evidence records.
- **Assumptions:** the gates and thresholds encode the desired evidentiary bar.
- **Limitations:** a verdict is only as sound as its inputs and thresholds.
- **Before moving on:** understand why a conjunction of gates beats a weighted score.

### NB 07 — Evidence Ledger
- **Concept taught:** provenance and reproducibility as first-class artifacts.
- **Why it exists:** a conclusion you cannot reproduce or trace is not science.
- **Problem it solves:** "why do we believe this, and can we reproduce it exactly?"
- **When to use:** every test records here; audits and reproducibility checks read
  here.
- **Assumptions:** every producer records complete, honest provenance.
- **Limitations:** provenance quality depends on discipline at record time.
- **Before moving on:** understand append-only logs, determinism via seeds, and the
  full `EvidenceRecord` schema.

## 13. Evidence philosophy

The Evidence Ledger is not a Project 07 convenience — it is intended as the
**provenance layer for the entire research repository**. Every statistical
conclusion the lab makes should eventually be traceable, without external context,
back to:

- the **Project 06 freeze/tag** it was computed against,
- the **strategy version** under test,
- the **dataset** and date range,
- the **parameters** and **random seed**,
- the **statistical method** and its **assumptions**,
- the **notebook** and **source module** that produced it,
- the **code version** (commit hash / git tag / implementation version).

The objective is **complete scientific reproducibility**: given a ledger record,
anyone can re-run the exact test on the exact data with the exact code and obtain
the exact result. Conclusions without a ledger record are treated as unverified.

## 14. Future extensions

Documentation-only placeholders for methods that may be added later. **No files or
interfaces exist for these yet** — they are recorded here to signal intended
direction, not committed scope:

- **Bayesian inference** — posterior distributions over Sharpe / edge instead of
  point p-values.
- **Bayesian model comparison** — Bayes factors across competing strategy models.
- **Block permutation tests** — permutation testing that preserves serial
  dependence.
- **Robust confidence intervals** — heavy-tail- and outlier-resistant intervals.
- **Cross-validation diagnostics** — combinatorial purged CV / walk-forward
  overfitting diagnostics.
- **Stability selection** — selection frequency under resampling to harden feature/
  strategy choice.
- **Regime-aware bootstrap** — resampling conditioned on market regime.
- **Bayesian performance attribution** — posterior attribution of returns to
  factors/regimes.
