"""grade.py - grades every run of the AMP v6 study and writes the analysis. NEVER attach it, KEYS.json or
arena5.py to a test chat.

    python grade.py [folder ...]      (default: the folder this file is in, then /mnt/user-data/uploads)

The folder must hold: KEYS.json, plan.csv, stats6.py, arena5.py, and one answer file per finished run:
R007.json (the merged final JSON blocks of PART1-4) and R007_p5.json (the PART5.json the model saved).
Missing runs are simply skipped; every analysis uses the seeds that are complete for the cells it compares.

Writes REPORT.md, runs.csv and amp_feedback_<model>.json (one per model, from its FULL runs only) to:
<first folder>/results/ when folders are given, else /mnt/user-data/outputs/ (the app), else ./results/.

v6.7: when folders are given, runs are read ONLY from them (loose files and the .zip files in them); nothing is
mixed in from /mnt/user-data/uploads. Support files (KEYS.json, plan.csv, arena5.py, amp_lab.py, tests/) are also
looked up in this file's folder, the parents, and their sealed/ grader/ protocols/ subfolders, so with the kit:
    python kit/grader/grade.py runs_api kit        (Track B)
    python grade.py                                (Track A in the app: attach grader/, KEYS.json, plan.csv,
                                                    runs.zip, and for checking certificates tests.zip + amp_lab.py)
"""
from __future__ import annotations

import csv
import glob
import itertools
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
for d in (HERE, "/mnt/user-data/uploads"):
    if d not in sys.path:
        sys.path.insert(0, d)
import stats6 as S  # noqa: E402

KIND = {"Q": "I", "G": "G", "K": "P", "T": "P", "C": "C", "I": "J"}
EXACT = [f"Q{i}" for i in range(1, 7)] + [f"G{i}" for i in range(1, 5)] + ["K1", "T1"]
FAMILY = {"insight Q": [f"Q{i}" for i in range(1, 7)], "induction G": [f"G{i}" for i in range(1, 5)], "precision P": ["K1", "T1"]}
IDEAS = ["I1", "I2", "I3", "I4"]


# ============================================================================ scoring one run
def norm_num(v):
    return str(v).strip().replace(",", "").replace(" ", "").strip('"')


def same(k, got, want):
    if got is None:
        return False
    if k.startswith("Q"):
        return norm_num(got) == norm_num(want)
    if k.startswith("G"):
        try:
            return [[str(r) for r in g] for g in got] == want
        except TypeError:
            return False
    return isinstance(got, str) and got.rstrip("\n") == want.rstrip("\n")


def circles(sol, n, tol=1e-9):
    try:
        cs = [(float(x), float(y), float(r)) for x, y, r in sol]
    except Exception:
        return None
    if len(cs) != n or any(not (r > 0 and x - r >= -tol and x + r <= 1 + tol and y - r >= -tol and y + r <= 1 + tol) for x, y, r in cs):
        return None
    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1]) < cs[i][2] + cs[j][2] - tol:
                return None
    return sum(r for _, _, r in cs)


def capset(sol, n):
    try:
        vs = [tuple(int(v) for v in vec) for vec in sol]
    except Exception:
        return None
    if not vs or any(len(v) != n or any(e not in (0, 1, 2) for e in v) for v in vs) or len(set(vs)) != len(vs):
        return None
    s = set(vs)
    for i, a in enumerate(vs):
        for b in vs[i + 1:]:
            if tuple((-x - y) % 3 for x, y in zip(a, b)) in s:
                return None
    return len(vs)


def golomb(sol, n):
    try:
        xs = sorted(int(v) for v in sol)
    except Exception:
        return None
    if len(xs) != n or len(set(xs)) != n or xs[0] < 0:
        return None
    d = [b - a for i, a in enumerate(xs) for b in xs[i + 1:]]
    return xs[-1] - xs[0] if len(set(d)) == len(d) else None


def rectfree(sol, n):
    try:
        rows = [str(r) for r in sol]
    except Exception:
        return None
    if len(rows) != n or any(len(r) != n or set(r) - {"0", "1"} for r in rows):
        return None
    sets = [{j for j, ch in enumerate(r) if ch == "1"} for r in rows]
    if any(len(a & b) >= 2 for a, b in itertools.combinations(sets, 2)):
        return None
    return sum(len(s) for s in sets)


SCORERS = {"C1": (circles, "max"), "C2": (capset, "max"), "C3": (golomb, "min"), "C4": (rectfree, "max")}

