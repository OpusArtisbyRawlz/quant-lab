# modernized/ — reserved

Intentionally empty for now.

This directory is reserved for a **later, reproducible/automated implementation** that
reproduces the vendored historical notebook
(`../notebooks/spy_volatility_regime_model.ipynb`) **exactly** — same features
(`RV5_trail`, `RV20_trail`, `RV5_fwd_ann`, `VolRatio`), same two-stage
regression→logistic-calibration model, same walk-forward / out-of-fold structure, and
a matching `vol_regime_calibrated_oof.csv` — **before** any methodological change is
made.

Nothing here modifies the historical record: the vendored notebook and artifact stay
byte-for-byte faithful. Reproducibility verification (replay) will land in a separate
PR; until then Project 02 is `recovered_source`, `replayable: pending`.
