"""Tests for the site renderer's pure helpers. The HTML itself is checked
by eye; these pin the numbers and flags feeding it."""

from src.render_site import (
    calibration_ratio,
    common_driver_method,
    freshness_table,
    partial_cell,
    placebo_partial_cell,
)


def test_calibration_is_survivors_over_noise_mean():
    summary = {"n_survivors_today": 53, "placebo": {"mean_survivors": 202.1}}
    assert calibration_ratio(summary) == "0.26×"


def test_calibration_guards_degenerate_noise_mean():
    summary = {"n_survivors_today": 5, "placebo": {"mean_survivors": 0.0}}
    assert calibration_ratio(summary) == "n/a"


def test_partial_cell_states():
    held = partial_cell({"partial_status": "ok", "partial_rho": 0.31, "common_driver": False})
    faded = partial_cell({"partial_status": "ok", "partial_rho": 0.05, "common_driver": True})
    sample = partial_cell({"partial_status": "ok", "partial_rho": 0.10, "common_driver": None})
    assert "+0.31" in held and "holds" in held
    assert "+0.05" in faded and "fades" in faded and "neg" in faded
    assert "weekends, not stress" in sample and "neg" not in sample
    assert "is the control" in partial_cell({"partial_status": "is_conditioner"})
    assert "low overlap" in partial_cell({"partial_status": "insufficient_overlap"})
    assert partial_cell({}) == "<td class='mono'>-</td>"  # pre-conditioner records


def test_placebo_partial_cell_needs_data():
    assert placebo_partial_cell({"placebo": {}}) == ""
    assert placebo_partial_cell({"placebo": {"partial_flagged_fraction": None}}) == ""
    assert "4%" in placebo_partial_cell({"placebo": {"partial_flagged_fraction": 0.04}})


def test_common_driver_method_needs_conditioner():
    assert common_driver_method({"settings": {}}) == ""
    html = common_driver_method({
        "settings": {"conditioner": "econ_vix"},
        "labels": {"econ_vix": "VIX volatility index"},
        "placebo": {"partial_held_fraction": 0.94},
    })
    assert "VIX volatility index" in html
    assert "not a filter" in html
    assert "94%" in html  # holding is the default outcome, and the page says so


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
