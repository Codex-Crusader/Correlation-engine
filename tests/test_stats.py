"""Tests for the statistics package. This module is the heart of the
project; nothing else matters if these are wrong."""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from src.stats import (
    apply_correction,
    benjamini_hochberg,
    best_lag_per_pair,
    edge_key,
    iaaft_surrogate,
    lagged_correlations,
    make_stationary,
    phase_randomize,
    preprocess,
    remove_weekday_effect,
    run_placebo_panel,
    stable_edge_keys,
    surrogate_series,
)

RNG = np.random.default_rng(42)


def daily_index(n=500, start="2024-01-01"):
    return pd.date_range(start, periods=n, freq="D")


# ---------------------------------------------------------------- preprocess

def test_white_noise_needs_no_differencing():
    series = pd.Series(RNG.normal(size=500), index=daily_index())
    result, n_diffs = make_stationary(series)
    assert result is not None
    assert n_diffs == 0


def test_random_walk_needs_one_difference():
    series = pd.Series(RNG.normal(size=500).cumsum(), index=daily_index())
    result, n_diffs = make_stationary(series)
    assert result is not None
    assert n_diffs == 1


def test_stubbornly_nonstationary_series_is_dropped():
    # A constant series can never pass the ADF test.
    series = pd.Series(np.ones(500), index=daily_index())
    result, _ = make_stationary(series)
    assert result is None


def test_weekday_effect_is_removed():
    index = daily_index()
    weekly_cycle = np.where(index.dayofweek < 5, 10.0, 0.0)
    series = pd.Series(weekly_cycle + RNG.normal(size=len(index)), index=index)
    adjusted = remove_weekday_effect(series)
    weekday_means = adjusted.groupby(pd.DatetimeIndex(adjusted.index).dayofweek).mean()
    assert np.allclose(weekday_means, 0.0, atol=1e-9)


def test_two_trending_series_do_not_correlate_after_preprocess():
    # The spurious-regression case: both trend up, levels correlate ~0.99.
    index = daily_index()
    trend = np.arange(len(index), dtype=float)
    series_a = pd.Series(trend + RNG.normal(scale=5, size=len(index)), index=index)
    series_b = pd.Series(trend + RNG.normal(scale=5, size=len(index)), index=index)
    level_rho = scipy_stats.spearmanr(series_a, series_b)[0]
    assert level_rho > 0.9  # the trap is real

    processed_a, _ = preprocess(series_a)
    processed_b, _ = preprocess(series_b)
    frame: pd.DataFrame = pd.concat([processed_a, processed_b], axis=1)
    aligned = frame.dropna()
    change_rho = scipy_stats.spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])[0]
    assert abs(change_rho) < 0.15  # and preprocessing defuses it


# ----------------------------------------------------------------- correlate

def test_lag_convention_positive_lag_means_a_leads_b():
    index = daily_index()
    base = pd.Series(RNG.normal(size=len(index)), index=index)
    follower = base.shift(2) + RNG.normal(scale=0.1, size=len(index))
    series = {"leader": base, "follower": pd.Series(follower, index=index)}

    results, n_tests = lagged_correlations(series, max_lag=7, min_overlap=100)
    assert n_tests == 15  # one pair, lags -7..7
    best = max(results, key=lambda r: abs(r.rho))
    # follower[t] = leader[t-2], so leader leads follower by 2 days.
    if best.metric_a == "leader":
        assert best.lag == 2
    else:
        assert best.lag == -2
    assert best.rho > 0.9


def test_insufficient_overlap_is_skipped_but_still_counted():
    index = daily_index(50)
    series = {
        "a": pd.Series(RNG.normal(size=50), index=index),
        "b": pd.Series(RNG.normal(size=50), index=index),
    }
    results, n_tests = lagged_correlations(series, max_lag=3, min_overlap=100)
    assert results == []
    assert n_tests == 7  # honesty: attempted tests are reported even if skipped


def test_best_lag_per_pair_keeps_strongest():
    results, _ = lagged_correlations(
        {
            "a": pd.Series(RNG.normal(size=300), index=daily_index(300)),
            "b": pd.Series(RNG.normal(size=300), index=daily_index(300)),
        },
        max_lag=7,
        min_overlap=100,
    )
    best = best_lag_per_pair(results)
    assert len(best) == 1
    assert abs(best[0].rho) == max(abs(r.rho) for r in results)


# ---------------------------------------------------------------- correction

def test_bh_matches_scipy_reference():
    p_values = RNG.uniform(size=200)
    ours = benjamini_hochberg(p_values)
    reference = scipy_stats.false_discovery_control(p_values, method="bh")
    assert np.allclose(ours, reference)


