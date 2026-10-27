# PURGING & EMBARGO VALIDATION — Stage B2/B3

**Module:** `src/statistics/cross_validation.py` · **Tests:** `tests/test_cross_validation.py` (12)
**Application:** `scripts/b_model_level_cv.py` · data: `data/model_cv_purged_kfold.csv`

---

## 1. What is being validated, and the unit of observation (B1)
The canonical object for purging is the **Project-04 forecasting problem**: panel
`data/processed/project_04_features_v2.csv` (174,101 rows, 20 tickers, 1985–2026), 13 features →
label **`fwd_ret_5`** (forward 5-trading-day return). The label is an **overlapping interval**: the
observation at date *d* consumes returns on *d+1…d+5*, so observations within 5 trading days share
label information. Unit of observation = **trading date** (tickers pooled cross-sectionally); purging
and embargo act on the date axis.

The forecaster used is a **representative closed-form ridge** (α=10, standardized features) — this is a
transparent linear proxy to exercise the leakage machinery and measure generalization of the
forecasting *approach*, **not** a byte-for-byte reproduction of P04's production model. Skill metric =
pooled **OOS rank IC** (Spearman of prediction vs realized `fwd_ret_5`).

## 2. Purging — implementation
`purge_train_indices(train, test, t1)` removes every training observation whose label interval
`[i, t1[i]]` intersects the test label span `[min(test), max(max(test), max(t1[test]))]`. `t1` is
driven by the **actual label intervals** (here `t1[d]=d+5`), never a fixed row count. Verified by
`test_purge_removes_exactly_the_overlapping_labels` (n=20, horizon=5, test=10..14 → exactly
positions 5..19 purged, 0..4 survive) and `test_irregular_timestamp_t1` (uneven label lengths).

## 3. Embargo — implementation
`embargo_train_indices` drops training observations in a window of `embargo` positions **immediately
after** each contiguous test block (the pre-test side is already handled by interval purging).
Distinguished from purging: purging prevents *label-overlap* leakage; embargo additionally suppresses
*serial-correlation* leakage just after the test block. Verified by `test_embargo_removes_only_post_test_window`.

## 4. Independent tests (all pass)
Correct purging · irregular timestamps · **no future information enters training**
(`test_no_future_information_enters_training` checks every train interval is disjoint from the test
label span) · no over-removal (`horizon=0` purges nothing) · first/last fold boundaries + full disjoint
coverage · deterministic · purged counts reported. 12/12 pass.

## 5. Results — purged K-fold with embargo sensitivity + leaky baseline

| scheme | mean OOS IC | std OOS IC | min | max | dates purged/fold | dates embargoed/fold |
|---|---:|---:|---:|---:|---:|---:|
| purged, embargo 0 | 0.0373 | 0.0242 | 0.017 | 0.086 | 8.3 | 0 |
| purged, embargo 5 | 0.0373 | 0.0242 | 0.017 | 0.086 | 8.3 | 0 |
| purged, embargo 10 | 0.0371 | 0.0239 | 0.016 | 0.085 | 8.3 | 4.2 |
| purged, embargo 21 | 0.0371 | 0.0239 | 0.016 | 0.085 | 8.3 | 13.3 |
| **shuffled K-fold (LEAKY)** | **0.0421** | **0.0056** | 0.035 | 0.053 | 0 | 0 |

**Reading.** The representative forecaster has a **small but genuine OOS skill (~0.037 rank IC)**. The
leaky shuffled K-fold reports a *higher* mean IC (0.042) with *artificially tight* dispersion
(std 0.006 vs 0.024) — the classic label-overlap leakage signature that purging removes. Skill is
**insensitive to embargo** (0→21 days: 0.0373→0.0371), indicating the result is not driven by
immediate serial correlation. Embargo chosen with reference to the 5-day label horizon; 5–21 days
reported as sensitivity (an embargo beyond the label horizon is conservatism, not a leakage necessity).

## 6. Scope note
This validates the **generalization of a representative P04-style forecaster** under leakage-aware CV.
It is a research generalization test; it does not certify P04's exact production model, and (being
non-chronological in CPCV) is not a live-trading walk-forward replica.
