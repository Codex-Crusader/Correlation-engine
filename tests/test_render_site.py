"""Tests for the site renderer's pure helpers. The HTML itself is checked
by eye; these pin the numbers and flags feeding it."""

from src.render_site import calibration_ratio, freshness_table


def test_calibration_is_survivors_over_noise_mean():
    summary = {"n_survivors_today": 53, "placebo": {"mean_survivors": 202.1}}
    assert calibration_ratio(summary) == "0.26×"


def test_calibration_guards_degenerate_noise_mean():
    summary = {"n_survivors_today": 5, "placebo": {"mean_survivors": 0.0}}
    assert calibration_ratio(summary) == "n/a"


def test_freshness_flags_respect_expected_lag():
    summary = {
        "labels": {},
        "freshness": [
            {"id": "on_time", "source": "gdelt", "last_date": "2026-07-14",
             "days_behind": 1, "expected_lag_days": 0},
            {"id": "laggy_but_normal", "source": "fred", "last_date": "2026-07-08",
             "days_behind": 7, "expected_lag_days": 7},
            {"id": "genuinely_stale", "source": "fred", "last_date": "2026-07-03",
             "days_behind": 12, "expected_lag_days": 7},
            {"id": "never", "source": "wikipedia", "last_date": None,
             "days_behind": None, "expected_lag_days": 0},
        ],
    }
    html = freshness_table(summary)
    flagged = [line for line in html.split("<tr") if 'class="stale"' in line]
    assert len(flagged) == 2
    assert any("genuinely_stale" in line for line in flagged)
    assert any("never fetched" in line for line in flagged)
    assert not any("laggy_but_normal" in line for line in flagged)
