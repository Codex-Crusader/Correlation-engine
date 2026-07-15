"""Mocked-API tests for the fetchers.

Nothing here touches the network or the real data/ directory: requests.get
and time are stubbed, and DATA_DIR is redirected to a temp directory. The
targets are the behaviours most likely to break silently: merge idempotency,
resume windows, 429/backoff handling in get_json, and the GDELT circuit
breaker and cross-metric pacing.
"""

import datetime
import threading
import time

import pandas as pd
import pytest
import requests

from src import fetch as fetch_step
from src.fetch import fetch_lane, lane_split, staleness
from src.fetchers import common, federal_register, fred, gdelt, wikipedia
from src.fetchers.common import (
    PermanentAPIError,
    fetch_window,
    get_json,
    load_series,
    merge_series,
    series_path,
)

SETTINGS = {"history_start": "2026-01-01", "refetch_days": 3}


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def fresh_gdelt_state(monkeypatch):
    monkeypatch.setattr(gdelt, "_throttled", False)
    monkeypatch.setattr(gdelt, "_last_call_at", 0.0)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def install_http(monkeypatch, script):
    """Replace requests.get with a scripted sequence. Each entry is a
    FakeResponse to return or an exception instance to raise. Returns the
    call log."""
    calls = []

    def fake_get(url, params=None, **_):
        calls.append({"url": url, "params": params})
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(common.requests, "get", fake_get)
    return calls


def series(dates, values):
    return pd.Series(values, index=pd.DatetimeIndex(dates), name="value")


def ts(value) -> pd.Timestamp:
    """pd.Timestamp with the NaT branch of the stub signature ruled out, so
    type checkers accept it where a plain Timestamp is required."""
    stamp = pd.Timestamp(value)
    assert isinstance(stamp, pd.Timestamp)
    return stamp


# -------------------------------------------------------------- merge_series

def test_merge_roundtrips_through_csv():
    rows = merge_series("m", series(["2026-01-01", "2026-01-02"], [1.0, 2.0]))
    assert rows == 2
    stored = load_series("m")
    assert list(stored) == [1.0, 2.0]
    assert list(stored.index) == list(pd.to_datetime(["2026-01-01", "2026-01-02"]))


def test_merge_is_idempotent():
    fresh = series(["2026-01-01", "2026-01-02"], [1.0, 2.0])
    merge_series("m", fresh)
    first_csv = series_path("m").read_text()
    rows = merge_series("m", fresh)
    assert rows == 2
    assert series_path("m").read_text() == first_csv


def test_new_values_win_on_conflict():
    # Sources revise recent data; a refetch must overwrite, not keep stale.
    merge_series("m", series(["2026-01-01"], [1.0]))
    merge_series("m", series(["2026-01-01"], [9.0]))
    assert load_series("m")["2026-01-01"] == 9.0


def test_merge_preserves_history_outside_new_range():
    merge_series("m", series(["2026-01-01", "2026-01-02"], [1.0, 2.0]))
    merge_series("m", series(["2026-01-10"], [10.0]))
    stored = load_series("m")
    assert len(stored) == 3
    assert stored["2026-01-01"] == 1.0


def test_empty_merge_writes_nothing():
    assert merge_series("m", pd.Series(dtype=float)) == 0
    assert not series_path("m").exists()


def test_duplicate_dates_in_fetch_keep_last():
    duplicated = pd.Series(
        [1.0, 2.0], index=pd.DatetimeIndex(["2026-01-01", "2026-01-01"])
    )
    assert merge_series("m", duplicated) == 1
    assert load_series("m")["2026-01-01"] == 2.0


# -------------------------------------------------------------- fetch_window

def test_first_run_window_starts_at_history_start():
    start, end = fetch_window("never_fetched", "2024-01-01", 3)
    assert start == datetime.date(2024, 1, 1)
    assert end == datetime.datetime.now(datetime.timezone.utc).date()


def test_resume_window_backs_up_refetch_days():
    merge_series("m", series(["2026-06-30", "2026-07-01"], [1.0, 2.0]))
    start, _ = fetch_window("m", "2024-01-01", 3)
    assert start == datetime.date(2026, 6, 28)


# ------------------------------------------------------------------ get_json

