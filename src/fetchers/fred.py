"""FRED API: daily economic time series.

Needs a free API key from https://fred.stlouisfed.org/docs/api/api_key.html,
stored as the FRED_API_KEY repo secret. If the key is absent the fetcher
skips its metrics with a warning instead of failing the whole run, so the
repo works out of the box and FRED joins in once the secret is set.

Only use daily FRED series here. Weekly or monthly series would need
resampling decisions that quietly manufacture autocorrelation; keeping the
pool daily-only avoids that entire class of bug. Market series have no
weekend values; those days stay NaN and pairwise overlap handles it.
"""

import os

import pandas as pd

from .common import fetch_window, get_json, merge_series

API_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_daily_values(series_id, api_key, start):
    payload = get_json(API_URL, params={
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start.isoformat(),
    })
    points = {}
    for obs in payload.get("observations", []):
        if obs["value"] != ".":  # FRED's marker for missing
            points[pd.Timestamp(obs["date"])] = float(obs["value"])
    return pd.Series(points).sort_index()


def fetch(metric, settings):
    """Entry point called by src.fetch. metric['params']['series_id'] is the
    FRED series id, e.g. VIXCLS."""
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        print(f"  SKIP {metric['id']}: FRED_API_KEY not set")
        return 0
    start, _ = fetch_window(
        metric["id"], settings["history_start"], settings["refetch_days"]
    )
    values = fetch_daily_values(metric["params"]["series_id"], api_key, start)
    return merge_series(metric["id"], values)
