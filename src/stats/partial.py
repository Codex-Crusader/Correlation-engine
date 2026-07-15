"""Partial Spearman correlation: does an edge survive removing a common driver?

Most co-movement in this pool is everything reacting to the same event: a
crisis moves news coverage, pageviews, and market series together, and every
such pair shows up as an edge. Partialing out a market-stress proxy (VIX
changes) asks the sharper question: do these two series still move together
beyond what stress explains?

This is an annotation, never a gate. The conditioner is itself driven by
news, so conditioning can erase genuinely stress-mediated relationships and
can occasionally manufacture association out of nothing (collider bias).
The partial rho is reported next to the raw rho, and the publication filters
ignore it.

Timing: when correlating a[t] against b[t+k], a common driver may act at
either timestamp, so the conditioning set is {cond[t], cond[t+k]} and both
sides are residualized on both columns. Rows where the conditioner is
missing (market series have no weekend values) drop out; the partial runs
on fewer days than the raw rho and reports its own n.

Sample confound: dropping weekends changes the edge before any conditioning
happens (measured on real data 2026-07-15: every Federal Register pair's
rho fell below the floor on weekdays alone, with conditioning removing
almost nothing on top). So the raw rho is recomputed on the exact rows the
partial uses, and an edge is only blamed on the common driver when that
same-sample rho still clears the floor and the partial does not. An edge
already below the floor on the conditioner's days gets no verdict: its
strength lives in the weekend rows, which says nothing about market stress.
"""

import numpy as np
import pandas as pd


def partial_spearman(series_a: pd.Series, series_b: pd.Series,
                     conditioner: pd.Series, lag: int):
    """Partial Spearman rho of a[t] vs b[t + lag] given the conditioner at
    both timestamps.

    Returns (partial_rho, sample_rho, n_overlap), where sample_rho is the
    plain Spearman rho on the SAME rows the partial uses. The two differ
    from the full-sample rho for different reasons (conditioning vs the
    conditioner's missing days), and telling those apart is the caller's
    whole job. Rhos are NaN when fewer than 3 usable rows exist or a
    residual is constant (ranks fully explained by the conditioner)."""
    frame: pd.DataFrame = pd.concat(
        [series_a, series_b.shift(-lag), conditioner, conditioner.shift(-lag)],
        axis=1, keys=["a", "b", "cond_a", "cond_b"],
    ).dropna()
    n = len(frame)
    if n < 3:
        return float("nan"), float("nan"), n
    ranks = frame.rank().to_numpy()
    sample_rho = float(np.corrcoef(ranks[:, 0], ranks[:, 1])[0, 1])
    # At lag 0 the two conditioner columns are identical; keep one to avoid
    # a singular design matrix.
    cond = ranks[:, 2:3] if lag == 0 else ranks[:, 2:4]
    design = np.column_stack([np.ones(n), cond])
    resid_a = ranks[:, 0] - design @ np.linalg.lstsq(design, ranks[:, 0], rcond=None)[0]
    resid_b = ranks[:, 1] - design @ np.linalg.lstsq(design, ranks[:, 1], rcond=None)[0]
    if resid_a.std() < 1e-12 or resid_b.std() < 1e-12:
        return float("nan"), sample_rho, n
    return float(np.corrcoef(resid_a, resid_b)[0, 1]), sample_rho, n


def annotate_partials(edges, series_by_id, conditioner_id, conditioner,
                      min_abs_rho, min_overlap):
    """Fill the partial_* fields on each PairResult, in place.

    `conditioner` is passed separately from `series_by_id` on purpose: the
    placebo panel conditions surrogate edges on the REAL conditioner series
    (surrogates are independent of it by construction), which is exactly
    what makes its luck rate a fair baseline for the flag.

    partial_status values:
      ok                    partial computed on enough days
      is_conditioner        the edge touches the conditioner itself
      insufficient_overlap  too few conditioner-overlapping days for a verdict
      unavailable           no conditioner series (not configured, or dropped)

    common_driver verdict (only under status ok):
      False  the partial still clears the effect-size floor: the edge holds
      True   the same-sample rho clears the floor but the partial does not:
             the conditioning, not the sample, removed the edge
      None   the edge is already below the floor on the conditioner's days
             before any conditioning: a weekend-sample effect, no verdict
    """
    for edge in edges:
        if conditioner is None:
            edge.partial_status = "unavailable"
            continue
        if conditioner_id in (edge.metric_a, edge.metric_b):
            edge.partial_status = "is_conditioner"
            continue
        rho, sample_rho, n = partial_spearman(
            series_by_id[edge.metric_a], series_by_id[edge.metric_b],
            conditioner, edge.lag,
        )
        edge.partial_n = n
        if np.isnan(rho) or n < min_overlap:
            edge.partial_rho = None if np.isnan(rho) else float(rho)
            edge.partial_status = "insufficient_overlap"
            continue
        edge.partial_rho = float(rho)
        edge.partial_sample_rho = float(sample_rho)
        edge.partial_status = "ok"
        if abs(rho) >= min_abs_rho:
            edge.common_driver = False
        elif abs(sample_rho) >= min_abs_rho:
            edge.common_driver = True
        else:
            edge.common_driver = None
    return edges
