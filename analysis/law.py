"""law.py - from one recovery number to a recovery CURVE, and from accuracy to accuracy-per-cost.

For every (weak, strong) model pair run with FULL@weak, PLAIN@strong, PLAIN@weak on shared seeds:
  gap  = PLAIN@strong - PLAIN@weak            (how big the generation gap is on this benchmark)
  R    = (FULL@weak - PLAIN@weak) / gap       (share of the gap the scaffold recovers), seed-bootstrap CI
  cost = mean cost(FULL@weak) / mean cost(PLAIN@strong)   (needs prices in providers.json, Track B)
Then fits R = a + b * gap across pairs (weighted by 1/var(R), pair-level bootstrap for the slope) - the
question "does the scaffold recover a stable share, or less as gaps grow?" A curve needs >= 4 pairs; with fewer
the script reports the points and says the fit is not identified.

    python law.py runs.csv [more_runs.csv ...] --pairs 48:55,haiku:sonnet,os-small:os-large [--metric exact]
Writes LAW.md next to the first input.
"""
import argparse
import csv
import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit", "grader"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import stats6 as S  # noqa: E402


def load(paths, metric):
    by = defaultdict(lambda: defaultdict(list))
    cost = defaultdict(list)
    for p in paths:
        for r in csv.DictReader(open(p, encoding="utf-8")):
            by[r["cell"]][int(r["seed"])].append(float(r[metric]))
            if r.get("cost"):
                cost[r["cell"]].append(float(r["cost"]))
    return by, cost


def wls(xs, ys, ws):
    sw = sum(ws)
    mx, my = sum(w * x for w, x in zip(ws, xs)) / sw, sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    if sxx <= 0:
        return None, None
    b = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys)) / sxx
    return my - b * mx, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--metric", default="exact")
    a = ap.parse_args()
    by, cost = load(a.runs, a.metric)
    rows = []
    L = ["# Recovery curve and cost\n", f"metric: `{a.metric}`; R = share of the weak→strong gap recovered by FULL@weak\n",
         "| pair | n | gap [CI] | R [CI] | cost FULL@weak / PLAIN@strong |", "|---|---|---|---|---|"]
    for pr in a.pairs.split(","):
        weak, strong = pr.split(":")
        A, B, C = by[f"FULL@{weak}"], by[f"PLAIN@{strong}"], by[f"PLAIN@{weak}"]
        seeds = sorted(set(A) & set(B) & set(C))
        if len(seeds) < 3:
            L.append(f"| {weak}→{strong} | {len(seeds)} | – | – | not enough shared seeds |")
            continue
        x, y, z = ([S.mean(D[s]) for s in seeds] for D in (A, B, C))
        g = S.gap_recovery(x, y, z)
        cr = (S.mean(cost[f"FULL@{weak}"]) / S.mean(cost[f"PLAIN@{strong}"])) if cost[f"FULL@{weak}"] and cost[f"PLAIN@{strong}"] else None
        L.append(f"| {weak}→{strong} | {g['n']} | {g['gap']:+.3f} {S.fmt_ci(g['gap_ci'])} | "
                 + (f"{g['R']:+.2f} {S.fmt_ci(g['ci'], 2)}" if g.get("R") is not None else "–")
                 + f" | {cr:.2f}× |" if cr else " | – |")
        if g.get("R") is not None and not g["gap_unstable"] and not math.isnan(g["ci"][0]):
            var = ((g["ci"][1] - g["ci"][0]) / 3.92) ** 2 or 1e-6
            rows.append((g["gap"], g["R"], 1 / var, cr))
    L.append("")
    if len(rows) >= 4:
        a0, b = wls([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
        rng, bs = random.Random(0), []
        for _ in range(5000):
            smp = [rows[rng.randrange(len(rows))] for _ in rows]
            fit = wls([r[0] for r in smp], [r[1] for r in smp], [r[2] for r in smp])
            if fit[1] is not None:
                bs.append(fit[1])
        bs.sort()
        lo, hi = S.percentile(bs, 0.025), S.percentile(bs, 0.975)
        L.append(f"Fit: R = {a0:.2f} {b:+.2f} × gap  (slope 95% CI [{lo:+.2f}, {hi:+.2f}], {len(rows)} pairs).")
        L.append("Reading: slope CI containing 0 → the scaffold recovers a roughly constant share of the gap; "
                 "negative slope → it recovers less of bigger gaps (weights matter more as gaps grow).")
    else:
        L.append(f"Curve not identified: {len(rows)} usable pair(s); need ≥ 4. The table above is the honest result.")
    if any(r[3] for r in rows):
        L.append("\nHeadline form: \"recovers R% of the gap at C× the stronger model's cost\" (one line per pair above).")
    out = os.path.join(os.path.dirname(os.path.abspath(a.runs[0])), "LAW.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
