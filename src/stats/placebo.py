"""Placebo panel: run the identical pipeline on data that contains no
real relationships, and show what it finds.

Method: phase randomization. Each series is passed through an FFT, its phases
are replaced with uniform random ones, and it is transformed back. The
surrogate keeps the original's power spectrum, and therefore its
autocorrelation ("wiggliness"), but any real relationship between two series
is destroyed. This is a stricter, more honest null than shuffling, which
kills autocorrelation and makes noise look tamer than it really is.

Whatever count of "significant" edges the placebo runs produce is the
baseline the real findings must be judged against, and the site shows it
with the same visual weight as the real result.
"""

import os
from multiprocessing import Pool

import numpy as np
import pandas as pd

from .correction import apply_correction
from .correlate import lagged_correlations


def phase_randomize(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Surrogate with the same power spectrum but random phases."""
    n = len(values)
    spectrum = np.fft.rfft(values)
    phases = np.exp(1j * rng.uniform(0.0, 2.0 * np.pi, len(spectrum)))
    phases[0] = 1.0  # keep the mean
    if n % 2 == 0:
        phases[-1] = 1.0  # Nyquist bin must stay real
    return np.fft.irfft(spectrum * phases, n=n)


def surrogate_series(series: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Phase-randomized copy of a series, preserving its missing-data pattern.

    NaNs are linearly interpolated for the FFT only, then punched back out,
    so the surrogate faces the same overlap constraints as the original.
    """
    missing = series.isna()
    filled = series.interpolate(limit_direction="both")
    if filled.isna().any():  # series was entirely NaN
        return series.copy()
    surrogate_values = phase_randomize(filled.to_numpy(), rng)
    surrogate = pd.Series(surrogate_values, index=series.index)
    surrogate[missing] = np.nan
    return surrogate


def _run_one_rep(args):
    """One surrogate universe through steps 3-5. Top-level (not nested) so
    multiprocessing can pickle it under the spawn start method."""
    series_by_id, max_lag, min_overlap, fdr_q, min_abs_rho, child_seed = args
    rng = np.random.default_rng(child_seed)
    surrogates = {
        name: surrogate_series(series, rng)
        for name, series in series_by_id.items()
    }
    results, _ = lagged_correlations(surrogates, max_lag, min_overlap)
    apply_correction(results)
    return [
        r for r in results
        if r.q_value < fdr_q and abs(r.rho) >= min_abs_rho
    ]


def run_placebo_panel(series_by_id, max_lag, min_overlap, fdr_q, min_abs_rho,
                      reps, seed=None, n_jobs=None):
    """Run the real pipeline `reps` times on surrogate universes, in parallel.

    Reps are independent by construction, so they fan out over a process
    pool (n_jobs defaults to one worker per core, capped at reps). Each rep
    draws from its own SeedSequence-spawned stream rather than sharing one
    generator, which makes a seeded panel reproducible bit-for-bit at any
    worker count -- including n_jobs=1, which skips the pool entirely.

    Returns a dict with the per-rep counts of edges that survive the same
    q-value and effect-size filters the real analysis uses, plus the edges
    from the first rep so the site can draw an example noise graph.
    """
    child_seeds = np.random.SeedSequence(seed).spawn(reps)
    jobs = [
        (series_by_id, max_lag, min_overlap, fdr_q, min_abs_rho, child_seed)
        for child_seed in child_seeds
    ]
    if n_jobs is None:
        n_jobs = min(reps, os.cpu_count() or 1)
    if n_jobs > 1:
        with Pool(n_jobs) as pool:
            survivors_per_rep = pool.map(_run_one_rep, jobs)
    else:
        survivors_per_rep = [_run_one_rep(job) for job in jobs]
    survivor_counts = [len(survivors) for survivors in survivors_per_rep]
    return {
        "reps": reps,
        "survivor_counts": survivor_counts,
        "mean_survivors": float(np.mean(survivor_counts)),
        "max_survivors": int(np.max(survivor_counts)),
        "example_edges": survivors_per_rep[0],
    }
