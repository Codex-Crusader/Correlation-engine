# Disclaimer

This project exists to demonstrate honest statistical methodology. Read this
anyway, because the subject matter (markets, government activity, news) makes
it easy to misuse.

## Correlation is not causation. Ever.

Every output of this tool - every "edge," every chart, every lead–lag
ordering - describes **co-movement between two time series**. It never
describes cause and effect. A pattern where changes in news coverage precede
changes in a market indicator by two days routinely means the market moved
first and the news cycle is slow, or that a third event drove both. The tool
deliberately never uses causal language. Neither may you, when quoting it.

## Not financial advice

Some of the tracked series are market indicators (Treasury yields, the VIX,
exchange rates, oil prices). **Nothing this tool publishes is investment
advice, a trading signal, or a prediction of any market's future behavior.**
It is a statistics demonstration. If you trade on a pattern this tool
surfaced, that decision and its consequences are entirely yours.

## Not policy analysis

Some tracked series count government documents (executive orders,
proclamations, memoranda). A correlation involving them is not a statement
about any administration's intent, effectiveness, or future actions.

## The statistics are approximate, by documented necessity

- The false-discovery correction assumes independence or positive dependence
  between tests; a pair's overlapping lags violate the former. q-values are
  therefore approximate (this is disclosed on the site and in the README).
- The placebo panel exists precisely because the corrections are imperfect.
  If the noise panel resembles the signal panel, trust nothing.
- A published edge means "this pattern recurred for two weeks." Patterns
  stop. Publication is not a promise of persistence.

## Third-party data

All data comes from public third-party APIs: the Federal Register, GDELT,
FRED (Federal Reserve Bank of St. Louis), and Wikimedia. This project does
not control, verify, or guarantee their accuracy, availability, or revision
behavior. Their data remains subject to their own terms of use, and any
analysis inherits their errors.

## No warranty

The software is provided "as is", without warranty of any kind, as stated in
the [LICENSE](LICENSE). The authors are not liable for any decision,
financial or otherwise, made on the basis of this tool's output.

---

*The short version: this is a machine that searches ~4,900 hypotheses a day
and shows you the survivors next to what pure noise produces. It is a lesson
about multiple comparisons wearing a dashboard. Treat it as one.*
