"""Wikimedia Pageviews API: daily views for one article, as a public
attention proxy.

Free, no key, daily granularity, data back to 2015. Docs:
https://wikimedia.org/api/rest_v1/

agent=user filters out bot traffic. Wikimedia's API policy requires a
descriptive User-Agent with contact info; common.USER_AGENT provides it
(update it with your real repo URL). The most recent day or two may not be
loaded yet; the refetch window picks them up on later runs.
"""

import pandas as pd
import requests

from .common import USER_AGENT, fetch_window, merge_series

API_TEMPLATE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/user/{article}/daily/{start}/{end}"
)


def fetch_daily_views(article, start, end):
    url = API_TEMPLATE.format(
        article=article,
        start=pd.Timestamp(start).strftime("%Y%m%d") + "00",
        end=pd.Timestamp(end).strftime("%Y%m%d") + "00",
    )
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    if response.status_code == 404:
        return pd.Series(dtype=float)  # no data in range yet
    response.raise_for_status()
    points = {
        pd.Timestamp(item["timestamp"][:8]): float(item["views"])
        for item in response.json().get("items", [])
    }
    return pd.Series(points).sort_index()


def fetch(metric, settings):
    """Entry point called by src.fetch. metric['params']['article'] is the
    exact article title with underscores, e.g. Federal_Reserve."""
    start, end = fetch_window(
        metric["id"], settings["history_start"], settings["refetch_days"]
    )
    views = fetch_daily_views(metric["params"]["article"], start, end)
    return merge_series(metric["id"], views)
