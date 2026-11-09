"""sim_aiv.py - mechanism demonstration (SIMULATION, not evidence about real models).

A world where verification methods fail TOGETHER for mechanistic reasons, not by an assumed correlation number:
  - shared helpers: when helper h fails on a task, every method calling h returns the same wrong value;
  - representation blind spots: when class k fails on a task, every method of class k returns the same wrong value;
  - own bugs: a method-specific random wrong value.
Policies get the same candidate methods, the same budget of method runs, and the same graded warm-up data:
  P0 uniform      2 random methods per task, extra runs on disagreements
  P1 confidence   1 method each, extra runs go to the lowest self-confidence tasks until two methods agree
                  (proxy for confidence-based adaptive test-time scaling), random extra methods
  P2 class-route  learns class-pair shared-failure rates from warm-up (proxy for correlation-aware routing between
                  models/verifiers), and uses the SAME global allocator and stopping rule as P3
  P3 AIV          differs from P2 ONLY in the risk predictor: it predicts shared-failure risk of a pair from its executed structure (shared callees, structural
                  similarity, class) with a model fitted on warm-up; designs the next check to minimise that risk;
                  allocates runs globally to the largest predicted error drop; reports calibrated p
  P4 AIV+conf     P3 with the model's self-confidence as the prior for a not-yet-checked answer (composition)
Metrics: accuracy, silent errors (reported p >= .9 but wrong), Brier score of reported p.
    python sim_aiv.py [worlds=20]
"""
import math
import random
import statistics as st
import sys

import amp_lab as L

H, K, M = 12, 4, 8


def make_world(seed):
    r = random.Random(seed)
    helpers = [r.uniform(0.02, 0.15) for _ in range(H)]
    blind = [r.uniform(0.03, 0.12) for _ in range(K)]
    pref = [r.sample(range(H), 4) for _ in range(K)]             # each class tends to use its own helpers
    return r, helpers, blind, pref


def make_task(r, helpers, blind, pref):
    fail_h = [r.random() < b for b in helpers]
    fail_k = [r.random() < b for b in blind]
    methods = []
    for m in range(M):
        k = r.randrange(K)
        hs = set(r.sample(pref[k], 2)) | ({r.randrange(H)} if r.random() < 0.5 else set())
        e = r.uniform(0.03, 0.10)
        if r.random() < e:
            out = ("own", m, r.random())
        elif fail_k[k]:
            out = ("class", k)
        elif any(fail_h[h] for h in sorted(hs)):
            out = ("helper", min(h for h in hs if fail_h[h]))
        else:
            out = "TRUE"
        methods.append({"k": k, "hs": hs, "out": out, "sim_seed": r.random()})
    conf = min(0.99, max(0.01, 0.6 + (0.25 if methods[0]["out"] == "TRUE" else -0.1) + r.gauss(0, 0.15)))
    return methods, conf


def feats(a, b):
    same = int(a["k"] == b["k"])
    sim = (0.4 + 0.4 * ((a["sim_seed"] + b["sim_seed"]) / 2)) if same else 0.3 * ((a["sim_seed"] + b["sim_seed"]) / 2)
    return {"struct_sim": sim, "shared_callees": L._jac(a["hs"], b["hs"]), "lineage": 0, "same_class": same}


class Mem:
    def __init__(self, rows):
        self.data = {"pairs": rows}


def warmup(world, n=300):
    r, helpers, blind, pref = world
    rows, cls = [], {}
    for _ in range(n):
        ms, _ = make_task(r, helpers, blind, pref)
        for i in range(M):
            for j in range(i + 1, M):
                a, b = ms[i], ms[j]
                if a["out"] == b["out"]:
                    wrong = a["out"] != "TRUE"
                    rows.append({**feats(a, b), "wrong": wrong})
                    key = tuple(sorted((a["k"], b["k"])))
                    c = cls.setdefault(key, [1, 20])                     # Laplace-ish prior: 1 wrong in 20
                    c[0] += wrong
                    c[1] += 1
    return Mem(rows), {k: v[0] / v[1] for k, v in cls.items()}