def test_429_then_success_honors_retry_after(monkeypatch, sleeps):
    calls = install_http(monkeypatch, [
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, payload={"ok": True}),
    ])
    assert get_json("http://x") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [7]


def test_retry_after_is_capped(monkeypatch, sleeps):
    install_http(monkeypatch, [
        FakeResponse(429, headers={"Retry-After": "9999"}),
        FakeResponse(200, payload={}),
    ])
    get_json("http://x")
    assert sleeps == [300]


def test_gives_up_on_429_without_a_final_wasted_sleep(monkeypatch, sleeps):
    install_http(monkeypatch, [FakeResponse(429), FakeResponse(429)])
    with pytest.raises(RuntimeError, match="429"):
        get_json("http://x", max_retries=2, base_delay=5)
    assert sleeps == [5]  # backoff between attempts, none after the last


def test_5xx_is_retried(monkeypatch, sleeps):
    calls = install_http(monkeypatch, [
        FakeResponse(503),
        FakeResponse(200, payload={"ok": True}),
    ])
    assert get_json("http://x") == {"ok": True}
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_transient_network_error_is_retried(monkeypatch, sleeps):
    calls = install_http(monkeypatch, [
        requests.exceptions.ConnectionError("dropped"),
        FakeResponse(200, payload={"ok": True}),
    ])
    assert get_json("http://x") == {"ok": True}
    assert len(calls) == 2


def test_network_error_on_last_attempt_propagates(monkeypatch, sleeps):
    install_http(monkeypatch, [
        requests.exceptions.ConnectionError("dropped"),
        requests.exceptions.ConnectionError("dropped"),
    ])
    with pytest.raises(requests.exceptions.ConnectionError):
        get_json("http://x", max_retries=2)


def test_gdelt_text_throttle_is_treated_as_retryable(monkeypatch, sleeps):
    # GDELT rate-limits with HTTP 200 and a plain-text notice, not a 429.
    install_http(monkeypatch, [
        FakeResponse(200, text="Please limit requests to one every 5 seconds."),
        FakeResponse(200, payload={"ok": True}),
    ])
    assert get_json("http://x") == {"ok": True}
    assert len(sleeps) == 1


def test_non_throttle_error_body_fails_fast(monkeypatch, sleeps):
    calls = install_http(monkeypatch, [
        FakeResponse(200, text="Invalid query syntax near OR."),
    ])
    with pytest.raises(PermanentAPIError):
        get_json("http://x")
    assert len(calls) == 1  # no retries: backing off cannot fix a bad query
    assert sleeps == []


def test_client_error_raises_immediately(monkeypatch, sleeps):
    calls = install_http(monkeypatch, [FakeResponse(404)])
    with pytest.raises(requests.HTTPError):
        get_json("http://x")
    assert len(calls) == 1
    assert sleeps == []


# --------------------------------------------------------------------- gdelt

class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def gdelt_payload(rows):
    return {"timeline": [{"data": [
        {"date": pd.Timestamp(date).strftime("%Y%m%d") + "000000",
         "value": value, "norm": norm}
        for date, value, norm in rows
    ]}]}