RUNNER = r'''
import json, sys, random
sys.path.insert(0, sys.argv[1])
import arena5 as A
req = json.loads(sys.stdin.read()); ns = {}
exec(req["src"], ns)
t, seeds = req["task"], req["seeds"]
if t == "I1":
    v = [A.i1_run(ns["place"], A.i1_sequence(random.Random(s))) for s in seeds]
    b = [A.i1_run(A.i1_baseline, A.i1_sequence(random.Random(s))) for s in seeds]
elif t == "I2":
    v = [A.i2_run(ns["Predictor"], A.i2_sequence(random.Random(s))) for s in seeds]
    b = [A.i2_run(A.I2Baseline, A.i2_sequence(random.Random(s))) for s in seeds]
elif t == "I3":
    v, b = [], []
    for s in seeds:
        jobs = A.i3_instance(random.Random(s)); base = A.i3_cost(jobs, A.i3_baseline(jobs))
        try: c = A.i3_cost(jobs, list(ns["schedule"]([tuple(j) for j in jobs])))
        except Exception: c = None
        v.append((c if c is not None else 10 * base) / max(base, 1)); b.append(1.0)
else:
    v = [A.i4_run(ns["Player"], seed=s) for s in seeds]
    b = [A.i4_run(A.I4Baseline, seed=s) for s in seeds]
print(json.dumps({"score": sum(v) / len(v), "baseline": sum(b) / len(b)}))
'''


def run_idea(task, code, seeds, arena_dir, timeout=600):
    if not isinstance(code, str) or not code.strip():
        return None
    try:
        out = subprocess.run([sys.executable, "-c", RUNNER, arena_dir], input=json.dumps({"task": task, "src": code, "seeds": seeds}),
                             capture_output=True, text=True, timeout=timeout)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def idea_gain(task, res):
    """Improvement over the simple baseline on the hidden instances, oriented so that HIGHER is better and 0 = baseline.
    A missing or crashing solution scores 0 (= no better than the baseline)."""
    if not res:
        return 0.0
    s, b = res["score"], res["baseline"]
    if task == "I1":
        return b / s - 1
    if task == "I2":
        return (b - s) / b
    if task == "I3":
        return 1 - s
    return s - b


def grade_run(ans, key, arena_dir, run_ideas=True, attest=None):
    g = {"items": {k: same(k, ans.get(k), key[k]) for k in EXACT}}
    conf = ans.get("_conf") or {}
    ledger = ans.get("_ledger") or {}
    g["conf"] = {}
    for k in EXACT:
        p = conf.get(k, (ledger.get(k) or {}).get("p"))
        try:
            g["conf"][k] = min(1.0, max(0.0, float(p)))
        except (TypeError, ValueError):
            g["conf"][k] = None
    g["E"] = {k: (ledger.get(k) or {}).get("E") for k in EXACT}
    g["pairs"] = {k: (ledger.get(k) or {}).get("pairs") or [] for k in EXACT}
    g["oracle"] = {k: bool((ledger.get(k) or {}).get("oracle")) for k in EXACT}
    # v6.6: the ledger's oracle / E3 is the model's own claim. When the run's certificate was re-checked against the
    # real problem files and the runner's signed #LIVE log (attest), a claim that was not proven loses its oracle flag
    # and is capped at E2.
    # v6.7: a claim that could NOT be checked (no certificate, or nothing to check it against) is treated the same
    # way, so declared words never count as oracle-backed (README: "declared words do not reach E3"). It is listed
    # separately (prov_unchecked) so the report can tell "refuted" from "not checkable".
    g["prov"], g["prov_refuted"], g["prov_unchecked"] = ("checked" if attest is not None else "unchecked"), [], []
    proven = (set(attest.get("proven") or []) if attest.get("intact") else set()) if attest is not None else set()
    for k in EXACT:
        if g["oracle"][k] and k not in proven:
            g["oracle"][k] = False
            (g["prov_refuted"] if attest is not None else g["prov_unchecked"]).append(k)
            try:
                g["E"][k] = min(2, int(g["E"][k]))
            except (TypeError, ValueError):
                pass
    ob = [g["items"][k] for k in EXACT if g["oracle"][k]]
    nob = [g["items"][k] for k in EXACT if not g["oracle"][k]]
    g["oracle_rate"] = sum(g["oracle"].values()) / len(EXACT)
    g["acc_oracle"] = (sum(ob) / len(ob)) if ob else None          # accuracy on items the model backed with an external oracle
    g["acc_nonoracle"] = (sum(nob) / len(nob)) if nob else None
    for fam, ks in FAMILY.items():
        g[fam] = sum(g["items"][k] for k in ks) / len(ks)
    g["exact"] = sum(g["items"].values()) / len(EXACT)
    spec, ref = key["C_spec"], key["C_ref"]
    cs = []
    for c, (f, best) in SCORERS.items():
        v = f(ans[c], spec[c]) if c in ans else None
        g[c] = v
        cs.append(0.0 if v is None else (v / ref[c] if best == "max" else ref[c] / v))
    g["creative"] = sum(cs) / len(cs)
    gains, g["gain"] = [], {}
    for t in IDEAS:
        res = run_idea(t, ans.get(t), key["I_seeds"][t], arena_dir) if run_ideas else None
        g[t] = res["score"] if res else None
        gains.append(idea_gain(t, res))
        g["gain"][t] = gains[-1] if (res or (isinstance(ans.get(t), str) and ans[t].strip())) else None   # crash = failed
    g["shipped"] = {t: s for t, s in (ans.get("_shipped") or {}).items() if t in IDEAS and isinstance(s, str)}
    g["ideas"] = sum(gains) / len(gains)
    g["brier"] = S.brier([g["conf"][k] for k in EXACT], [g["items"][k] for k in EXACT])
    g["silent"] = sum(1 for k in EXACT if (g["conf"][k] or 0) >= 0.9 and not g["items"][k]) / len(EXACT)
    return g


