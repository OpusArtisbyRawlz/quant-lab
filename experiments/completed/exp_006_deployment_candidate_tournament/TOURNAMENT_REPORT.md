# exp_006 — Deployment Candidate Tournament

**Objective.** Find the strongest *deployable* strategy in the repository by
running every serious candidate through one identical validation battery and
letting the evidence rank them. No candidate is privileged for having been
shipped, for originating in a notebook, or for coming from the robustness branch.
The recommendation below rests solely on quantitative evidence produced here.

**Deployment-candidate lineage (preserved, never overwritten):**

| Version | Strategy | Status after this tournament |
|---|---|---|
| **V1** | exp_005 dual-layer smooth-DD product (as shipped) | **Archived baseline** (retained, untouched) |
| **V2** | DD-Only overlay (floor 0.3, k 5) on the deployment base | **Promoted — new deployment candidate** |

V2's artifacts already exist in the sibling folder
`exp_006_deployment_overlay_challenge/` (returns, weights, config); this
tournament is the formal, evidence-based confirmation of that promotion against
the *full* candidate field, including the historical low-MDD strategies.

---

## Candidate field (15 candidates, 3 groups)

* **Group A — V1 baseline (1).** The shipped product. Has a 20-name position book.
* **Group B — deployment-base challengers (8).** Robustness-notebook overlays
  re-applied to the *recovered deployment base* (strip V1's outermost portfolio
  exposure, re-apply one overlay). Same universe and book machinery → the full
  capacity / turnover / transaction-cost battery is defined.
* **Group C — historical low-MDD challengers (6).** The same overlays applied to
  the historical `final_returns_v2_with_dates.csv` series, reproduced **exactly**
  as in `05_robustness_checks.ipynb` (cells 20, 22, 15). These are a
  **return-only research series — no position book**, so book-dependent battery
  stages are *not evaluable* (recorded N/A, not waived).

Period 2016-01-04 → 2026-03-06, 2,558 trading days. Each candidate has its own
folder under `candidates/<slug>/` with `config.json`, `metrics.json`,
`provenance.json` (incl. git commit), equity/drawdown/exposure curves, rolling
metrics, and (book candidates) turnover, transaction-cost, capacity, rebalance
and operational-stress outputs.

---

## Phase 1 — Historical reproduction (passed)

The historical low-MDD candidates reproduce their reported metrics exactly on the
v2 base (matching the ≈23–25 % MDD / ≈2.3–2.4 Sharpe / ≈36–37 % CAGR target):

| Historical candidate | Sharpe | CAGR | MDD | Calmar |
|---|---|---|---|---|
| DD Only (floor 0.3, k 5) | 2.398 | 0.362 | **−0.232** | 1.561 |
| Combined / Floor 0.3 | 2.292 | 0.372 | −0.248 | 1.499 |
| Floor 0.5 | 2.221 | 0.371 | −0.277 | 1.339 |
| Floor 0.6 | 2.187 | 0.372 | −0.294 | 1.265 |
| v2 base (raw, no overlay) | 2.151 | 0.375 | −0.343 | 1.094 |

Reproduction is faithful, so Group C enters the tournament as a first-class
challenger on its own reported numbers.

---

## Master comparison (ranked)

Deployability is a **gate** (a candidate with no book cannot be capacity- or
cost-validated, so it cannot clear the promotion criteria). Book candidates are
ranked by a z-scored deployment-quality composite (Sharpe, Sortino, cost-adj
Sharpe, Calmar, MDD, Ulcer, operational resilience); Group C is ranked among
itself on paper risk-adjusted quality and held below the deployable cohort.
Full table: `master_comparison.csv`.

| Rank | Candidate | Grp | Deployable | Sharpe | Sortino | CAGR | MDD | Calmar | Ulcer | Cost-adj Sharpe | Capacity@10% med | Ops worst Sh |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **DD Only (floor0.3,k5)** | B | ✅ | **2.352** | 4.352 | 0.407 | **−0.295** | **1.382** | **0.142** | **2.264** | $3.25B | **2.170** |
| 2 | Combined / Floor 0.3 | B | ✅ | 2.281 | 4.221 | 0.426 | −0.315 | 1.352 | 0.147 | 2.196 | $3.18B | 2.103 |
| 4 | Floor 0.5 | B | ✅ | 2.183 | 3.945 | 0.425 | −0.355 | 1.198 | 0.164 | 2.097 | $2.74B | 2.003 |
| 5 | DD k=5 | B | ✅ | 2.132 | 3.804 | 0.426 | −0.381 | 1.118 | 0.172 | 2.046 | $2.52B | 1.951 |
| 7 | **V1 baseline (shipped)** | A | ✅ | 2.090 | 3.619 | 0.377 | −0.367 | 1.027 | 0.166 | 1.999 | $2.60B | 1.900 |
| 8 | Clip 0.8–1.0 | B | ✅ | 2.084 | 3.631 | 0.403 | −0.406 | 0.992 | 0.172 | 1.995 | $2.31B | 1.896 |
| 9 | DD k=1 | B | ✅ | 1.992 | 3.439 | 0.428 | −0.446 | 0.960 | 0.194 | 1.808 | $2.12B | 1.808 |
| 10 | *Historical DD Only* | C | ❌ no book | *2.398* | *4.484* | *0.362* | *−0.232* | *1.561* | *0.121* | N/A | N/A | N/A |
| 11 | *Historical Combined / Floor 0.3* | C | ❌ no book | *2.292* | *4.249* | *0.372* | *−0.248* | *1.499* | *0.130* | N/A | N/A | N/A |
| 13 | *Historical Floor 0.5* | C | ❌ no book | *2.221* | *4.044* | *0.371* | *−0.277* | *1.339* | *0.141* | N/A | N/A | N/A |
| 15 | *Historical v2 base (raw)* | C | ❌ no book | *2.151* | *3.773* | *0.375* | *−0.343* | *1.094* | *0.157* | N/A | N/A | N/A |

