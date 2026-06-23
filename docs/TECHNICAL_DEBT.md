# Technical Debt Ledger

Tracked, accepted debt in the multi-agent quant-research system. Each entry
records what the debt is, why it was accepted, the risk it carries, and where
it is scheduled to be paid down. Add to this file when a deliberate shortcut is
taken — do not let debt live only in PR comments.

> **M10 PR-1 (Research Campaign foundation): no new debt.** The
> `research_campaign.budget_spent` counter is a deliberate, recoverable cache of
> a value always derivable from campaign-tagged experiments — not an accepted
> shortcut. It is documented as intentional design in `agents/TODOS.md` §7 so it
> is not later mis-logged here. PR-11 will add the TD-3 registry-seam entry.

> **M10 PR-3 (Campaign attribution linkage): no new debt.** Attribution is
> *derived* at read time from link keys that already exist
> (`pending_ideas.campaign_id` / `.experiment_id`, `hypothesis_node.campaign_id`
> / `.idea_id`); no campaign_id column is added to experiments, lessons, or
> observations, so the M7 execution path, the approval gate, and M9 evaluation
> are untouched. `link_idea_to_campaign` is write-once and the
> `campaign_attribution` module is read-only — see `agents/TODOS.md` §9. Because
> the anchors live on the ideas/hypotheses, attribution survives campaign-row
> deletion/rebuild; this is intentional design, not an accepted shortcut.

> **M10 PR-4 (ResearchStrategist + `bar_type` plumbing): no new debt.**
> `bar_type` is a first-class typed field migrated additively (`NOT NULL DEFAULT
> 'time'`) across `hypothesis_node` → `pending_ideas` → `ExperimentSpec` /
> `config.json` → `experiments`, so the path is complete and will *not* need a
> follow-up migration when the bar-construction engine lands. That engine is a
> deliberate, scoped deferral to a later milestone (not debt): the schema and
> interfaces are complete now, and the runner currently only realizes `time`
> bars; non-time `bar_type` ideas are representable, queueable, and auditable but
> not yet executable. The `research_strategist` is deterministic, reads M9 +
> campaign state read-only, and writes only hypothesis nodes/edges and `pending`
> ideas through the existing approval queue — the human gate and the M7/M9 cores
> are untouched.

> **M10 PR-2 (Hypothesis evolution tree): no new debt.** `hypothesis_node` /
> `hypothesis_edge` are append-only and storage-reconstructible (see
> `agents/TODOS.md` §8). The two write-once link columns (`idea_id`,
> `experiment_id`) are stamps applied after creation elsewhere, not mutations of
> the hypothesis, so node auditability is preserved.

| ID | Title | Status | Introduced | Scheduled |
|----|-------|--------|------------|-----------|
| TD-1 | Forward-return horizon treated as per-period | Open | M3 (pipeline), surfaced in M5 | Roadmap → "Horizon-correct returns" (post-M5) |
| TD-2 | `protocol.py` is a single shared god-module | Open | M1 | Unscheduled |
| TD-3 | Hardcoded signal-resolution defaults (Designer/Commander) | Open | M4 | With M6 idea generator |
| TD-4 | `promote_or_combine` is a dead recommendation label | Resolved by M9 | M4 | M9 context-aware signal lifecycle |
| TD-5 | Idea deduplication is exact-match only | Open | M6 | With semantic-similarity dedup (post-M7) |
| TD-7 | M6 feasibility validation skipped real-data checks | Resolved by M7 | M6 | M7 idea executor |
| TD-9 | Provenance stamped via post-run upsert, not at insert | Open | M7.1 | Next time the ingestion layer is touched |

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

## TD-4 — `promote_or_combine` dead label — Resolved by M9

