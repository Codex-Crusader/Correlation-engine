# Correlation Engine

A daily-updating correlation scan that runs entirely on GitHub Actions. No
server, no database, no paid APIs. Every day it pulls a fixed pool of time
series (government announcements, news coverage volumes, economic
indicators, public attention), tests every pair for correlated changes, and
publishes a static page showing the strongest stable patterns next to what
the identical pipeline finds in pure noise.

The honesty is the product. A naive version of this tool is a machine for
generating false claims; everything below exists to prevent that.

## What an edge means, and what it does not mean

An edge means two *change* series moved together, possibly at a lag of up to
7 days, consistently across the last two weeks of runs. It does not mean one
caused the other. Government announcements usually respond to events, so
even a clean lead–lag ordering routinely points backwards, and most
co-movement in this pool is driven by a third thing (an election, a crisis,
a news cycle) touching both series. The tool never uses causal language, and
neither should you when quoting it.

## The four filters

Every published edge has survived all of these, in order:

1. **Stationarity.** Two series that both trend upward correlate near 0.9
   for no reason (spurious regression). Every series is differenced until it
   passes an ADF test (max twice, then it's dropped and logged), and the
   weekday cycle is removed from the changes, since news volume and
   pageviews have strong weekly rhythms that would otherwise fake lag-7
   correlations. Correlations are Spearman, on changes, never on levels.

2. **Multiple-testing correction.** With ~26 metrics and 15 lags there are
   roughly 4,900 tests per day; at raw p < 0.05 you'd expect ~245 hits from
   chance alone, and re-rolling daily makes it worse. Benjamini–Hochberg FDR
   control (q < 0.05) is applied across all tests, and both raw p and
   corrected q are stored. Honest caveat: the 15 lags of one pair are
   positively dependent rather than independent, so q-values are
   approximate. That approximation is one reason the placebo panel exists.
   An effect-size floor (|ρ| ≥ 0.20) additionally drops
   tiny-but-significant correlations.

3. **Stability.** A correlation that appears once is noise. An edge is
   published only if the same pair, with the same sign, survived filters 1–2
   in at least 10 of the last 14 runs that actually happened.

4. **The placebo panel.** Every day the identical pipeline also runs 20
   times on phase-randomized surrogates: each series is FFT'd, its phases
   are scrambled, and it's transformed back, preserving its power spectrum
   (and so its autocorrelation) while destroying every real cross-series
   relationship. Phase randomization was chosen over shuffling because
   shuffling kills autocorrelation and makes noise look tamer than it is.
   The site shows the noise panel with the same visual weight as the real
   one. If they look alike, trust nothing.

The site always displays: the number of tests run, the expected false
positives at raw p < 0.05, the placebo baseline, and the number of edges
published. Nine edges is a good day. Zero edges is a valid, honest result.

## The metric pool

`config/metrics.yaml` is the entire pool: which series exist, how each is
fetched, and when it was added. The model is a **fixed core with gated
additions**. The founding pool (everything with `date_added` on or before
`pool_founded`) was chosen before the tool had produced any output. Anything
added later waits `eligibility_days` (60) before entering the analysis, so
a result can never recruit the metric that would confirm it. All pool
changes are ordinary commits, so the pool's full history is public.

Keep the pool around 30–50 series. Every addition multiplies the test count,
and the honesty panel will show it.

## Data sources

| Source | What | Auth |
|---|---|---|
| [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | Daily counts of presidential documents (executive orders, proclamations, memoranda), structured at the source | none |
| [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Daily share of global news coverage matching a topic query (`timelinevolraw`, matched/norm) | none, but needs a User-Agent and 429 backoff (handled) |
| [FRED](https://fred.stlouisfed.org/docs/api/fred/) | Daily economic series (yields, VIX, FX, oil) | free key, repo secret `FRED_API_KEY` |
| [Wikimedia Pageviews](https://wikimedia.org/api/rest_v1/) | Daily per-article views, bot traffic excluded (`agent=user`) | none |

Only daily-frequency series are allowed in the pool. Mixing frequencies
would require resampling choices that quietly manufacture autocorrelation.

## Architecture

```
config/metrics.yaml        the pool and all analysis settings
src/fetch.py               runs every fetcher; one flaky source never sinks a run
src/fetchers/              one module per source, independently testable
src/analyze.py             the pipeline: preprocess -> correlate -> BH -> placebo -> stability
src/stats/                 the statistics package (the heart of the project)
src/render_site.py         results/latest.json -> docs/index.html
data/                      one CSV per metric, committed every run
results/history/           one JSON per run: the edges that survived that day
docs/                      the published site (GitHub Pages, main branch /docs)
.github/workflows/daily.yml
```

**Git-scraping.** Every fetched observation and every daily result is
committed, so the full history of what the tool saw and claimed is auditable
by anyone reading the log. CSV rather than Parquet, deliberately: the commit
log is the audit trail and CSV diffs are human-readable.

**Cron reliability.** GitHub scheduled workflows run late or get skipped.
The pipeline assumes nothing: fetchers request a date *range* ending today
(first run backfills from `history_start`, later runs re-request a trailing
`refetch_days` window to catch revisions and fill gaps), merges are keyed by
date so re-running a day is idempotent, and the stability filter counts
*runs that happened*, not calendar days. A skipped day needs no special
handling; run `workflow_dispatch` by hand or just wait for tomorrow.

## Setup

1. Create the repo, push this code.
2. Get a free FRED key and add it as the `FRED_API_KEY` Actions secret.
   (Without it, FRED metrics are skipped with a warning; everything else
   still runs.)
3. Settings → Pages → Deploy from a branch → `main`, folder `/docs`.
4. Update `USER_AGENT` in `src/fetchers/common.py` and the repo URL in
   `src/render_site.py` with your real repo path. Wikimedia's API policy
   requires a User-Agent with contact info.
5. Run the workflow once by hand (Actions → daily → Run workflow). The
   first run backfills two years of history and takes the longest.
6. Nothing publishes until an edge has recurred in 10 of the last 14 runs,
   so expect an empty (and correct) graph for roughly the first two weeks.

Run locally:

```bash
pip install -r requirements.txt
python -m pytest tests/          # the stats tests; run these first
FRED_API_KEY=yourkey python -m src.fetch
python -m src.analyze
python -m src.render_site        # then open docs/index.html
```

## Known limits, stated plainly

- **Selection bias survives the gate.** The founding pool was still chosen
  by a person with priors. The gate stops results-driven additions; it
  cannot make the initial choice neutral. The pool file's git history is the
  disclosure.
- **q-values are approximate** under lag dependence, as above.
- **Zero-inflated series.** Executive orders are zero most days and the
  Federal Register doesn't publish weekends. Spearman and the weekday
  adjustment soften this, but sparse-event series are the pool's weakest
  members statistically.
- **GDELT availability.** The DOC API has intermittent outages and rate
  limits. A failed source logs and skips; the range-based refetch fills the
  hole on the next successful run.
- **This finds patterns, not truths.** The correct reading of any edge is:
  "out of ~4,900 searches today, this pattern was the most persistent, and
  here is what pure noise produces under the same search." Nothing more.
