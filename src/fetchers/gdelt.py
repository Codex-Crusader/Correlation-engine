"""GDELT DOC 2.0 API: daily news coverage volume for a topic query.

Mode timelinevolraw returns, per day, the number of matching articles and a
"norm" field with the total articles GDELT monitored that day. We store
100 * matched / norm: the share of global coverage. Raw counts would mostly
measure GDELT's own monitoring volume, which grows and dips on weekends.

GDELT throttles per IP, and GitHub-hosted runners share IP ranges, so the
budget may be exhausted before our run even starts. Three defences:
  - patient per-call retries with long backoff (common.get_json),
  - a circuit breaker: once one call exhausts its retries, the remaining
    GDELT metrics fail fast instead of each burning minutes of backoff,
  - partial progress: chunks are fetched oldest-first, so if throttling
    cuts a backfill short we keep the contiguous prefix; the next run
    resumes from the last stored date.
"""

import time

import pandas as pd

from .common import PermanentAPIError, fetch_window, get_json, merge_series

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# One timeline call serves years of data at daily resolution (verified
# 2026-07: a 744-day request returned daily points across the whole span),
# so a full backfill from history_start is a single call per metric. Fewer
# calls matter more than partial progress: exceeding GDELT's budget blocks
# the IP for ~20 minutes, far longer than any sane retry schedule.
CHUNK_DAYS = 1095
SECONDS_BETWEEN_CALLS = 10  # GDELT asks for >= 5s; extra margin for shared CI IPs
MAX_RETRIES = 5
BASE_DELAY = 10  # waits 10/20/40/80s between attempts (capped in get_json)

# Set once any call gives up: the IP is throttled, so further calls this run
# are pointless. fetch() checks it and fails fast per metric.
_throttled = False


def fetch_daily_share(query: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Daily coverage share (percent of monitored articles) for a query.

    Returns whatever contiguous prefix was fetched before throttling hit;
    raises only if the very first chunk failed (nothing to keep).
    """
    global _throttled
    points = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + pd.Timedelta(days=CHUNK_DAYS - 1), end)
        try:
            payload = get_json(API_URL, params={
                "query": query,
                "mode": "timelinevolraw",
                "format": "json",
                "startdatetime": chunk_start.strftime("%Y%m%d") + "000000",
                "enddatetime": chunk_end.strftime("%Y%m%d") + "235959",
            }, max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
        except PermanentAPIError:
            raise  # bad query, not rate limiting: don't trip the breaker
        except Exception:
            _throttled = True
            if points:
                # Keep the contiguous prefix already fetched; the next run's
                # fetch_window resumes from the last stored date.
                print(f"  ..   GDELT gave out mid-range; keeping "
                      f"{len(points)} days fetched so far")
                break
            raise
        timeline = payload.get("timeline") or []
        for entry in (timeline[0].get("data", []) if timeline else []):
            date = pd.Timestamp(entry["date"][:8])
            norm = entry.get("norm") or 0
            if norm > 0:
                points[date] = 100.0 * entry.get("value", 0) / norm
        chunk_start = chunk_end + pd.Timedelta(days=1)
        if chunk_start <= end:  # no point sleeping after the final chunk
            time.sleep(SECONDS_BETWEEN_CALLS)
    return pd.Series(points).sort_index()


def fetch(metric, settings):
    """Entry point called by src.fetch. metric['params']['query'] is the
    GDELT query string, e.g. '"interest rate"' or 'tariff OR tariffs'."""
    if _throttled:
        raise RuntimeError(
            "GDELT throttled earlier in this run; skipping to avoid more backoff"
        )
    start, end = fetch_window(
        metric["id"], settings["history_start"], settings["refetch_days"]
    )
    query = metric["params"]["query"].strip()
    if " OR " in query and not query.startswith("("):
        query = f"({query})"  # GDELT requires OR'd terms to be parenthesized
    share = fetch_daily_share(query, pd.Timestamp(start), pd.Timestamp(end))
    return merge_series(metric["id"], share)
