"""Synthetic end-to-end check: plant known per-cell accuracies, grade, and see the statistics recover them."""
import json, os, random, shutil, subprocess, sys, csv
KIT = sys.argv[1]; W = sys.argv[2]
shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
for f in os.listdir(f"{KIT}/grader"): shutil.copy(f"{KIT}/grader/{f}", W)
shutil.copy(f"{KIT}/sealed/KEYS.json", W)
keys = json.load(open(f"{W}/KEYS.json"))
ACC = {"FULL@48": .80, "PLAIN@55": .70, "PLAIN@48": .45, "noEV@48": .72, "noBLIND@48": .65, "noINS@48": .55,
       "noIDEA@48": .80, "noMEM@48": .78, "noLAB@48": .60, "TOOLS@48": .55, "SC5@48": .58, "BON5@48": .68, "FULL@55": .88}
FF = "def place(x, bins):\n    for i,b in enumerate(bins):\n        if b+x<=1: return i\n    return len(bins)\n"
BF = "def place(x, bins):\n    best=None\n    for i,b in enumerate(bins):\n        if b+x<=1 and (best is None or b>bins[best]): best=i\n    return len(bins) if best is None else best\n"
rng = random.Random(3)
for row in csv.DictReader(open(f"{W}/plan.csv")):
    cell = f"{row['condition']}@{row['model']}"; k = keys[row["seed"]]; acc = ACC[cell]
    seed_eff = (int(row["seed"]) % 5 - 2) * 0.05            # seed difficulty shared by all cells (pairing matters)
    ans, conf, led = {}, {}, {}
    for it in [f"Q{i}" for i in range(1, 7)] + [f"G{i}" for i in range(1, 5)] + ["K1", "T1"]:
        a = acc - (0.3 if it.startswith("G") else 0) + seed_eff
        ok = rng.random() < a
        ans[it] = k[it] if ok else ("0" if it[0] in "QKT" else [["0"]])
        conf[it] = round(min(.99, max(.05, a + rng.uniform(-.1, .1))), 2)
        if row["condition"] == "FULL": led[it] = {"E": 3 if ok and rng.random() < .8 else rng.choice([1, 2]), "p": conf[it]}
    ans["_conf"] = conf
    if led: ans["_ledger"] = led
    ans["C3"] = [0, 1, 3]  # invalid on purpose (wrong count)
    json.dump(ans, open(f"{W}/{row['run_id']}.json", "w"))
    if row["condition"] in ("FULL", "PLAIN") and int(row["seed"]) <= 3:
        json.dump({"I1": BF if cell == "FULL@48" else FF}, open(f"{W}/{row['run_id']}_p5.json", "w"))
print(subprocess.run([sys.executable, f"{W}/grade.py", W], capture_output=True, text=True, timeout=1500).stdout[-6000:])
