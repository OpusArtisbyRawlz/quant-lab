"""
Permutation primitives for Project 07 statistical-integrity tests.

Permutation testing asks whether an observed association (e.g. signal → forward
return) could have arisen by chance by repeatedly *reshuffling* the sample and
recomputing the statistic under the null of no association. This module provides
the lowest-level primitive — a single random permutation of positional indices —
on which the higher-level permutation sample / test functions will build.

Determinism: all randomness comes from the caller-supplied NumPy ``Generator``.

Scaffold status: only ``permutation_indices`` is implemented; higher-level
permutation functions are not part of this module yet.
"""

from __future__ import annotations

from typing import Callable

import numpy as np


def permutation_indices(
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate one random permutation of the indices ``0, 1, ..., n - 1``.

    **This is a permutation, not a bootstrap resample.** Unlike bootstrap
    resampling (which samples positions *with replacement*), a permutation is a
    reordering *without replacement*:

    - **no observation is duplicated** — each index appears exactly once;
    - **no observation is omitted** — every index in ``[0, n - 1]`` is present.

    Its purpose is to **break ordering / association while preserving the observed
    sample values**. Applying the returned indices to one of two paired series
    (e.g. shuffling signals against fixed forward returns) destroys any genuine
    relationship between them while leaving each series' marginal distribution
    unchanged — exactly the null needed for a permutation test.

    Parameters
    ----------
    n
        Number of indices to permute (the sample length). Must be a positive
        integer; ``bool`` is rejected explicitly.
    rng
        A NumPy random ``Generator`` (e.g. ``np.random.default_rng(seed)``). All
        randomness is drawn from this object only; no generator is created
        internally, so output is reproducible for a given seeded generator.

    Returns
    -------
    numpy.ndarray
        A 1-D integer array of length ``n`` containing each of
        ``0, 1, ..., n - 1`` exactly once, in random order.

    Raises
    ------
    ValueError
        If ``n`` is not a positive integer (a ``bool`` is not accepted).
    """
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n <= 0:
        raise ValueError(f"n must be a positive integer, got {n!r}")

    # rng.permutation(int) returns a permuted arange(n) drawn solely from the
    # supplied generator — a permutation (no replacement) by construction.
    return rng.permutation(int(n))


def permutation_sample(
    values: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one permuted copy of ``values`` — the same multiset, reordered.

    Applies :func:`permutation_indices` to reorder the sample without replacement:
    every original value appears exactly once and none is dropped, so only the
    *order* changes. This is the building block of a permutation test — shuffling
    one paired series to break its association with another while leaving its
    marginal distribution untouched.

    Because a permutation only reorders values (no arithmetic), the input dtype is
    preserved: an integer array permutes to an integer array, a float array to a
    float array.

    Parameters
    ----------
    values
        A 1-D numeric array-like to permute (the original sample). Not mutated.
    rng
        A NumPy random ``Generator``. All randomness is drawn from this object
        only, via :func:`permutation_indices`; no generator is created internally.

    Returns
    -------
    numpy.ndarray
        A new 1-D array of the same length and dtype as ``values``, containing the
        same values in random order.

    Raises
    ------
    ValueError
        If ``values`` is not 1-D, is empty, or is non-numeric.
    """
    arr = np.asarray(values)
    if arr.ndim != 1:
        raise ValueError(
            f"values must be a 1-D array, got {arr.ndim}-D with shape {arr.shape}"
        )
    if arr.size == 0:
        raise ValueError("values must be non-empty")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"values must be numeric, got dtype {arr.dtype!r}")

    # Fancy indexing returns a fresh array (dtype preserved); the input is never
    # written to.
    indices = permutation_indices(arr.shape[0], rng)
    return arr[indices]


