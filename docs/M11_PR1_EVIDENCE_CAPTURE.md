# M11 PR-1 — Evidence Capture and Provenance

The first implementation slice of the frozen **M11 Research Intelligence** design
(`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`). It ships the *minimum durable
evidence layer*: reliable, auditable capture of evidence from finished
experiments. **It makes no promotion, retirement, confidence, or deployment
decision** — those belong to later M11 PRs that *read* what is captured here.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/storage/db.py` | modified | New `evidence_event` table; `SCHEMA_VERSION` 12 → 13; indexes. Additive only. |
| `agents/storage/evidence_store.py` | new | Pure storage for `evidence_event`: idempotent writer + read APIs. |
| `agents/research_intelligence/__init__.py` | new | M11 package surface (exports `EvidenceRecorder`). |
| `agents/research_intelligence/evidence_recorder.py` | new | Capture-only recorder: finished experiment → one immutable evidence event. |
| `agents/tests/test_evidence_capture.py` | new | 14 tests covering the 10 required proofs. |
| `docs/M11_PR1_EVIDENCE_CAPTURE.md` | new | This document. |

No changes to M7, M9, M10, the Bar Engine, the human approval gate, or
deployment logic. No existing rows are mutated. No decision logic is added.

## Schema — `evidence_event` (new table, additive)

One immutable, fully-provenanced row per **(experiment × evidence source)**. Every
column beyond the natural key is nullable, so legacy and partially-instrumented
experiments are representable without corruption.

Captured fields (where available): `hypothesis_id`, `experiment_id`,
`campaign_id`, `source_idea_id`, `source_model`, `market`, `universe`, `regime`,
`bar_type`, `feature_names` (JSON), `dataset_id`, `date_start`/`date_end`,
`evidence_source`, `methodology_version`, `stat_method_version`, `metrics`
(JSON), `robustness_flags` (JSON), `capacity_metrics` (JSON, from Project 06),
`critic_decision`, `provenance` (JSON), `created_at`.

**Evidence-source classification** (`evidence_source`, one of):
`in_sample`, `validation`, `embargo`, `walk_forward`, `holdout`, `live_paper`.

## Idempotency strategy

Natural key `UNIQUE (experiment_id, evidence_source)`, both columns `NOT NULL`
(with `evidence_source` defaulting to `in_sample`). The writer uses
`INSERT ... ON CONFLICT (experiment_id, evidence_source) DO NOTHING` and returns
`None` when the row already exists. Consequences:

- Re-recording the same finished experiment under the same source is a **no-op**
  — safe under re-runs and crash recovery (same guarantee as the existing
  event logs).
- Distinct evidence sources for one experiment are captured as **separate**
  rows, so a strategy accumulates in-sample, validation, walk-forward, holdout,
  and live-paper evidence side by side.
- Both key columns are `NOT NULL` deliberately: SQLite treats `NULL`s as
  distinct in a `UNIQUE` constraint, which would defeat idempotency.

## Architectural properties

- **Additive only** — a new table + a version bump; new-table creation is
  reconciled onto legacy DBs by `create_all_tables` (`CREATE TABLE IF NOT
  EXISTS`).
- **Event-sourced / append-only** — `evidence_event` is truth; nothing is
  updated in place.
- **Reconstructible** — a fresh DB + the same finished experiments reproduce the
  same evidence rows (modulo autoincrement id / wall-clock `created_at`).
- **Deterministic** — the recorder reads ledger + regime + hypothesis-node link
  and folds them into one row with no randomness.
- **Read-only against M7/M9/M10** — the recorder only *reads* `experiments`,
  `regime_label`, and `hypothesis_node`; it writes solely to `evidence_event`.

## Read APIs (for later M11 components)

`evidence_store`: `record_evidence`, `get_evidence`, `list_evidence`
(filter by experiment / hypothesis / campaign / source), `evidence_for_experiment`,
`evidence_sources_for`, `has_evidence`, `distinct_experiment_ids`, `count`.

## Sample evidence record

```json
{
  "id": 1,
  "experiment_id": "EXP-1",
  "hypothesis_id": "NODE-1",
  "campaign_id": "CAMP-7",
  "source_idea_id": "IDEA-9",
  "source_model": "claude",
  "market": "India",
  "universe": "NIFTY50",
  "regime": "low_vol",
  "bar_type": "time",
  "feature_names": ["mom_12_1", "vol_20"],
  "dataset_id": "ds-abc123",
  "date_start": "2020-01-01",
  "date_end": "2024-12-31",
  "evidence_source": "in_sample",
  "methodology_version": "m11-0",
  "stat_method_version": "none",
  "metrics": {"sharpe": 1.4, "net_sharpe": 1.1, "net_calmar": 0.8,
              "turnover_annualized": 3.2, "auc": 0.55},
  "robustness_flags": ["passes_subsample"],
  "capacity_metrics": {"capacity_usd": 5000000},
  "critic_decision": "keep",
  "provenance": {"project": "P11", "experiment_type": "portfolio",
                 "status": "completed"},
  "created_at": "2026-07-15T00:00:00+00:00"
}
```

## Required proofs → tests (`agents/tests/test_evidence_capture.py`)

1. One completed experiment creates one evidence event — `test_one_experiment_creates_one_evidence_event`.
2. Reprocessing does not duplicate — `test_reprocessing_is_idempotent`.
3. Provenance survives restart/reconstruction — `test_provenance_survives_restart`, `test_regime_and_hypothesis_link_captured`.
4. Evidence sources remain distinguishable — `test_evidence_sources_are_distinguishable` (+ `test_unknown_evidence_source_rejected`).
5. Legacy experiments representable without corruption — `test_legacy_experiment_minimal_fields` (+ `test_missing_experiment_raises`).
6. M7 execution unchanged — `test_m7_experiment_row_unchanged`.
7. M9 learning unchanged — `test_m9_signal_tables_unchanged`.
8. M10 research-loop behaviour unchanged — `test_m10_tables_unchanged`.
9. Full regression suite green + no decision columns — whole suite + `test_schema_has_evidence_event_table`, `test_legacy_db_gains_evidence_event_table`.
10. Clean checkout + fresh DB reproduce identical evidence — `test_deterministic_reproduction_across_fresh_dbs`.

## Explicitly NOT in this PR

No Bayesian posterior updating, confidence scores, credible intervals,
multiple-testing correction, deflated Sharpe, promotion, retirement, evidence
budgets, or prioritizer/strategist/scheduler/deployment changes. **This PR stores
evidence only.**
