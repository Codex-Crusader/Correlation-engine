"""Render results/latest.json into a static page at docs/index.html.

Run as: python -m src.render_site

Design intent: the honesty is the product. The page leads with the numbers
that contextualize everything (tests run, expected false positives, noise
baseline), and the signature element is a pair of identical graph panels:
today's stable findings next to what the same pipeline finds in pure noise.
If those two panels look alike, the reader should trust nothing, and the
page makes that comparison unavoidable rather than burying it in a footnote.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "results" / "latest.json"
OUTPUT_PATH = ROOT / "docs" / "index.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Correlation Engine — daily pattern scan with its error bars showing</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@500;600&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
:root {
  --paper: #F2F4F1; --ink: #1C2B2D; --muted: #66716F;
  --line: #C9D0CC; --pos: #0F7B6C; --neg: #B0492F;
}
* { box-sizing: border-box; margin: 0; }
body {
  background: var(--paper); color: var(--ink);
  font: 16px/1.6 "IBM Plex Sans", sans-serif;
  max-width: 1080px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem;
}
h1 { font: 600 2.4rem/1.15 "Zilla Slab", serif; letter-spacing: -0.01em; }
h2 { font: 600 1.35rem/1.3 "Zilla Slab", serif; margin: 2.75rem 0 0.75rem; }
.subtitle { color: var(--muted); margin-top: 0.5rem; max-width: 46rem; }
.mono { font-family: "IBM Plex Mono", monospace; }
.rundate { font-family: "IBM Plex Mono", monospace; color: var(--muted);
  font-size: 0.85rem; margin-top: 1rem; }

/* Honesty strip: same visual weight as anything on the page. */
.honesty { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1px; background: var(--line); border: 1px solid var(--line); margin-top: 2rem; }
.honesty div { background: var(--paper); padding: 1rem 1.1rem; }
.honesty .num { font: 500 2rem/1.1 "IBM Plex Mono", monospace; display: block; }
.honesty .lbl { color: var(--muted); font-size: 0.85rem; }

.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-top: 1rem; }
@media (max-width: 780px) { .panels { grid-template-columns: 1fr; } }
.panel { border: 1px solid var(--line); padding: 1rem; }
.panel h3 { font: 500 0.95rem "IBM Plex Mono", monospace; text-transform: uppercase;
  letter-spacing: 0.06em; }
.panel p { color: var(--muted); font-size: 0.85rem; margin-top: 0.25rem; }
.panel svg { width: 100%; height: auto; display: block; margin-top: 0.75rem; }

table { border-collapse: collapse; width: 100%; margin-top: 1rem;
  font-size: 0.9rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--line); }
th { font: 500 0.78rem "IBM Plex Mono", monospace; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); }
td.mono { font-size: 0.85rem; }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.empty { color: var(--muted); font-style: italic; padding: 1.5rem 0; }
.method { max-width: 46rem; }
.method p { margin-top: 0.9rem; }
.method strong { font-weight: 600; }
footer { margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: 0.85rem; }
a { color: inherit; }
</style>
</head>
<body>
<header>
  <h1>Correlation Engine</h1>
  <p class="subtitle">A daily scan for statistical patterns across government
  announcements, news coverage, economic indicators, and public attention —
  shown next to what pure noise produces under the identical pipeline.
  <strong>Nothing on this page is a causal claim.</strong></p>
  <p class="rundate">run __RUN_DATE__ · __N_METRICS__ metrics · lags −__MAX_LAG__…+__MAX_LAG__ days</p>
</header>

<section class="honesty" aria-label="Multiple comparisons context">
  <div><span class="num">__N_TESTS__</span><span class="lbl">hypothesis tests run today (pairs × lags)</span></div>
  <div><span class="num">≈ __EXPECTED_FP__</span><span class="lbl">hits expected from chance alone at raw p &lt; 0.05</span></div>
  <div><span class="num">__PLACEBO_MEAN__</span><span class="lbl">avg edges the same pipeline finds in pure noise (__PLACEBO_REPS__ runs)</span></div>
  <div><span class="num">__N_STABLE__</span><span class="lbl">edges published after FDR, effect-size, and stability filters</span></div>
</section>

<section class="panels">
  <div class="panel">
    <h3>Signal — stable edges</h3>
    <p>Survived FDR q &lt; __FDR_Q__, |ρ| ≥ __MIN_RHO__, and appeared in ≥ __STAB_MIN__ of the last __STAB_RUNS__ runs.</p>
    <svg id="graph-real" viewBox="0 0 460 460"></svg>
  </div>
  <div class="panel">
    <h3>Noise — placebo panel</h3>
    <p>The identical analysis run on phase-randomized surrogates: same wiggliness, no real relationships. If this side has edges too, calibrate your trust accordingly.</p>
    <svg id="graph-placebo" viewBox="0 0 460 460"></svg>
  </div>
</section>

<section>
  <h2>Published edges</h2>
  __EDGE_TABLE__
</section>

<section class="method">
  <h2>Methodology, including why you should stay skeptical</h2>
  <p><strong>Correlation, never causation.</strong> An edge means two change
  series moved together, possibly at a lag. Government announcements usually
  respond to events, so even a suggestive lead–lag ordering routinely points
  backwards, and most co-movement is driven by some third thing.</p>
  <p><strong>Changes, not levels.</strong> Every series is differenced until
  it passes a stationarity test, then adjusted for day-of-week cycles.
  Correlating raw trending levels manufactures fake relationships; this
  pipeline refuses to do it.</p>
  <p><strong>Multiple comparisons.</strong> Testing __N_TESTS__ hypotheses
  guarantees chance hits; the strip above says how many. Benjamini–Hochberg
  correction bounds the expected false-discovery share at __FDR_Q_PCT__%.
  The lags of a single pair are not independent tests, so treat q-values as
  approximate — which is what the noise panel is for.</p>
  <p><strong>Stability.</strong> A pattern that appears once is noise. Edges
  are published only after recurring, with the same sign, across most of the
  recent daily runs.</p>
  <p><strong>Audit trail.</strong> Every fetched observation and every daily
  result is committed to the repository, so the full history of what this
  tool saw and claimed is public in the commit log.</p>
</section>

<footer>Data: Federal Register API · GDELT DOC 2.0 · FRED · Wikimedia Pageviews.
Rebuilt daily by GitHub Actions. Source and data history: <a href="__REPO_URL__">repository</a>.</footer>

<script>
const DATA = __DATA_JSON__;

function drawGraph(svgId, edges) {
  const svg = document.getElementById(svgId);
  const metrics = DATA.metrics_in_analysis;
  const size = 460, cx = size / 2, cy = size / 2, radius = 165;
  const pos = {};
  metrics.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / metrics.length - Math.PI / 2;
    pos[id] = [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle), angle];
  });
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs) => {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  for (const e of edges) {
    const [x1, y1] = pos[e.metric_a] || [], [x2, y2] = pos[e.metric_b] || [];
    if (x1 === undefined || x2 === undefined) continue;
    svg.appendChild(el("line", {
      x1, y1, x2, y2,
      stroke: e.rho >= 0 ? "var(--pos)" : "var(--neg)",
      "stroke-width": (1 + 4 * Math.abs(e.rho)).toFixed(1),
      "stroke-opacity": 0.75,
    }));
  }
  const connected = new Set(edges.flatMap(e => [e.metric_a, e.metric_b]));
  metrics.forEach(id => {
    const [x, y, angle] = pos[id];
    svg.appendChild(el("circle", {
      cx: x, cy: y, r: connected.has(id) ? 5 : 3,
      fill: connected.has(id) ? "var(--ink)" : "var(--line)",
    }));
    const lx = cx + (radius + 14) * Math.cos(angle);
    const ly = cy + (radius + 14) * Math.sin(angle);
    const label = el("text", {
      x: lx, y: ly, "font-size": "8.5",
      "font-family": "IBM Plex Mono, monospace",
      fill: connected.has(id) ? "var(--ink)" : "var(--muted)",
      "text-anchor": Math.cos(angle) > 0.2 ? "start" : (Math.cos(angle) < -0.2 ? "end" : "middle"),
      "dominant-baseline": "middle",
    });
    label.textContent = id;
    svg.appendChild(label);
  });
  if (edges.length === 0) {
    const note = el("text", {
      x: cx, y: cy, "text-anchor": "middle", fill: "var(--muted)",
      "font-family": "IBM Plex Mono, monospace", "font-size": "12",
    });
    note.textContent = svgId === "graph-real"
      ? "no edges passed all filters" : "noise produced no edges today";
    svg.appendChild(note);
  }
}
drawGraph("graph-real", DATA.stable_edges);
drawGraph("graph-placebo", DATA.placebo.example_edges);
</script>
</body>
</html>"""


