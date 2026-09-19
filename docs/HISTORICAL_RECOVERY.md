# Historical Strategy Recovery

Recovers the historical strategies of **Projects 03–06** into the factory as new,
append-only research — via a **curated, operator-reviewed manifest** and a thin
`HypothesisSource`. It adds no research logic, no new agent, and changes no
statistical methodology; it only *enumerates* the reviewed manifest and enqueues
`pending` ideas through the existing approval → Designer → executor → M11 → Project 07
pipeline. **Nothing runs until the operator approves the enumeration and explicitly
launches a campaign.**

## Scope (confirmed against the repo)

- **Project 01** does not exist (no directory, notebooks, or git history).
- **Project 02** ("volatility regime") was done, but its artifacts are **not in this
  repo** — it survives only as an external dependency referenced by P04/P05. It is
  therefore out of recovery scope (nothing here to recover from it).
- **Projects 03–06** are in scope. **Project 07** is the authoritative statistical
  evaluator (the hand-off boundary), not a strategy source.

## The manifest (the review gate)

`agents/recovery/historical_strategies.json` is the single source of truth for *which*
strategies exist. It is grounded in `experiments/completed/*/config.*` +
`results_summary.md` + `strategy_comparison.csv`, one entry per strategy with:
`strategy_id`, `project`, `experiment_id`, `kind`
(`baseline`/`blend`/`overlay`/`deployment`), `hypothesis`, `signals`, `market`,
`universe`, `bar_type`, `alt_bar_eligible`, and a `mapping_status`:

- `clean` — features are registerable factory signals (e.g. P03 SPY-direction).
- `ml_model` — an ML return-forecast (P04 LS20/LS30/blends); its forecast signal must
  be added to the signal library before execution.
- `overlay` / `deployment` — a risk (P05) or robustness (P06) layer, not a standalone
  alpha hypothesis.

`mapping_status` is advisory metadata for review — it does **not** gate enumeration.
Edit the manifest freely; the machinery reads it generically (no code change needed).

## Verifying enumeration (before any run)

```bash
quant recovery list       # every strategy in the manifest
quant recovery verify     # coverage per project 03-06; non-zero exit if incomplete
```

`verify` is the step-4 pre-launch gate: it confirms every in-scope project is
represented and prints the full strategy list. Current draft enumerates **9**
strategies — P03×1 (baseline), P04×6 (2 baseline LS + 4 blends), P05×1 (overlay),
P06×1 (deployment).

## Templates and campaigns

`agents/recovery/templates.py` builds three DRAFT campaigns (all
`campaign_type = historical_recovery`), instantiated via the existing
`CampaignManager`:

| Template | Scope | Recovers |
| --- | --- | --- |
| `baseline` | `{recovery_kind: baseline}` | the baseline strategies at native (time) bars |
| `altbar`   | `{recovery_kind: baseline, bar_types: [time, volume, dollar]}` | each alt-bar-eligible baseline, once per clock |
| `blend`    | `{recovery_kind: blend}` | the LS20+LS30 blends |

```bash
quant recovery create baseline    # DRAFT; prints exactly what it will recover
quant recovery create altbar
quant recovery create blend
```

`create` leaves the campaign **DRAFT** and prints the strategies it would recover.
Launching (activate + run) is a separate, deliberate step.

## Advancing recovered ideas (the human gate)

A recovery tick's `generate` phase does two things per recovered strategy, mirroring
the ResearchStrategist: it **registers a root `hypothesis_node`** (so the strategy is a
first-class M11 hypothesis) and **enqueues a `pending` idea** linked to that node. So
after one tick you see, e.g., *3 hypotheses (nodes) + 3 pending ideas + 0 experiments*.

Zero experiments is **expected** — the human approval gate. Only `approved` ideas are
dispatched/executed (recovered ideas are never auto-approved). To advance the queue:

```bash
quant idea list                       # the pending recovered ideas
quant idea approve <idea_id>          # human decision → executable pool
quant campaign run <campaign_id>      # a tick dispatches + executes approved ideas
```

On execution the loop stamps the experiment back onto the idea's hypothesis node, and
M11 records evidence against it (then Project 07 evaluates, authoritatively). Reject an
idea with `quant idea reject <idea_id>`.

## Immutable origin provenance

Every recovered hypothesis carries an **immutable origin-provenance record** so it stays
permanently traceable to its exact source. It reuses existing storage — no new tables:

- **Per hypothesis/idea** — the record is written **write-once** into the existing
  `pending_ideas.metadata` JSON at enqueue (`metadata.provenance`). Experiments and
  evidence reference the idea by id, so the whole downstream chain resolves through one
  lookup (no duplication).
- **Per campaign** — the recovery campaign's genesis-event `scope` carries
  `recovery_manifest_version` (append-only, immutable).

Fields: `origin_project`, `origin_repository`, `origin_commit`, `origin_branch`,
`origin_notebook`, `origin_artifact`, `origin_strategy_name`,
`recovery_manifest_version`, `recovery_timestamp`, `vendored_snapshot` (+ `vendored_path`
and `origin_bar_type`). For **Project 02** these point at the vendored notebook **and**
the authoritative external GitHub repo/commit (read from the snapshot's
`provenance.json`); for in-repo projects (03-06) they point at the quant-lab experiment.

**Determinism:** `recovery_timestamp` is the campaign's own `created_at` (an existing,
immutable value), not a fresh wall-clock read — so replay never regenerates it. The
source converges (skips already-proposed candidates), so provenance is never rewritten.

Inspect a hypothesis's origin: `quant recovery provenance <idea_id>`.

## Determinism & isolation

The source enumerates in sorted manifest order, sorts alt-bar clocks, and skips
already-proposed `(bar_type, hypothesis)` pairs, so it converges (each candidate once)
and re-ticking the same state proposes nothing new. Ideas are `pending` (human gate
intact). Append-only storage, deterministic replay, and the Project 07 boundary are
preserved; there is no Chrysos coupling.
