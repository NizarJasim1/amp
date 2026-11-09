"""make_kit.py - builds the complete, pre-registered AMP v6 study kit.

    python make_kit.py --seeds 30 --out kit

kit/
  protocols/          AMP_v6.md, AMP_v6_no<X>.md (10 ablations), BASE_*.md (4 baselines; FULL@55 is the 5th), amp_lab.py
  tests/T<seed>/      PART1..PART5.txt for every seed (fresh instances; attach to test chats)
  sealed/KEYS.json    the answers - never attach to a test chat
  grader/             grade.py, stats6.py, arena5.py (+ copy KEYS.json and plan.csv here when grading)
  plan.csv            every run: id, tier, seed, condition, model, files to attach, memory chain
  RUNSHEET.md         the same plan, readable
  PREREG.md           hypotheses, endpoints, analysis, and SHA-256 of every file that must not change later
"""
import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_gen  # noqa: E402
import conditions as C  # noqa: E402

TIERS = [  # (tier, seeds, cells)  - cells are (condition, model)
    ("P pilot", range(1, 6), [("FULL", "48"), ("PLAIN", "55"), ("PLAIN", "48")]),
    ("1 primary", range(6, 21), [("FULL", "48"), ("PLAIN", "55"), ("PLAIN", "48")]),
    ("2 ablation", range(1, 11), [(f"no{m}", "48") for m in C.MODULES]),
    ("3 baselines", range(1, 11), [("TOOLS", "48"), ("SC5", "48"), ("BON5", "48"), ("CONF", "48"), ("FULL", "55")]),
    ("X extension", range(21, 31), [("FULL", "48"), ("PLAIN", "55"), ("PLAIN", "48")]),
]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def make_plan(seed_limit, extra_pairs=()):
    rng = random.Random("amp-v6-plan")
    rows, n, last_mem = [], 0, {}
    tiers = list(TIERS) + [(f"L law {w}:{s}", range(1, 11), [("FULL", w), ("PLAIN", s), ("PLAIN", w)]) for w, s in extra_pairs]
    for tier, seeds, cells in tiers:
        for s in seeds:
            if s > seed_limit:
                continue
            order = cells[:]
            rng.shuffle(order)                      # randomised order inside each seed block (time drift)
            for cond, model in order:
                n += 1
                rid = f"R{n:03d}"
                proto, lab, mem, _ = C.CONDITIONS[cond]
                files = ([f"protocols/{proto}"] if proto else []) + (["protocols/amp_lab.py"] if lab else [])
                cell = f"{cond}@{model}"
                rows.append({"run_id": rid, "tier": tier, "seed": s, "condition": cond, "model": model,
                             "model_name": C.MODELS.get(model, model), "attach_first": " ".join(files + [f"tests/T{s}/PART1.txt"]),
                             "memory_from": last_mem.get(cell, "") if mem else "", "opening": C.opening_message(cond)})
                if mem:
                    last_mem[cell] = rid
    return rows


def embed_given_manifest(out):
    """v6.6: write the sha256 of every problem file into the kit's amp_lab.py, so a source sealed as 'given' is
    checked against the real problem files instead of taken on the model's word (works in Track A too)."""
    shas = set()
    for root, _, files in os.walk(os.path.join(out, "tests")):
        for f in files:
            if f.startswith("PART") and f.endswith(".txt"):
                text = open(os.path.join(root, f), encoding="utf-8").read()
                shas.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
    p = os.path.join(out, "protocols", "amp_lab.py")
    src = open(p, encoding="utf-8").read()
    line = next(ln for ln in src.splitlines() if ln.startswith("KIT_GIVEN_SHA256 = "))
    new = "KIT_GIVEN_SHA256 = frozenset({" + ", ".join(f'"{h}"' for h in sorted(shas)) + "})   # problem files of this kit"
    open(p, "w", encoding="utf-8").write(src.replace(line, new, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--out", default="kit")
    ap.add_argument("--pairs", default="", help="extra weak:strong model pairs for the recovery curve, e.g. os-s:os-l,haiku:sonnet")
    a = ap.parse_args()
    out = a.out
    for sub in ("protocols", "tests", "sealed", "grader"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    C.build_protocols(os.path.join(out, "protocols"))
    shutil.copy(os.path.join(HERE, "amp_lab.py"), os.path.join(out, "protocols", "amp_lab.py"))
    keys = {}
    for s in range(1, a.seeds + 1):
        kp = os.path.join(out, "tests", f"T{s}", ".done")
        parts, key = bench_gen.build(s)
        d = os.path.join(out, "tests", f"T{s}")
        os.makedirs(d, exist_ok=True)
        for name, text in parts.items():
            open(os.path.join(d, f"{name}.txt"), "w", encoding="utf-8").write(text)
        keys[str(s)] = key
        print(f"T{s} ok", flush=True)
        _ = kp
    json.dump(keys, open(os.path.join(out, "sealed", "KEYS.json"), "w"), sort_keys=True)
    embed_given_manifest(out)
    for f in ("grade.py", "stats6.py", "arena5.py"):
        shutil.copy(os.path.join(HERE, f), os.path.join(out, "grader", f))
    rows = make_plan(a.seeds, [tuple(p.split(":")) for p in a.pairs.split(",") if p])
    with open(os.path.join(out, "plan.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    shutil.copy(os.path.join(out, "plan.csv"), os.path.join(out, "grader", "plan.csv"))
    rs = ["# Run sheet (generated; follow top to bottom)\n", "| run | tier | seed | condition | model | attach in the first message | memory from |",
          "|---|---|---|---|---|---|---|"]
    rs += [f"| {r['run_id']} | {r['tier']} | {r['seed']} | {r['condition']} | {r['model_name']} | {r['attach_first']} | {r['memory_from'] or '–'} |" for r in rows]
    open(os.path.join(out, "RUNSHEET.md"), "w", encoding="utf-8").write("\n".join(rs) + "\n")
    hashes = {p: sha(os.path.join(out, p)) for p in ["sealed/KEYS.json", "plan.csv"] +
              [f"protocols/{f}" for f in sorted(os.listdir(os.path.join(out, "protocols")))
               if os.path.isfile(os.path.join(out, "protocols", f)) and not f.startswith((".", "__"))] +
              [f"grader/{f}" for f in ("grade.py", "stats6.py", "arena5.py")]}
    tmpl = open(os.path.join(HERE, "PREREG.tmpl.md"), encoding="utf-8").read()
    table = "\n".join(f"| `{p}` | `{h}` |" for p, h in hashes.items())
    open(os.path.join(out, "PREREG.md"), "w", encoding="utf-8").write(tmpl.replace("__HASHES__", table).replace("__NRUNS__", str(len(rows))))
    print(f"kit written: {len(rows)} planned runs, {a.seeds} seeds")


if __name__ == "__main__":
    main()
