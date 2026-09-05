# M11 PR-8 — Decision Consumption (decision_v1)

The eighth M11 slice — the design's **M11-4 (decision consumption)**: the existing
research agents begin consuming the M11 evidence projections instead of the coarse
M9 heuristic. **No new agent** is introduced; an existing agent gains the
responsibility.

**Scope confirmed with the reviewer:** the **Strategist** consumes evidence now
(it has a clean `node_id → hypothesis_state` join); the **Prioritizer** and
**Scheduler** are **deferred** because ideas/candidates carry no hypothesis link —
consuming per-hypothesis `b_h`/axes there needs a linkage threaded through
idea-generation → `pending_ideas` → candidates (a deeper M10/M7 data-model change),
which is out of scope for this PR.

The change to the Strategist (an M10 agent) is **additive and default-off**, so it
overrides the "no M10 changes" line **only** for `research_strategist`, and only
when explicitly enabled — behaviour is byte-identical to pre-PR-8 by default.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/decision.py` | new | Pure `decision_v1` policy: `EvidenceView` + `is_confirmed` / `is_refuted` / `does_generalise`. No DB, no RNG. |
| `agents/research_strategist/strategist.py` | modified | Consume the posterior/stage/retirement via the `node_id` join, behind `StrategistConfig.use_evidence` (default `False`). |
| `agents/research_intelligence/__init__.py` | modified | Export the `decision` module. |
| `agents/tests/test_decision_policy.py` | new | 10 pure-policy tests. |
| `agents/tests/test_strategist_evidence_consumption.py` | new | 6 integration + back-compat tests. |
| `docs/M11_PR8_DECISION_CONSUMPTION.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10 **other than the approved Strategist edit**, the Bar
Engine, the executor, approval, or deployment. No schema change. No evidence
mutated.

## `decision_v1` — evidence → agent predicates

A pure mapping from the M11 projections to the boolean signals the agents already
reason with, with bars aligned to the sibling engines so all actors agree:

- **confirmed** ⇔ `π_h ≥ 0.90` (== Promotion's Promising bar) **and** `μ_h > S0`
  **and** not retired.
- **refuted** ⇔ retirement state is `Retired-Refuted`, **or** `π_h ≤ 0.05`
  (== Retirement's ε_ref).
- **generalises** ⇔ `g_count ≥ 2` (== Validated's G_cnt).

It operates on an `EvidenceView` the caller loads; the policy itself touches no
database.

## Strategist consumption (additive, default-off, back-compatible)

- `StrategistConfig.use_evidence: bool = False`. **Default off ⇒ byte-identical to
  the pre-PR-8 M9-heuristic path** (all 40 existing strategist tests pass
  unchanged).
- When on, `_evidence_view(node_id)` loads the node's `hypothesis_state` (+
  `retirement_evaluation`) by the clean `node_id → hypothesis_id` join.
  `_confirmed` / `_refuted` decide via `decision_v1` when a view exists, and
  `_expandable` returns `False` for a retired node (a retired hypothesis is
  terminal — it stops expanding).
- **Old path recovered when evidence is absent:** a node with no posterior yet
  yields `None` from the view loader, so the predicate falls back to the M9
  `signal_context_performance` heuristic — evidence-on and evidence-off agree
  exactly for such nodes (tested).

## Deferred (needs a hypothesis linkage that does not exist yet)

- **Prioritizer** — ranks `pending_ideas`, which carry no `node_id`/`hypothesis_id`
  column, so the four-axis `ScoreBreakdown` components + budget cap cannot be
  joined to a hypothesis. Deferred until the linkage is threaded.
- **Scheduler** — admits by `campaign_id`, not hypothesis, so the per-hypothesis
  `b_h` has no candidate-level key. Deferred. (The evidence budget's quota-`accept`
  seam from PR-7 remains available once a linkage exists.)

## Architectural properties

- **No new agent** — an existing agent (Strategist) gains the responsibility; the
  decision logic is a pure policy module.
- **Additive / default-off** — the flag defaults to `False`; no schema change.
- **Deterministic / replay-safe** — the policy is a pure function; the strategist's
  evidence reads are deterministic by `hypothesis_id`.
- **Append-only evidence** — the Strategist only *reads* the projections; it
  mutates no evidence and no projection.
- **One-directional coupling** — the M10 agent imports the M11 policy + stores
  (consumption); `research_intelligence` does not import the strategist (no cycle).
- **Boundaries preserved** — no executor, Bar Engine, or other M10 agent touched;
  AST/boundary/import-closure guards green.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **No new agents** | Only `decision.py` (a policy module) added; the Strategist is extended, not replaced. |
| **Existing agent consumes projections + budget outputs** | Strategist reads `hypothesis_state` + `retirement_evaluation` (`test_confirmed_from_posterior`, `test_refuted_from_low_pi`, `test_retired_node_is_not_expandable_and_is_refuted`). |
| **Pure policy/process layer** | `decision_v1` is pure (`test_decision_policy.py`, 10 tests). |
| **Append-only evidence / no mutation** | Strategist only reads; no writes to evidence or projections. |
| **Deterministic replay** | Pure policy; deterministic reads by id. |
| **Back-compat (old heuristic when evidence absent)** | `test_no_posterior_falls_back_to_m9_heuristic`, `test_use_evidence_off_ignores_posterior`, `test_default_config_is_evidence_off`; all 40 pre-existing strategist tests pass unchanged. |
| **No changes to M7 / M9 / other M10 / Bar Engine** | Diff limited to `research_strategist` + the M11 package; no other agent/execution file modified. |
| **AST / boundary guards preserved** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **quant-lab / chrysos separation** | No Chrysos references; no cross-repo dependency. |
| **Full regression suite passing** | **1141 passed, 1 skipped** (pre-existing). +16 new tests; prior 1125 unchanged. |

## Critical self-review (findings addressed)

- **Replay** — `decision_v1` pure; strategist reads deterministic by id.
- **Evidence mutation** — none; strategist only reads the projections.
- **Hidden coupling** — the only new coupling is the intended, one-directional
  M10→M11 consumption (agent reads policy + stores); no import cycle.
- **Statistical leakage** — the view consumes posterior-derived signals
  (π/μ/g_count/retirement); no OOS/holdout data.
- **Complexity** — minimal: one default-off flag, optional `node_id` params, one
  view loader; no duplicated logic.
- **Reuse** — reuses `hypothesis_state_store` / `retirement_store` and the
  `decision_v1` policy; the deferred Prioritizer/Scheduler will reuse the same
  policy + PR-7's budget seam once a linkage exists.

## Explicitly NOT in this PR

Prioritizer `ScoreBreakdown` axis components + budget cap, Scheduler stage/budget
awareness, the idea→hypothesis linkage they require, the `assess` loop phase, and
hysteretic demotion — deferred. **This PR wires Strategist consumption only.**