# ============================================================================ analysis
ENDPOINTS = ["exact", "insight Q", "induction G", "precision P", "creative", "ideas"]
SAFETY = ["silent", "brier"]   # silent = share of items answered wrong with stated p >= .9 (overconfident errors)


def cell_vectors(graded, plan, cell_a, cell_b, metric):
    """Paired vectors over seeds where both cells have a graded run (mean over replicate runs of a seed)."""
    by = defaultdict(lambda: defaultdict(list))
    for rid, g in graded.items():
        r = plan[rid]
        by[r["cell"]][r["seed"]].append(g[metric])
    seeds = sorted(set(by[cell_a]) & set(by[cell_b]))
    return [S.mean(by[cell_a][s]) for s in seeds], [S.mean(by[cell_b][s]) for s in seeds], seeds


def triple_vectors(graded, plan, a, b, c, metric):
    by = defaultdict(lambda: defaultdict(list))
    for rid, g in graded.items():
        by[plan[rid]["cell"]][plan[rid]["seed"]].append(g[metric])
    seeds = sorted(set(by[a]) & set(by[b]) & set(by[c]))
    return [S.mean(by[a][s]) for s in seeds], [S.mean(by[b][s]) for s in seeds], [S.mean(by[c][s]) for s in seeds]


def compare_block(lines, graded, plan, pairs, title, metric="exact"):
    lines += [f"\n### {title}  (metric: {metric}; paired over seeds; Holm-adjusted within this table)\n",
              "| comparison | n seeds | mean A | mean B | A − B [95% CI] | p | p (Holm) | d_z | Cliff δ | W/T/L |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for a, b in pairs:
        x, y, _ = cell_vectors(graded, plan, a, b, metric)
        if len(x) >= 2:
            rows.append((a, b, S.paired_summary(x, y)))
    adj = S.holm([r[2]["p"] for r in rows]) if rows else []
    for (a, b, r), pa in zip(rows, adj):
        lines.append(f"| {a} vs {b} | {r['n']} | {r['mean_x']:.3f} | {r['mean_y']:.3f} | {r['diff']:+.3f} {S.fmt_ci(r['ci'])} | "
                     f"{r['p']:.4f} | {pa:.4f} | {r['dz']:+.2f} | {r['cliff']:+.2f} | {r['wins']}/{r['ties']}/{r['losses']} |")
    if not rows:
        lines.append("| (not enough paired seeds yet) | | | | | | | | | |")
    return rows


def analyse(graded, plan, out_dir, warnings=()):
    L = ["# AMP v6 — results\n", f"Graded runs: {len(graded)}. Cells are CONDITION@MODEL (48 = Opus 4.8, 55 = Opus 5.5).\n"]
    if warnings:
        L += ["**Grader warnings (read before the numbers):**\n"] + [f"- {w}" for w in warnings] + [""]
    cells = defaultdict(list)
    for rid, g in graded.items():
        cells[plan[rid]["cell"]].append(g)
    L += ["## Cell means\n", "| cell | runs | " + " | ".join(ENDPOINTS) + " | Brier | silent errors |", "|---|---|" + "---|" * (len(ENDPOINTS) + 2)]
    for cell in sorted(cells):
        gs = cells[cell]
        L.append(f"| {cell} | {len(gs)} | " + " | ".join(f"{S.mean([g[m] for g in gs]):.3f}" for m in ENDPOINTS)
                 + f" | {S.mean([g['brier'] for g in gs if not math.isnan(g['brier'])]):.3f} | {S.mean([g['silent'] for g in gs]):.3f} |")

    # ---- primary claim: gap recovery
    L.append("\n## Primary claim: share of the 4.8 → 5.5 gap recovered by AMP\n")
    L.append("R = (FULL@48 − PLAIN@48) / (PLAIN@55 − PLAIN@48), paired cluster bootstrap over seeds. R = 1 means 4.8 + AMP equals 5.5.\n")
    L += ["| endpoint | n | gap 5.5 − 4.8 [CI] | R [95% CI] | reading |", "|---|---|---|---|---|"]
    primary = {}
    for m in ENDPOINTS:
        a, b, c = triple_vectors(graded, plan, "FULL@48", "PLAIN@55", "PLAIN@48", m)
        if len(a) < 2:
            L.append(f"| {m} | {len(a)} | – | – | not enough seeds |")
            continue
        r = S.gap_recovery(a, b, c)
        if r["R"] is None or math.isnan(r["ci"][0]):
            L.append(f"| {m} | {r['n']} | {r['gap']:+.3f} | – | no gap between the plain models on these seeds |")
            continue
        primary[m] = r
        reading = ("gap not established (5.5 not reliably better here): R not interpretable" if r["gap_unstable"] else
                   "AMP passes 5.5" if r["ci"][0] > 1 else "reaches 5.5 (CI includes 1)" if r["ci"][0] <= 1 <= r["ci"][1] else
                   "partial recovery" if r["ci"][0] > 0 else "no reliable recovery")
        L.append(f"| {m} | {r['n']} | {r['gap']:+.3f} {S.fmt_ci(r['gap_ci'])} | {r['R']:+.2f} {S.fmt_ci(r['ci'], 2)} | {reading} |")

    compare_block(L, graded, plan, [("FULL@48", "PLAIN@55"), ("FULL@48", "PLAIN@48"), ("FULL@55", "PLAIN@55")], "Direct comparisons")
    for m in ("creative", "ideas"):
        compare_block(L, graded, plan, [("FULL@48", "PLAIN@55"), ("FULL@48", "PLAIN@48")], "Direct comparisons", metric=m)

    abl = [("FULL@48", f"no{x}@48") for x in ("ORACLE", "LAB", "INS", "BLIND", "ATT", "EV", "DATA", "OUT", "MEM", "IDEA")]
    L.append("\n## Ablations: what each component contributes (FULL − variant; positive = the component helps; for `silent`, NEGATIVE = helps)")
    for m in ("exact", "creative", "ideas", "silent"):
        compare_block(L, graded, plan, abl, "Ablation", metric=m)
    base = [("FULL@48", f"{b}@48") for b in ("TOOLS", "SC5", "BON5", "CONF")]
    L.append("\n## Baselines at equal model (is it the method, or just tools / sampling / verification?)")
    for m in ("exact", "creative", "ideas", "silent"):
        compare_block(L, graded, plan, base, "Baselines", metric=m)

    # ---- oracle gating: superiority is claimed only where an external oracle decides correctness
    L.append("\n## Oracle gating (the governing check)\n")
    L.append("A scaffold that only organises thinking lifts the stronger model too, so it cannot explain the weaker "
             "model passing it. Real superiority should appear only where the model backed its answer with an EXTERNAL "
             "oracle (held-out verification, a validator, brute force). Two tests of this:\n")
    L += ["**(a) Within FULL@48, accuracy on oracle-backed vs non-oracle-backed items.**",
          "| cell | oracle-backed rate | acc oracle-backed | acc non-oracle | gap |", "|---|---|---|---|---|"]
    for cell in sorted(cells):
        gs = cells[cell]
        rate = S.mean([g["oracle_rate"] for g in gs])
        ob = [g["acc_oracle"] for g in gs if g["acc_oracle"] is not None]
        no = [g["acc_nonoracle"] for g in gs if g["acc_nonoracle"] is not None]
        gap = (S.mean(ob) - S.mean(no)) if ob and no else float("nan")
        L.append(f"| {cell} | {rate:.2f} | {('%.3f' % S.mean(ob)) if ob else '–'} | {('%.3f' % S.mean(no)) if no else '–'} | "
                 + (f"{gap:+.3f}" if not math.isnan(gap) else "–") + " |")
    L.append("\n**(b) Does FULL@48 beat the stronger model only where it used the oracle?** FULL@48 − PLAIN@55 on the "
             "subset of seeds × items that FULL backed with an oracle, vs the rest.")
    sub = {"oracle-backed items": [], "other items": []}
    byseed = defaultdict(lambda: defaultdict(dict))
    for rid, g in graded.items():
        byseed[plan[rid]["cell"]][plan[rid]["seed"]] = g
    for s in sorted(set(byseed.get("FULL@48", {})) & set(byseed.get("PLAIN@55", {}))):
        fa, fb = byseed["FULL@48"][s], byseed["PLAIN@55"][s]
        for k in EXACT:
            bucket = "oracle-backed items" if fa["oracle"][k] else "other items"
            sub[bucket].append(fa["items"][k] - fb["items"][k])
    L += ["\n| subset | n items | FULL@48 − PLAIN@55 (mean) |", "|---|---|---|"]
    for name, d in sub.items():
        L.append(f"| {name} | {len(d)} | {S.mean(d):+.3f} |" if d else f"| {name} | 0 | – |")
    L.append("\nReading: if FULL only pulls ahead of the stronger model on oracle-backed items, that is the predicted "
             "and honest result — the scaffold's edge is the external oracle, not the model. Claiming superiority on "
             "oracle-poor items would not be credible and is not claimed.")

    # ---- provenance: which oracle claims were actually checked
    L.append("\n## Provenance of oracle claims\n")
    L.append("An oracle claim counts only if it was proven after the run (Track B: the runner's attestation; Track A: "
             "the certificate re-checked against the kit's problem files). Refuted or uncheckable claims are capped at E2 "
             "and do not count as oracle-backed above.\n")
    L += ["| cell | runs | runs checked | claims proven | claims refuted | claims not checkable |", "|---|---|---|---|---|---|"]
    for cell in sorted(cells):
        gs = cells[cell]
        L.append(f"| {cell} | {len(gs)} | {sum(g['prov'] == 'checked' for g in gs)} | {sum(sum(g['oracle'].values()) for g in gs)} | "
                 f"{sum(len(g['prov_refuted']) for g in gs)} | {sum(len(g['prov_unchecked']) for g in gs)} |")

    # ---- calibration and evidence levels
    L.append("\n## Calibration and evidence levels\n")
    L += ["| cell | items with a stated p | Brier (lower = better) | accuracy when p ≥ .9 |", "|---|---|---|---|"]
    for cell in sorted(cells):
        ps = [(g["conf"][k], g["items"][k]) for g in cells[cell] for k in EXACT if g["conf"][k] is not None]
        hi = [y for p, y in ps if p >= 0.9]
        L.append(f"| {cell} | {len(ps)} | {S.brier([p for p, _ in ps], [y for _, y in ps]):.3f} | "
                 + (f"{sum(hi) / len(hi):.3f} (n={len(hi)})" if hi else "–") + " |")
    byE = defaultdict(list)
    for g in graded.values():
        for k in EXACT:
            if g["E"][k] is not None:
                byE[(KIND[k[0]], int(g["E"][k]))].append(g["items"][k])
    if byE:
        L += ["\nAccuracy by stated evidence level (AMP runs). The E-level is a valid signal only if accuracy rises with E.\n",
              "| kind | " + " | ".join(f"E{e}" for e in range(5)) + " |", "|---|" + "---|" * 5]
        for kind in sorted({k for k, _ in byE}):
            L.append(f"| {kind} | " + " | ".join(f"{sum(byE[(kind, e)]) / len(byE[(kind, e)]):.2f} (n={len(byE[(kind, e)])})"
                                                 if byE[(kind, e)] else "–" for e in range(5)) + " |")

    # ---- power
    L.append("\n## Power: seeds needed (paired, two-sided α = .05, 80% power)\n")
    L += ["| comparison | sd of paired diff | observed diff | seeds needed for observed | for 1 item (0.083) |", "|---|---|---|---|---|"]
    for a, b in [("FULL@48", "PLAIN@55"), ("FULL@48", "PLAIN@48")] + abl:
        x, y, _ = cell_vectors(graded, plan, a, b, "exact")
        if len(x) >= 3:
            d = [p - q for p, q in zip(x, y)]
            L.append(f"| {a} vs {b} | {S.sd(d):.3f} | {S.mean(d):+.3f} | {S.n_for_power(S.sd(d), S.mean(d))} | {S.n_for_power(S.sd(d), 1 / 12)} |")

    # ---- the one-sentence claim, filled from the data
    if "exact" in primary:
        r = primary["exact"]
        neg = [m for m in ("insight Q", "induction G", "precision P", "creative", "ideas") if m in primary and primary[m]["ci"][0] <= 0]
        L.append("\n## Claim (auto-filled; edit only the wording)\n")
        obr = S.mean([g["oracle_rate"] for g in cells.get("FULL@48", [])]) if cells.get("FULL@48") else float("nan")
        L.append(f"> On {r['n']} freshly generated, contamination-free test instances whose answers are checked by an "
                 f"external oracle (held-out verification, validators, brute force), Opus 4.8 with AMP v6 recovered "
                 f"{100 * r['R']:.0f}% (95% CI {100 * r['ci'][0]:.0f}% to {100 * r['ci'][1]:.0f}%) of the exact-answer gap to "
                 f"Opus 5.5" + (f", backing {100 * obr:.0f}% of items with an oracle" if not math.isnan(obr) else "") + "."
                 + (f" No reliable recovery on: {', '.join(neg)}." if neg else "")
                 + " The claim is scoped to oracle-rich tasks; on tasks with no external check the scaffold is not claimed to beat the stronger model. "
                 "Scope: superiority is over the PLAIN stronger model; with the same oracle the stronger model is expected to stay ahead (see FULL@55).")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    return "\n".join(L)


# ============================================================================ main: collecting the inputs
# v6.7: ONE reader for loose files and for zip members, so a run's _meta / _attest / _cert / _evidence files are
# classified the same way wherever they come from (before, inside runs.zip they were merged into the answers and the
# attestation, track and cost were lost). An explicit folder is the only place runs are read from: nothing is mixed
# in from /mnt/user-data/uploads or a recursive /mnt search.
RUN_FILE = re.compile(r"^(R\d+)(?=[_ .(]|$)")
RUN_TAGS = ("_meta", "_cert", "_memory", "_attest", "_evidence")   # anything else named R<n>*.json is answers (R007.json, R007_p5.json)
TEST_FILE = re.compile(r"(?:^|/)tests/T(\d+)/(PART\d+)\.txt$")
SUPPORT_SUBDIRS = ("", "sealed", "grader", "protocols")


def _read(path):
    with open(path, "rb") as f:
        return f.read()


class Inputs:
    """Everything the grader reads, from folders and from the .zip files in them."""

    def __init__(self, folders):
        self.explicit = bool(folders)
        self.run_dirs = [os.path.abspath(f) for f in folders] if folders else \
            [d for d in dict.fromkeys([HERE, "/mnt/user-data/uploads"]) if os.path.isdir(d)]
        roots = self.run_dirs + [HERE] + [os.path.dirname(d) for d in self.run_dirs + [HERE]]
        self.support_roots = list(dict.fromkeys(os.path.abspath(r) for r in roots))
        self.files = []                                    # (display origin, name inside, reader, is a zip member)
        self._zips = []
        self.warnings = []
        for d in self.run_dirs:
            # canonical names first: "R007.json" is used before a browser's duplicate "R007 (1).json"
            for p in sorted(glob.glob(os.path.join(d, "*")), key=lambda q: (" (" in os.path.basename(q), q)):
                if os.path.isfile(p) and p.lower().endswith(".zip"):
                    self._add_zip(p)
                elif os.path.isfile(p):
                    self.files.append((p, os.path.basename(p), (lambda q=p: _read(q)), False))

    def _add_zip(self, zp):
        import zipfile
        try:
            z = zipfile.ZipFile(zp)
        except zipfile.BadZipFile:
            self.warnings.append(f"{zp}: not a readable zip, skipped")
            return
        self._zips.append(z)
        for name in sorted(z.namelist(), key=lambda n: (" (" in os.path.basename(n), n)):
            if not name.endswith("/") and "__MACOSX" not in name:
                self.files.append((f"{zp}:{name}", name, (lambda z=z, n=name: z.read(n)), True))

    # ---- support files: KEYS.json, plan.csv, arena5.py, amp_lab.py, tests/T<n>/PART<k>.txt
    def support(self, name, prefer=None):
        """Bytes of a support file: loose (in a run folder, the grader's folder, their parents, or their sealed/,
        grader/, protocols/ subfolders), else a zip member with that base name. `prefer` ranks candidates."""
        cands = []
        for r in self.support_roots:
            for sub in SUPPORT_SUBDIRS:
                p = os.path.join(r, sub, name)
                if os.path.isfile(p):
                    cands.append((p, _read(p)))
        cands += [(o, rd()) for o, n, rd, z in self.files if z and os.path.basename(n) == name]
        if not cands:
            return None, None
        if prefer:
            cands.sort(key=lambda c: -prefer(c[1]))
        return cands[0]

    def tests(self):
        """{seed: {'PART1': text, ...}} from tests/ folders under the support roots and from zip members."""
        out = defaultdict(dict)
        for r in self.support_roots:
            for p in sorted(glob.glob(os.path.join(r, "tests", "T*", "PART*.txt"))):
                m = TEST_FILE.search(p.replace(os.sep, "/"))
                if m:
                    out[int(m.group(1))].setdefault(m.group(2), open(p, encoding="utf-8").read())
        for o, n, rd, z in self.files:
            m = TEST_FILE.search(n)
            if m:
                out[int(m.group(1))].setdefault(m.group(2), rd().decode("utf-8"))
        return out

    # ---- run files
    def runs(self, plan):
        """{rid: {'answers': {...}, 'meta': ..., 'attest': ..., 'cert': ...}}; conflicting copies are reported."""
        runs = defaultdict(lambda: {"answers": {}, "meta": None, "attest": None, "cert": None})
        seen = {}
        # loose files before zip members, and a canonical name before a browser's duplicate ("R007 (1).json")
        order = sorted(self.files, key=lambda f: (f[3], " (" in os.path.basename(f[1]), f[0]))
        for origin, name, rd, _ in order:
            base = os.path.basename(name)
            m = RUN_FILE.match(base)
            if not m or not base.endswith(".json") or m.group(1) not in plan:
                continue
            rid = m.group(1)
            tag = next((t for t in RUN_TAGS if t in base), "")
            data = rd()
            ident = (rid, tag, base.split(".")[0].split(" ")[0])
            if ident in seen:
                if seen[ident][1] != data:
                    self.warnings.append(f"{rid}: two different copies ({seen[ident][0]} and {origin}); "
                                         f"the first was used - check which one is right")
                continue
            seen[ident] = (origin, data)
            try:
                obj = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self.warnings.append(f"{origin}: unreadable JSON ({e}); skipped")
                continue
            r = runs[rid]
            if tag == "_meta":
                r["meta"] = obj
            elif tag == "_attest":
                r["attest"] = (obj or {}).get("registry")
            elif tag == "_cert":
                r["cert"] = obj
            elif tag in ("_memory", "_evidence"):
                continue
            elif isinstance(obj, dict):
                r["answers"].update(obj)
        return runs

    def close(self):
        for z in self._zips:
            z.close()


def _manifest_size(src):
    """Rank amp_lab.py copies: the kit copy carries the problem files' sha256 manifest, src/ has an empty one."""
    m = re.search(rb"KIT_GIVEN_SHA256 = frozenset\(\{([^}]*)\}\)", src or b"")
    return len(m.group(1)) if m else 0


def track_a_attest(lab_src, cert, parts):
    """Track A: no runner, so only 'given' can be proven, by re-checking the certificate against the kit's own
    problem files (sha256 + pairs literally in the text). live / validator claims stay unproven there."""
    if not lab_src or not parts:
        return None
    import importlib.util
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "amp_lab_attest.py")
        open(p, "wb").write(lab_src)
        spec = importlib.util.spec_from_file_location("amp_lab_attest", p)
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
    if not hasattr(lab, "attest_certificate"):
        return None
    return lab.attest_certificate(cert, [parts[k] for k in sorted(parts)])


