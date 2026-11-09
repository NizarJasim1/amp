"""compare_tracks.py - does Track B (API runner) measure the same thing as Track A (the app, by hand)?

    python compare_tracks.py app_runs.csv api_runs.csv [--metric exact]
For every cell, on seeds run in both tracks: mean(app) - mean(api) with a seed-bootstrap CI, and the gap recovery R
computed separately in each track. If the CIs of the per-cell differences include 0 and the two R values agree,
the API results can stand in for the app (and the paper says so with these numbers); if not, report both.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit", "grader"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import stats6 as S  # noqa: E402


def load(p, metric):
    by = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(p, encoding="utf-8")):
        by[r["cell"]][int(r["seed"])].append(float(r[metric]))
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app")
    ap.add_argument("api")
    ap.add_argument("--metric", default="exact")
    a = ap.parse_args()
    A, B = load(a.app, a.metric), load(a.api, a.metric)
    print("| cell | n | app | api | app − api [CI] | p |\n|---|---|---|---|---|---|")
    for cell in sorted(set(A) & set(B)):
        seeds = sorted(set(A[cell]) & set(B[cell]))
        if len(seeds) < 2:
            continue
        x, y = [S.mean(A[cell][s]) for s in seeds], [S.mean(B[cell][s]) for s in seeds]
        r = S.paired_summary(x, y)
        print(f"| {cell} | {r['n']} | {r['mean_x']:.3f} | {r['mean_y']:.3f} | {r['diff']:+.3f} {S.fmt_ci(r['ci'])} | {r['p']:.3f} |")
    for name, D in (("app", A), ("api", B)):
        seeds = sorted(set(D["FULL@48"]) & set(D["PLAIN@55"]) & set(D["PLAIN@48"]))
        if len(seeds) >= 3:
            g = S.gap_recovery(*([S.mean(D[c][s]) for s in seeds] for c in ("FULL@48", "PLAIN@55", "PLAIN@48")))
            print(f"R ({name}, n={g['n']}): {g['R']:+.2f} {S.fmt_ci(g['ci'], 2)}" if g.get("R") is not None else f"R ({name}): undefined")


if __name__ == "__main__":
    main()
