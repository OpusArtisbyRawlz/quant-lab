# Historical Strategy Recovery — source of truth

This directory holds the **human-readable, reproducible report** for the Historical
Strategy Recovery program (Projects 02–06).

## What this is

- **`HISTORICAL_STRATEGY_RECOVERY.ipynb`** — the report. It reads stored evidence and
  regenerates every table: the complete strategy inventory, the counts, the fidelity
  results, the Project 07 handoff status, the blockers, and the progress dashboard.
- **`recovery_inventory.py`** — the shared, testable enumeration logic the notebook
  imports (reading the result CSVs, project summaries, recovery manifest, and factory DB).

## What this is NOT

This is **not** a replacement for the database, the recovery manifest
(`agents/recovery/historical_strategies.json`), the campaign/event log, or the provenance
system. Those remain the authoritative sources. This notebook only *reads and summarizes*
them, so the numbers you see are always derived from stored artifacts — never hand-typed.

## Design rules

- **Reproducible.** Re-run the notebook top-to-bottom to refresh; tables regenerate from
  artifacts. Static explanatory prose is fine; final metrics are not hard-coded.
- **Evidence-backed.** Every candidate row points at a concrete `source_file`. Nothing is
  inferred; abandoned variants are enumerated, not collapsed into the one that was selected.
- **Graceful.** The raw `data/` tree and the factory DB are git-ignored; when an artifact
  is absent the corresponding rows are simply omitted, so the notebook runs on any checkout.

## How to run

```bash
cd research/historical_recovery
PYTHONPATH=../.. jupyter nbconvert --to notebook --execute --inplace \
  HISTORICAL_STRATEGY_RECOVERY.ipynb
# or open it in Jupyter and Run All
```

Quick count without Jupyter:

```bash
PYTHONPATH=../.. python recovery_inventory.py
```

## Scope note

The inventory enumerates **materially distinct strategies actually tested** across Projects
02–06, including blends, transform variants, per-strategy overlay combinations, and
deployment challengers. The recovery *manifest* is a curated subset (the human-approved
recovery scope); the inventory is the full discovered set, so the two counts differ by
design.