All candidates share an identical worst-drawdown structure: the deepest episode
peaks at the all-time high (2024-06-04) and **never recovers** by the end of the
sample (still underwater on 2026-03-06). `MaxDD_recovery_d` is therefore `null`
for every candidate — the worst drawdown is the *current* one. Time-underwater is
≈89 % for all (new all-time highs occur on ≈11 % of days).

---

## Significance, base test, stability, leakage

**Paired vs unpaired block bootstrap vs V1** (`significance_vs_v1.csv`, N=5000,
block=21d):

| Challenger | Pairing | ΔSharpe | 95% CI | ΔMDD | 95% CI |
|---|---|---|---|---|---|
| DD Only (B) | paired | **+0.262** | **[+0.133, +0.390]** | **+0.072** | **[+0.026, +0.113]** |
| Combined (B) | paired | +0.191 | [+0.024, +0.366] | +0.052 | [−0.008, +0.097] |
| Historical DD Only (C) | **unpaired** | +0.308 | **[−1.21, +1.85]** | +0.135 | **[−0.105, +0.337]** |

The Group-B winner's edge is **significant** (both CIs exclude zero, p≈0). The
Group-C edge over V1 is **not statistically distinguishable from zero**: because
it lives on a *different, unaligned* base series, the differential must be
resampled unpaired and its CI is enormous. The paired Group-B comparison cancels
common market noise; the unpaired Group-C comparison cannot.

**Apples-to-apples base test** (`base_apples_to_apples.csv`) — the *same*
DD-Only(0.3,5) overlay:

| Series | Sharpe | MDD | Vol |
|---|---|---|---|
| deployment base (raw) | 1.978 | −0.469 | 0.186 |
| v2 base (raw) | 2.151 | −0.343 | **0.154** |
| DD-Only on deployment base | 2.352 | −0.295 | 0.150 |
| DD-Only on v2 base | 2.398 | −0.232 | 0.133 |

The overlay is identical on both rows; Group C's lower MDD comes **entirely from
the v2 base being a lower-vol, shallower-drawdown return stream**, not from a
better risk control. The overlay adds the same kind of improvement to each base.

**Walk-forward parameter stability** (`walk_forward_stability.csv`, expanding
window, select floor/k by training Sharpe, score held-out year):

| Base | Folds Sharpe>V1 | Folds MDD shallower | mean ΔSharpe |
|---|---|---|---|
| deployment (Group B) | **6/7** | 7/7 | +0.285 |
| v2 (Group C) | **3/7** | 7/7 | +0.240 |

The deployable candidate beats V1 consistently fold-to-fold; the v2-base
candidate's Sharpe edge is *inconsistent* OOS (only 3/7). Full-sample
floor×k neighbourhood Sharpe spread is small for both (0.152 / 0.107).

**Leakage / look-ahead** (`leakage_check.csv`): candidate return = base return ×
exposure_{t-1} to max abs error **0.0** on both bases; the overlay is causal
(drawdown from causal cummax, exposure lagged one day). The leaky contemporaneous
variant would read Sharpe ≈2.64 vs the deployed causal 2.35 — confirming the
reported edge does **not** come from look-ahead.

---

## Final report — answers

**1. Which candidate is strongest overall?**
On the *deployment-quality* composite, **DD-Only (floor 0.3, k 5) on the
deployment base** (Group B) — rank 1, and the strategy promoted to **V2**. On
*paper risk-adjusted metrics alone*, Historical DD-Only (Group C) scores highest
(Sharpe 2.398, MDD −0.232, Ulcer 0.121), but it is not deployable (see Q9).

**2. Which candidate is most robust?**
V2 (DD-Only, deployment base). It is the only candidate whose edge over V1 is
statistically significant *and* persistent: 6/7 walk-forward folds, all four
calendar subperiods, survives transaction-cost, capacity and operational stress,
and shows the highest operational worst-case Sharpe (2.170).

