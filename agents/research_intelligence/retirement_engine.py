"""
RetirementEngine — project the §3.2 retirement track (M11 PR-6).

For each hypothesis, the engine reads its PR-2 ``hypothesis_state`` posterior
(π_h, CI_high — plus σ_h / n_eff for the audit snapshot), applies the pure
``retirement_v1`` policy, and writes one ``retirement_evaluation`` row.

It is a **pure fold**: retirement is a stateless function of the current
posterior, so a rebuild is idempotent, replay-stable, and reopens automatically
(new evidence → updated posterior → next rebuild returns ``Live``). It
**recomputes no statistics** (consumes the posterior verbatim), mutates no
evidence, and writes no promotion decision — the two lifecycle tracks are composed
downstream, keeping this engine fully separate from the Promotion Engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import hypothesis_state_store, retirement_store
from .retirement import (
    DEFAULT_POLICY, RetirementPolicy, RetirementInputs, evaluate_retirement,
)


class RetirementEngine:
    def __init__(self, db_path: Path = DB_PATH,
                 policy: RetirementPolicy = DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.policy = policy

    def rebuild_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Recompute and persist the retirement determination for one hypothesis.

        Returns the written row, or ``None`` if the hypothesis has no posterior.
        """
        st = hypothesis_state_store.get_hypothesis_state(
            hypothesis_id, db_path=self.db_path)
        if st is None:
            return None

        result = evaluate_retirement(
            RetirementInputs(
                hypothesis_id=hypothesis_id,
                q_exceed_prob=st["q_stat_prob"],
                ci_high=st["ci_high"],
                posterior_sd=st["posterior_sd"],
                n_eff=st["n_eff"],
            ),
            self.policy,
        )

        row = {
            "hypothesis_id": hypothesis_id,
            "retired": 1 if result.retired else 0,
            "state": result.state,
            "reason": result.reason,
            "q_exceed_prob": st["q_stat_prob"],
            "ci_high": st["ci_high"],
            "posterior_sd": st["posterior_sd"],
            "n_eff": st["n_eff"],
            "refuted": 1 if result.refuted else 0,
            "detail": result.detail(),
            "epsilon_ref": self.policy.epsilon_ref,
            "s_star": self.policy.S_star,
            "method": result.method,
        }
        retirement_store.upsert_retirement(row, db_path=self.db_path)
        return row

    def rebuild_all(self) -> list[str]:
        """Rebuild retirement for every hypothesis with a posterior.

        Returns the hypothesis_ids evaluated. Prunes rows for hypotheses whose
        posterior has left the projection.
        """
        states = hypothesis_state_store.list_hypothesis_states(db_path=self.db_path)
        current_ids = {st["hypothesis_id"] for st in states}

        for existing in retirement_store.list_retirements(db_path=self.db_path):
            if existing["hypothesis_id"] not in current_ids:
                retirement_store.delete_retirement(
                    existing["hypothesis_id"], db_path=self.db_path)

        rebuilt: list[str] = []
        for hid in sorted(current_ids):
            if self.rebuild_hypothesis(hid) is not None:
                rebuilt.append(hid)
        return rebuilt