def load_plan(text):
    plan = {}
    for row in csv.DictReader(text.splitlines()):
        row["seed"] = int(row["seed"])
        row["cell"] = f"{row['condition']}@{row['model']}"
        plan[row["run_id"]] = row
    return plan


def arena_dir_for(inp):
    """arena5.py must be a real file (the idea runner imports it in a subprocess)."""
    for r in [HERE] + inp.support_roots:
        for sub in SUPPORT_SUBDIRS:
            if os.path.isfile(os.path.join(r, sub, "arena5.py")):
                return os.path.join(r, sub)
    _, data = inp.support("arena5.py")
    if data is None:
        return None
    import tempfile
    d = tempfile.mkdtemp(prefix="amp_arena_")
    open(os.path.join(d, "arena5.py"), "wb").write(data)
    return d


def output_dir(inp):
    if inp.explicit:
        d = inp.run_dirs[0]
        if os.access(d, os.W_OK):
            return os.path.join(d, "results")
    if os.path.isdir("/mnt/user-data/outputs"):
        return "/mnt/user-data/outputs"
    return os.path.join(HERE if os.access(HERE, os.W_OK) else os.getcwd(), "results")


def feedback(graded, plan):
    """One feedback file per model, from that model's FULL runs only (PREREG section 6): a FULL@48 chain learns from
    FULL@48 outcomes, never from FULL@55 or from another condition. Unproven oracle claims are already capped."""
    out = defaultdict(lambda: {"runs": [], "outcomes": []})
    for rid, g in graded.items():
        if plan[rid]["condition"] != "FULL":
            continue
        fb = out[plan[rid]["model"]]
        fb["runs"].append({"run": rid, "items": [{"kind": KIND[k[0]], "E": g["E"][k], "ok": g["items"][k], "pairs": g["pairs"][k]}
                                                 for k in EXACT if g["E"][k] is not None]})
        # official verdicts on ideas the model shipped (Outcomes ledger): held = beat the baseline on hidden instances
        fb["outcomes"] += [{"run": rid, "task": t, "sid": sid, "held": (g["gain"].get(t) or 0) > 0, "gain": g["gain"].get(t)}
                           for t, sid in g.get("shipped", {}).items() if g["gain"].get(t) is not None]
    return out


