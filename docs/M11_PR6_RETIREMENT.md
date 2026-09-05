# M11 PR-6 — Retirement Track (retirement_v1)

The sixth implementation slice of the frozen **M11 Research Intelligence** design.
It implements methodology **§3.2 (retirement predicates)** — the first-class,
evidence-driven retirement track that runs parallel to promotion.

**It is a module/engine, not a new agent** (like the Posterior, Holdout, FDR, and
Promotion engines). It **consumes the existing posterior** and recomputes nothing;
retirement is a **stateless function of the current posterior**, so it is
replay-deterministic and reopens automatically when new evidence arrives.

Follows `docs/M11_STATISTICAL_METHODOLOGY.md` §3.2 (+ §10) and
`docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`.

## What this PR adds

| File | Kind | Responsibility |
| --- | --- | --- |
| `agents/research_intelligence/retirement.py` | new | Pure `retirement_v1` policy: `RetirementPolicy`, `evaluate_retirement`. No DB, no RNG. |
| `agents/research_intelligence/retirement_engine.py` | new | Pure fold: read the PR-2 posterior → apply the policy → write `retirement_evaluation`. |
| `agents/storage/retirement_store.py` | new | Storage for the `retirement_evaluation` projection. |
| `agents/storage/db.py` | modified | New `retirement_evaluation` table; `SCHEMA_VERSION` 17 → 18; indexes. Additive only. |
| `agents/research_intelligence/__init__.py` | modified | Export `RetirementEngine` and the `retirement` module. |
| `agents/tests/test_retirement_policy.py` | new | 10 pure-policy tests. |
| `agents/tests/test_retirement_engine.py` | new | 14 engine/replay/boundary tests. |
| `docs/M11_PR6_RETIREMENT.md` · `docs/M11_IMPLEMENTATION_STATUS.md` | doc | This document · status tracker. |

No changes to M7, M9, M10, the Bar Engine, approval, or deployment. No existing
rows mutated. No migration beyond the additive table.

## Scope — Retired-Refuted only (the other three deferred)

§3.2 defines four retirement states with sharply different dependency readiness.
PR-6 **fires only Retired-Refuted** — the sole state whose predicate and constants
are fully pinned by §10 and derivable from the current posterior:

    Retired-Refuted  ⇔  Pr(θ_h > S0) ≤ ε_ref (0.05)  AND  CI_high_h < S★ (0.5)

Both conditions are required: the posterior mass sits below break-even **and** even
the upper credible bound is below the economic bar — the edge is *affirmatively
absent*, not merely unproven. (A low-π hypothesis whose CI still clears S★, or a
weak-but-positive one with π > ε_ref, stays **Live**.)

The other three states are **modelled but deferred** — recognized lifecycle values
this policy never assigns yet, each blocked on a subsystem that does not exist and
each reported (with its reason) in every row's `detail.deferred`:

