"""bench_gen.py - fresh, never-seen test instances for every part of the AMP benchmark, from a seed.

Every run of the experiment gets its own seed, so no answer can exist in any model's training data and the
sample size is limited only by how many chats are run. Every generated exact answer is SELF-VERIFIED at
generation time: the fast method that produces the key must agree with a brute force on small parameters
of the same instance, otherwise the instance is rejected and redrawn.

    python bench_gen.py --seed 1234 --out tests/       ->  tests/T1234/PART1..5.txt  +  tests/T1234/key.json
"""
from __future__ import annotations

import itertools
import json
import math
import os
import random
import sys
from fractions import Fraction
from functools import lru_cache

sys.setrecursionlimit(20000)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import amp_lab as L  # noqa: E402
import arena5 as A5  # noqa: E402
import programs_src as PR  # noqa: E402

MOD = 10**9 + 7
BIG = 10**18


class Reject(Exception):
    """The drawn instance failed self-verification or is degenerate: draw another."""


# ============================================================================== Q: insight families
def q_strings(rng):
    k = rng.choice([3, 4])
    letters = "ABCD"[:k]
    forb = set()
    while len(forb) < rng.choice([1, 2]):
        w = "".join(rng.choice(letters) for _ in range(3))
        if w[0] != w[1] and w[1] != w[2]:
            forb.add(w)
    forb = sorted(forb)

    def ok(s):
        return all(s[i] != s[i + 1] for i in range(len(s) - 1)) and not any(f in s for f in forb)
    states = [a + b for a in letters for b in letters if a != b]

    def step(s):
        return [(s[1] + c, 1) for c in letters if c != s[1] and s + c not in forb]

    def count(n, mod=None):
        if n < 2:
            return k ** n if mod is None else k ** n % mod
        return L.transfer_count(states, step, n - 2, lambda s: 1, mod=mod)
    for n in range(0, 8):
        if count(n) != sum(1 for t in itertools.product(letters, repeat=n) if ok("".join(t))):
            raise Reject()
    if count(10) == 0:
        raise Reject()
    words = " and ".join(f'"{f}"' for f in forb)
    text = (f"Count the strings of length n = 10^18 over the alphabet {{{', '.join(letters)}}} in which no two adjacent letters are equal "
            f"and none of {words} occurs as a contiguous substring. Give the count modulo 1000000007.")
    return text, str(count(BIG, MOD))


def q_subtraction(rng):
    S = sorted(rng.sample(range(1, 16), rng.choice([3, 4])))
    lose = [False] * 6001
    for n in range(6001):
        lose[n] = not any(n >= s and lose[n - s] for s in S)
    per = L.find_period(lose, max_pre=500, max_per=1000)
    if per is None:
        raise Reject()
    pre, p = per
    if p < 6:
        raise Reject()                                         # trivial parity-type games are not insight problems
    N = rng.choice([10**15, 10**16, 10**17])
    ans = L.periodic_count(lose, pre, p, N, start=1)
    for M in (50, 777, 5999):
        if L.periodic_count(lose, pre, p, M, start=1) != sum(lose[1:M + 1]):
            raise Reject()
    for n in range(1, 40):                                     # Grundy-free ground truth
        if lose[n] == L.brute_win(n, lambda m: [m - s for s in S if m >= s]):
            raise Reject()
    e = int(round(math.log10(N)))
    text = (f"A pile has n tokens. Two players alternate; a move removes exactly {', '.join(map(str, S[:-1]))} or {S[-1]} tokens "
            f"(never more than the pile holds). A player who cannot move loses. For how many n with 1 <= n <= 10^{e} "
            "is the player about to move in a losing position? Give the exact count.")
    return text, str(ans)


