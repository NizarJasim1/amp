"""arc_anchor.py - anchor the study to a known external benchmark AND audit contamination.

ARC-format tasks (JSON: {"train": [{"input", "output"}...], "test": [{"input", "output"}...]}), e.g. the public
ARC-AGI evaluation set downloaded by you. Each test seed gets K tasks as PART6. Every (seed, task) is shown either
ORIGINAL or as an ISOMORPH: a random permutation of colours 1-9 (0 stays background) plus one of the 8
rotations/reflections, applied consistently to every grid of the task. An isomorph has the same rule and the same
difficulty for a solver that learns from the examples, but its exact grids cannot have been memorised.
  -> accuracy(original) > accuracy(isomorph) by a significant margin = evidence of contamination of the external set;
  -> no difference = the external anchor is usable, and the model's ARC number is comparable with the field.
(Our own generated parts need no such audit: their instances did not exist before the run; key hashes prove it.)

    python arc_anchor.py build --arc-dir ARC/evaluation --kit ../kit --k 4
    python arc_anchor.py grade --kit ../kit --runs ../runs_api            (needs runs.csv from grade.py there)
"""
import argparse
import csv
import glob
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit", "grader"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import stats6 as S  # noqa: E402


def d8(g, k):
    for _ in range(k % 4):
        g = [list(r) for r in zip(*g[::-1])]
    return [r[::-1] for r in g] if k >= 4 else g


def iso(task, rng):
    perm = list(range(1, 10))
    rng.shuffle(perm)
    cmap = {0: 0, **{i + 1: perm[i] for i in range(9)}}
    k = rng.randrange(1, 8)                                      # never the identity transform

    def f(g):
        return d8([[cmap[v] for v in row] for row in g], k)
    return {s: [{io: f(ex[io]) for io in ex} for ex in task[s]] for s in ("train", "test")}


def gstr(g):
    return ["".join(str(v) for v in row) for row in g]


def build(a):
    files = sorted(glob.glob(os.path.join(a.arc_dir, "*.json")))
    tasks = {os.path.basename(f)[:-5]: json.load(open(f)) for f in files}
    tasks = {k: t for k, t in tasks.items() if len(t["test"]) == 1 and all(max(len(g), len(g[0])) <= 30 for ex in t["train"] + t["test"] for g in (ex["input"], ex["output"]))}
    names = sorted(tasks)
    keys = {}
    for d in sorted(glob.glob(os.path.join(a.kit, "tests", "T*"))):
        seed = int(os.path.basename(d)[1:])
        rng = random.Random(f"arc-{seed}")
        pick = rng.sample(names, a.k)
        variants = [i % 2 for i in range(a.k)]
        rng.shuffle(variants)                                    # half originals, half isomorphs per test
        lines = ["Each puzzle shows grids before and after one hidden transformation. Grids are rows of digits; "
                 "0 is background. Find each rule and apply it to the test input.",
                 'Final answer: one ```json block, last in your reply: {"A1": grid, ...} where a grid is a list of row strings. '
                 'Also put in that JSON "_conf": {"A1": 0.9, ...}: your probability that each output is exactly right.', ""]
        kk = {}
        for i, (name, v) in enumerate(zip(pick, variants), 1):
            t = tasks[name] if v == 0 else iso(tasks[name], rng)
            lines.append(f"A{i}.")
            for j, ex in enumerate(t["train"], 1):
                lines += [f"Example {j} input:"] + gstr(ex["input"]) + [f"Example {j} output:"] + gstr(ex["output"]) + [""]
            lines += ["Test input:"] + gstr(t["test"][0]["input"]) + [""]
            kk[f"A{i}"] = {"task": name, "variant": "isomorph" if v else "original", "answer": gstr(t["test"][0]["output"])}
        open(os.path.join(d, "PART6.txt"), "w", encoding="utf-8").write("\n".join(lines))
        keys[str(seed)] = kk
    json.dump(keys, open(os.path.join(a.kit, "sealed", "ARC_KEYS.json"), "w"), sort_keys=True)
    print(f"PART6 written for {len(keys)} tests from {len(names)} eligible tasks")


def grade(a):
    keys = json.load(open(os.path.join(a.kit, "sealed", "ARC_KEYS.json")))
    plan = {r["run_id"]: r for r in csv.DictReader(open(os.path.join(a.kit, "plan.csv")))}
    acc = defaultdict(list)                                       # cell -> [ok]
    per_task = defaultdict(lambda: {"original": [], "isomorph": []})
    for p in glob.glob(os.path.join(a.runs, "R*.json")):
        base = os.path.basename(p)
        rid = base.split(".")[0]
        if "_" in rid or rid not in plan:
            continue
        ans = json.load(open(p))
        row = plan[rid]
        for item, k in keys.get(row["seed"], {}).items():
            got = ans.get(item)
            ok = isinstance(got, list) and [str(r) for r in got] == k["answer"]
            acc[(f"{row['condition']}@{row['model']}", k["variant"])].append(ok)
            per_task[k["task"]][k["variant"]].append(ok)
    print("| cell | original acc (n) | isomorph acc (n) |\n|---|---|---|")
    for cell in sorted({c for c, _ in acc}):
        o, i = acc[(cell, "original")], acc[(cell, "isomorph")]
        print(f"| {cell} | {S.mean(o):.3f} ({len(o)}) | {S.mean(i):.3f} ({len(i)}) |")
    d = [S.mean(v["original"]) - S.mean(v["isomorph"]) for v in per_task.values() if v["original"] and v["isomorph"]]
    if len(d) >= 2:
        r = S.paired_summary(d, [0.0] * len(d))
        print(f"\nContamination audit over {len(d)} tasks seen in both forms: original − isomorph = {r['diff']:+.3f} "
              f"{S.fmt_ci(r['ci'])}, p = {r['p']:.4f}. Positive and significant = memorisation of the external set.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "grade"])
    ap.add_argument("--arc-dir")
    ap.add_argument("--kit", required=True)
    ap.add_argument("--runs")
    ap.add_argument("--k", type=int, default=4)
    a = ap.parse_args()
    build(a) if a.cmd == "build" else grade(a)
