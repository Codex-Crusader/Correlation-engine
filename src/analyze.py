"""Analysis step: read accumulated history, run the statistics, write results.

Run as: python -m src.analyze

Pipeline, in order, with nothing skippable:
  1. Load eligible metrics (past their eligibility gate).
  2. Preprocess each: difference to stationarity, remove weekday cycle.
  3. Spearman correlation for every pair at every lag in the window.
  4. Benjamini-Hochberg FDR correction across ALL tests.
  5. Effect-size floor.
  6. Common-driver annotation: each survivor gets a partial Spearman rho
     with the market-stress conditioner removed. Context only; it never
     gates publication.
  7. Placebo panel: the same steps 3-6 on phase-randomized surrogates.
  8. Stability: today's survivors are appended to history; only edges seen
     in enough recent runs are published.

Output: results/history/edges_<date>.json (one per run, the audit trail)
and results/latest.json (everything the site needs).
"""

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from .fetchers.common import last_stored_date, load_series
from .stats import (
    annotate_partials,
    apply_correction,
    best_lag_per_pair,
    edge_key,
    lagged_correlations,
    load_history,
    preprocess,
    run_placebo_panel,
    stable_edge_keys,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "metrics.yaml"
RESULTS_DIR = ROOT / "results"
HISTORY_DIR = RESULTS_DIR / "history"


def eligible_metrics(config, today):
    """Metrics past their eligibility gate.

    The gate stops today's news from picking today's metrics. Metrics in the
    founding pool (date_added on or before pool_founded) are exempt: they
    were chosen blind, before the tool had produced any result to chase.
    """
    settings = config["settings"]
    wait_days = settings["eligibility_days"]
    founded = pd.Timestamp(settings["pool_founded"]).date()
    eligible, waiting = [], []
    for metric in config["metrics"]:
        added = pd.Timestamp(metric["date_added"]).date()
        if added <= founded or (today - added).days >= wait_days:
            eligible.append(metric)
        else:
            waiting.append(metric["id"])
    return eligible, waiting


def load_and_preprocess(metrics):
    """Load each eligible metric and make it correlation-safe."""
    processed, prep_report = {}, []
    for metric in metrics:
        raw = load_series(metric["id"])
        if raw.empty:
            prep_report.append({"id": metric["id"], "status": "no data"})
            continue
        series, n_diffs = preprocess(raw)
        if series is None:
            prep_report.append({"id": metric["id"], "status": "dropped: not stationary"})
            continue
        processed[metric["id"]] = series
        prep_report.append(
            {"id": metric["id"], "status": "ok", "n_diffs": n_diffs, "n_points": int(raw.notna().sum())}
        )
    return processed, prep_report


def freshness_report(config, today):
    """Per-metric data freshness, for the site's health table and /health.json.

    Covers every configured metric, not just the eligible ones: a metric
    waiting on its eligibility gate is still being fetched daily, and a
    quietly dead source should be visible regardless of analysis status.
    """
    report = []
    for metric in config["metrics"]:
        last = last_stored_date(metric["id"])
        report.append({
            "id": metric["id"],
            "source": metric["source"],
            "last_date": last.isoformat() if last else None,
            "days_behind": None if last is None else (today - last).days,
            "expected_lag_days": metric.get("expected_lag_days", 0),
        })
    # Never-fetched first, then stalest: the table is a triage list, and the
    # problem cases must not hide at the bottom.
    report.sort(key=lambda r: (r["days_behind"] is not None, -(r["days_behind"] or 0)))
    return report


def edge_dict(result):
    record = asdict(result)
    record["rho"] = round(record["rho"], 4)
    record["p_value"] = float(f"{record['p_value']:.3e}")
    record["q_value"] = round(record["q_value"], 4)
    for field in ("partial_rho", "partial_sample_rho"):
        if record[field] is not None:
            record[field] = round(record[field], 4)
    return record


def main():
    config = yaml.safe_load(CONFIG_PATH.read_text())
    settings = config["settings"]
    today = date.today()

    metrics, waiting = eligible_metrics(config, today)
    labels = {m["id"]: m.get("label", m["id"]) for m in config["metrics"]}
    series_by_id, prep_report = load_and_preprocess(metrics)
    print(f"{len(series_by_id)} series in analysis, {len(waiting)} waiting on eligibility")

    # Steps 3-5: correlate, correct, apply the effect-size floor.
    results, n_tests = lagged_correlations(
        series_by_id, settings["max_lag_days"], settings["min_overlap"]
    )
    apply_correction(results)
    survivors = [
        r for r in results
        if r.q_value < settings["fdr_q"] and abs(r.rho) >= settings["min_abs_rho"]
    ]
    survivors = best_lag_per_pair(survivors)
    print(f"{n_tests} tests, {len(survivors)} pairs survive FDR and effect-size filters")

    # Step 6: which survivors are just everything-reacts-to-the-same-crisis?
    conditioner_id = settings.get("conditioner")
    conditioner = series_by_id.get(conditioner_id) if conditioner_id else None
    annotate_partials(
        survivors, series_by_id, conditioner_id, conditioner,
        settings["min_abs_rho"], settings.get("partial_min_overlap", 0),
    )
    n_flagged = sum(1 for r in survivors if r.common_driver)
    print(f"common-driver check vs {conditioner_id}: "
          f"{n_flagged} of {len(survivors)} survivors fade after conditioning")

    # Step 7: what does pure noise produce under the identical pipeline?
    # Seeded by the run date: the committed noise baseline is reproducible
    # bit-for-bit from the audit trail, while each day still gets fresh
    # surrogate draws instead of reusing one noise universe forever.
    placebo = run_placebo_panel(
        series_by_id,
        settings["max_lag_days"],
        settings["min_overlap"],
        settings["fdr_q"],
        settings["min_abs_rho"],
        settings["placebo_reps"],
        seed=int(today.strftime("%Y%m%d")),
        conditioner_id=conditioner_id,
        conditioner=conditioner,
        partial_min_overlap=settings.get("partial_min_overlap", 0),
    )
    placebo["example_edges"] = [edge_dict(r) for r in placebo["example_edges"]]
    print(f"placebo: mean {placebo['mean_survivors']:.1f} edges across {placebo['reps']} noise universes")

    # Step 8: append today's survivors to history, then apply stability.
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_file = HISTORY_DIR / f"edges_{today.isoformat()}.json"
    history_file.write_text(json.dumps(
        {"date": today.isoformat(), "edges": [edge_dict(r) for r in survivors]}, indent=1
    ))

    history = load_history(HISTORY_DIR, settings["stability_window"])
    stable_keys = stable_edge_keys(history, settings["stability_min"])
    stable_edges = []
    for result in survivors:
        key = edge_key(result.metric_a, result.metric_b, result.rho)
        if key in stable_keys:
            record = edge_dict(result)
            record["appearances"] = stable_keys[key]
            stable_edges.append(record)
    print(f"{len(stable_edges)} edges are stable over the last {len(history)} runs")

    summary = {
        "run_date": today.isoformat(),
        "settings": settings,
        "metrics_in_analysis": sorted(series_by_id),
        "metrics_waiting_on_eligibility": waiting,
        "labels": labels,
        "preprocessing": prep_report,
        "n_pairs": len(series_by_id) * (len(series_by_id) - 1) // 2,
        "n_tests": n_tests,
        "expected_false_positives_at_p05": round(n_tests * 0.05, 1),
        "n_survivors_today": len(survivors),
        "runs_in_stability_window": len(history),
        "stable_edges": stable_edges,
        "placebo": placebo,
        "freshness": freshness_report(config, today),
    }
    (RESULTS_DIR / "latest.json").write_text(json.dumps(summary, indent=1))
    print(f"wrote {RESULTS_DIR / 'latest.json'}")


if __name__ == "__main__":
    main()
