"""
Probabilistic and Deflated Sharpe Ratio for Project 07.

Implements the Bailey–López de Prado framework for judging a Sharpe ratio while
accounting for (a) the number of trials that produced it, (b) the non-normality
of returns, and (c) the track-record length:

- **Probabilistic Sharpe Ratio (PSR)** — the probability that the true Sharpe
  exceeds a benchmark, given the observed Sharpe, sample length, skew and
  kurtosis.
- **Deflated Sharpe Ratio (DSR)** — PSR against a benchmark that is *inflated by
  the selection process*: the expected maximum Sharpe under the null across
  ``n_trials`` independent trials.
- **Minimum Track-Record Length (minTRL)** — the sample length required for a
  Sharpe to be significant at a target confidence.

These convert a raw, search-inflated Sharpe into a selection-aware probability.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Result of a Deflated-Sharpe evaluation.

    Attributes
    ----------
    observed_sharpe
        Non-annualised observed Sharpe ratio of the strategy.
    deflated_probability
        Probability the true Sharpe exceeds the selection-adjusted benchmark
        (i.e. the DSR). Values near 1 indicate a genuine edge; near 0.5 or below
        indicate the result is consistent with selection noise.
    expected_max_sharpe
        Expected maximum Sharpe under the null across ``n_trials`` trials — the
        benchmark the observed Sharpe must beat.
    n_trials
        Number of trials in the search family.
    skew, kurtosis
        Sample skewness and kurtosis used in the non-normality adjustment.
    n_observations
        Track-record length (number of return observations).
    """

    observed_sharpe: float
    deflated_probability: float
    expected_max_sharpe: float
    n_trials: int
    skew: float
    kurtosis: float
    n_observations: int


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    benchmark_sharpe: float = 0.0,
) -> float:
    """Probabilistic Sharpe Ratio: P(true Sharpe > ``benchmark_sharpe``).

    Uses the observed Sharpe, sample length, skewness and kurtosis to produce a
    probability rather than a point estimate.

    Parameters
    ----------
    returns
        Daily return series.
    benchmark_sharpe
        Non-annualised benchmark Sharpe to test against (default 0).

    Returns
    -------
    float
        Probability in ``[0, 1]``.

    Notes
    -----
    Implements the Bailey–López de Prado / AFML formula

    ``PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(T - 1)
                      / sqrt(1 - g3*SR_hat + ((g4 - 1)/4)*SR_hat^2) )``

    where ``SR_hat`` is the per-period (non-annualised) Sharpe, ``T`` the number
    of observations, ``g3`` the sample skewness, and ``g4`` the ordinary/Pearson
    kurtosis (Normal = 3). Pandas ``Series.kurt()`` returns *excess* kurtosis
    (Normal = 0), so ``g4 = returns.kurt() + 3``.

    Raises
    ------
    ValueError
        If ``benchmark_sharpe`` is not a finite number; if fewer than 4 valid
        observations remain; if the returns are non-numeric or contain non-finite
        values; if the standard deviation is zero or non-finite; or if the AFML
        denominator variance term is non-positive or non-finite.
    """
    if (
        isinstance(benchmark_sharpe, bool)
        or not isinstance(benchmark_sharpe, (int, float, np.integer, np.floating))
        or not np.isfinite(benchmark_sharpe)
    ):
        raise ValueError(
            f"benchmark_sharpe must be a finite number, got {benchmark_sharpe!r}"
        )

    returns = pd.Series(returns).dropna()

    if not pd.api.types.is_numeric_dtype(returns) or pd.api.types.is_bool_dtype(returns):
        raise ValueError(f"returns must be numeric, got dtype {returns.dtype!r}")

    n_obs = int(returns.shape[0])
    if n_obs < 4:
        raise ValueError(
            f"probabilistic_sharpe_ratio requires at least 4 valid observations, got {n_obs}"
        )
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError("returns contain non-finite values (NaN/Inf)")

    std = float(returns.std(ddof=1))
    if not np.isfinite(std) or std == 0.0:
        raise ValueError(f"return standard deviation must be finite and non-zero, got {std!r}")

    sr_hat = float(returns.mean()) / std          # per-period (non-annualised) Sharpe
    skew = float(returns.skew())                  # g3 (pandas sample skewness)
    kurtosis = float(returns.kurt()) + 3.0        # g4 ordinary/Pearson (Normal = 3)

    denom_var = 1.0 - skew * sr_hat + ((kurtosis - 1.0) / 4.0) * sr_hat ** 2
    if not np.isfinite(denom_var) or denom_var <= 0.0:
        raise ValueError(
            f"PSR denominator variance term must be positive and finite, got {denom_var!r}"
        )

    z = (sr_hat - float(benchmark_sharpe)) * np.sqrt(n_obs - 1) / np.sqrt(denom_var)
    return float(norm.cdf(z))


