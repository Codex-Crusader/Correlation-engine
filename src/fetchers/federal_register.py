"""Federal Register API: daily counts of presidential documents.

Structured and dated at the source, so no scraping. Docs:
https://www.federalregister.gov/developers/documentation/api/v1

One metric = daily count of one presidential document subtype. Days with no
documents are explicitly recorded as 0; missing zeros would bias every
correlation. Note the Federal Register does not publish on weekends and
holidays, which creates a weekly cycle; the preprocessing step's weekday
adjustment exists partly for this.
"""

import pandas as pd

from .common import fetch_window, get_json, merge_series

API_URL = "https://www.federalregister.gov/api/v1/documents.json"


def fetch_daily_counts(subtype, start, end):
    """Count documents of one presidential subtype per publication date."""
    params = {
        "conditions[type][]": "PRESDOCU",
        "conditions[presidential_document_type][]": subtype,
        "conditions[publication_date][gte]": start.isoformat(),
        "conditions[publication_date][lte]": end.isoformat(),
        "fields[]": "publication_date",
        "per_page": 1000,
    }
    dates = []
    payload = get_json(API_URL, params=params)
    while True:
        dates += [doc["publication_date"] for doc in payload.get("results", [])]
        next_page = payload.get("next_page_url")
        if not next_page:
            break
        payload = get_json(next_page)

    full_range = pd.date_range(start, end, freq="D")
    counts = pd.Series(0.0, index=full_range)
    if dates:
        observed = pd.to_datetime(pd.Series(dates)).value_counts()
        counts = counts.add(observed.reindex(full_range, fill_value=0), fill_value=0)
    return counts


def fetch(metric, settings):
    """Entry point called by src.fetch. metric['params']['subtype'] selects
    the document type, e.g. executive_order or proclamation."""
    start, end = fetch_window(
        metric["id"], settings["history_start"], settings["refetch_days"]
    )
    counts = fetch_daily_counts(metric["params"]["subtype"], start, end)
    return merge_series(metric["id"], counts)
