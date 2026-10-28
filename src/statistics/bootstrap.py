"""
Bootstrap resampling for performance-metric uncertainty (Project 07).

Backtest performance metrics (Sharpe, Calmar, CAGR, max drawdown) are point
estimates from a single, finite, autocorrelated return path. This module
quantifies their sampling uncertainty with resampling methods appropriate for
serially dependent financial returns — the **stationary bootstrap** (Politis &
Romano) and the **circular block bootstrap** — rather than the naive iid
bootstrap, which understates uncertainty for autocorrelated series.

Determinism: every routine takes an explicit ``seed`` and is fully reproducible;
the seed is recorded in the Evidence Ledger.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BootstrapResult:
    """Result of a bootstrap estimate for a single metric.

    Attributes
    ----------
    point_estimate
        The metric computed on the observed sample.
    ci_low, ci_high
        Lower/upper bounds of the confidence interval.
    confidence_level
        Nominal coverage (e.g. ``0.95``).
    n_resamples
        Number of bootstrap resamples used.
    method
        Resampling scheme (``"stationary"`` or ``"circular_block"``).
    seed
        RNG seed used.
    distribution
        The bootstrap distribution of the metric (length ``n_resamples``).
    """

    point_estimate: float
    ci_low: float
    ci_high: float
    confidence_level: float
    n_resamples: int
    method: str
    seed: int
    distribution: np.ndarray


def stationary_bootstrap_indices(
    n: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate one stationary-bootstrap index sample of length ``n``.

    **Why the stationary bootstrap.** Financial returns are serially dependent
    (volatility clustering, short-run autocorrelation), so the naive iid bootstrap
    — which resamples single observations independently — destroys that structure
    and understates the sampling uncertainty of path-dependent metrics. The
    stationary bootstrap (Politis & Romano, 1994) instead resamples *contiguous
    blocks* of observations, preserving short-range dependence, while randomising
    the block length so that the resampled series is itself (block-)stationary —
    unlike the fixed-length block bootstrap, whose fixed cut points break
    stationarity.

    **What ``p = 1 / expected_block_length`` means.** At every step we either
    extend the current block or start a new one. Starting a new block is a
    Bernoulli trial with success probability ``p = 1 / expected_block_length``.
    The resulting block lengths are geometrically distributed with mean
    ``expected_block_length``: small ``p`` (large expected block length) yields long
    runs that preserve more autocorrelation; ``p = 1`` (``expected_block_length =
    1``) starts a new block every step, reducing exactly to iid resampling.

    **Why circular wrapping.** When a block runs off the end of the series, the
    continuation index wraps to the front via ``(previous_index + 1) % n``. This
    lets a block that begins near the end reach full length and gives every
    observation an equal chance of appearing, removing the end-of-sample
    under-representation a non-wrapping scheme would introduce.

    **Output is indices, not returns.** This function returns positional indices
    into the original sample; the caller applies them (e.g. ``returns.iloc[idx]``)
    to build a resampled series. Keeping index generation separate makes it
    reusable across any metric and trivially reproducible from the supplied
    generator.

    Parameters
    ----------
    n
        Length of the index vector to produce (equals the length of the original
        sample). Must be a positive integer.
    expected_block_length
        Mean block length; must be strictly positive. Larger values preserve more
        serial dependence. A value of ``1`` reduces to iid resampling.
    rng
        A NumPy random ``Generator`` (e.g. ``np.random.default_rng(seed)``). All
        randomness is drawn from this object only; global NumPy random state is
        never touched, so output is fully reproducible for a given seeded generator.

    Returns
    -------
    numpy.ndarray
        A 1-D array of exactly ``n`` integer indices, each in ``[0, n - 1]``.

    Raises
    ------
    ValueError
        If ``n`` is not a positive integer, or ``expected_block_length`` is not a
        positive finite number.
    """
    if not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n <= 0:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    if (
        not isinstance(expected_block_length, (int, float, np.integer, np.floating))
        or isinstance(expected_block_length, bool)
        or not np.isfinite(expected_block_length)
        or expected_block_length <= 0
    ):
        raise ValueError(
            "expected_block_length must be a positive finite number, "
            f"got {expected_block_length!r}"
        )

    n = int(n)
    p = 1.0 / float(expected_block_length)

    indices = np.empty(n, dtype=np.intp)
    # Start the first block at a uniformly random position.
    indices[0] = rng.integers(n)
    for i in range(1, n):
        if rng.random() < p:
            # Start a new block at a uniformly random position.
            indices[i] = rng.integers(n)
        else:
            # Continue the current block, wrapping circularly at the end.
            indices[i] = (indices[i - 1] + 1) % n
    return indices