def run_policy(policy, tasks, budget, w, clsrate):
    n = len(tasks)
    used = [[] for _ in range(n)]
    spent = 0

    def add(t, m):
        nonlocal spent
        used[t].append(m)
        spent += 1

    def risk(a, b):
        if policy == "P2":
            return clsrate.get(tuple(sorted((a["k"], b["k"]))), 0.05)
        return L.pair_risk(feats(a, b), w=w)

    def state(t):
        ms = [tasks[t][0][i] for i in used[t]]
        agree = [(ms[i], ms[j]) for i in range(len(ms)) for j in range(i + 1, len(ms)) if ms[i]["out"] == ms[j]["out"]]
        return ms, agree

    def unused(t):
        return [i for i in range(M) if i not in used[t]]
    rng = random.Random(7)
    import heapq
    if policy == "P1":
        for t in range(n):
            add(t, 0)
        heap = [(tasks[t][1], t) for t in range(n)]                  # lowest self-confidence first
        heapq.heapify(heap)
        while spent < budget and heap:
            c, t = heapq.heappop(heap)
            u = unused(t)
            if state(t)[1] or not u:
                continue
            add(t, rng.choice(u))
            heapq.heappush(heap, (c, t))
    elif policy == "P0":
        for t in range(n):
            add(t, 0)
        for t in range(n):
            if spent >= budget:
                break
            add(t, rng.choice(unused(t)))
        progressed = True
        while spent < budget and progressed:
            progressed = False
            for t in range(n):
                if spent >= budget:
                    break
                if not state(t)[1] and unused(t):
                    add(t, rng.choice(unused(t)))
                    progressed = True
    else:  # P2 and P3 share the SAME global allocator; only the pair-risk predictor differs
        for t in range(n):
            add(t, 0)

        def p_wrong(t):
            ms, agree = state(t)
            if agree:
                return min(risk(a, b) for a, b in agree)
            if policy == "P4" and len(ms) == 1:
                return 1 - tasks[t][1]                               # self-confidence as the prior for an unchecked answer
            return 0.5

        def best_next(t):
            ms, _ = state(t)
            return min(unused(t), key=lambda i: min(risk(tasks[t][0][i], m) for m in ms))
        heap = [(-p_wrong(t), t) for t in range(n)]
        heapq.heapify(heap)
        while spent < budget and heap:
            negp, t = heapq.heappop(heap)
            if not unused(t):
                continue
            i = best_next(t)
            ideal = min(risk(tasks[t][0][i], m) for m in state(t)[0])
            if state(t)[1] and -negp - ideal <= 1e-4:
                continue
            add(t, i)
            heapq.heappush(heap, (-p_wrong(t), t))
    # answers + reported confidence
    correct, silent, brier = 0, 0, 0.0
    for t in range(n):
        ms, agree = state(t)
        if policy in ("P2", "P3", "P4") and agree:
            a, b = min(agree, key=lambda ab: risk(*ab))
            ans, p = a["out"], 1 - risk(a, b)
        elif agree:
            ans, p = agree[0][0]["out"], 0.95                       # naive: agreement treated as independent
        else:
            ans, p = ms[0]["out"], (tasks[t][1] if policy in ("P1", "P4") and len(ms) == 1 else 0.5)
        ok = ans == "TRUE"
        correct += ok
        silent += (p >= 0.9 and not ok)
        brier += (p - ok) ** 2
    return correct / n, silent / n, brier / n, spent / n


def main():
    worlds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    res = {}
    for ws in range(worlds):
        world = make_world(ws)
        mem, clsrate = warmup(world)
        w = L.pair_weights(mem)
        r, helpers, blind, pref = world
        tasks = [make_task(r, helpers, blind, pref) for _ in range(400)]
        for per in (2.0, 2.5, 3.0):
            for pol in ("P0", "P1", "P2", "P3", "P4"):
                res.setdefault((per, pol), []).append(run_policy(pol, tasks, int(per * len(tasks)), w, clsrate))
    lines = ["SIMULATION (mechanism demo, not real-model evidence). mean over %d worlds x 400 tasks; same budget per row" % worlds,
             "budget/task  policy          accuracy        silent errors (p>=.9, wrong)   Brier"]
    names = {"P0": "uniform", "P1": "confidence", "P2": "class-route", "P3": "AIV", "P4": "AIV+conf"}
    for (per, pol), v in sorted(res.items()):
        acc = [x[0] for x in v]
        sil = [x[1] for x in v]
        bri = [x[2] for x in v]
        lines.append(f"{per:>5}        {pol} {names[pol]:12s} {st.mean(acc):.4f} ± {st.stdev(acc):.4f}   "
                     f"{st.mean(sil):.4f} ± {st.stdev(sil):.4f}            {st.mean(bri):.4f}")
    for per in (2.0, 2.5, 3.0):
        for x, y in (("P3", "P2"), ("P4", "P1"), ("P4", "P2")):
            d = [a[0] - b[0] for a, b in zip(res[(per, x)], res[(per, y)])]
            s = [b[1] - a[1] for a, b in zip(res[(per, x)], res[(per, y)])]
            lines.append(f"budget {per}: {names[x]} - {names[y]}: accuracy {st.mean(d):+.4f} (wins {sum(v > 0 for v in d)}/{len(d)} worlds), "
                         f"silent errors removed {st.mean(s):+.4f}")
    out = "\n".join(lines)
    print(out)
    open("sim_aiv_results.txt", "w").write(out + "\n")


if __name__ == "__main__":
    main()
