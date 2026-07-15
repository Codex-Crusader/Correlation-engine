"""Spearman cross-correlation over all metric pairs and a window of lags.

Spearman, not Pearson: GDELT volumes and pageviews have huge one-day spikes,
and rank correlation does not get dragged around by them.

Lag convention: a result with lag k correlates a[t] against b[t + k].
Positive k means changes in `metric_a` tend to precede changes in `metric_b`
by k days. Precedence is NOT causation and nothing downstream may present
it as such.

Every (pair, lag) combination is one hypothesis test. The total count is
reported to the correction step and to the site, because that count is the
whole multiple-comparisons story.
"""

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


@dataclass
class PairResult:
    metric_a: str
    metric_b: str
    lag: int
    rho: float
    p_value: float
    n_overlap: int
    q_value: float | None = None  # filled in by the BH correction step
    # Filled in by annotate_partials (src/stats/partial.py) for edges that
    # survive the filters. Context only: never part of the publication gate.
    partial_rho: float | None = None
    partial_sample_rho: float | None = None  # raw rho on the partial's own rows
    partial_n: int | None = None
    common_driver: bool | None = None  # True: conditioning removed the edge;
                                       # None: no verdict (see annotate_partials)
    partial_status: str | None = None  # ok | is_conditioner | insufficient_overlap | unavailable


def lagged_correlations(series_by_id: dict, max_lag: int, min_overlap: int):
    """Test every unordered pair at every lag in [-max_lag, +max_lag].

    Returns (results, n_tests). n_tests counts every combination attempted,
    including those skipped for insufficient overlap, so the reported test
    count never understates how much searching was done.
    """
    results = []
    n_tests = 0
    for name_a, name_b in combinations(sorted(series_by_id), 2):
        series_a = series_by_id[name_a]
        series_b = series_by_id[name_b]
        for lag in range(-max_lag, max_lag + 1):
            n_tests += 1
            frame: pd.DataFrame = pd.concat(
                [series_a, series_b.shift(-lag)], axis=1, keys=["a", "b"]
            )
            aligned = frame.dropna()
            if len(aligned) < min_overlap:
                continue
            rho, p_value = spearmanr(aligned["a"], aligned["b"])
            if np.isnan(rho):
                continue
            results.append(
                PairResult(name_a, name_b, lag, float(rho), float(p_value), len(aligned))
            )
    return results, n_tests


def best_lag_per_pair(results):
    """Keep only the strongest surviving lag for each pair, for display.

    Selection happens AFTER correction, so this does not inflate significance;
    it just avoids showing the same pair seven times.
    """
    best = {}
    for result in results:
        key = (result.metric_a, result.metric_b)
        if key not in best or abs(result.rho) > abs(best[key].rho):
            best[key] = result
    return list(best.values())
