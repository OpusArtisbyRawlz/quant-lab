# Known Limitations — Milestone 2 (Quant Interface Layer)

This file documents known gaps and design decisions deferred from Milestone 2.
Each item is intentional: the code handles the case gracefully (warning, skip,
or fallback) rather than raising. Future milestones can address them as needed.

---

## 1. YAML Config Parsing Requires PyYAML

**File:** `agents/quant_interface/artifact_reader.py` — `_parse_yaml_safe()`

PyYAML is not installed in this project. If an experiment folder contains
`config.yaml` instead of `config.json`, the reader will log a warning:

> `config.yaml: PyYAML not installed — config.yaml cannot be parsed.`

The bundle is still returned with `config=None` and all other fields populated.

**Fix:** `pip install pyyaml` and add to `requirements.txt`.
All existing experiments use `config.json` so this is low priority.

---

## 2. Nested Artifact Traversal Not Supported

**File:** `agents/quant_interface/ingestion.py` — `ingest_all_completed()`

`ingest_all_completed()` only scans the **direct children** of `experiments/completed/`.
Experiment folders whose artifacts live in subdirectories (e.g. a `results/` subfolder
inside the experiment directory) are not traversed.

**Observed cases:**
- `exp_005_risk_engine_v1` — artifacts in subdirectory, skipped
- `exp_006_failure_analysis` — artifacts in subdirectory, skipped

**Fix:** Add optional recursive traversal with depth limit, or define a convention
(e.g. flatten all artifacts into the root of each experiment folder).

---

## 3. Experiment Type Taxonomy Is Heuristic

**File:** `agents/quant_interface/artifact_reader.py` — `detect_experiment_type()`

Type detection is based on metric key-set intersection and config model-name hints.
It is a best-effort heuristic, not ground truth. Known edge cases:

- An experiment reporting both `sharpe` and `auc` will be classified as
  `classification` (classification keys take priority over portfolio keys).
- A portfolio experiment whose `config.json` contains `"model": "exposure_weighted"`
  will be classified as `risk_overlay` due to the config name hint.
- Experiments with no metrics, no config, and only a summary text will be `unknown`.

**Fix options:**
- Add an explicit `type` field to `config.json` per experiment.
- Allow human/agent override via `upsert_experiment({"experiment_type": "..."})`.
- Add a `--force-type` flag to `ingest_one()`.

---

## 4. Classification and Regression Metrics Not Mapped to Named Columns

**File:** `agents/quant_interface/ingestion.py` — `_upsert_from_bundle()`

By design, `sharpe`, `mdd`, `cagr`, `vol`, and `calmar` columns in the
`experiments` table are left `NULL` for classification and regression experiments.
All native metrics are stored in the `raw_metrics` JSON column instead.

This means queries like `ORDER BY sharpe DESC` will exclude classification and
regression experiments. Agents that need to rank across all experiment types must
parse `raw_metrics` and use the appropriate metric for each type.

**Fix:** Add type-specific metric columns to the schema, or add a `primary_metric_value`
float column populated with the most relevant metric per type (AUC for classification,
R² for regression, Sharpe for portfolio, Calmar for risk overlay).

---

## 5. Empty Experiments Folder in exp_004

`exp_004_return_forecast_alpha` was skipped during real ingestion because all
files present were empty (0 bytes). This is correct behaviour — the bundle is
flagged `is_empty` and the ingest result is `status="skipped"`.

No code change needed. The experiment should be re-run or its artifacts manually
populated before ingestion.

---

## 6. Signal Library Promotion Is Manual Only

**File:** `agents/quant_interface/ingestion.py` — `get_unpromoted_variants()`, `mark_variant_promoted()`

Strategy variants ingested from `strategy_comparison.csv` are stored in
`strategy_variants` with `promoted_to_library=0`. Promotion to `signal_library`
requires an explicit call to `mark_variant_promoted()`.

No automated promotion logic exists yet. A Critic Agent or human decision is
required to evaluate each variant and trigger promotion.

**Future:** Milestone 3 (Critic Agent) should consume `get_unpromoted_variants()`
and apply keep/reject/retest logic before writing to `signal_library`.

**Update (M9):** Automated, context-aware promotion now exists. The
`SignalLibrarian` (`agents/signal_librarian/`) runs after the Ledger and drives a
real `observed → candidate → promoted → retired` lifecycle on `signal_library`,
keyed on context cells (`feature × market × universe × regime × bar_type`).
Promotion requires multi-context confirmation. The manual
`strategy_variants → mark_variant_promoted()` path above is independent and still
manual; unifying the two is unscheduled. See
`docs/M9_CONTEXT_SIGNAL_INTELLIGENCE.md`.

---

## 7. research_campaign Is a Rebuildable Projection (M10 PR-1)

**File:** `agents/storage/campaign_store.py`; `agents/campaign_manager/manager.py`

The campaign layer is event-sourced. `campaign_state_events` is append-only and
the **single source of truth** (it carries no FK, mirroring M9's
`signal_lifecycle_events`, so it outlives the row). `research_campaign` is a
rebuildable *projection*:

- **Authoritative state** = `reconstruct_state_from_events()` (latest event's
  `to_state`); `research_campaign.state` is only a cache. `transition()` judges
  legality against the log, never the cached column.
- **Authoritative config** is carried in the genesis event's evidence, so the
  row's static fields are reconstructible.
- **Authoritative progress** = `count_campaign_experiments()`
  (`pending_ideas.campaign_id` joined to a non-null `experiment_id`);
  `budget_spent` is a cache.

`CampaignManager.reconcile()` / `reconcile_all()` repair the projection from the
log after an interrupted transition (event appended, cache update missed) or a
deleted/missing row; `rebuild_from_events()` recreates the row outright. Startup
reconciliation should call `reconcile_all()`. This is intentional, recoverable
design — not debt.

The loop that keeps caches fresh and ties campaigns to the idea pipeline arrives
in later M10 PRs (PR-3 linkage, PR-7 `run_tick` STEP 0 recovery).

---

## 8. Hypothesis Tree Is Append-Only and Storage-Reconstructible (M10 PR-2)

**File:** `agents/storage/hypothesis_store.py`;
`agents/hypothesis_manager/manager.py`

`hypothesis_node` and `hypothesis_edge` are append-only. A node is an immutable,
fully-auditable record; it is never updated in place except for two write-once
link stamps (`idea_id`, `experiment_id`) applied when an idea/experiment is
created from it elsewhere — the hypothesis content itself is never mutated. Every
non-root node records its primary `parent_id`, `root_id`, `depth`, and the
`origin_operator` that produced it; every parent→child relationship is also an
explicit `hypothesis_edge` carrying the operator. `combine` is the one
multi-parent operator (a DAG): it writes one `combine` edge per merged parent
into a single child whose primary parent is the first.

`HypothesisTreeManager` is the sole writer; `reconstruct_tree` /
`reconstruct_forest` / `lineage` rebuild the structure purely from storage, with
tests proving lossless reconstruction and operator preservation.

**Not yet wired:** nodes are not yet generated by the IdeaGenerator or linked
into the campaign loop — that arrives in PR-3 (campaign/idea linkage) and PR-4
(ResearchStrategist drives the operators). The `signals` inheritance on `evolve`
is a convenience default, not a feasibility check; signal validity is still
enforced downstream by the existing M6 validator.
