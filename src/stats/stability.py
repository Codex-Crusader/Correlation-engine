"""Stability filter: an edge that appears once is noise.

Each daily run writes its surviving edges to results/history/. An edge is
only published if the same pair, with the same correlation sign, appeared in
at least `min_appearances` of the last `window` runs that actually happened.
Counting runs rather than calendar days makes skipped or late crons harmless.
"""

import json
from pathlib import Path


def edge_key(metric_a: str, metric_b: str, rho: float) -> str:
    """Order-independent identity for an edge: pair plus correlation sign."""
    first, second = sorted([metric_a, metric_b])
    sign = "+" if rho >= 0 else "-"
    return f"{first}|{second}|{sign}"


def load_history(history_dir: Path, window: int):
    """Newest `window` run files as a list of (date, set_of_edge_keys)."""
    files = sorted(history_dir.glob("edges_*.json"))[-window:]
    history = []
    for path in files:
        record = json.loads(path.read_text())
        keys = {
            edge_key(e["metric_a"], e["metric_b"], e["rho"])
            for e in record["edges"]
        }
        history.append((record["date"], keys))
    return history


def stable_edge_keys(history, min_appearances: int):
    """Edge keys present in at least min_appearances of the given runs.

    Returns {edge_key: appearance_count}. If fewer runs than min_appearances
    exist yet (a young repo), nothing can qualify, which is correct: the tool
    should publish nothing rather than publish something unstable.
    """
    counts = {}
    for _, keys in history:
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return {key: n for key, n in counts.items() if n >= min_appearances}
