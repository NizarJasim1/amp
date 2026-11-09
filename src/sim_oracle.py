"""sim_oracle.py - the governing claim, in a simulation (NOT real-model evidence).

Two models: WEAK (lower prior-correctness) and STRONG. A task is 'oracle-rich' (an external check exists: running
a candidate on held-out cases) or 'oracle-poor' (only the model's own judgement). Three scaffolds, applied to BOTH
models with the SAME budget:
  none   : report the model's first answer
  think  : organise thinking -> a uniform small bump to prior-correctness on EVERY task (same for both models)
  oracle : on oracle-rich tasks, generate K candidates and keep one that passes the held-out oracle; on oracle-poor
           tasks it can do nothing extra (no external check), so it falls back to 'think'
The question: does 'oracle' let WEAK pass STRONG, and ONLY where the oracle exists?
    python sim_oracle.py [worlds=400]
"""
import random
import statistics as st
import sys

WEAK, STRONG = 0.45, 0.70        # prior P(a single candidate is correct) for the two models
THINK = 0.06                     # uniform gain from organising thought - identical for both models (the trap)
K = 6                            # candidates generated for the oracle to filter
ORACLE_FP = 0.15                 # chance the held-out oracle passes a wrong candidate


def one(model, scaffold, oracle_rich, rng):
    base = model + (THINK if scaffold in ("think", "oracle") else 0)
    if scaffold == "oracle" and oracle_rich:
        for _ in range(K):                       # try candidates; keep the first the external oracle accepts
            correct = rng.random() < base
            if correct or rng.random() < ORACLE_FP:   # oracle accepts a correct one, or is fooled by a wrong one
                return correct
        return rng.random() < base               # none accepted: fall back to a fresh attempt
    return rng.random() < base


def run(worlds):
    rng = random.Random(0)
    cells = {}
    for rich in (True, False):
        for model, mname in ((WEAK, "weak"), (STRONG, "strong")):
            for sc in ("none", "think", "oracle"):
                acc = st.mean(one(model, sc, rich, rng) for _ in range(worlds))
                cells[(rich, mname, sc)] = acc
    out = ["SIMULATION (mechanism demo, not real-model evidence). %d tasks per cell." % worlds,
           "'think' adds the SAME bump to both models; 'oracle' filters candidates by an external check (oracle-rich only).\n",
           "| tasks | scaffold | weak | strong | weak − strong |", "|---|---|---|---|---|"]
    for rich in (True, False):
        for sc in ("none", "think", "oracle"):
            w, s = cells[(rich, "weak", sc)], cells[(rich, "strong", sc)]
            out.append(f"| {'oracle-rich' if rich else 'oracle-poor'} | {sc} | {w:.3f} | {s:.3f} | {w - s:+.3f} |")
    # the governing numbers
    wr = cells[(True, "weak", "oracle")] - cells[(True, "strong", "none")]
    wt = cells[(True, "weak", "think")] - cells[(True, "strong", "think")]
    wp = cells[(False, "weak", "oracle")] - cells[(False, "strong", "think")]
    wvs = cells[(True, "weak", "oracle")] - cells[(True, "strong", "oracle")]
    out += ["",
            f"weak+oracle vs strong+none   (oracle-rich): {wr:+.3f}  <- weak passes the UNSCAFFOLDED strong model, via the oracle",
            f"weak+oracle vs strong+oracle (oracle-rich): {wvs:+.3f}  <- give the strong model the SAME oracle and it stays ahead",
            f"weak+think  vs strong+think  (oracle-rich): {wt:+.3f}  <- organising thought alone keeps the strong model ahead",
            f"weak+oracle vs strong+think  (oracle-poor): {wp:+.3f}  <- with no external check, no superiority (as predicted)",
            "",
            "HONEST SCOPE: the weak model passes the strong one only when the strong one is NOT itself using the scaffold.",
            "With the same oracle on both, the stronger model stays ahead. The claim is 'closes / crosses the gap to the",
            "plain stronger model', never 'beats the stronger model also running AMP'."]
    text = "\n".join(out)
    print(text)
    open("sim_oracle_results.txt", "w").write(text + "\n")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 4000)
