"""GDELT DOC 2.0 API: daily news coverage volume for a topic query.

Mode timelinevolraw returns, per day, the number of matching articles and a
"norm" field with the total articles GDELT monitored that day. We store
100 * matched / norm: the share of global coverage. Raw counts would mostly
measure GDELT's own monitoring volume, which grows and dips on weekends.

The API needs a User-Agent (anonymous requests get rate limited) and can
return 429; common.get_json handles both. Requests are chunked to 180 days
and spaced out to stay polite.
"""

import time

import pandas as pd

from .common import fetch_window, get_json, merge_series

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
CHUNK_DAYS = 180
SECONDS_BETWEEN_CALLS = 6


def fetch_daily_share(query, start, end):
    """Daily coverage share (percent of monitored articles) for a query."""
    points = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + pd.Timedelta(days=CHUNK_DAYS - 1), pd.Timestamp(end))
        payload = get_json(API_URL, params={
            "query": query,
            "mode": "timelinevolraw",
            "format": "json",
            "startdatetime": pd.Timestamp(chunk_start).strftime("%Y%m%d") + "000000",
            "enddatetime": pd.Timestamp(chunk_end).strftime("%Y%m%d") + "235959",
        })
        timeline = payload.get("timeline") or []
        for entry in (timeline[0].get("data", []) if timeline else []):
            date = pd.Timestamp(entry["date"][:8])
            norm = entry.get("norm") or 0
            if norm > 0:
                points[date] = 100.0 * entry.get("value", 0) / norm
        chunk_start = chunk_end + pd.Timedelta(days=1)
        time.sleep(SECONDS_BETWEEN_CALLS)
    return pd.Series(points).sort_index()


def fetch(metric, settings):
    """Entry point called by src.fetch. metric['params']['query'] is the
    GDELT query string, e.g. '"interest rate"' or 'tariff OR tariffs'."""
    start, end = fetch_window(
        metric["id"], settings["history_start"], settings["refetch_days"]
    )
    share = fetch_daily_share(metric["params"]["query"], pd.Timestamp(start), pd.Timestamp(end))
    return merge_series(metric["id"], share)