def expected_max_sharpe(
    *,
    n_trials: int,
    trial_sharpe_variance: float,
) -> float:
    r"""Expected maximum Sharpe under the null across independent trials.

    The selection-adjusted benchmark for the Deflated Sharpe Ratio: with more
    trials, the best Sharpe observed by chance alone rises. Implements the
    Bailey–López de Prado approximation

    ``SR* = sqrt(V) * [ (1 - g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N*e)) ]``

    where ``V`` is the cross-trial Sharpe variance, ``N`` the number of trials,
    ``g`` the Euler–Mascheroni constant, ``e`` Euler's number, and ``Phi^-1`` the
    standard-Normal inverse CDF.

    Parameters
    ----------
    n_trials
        Number of **independent / effective** trials in the family — *not*
        automatically the raw number of parameter combinations searched. Highly
        correlated variants (e.g. overlays of the same base book, or dense
        parameter-grid points) count as far fewer independent trials than their
        raw count; choose ``n_trials`` accordingly. Must be an integer > 1.
    trial_sharpe_variance
        Variance ``V[SR_hat]`` of the Sharpe estimates across trials. **Must be on
        the same scale as the Sharpe ratio that DSR will later test** (e.g.
        per-period if DSR is applied to a per-period Sharpe; annualised if
        annualised). Must be finite and non-negative.

    Returns
    -------
    float
        Expected maximum Sharpe under the null, on the same scale as
        ``trial_sharpe_variance``. Zero variance returns ``0.0``.

    Raises
    ------
    ValueError
        If ``n_trials`` is not an integer greater than 1, or
        ``trial_sharpe_variance`` is not a finite, non-negative number.
    """
    if (
        isinstance(n_trials, bool)
        or not isinstance(n_trials, (int, np.integer))
        or n_trials <= 1
    ):
        raise ValueError(f"n_trials must be an integer greater than 1, got {n_trials!r}")
    if (
        isinstance(trial_sharpe_variance, bool)
        or not isinstance(trial_sharpe_variance, (int, float, np.integer, np.floating))
        or not np.isfinite(trial_sharpe_variance)
        or trial_sharpe_variance < 0.0
    ):
        raise ValueError(
            "trial_sharpe_variance must be a finite, non-negative number, "
            f"got {trial_sharpe_variance!r}"
        )

    N = int(n_trials)
    gamma = np.euler_gamma          # Euler–Mascheroni constant (numpy, stable)
    e = np.e                        # Euler's number

    z = (1.0 - gamma) * norm.ppf(1.0 - 1.0 / N) + gamma * norm.ppf(1.0 - 1.0 / (N * e))
    return float(np.sqrt(trial_sharpe_variance) * z)


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    n_trials: int,
    trial_sharpe_variance: float,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio — PSR against the selection-inflated benchmark.

    Parameters
    ----------
    returns
        Daily return series of the selected strategy.
    n_trials
        Number of trials that were searched to find this strategy.
    trial_sharpe_variance
        Variance of Sharpe estimates across the trial family.

    Returns
    -------
    DeflatedSharpeResult
        The deflated probability and the benchmark it was tested against.

    Notes
    -----
    ``DSR = PSR(SR*_selection)`` where ``SR*_selection`` is the expected maximum
    Sharpe under the null across ``n_trials`` trials
    (:func:`expected_max_sharpe`). All Sharpe quantities are handled on the
    **per-period** scale: ``trial_sharpe_variance`` must therefore be the variance
    of *per-period* trial Sharpes, so that ``SR*`` lands on the same scale as the
    per-period Sharpe that :func:`probabilistic_sharpe_ratio` uses internally.

    ``n_trials`` must represent the number of **independent / effective** trials in
    the search, not the raw count of parameter combinations (near-duplicate
    variants count as far fewer independent trials). The caller must choose it
    explicitly — this function does not infer or default an effective ``N``.

    Raises
    ------
    ValueError
        Propagated from :func:`expected_max_sharpe` (invalid ``n_trials`` or
        ``trial_sharpe_variance``) and from :func:`probabilistic_sharpe_ratio`
        (invalid ``returns``).
    """
    # Multiple-testing-adjusted benchmark (per-period). Validates n_trials and
    # trial_sharpe_variance by reuse.
    sr_star = expected_max_sharpe(
        n_trials=n_trials,
        trial_sharpe_variance=trial_sharpe_variance,
    )

    # DSR = PSR evaluated against the selection-inflated benchmark. Validates
    # returns by reuse.
    deflated_probability = probabilistic_sharpe_ratio(returns, benchmark_sharpe=sr_star)

    # Descriptive fields for the result (returns already validated above).
    series = pd.Series(returns).dropna()
    observed_sharpe = float(series.mean()) / float(series.std(ddof=1))  # per-period
    skew = float(series.skew())
    kurtosis = float(series.kurt()) + 3.0                               # ordinary/Pearson

    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        deflated_probability=deflated_probability,
        expected_max_sharpe=sr_star,
        n_trials=int(n_trials),
        skew=skew,
        kurtosis=kurtosis,
        n_observations=int(series.shape[0]),
    )


def minimum_track_record_length(
    returns: pd.Series,
    *,
    benchmark_sharpe: float = 0.0,
    confidence_level: float = 0.95,
) -> float:
    """Minimum track-record length for significance at ``confidence_level``.

    Parameters
    ----------
    returns
        Daily return series.
    benchmark_sharpe
        Non-annualised benchmark Sharpe.
    confidence_level
        Target confidence.

    Returns
    -------
    float
        Required number of observations for the observed Sharpe to be
        significantly above ``benchmark_sharpe``.

    Notes
    -----
    Implements the Bailey–López de Prado / AFML minimum track-record length —
    the PSR formula inverted for the sample length ``T``::

        T_min = 1 + [1 - g3*SR_hat + ((g4 - 1)/4)*SR_hat^2] * (Phi^-1(c) / (SR_hat - SR*))^2

    with the same conventions as :func:`probabilistic_sharpe_ratio`: ``SR_hat`` is
    the per-period Sharpe, ``SR*`` (``benchmark_sharpe``) must be per-period,
    ``g3`` the sample skewness, ``g4`` the ordinary/Pearson kurtosis
    (``returns.kurt() + 3``), and ``c`` the ``confidence_level``. The raw
    real-valued ``T_min`` is returned (not ceiled); ``math.ceil`` it at the call
    site if a whole-number observation count is required.

    ``confidence_level`` should be above 0.5 for the one-sided "Sharpe above the
    benchmark" test (values in ``(0, 1)`` are accepted).

    Raises
    ------
    ValueError
        If ``benchmark_sharpe`` is not finite; ``confidence_level`` is not strictly
        in ``(0, 1)``; fewer than 4 valid observations remain; returns are
        non-numeric or non-finite; the standard deviation is zero or non-finite;
        the denominator variance term is non-positive or non-finite; or the
        observed Sharpe does not exceed ``benchmark_sharpe`` (no finite minimum
        track record exists in that case).
    """
    if (
        isinstance(benchmark_sharpe, bool)
        or not isinstance(benchmark_sharpe, (int, float, np.integer, np.floating))
        or not np.isfinite(benchmark_sharpe)
    ):
        raise ValueError(
            f"benchmark_sharpe must be a finite number, got {benchmark_sharpe!r}"
        )
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float, np.integer, np.floating))
        or not (0.0 < float(confidence_level) < 1.0)
    ):
        raise ValueError(
            f"confidence_level must be strictly in (0, 1), got {confidence_level!r}"
        )

    returns = pd.Series(returns).dropna()

    if not pd.api.types.is_numeric_dtype(returns) or pd.api.types.is_bool_dtype(returns):
        raise ValueError(f"returns must be numeric, got dtype {returns.dtype!r}")

    n_obs = int(returns.shape[0])
    if n_obs < 4:
        raise ValueError(
            f"minimum_track_record_length requires at least 4 valid observations, got {n_obs}"
        )
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError("returns contain non-finite values (NaN/Inf)")

    std = float(returns.std(ddof=1))
    if not np.isfinite(std) or std == 0.0:
        raise ValueError(f"return standard deviation must be finite and non-zero, got {std!r}")

    sr_hat = float(returns.mean()) / std          # per-period (non-annualised) Sharpe
    skew = float(returns.skew())                  # g3 (pandas sample skewness)
    kurtosis = float(returns.kurt()) + 3.0        # g4 ordinary/Pearson (Normal = 3)

    denom_var = 1.0 - skew * sr_hat + ((kurtosis - 1.0) / 4.0) * sr_hat ** 2
    if not np.isfinite(denom_var) or denom_var <= 0.0:
        raise ValueError(
            f"minTRL denominator variance term must be positive and finite, got {denom_var!r}"
        )

    gap = sr_hat - float(benchmark_sharpe)
    if gap <= 0.0:
        raise ValueError(
            "observed per-period Sharpe (%.6g) does not exceed benchmark_sharpe (%.6g); "
            "no finite minimum track record exists for proving the Sharpe is above the "
            "benchmark under the current estimate" % (sr_hat, float(benchmark_sharpe))
        )

    z = float(norm.ppf(float(confidence_level)))
    return float(1.0 + denom_var * (z / gap) ** 2)
