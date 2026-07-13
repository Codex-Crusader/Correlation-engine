"""Benjamini-Hochberg false discovery rate control.

With thousands of (pair, lag) tests per day, raw p < 0.05 guarantees a pile
of false positives. BH adjusts each p-value into a q-value: keeping every
result with q < 0.05 bounds the expected share of false discoveries at 5%.

Honest caveat, also stated in the README: the 15 lags of one pair are not
independent tests, and BH assumes independence or positive dependence. In
practice positive dependence holds here and BH remains valid (Benjamini and
Yekutieli 2001), but the q-values are approximate, which is one more reason
the placebo panel exists.
"""

import numpy as np


def benjamini_hochberg(p_values) -> np.ndarray:
    """Return BH q-values in the same order as the input p-values."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    if m == 0:
        return np.array([])
    order = np.argsort(p)
    scaled = p[order] * m / np.arange(1, m + 1)
    # q-values must be monotone: enforce from the largest rank downward.
    q_sorted = np.minimum.accumulate(scaled[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.clip(q_sorted, 0.0, 1.0)
    return q


def apply_correction(results):
    """Fill in q_value on each PairResult, in place. Returns the results."""
    q_values = benjamini_hochberg([r.p_value for r in results])
    for result, q in zip(results, q_values):
        result.q_value = float(q)
    return results
