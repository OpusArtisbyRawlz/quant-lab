# Project 03 — directional classifier recovery result

**Status: RECOVERED — all candidates FIDELITY VERIFIED through the real factory.**

Project 03 (single-asset SPY 5-day direction classifier) is recovered through a new,
**general** classifier experiment path — analogous to the portfolio path — without being
forced through the portfolio/Sharpe engine and without translating classification into
synthetic returns.

## Candidates — FIDELITY VERIFIED

Recovered via the real campaign `p03-classifier-recovery` (manifest → idea → hypothesis →
approval → experiment → evidence → M11 → Project 07 preliminary):

| Candidate | Model | AUC | Accuracy | Confusion (tn/fp/fn/tp) | Reference |
| --- | --- | --- | --- | --- | --- |
| p03_logistic | logistic (scaler+LR) | **0.5389** | **0.5863** | 2/431/5/616 | exp_001 (auc 0.5389, acc 0.5863) — exact |
| p03_random_forest | RF (200, depth 4, seed 42) | **0.5063** | 0.5873 | 4/429/6/615 | project_summary ~0.506 — exact |
| p03_naive_baseline | always-up reference | n/a | **0.5892** | 0/433/0/621 | baseline ~0.589 — exact |

Logistic full battery: AUC 0.5389, accuracy 0.5863, **brier 0.2415, log_loss 0.6759**,
precision 0.5883, recall 0.9919, prevalence 0.5892, n_test 1054. Precision/recall match
exp_001 (0.5883 / 0.9919) exactly. **Prediction series is bit-identical** to
`exp_001_dir_alpha_spy_5d/predictions.csv` (max abs diff 0.0, 1054 rows).

## Authoritative recipe (ported verbatim)

`research/project_03_directional_alpha/notebooks/03_model_training.ipynb` (cells 4/6/10/37):
features {ret_5, ret_10, ret_20, ma_dist_20, rv20, volume_ratio}, target = (fwd_ret_5 > 0),
chronological **80/20** split, `Pipeline(StandardScaler, LogisticRegression(max_iter=1000))`
/ `RandomForestClassifier(200, depth 4, seed 42)` / always-up baseline. (The notebook is
authoritative; `config.yaml`'s aspirational `rsi_14`/walk-forward were not what produced
the results, so they are not used.)

## Architecture — general classifier path (no P03-only hack)

- `src/classifier/directional.py` — single-asset directional classifier (asset, features,
  horizon, model, split all parameterised).
- `ExperimentSpec.classifier` (optional dict) — default None ⇒ the cross-sectional path is
  unchanged. `spec_builder` + recovery source thread it from idea metadata.
- `runner._run_classifier_experiment` — dispatched before the panel/bar path; writes
  `metrics.json` (classification keys) + `predictions.csv`; no portfolio returns.
- `spec_validator._validate_classifier` — validates the classifier contract (single
  `<asset>.csv`, model, features), not KNOWN_SIGNALS / a universe directory.
- Manifest `KIND_CLASSIFIER` + entries `p03_logistic` / `p03_random_forest` /
  `p03_naive_baseline`.

## Distinct experiment type — no mixing, no methodology change

- Ingestion auto-detects `experiment_type="classification"` from the metric keys and stores
  them in `raw_metrics`; the return columns (sharpe/mdd/…) stay **NULL**.
- M11's sharpe-based evidence engines (`EvidenceProjector`, holdout, FDR, …) **skip rows
  without a performance number** — so classifier experiments are recorded as evidence but
  never folded into the return-based posteriors. No M11 change was required.
- The Project 07 hand-off is campaign-level and metric-agnostic; the classifier campaign
  reaches `pending_handoffs` / `preliminary` like any other. No Project 07 change was
  required; classification and portfolio metrics are never mixed.

## Recovery markers

| Candidate | FOUND | EXECUTABLE | REPLAYED | FIDELITY VERIFIED | PROJECT07 |
| --- | :-: | :-: | :-: | :-: | :-: |
| p03_logistic | ✅ | ✅ | ✅ (exp_051) | ✅ | preliminary |
| p03_random_forest | ✅ | ✅ | ✅ (exp_053) | ✅ | preliminary |
| p03_naive_baseline | ✅ | ✅ | ✅ (exp_052) | ✅ | preliminary |

With P03 recovered, **historical recovery is COMPLETE** for every replayable historical
strategy (P02–P06).