def lag_phrase(edge, labels):
    """Careful wording: temporal precedence, never causal direction."""
    a = labels.get(edge["metric_a"], edge["metric_a"])
    b = labels.get(edge["metric_b"], edge["metric_b"])
    if edge["lag"] == 0:
        return "same day"
    leader, follower, days = (a, b, edge["lag"]) if edge["lag"] > 0 else (b, a, -edge["lag"])
    return f"changes in “{leader}” precede “{follower}” by {days}d (not causal)"


def edge_table(summary):
    edges = summary["stable_edges"]
    if not edges:
        return ('<p class="empty">No edge passed all four filters today. '
                "That is a valid, honest result, not a malfunction.</p>")
    labels = summary["labels"]
    rows = []
    for e in sorted(edges, key=lambda edge: -abs(edge["rho"])):
        sign_class = "pos" if e["rho"] >= 0 else "neg"
        rows.append(
            "<tr>"
            f"<td>{labels.get(e['metric_a'], e['metric_a'])}</td>"
            f"<td>{labels.get(e['metric_b'], e['metric_b'])}</td>"
            f"<td class='mono {sign_class}'>{e['rho']:+.2f}</td>"
            f"<td class='mono'>{e['q_value']:.3f}</td>"
            f"<td class='mono'>{e['appearances']}/{summary['runs_in_stability_window']}</td>"
            f"<td>{lag_phrase(e, labels)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Metric A</th><th>Metric B</th><th>ρ (changes)</th>"
        "<th>q-value</th><th>Runs seen</th><th>Timing</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def main():
    summary = json.loads(RESULTS_PATH.read_text())
    settings = summary["settings"]
    html = TEMPLATE
    for marker, value in {
        "__RUN_DATE__": summary["run_date"],
        "__N_METRICS__": str(len(summary["metrics_in_analysis"])),
        "__MAX_LAG__": str(settings["max_lag_days"]),
        "__N_TESTS__": f"{summary['n_tests']:,}",
        "__EXPECTED_FP__": str(summary["expected_false_positives_at_p05"]),
        "__PLACEBO_MEAN__": f"{summary['placebo']['mean_survivors']:.1f}",
        "__PLACEBO_REPS__": str(summary["placebo"]["reps"]),
        "__N_STABLE__": str(len(summary["stable_edges"])),
        "__FDR_Q__": str(settings["fdr_q"]),
        "__FDR_Q_PCT__": str(round(settings["fdr_q"] * 100)),
        "__MIN_RHO__": str(settings["min_abs_rho"]),
        "__STAB_MIN__": str(settings["stability_min"]),
        "__STAB_RUNS__": str(settings["stability_window"]),
        "__EDGE_TABLE__": edge_table(summary),
        "__REPO_URL__": "https://github.com/Codex-Crusader/Correlation-engine",
        "__DATA_JSON__": json.dumps(summary),
    }.items():
        html = html.replace(marker, value)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")  # template has non-cp1252
                                                    # chars; locale default breaks on Windows
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