def stationary_bootstrap_sample(
    returns: np.ndarray,
    expected_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw one stationary-bootstrap synthetic return sample of the same length.

    Thin, deterministic wrapper over :func:`stationary_bootstrap_indices`: it
    generates one set of resampling indices and gathers the corresponding returns.
    Separating index generation (which strategy/metric to resample) from index
    *application* (this function) keeps the resampling scheme reusable and makes
    the sample fully reproducible from the supplied generator.

    The returned sample preserves short-range serial dependence exactly as the
    index generator does (random-length contiguous blocks with circular wrap); see
    :func:`stationary_bootstrap_indices` for the algorithm and the meaning of
    ``expected_block_length``.

    Parameters
    ----------
    returns
        A 1-D numeric array-like of returns (the original sample). Not mutated.
    expected_block_length
        Mean block length passed straight through to
        :func:`stationary_bootstrap_indices`; must be a positive finite number.
    rng
        A NumPy ``Generator``. All randomness is drawn from this object only; no
        generator is created internally.

    Returns
    -------
    numpy.ndarray
        A new 1-D float array of exactly ``len(returns)`` values, each drawn from
        the original sample.

    Raises
    ------
    ValueError
        If ``returns`` is not 1-D, is empty, or is non-numeric (or if
        ``expected_block_length`` is invalid, raised by the delegated index call).
    """
    arr = np.asarray(returns)
    if arr.ndim != 1:
        raise ValueError(
            f"returns must be a 1-D array, got {arr.ndim}-D with shape {arr.shape}"
        )
    if arr.size == 0:
        raise ValueError("returns must be non-empty")
    if not np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_):
        raise ValueError(f"returns must be numeric, got dtype {arr.dtype!r}")

    # Preserve float values without mutating the caller's array. Fancy indexing
    # below always returns a fresh array, so the input is never written to.
    values = np.asarray(arr, dtype=float)
    n = values.shape[0]

    indices = stationary_bootstrap_indices(
        n=n,
        expected_block_length=expected_block_length,
        rng=rng,
    )
    return values[indices]


def circular_block_bootstrap_indices(
    n: int,
    *,
    block_length: int,
    seed: int,
) -> np.ndarray:
    """Generate one circular-block-bootstrap index sample of length ``n``.

    Fixed-length blocks are drawn with wrap-around at the series end so every
    observation has equal resampling probability.

    Parameters
    ----------
    n
        Length of the index vector to produce.
    block_length
        Fixed block length.
    seed
        RNG seed.

    Returns
    -------
    numpy.ndarray
        Integer indices in ``[0, n)`` of length ``n``.
    """
    raise NotImplementedError("bootstrap resampling not implemented (scaffold).")


def bootstrap_metric(
    returns: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    n_bootstrap: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate the bootstrap sampling distribution of a performance metric.

    Repeatedly draws stationary-bootstrap resamples of ``returns`` (via
    :func:`stationary_bootstrap_sample`) and evaluates ``metric_fn`` on each,
    producing the empirical sampling distribution of the metric. This is the raw
    distribution only — confidence intervals and point summaries are computed
    separately (see :func:`bootstrap_confidence_interval`), keeping this a single,
    reusable engine that works for any scalar metric.

    Determinism: all randomness is drawn from the supplied ``rng``; the same
    seeded generator reproduces the same distribution. Each iteration consumes the
    generator in sequence, so iterations are distinct draws rather than repeats.

    Parameters
    ----------
    returns
        A 1-D numeric array-like of returns (the original sample). Not mutated;
        validation of shape/dtype is delegated to
        :func:`stationary_bootstrap_sample`.
    metric_fn
        Callable mapping a 1-D return sample to a scalar (e.g. a Sharpe or Calmar
        function). Called exactly ``n_bootstrap`` times, once per resample.
    n_bootstrap
        Number of bootstrap resamples to draw; must be a positive integer.
    expected_block_length
        Mean block length passed through to the stationary bootstrap; must be a
        positive finite number (validated by the delegated sample call).
    rng
        A NumPy ``Generator``. All randomness is drawn from this object only; no
        generator is created internally.

    Returns
    -------
    numpy.ndarray
        A 1-D ``float`` array of length ``n_bootstrap`` — one metric value per
        resample.

    Raises
    ------
    ValueError
        If ``n_bootstrap`` is not a positive integer, or ``metric_fn`` is not
        callable. (Invalid ``returns`` / ``expected_block_length`` are raised by
        the delegated :func:`stationary_bootstrap_sample` call.)
    """
    if not isinstance(n_bootstrap, (int, np.integer)) or isinstance(n_bootstrap, bool) \
            or n_bootstrap <= 0:
        raise ValueError(f"n_bootstrap must be a positive integer, got {n_bootstrap!r}")
    if not callable(metric_fn):
        raise ValueError(f"metric_fn must be callable, got {type(metric_fn).__name__}")

    n_bootstrap = int(n_bootstrap)
    distribution = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        sample = stationary_bootstrap_sample(
            returns=returns,
            expected_block_length=expected_block_length,
            rng=rng,
        )
        distribution[i] = metric_fn(sample)
    return distribution


def bootstrap_confidence_interval(
    distribution: np.ndarray,
    confidence_level: float = 0.95,
) -> tuple[float, float, float]:
    """Summarise a bootstrap metric distribution with a standard error and a
    percentile confidence interval.

    Given the sampling distribution returned by :func:`bootstrap_metric`, this
    computes the **bootstrap standard error** (the sample standard deviation of the
    distribution, ``ddof=1``) and the two-sided **percentile confidence interval**
    at ``confidence_level``. The percentile method takes the empirical quantiles of
    the distribution directly, making no normality assumption.

    For a coverage of ``confidence_level`` the tail mass is
    ``alpha = 1 - confidence_level``, split equally: the interval runs from the
    ``alpha / 2`` quantile to the ``1 - alpha / 2`` quantile.

    Parameters
    ----------
    distribution
        A 1-D array of bootstrap metric values (from :func:`bootstrap_metric`).
        Must be non-empty and contain only finite values. Not mutated.
    confidence_level
        Nominal coverage in the open interval ``(0, 1)`` (e.g. ``0.95``).

    Returns
    -------
    tuple of float
        ``(standard_error, lower_bound, upper_bound)``.

    Raises
    ------
    ValueError
        If ``distribution`` is not 1-D, is empty, or contains non-finite values
        (NaN/Inf), or if ``confidence_level`` is not strictly between 0 and 1.
    """
    arr = np.asarray(distribution)
    if arr.ndim != 1:
        raise ValueError(
            f"distribution must be 1-D, got {arr.ndim}-D with shape {arr.shape}"
        )
    if arr.size == 0:
        raise ValueError("distribution must be non-empty")
    try:
        all_finite = bool(np.isfinite(arr).all())
    except TypeError:
        raise ValueError(f"distribution must be numeric, got dtype {arr.dtype!r}")
    if not all_finite:
        raise ValueError("distribution must be finite (contains NaN or Inf)")
    if (
        not isinstance(confidence_level, (int, float, np.integer, np.floating))
        or isinstance(confidence_level, bool)
        or not (0.0 < float(confidence_level) < 1.0)
    ):
        raise ValueError(
            f"confidence_level must satisfy 0 < level < 1, got {confidence_level!r}"
        )

    standard_error = float(np.std(arr, ddof=1))

    alpha = 1.0 - float(confidence_level)
    lower_bound = float(np.percentile(arr, 100.0 * (alpha / 2.0)))
    upper_bound = float(np.percentile(arr, 100.0 * (1.0 - alpha / 2.0)))

    return standard_error, lower_bound, upper_bound


def paired_bootstrap_difference(
    a: np.ndarray,
    b: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    n_resamples: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Bootstrap distribution of a *paired* metric difference ``metric(a) - metric(b)``.

    ``a`` and ``b`` are two aligned, equal-length series (e.g. a challenger and the
    incumbent, indexed by the same dates). Each bootstrap replication draws **one**
    set of stationary-bootstrap indices (via :func:`stationary_bootstrap_indices`)
    and applies it to **both** series, so the contemporaneous dependence between
    ``a`` and ``b`` is preserved — the correct design for a paired test. The two
    series are never resampled independently.

    This is metric-agnostic: pass any callable that maps a 1-D resample to a scalar
    (Sharpe on returns, or a path-dependent metric such as max drawdown computed
    from the resampled return path). It reuses the existing stationary-bootstrap
    index generator rather than duplicating resampling logic.

    Parameters
    ----------
    a, b
        1-D numeric array-likes of equal length (paired observations). Not mutated.
    metric_fn
        Callable mapping a 1-D resample to a scalar; called ``2 * n_resamples``
        times (once per series per replication).
    n_resamples
        Number of bootstrap replications; must be a positive integer.
    expected_block_length
        Mean block length for the stationary bootstrap (validated by the delegated
        index call).
    rng
        A NumPy ``Generator``. All randomness is drawn from this object only.

    Returns
    -------
    numpy.ndarray
        A 1-D ``float`` array of length ``n_resamples`` holding
        ``metric_fn(a[idx]) - metric_fn(b[idx])`` per replication.

    Raises
    ------
    ValueError
        If ``a``/``b`` are not 1-D numeric, are empty, or differ in length; if
        ``n_resamples`` is not a positive integer; or if ``metric_fn`` is not
        callable. (Invalid ``expected_block_length`` is raised by the delegated
        index call.)
    """
    arr_a = np.asarray(a)
    arr_b = np.asarray(b)
    for name, arr in (("a", arr_a), ("b", arr_b)):
        if arr.ndim != 1:
            raise ValueError(f"{name} must be 1-D, got {arr.ndim}-D with shape {arr.shape}")
        if arr.size == 0:
            raise ValueError(f"{name} must be non-empty")
        if not np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_):
            raise ValueError(f"{name} must be numeric, got dtype {arr.dtype!r}")
    if arr_a.shape[0] != arr_b.shape[0]:
        raise ValueError(
            f"a and b must have equal length, got {arr_a.shape[0]} and {arr_b.shape[0]}"
        )
    if not isinstance(n_resamples, (int, np.integer)) or isinstance(n_resamples, bool) \
            or n_resamples <= 0:
        raise ValueError(f"n_resamples must be a positive integer, got {n_resamples!r}")
    if not callable(metric_fn):
        raise ValueError(f"metric_fn must be callable, got {type(metric_fn).__name__}")

    va = np.asarray(arr_a, dtype=float)
    vb = np.asarray(arr_b, dtype=float)
    n = va.shape[0]
    n_resamples = int(n_resamples)
    out = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        idx = stationary_bootstrap_indices(n, expected_block_length, rng)  # shared indices
        out[i] = metric_fn(va[idx]) - metric_fn(vb[idx])
    return out
