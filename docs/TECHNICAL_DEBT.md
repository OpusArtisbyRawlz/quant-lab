# Technical Debt Ledger

Tracked, accepted debt in the multi-agent quant-research system. Each entry
records what the debt is, why it was accepted, the risk it carries, and where
it is scheduled to be paid down. Add to this file when a deliberate shortcut is
taken — do not let debt live only in PR comments.

| ID | Title | Status | Introduced | Scheduled |
|----|-------|--------|------------|-----------|
| TD-1 | Forward-return horizon treated as per-period | Open | M3 (pipeline), surfaced in M5 | Roadmap → "Horizon-correct returns" (post-M5) |
| TD-2 | `protocol.py` is a single shared god-module | Open | M1 | Unscheduled |
| TD-3 | Hardcoded signal-resolution defaults (Designer/Commander) | Open | M4 | With M6 idea generator |
| TD-4 | `promote_or_combine` is a dead recommendation label | Open | M4 | When signal-library lifecycle lands |

---

## TD-1 — Forward-return horizon treated as per-period

**What.** The cross-sectional pipeline computes portfolio returns as
`weight × fwd_ret_5` grouped by date, where `fwd_ret_5` is a **5-day forward
return**. These overlapping 5-day returns are then fed to `compute_metrics`
and annualised with `periods_per_year = 252` as if each row were an
independent daily return.

**Consequence.**
- Annualised figures (Sharpe, CAGR, vol) assume 252 independent periods, but
  5-day overlapping returns are serially correlated and not daily — so the
  annualisation basis is internally inconsistent.
- The magnitudes are usable for **relative** comparison between experiments
  (every experiment shares the same convention) but are **not** correct
  absolute investability numbers.

**Why accepted (M5).** M5's scope was net-of-cost metrics and robustness, not
return-horizon semantics. Critically, M5 computes turnover, costs, and the net
return series on the **same cadence** as the existing gross series, so
**net stays consistent with gross** and the gross/net comparison is valid.
Refactoring the horizon would have changed every existing gross number and
broken the M1–M4 backwards-compatibility guarantee inside an unrelated PR.

**Risk if left.** Anyone reading absolute Sharpe/CAGR as real deployable
figures will be misled. Rolling-performance and deflated-Sharpe work (roadmap)
depends on a correct period definition, so this should be paid down *before*
the formal-statistics milestone.

**Resolution sketch.** Introduce explicit horizon-aware returns: either
non-overlapping holding-period returns, or per-day returns derived from the
held book, with an annualisation basis that matches the chosen period. Do this
as its own milestone with a full re-baseline of stored gross metrics, not as a
side change.

**Do not** refactor horizon semantics inside M5.

---

## TD-2 — `protocol.py` god-module

Every agent imports the same dataclass module. Fine now; will become a
merge-contention and message-versioning hazard as message shapes evolve.
Resolution: split per-bounded-context or introduce versioned message schemas.

## TD-3 — Hardcoded signal-resolution defaults

The Designer's default signal sets and the Commander's keyword scan against
`KNOWN_SIGNALS` are brittle string matching. To be made data-driven alongside
the M6 idea generator, which will need a richer signal-feasibility check anyway.

## TD-4 — `promote_or_combine` dead label

The Ledger writes the string `promote_or_combine` as a recommendation but
nothing consumes it. Becomes real when the signal-library lifecycle
(promote/combine/retire) is implemented in a later milestone.
