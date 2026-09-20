"""
Build the Project 04 recovery universe (deterministic, faithful date-scoping).

Project 04's authoritative strategy trades the ``v1 ∩ v2`` forecast panel
(2016-01-04 … 2026-03-06, 20 US equities). The factory executor recomputes features
and forward returns from raw OHLCV and scores the *entire* loaded panel, so running it
over the full 1970-2026 history would zero-pad every pre-2016 date (no forecast → no
position) and deflate the Sharpe by ~√(active/total). To reproduce the notebook's
2016-2026 result exactly, we scope the recovery universe to the strategy's own window.

This script copies ``data/raw/project_04_universe`` → ``data/raw/project_04_universe_recovery``
filtered to ``[START, end-of-data]`` where:

* ``START = 2015-12-03`` — ~20 trading days before 2016-01-04, exactly the feature
  warmup ``add_price_features`` needs, so ``dropna()`` trims the panel to begin at
  2016-01-04 with **no** leading zero-weight dates.
* the tail is **not** truncated — the raw data runs to 2026-03-13, and those five
  extra bars let ``add_forward_returns(horizon=5)`` compute a valid ``fwd_ret_5``
  through 2026-03-06 (their own rows then drop out, so no trailing zero-padding).

Result: the factory panel is exactly the 2558 authoritative dates, and the runner
reproduces LS20 Sharpe 1.5160 / MDD -0.6553 and LS30 Sharpe 1.4176 / MDD -0.5490.

Data lives under the git-ignored ``data/`` tree (repo convention); this builder is the
committed, reproducible source of truth. Run: ``python -m agents.recovery.build_p04_recovery_universe``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_UNIVERSE = _REPO_ROOT / "data" / "raw" / "project_04_universe"
RECOVERY_UNIVERSE = _REPO_ROOT / "data" / "raw" / "project_04_universe_recovery"

# 20 trading days before the first authoritative date (2016-01-04); consumed exactly
# by the feature warmup so the panel begins at 2016-01-04 with no zero-padding.
START = "2015-12-03"


def build(source: Path = SOURCE_UNIVERSE, dest: Path = RECOVERY_UNIVERSE) -> Path:
    if not source.exists():
        raise FileNotFoundError(
            f"Source universe not found: {source}. The raw data tree is git-ignored; "
            "restore data/raw/project_04_universe before building the recovery universe."
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files = sorted(source.glob("*.csv"))
    for f in files:
        df = pd.read_csv(f, parse_dates=["Date"])
        df[df["Date"] >= START].to_csv(dest / f.name, index=False)
    return dest


if __name__ == "__main__":  # pragma: no cover
    out = build()
    n = len(list(out.glob("*.csv")))
    print(f"Built {out} ({n} tickers, from {START}).")
