# COST AND TURNOVER AUDIT

**Audit:** `exp_007_research_integrity_audit` · data: `COST_AND_TURNOVER_AUDIT.csv`

Central question (Phase 4): *was turnover computed from actual position changes, or from an
exposure-scaled return series?*

---

## 1. How turnover is actually computed

`src/analysis/turnover.py::compute_turnover(weights) = Σ|Δw_t| / 2` — one-way turnover from the **position
book**, not from returns. In the tournament:

```python
turnover = compute_turnover(book)        # book = as-traded weights
# V1:          book = wide                     (shipped as-traded weights)
# DD/Combined: book = base_book.mul(e)         base_book = wide / exp  (correct same-row inverse)
```

So turnover is derived from asset-level weight changes, **not** from `|Δexposure|` or scaled returns. (The
only place `|Δexposure|` is used is the explicit *proxy* lower-bound for Group-C return-only candidates, which
is clearly labelled a proxy and is not used for V1/DD/Combined.) **Answer: turnover came from the real book.**

## 2. Is turnover affected by the defect?

The book recovery `wide/exp` is the *correct* same-row inverse, so the book itself is clean. The only
defect channel into turnover is second-order: the challenger exposure `e` is computed on the drawdown of the
**defective** base, so `book = base_book·e` shifts slightly. Recomputing turnover on the canonical base:

| candidate | mean turnover (shipped) | mean turnover (recompute, old base) | mean turnover (corrected base) | ann cost drag @10bps old | corrected |
|---|---:|---:|---:|---:|---:|
| V1 | 0.0581 | 0.0581 | 0.0581 | 1.46% | 1.46% |
| DD Only | 0.0532 | 0.0532 | 0.0527 | 1.34% | 1.33% |
| Combined | 0.0555 | 0.0555 | 0.0550 | 1.40% | 1.39% |

- Recompute reproduces the shipped turnover exactly → the audit faithfully reproduces the book pipeline.
- Correction moves mean turnover by **< 0.0006** and annual cost drag by **< 0.02 pp**. **Turnover and
  transaction costs are materially unaffected** by the defect. A correct cost formula was applied to a
  correctly-constructed book; the only error was in the *return* lineage, not the cost lineage.

## 3. Cost model as applied — verified components and limitations

| component | treatment | status |
|---|---|---|
| one-way turnover | `Σ|Δw|/2` from book | VERIFIED (actual positions) |
| commission / spread | folded into a single **10 bps** one-way cost (P06 deployment-report assumption) | VERIFIED formula; blended bps is an assumption |
| net return | `net = gross − turnover·(bps/1e4)` | VERIFIED |
| long/short notional, gross vs net exposure | book carries signed weights; gross=Σ|w|, net=Σw | VERIFIED from book |
| market impact / capacity | separate capacity battery (ADV, 10% participation) — book-based | VERIFIED basis; not in net return |
| borrow / financing / leverage cost on shorts | **NOT modelled** | LIMITATION (pre-existing, affects all three equally) |
| execution timing | exposure applied `t-1→t` (lagged); book contemporaneous | VERIFIED look-ahead-safe |

## 4. Verdict (Central Question 2)

**Turnover and transaction costs were calculated from the correct positions and exposures, and are
essentially unchanged by the lineage defect.** The net-return *series* for DD Only/Combined still move — but
only because their **gross** returns were defective, not because the cost/turnover accounting was wrong.
Remaining cost limitation: borrow/financing costs on the short book are still unmodelled for every candidate
(carry this into any paper-trading go/no-go).