def q_race(rng):
    L5 = rng.choice([4, 5])
    while True:
        a = "".join(rng.choice("HT") for _ in range(L5))
        b = "".join(rng.choice("HT") for _ in range(L5))
        if a != b and a not in b and b not in a:
            break
    ph = rng.choice([Fraction(1, 2), Fraction(2, 3), Fraction(3, 5), Fraction(1, 3)])
    pats = [a, b]
    states = sorted({p[:i] for p in pats for i in range(len(p))}, key=lambda s: (len(s), s))

    def nxt(s, c):
        t = s + c
        for i, p in enumerate(pats):
            if t.endswith(p):
                return ("END", i)
        while t not in states:
            t = t[1:]
        return t
    allst = states + [("END", 0), ("END", 1)]
    res = L.markov_absorb(allst, lambda s: [(ph, nxt(s, "H")), (1 - ph, nxt(s, "T"))],
                          lambda s: (1 if s[1] == 0 else 0) if isinstance(s, tuple) else None)
    ans = res[""]
    r = random.Random(rng.random())                            # Monte Carlo sanity
    w = 0
    for _ in range(20000):
        s = ""
        while True:
            s += "H" if r.random() < ph else "T"
            if s.endswith(a):
                w += 1
                break
            if s.endswith(b):
                break
    if abs(w / 20000 - float(ans)) > 0.03:
        raise Reject()
    if ans in (0, 1):
        raise Reject()
    text = (f"A biased coin shows heads (H) with probability {ph} and tails (T) with probability {1 - ph}. It is flipped until "
            f"either {a} or {b} appears as consecutive flips. What is the exact probability that {a} appears first? Give a reduced fraction a/b.")
    return text, f"{ans.numerator}/{ans.denominator}"


def q_digits(rng):
    base = rng.choice([2, 3, 5, 10])
    m = rng.choice([7, 9, 11, 13, 17, 19, 23])
    if base == 2:
        rule, bad = "has no two adjacent 1s in its binary representation", lambda s, d: s[1] == 1 and d == 1
    elif base == 3:
        rule, bad = "has no digit 2 in its base-3 representation", lambda s, d: d == 2
    elif base == 5:
        rule, bad = "has no two equal adjacent digits in its base-5 representation", lambda s, d: s[1] == d and s[2]
    else:
        f = rng.choice([3, 4, 7])
        rule, bad = f"has no digit {f} in its decimal representation", lambda s, d, f=f: d == f
    N = rng.randrange(10**17, 10**18)

    def step(st, d, lead):
        if not lead and bad(st, d):
            return None
        return ((st[0] * base + d) % m, d if not lead else 0, 0 if lead else 1)
    cnt = L.digit_dp(N, base, (0, 0, 0), step, lambda st: st[0] == 0) - 1      # remove x = 0

    for M in (100, 2000):
        got = L.digit_dp(M, base, (0, 0, 0), step, lambda st: st[0] == 0) - 1
        want = sum(1 for x in range(1, M + 1) if x % m == 0 and _digit_ok(x, base, bad))
        if got != want:
            raise Reject()
    text = (f"Let N = {N}. How many integers x with 1 <= x <= N are divisible by {m} and "
            f"{rule.replace('has', 'have', 1).replace(' its ', ' their ')}? Give the exact count.")
    return text, str(cnt)


def _digit_ok(x, base, bad):
    ds = []
    while x:
        ds.append(x % base)
        x //= base
    ds = ds[::-1]
    prev, started = 0, 0
    for d in ds:
        if bad((0, prev, started), d):
            return False
        prev, started = d, 1
    return True


