"""PART5 gauge: ideas scored on HIDDEN instances. Used by check.py (hidden seeds) and to make the public samples."""
import math, random

# ------------------------------------------------------------------ I1 online bin packing
def i1_sequence(rng, n=300):
    seq, mode = [], rng.random()
    for _ in range(n):
        u = rng.random()
        if u < 0.40: x = rng.uniform(0.15, 0.25)
        elif u < 0.70: x = rng.uniform(0.30, 0.40)
        elif u < 0.90: x = rng.uniform(0.55, 0.65)
        else: x = rng.uniform(0.01, 0.05)
        seq.append(round(x, 4))
    if mode < 0.3:                      # adversarial blocks: small items first, then large ones
        seq.sort()
    elif mode < 0.45:
        seq.sort(reverse=True)
    return seq

def i1_run(place, seq):
    bins = []
    for x in seq:
        try:
            k = place(x, list(bins))
        except Exception:
            k = len(bins)
        if not isinstance(k, int) or k < 0 or k > len(bins) or (k < len(bins) and bins[k] + x > 1 + 1e-9):
            k = len(bins)               # invalid choice: forced into a new bin
        if k == len(bins): bins.append(x)
        else: bins[k] += x
    return len(bins) / math.ceil(sum(seq) - 1e-9)

def i1_baseline(x, bins):
    for i, b in enumerate(bins):
        if b + x <= 1: return i
    return len(bins)

# ------------------------------------------------------------------ I2 sequence prediction (log-loss, 4 symbols)
def i2_sequence(rng, n=1500):
    kind = rng.randrange(4)
    out = []
    if kind == 0:                                   # sparse order-2 Markov chain
        T = {}
        for a in range(4):
            for b in range(4):
                p = [rng.random() ** 4 for _ in range(4)]; s = sum(p); T[(a, b)] = [v / s for v in p]
        a, b = 0, 1
        for _ in range(n):
            c = rng.choices(range(4), T[(a, b)])[0]; out.append(c); a, b = b, c
    elif kind == 1:                                 # noisy periodic pattern with occasional period change
        pat = [rng.randrange(4) for _ in range(rng.randint(3, 9))]
        for t in range(n):
            if rng.random() < 0.004: pat = [rng.randrange(4) for _ in range(rng.randint(3, 9))]
            out.append(pat[t % len(pat)] if rng.random() > 0.08 else rng.randrange(4))
    elif kind == 2:                                 # switching between two order-1 chains
        Ts = []
        for _ in range(2):
            Ts.append([[v / s for v in p] for p in [[rng.random() ** 3 for _ in range(4)] for _ in range(4)] for s in [sum(p)]])
        cur, a, k = 0, 0, 0
        for t in range(n):
            if t % rng.randint(150, 250) == 0: cur = 1 - cur
            a = rng.choices(range(4), Ts[cur][a])[0]; out.append(a)
    else:                                           # slow counter with noise
        k = rng.randint(3, 12)
        for t in range(n):
            out.append((t // k) % 4 if rng.random() > 0.1 else rng.randrange(4))
    return out

def i2_run(Predictor, seq):
    p = Predictor(); loss = 0.0
    for s in seq:
        try:
            q = list(p.predict()); tot = sum(max(0.0, float(v)) for v in q)
            prob = max(0.0, float(q[s])) / tot if tot > 0 and len(q) == 4 else 0.0
        except Exception:
            prob = 0.0
        loss += -math.log2(max(prob, 1e-6))
        try: p.update(s)
        except Exception: pass
    return loss / len(seq)

class I2Baseline:
    def __init__(self): self.c = [1, 1, 1, 1]
    def predict(self): return list(self.c)
    def update(self, s): self.c[s] += 1

# ------------------------------------------------------------------ I3 weighted tardiness scheduling
def i3_instance(rng, n=60):
    tight = rng.choice([0.4, 0.6, 0.8]); spread = rng.choice([0.2, 0.6, 1.0])
    p = [rng.randint(1, 100) for _ in range(n)]; P = sum(p)
    lo, hi = P * (1 - tight - spread / 2), P * (1 - tight + spread / 2)
    return [(p[i], rng.randint(1, 10), max(0, int(rng.uniform(lo, hi)))) for i in range(n)]

def i3_cost(jobs, order):
    if sorted(order) != list(range(len(jobs))): return None
    t = cost = 0
    for i in order:
        p, w, d = jobs[i]; t += p; cost += w * max(0, t - d)
    return cost

def i3_baseline(jobs):
    return sorted(range(len(jobs)), key=lambda i: jobs[i][2])

# ------------------------------------------------------------------ I4 iterated rock-paper-scissors vs hidden bots
BEATS = lambda m: (m + 1) % 3     # move that beats m

def make_bots(seed):
    rng = random.Random(seed)
    def biased(p):
        def f(h, r): return r.choices(range(3), p)[0]
        return f
    def cycle(start, step):
        def f(h, r): return (start + step * len(h)) % 3
        return f
    def beat_last(h, r):                      # beats the opponent's last move
        return BEATS(h[-1][0]) if h else r.randrange(3)
    def copy_last(h, r):
        return h[-1][0] if h else r.randrange(3)
    def freq_counter(h, r):                   # beats the opponent's most frequent move
        if not h: return r.randrange(3)
        c = [0, 0, 0]
        for m, _ in h[-60:]: c[m] += 1
        return BEATS(max(range(3), key=lambda i: c[i]))
    def markov2(h, r):                        # predicts opponent from its last two moves, plays the counter
        if len(h) < 3: return r.randrange(3)
        key = (h[-2][0], h[-1][0]); cnt = [0, 0, 0]
        for i in range(2, len(h)):
            if (h[i - 2][0], h[i - 1][0]) == key: cnt[h[i][0]] += 1
        return BEATS(max(range(3), key=lambda i: cnt[i])) if sum(cnt) else r.randrange(3)
    def mirror2(h, r):
        return h[-2][0] if len(h) >= 2 else r.randrange(3)
    def win_stay_lose_shift(h, r):
        if not h: return r.randrange(3)
        me, opp = h[-1][1], h[-1][0]
        return me if BEATS(opp) == me else BEATS(me)
    def switcher(h, r):
        k = (len(h) // 120) % 4
        return [freq_counter, cycle(1, 2), markov2, beat_last][k](h, r)
    bots = [biased([0.5, 0.3, 0.2]), cycle(rng.randrange(3), 1), cycle(rng.randrange(3), 2), beat_last, copy_last,
            freq_counter, markov2, mirror2, win_stay_lose_shift, switcher]
    return bots

def i4_run(Player, rounds=600, seed=0):
    bots = make_bots(seed); total = 0.0
    for b_i, bot in enumerate(bots):
        r = random.Random(seed * 1000 + b_i); me = Player(); hist_me, hist_bot = [], []
        score = 0
        for t in range(rounds):
            try: m = int(me.move([(a, b) for a, b in zip(hist_me, hist_bot)])) % 3
            except Exception: m = r.randrange(3)
            o = bot([(a, b) for a, b in zip(hist_me, hist_bot)], r) % 3   # bot sees (player move, bot move)
            score += 1 if m == BEATS(o) else (-1 if o == BEATS(m) else 0)
            hist_me.append(m); hist_bot.append(o)
        total += score / rounds
    return total / len(bots)

class I4Baseline:
    def __init__(self): import random as _r; self.r = _r.Random(7)
    def move(self, history): return self.r.randrange(3)