def main(argv=None):
    folders = list(sys.argv[1:] if argv is None else argv)
    inp = Inputs(folders)
    where = ", ".join(inp.run_dirs) or "(nothing)"
    _, keys_b = inp.support("KEYS.json")
    _, plan_b = inp.support("plan.csv")
    arena_dir = arena_dir_for(inp)
    missing = [n for n, v in (("KEYS.json", keys_b), ("plan.csv", plan_b), ("arena5.py", arena_dir)) if v is None]
    if missing:
        sys.exit(f"grade.py: cannot find {', '.join(missing)} (searched {', '.join(inp.support_roots)} and the zips in "
                 f"{where}). Track B: python grade.py runs_api ../kit")
    keys = json.loads(keys_b.decode("utf-8"))
    plan = load_plan(plan_b.decode("utf-8"))
    runs = inp.runs(plan)
    lab_origin, lab_src = inp.support("amp_lab.py", prefer=_manifest_size)
    tests = inp.tests() if any(r["cert"] and not r["attest"] for r in runs.values()) else {}
    graded, metas, no_check = {}, {}, []
    for rid in sorted(runs):
        r = runs[rid]
        if not r["answers"]:
            inp.warnings.append(f"{rid}: only side files ({', '.join(k for k in ('meta', 'attest', 'cert') if r[k])}), no answers; skipped")
            continue
        seed = plan[rid]["seed"]
        metas[rid] = r["meta"] or {}
        att = r["attest"]
        if att is None and r["cert"] is not None:
            att = track_a_attest(lab_src, r["cert"], tests.get(seed, {}))
            if att is None:
                no_check.append(rid)
        g = grade_run(r["answers"], keys[str(seed)], arena_dir, attest=att)
        if g["prov_refuted"]:
            print(f"{rid}: oracle claim NOT proven for {g['prov_refuted']} -> capped at E2")
        if g["prov_unchecked"]:
            print(f"{rid}: oracle claim could not be checked for {g['prov_unchecked']} -> capped at E2")
        graded[rid] = g
        wrong = [k for k, ok in g["items"].items() if not ok]
        print(f"{rid} {plan[rid]['cell']:12s} seed {seed}: exact {g['exact']:.2f} creative {g['creative']:.2f} ideas {g['ideas']:+.3f}"
              + (f" | wrong {wrong}" if wrong else ""))
    inp.close()
    if no_check:
        inp.warnings.append(f"{len(no_check)} run(s) have a certificate but it could not be re-checked: attach the kit's "
                            f"tests/ (or a zip of it) and protocols/amp_lab.py. Their oracle claims were capped at E2: "
                            + ", ".join(no_check))
    for w in inp.warnings:
        print("WARNING: " + w, file=sys.stderr)
    out_dir = output_dir(inp)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "runs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "cell", "seed", "condition", "model", "track", "tokens", "cost", "silent", "prov"] + ENDPOINTS + ["brier"]
                   + EXACT + ["C1", "C2", "C3", "C4"] + IDEAS)
        for rid, g in graded.items():
            m = metas.get(rid, {})
            tok = sum((m.get("tokens") or {}).values()) if m else ""
            w.writerow([rid, plan[rid]["cell"], plan[rid]["seed"], plan[rid]["condition"], plan[rid]["model"], m.get("track", "app"),
                        tok, m.get("cost") if m.get("cost") is not None else "", round(g["silent"], 4), g["prov"]]
                       + [round(g[m_], 4) for m_ in ENDPOINTS] + [round(g["brier"], 4)]
                       + [int(g["items"][k]) for k in EXACT] + [g[c] for c in ("C1", "C2", "C3", "C4")] + [g[t] for t in IDEAS])
    written = []
    for model, fb in sorted(feedback(graded, plan).items()):
        name = f"amp_feedback_{model}.json"
        json.dump(fb, open(os.path.join(out_dir, name), "w"), indent=1)
        written.append(name)
    analyse(graded, plan, out_dir, warnings=inp.warnings)
    print(f"\nwritten: {out_dir}/REPORT.md, runs.csv" + (", " + ", ".join(written) if written else ""))

if __name__ == "__main__":
    main()