| Deferred state | Blocked on |
| --- | --- |
| **Retired-Decayed** | Platform-wide event-time decay in the posterior. The current decay clock is **per-hypothesis** (`rows_to_evidence` assigns Δ within each hypothesis's own evidence, so its newest experiment always has Δ=0 and full weight). A posterior never fades from staleness, so "once-supported" (many experiments ⇒ high n_eff) and the predicate's `n_eff < n_floor` are contradictory. Realizing it needs a posterior revision — out of scope. |
| **Retired-Saturated** | EVOI (§4 evidence budget) — PR-7, not built. |
| **Retired-Redundant** | A hypothesis novelty/similarity subsystem — not built. |

This scope was confirmed with the reviewer.

## Stateless determination → automatic reopen (§3.2)

Retirement is evaluated as a pure function of the **current** posterior, recomputed
on every rebuild. This is what makes reopen-on-new-evidence automatic and replay
safe: a Retired-Refuted hypothesis that later receives genuinely new evidence has
its posterior re-projected by the EvidenceProjector; the next retirement rebuild
sees π/CI lifted and returns **Live** — reproducible and auditable, with no hidden
transition state. (Verified by `test_reopens_when_new_evidence_lifts_posterior`.)

## Track composition (engines kept separate)

The RetirementEngine writes only its own `retirement_evaluation` projection and
imports **no other engine** (not promotion/holdout/fdr) and **no execution module**
— it reads only the PR-2 `hypothesis_state`. The Promotion Engine is untouched. The
two parallel lifecycle tracks (a hypothesis is in exactly one state) are **composed
downstream** by the orchestrating agent/reporter — retirement overrides promotion —
rather than by coupling the two engines. This preserves every architectural
boundary established in prior PRs.

Budget-freeze on retirement (§3.2/§4) is deferred to PR-7, where the evidence
budget exists to be frozen; PR-6 records the retirement determination that PR-7
will consume.

## Output — `retirement_evaluation` (new, additive, rebuildable)

A droppable cache, one row per hypothesis (PK `hypothesis_id`), versioned
`retirement_v1`: `retired`, `state`, `reason`, the deciding posterior snapshot
(`q_exceed_prob`, `ci_high`, `posterior_sd`, `n_eff`), `refuted`, `detail` (JSON:
fired predicate + deferred states), the policy snapshot (`epsilon_ref`, `s_star`),
`method`, `last_rebuilt_at`.

## Architectural properties

- **Module, not an agent** — a per-hypothesis pure fold; the research agents
  orchestrate it. No new agent introduced.
- **Additive only** — one new table + version bump (`CREATE TABLE IF NOT EXISTS`).
- **Deterministic / replay-safe** — stateless function of the posterior; rebuild
  idempotent, order-independent, prunes departed hypotheses.
- **Append-only evidence** — `evidence_event` never mutated; the evaluation is a
  rebuildable projection.
- **No recomputation / no leakage** — consumes π_h and CI_high verbatim from the
  posterior; runs no statistics and touches no OOS/holdout data.
- **Boundary-clean** — imports only `hypothesis_state_store` + the retirement
  policy; no engine-to-engine or execution coupling.

---

# Verification report

**Command:** `PYTHONPATH=/Users/rawls/quant-lab venv/bin/python -m pytest agents/tests/ -q`

| Requirement | Evidence |
| --- | --- |
| **Retirement is deterministic** | `evaluate_retirement` is a pure function (`test_is_a_pure_function`); engine rebuild idempotent (`test_rebuild_is_idempotent`). |
| **Replay-safe** | `test_projection_is_replay_deterministic_across_insertion_order`; `test_deterministic_rebuild_from_empty_database`. |
| **Append-only evidence / no mutation** | `test_evidence_events_are_never_mutated`. |
| **Consume existing posterior; do not recompute** | Reads only `hypothesis_state`; `test_retirement_does_not_touch_posterior`. |
| **M7 / Bar Engine unchanged** | No `experiment_runner/` or execution files modified. |
| **M9 / M10 unchanged; separate from Promotion** | `test_retirement_does_not_touch_m9_or_promotion`. |
| **Not a new agent; no new coupling** | RetirementEngine imports only `hypothesis_state_store` + the policy — no other engine, no execution. |
| **Boundary guards green** | bar-agnostic AST + boundary/executor + import-closure: **68 passed**. |
| **Full regression suite passing** | **1094 passed, 1 skipped** (pre-existing). +24 new tests; prior 1070 unchanged. |

### Behavioural checks demonstrated

- Strongly-negative hypothesis → **Retired-Refuted**; strong/weak positive → Live
  (`test_refuted_hypothesis_is_retired`, `test_strong_and_weak_positive_stay_live`).
- Both conditions required; ε_ref inclusive, S★ strict
  (`test_not_refuted_when_upside_remains`, `test_epsilon_ref_boundary_is_inclusive`,
  `test_s_star_boundary_is_strict`).
- **Reopen** on new evidence (`test_reopens_when_new_evidence_lifts_posterior`).
- Deferred states modelled with reasons, never fired
  (`test_deferred_states_are_modelled_but_never_fired`).
- Empty-DB rebuild; stale-row pruning on population change.

## Critical self-review (findings addressed)

- **Replay** — stateless posterior function; no transition state; rebuild
  idempotent + order-independent + prunes departed hypotheses.
- **Evidence mutation** — none; retirement writes only its own projection.
- **Hidden coupling** — none; imports only `hypothesis_state_store`; the two
  lifecycle tracks compose downstream, not via engine coupling.
- **Statistical leakage** — none; π_h/CI_high consumed verbatim; no OOS data.
- **Complexity / reuse** — minimal; a pure consumer of the PR-2 posterior, no
  evidence re-read and no duplicated math.
- **New agents** — none.

## Explicitly NOT in this PR

Retired-Decayed/Saturated/Redundant firing (deferred, see scope), evidence
budget/EVOI + budget-freeze (§4), the `assess` loop phase + append-only transition
log, hysteretic demotion, and the downstream lifecycle composition itself — all
later PRs. **This PR determines retirement (Refuted) only.**
