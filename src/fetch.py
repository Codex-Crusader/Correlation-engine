"""Fetch step: pull every configured metric and merge into data/.

Run as: python -m src.fetch

One flaky source must not sink the run, so failures are logged per metric
and the step succeeds if anything at all was fetched. The analysis step
works off whatever history exists.
"""

import sys
import traceback
from pathlib import Path

import yaml

from .fetchers import federal_register, fred, gdelt, wikipedia

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "metrics.yaml"

FETCHERS = {
    "federal_register": federal_register.fetch,
    "fred": fred.fetch,
    "gdelt": gdelt.fetch,
    "wikipedia": wikipedia.fetch,
}


def load_config():
    return yaml.safe_load(CONFIG_PATH.read_text())


def main():
    config = load_config()
    settings = config["settings"]
    successes, failures = 0, 0
    for metric in config["metrics"]:
        fetcher = FETCHERS[metric["source"]]
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
