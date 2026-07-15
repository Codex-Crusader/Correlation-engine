"""Tests for the analysis step's non-statistical plumbing. The statistics
themselves are covered in test_stats."""

import datetime

import pandas as pd
import pytest

from src.analyze import freshness_report
from src.fetchers import common
from src.fetchers.common import merge_series


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "DATA_DIR", tmp_path)


def store(metric_id, date):
    merge_series(metric_id, pd.Series([1.0], index=pd.DatetimeIndex([date])))


def config_with(ids):
    return {"metrics": [{"id": metric_id, "source": "fred"} for metric_id in ids]}


def test_freshness_reports_days_behind():
    store("m", "2026-07-10")
    report = freshness_report(config_with(["m"]), datetime.date(2026, 7, 15))
    assert report == [{
        "id": "m", "source": "fred",
        "last_date": "2026-07-10", "days_behind": 5,
        "expected_lag_days": 0,
    }]


def test_freshness_carries_expected_lag_from_config():
    store("m", "2026-07-10")
    config = {"metrics": [{"id": "m", "source": "fred", "expected_lag_days": 7}]}
    report = freshness_report(config, datetime.date(2026, 7, 15))
    assert report[0]["expected_lag_days"] == 7


def test_freshness_covers_never_fetched_metrics():
    report = freshness_report(config_with(["ghost"]), datetime.date(2026, 7, 15))
    assert report[0]["last_date"] is None
    assert report[0]["days_behind"] is None


def test_freshness_sorts_never_fetched_then_stalest():
    store("fresh", "2026-07-15")
    store("stale", "2026-07-01")
    report = freshness_report(
        config_with(["fresh", "stale", "ghost"]), datetime.date(2026, 7, 15)
    )
    assert [r["id"] for r in report] == ["ghost", "stale", "fresh"]
