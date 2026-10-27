# exp_007_p06_p07_remediation

Controlled remediation of the exp_006 return-lineage **double-lag** defect: fix at source, regenerate all
affected P06/P07 evidence on the corrected base, reconcile. Follows `exp_007_research_integrity_audit`.
Branch: `remediation/p06-p07-return-lineage`. Nothing optimised; no candidate promoted; inputs immutable.

## Start here
- `reports/PROJECT_07_RECONCILED_REPORT.md` — consolidated findings + Phase-9 integrity gate (10 Qs, pass/fail).
- `reports/SOURCE_FIX_REPORT.md` — the one-line defect, the fix, the 8 corrected call sites, tests.

## Deliverables (`reports/`)
| # | file | contents |
|---|---|---|
| 1 | `SOURCE_FIX_REPORT.md` | corrected code paths + explanation |
| 2 | `REGENERATED_PERFORMANCE.csv` | gross/net metrics, old vs corrected, per candidate |
| 3 | `COST_AND_CAPITAL_SENSITIVITY.csv` | trading/borrow/financing scenarios + break-even |
| 4 | `STATISTICAL_TEST_RECONCILIATION.csv` | each significance test, old vs corrected |
| 5 | `MONTE_CARLO_COST_AUDIT.md` | MC methodology, net results, limitations |
| 6 | `ARTIFACT_DEPENDENCY_STATUS.csv` | VALID / CORRECTED / PROVISIONAL / INVALID per artifact |
| 7 | `PROJECT_07_RECONCILED_REPORT.md` | final consolidated findings |
| 8 | `UPDATED_EVIDENCE_LEDGER_ENTRY.json` | ledger entry (+ regenerated `exp_007_candidate_net_validation/evidence_records.json`) |
| 9 | `scripts/`, `logs/`, `evidence_record.json`, `MANIFEST_SHA256.txt` | reproducible scripts, logs, hashes, seeds, config |

## Layout
- `scripts/` — reproducible regeneration scripts (NB09, NB06/WRC, cost sensitivity, cost-aware MC, reconciliation, evidence).
- `logs/` — stdout of every regeneration run + before/after source hashes + pytest logs.
- `data/` — corrected copies of regenerated daily returns, significance, WRC, econ, MC tables.
- `archived_defective_outputs/` — read-only pre-fix outputs (246 files) + their sha256 manifest.
- `reports/` — the 9 deliverables.

## Reproduce
From repo root, on the remediation branch:
```
PYTHONPATH=. venv/bin/python -m pytest research/project_07_statistical_integrity/tests \
    research/project_06_deployment_validation/tests -q
# then rerun the fixed experiment scripts + scripts/*.py (seeds are fixed; see evidence_record.json)
```

## Source fix (one line)
`base_ret = portfolio_return / portfolio_dd_exposure` (same-row; stored exposure already lagged) —
replaces the double-lagged `portfolio_return / portfolio_dd_exposure.shift(1)`. Equals the canonical
`port_pre` rebuilt from Project-04 to 1e-12.

## Headline
V1 unchanged (bit-identical). DD Only = credible **drawdown + Sharpe** improver over V1 (no CAGR edge).
Combined DD+Vol = **no** incremental edge over V1 on any axis. White's Reality Check unchanged (p=0.0103).
Promotion gate flips PASS→FAIL on corrected returns. No winner selected.