def q_necklace(rng):
    k = rng.choice([2, 3, 4])
    n = rng.randrange(10**11, 10**12)

    if n % MOD == 0:
        raise Reject()

    def neck(n, mod=None):
        s = sum(L.euler_phi(d) * (pow(k, n // d, mod) if mod else k ** (n // d)) for d in L.divisors(n))
        return s * pow(n, -1, mod) % mod if mod else s // n
    for t in range(1, 8):
        seen = set()
        for w in itertools.product(range(k), repeat=t):
            seen.add(min(w[i:] + w[:i] for i in range(t)))
        if len(seen) != neck(t):
            raise Reject()
    text = (f"How many strings of length n = {n} over an alphabet of {k} letters are there up to rotation (two strings are the same "
            f"if one is a cyclic rotation of the other)? Give the count modulo 1000000007.")
    return text, str(neck(n, MOD))


def q_trees(rng):
    rows = rng.choice([2, 3, 4])
    extra = rng.choice(["grid", "cylinder", "diag"]) if rows >= 3 else rng.choice(["grid", "diag"])
    N = rng.randrange(10**17, 10**18)

    def graph(n):
        V = [(r, c) for r in range(rows) for c in range(n)]
        idx = {v: i for i, v in enumerate(V)}
        edges = set()
        for (r, c) in V:
            nbrs = [(r + 1, c), (r, c + 1)]
            if extra == "cylinder" and r == rows - 1:
                nbrs.append((0, c))
            if extra == "diag":
                nbrs.append((r + 1, c + 1))
            for v in nbrs:
                if v in idx and v != (r, c):
                    edges.add(tuple(sorted((idx[(r, c)], idx[v]))))
        return len(V), sorted(edges)

    def trees(n):
        nv, edges = graph(n)
        Lm = [[0] * nv for _ in range(nv)]
        for a, b in edges:
            Lm[a][a] += 1
            Lm[b][b] += 1
            Lm[a][b] -= 1
            Lm[b][a] -= 1
        return L.det_exact([row[1:] for row in Lm[1:]]) if nv > 1 else 1

    def brute(n):                                              # count spanning trees literally (union-find)
        nv, edges = graph(n)
        tot = 0
        for sub in itertools.combinations(edges, nv - 1):
            par = list(range(nv))

            def f(x):
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x
            ok = True
            for a, b in sub:
                ra, rb = f(a), f(b)
                if ra == rb:
                    ok = False
                    break
                par[ra] = rb
            tot += ok
        return tot
    for n in (1, 2, 3):
        if graph(n)[0] <= 9 and trees(n) != brute(n):
            raise Reject()
    seq = [trees(n) for n in range(1, 31)]
    h = L.guess_linear(seq, holdout=5)
    if h is None:
        raise Reject()
    ans = L.lin_nth(h["coeffs"], seq[:h["order"]], N - 1, MOD)
    shape = {"grid": f"the grid graph with {rows} rows and n columns (a vertex per cell, edges between cells sharing a side)",
             "cylinder": f"the cylinder graph with {rows} rows and n columns (cells sharing a side are adjacent, and additionally the top and bottom cell of every column are adjacent)",
             "diag": f"the graph on a {rows} x n array of cells where cell (r, c) is adjacent to (r+1, c), (r, c+1) and (r+1, c+1) whenever those cells exist"}[extra]
    text = f"How many spanning trees does {shape} have for n = {N}? Give the count modulo 1000000007."
    return text, str(ans)


def q_gcdsum(rng):
    N = rng.randrange(10**8, 10**9)
    Phi = _phi_prefix_factory(N)
    ans = sum((Phi(hi) - Phi(lo - 1)) * q * q for lo, hi, q in L.floor_blocks(N))
    for M in (1, 7, 60):
        if sum(math.gcd(i, j) for i in range(1, M + 1) for j in range(1, M + 1)) != sum(
                (_phi_prefix_factory(M)(hi) - _phi_prefix_factory(M)(lo - 1)) * q * q for lo, hi, q in L.floor_blocks(M)):
            raise Reject()
    text = f"Let N = {N}. Compute the exact sum of gcd(i, j) over all pairs of integers 1 <= i <= N and 1 <= j <= N."
    return text, str(ans)


def _phi_prefix_factory(N):
    Lim = int(N ** (2 / 3)) + 10
    pre = list(itertools.accumulate(L.phi_upto(Lim)))
    pre[0] = 0
    memo = {}

    def S(n):
        if n <= Lim:
            return pre[n]
        if n in memo:
            return memo[n]
        res = n * (n + 1) // 2
        for lo, hi, q in L.floor_blocks(n):
            if hi >= 2:
                res -= (hi - max(lo, 2) + 1) * S(q)
        memo[n] = res
        return res
    return S


Q_FAMILIES = [q_strings, q_subtraction, q_race, q_digits, q_necklace, q_trees, q_gcdsum]


# ============================================================================== G: induction grammar
def _blobs(rng, H, W, sizes, colors):
    for _ in range(200):
        g = [[0] * W for _ in range(H)]
        ok = True
        for size, col in zip(sizes, colors):
            placed = False
            for _ in range(200):
                r, c = rng.randrange(H), rng.randrange(W)
                cells = {(r, c)}
                while len(cells) < size:
                    y, x = rng.choice(sorted(cells))
                    dy, dx = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                    if 0 <= y + dy < H and 0 <= x + dx < W:
                        cells.add((y + dy, x + dx))
                if all(all(not (0 <= y + a < H and 0 <= x + b < W) or g[y + a][x + b] == 0 for a in (-1, 0, 1) for b in (-1, 0, 1)) for y, x in cells):
                    for y, x in cells:
                        g[y][x] = col
                    placed = True
                    break
            if not placed:
                ok = False
                break
        if ok:
            return g
    raise Reject()


def _rot(g, k):
    for _ in range(k % 4):
        g = [list(r) for r in zip(*g[::-1])]
    return g


def g_rule(rng):
    kind = rng.choice(["rank", "gravity", "rays", "crop", "keep_color", "count_bar"])
    if kind == "rank":
        order = rng.choice(["largest", "smallest"])

        def make(r):
            k = r.randint(3, 4)
            return _blobs(r, r.randint(7, 10), r.randint(7, 10), r.sample(range(1, 9), k), [5] * k)

        def f(g):
            objs = sorted(L.g_objects(L.grid(g)), key=lambda o: len(o[1]) * (-1 if order == "largest" else 1))
            out = [[0] * len(g[0]) for _ in g]
            for rank, (_, cells) in enumerate(objs, 1):
                for y, x in cells:
                    out[y][x] = rank
            return out
    elif kind == "gravity":
        direction, after = rng.choice(["down", "up", "left", "right"]), rng.choice([0, 1, 2])

        def make(r):
            H, W = r.randint(6, 9), r.randint(6, 9)
            return [[r.choice([1, 2, 3, 4]) if r.random() < 0.3 else 0 for _ in range(W)] for _ in range(H)]

        def f(g):
            k = {"down": 0, "left": 1, "up": 2, "right": 3}[direction]
            h = _rot(g, k)
            H, W = len(h), len(h[0])
            out = [[0] * W for _ in range(H)]
            for c in range(W):
                col = [h[r][c] for r in range(H) if h[r][c]]
                for i, v in enumerate(reversed(col)):
                    out[H - 1 - i][c] = v
            out = _rot(out, (4 - k) % 4)
            return [row[::-1] for row in out] if after == 1 else (out[::-1] if after == 2 else out)
    elif kind == "rays":
        side = rng.choice(["top", "left", "bottom", "right"])

        def make(r):
            H, W = r.randint(7, 10), r.randint(7, 10)
            g = [[8 if r.random() < 0.12 else 0 for _ in range(W)] for _ in range(H)]
            g[0] = [r.choice([0, 0, 1, 2, 3]) for _ in range(W)]
            return _rot(g, {"top": 0, "right": 1, "bottom": 2, "left": 3}[side])

        def f(g):
            k = {"top": 0, "right": 1, "bottom": 2, "left": 3}[side]
            h = _rot(g, (4 - k) % 4)
            out = [row[:] for row in h]
            for c in range(len(h[0])):
                v = h[0][c]
                if v:
                    rr = 1
                    while rr < len(h) and h[rr][c] == 0:
                        out[rr][c] = v
                        rr += 1
            return _rot(out, k)
    elif kind == "crop":
        which, turn = rng.choice(["largest", "smallest"]), rng.choice([0, 1, 2, 3])

        def make(r):
            k = r.randint(2, 4)
            return _blobs(r, r.randint(7, 10), r.randint(7, 10), r.sample(range(2, 10), k), r.sample([1, 2, 3, 4, 6, 7], k))

        def f(g):
            objs = L.g_objects(L.grid(g))
            col, cells = (max if which == "largest" else min)(objs, key=lambda o: len(o[1]))
            return _rot([list(row) for row in L.g_crop(L.grid(g), cells)], turn)
    elif kind == "keep_color":
        def make(r):
            H, W = r.randint(6, 9), r.randint(6, 9)
            return [[r.choice([0, 0, 1, 2, 3, 4]) for _ in range(W)] for _ in range(H)]

        def f(g):
            cnt = {}
            for row in g:
                for v in row:
                    if v:
                        cnt[v] = cnt.get(v, 0) + 1
            top = max(cnt.values())
            if sum(1 for c in cnt if cnt[c] == top) > 1:
                raise Reject()
            best = max(cnt, key=lambda c: cnt[c])
            return [[v if v == best else 0 for v in row] for row in g]
    else:
        def make(r):
            k = r.randint(4, 7)
            return _blobs(r, r.randint(8, 10), r.randint(8, 10), [r.randint(1, 3) for _ in range(k)], [r.choice([1, 2, 3]) for _ in range(k)])

        def f(g):
            objs = L.g_objects(L.grid(g))
            cnt = {}
            for col, _ in objs:
                cnt[col] = cnt.get(col, 0) + 1
            cols = sorted(cnt)
            width = max(cnt.values())
            return [[c if i < cnt[c] else 0 for i in range(width)] for c in cols]
    return kind, make, f


def make_g(rng, name):
    for _ in range(50):
        kind, make, f = g_rule(rng)
        try:
            ex = [make(rng) for _ in range(4)]
            qs = [make(rng) for _ in range(2)]
            outs = [f(e) for e in ex]
            if any(o == e for o, e in zip(outs, ex)) or len({json.dumps(o) for o in outs}) < 4:
                continue
            return {"name": name, "kind": kind, "examples": [{"input": L.grid_str(e), "output": L.grid_str(o)} for e, o in zip(ex, outs)],
                    "queries": [L.grid_str(q) for q in qs]}, [L.grid_str(f(q)) for q in qs]
        except (Reject, ValueError):
            continue
    raise Reject()


# ============================================================================== C: creative (parameterised)
def make_c(rng):
    n_c = rng.randint(24, 32)
    dim = rng.choice([6, 7])
    marks = rng.randint(24, 32)
    side = rng.randint(15, 24)
    # reference values for normalisation (simple, valid constructions)
    k = math.ceil(math.sqrt(n_c))
    ref_circ = (k * k - (k * k - n_c)) * (1 / (2 * k))
    ref_cap = 2 ** dim
    q = next(p for p in L.primes_upto(60) if p + 1 >= marks)
    ref_gol = L.golomb_from_modular(L.singer_difference_set(q), q * q + q + 1, marks)[-1]
    ref_rect = side + (side - 1)                                  # one full row + one full column
    spec = {"C1": n_c, "C2": dim, "C3": marks, "C4": side}
    ref = {"C1": round(ref_circ, 6), "C2": ref_cap, "C3": ref_gol, "C4": ref_rect}
    text = f"""Four open construction / optimisation problems. Give your best VALID solution to each.

C1. Place {n_c} non-overlapping circles inside the unit square [0,1] x [0,1] to MAXIMISE the sum of their radii. Circles may touch (tolerance 1e-9). Output: a list of {n_c} triples [x, y, r].

C2. Find the LARGEST cap set you can in F_3^{dim}: distinct vectors of length {dim} with entries in {{0,1,2}}, such that no three distinct vectors a, b, c satisfy a + b + c = 0 (mod 3) in every coordinate. Output: the list of vectors.

C3. Choose {marks} distinct non-negative integers (marks) such that all pairwise differences are distinct, MINIMISING the largest mark minus the smallest mark. Output: the sorted list of {marks} integers.

C4. Fill a {side} x {side} grid with 0s and 1s to MAXIMISE the number of 1s, such that no four 1s form the corners of a rectangle (no two rows both have a 1 in the same two columns). Output: a list of {side} strings of {side} characters '0'/'1'.

Final answer: one ```json block, last in your reply: {{"C1": [[x, y, r], ...], "C2": [[...], ...], "C3": [...], "C4": ["0101...", ...]}}
"""
    return text, spec, ref


# ============================================================================== assemble one test
def build(seed: int) -> tuple[dict, dict]:
    rng = random.Random(f"amp-bench-{seed}")
    parts, key = {}, {"seed": seed}
    fams = rng.sample(Q_FAMILIES, 6)
    qtexts = []
    for i, fam in enumerate(fams, 1):
        for _ in range(100):
            try:
                t, a = fam(rng)
                break
            except Reject:
                continue
        else:
            raise RuntimeError(f"family {fam.__name__} kept failing")
        qtexts.append(f"Q{i}. {t}")
        key[f"Q{i}"] = a
        key.setdefault("families", []).append(fam.__name__)
    parts["PART1"] = ("Solve the problems below. Each has one exact answer. Final answer: one ```json block, last in your reply: "
                      '{"Q1": "...", ...} with every answer a JSON string (a decimal integer, or a reduced fraction "a/b" where asked).'
                      ' Also put in that JSON "_conf": {"Q1": 0.9, ...}: for each item, your probability (0 to 1) that the answer is exactly right.\n\n'
                      + "\n\n".join(qtexts) + "\n")
    gl = ["Each puzzle shows grids before and after one hidden transformation (the same rule within a puzzle, different rules in "
          "different puzzles). Grids are rows of digits; 0 is background. Discover each rule and apply it to the two query grids.",
          'Final answer: one ```json block, last in your reply: {"G1": [grid, grid], ...} where each grid is a list of row strings. '
          'Also put in that JSON "_conf": {"G1": 0.9, ...}: for each puzzle, your probability (0 to 1) that both query outputs are exactly right.', ""]
    for i in range(1, 5):
        task, ans = make_g(rng, f"G{i}")
        key[f"G{i}"] = ans
        key.setdefault("g_kinds", []).append(task["kind"])
        gl.append(f"G{i}.")
        for k, e in enumerate(task["examples"], 1):
            gl += [f"Example {k} input:"] + e["input"] + [f"Example {k} output:"] + e["output"] + [""]
        for k, q in enumerate(task["queries"], 1):
            gl += [f"Query {k} input:"] + q + [""]
    parts["PART2"] = "\n".join(gl)
    kv, tf = PR.KVDB, PR.TEXTFMT
    kcmd = PR._kv_cmds(rng, ["set", "get", "del", "incr", "count", "begin", "rollback", "commit", "bad", "get"], (45, 60))
    tin = PR._fmt(rng, [rng.choice(["justify", "center", "right"])], paragraphs=(2, 3), long_words=True)
    key["K1"], key["T1"] = _run_ref(kv.source, kcmd), _run_ref(tf.source, tin)
    parts["PART3"] = ("Two programs are documented below. For each input give the program's exact full output.\n\n" + kv.docs + "\n\nK1. Input (stdin):\n```\n"
                      + kcmd + "```\n\n" + tf.docs + "\n\nT1. Input (stdin):\n```\n" + tin + "```\n\n"
                      'Final answer: one ```json block, last in your reply: {"K1": "...", "T1": "..."} (complete outputs as single strings, lines joined with \\n, keep every space, no trailing newline). '
                      'Also put in that JSON "_conf": {"K1": 0.9, "T1": 0.9}: your probability (0 to 1) that each output is exactly right.\n')
    ctext, cspec, cref = make_c(rng)
    parts["PART4"] = ctext
    key["C_spec"], key["C_ref"] = cspec, cref
    key["I_seeds"] = {t: [f"{seed}-{t}-{k}" for k in range(16)] for t in ("I1", "I2", "I3")}
    key["I_seeds"]["I4"] = [seed * 7 + 1, seed * 7 + 2]
    parts["PART5"] = open(os.path.join(HERE, "PART5_template.txt"), encoding="utf-8").read()
    return parts, key


def _run_ref(src, stdin):
    import subprocess
    r = subprocess.run([sys.executable, "-c", src], input=stdin.encode(), capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().rstrip("\n")


if __name__ == "__main__":
    import argparse
    import hashlib
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", default="tests")
    a = ap.parse_args()
    parts, key = build(a.seed)
    d = os.path.join(a.out, f"T{a.seed}")
    os.makedirs(d, exist_ok=True)
    for name, text in parts.items():
        open(os.path.join(d, f"{name}.txt"), "w", encoding="utf-8").write(text)
    blob = json.dumps(key, sort_keys=True)
    open(os.path.join(d, "key.json"), "w", encoding="utf-8").write(blob)
    print(f"T{a.seed}: written; key sha256 {hashlib.sha256(blob.encode()).hexdigest()}")