def test_bh_on_pure_noise_rejects_almost_nothing():
    index = daily_index()
    series = {
        f"noise_{i}": pd.Series(RNG.normal(size=len(index)), index=index)
        for i in range(10)
    }
    results, _ = lagged_correlations(series, max_lag=7, min_overlap=100)
    apply_correction(results)
    raw_hits = sum(r.p_value < 0.05 for r in results)
    corrected_hits = sum(r.q_value < 0.05 for r in results)
    assert raw_hits > 0  # raw threshold produces false positives, as expected
    assert corrected_hits <= max(2, raw_hits // 5)  # BH removes almost all


# ------------------------------------------------------------------- placebo

def test_phase_randomization_preserves_power_spectrum():
    values = RNG.normal(size=500).cumsum()
    surrogate = phase_randomize(values, RNG)
    assert len(surrogate) == len(values)
    original_power = np.abs(np.fft.rfft(values))
    surrogate_power = np.abs(np.fft.rfft(surrogate))
    assert np.allclose(original_power, surrogate_power, rtol=1e-8)


def ar1(n=500, phi=0.8, seed_noise=None):
    values = np.empty(n)
    values[0] = 0.0
    noise = RNG.normal(size=n) if seed_noise is None else seed_noise
    for i in range(1, n):
        values[i] = phi * values[i - 1] + noise[i]
    return values


def spectrum_rel_error(original, surrogate):
    a = np.abs(np.fft.rfft(original))
    b = np.abs(np.fft.rfft(surrogate))
    return np.linalg.norm(a - b) / np.linalg.norm(a)


def test_iaaft_preserves_power_spectrum_closely():
    # On continuous data IAAFT converges tightly (measured ~0.01 relative
    # error on real series); 0.05 leaves headroom without letting a broken
    # implementation through (a shuffle scores ~0.9 here).
    values = ar1()
    surrogate = iaaft_surrogate(values, np.random.default_rng(0))
    assert spectrum_rel_error(values, surrogate) < 0.05


def test_iaaft_spectrum_survives_heavy_ties():
    # Zero-inflation caps how well any value-preserving surrogate can match
    # the spectrum (measured ~0.23 on the real executive-orders series), but
    # IAAFT must stay far ahead of a plain shuffle on the same data.
    rng = np.random.default_rng(0)
    values = np.where(rng.uniform(size=600) < 0.4, 0.0,
                      ar1(600, seed_noise=rng.normal(size=600)))
    surrogate = iaaft_surrogate(values, np.random.default_rng(1))
    shuffled = rng.permutation(values)
    assert spectrum_rel_error(values, surrogate) < 0.5 * spectrum_rel_error(values, shuffled)


def test_iaaft_preserves_marginals_exactly():
    # Zero-inflated and spiky, like the real document counts: the surrogate
    # must be a permutation of the observed values, ties and all.
    values = np.where(RNG.uniform(size=400) < 0.7, 0.0, RNG.exponential(5, 400))
    surrogate = iaaft_surrogate(values, np.random.default_rng(0))
    assert np.array_equal(np.sort(surrogate), np.sort(values))
    assert not np.array_equal(surrogate, values)  # and not the identity


def test_iaaft_approximately_preserves_autocorrelation():
    # AR(1) with strong persistence; the surrogate must stay comparably
    # persistent, or the null would be too easy (the shuffling failure mode).
    values = ar1()
    surrogate = iaaft_surrogate(values, np.random.default_rng(0))

    def lag1_autocorr(x):
        return np.corrcoef(x[:-1], x[1:])[0, 1]

    assert abs(lag1_autocorr(surrogate) - lag1_autocorr(values)) < 0.15


def test_surrogate_preserves_missing_data_pattern():
    series = pd.Series(RNG.normal(size=200), index=daily_index(200))
    series.iloc[10:20] = np.nan
    surrogate = surrogate_series(series, RNG)
    assert surrogate.isna().equals(series.isna())
    # And it must actually differ from the original where data exists.
    assert not np.allclose(surrogate.dropna(), series.dropna())


def test_placebo_panel_on_correlated_data_reports_low_counts():
    # Two genuinely correlated series; surrogates must destroy the link.
    index = daily_index(400)
    base = pd.Series(RNG.normal(size=400), index=index)
    series = {
        "a": base,
        "b": base + RNG.normal(scale=0.3, size=400),
        "c": pd.Series(RNG.normal(size=400), index=index),
    }
    panel = run_placebo_panel(
        series, max_lag=7, min_overlap=100, fdr_q=0.05,
        min_abs_rho=0.2, reps=5, seed=7,
    )
    assert panel["reps"] == 5
    assert len(panel["survivor_counts"]) == 5
    assert panel["mean_survivors"] < 2  # the real a-b link must not survive


# ----------------------------------------------------------------- stability

def test_edge_key_is_order_independent_and_signed():
    assert edge_key("b", "a", 0.5) == edge_key("a", "b", 0.7)
    assert edge_key("a", "b", 0.5) != edge_key("a", "b", -0.5)


def test_stability_requires_min_appearances():
    history = [
        ("2026-07-01", {"a|b|+", "c|d|-"}),
        ("2026-07-02", {"a|b|+"}),
        ("2026-07-03", {"a|b|+", "c|d|-"}),
    ]
    stable = stable_edge_keys(history, min_appearances=3)
    assert stable == {"a|b|+": 3}


def test_young_repo_publishes_nothing():
    history = [("2026-07-01", {"a|b|+"})]
    assert stable_edge_keys(history, min_appearances=10) == {}
