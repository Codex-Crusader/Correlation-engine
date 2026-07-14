"""Fetch step: pull every configured metric and merge into data/.

Run as: python -m src.fetch

One flaky source must not sink the run, so failures are logged per metric
and the step succeeds if anything at all was fetched. The analysis step
works off whatever history exists.
"""

import datetime
import sys
import traceback
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


def main():
    config = load_config()
    settings = config["settings"]
    successes, failures = 0, 0
    for metric in sorted(config["metrics"], key=staleness):
        fetcher = FETCHERS[metric["source"]]
        # noinspection PyBroadException -- deliberate: one flaky source must
        # not sink the whole run (see module docstring)
        try:
            rows = fetcher(metric, settings)
            print(f"  OK   {metric['id']}: {rows} rows stored")
            successes += 1
        except Exception:
            print(f"  FAIL {metric['id']}")
            traceback.print_exc()
            failures += 1
    print(f"Fetch done: {successes} ok, {failures} failed")
    if successes == 0:
        sys.exit(1)  # nothing fetched at all: fail loudly


if __name__ == "__main__":
    main()
