"""Shared plumbing for all fetchers.

Storage is one CSV per metric with columns date,value, committed to the repo.
CSV rather than Parquet because the commit log IS the audit trail, and CSV
diffs are readable by anyone.

Every fetcher works on a date range and merges into the existing file keyed
by date, so runs are idempotent: re-running today rewrites the same rows,
and a range fetch automatically backfills any days a skipped cron missed.
"""

import time
from pathlib import Path

import pandas as pd
import requests

USER_AGENT = (
    "correlation-engine/1.0 (https://github.com/YOUR_USERNAME/YOUR_REPO; "
    "daily research pipeline)"
)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def get_json(url, params=None, max_retries=4, base_delay=5):
    """GET with a proper User-Agent, exponential backoff, and 429 handling."""
    for attempt in range(max_retries):
        response = requests.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60
        )
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", base_delay * 2 ** attempt))
            time.sleep(min(wait, 300))
            continue
        if response.status_code >= 500:
            time.sleep(base_delay * 2 ** attempt)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Gave up on {url} after {max_retries} attempts")


def series_path(metric_id: str) -> Path:
    return DATA_DIR / f"{metric_id}.csv"


def load_series(metric_id: str) -> pd.Series:
    """Load a stored metric as a date-indexed Series. Empty if none yet."""
    path = series_path(metric_id)
    if not path.exists():
        return pd.Series(dtype=float, name="value")
    frame = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return frame["value"]


def last_stored_date(metric_id: str):
    series = load_series(metric_id)
    return None if series.empty else series.index.max().date()


def merge_series(metric_id: str, new_series: pd.Series) -> int:
    """Merge new observations into the stored CSV, new values winning on
    conflict (sources revise recent data). Returns rows written."""
    if new_series.empty:
        return 0
    new_series = new_series[~new_series.index.duplicated(keep="last")]
    existing = load_series(metric_id)
    combined = new_series.combine_first(existing).sort_index()
    combined.name = "value"
    DATA_DIR.mkdir(exist_ok=True)
    combined.rename_axis("date").to_csv(series_path(metric_id))
    return len(combined)


def fetch_window(metric_id: str, history_start: str, refetch_days: int):
    """Date range a fetcher should request: from history_start on the first
    run, otherwise from a few days before the last stored date, to catch
    late-arriving revisions and fill cron gaps."""
    last = last_stored_date(metric_id)
    today = pd.Timestamp.utcnow().date()
    if last is None:
        start = pd.Timestamp(history_start).date()
    else:
        start = last - pd.Timedelta(days=refetch_days)
    return start, today