def test_pacing_spans_separate_fetch_calls(monkeypatch):
    # The regression that got CI blocked: with one call per metric, pacing
    # per chunk alone lets back-to-back metrics hit the API with no gap.
    clock = FakeClock()
    monkeypatch.setattr(gdelt.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(gdelt.time, "sleep", clock.sleep)

    def fake_get_json(*_args, **_kwargs):
        clock.now += 3.0  # the HTTP round-trip takes a moment
        return gdelt_payload([("2026-01-01", 5, 100)])

    monkeypatch.setattr(gdelt, "get_json", fake_get_json)
    gdelt.fetch({"id": "g1", "params": {"query": "tariff"}}, SETTINGS)
    gdelt.fetch({"id": "g2", "params": {"query": "rates"}}, SETTINGS)
    assert clock.sleeps == [pytest.approx(gdelt.SECONDS_BETWEEN_CALLS - 3.0)]


def test_breaker_trips_and_remaining_metrics_fail_fast(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)
    calls = []

    def throttled(url, **_):
        calls.append(url)
        raise RuntimeError("still throttled after 5 attempts")

    monkeypatch.setattr(gdelt, "get_json", throttled)
    with pytest.raises(RuntimeError):
        gdelt.fetch({"id": "g1", "params": {"query": "tariff"}}, SETTINGS)
    assert gdelt._throttled is True
    with pytest.raises(RuntimeError, match="earlier in this run"):
        gdelt.fetch({"id": "g2", "params": {"query": "rates"}}, SETTINGS)
    assert len(calls) == 1  # the second metric never burned an API call


def test_permanent_error_does_not_trip_breaker(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)

    def bad_query(*_args, **_kwargs):
        raise PermanentAPIError("bad query")

    monkeypatch.setattr(gdelt, "get_json", bad_query)
    with pytest.raises(PermanentAPIError):
        gdelt.fetch({"id": "g1", "params": {"query": "tariff"}}, SETTINGS)
    assert gdelt._throttled is False


def test_partial_progress_keeps_contiguous_prefix(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)
    script = [
        gdelt_payload([("2020-01-01", 5, 100), ("2020-01-02", 8, 200)]),
        RuntimeError("throttled"),
    ]

    def scripted(*_args, **_kwargs):
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(gdelt, "get_json", scripted)
    start = ts("2020-01-01")
    end = ts(start + pd.Timedelta(days=gdelt.CHUNK_DAYS + 50))  # spans two chunks
    share = gdelt.fetch_daily_share("tariff", start, end)
    assert list(share) == [pytest.approx(5.0), pytest.approx(4.0)]
    assert gdelt._throttled is True


def test_failure_on_first_chunk_raises(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)

    def throttled(*_args, **_kwargs):
        raise RuntimeError("throttled")

    monkeypatch.setattr(gdelt, "get_json", throttled)
    with pytest.raises(RuntimeError):
        gdelt.fetch_daily_share("tariff", ts("2026-01-01"), ts("2026-01-05"))


def test_or_query_is_parenthesized(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)
    seen = []

    def capture(*_args, params=None, **_kwargs):
        seen.append(params["query"])
        return gdelt_payload([("2026-01-01", 1, 100)])

    monkeypatch.setattr(gdelt, "get_json", capture)
    gdelt.fetch({"id": "g", "params": {"query": "tariff OR tariffs"}}, SETTINGS)
    assert seen == ["(tariff OR tariffs)"]


def test_share_is_percent_of_norm_and_zero_norm_days_are_skipped(monkeypatch):
    monkeypatch.setattr(gdelt, "_pace", lambda: None)
    payload = gdelt_payload([("2026-01-01", 5, 200), ("2026-01-02", 3, 0)])
    monkeypatch.setattr(gdelt, "get_json", lambda *_args, **_kwargs: payload)
    share = gdelt.fetch_daily_share("tariff", ts("2026-01-01"), ts("2026-01-02"))
    assert list(share.index) == [pd.Timestamp("2026-01-01")]
    assert share.iloc[0] == pytest.approx(2.5)


# ---------------------------------------------------------------------- fred

def test_fred_skips_when_key_missing(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    def must_not_be_called(*_args, **_kwargs):
        raise AssertionError("no API call should happen without a key")

    monkeypatch.setattr(fred, "get_json", must_not_be_called)
    assert fred.fetch({"id": "f", "params": {"series_id": "VIXCLS"}}, SETTINGS) == 0


def test_fred_parses_values_and_skips_missing_marker(monkeypatch):
    payload = {"observations": [
        {"date": "2026-01-02", "value": "1.5"},
        {"date": "2026-01-03", "value": "."},
    ]}
    monkeypatch.setattr(fred, "get_json", lambda *_args, **_kwargs: payload)
    values = fred.fetch_daily_values("VIXCLS", "key", datetime.date(2026, 1, 1))
    assert len(values) == 1
    assert values["2026-01-02"] == 1.5


# ----------------------------------------------------------------- wikipedia

def test_wikipedia_404_means_no_data_yet(monkeypatch):
    install_http(monkeypatch, [FakeResponse(404)])
    views = wikipedia.fetch_daily_views("Some_Article", "2026-01-01", "2026-01-05")
    assert views.empty


def test_wikipedia_parses_daily_views(monkeypatch):
    payload = {"items": [
        {"timestamp": "2026010100", "views": 100},
        {"timestamp": "2026010200", "views": 250},
    ]}
    install_http(monkeypatch, [FakeResponse(200, payload=payload)])
    views = wikipedia.fetch_daily_views("Some_Article", "2026-01-01", "2026-01-02")
    assert views["2026-01-02"] == 250.0


# ---------------------------------------------------------- federal_register

def test_days_without_documents_are_recorded_as_zero(monkeypatch):
    payload = {"results": [{"publication_date": "2026-01-02"}]}
    monkeypatch.setattr(
        federal_register, "get_json", lambda *_args, **_kwargs: payload
    )
    counts = federal_register.fetch_daily_counts(
        "executive_order", datetime.date(2026, 1, 1), datetime.date(2026, 1, 3)
    )
    assert len(counts) == 3
    assert counts["2026-01-01"] == 0.0
    assert counts["2026-01-02"] == 1.0


def test_pagination_is_followed(monkeypatch):
    pages = [
        {"results": [{"publication_date": "2026-01-01"}],
         "next_page_url": "http://page2"},
        {"results": [{"publication_date": "2026-01-01"}]},
    ]
    urls = []

    def scripted(url, **_):
        urls.append(url)
        return pages.pop(0)

    monkeypatch.setattr(federal_register, "get_json", scripted)
    counts = federal_register.fetch_daily_counts(
        "executive_order", datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
    )
    assert counts["2026-01-01"] == 2.0
    assert urls == [federal_register.API_URL, "http://page2"]


# ----------------------------------------------------------------- src.fetch

def test_stalest_metrics_sort_first():
    merge_series("fresh", series(["2026-07-01"], [1.0]))
    merge_series("stale", series(["2026-01-05"], [1.0]))
    metrics = [{"id": "fresh"}, {"id": "stale"}, {"id": "brand_new"}]
    ordered = [m["id"] for m in sorted(metrics, key=staleness)]
    assert ordered == ["brand_new", "stale", "fresh"]


def test_lane_split_isolates_gdelt_and_keeps_staleness_order():
    merge_series("g_fresh", series(["2026-07-01"], [1.0]))
    merge_series("w_fresh", series(["2026-07-01"], [1.0]))
    metrics = [
        {"id": "g_fresh", "source": "gdelt"},
        {"id": "g_new", "source": "gdelt"},
        {"id": "w_fresh", "source": "wikipedia"},
        {"id": "f_new", "source": "fred"},
    ]
    gdelt_lane, other_lane = lane_split(metrics)
    assert [m["id"] for m in gdelt_lane] == ["g_new", "g_fresh"]
    assert [m["id"] for m in other_lane] == ["f_new", "w_fresh"]


def test_fetch_lane_counts_failures_without_stopping(monkeypatch):
    monkeypatch.setitem(fetch_step.FETCHERS, "gdelt", lambda m, s: 5)
    monkeypatch.setitem(
        fetch_step.FETCHERS, "fred",
        lambda m, s: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ok, failed = fetch_lane(
        [{"id": "a", "source": "gdelt"},
         {"id": "b", "source": "fred"},
         {"id": "c", "source": "gdelt"}],
        {},
    )
    assert (ok, failed) == (2, 1)


def test_lanes_actually_overlap(monkeypatch):
    # The whole point of the lanes: the non-GDELT lane must run WHILE the
    # GDELT lane is busy. The stub GDELT fetcher waits for the other lane's
    # signal; under any serial execution this would time out.
    other_lane_ran = threading.Event()
    overlap = {}

    def gdelt_stub(*_args, **_kwargs):
        overlap["seen"] = other_lane_ran.wait(timeout=10)
        return 1

    def fred_stub(*_args, **_kwargs):
        other_lane_ran.set()
        return 1

    monkeypatch.setitem(fetch_step.FETCHERS, "gdelt", gdelt_stub)
    monkeypatch.setitem(fetch_step.FETCHERS, "fred", fred_stub)
    monkeypatch.setattr(fetch_step, "load_config", lambda: {
        "settings": {},
        "metrics": [
            {"id": "g", "source": "gdelt"},
            {"id": "f", "source": "fred"},
        ],
    })
    fetch_step.main()
    assert overlap["seen"] is True