**3. Which candidate has the best risk-adjusted profile?**
Among *deployable* candidates, V2 (Sharpe 2.352, Sortino 4.352, Calmar 1.382,
Ulcer 0.142). On raw return-series numbers Historical DD-Only edges it, but that
advantage is a property of the lower-vol v2 base and is not significant (Q5).

**4. Which candidate would you deploy today?**
**V2 — DD-Only (floor 0.3, k 5) on the deployment base.** It is the strongest
strategy that is actually deployable: it has a position book, survives every
cost/capacity/operational check, and significantly dominates the incumbent.

**5. Is the improvement statistically meaningful?**
Yes, for V2 vs V1: paired block-bootstrap ΔSharpe +0.262 [+0.133, +0.390] and
ΔMDD +0.072 [+0.026, +0.113], both CIs excluding zero (p≈0), persistent across
folds and subperiods. **No** for the historical Group-C candidates vs V1: their
ΔSharpe/ΔMDD CIs straddle zero once resampled honestly (unpaired, different base).

**6. What trade-offs exist between candidates?**
Within Group B the trade-off is floor/aggressiveness: lower floor & DD-only (no
vol term) → higher Sharpe, shallower MDD, lower turnover and exposure; adding the
vol-scaling term or tightening clips (Combined, Clip 0.8–1.0, k=1) costs Sharpe
and deepens MDD, mostly via low-vol-regime participation drag. Group C trades
*deployability for paper smoothness*: lower headline MDD/vol, but no book, no
capacity, no cost validation, and an unverifiable construction. V2 vs V1: V2
gives up nothing — better on every axis at lower gross exposure and turnover.

**7. Should Deployment Candidate V1 remain active?**
No. V1 is dominated by V2 on every battery dimension (Sharpe, CAGR, MDD, Calmar,
Sortino, Ulcer, cost-adjusted Sharpe, capacity, operational worst-case) at lower
exposure and turnover, and the gap is statistically significant. V1 should be
**archived as the baseline** (retained, reproducible, untouched), with V2 active.

**8. If V2 is recommended, explain exactly why.**
V2 = DD-Only (floor 0.3, k 5) on the deployment base. It (a) dominates V1 on the
full battery — Sharpe 2.352 vs 2.090, MDD −0.295 vs −0.367 (~20 % shallower),
Calmar 1.382 vs 1.027, cost-adj Sharpe 2.264 vs 1.999, capacity $3.25B vs $2.60B,
ops worst Sharpe 2.170 vs 1.900 — at *lower* gross exposure (0.69 vs 0.80) and
turnover (0.053 vs 0.058); (b) the edge is statistically significant and
walk-forward / subperiod persistent; (c) it is causal (no look-ahead); and (d) it
beats every other *deployable* challenger, with the gain coming from cutting risk
in drawdowns rather than from leverage. The clean drawdown signal beats the
vol-blended ones, which only add low-vol-regime drag.

**9. If the historical 23–25 % MDD candidates do not win, explain precisely why
they failed despite their attractive historical metrics.**
They fail on **two independent grounds**, neither of which is "where they came
from":

  1. **Not deployable.** `final_returns_v2_with_dates.csv` is a bare *return
     series* with no position book, no universe mapping, and no turnover. The
     deployment promotion criteria require surviving transaction-cost, capacity
     and operational validation — Group C cannot even *undergo* those stages
     (every book-dependent cell is N/A). A strategy you cannot size, trade, or
     capacity-check is not a deployment candidate, however good its paper curve.

  2. **The edge is not real once measured honestly.** The apples-to-apples test
     shows the *same* DD-Only overlay produces MDD −0.295 on the deployment base
     and −0.232 on v2 — so the lower MDD is a property of the **lower-vol v2 base
     (vol 0.154 vs 0.186)**, not the overlay. And the v2-vs-V1 differential is
     statistically insignificant (unpaired ΔSharpe CI [−1.21, +1.85], ΔMDD CI
     [−0.105, +0.337]) and inconsistent walk-forward (only 3/7 folds beat V1 on
     Sharpe). Their attractive headline numbers are a lower-vol base plus the
     *same* overlay V2 already uses — not evidence of a superior, deployable
     strategy.

**10. If the historical candidates do win, explain why they weren't promoted
and provide evidence they now outperform V1 under identical validation.**
Not applicable — they do not win. They are non-deployable and their edge over V1
is not statistically established under identical, honest validation (Q9). The
deployable winner, V2, captures the *same* DD-only mechanism the historical
candidates use, applied to a base that has a tradeable book and survives the full
deployment battery.

---

### Decision

**Promote V2 = DD-Only (floor 0.3, k 5) on the deployment base.** Archive V1 as
the retained baseline. The historical low-MDD candidates are reproduced, ranked,
and explained, but are excluded from deployment on evidence: no position book
(cannot pass cost/capacity/operational validation) and no statistically
significant edge over V1. Re-fit floor/k periodically before live-capital changes
(both bases' optimisers favour the grid's lower floor boundary — the conservative
interior point 0.3/5 is used deliberately).
