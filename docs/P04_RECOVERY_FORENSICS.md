# P04 recovery forensics — is the authoritative implementation still anywhere?

> ## ✅ RESOLVED / CORRECTION (2026-09-20) — the generator WAS in the repo
>
> This forensic report concluded the authoritative generator was **"not present in any
> locally reachable source"** and that recoverability "hinges entirely on Colab/Drive."
> **That verdict was wrong.** The generator was in the repository all along:
> `research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb`,
> cells 4 / 7 / 9 / 117-130.
>
> **What the search missed and why.** The candidate table below dismisses this very
> notebook ("its own stored outputs: Combined **1.115**, signal-weighted 1.234… never
> writes `ls_20pct.csv`"). The error: only its *early* cells and a couple of
> intermediate output cells were read. The authoritative LS20/LS30 construction lives in
> the **later** cells (117-130), which build `combined_signal = z(signal_v1) + z(signal_v2)`
> — where `signal_v1 = v1.pred_flipped` and `signal_v2 = v2.pred`, inner-joined on
> (Date, Ticker) — then rank per date and take top/bottom 20 % (LS20) / 30 % (LS30) with
> equal weights and `max_weight=0.05`. Those cells print exactly **"LS 20% Sharpe:
> 1.5159546527611567"** and **"LS 30% Sharpe: 1.4175863355279652"**. The `1.115` figure
> quoted below is a *different, earlier* combined variant in the same notebook, not the
> LS20 book. The generator was never missing; the reconstruction attempts simply used
> `pred_flipped` alone instead of the two-forecast combined signal.
>
> **Corrected status.** P04 is **fully recoverable and now recovered.** The two books are
> ported as `hist_p04_ls20_v1` / `hist_p04_ls30_v1` and replay through the *unmodified*
> factory runner to **LS20 Sharpe 1.5160 / MDD -0.6553** and **LS30 Sharpe 1.4176 / MDD
> -0.5490** — a bit-exact match to `strategy_comparison.csv`. No Colab/Drive search was
> needed. See `docs/P04_FIDELITY_ANALYSIS.md` for the corrected fidelity ladder.
>
> Everything below is the **original (superseded) forensic report**, preserved verbatim.

---

**Read-only forensic investigation. No code changed, nothing ported, no fixes.**
Goal: find the exact Project 04 implementation that produced the authoritative
`exp_004_project04_final` results (LS 20% Sharpe ≈ **1.516**), before touching factory
code.

## Verdict (summary)

The authoritative generator is **not present in any locally reachable source** — not in
git (any commit/branch/tag/reflog/stash/dangling object), not on local disk, not in any
GitHub repo. The committed P04 notebooks **cannot** produce 1.516 (their own stored
outputs top out at ~1.23; reproducible reconstructions ≤ 0.85). The `exp_004` folder is
an **output-only export** (its `predictions.csv` and `results_summary.md` have always
been 0 bytes). The single un-searched source is **Google Colab / Drive**, which was
**not reachable** from this session (Chrome extension not connected). **Do not yet
conclude "unrecoverable"** — pending a Colab/Drive check.

Pattern match: this is the same shape as Project 02 — an external build whose **output
artifacts** were downloaded into quant-lab while the **generator** lived elsewhere
(P02 → an external GitHub repo; P04 → most likely Colab).

## Sources searched & results

| Source | Scope searched | Result |
| --- | --- | --- |
| Git — commits/branches | 40+ local branches, all `origin/*`, `--all --full-history` | No P04 portfolio/backtest generator; only **consumers** (P05/P06) + output CSVs |
| Git — tags | `project-06-…`, `stable-m11-…` | None P04 |
| Git — reflog | `git reflog --all` | No P04 generator entries |
| Git — stashes | `stash@{0}` (4 files) | Only a P05 failure-analysis notebook |
| Git — dangling/unreachable | `fsck --dangling --unreachable` (13 objs) | Trees/commits/blobs = P05 notebook versions |
| Git — **entire object store** | **all 753 blobs**, content-grepped for `strategy_timeseries`+`to_csv` generator signatures | 2 candidates → both **P05 `01_drawdown_overlay.ipynb`** (consumers) |
| Local disk (home) | all `.git` repos + `rg` for `ls_20pct`/`strategy_timeseries`/`combined_signal` | Only `quant-lab`; `swing-research-terminal` (no P04); no P04 notebooks |
| GitHub (`gh`) | all 4 repos | `quant-lab`, `spy-risk-volatility-model` (P02), `equity-direction-prediction` (P03), `desktop-tutorial` — **no P04 repo** |
| Shell history | `~/.zsh_sessions/*` | No generator command/path |
| **Google Colab / Drive** | — | **NOT searched — Chrome extension not connected** (in-app browser has no Google login) |

## Candidates found (with evidence & confidence)

| # | Candidate | What it is | Reproduces 1.516? | Confidence it is the generator |
| --- | --- | --- | --- | --- |
| 1 | `project_04/notebooks/04_portfolio_research.ipynb` | Portfolio research on `combined_signal = z(signal_v1=pred_flipped) + z(signal_v2=pred)` over v1∩v2 (2016–2026) | **No** — its own stored outputs: Combined **1.115**, signal-weighted **1.234**, capped 1.216, vol-target ~1.1–1.18; never writes `ls_20pct.csv`/`strategy_timeseries` | Low — closest committed relative, but numbers and outputs don't match |
| 2 | `03_model_training.ipynb` / `03_model_training_v2.ipynb` | Train the ML forecasts → `pred` (v1/v2) | N/A (produces predictions, not the portfolio series) | N/A — upstream of the gap |
| 3 | object-store blobs `8ea2d784`, `ee3682d1` | Prior versions of P05 `01_drawdown_overlay.ipynb` | No — **consume** P04's `ls_20pct.csv` | None — consumers |
| 4 | `exp_004_project04_final/` artifacts | Published **outputs**: `strategy_timeseries/*.csv`, `strategy_comparison.csv` (LS 20% = 1.516), `metrics.json`, `config.yaml`; **`predictions.csv` & `results_summary.md` = 0 bytes** | is the target, not a generator | — (output only; partial export) |
| 5 | GitHub `equity-direction-prediction` | P03 (SPY direction) exploration | No (P03) | None |
| 6 | GitHub `spy-risk-volatility-model` | P02 vol-regime | No (P02) | None |

## Exact differences (measured; see `P04_FIDELITY_ANALYSIS.md`)

| Construction | Window | Sharpe | Corr to authoritative `ls_20pct` |
| --- | --- | --- | --- |
| **Authoritative `ls_20pct.csv`** | 2016–2026 | **1.516** | 1.00 (self) |
| Notebook `combined_signal` (v1_z+v2_z), equal | 2016–2026 | **1.115** (its own stored output) | not measured (needs df_combined) |
| `src` equal-weight LS20 on `pred_flipped` (v1) | 2016–2026 | 0.529 | ≈ 0.10 |
| Factory replication, active only | 2016–2026 | 0.847 | — |
| Factory as executed (full 1970–2026) | full | 0.360 | — |

No committed construction reaches 1.516; the authoritative series' *return convention*
matches (overlapping 5-day; lag-1 autocorr 0.69) but its *basket* (higher mean, lower
vol) does not correspond to any committed signal/weighting.

## Answers to the specific questions

- **Which notebook generated the published LS20 series / `ls_20pct.csv`?** Unknown — **no
  generator exists in git, local disk, or GitHub**. The one committed portfolio notebook
  (`04_portfolio_research`) does not write those files and yields ≤1.23, not 1.516.
- **Multiple versions?** Yes upstream: v1 & v2 forecast models (`03_model_training[_v2]`)
  and the `04_portfolio_research` exploration (combined signal, 1.115). The published
  `exp_004` LS 20% (1.516) is a **distinct, higher-scoring construction not among them**.
- **Which version matches the published metrics?** **None** found.
- **Still exists / deleted / Colab-only / other repo?** Not tracked in git at any point
  (so not "git-deleted" — it was never committed); not in any local or GitHub repo. Most
  consistent with an **uncommitted local notebook (now gone) and/or Colab**.

## Is Project 04 fully recoverable?

**Not from any source reachable in this session.** Recoverability now hinges entirely on
**Colab/Drive**, which could not be searched (Chrome extension offline). If the
authoritative generator is not in Drive/Colab either, P04's exact 1.516 construction is
**not recoverable** and would be genuinely under-specified.

### Precisely what is missing
The notebook/script that turns the forecasts (`v1.csv`/`v2.csv`) into the published
`ls_20pct.csv`/`ls_30pct.csv`/`strategy_timeseries` at Sharpe 1.516 — specifically its
exact **signal transform, cross-sectional selection, weighting, any capping/neutral:ation,
and backtest parameters**. Everything downstream of that (the resulting CSVs, and the P05/
P06 consumers) is present; the construction step itself is not.

## Remaining action to close the investigation (no code changes)

Search **Google Drive + Colab** (read-only) for the generator, using these terms/filenames:
`ls_20pct`, `ls_30pct`, `strategy_timeseries`, `portfolio_research`, `project_04`,
`return_forecast`, `combined_signal`, `signal_v1`, `pred_flipped`, `blend_60_40`,
`exp_004`. In Colab: **File → Open notebook → Recent / Google Drive**, and Drive search
`type:notebook return forecast` / `owner:me project 04`. This requires the Claude-in-Chrome
extension connected and signed in (or the user to run the Drive/Colab search directly).
Until then the investigation is **complete for all local/git/GitHub sources (negative)**
and **pending only on Colab/Drive**.