The Ledger writes the string `promote_or_combine` as a recommendation but
nothing consumed it. **M9 (context-aware signal intelligence) activates the
lifecycle.** The SignalLibrarian runs after the Ledger, decomposes each
experiment into context cells (`feature × market × universe × regime ×
bar_type`), and drives a real `observed → candidate → promoted → retired`
lifecycle on `signal_library`, emitting an immutable `signal_lifecycle_events`
row on every transition. Promotion requires multi-context confirmation (≥2
distinct markets or regimes clearing the bar), so a single lucky context never
promotes a signal.

**Status.** Resolved by M9. No further work scheduled.

## TD-5 — Idea deduplication is exact-match only

**What.** The idea generator (M6) and the executor's pre-execution gate dedup
proposed ideas by **exact hypothesis-string equality** against prior
experiments and prior pending/approved ideas (`existing_hypotheses`,
`prior_idea_hypotheses`). Two hypotheses that are semantically identical but
worded differently ("momentum over 20 days" vs. "20-day price momentum") both
pass as distinct ideas.

**Why accepted (M6/M7).** Exact-match dedup is deterministic, keyless, and
needs no embedding model or vector store — keeping the idea pipeline runnable
offline and in tests. M7's scope is execution of *approved* ideas, not
upstream proposal quality; semantic dedup is a proposal-side concern.

**Risk if left.** As idea volume grows, near-duplicate ideas will consume human
approval attention and burn execution/runner cycles on effectively the same
experiment, inflating the ledger with redundant results.

**Resolution sketch.** Add an embedding-based similarity check (cosine over
sentence embeddings) with a tunable threshold, applied at validation time
alongside the exact-match gate. Gate behind the same feature flag as the
LLM-backed generator so the offline/test path stays exact-match only.

## TD-7 — M6 feasibility validation skipped real-data checks — Resolved by M7

**What (the debt).** M6 validated proposed ideas for *shape* (known signals,
non-empty hypothesis, dedup) but never confirmed that the idea's market /
universe actually had data on disk, because M6 deliberately stopped at the
approval queue and never touched the runner or data root.

**How M7 resolves it.** The idea executor re-validates every approved idea
against **real data** immediately before execution:
`idea_executor.run_single_approved_idea` builds the spec and calls
`validate_spec(spec, data_root=..., completed_dir=..., skip_data_check=(data_dict is not None))`.
In production (`data_dict_provider=None`) the data check runs against the real
data root; only injected synthetic `data_dict` test runs skip it — exactly as
the M5 runner does. A failure here transitions the idea to `rejected` with a
reason code (`universe_data_missing` / `signal_unavailable` /
`spec_invalid_after_revalidation`) rather than crashing, so an approved-but-
infeasible idea is recorded, not silently dropped.

**Status.** Resolved by M7. No further work scheduled.

## TD-9 — Provenance stamped via post-run upsert, not at insert

**What.** M7.1 stamps `experiments.source_idea_id` / `source_model` with an
`upsert_experiment` call issued **immediately after** `run_experiment` returns,
before Critic/Ledger run (`idea_executor.run_single_approved_idea`). This closes
the practically-relevant orphan window — the lesson is always written after
provenance exists, and an idea is linked to its experiment while still
`executing`. But the experiments row is still first created inside
`run_experiment` (via ingestion) without provenance, so a crash in the few
statements between row-insert and the follow-up upsert can still leave a
provenance-less row.

**Why accepted (M7.1).** Stamping at insert means threading `source_idea_id` /
`source_model` through `ExperimentSpec` → `write_config_json` → ingestion, which
touches the shared protocol dataclass (TD-2 surface) and the M5 ingestion path —
larger blast radius than the M7.1 reliability scope warranted. The post-run
upsert reduces the window to near-zero with a change isolated to the executor.

**Risk if left.** A process kill in a sub-millisecond window yields an
experiment row with NULL provenance; detectable via the orphan-experiment query
and repairable, but not impossible.

**Resolution sketch.** Add optional `source_idea_id` / `source_model` fields to
`ExperimentSpec`, persist them in `config.json`, and have ingestion write them
into the experiments row at insert time — removing the follow-up upsert
entirely. Do this the next time the ingestion layer is modified.
