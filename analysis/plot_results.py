"""plot_results.py - figures and a summary table built ONLY from graded data (runs.csv written by grade.py).

    python analysis/plot_results.py runs_api/results/runs.csv [more runs.csv ...] --out results/

Writes:
  results/summary.md         per cell and endpoint: n seeds, mean, 95% bootstrap CI over seeds
  results/fig_<endpoint>.svg grouped bars (one group per model, PLAIN vs FULL), with 95% CI whiskers

Every number in the figures comes from runs.csv; nothing is typed by hand. The unit of analysis is the seed
(replicate runs of a seed are averaged first), exactly as in grade.py. Differences are reported in absolute
points, never as relative percentages. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import conditions as C  # noqa: E402
import stats6 as S  # noqa: E402

ENDPOINTS = ["exact", "insight Q", "induction G", "precision P", "creative", "ideas"]
TITLES = {"exact": "Exact-answer accuracy (12 items)", "insight Q": "Insight problems", "induction G": "Grid rule induction",
          "precision P": "Precise execution", "creative": "Constructions (vs reference)", "ideas": "Ideas (gain over baseline)"}
PCT = {"exact", "insight Q", "induction G", "precision P"}          # shares of items: shown as %


def load(paths):
    """{cell: {seed: [values per endpoint ...]}} averaged over replicates of a seed."""
    raw = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for p in paths:
        for r in csv.DictReader(open(p, encoding="utf-8")):
            for e in ENDPOINTS:
                if r.get(e) not in (None, ""):
                    raw[r["cell"]][int(r["seed"])][e].append(float(r[e]))
    return {c: {s: {e: S.mean(v) for e, v in d.items()} for s, d in seeds.items()} for c, seeds in raw.items()}


def cell_stat(data, cell, e):
    xs = [d[e] for d in data.get(cell, {}).values() if e in d]
    if not xs:
        return None
    lo, hi, _ = S.bootstrap_ci(lambda idx: S.mean([xs[i] for i in idx]), len(xs), B=10000, seed=0)
    return {"n": len(xs), "mean": S.mean(xs), "lo": lo, "hi": hi}


def fmt(v, e):
    return f"{100 * v:.1f}" if e in PCT else f"{v:.3f}"


def summary(data):
    cells = sorted(data)
    L = ["# Results summary (generated from runs.csv)\n",
         "Mean over seeds with a 95% percentile bootstrap CI (B = 10,000, seed 0). Accuracy endpoints in % of items.\n"]
    for e in ENDPOINTS:
        L += [f"\n## {TITLES[e]}\n", "| cell | n seeds | mean | 95% CI |", "|---|---|---|---|"]
        for c in cells:
            st = cell_stat(data, c, e)
            if st:
                L.append(f"| {c} | {st['n']} | {fmt(st['mean'], e)} | [{fmt(st['lo'], e)}, {fmt(st['hi'], e)}] |")
    return "\n".join(L) + "\n"


def svg(data, e):
    models = sorted({c.split("@")[1] for c in data})
    conds = [c for c in ("PLAIN", "FULL") if any(f"{c}@{m}" in data for m in models)]
    stats = {(c, m): cell_stat(data, f"{c}@{m}", e) for c in conds for m in models}
    vals = [v for st in stats.values() if st for v in (st["lo"], st["hi"], st["mean"])]
    if not vals:
        return None
    top = 1.0 if e in PCT else max(0.05, max(vals) * 1.15)
    bot = 0.0 if e in PCT else min(0.0, min(vals) * 1.15)
    W, H, L0, T0, B0 = 720, 420, 70, 60, 360
    y = lambda v: B0 - (v - bot) / (top - bot) * (B0 - T0)  # noqa: E731
    colors = {"PLAIN": "#C9B8A6", "FULL": "#D9734E"}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
           f'<text x="{L0}" y="34" font-size="20" font-weight="700" fill="#222">{TITLES[e]}</text>']
    for k in range(6):
        v = bot + (top - bot) * k / 5
        out.append(f'<line x1="{L0}" x2="{W - 150}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#EEE"/>')
        out.append(f'<text x="{L0 - 8}" y="{y(v) + 4:.1f}" font-size="12" text-anchor="end" fill="#777">{fmt(v, e)}</text>')
    gw = (W - 150 - L0) / max(1, len(models))
    bw = min(70, gw / (len(conds) + 1))
    for i, m in enumerate(models):
        x0 = L0 + i * gw + (gw - bw * len(conds)) / 2
        for j, c in enumerate(conds):
            st = stats[(c, m)]
            if not st:
                continue
            x = x0 + j * bw
            y1, y0 = y(st["mean"]), y(0.0)
            out.append(f'<rect x="{x + 4:.1f}" y="{min(y1, y0):.1f}" width="{bw - 8:.1f}" height="{abs(y0 - y1):.1f}" fill="{colors[c]}"/>')
            cx = x + bw / 2
            out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(st["lo"]):.1f}" y2="{y(st["hi"]):.1f}" stroke="#333" stroke-width="1.5"/>')
            for yy in (y(st["lo"]), y(st["hi"])):
                out.append(f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#333" stroke-width="1.5"/>')
            out.append(f'<text x="{cx:.1f}" y="{y(st["hi"]) - 8:.1f}" font-size="13" font-weight="700" text-anchor="middle" fill="#333">{fmt(st["mean"], e)}</text>')
        ns = [stats[(c, m)]["n"] for c in conds if stats[(c, m)]]
        out.append(f'<text x="{L0 + i * gw + gw / 2:.1f}" y="{B0 + 24}" font-size="14" font-weight="700" text-anchor="middle" fill="#222">{C.MODELS.get(m, m)}</text>')
        out.append(f'<text x="{L0 + i * gw + gw / 2:.1f}" y="{B0 + 42}" font-size="11" text-anchor="middle" fill="#777">n = {min(ns) if ns else 0} seeds</text>')
    for j, c in enumerate(conds):
        out.append(f'<rect x="{W - 130}" y="{T0 + 24 * j}" width="14" height="14" fill="{colors[c]}"/>')
        out.append(f'<text x="{W - 110}" y="{T0 + 12 + 24 * j}" font-size="13" fill="#333">{"with AMP (FULL)" if c == "FULL" else "plain (PLAIN)"}</text>')
    out.append(f'<text x="{W - 130}" y="{T0 + 24 * len(conds) + 14}" font-size="11" fill="#777">whiskers: 95% CI</text>')
    out.append("</svg>")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="runs.csv file(s) written by grade.py")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    data = load(a.runs)
    if not data:
        sys.exit("no graded runs found")
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8").write(summary(data))
    for e in ENDPOINTS:
        s = svg(data, e)
        if s:
            name = "fig_" + e.split()[0].lower() + ".svg"
            open(os.path.join(a.out, name), "w", encoding="utf-8").write(s)
    print(f"written: {a.out}/summary.md and figures")


if __name__ == "__main__":
    main()
