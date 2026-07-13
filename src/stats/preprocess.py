"""Turn a raw daily series into a stationary, weekday-adjusted change series.

Correlating raw trending levels is the classic spurious-regression trap:
two series that both drift upward correlate near 0.9 for no reason. So every
series is differenced until it passes an ADF stationarity test, then adjusted
for day-of-week effects (news volume and pageviews have strong weekly cycles
that would otherwise show up as fake lag-7 correlations).
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

MAX_DIFFS = 2
ADF_ALPHA = 0.05
MIN_POINTS_FOR_ADF = 60


def is_stationary(series: pd.Series) -> bool:
    """ADF test. Null hypothesis is a unit root, so small p means stationary."""
    values = series.dropna().to_numpy()
    if len(values) < MIN_POINTS_FOR_ADF:
        return False
    if np.allclose(values, values[0]):
        return False  # constant series: nothing to correlate
    p_value = adfuller(values, autolag="AIC")[1]
    return p_value < ADF_ALPHA


def make_stationary(series: pd.Series):
    """Difference until the ADF test passes, up to MAX_DIFFS times.

    Returns (stationary_series, n_diffs), or (None, MAX_DIFFS) if the series
    still fails. Callers drop such series and log it; a series we cannot make
    stationary is a series we cannot honestly correlate.
    """
    current = series
    for n_diffs in range(MAX_DIFFS + 1):
        if is_stationary(current):
            return current, n_diffs
        current = current.diff()
    return None, MAX_DIFFS


def remove_weekday_effect(series: pd.Series) -> pd.Series:
    """Subtract each weekday's mean, computed on the series itself."""
    weekday_means = series.groupby(series.index.dayofweek).transform("mean")
    return series - weekday_means


def preprocess(series: pd.Series):
    """Full pipeline for one metric.

    Order matters: difference first (removes trend), then remove the weekday
    cycle from the changes. Returns (series, n_diffs) on success or
    (None, n_diffs) if the series must be dropped.
    """
    series = series.sort_index()
    stationary, n_diffs = make_stationary(series)
    if stationary is None:
        return None, n_diffs
    return remove_weekday_effect(stationary), n_diffs
