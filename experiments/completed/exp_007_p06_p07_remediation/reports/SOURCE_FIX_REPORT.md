# SOURCE FIX REPORT — Return-Lineage Remediation (Projects 06/07)

**Experiment:** `exp_007_p06_p07_remediation` · **Branch:** `remediation/p06-p07-return-lineage`
**Base commit:** `760f871` · **Date:** 2026-10-27
**Predecessor:** `exp_007_research_integrity_audit` (forensic audit; investigation baseline)

This remediation implements the verified correction **in the original source code**, regenerates every
affected downstream artifact on the corrected base, and reconciles Projects 06 and 07. No strategy was
optimised, no parameter changed, no production logic altered, and **no candidate was promoted**.

---

## 1. The defect (one line)

```python
base_ret = portfolio_return / portfolio_dd_exposure.shift(1)   # DOUBLE LAG
```
`exp_005` persists `portfolio_dd_exposure` as the **already-lagged** applied exposure
(`portfolio_exp.shift(1)`), and `portfolio_return[t] = port_pre[t] · exposure[t]` **same-row**. The extra
`.shift(1)` de-lagged the base a second time, injecting a spurious `exp[t-1]/exp[t-2]` factor on
2,327 / 2,558 days. The book recovery in the *same* functions (`wide / exp`, same-row) was already correct —
a self-contradiction that pinpointed the return line.

## 2. The fix

```python
base_ret = pr / exp            # same-row inverse; exp is already the lagged applied exposure
```
Verified equal to the canonical `port_pre` rebuilt from the Project-04 raw strategies to **1e-12**
(`test_remediation_source_fix.py::test_tournament_source_base_is_canonical`). The numerator and
denominator refer to the **same trading period** — demonstrated three ways: (a) `port_pre · exp == shipped
portfolio_return` to 1e-16; (b) the same-row quotient reconstructs the exp_004-built `port_pre` to 1e-12;
(c) the position book uses the identical same-row inverse. We did **not** substitute a different
approximation; the same-row inverse is the exact inverse.

## 3. Call sites corrected (8 scripts — the audit named 2; grep found 6 more)

| # | File | Line | Change |
|---|---|---|---|
| 1 | `exp_006…candidate_tournament/run_tournament.py` | 125 | `pr/exp.shift(1)` → `pr/exp` |
| 2 | `exp_006…candidate_tournament/tournament_significance.py` | 67 | same |
| 3 | `exp_006…candidate_tournament/tournament_stability.py` | 54 | same |
| 4 | `exp_006…overlay_challenge/run_overlay_challenge.py` | 108–111 | drop `exp_lag`; `pr/exp`; docstring+config string |
| 5 | `exp_006…overlay_challenge/statistical_significance.py` | 43 | same |
| 6 | `exp_006…overlay_challenge/walk_forward_sensitivity.py` | 68 **+ 97** | `pr/exp`; **reproduction re-apply → same-row** `base*exp` |
| 7 | `exp_006…overlay_challenge/promote_deployment_candidate.py` | 43 | `pr/exp_inc`; **fixed but NOT run** (promotion prohibited) |
| 8 | `exp_007_garch_volatility_persistence/analysis_overlay_replay.py` | 22 | `pr/exp` |

The three `exp_007_research_integrity_audit/*.py` scripts and `test_return_lineage_audit.py` retain
`pr/exp.shift(1)` **intentionally** — they are the audit's defect-reproduction evidence.

### 3a. A subtlety fixed in `walk_forward_sensitivity.py`
Its `check_reproduction` re-applied the stripped exposure with `apply_exposure_to_return` (another lag),
which only "passed" because it inverted and re-applied the *same* extra shift. With the base corrected, the
honest re-application of the already-lagged stored exposure is **same-row** (`base_ret * exp`). GATE 1
(exact reproduction) now passes at 3e-18 against the true relationship.

## 4. Regression tests (Phase-2 requirements 1–8)

`research/project_07_statistical_integrity/tests/test_remediation_source_fix.py` (8 tests) binds to the
**real fixed source** (imports `load_deployment_base`, `load_base`, `build_candidates`):

1. V1 returns unchanged (incumbent == shipped). 2. DD Only/Combined reconstruct from canonical inputs.
3. One-day exposure lag. 4. No extra lag (source base == canonical). 5. Gross/net reconcile.
6. Double-shift fails the guard. 7. Corrected source passes. 8. Weights unchanged (`base_book·exp == wide`).

Plus the 5 analytic/identity tests in `test_return_lineage_audit.py`. **P06: 8 passed. P07: 269 passed,
11 skipped** (261 prior + 8 new). No assertion weakened; the 11 skips are pre-existing data-conditional.

## 5. Integrity of untouched projects
`exp_004` and `exp_005` artifacts are immutable inputs — **checksums verified unchanged**, dirs untouched.
V1's `equity_curve.csv`, `metrics.json`, `turnover.csv` are **bit-identical** after regeneration (only the
`git_commit` provenance stamp updates). The fix is surgical: 7 tracked scripts, +22/−13 lines, almost all
comments; one operator changed per file.

## 6. What regeneration produced (see `ARTIFACT_DEPENDENCY_STATUS.csv`)
Tournament, overlay-challenge, `exp_007_candidate_net_validation` (NB09), WRC (NB06), the NB03 dynamic
replay, and the GARCH overlay replay were all rerun/regenerated on the corrected base via the fixed scripts
and faithful transcription scripts in `scripts/` (identical seeds/blocks). Defective originals are archived
read-only under `archived_defective_outputs/` with a sha256 manifest.
