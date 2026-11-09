"""stats6.py - the statistics of the AMP v6 evaluation. Pure standard library, deterministic (seeded).

Design: every test seed is run under every condition (a BLOCK), so all comparisons are PAIRED on seeds. The
unit of resampling is the seed (cluster bootstrap), never the item, so item correlation inside a test cannot
inflate significance.

  paired_summary(x, y)   mean difference, 95% bootstrap CI, sign-flip permutation p (exact up to n=16, Monte
                         Carlo above), Cohen's d_z, Cliff's delta, wins/ties/losses
  gap_recovery(a, b, c)  R = (A - C) / (B - C) with a paired bootstrap CI over seeds; flags an unstable
                         denominator (when the B - C CI includes 0 the ratio is not interpretable)
  holm(ps)               Holm-Bonferroni adjusted p-values (family-wise error control)
  n_for_power(sd, delta) seeds needed for a two-sided paired test at alpha = .05 with 80% power
  brier(ps, ys)          calibration error of stated probabilities
"""
from __future__ import annotations

import itertools
import math
import random
from statistics import NormalDist

B_DEFAULT = 10000


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def percentile(sorted_xs, q):
    if not sorted_xs:
        return float("nan")
    pos = q * (len(sorted_xs) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def bootstrap_ci(stat, n, B=B_DEFAULT, seed=0, level=0.95):
    """Percentile CI of stat(idx) where idx is a resample (with replacement) of range(n)."""
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        v = stat(idx)
        if v is not None and not math.isnan(v):
            vals.append(v)
    vals.sort()
    a = (1 - level) / 2
    return percentile(vals, a), percentile(vals, 1 - a), len(vals) / B


def signflip_p(d, B=B_DEFAULT, seed=0):
    """Two-sided paired permutation (sign-flip) test of mean(d) = 0. Exact enumeration for n <= 16."""
    n = len(d)
    if n == 0:
        return float("nan")
    obs = abs(sum(d))
    if n <= 16:
        hits = sum(1 for signs in itertools.product((1, -1), repeat=n) if abs(sum(s * x for s, x in zip(signs, d))) >= obs - 1e-12)
        return hits / 2 ** n
    rng = random.Random(seed)
    hits = sum(1 for _ in range(B) if abs(sum(x if rng.random() < 0.5 else -x for x in d)) >= obs - 1e-12)
    return (hits + 1) / (B + 1)


def cliffs_delta(x, y):
    """P(X > Y) - P(X < Y) over all pairs: a robust effect size in [-1, 1] (|d| .11 small, .28 medium, .43 large)."""
    if not x or not y:
        return float("nan")
    gt = sum(1 for a in x for b in y if a > b)
    lt = sum(1 for a in x for b in y if a < b)
    return (gt - lt) / (len(x) * len(y))


def paired_summary(x, y, B=B_DEFAULT, seed=0):
    d = [a - b for a, b in zip(x, y)]
    n = len(d)
    out = {"n": n, "mean_x": mean(x), "mean_y": mean(y), "diff": mean(d)}
    if n == 0:
        return out
    lo, hi, _ = bootstrap_ci(lambda idx: mean([d[i] for i in idx]), n, B, seed)
    s = sd(d)
    out.update(ci=(lo, hi), p=signflip_p(d, B, seed), dz=(mean(d) / s if s and s > 0 else float("nan")),
               cliff=cliffs_delta(x, y), wins=sum(v > 0 for v in d), ties=sum(v == 0 for v in d), losses=sum(v < 0 for v in d),
               sd_diff=s)
    return out


def gap_recovery(a, b, c, B=B_DEFAULT, seed=0):
    """a = weak model + method, b = strong model plain, c = weak model plain, paired lists over the same seeds.
    R = 0: the method adds nothing; R = 1: the weak model reaches the strong one; R > 1: it passes it."""
    n = len(a)
    if n == 0:
        return {"n": 0}

    def R(idx):
        den = mean([b[i] - c[i] for i in idx])
        if abs(den) < 1e-12:
            return None
        return mean([a[i] - c[i] for i in idx]) / den
    point = R(list(range(n)))
    lo, hi, ok = bootstrap_ci(R, n, B, seed)
    den_lo, den_hi, _ = bootstrap_ci(lambda idx: mean([b[i] - c[i] for i in idx]), n, B, seed + 1)
    return {"n": n, "R": point, "ci": (lo, hi), "valid_share": ok, "gap": mean([x - y for x, y in zip(b, c)]),
            "gap_ci": (den_lo, den_hi), "gap_unstable": den_lo <= 0 <= den_hi}


def holm(ps):
    """Holm step-down adjusted p-values, returned in the input order."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        adj[i] = running
    return adj


def n_for_power(sd_diff, delta, alpha=0.05, power=0.80):
    """Seeds needed so a paired two-sided test detects a true mean difference delta (normal approximation + 2)."""
    if not delta or not sd_diff or math.isnan(sd_diff):
        return None
    z = NormalDist().inv_cdf
    return math.ceil(((z(1 - alpha / 2) + z(power)) * sd_diff / abs(delta)) ** 2) + 2


def brier(ps, ys):
    pairs = [(float(p), bool(y)) for p, y in zip(ps, ys) if p is not None]
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else float("nan")


def fmt_ci(ci, nd=3):
    return f"[{ci[0]:+.{nd}f}, {ci[1]:+.{nd}f}]"
