"""Fetch step: pull every configured metric and merge into data/.

Run as: python -m src.fetch

One flaky source must not sink the run, so failures are logged per metric
and the step succeeds if anything at all was fetched. The analysis step
works off whatever history exists.

Metrics run in two concurrent lanes: GDELT alone in one, every other source
in the other. GDELT is paced at 45s between calls and that pacing is pure
idle sleep, so the second lane's work hides inside those gaps; each API
still sees exactly the same calls at the same spacing, the job just stops
paying for the sleeps twice. GDELT's pacing/breaker globals are only ever
touched from its own lane, and lanes never share a metric's CSV.
"""

import datetime
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from .fetchers import federal_register, fred, gdelt, wikipedia
from .fetchers.common import last_stored_date

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "metrics.yaml"

FETCHERS = {
    "federal_register": federal_register.fetch,
    "fred": fred.fetch,
    "gdelt": gdelt.fetch,
    "wikipedia": wikipedia.fetch,
}


def load_config():
    return yaml.safe_load(CONFIG_PATH.read_text())


def staleness(metric):
    """Sort key: never-fetched metrics first, then oldest last-stored date.

    GDELT's per-IP budget can run out mid-run, and in config order the same
    tail metrics would starve every day; stalest-first means whatever missed
    out yesterday gets first claim on today's budget."""
    return last_stored_date(metric["id"]) or datetime.date.min


def lane_split(metrics):
    """Two serial lanes, each stalest-first: GDELT (paced), everything else.

    Stalest-first matters most inside the GDELT lane, where the per-IP
    budget can run out mid-run; splitting first preserves that ordering."""
    ordered = sorted(metrics, key=staleness)
    return (
        [m for m in ordered if m["source"] == "gdelt"],
        [m for m in ordered if m["source"] != "gdelt"],
    )


def fetch_lane(metrics, settings):
    """Fetch one lane serially. Returns (successes, failures)."""
    successes, failures = 0, 0
    for metric in metrics:
        fetcher = FETCHERS[metric["source"]]
        # Deliberately broad: one flaky source must not sink the whole run
        # (see module docstring).
        # noinspection PyBroadException
        try:
            rows = fetcher(metric, settings)
            print(f"  OK   {metric['id']}: {rows} rows stored")
            successes += 1
        except Exception:
            print(f"  FAIL {metric['id']}")
            traceback.print_exc()
            failures += 1
    return successes, failures


def main():
    config = load_config()
    settings = config["settings"]
    lanes = lane_split(config["metrics"])
    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        outcomes = list(pool.map(lambda lane: fetch_lane(lane, settings), lanes))
    successes = sum(ok for ok, _ in outcomes)
    failures = sum(failed for _, failed in outcomes)
    print(f"Fetch done: {successes} ok, {failures} failed")
    if successes == 0:
        sys.exit(1)  # nothing fetched at all: fail loudly


if __name__ == "__main__":
    main()