def permutation_metric(
    values: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    n_permutations: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate the empirical null distribution of a metric by permutation.

    Repeatedly permutes the observed ``values`` (via :func:`permutation_sample`)
    and evaluates ``metric_fn`` on each shuffle, producing the distribution of the
    metric **under the null of no ordering/association**. Because a permutation
    preserves the exact multiset of values and only randomises their order, this
    distribution isolates the part of the metric that depends on structure/order
    rather than on the values themselves — the reference against which an observed
    metric is later judged (p-value computation is a separate step, not done here).

    Determinism: all randomness is drawn from the supplied ``rng``, consumed in
    sequence, so the whole distribution is reproducible from one seeded generator
    and the iterations are distinct shuffles rather than repeats.

    Parameters
    ----------
    values
        A 1-D numeric array-like (the observed sample). Not mutated; shape/dtype
        validation is delegated to :func:`permutation_sample`.
    metric_fn
        Callable mapping a 1-D sample to a scalar. Called exactly
        ``n_permutations`` times, once per shuffle.
    n_permutations
        Number of permutations to draw; must be a positive integer (``bool`` is
        rejected explicitly).
    rng
        A NumPy ``Generator``. All randomness is drawn from this object only; no
        generator is created internally.

    Returns
    -------
    numpy.ndarray
        A 1-D ``float`` array of length ``n_permutations`` — one metric value per
        permutation.

    Raises
    ------
    ValueError
        If ``n_permutations`` is not a positive integer, or ``metric_fn`` is not
        callable. (Invalid ``values`` are raised by the delegated
        :func:`permutation_sample` call.)
    """
    if (
        isinstance(n_permutations, bool)
        or not isinstance(n_permutations, (int, np.integer))
        or n_permutations <= 0
    ):
        raise ValueError(
            f"n_permutations must be a positive integer, got {n_permutations!r}"
        )
    if not callable(metric_fn):
        raise ValueError(f"metric_fn must be callable, got {type(metric_fn).__name__}")

    n_permutations = int(n_permutations)
    distribution = np.empty(n_permutations, dtype=float)
    for i in range(n_permutations):
        sample = permutation_sample(values, rng)
        distribution[i] = metric_fn(sample)
    return distribution


def permutation_p_value(
    observed_metric: float,
    null_distribution: np.ndarray,
) -> float:
    """Compute the one-sided empirical permutation p-value.

    The p-value counts the permutation-null values that are **at least as extreme**
    as the observed metric (greater than or equal to it), using the add-one
    (Davison–Hinkley) estimator::

        p = (count(null_distribution >= observed_metric) + 1) / (len(null_distribution) + 1)

    **One-sided.** This tests the upper tail only (larger metric = more extreme);
    it answers "how often does a no-association shuffle produce a metric this large
    or larger?" A small ``p`` means the observed value is rarely matched under the
    null, i.e. evidence against it.

    **Why ``>=``.** A p-value counts outcomes *at least as extreme* as the
    observed one, so the observed value's own ties in the null are included.

    **Why add-one.** The observed sample is itself one valid arrangement under the
    null, so it is counted in both numerator and denominator (``+1`` each). This
    guarantees a strictly positive p-value — a distribution of ``n`` permutations
    can never yield ``p = 0`` — which is the correct floor: with finite
    permutations we can never prove the observed value is impossible under the
    null. The smallest attainable p-value is ``1 / (n + 1)``.

    Parameters
    ----------
    observed_metric
        The metric computed on the real (unshuffled) data. Must be a finite
        number.
    null_distribution
        A 1-D array of metric values under the null (e.g. from
        :func:`permutation_metric`). Must be non-empty and contain only finite
        numeric values. Not mutated.

    Returns
    -------
    float
        A probability in ``[0, 1]``.

    Raises
    ------
    ValueError
        If ``observed_metric`` is not a finite number, or ``null_distribution`` is
        not 1-D, is empty, or contains non-finite / non-numeric values.
    """
    if (
        isinstance(observed_metric, bool)
        or not isinstance(observed_metric, (int, float, np.integer, np.floating))
        or not np.isfinite(observed_metric)
    ):
        raise ValueError(
            f"observed_metric must be a finite number, got {observed_metric!r}"
        )

    arr = np.asarray(null_distribution)
    if arr.ndim != 1:
        raise ValueError(
            f"null_distribution must be 1-D, got {arr.ndim}-D with shape {arr.shape}"
        )
    if arr.size == 0:
        raise ValueError("null_distribution must be non-empty")
    try:
        all_finite = bool(np.isfinite(arr).all())
    except TypeError:
        raise ValueError(f"null_distribution must be numeric, got dtype {arr.dtype!r}")
    if not all_finite:
        raise ValueError("null_distribution must be finite (contains NaN or Inf)")

    count = int(np.count_nonzero(arr >= observed_metric))
    return (count + 1) / (arr.size + 1)
