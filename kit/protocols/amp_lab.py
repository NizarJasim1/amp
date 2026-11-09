"""amp_lab.py - the AMP laboratory: tested, general-purpose instruments for discovery, verification and search.

Load it in the code tool (works even if the upload was renamed, e.g. "amp_lab (1).py"):
    import glob, importlib.util, sys
    path = next(p for pat in ('/mnt/user-data/uploads/*amp_lab*.py', '/mnt/**/*amp_lab*.py', '**/*amp_lab*.py')
                for p in glob.glob(pat, recursive=True))
    spec = importlib.util.spec_from_file_location('amp_lab', path); lab = importlib.util.module_from_spec(spec)
    sys.modules['amp_lab'] = lab; spec.loader.exec_module(lab)
    from amp_lab import *
    lab_help()            # one-screen map of everything here

Design rules: exact arithmetic by default (int / Fraction / mod p); every guesser validates on held-out data and
says so; nothing here knows any particular puzzle. Pure standard library; numpy/scipy used only when present.
"""
from __future__ import annotations

import itertools
import math
import random
import time
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache, reduce

P1, P2 = 998244353, 1000000007

# =============================================================================================== evidence
class Ledger:
    """Hypothesis ledger: every claim is code + status. Reason only from SURVIVED/PROVED entries."""

    def __init__(self):
        self.rows = []

    def add(self, name, fn, note=""):
        self.rows.append({"name": name, "fn": fn, "status": "UNTESTED", "tests": 0, "note": note, "counterexample": None})
        return self.rows[-1]

    def test(self, name, cases, truth):
        """cases: iterable of inputs; truth(x) -> correct value. Stops at the first counterexample."""
        row = next(r for r in self.rows if r["name"] == name)
        for x in cases:
            row["tests"] += 1
            try:
                got = row["fn"](x)
            except Exception as e:  # noqa: BLE001
                got = f"error: {e!r}"
            want = truth(x)
            if got != want:
                row["status"], row["counterexample"] = "REFUTED", (x, got, want)
                return row
        row["status"] = "SURVIVED"
        return row

    def show(self):
        for r in self.rows:
            ce = f"  counterexample: {r['counterexample']}" if r["counterexample"] else ""
            print(f"[{r['status']:9}] {r['name']}  ({r['tests']} tests) {r['note']}{ce}")


def crosscheck(fast, slow, inputs, name="fast vs slow"):
    """Two independent methods must agree on every input. Returns (ok, first_disagreement)."""
    n = 0
    for x in inputs:
        n += 1
        a, b = fast(x), slow(x)
        if a != b:
            print(f"{name}: DISAGREE at {x!r}: {a!r} vs {b!r}")
            return False, (x, a, b)
    print(f"{name}: agree on {n} inputs")
    return True, None


def table(f, xs):
    out = []
    for x in xs:
        t = time.time()
        out.append(f(x))
        if time.time() - t > 20:
            print(f"table: stopped after x={x!r} (slow)")
            break
    return out


class Timebox:
    """with Timebox(30) as tb:  while tb.left(): ...   - bounded search loops."""

    def __init__(self, seconds):
        self.end = time.time() + seconds

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def left(self):
        return time.time() < self.end


# =============================================================================================== sequences
def bm_exact(s):
    """Shortest linear recurrence over Q: s[n] = sum c[i] * s[n-1-i]. Returns list of Fractions."""
    s = [Fraction(x) for x in s]
    C, B, L, m, b = [Fraction(1)], [Fraction(1)], 0, 1, Fraction(1)
    for n in range(len(s)):
        d = s[n] + sum(C[i] * s[n - i] for i in range(1, L + 1))
        if d == 0:
            m += 1
            continue
        T, coef = C[:], d / b
        C = C + [Fraction(0)] * (len(B) + m - len(C))
        for i in range(len(B)):
            C[i + m] -= coef * B[i]
        if 2 * L <= n:
            L, B, b, m = n + 1 - L, T, d, 1
        else:
            m += 1
    return [-x for x in C[1:L + 1]]


def bm_mod(s, p=P1):
    s = [x % p for x in s]
    C, B, L, m, b = [1], [1], 0, 1, 1
    for n in range(len(s)):
        d = s[n]
        for i in range(1, L + 1):
            d = (d + C[i] * s[n - i]) % p
        if d == 0:
            m += 1
            continue
        T, coef = C[:], d * pow(b, p - 2, p) % p
        C = C + [0] * (len(B) + m - len(C))
        for i in range(len(B)):
            C[i + m] = (C[i + m] - coef * B[i]) % p
        if 2 * L <= n:
            L, B, b, m = n + 1 - L, T, d, 1
        else:
            m += 1
    return [(-x) % p for x in C[1:L + 1]]


def guess_linear(s, holdout=3):
    """Linear recurrence with constant coefficients fitted on s[:-holdout] and checked on the rest."""
    if len(s) < 2 * holdout + 2:
        return None
    fit, rest = s[:-holdout], s[-holdout:]
    c = bm_exact(fit)
    if 2 * len(c) + 1 > len(fit):
        return None                       # not over-determined: no evidence
    seq = list(s[:len(fit)])
    for _ in rest:
        seq.append(sum(ci * seq[-1 - i] for i, ci in enumerate(c)))
    if seq[len(fit):] != [Fraction(x) for x in rest]:
        return None
    return {"kind": "linear", "coeffs": c, "order": len(c), "checked_on": len(rest), "start_index": 0}


def guess_poly(s, holdout=3, max_degree=12):
    if len(s) < holdout + 2:
        return None
    fit = s[:-holdout]
    for deg in range(0, min(max_degree, len(fit) - 2) + 1):
        f = poly_fit(fit[:deg + 1])
        if all(f(i) == s[i] for i in range(len(s))):
            if deg + 2 > len(fit):
                return None
            return {"kind": "polynomial", "degree": deg, "f": f, "checked_on": len(s) - deg - 1}
    return None


def poly_fit(ys):
    """Exact polynomial through (0, ys[0]), (1, ys[1]), ... (Newton form). Returns f(n) -> Fraction."""
    diffs, row = [], [Fraction(y) for y in ys]
    while row:
        diffs.append(row[0])
        row = [row[i + 1] - row[i] for i in range(len(row) - 1)]

    def f(n):
        tot, term = Fraction(0), Fraction(1)
        for k, d in enumerate(diffs):
            tot += d * term
            term = term * (n - k) / (k + 1)
        return tot
    return f


def find_period(seq, max_pre=500, max_per=2000):
    """Smallest (pre, per) with seq[i] == seq[i+per] for all i >= pre in the data (needs >= 2 periods of data)."""
    n = len(seq)
    for per in range(1, max_per + 1):
        if 2 * per > n:
            break
        pre = 0
        for i in range(n - per - 1, -1, -1):          # longest periodic tail for this period
            if seq[i] != seq[i + per]:
                pre = i + 1
                break
        if pre <= max_pre and n - pre >= 2 * per:
            return pre, per
    return None


def periodic_count(pred_seq, pre, per, N, start=1):
    """How many i in [start, N] have pred_seq[i] True, for a sequence periodic (pre, per) - data must cover pre+per."""
    if N < start:
        return 0
    lim = max(pre, start)
    if N < lim + per:
        return sum(1 for i in range(start, N + 1) if pred_seq[i])
    base = sum(1 for i in range(start, lim) if pred_seq[i])
    cyc = sum(1 for i in range(lim, lim + per) if pred_seq[i])
    full, rem = divmod(N - lim + 1, per)
    return base + full * cyc + sum(1 for i in range(lim, lim + rem) if pred_seq[i])


def guess_quasipoly(s, max_period=12, holdout=2):
    """s[n] = polynomial in n depending on n mod q (quasi-polynomial)."""
    for q in range(1, max_period + 1):
        fs, ok = [], True
        for r in range(q):
            sub = s[r::q]
            g = guess_poly(sub, holdout=holdout)
            if g is None:
                ok = False
                break
            fs.append(g["f"])
        if ok:
            return {"kind": "quasi-polynomial", "period": q, "f": lambda n, fs=fs, q=q: fs[n % q](n // q)}
    return None


def _nullspace_frac(rows, ncols):
    A = [[Fraction(x) for x in r] for r in rows]
    m, piv, r = len(A), [], 0
    for c in range(ncols):
        pr = next((i for i in range(r, m) if A[i][c] != 0), None)
        if pr is None:
            continue
        A[r], A[pr] = A[pr], A[r]
        pv = A[r][c]
        A[r] = [x / pv for x in A[r]]
        for i in range(m):
            if i != r and A[i][c] != 0:
                f = A[i][c]
                A[i] = [x - f * y for x, y in zip(A[i], A[r])]
        piv.append(c)
        r += 1
    free = [c for c in range(ncols) if c not in piv]
    basis = []
    for fcol in free:
        v = [Fraction(0)] * ncols
        v[fcol] = Fraction(1)
        for i, c in enumerate(piv):
            v[c] = -A[i][fcol]
        basis.append(v)
    return basis


def guess_precursive(s, max_order=4, max_degree=3, holdout=3, offset=0):
    """sum_{j=0..order} q_j(n) s[n-j] = 0 with polynomials q_j of degree <= degree, exact over Q.
    n is the true index (s[0] has index `offset`). Fitted on s[:-holdout], verified on the held-out terms."""
    fit = s[:-holdout]
    for total in range(2, max_order + max_degree + 2):
        for order in range(1, max_order + 1):
            degree = total - order
            if degree < 0 or degree > max_degree:
                continue
            unknowns = (order + 1) * (degree + 1)
            rows = [[(n + offset) ** d * fit[n - j] for j in range(order + 1) for d in range(degree + 1)]
                    for n in range(order, len(fit))]
            if len(rows) < unknowns + 2:
                continue
            basis = _nullspace_frac(rows, unknowns)
            if len(basis) != 1:
                continue
            v = basis[0]
            q = [v[j * (degree + 1):(j + 1) * (degree + 1)] for j in range(order + 1)]
            ev = lambda poly, n: sum(c * n ** d for d, c in enumerate(poly))  # noqa: E731
            ok = True
            for n in range(len(fit), len(s)):
                if ev(q[0], n + offset) == 0:
                    ok = False
                    break
                pred = -sum(ev(q[j], n + offset) * s[n - j] for j in range(1, order + 1)) / ev(q[0], n + offset)
                if pred != s[n]:
                    ok = False
                    break
            if ok:
                return {"kind": "P-recursive", "order": order, "degree": degree, "q": q, "offset": offset, "checked_on": holdout}
    return None


def identify(s, offset=0, holdout=3, verbose=True):
    """Run every guesser; return verified hypotheses, simplest first. s[0] corresponds to index `offset`."""
    found = []
    for g in (lambda: guess_poly(s, holdout), lambda: guess_linear(s, holdout),
              lambda: guess_quasipoly(s), lambda: guess_precursive(s, holdout=holdout, offset=offset)):
        try:
            h = g()
        except (ZeroDivisionError, ValueError):
            h = None
        if h:
            found.append(h)
    per = find_period(list(s), max_pre=len(s) // 3, max_per=len(s) // 3)
    if per:
        found.append({"kind": "eventually periodic", "pre": per[0], "period": per[1]})
    if verbose:
        if not found:
            print("identify: nothing verified. Try more terms, transforms (differences, ratios, s[n]/n!, log), or a 2nd parameter.")
        for h in found:
            print("identify:", {k: (v if k not in ("f",) else "<fn>") for k, v in h.items()})
    return found


def lin_nth(coeffs, init, n, mod=None):
    """n-th term (0-based) of s[k] = sum c[i] s[k-1-i]; exact (Fractions/ints) if mod is None else mod p."""
    k = len(coeffs)
    if n < len(init):
        return init[n] if mod is None else init[n] % mod
    if mod is None:
        seq = list(init[:k])
        for _ in range(n - k + 1):
            seq.append(sum(c * seq[-1 - i] for i, c in enumerate(coeffs)))
            seq = seq[-k:]
        return seq[-1]
    cs = [int(Fraction(c).numerator * pow(Fraction(c).denominator, -1, mod)) % mod for c in coeffs]
    M = [[0] * k for _ in range(k)]
    M[0] = cs
    for i in range(1, k):
        M[i][i - 1] = 1
    R = matpow_mod(M, n - (k - 1), mod)
    state = [int(init[k - 1 - i]) % mod for i in range(k)]
    return sum(R[0][j] * state[j] for j in range(k)) % mod


def prec_nth(h, init, n, mod):
    """Iterate a P-recursive hypothesis (from guess_precursive) up to index n, mod a prime. O(n * order)."""
    q, order, off = h["q"], h["order"], h["offset"]
    qm = [[int(Fraction(c).numerator * pow(Fraction(c).denominator, -1, mod)) % mod for c in poly] for poly in q]
    ev = lambda poly, x: sum(c * pow(x, d, mod) for d, c in enumerate(poly)) % mod  # noqa: E731
    vals = [int(v) % mod for v in init]
    for idx in range(len(vals) + off, n + 1):
        lead = ev(qm[0], idx)
        if lead == 0:
            raise ZeroDivisionError(f"leading coefficient vanishes at n={idx} mod p; use another prime")
        nxt = -sum(ev(qm[j], idx) * vals[-j] for j in range(1, order + 1)) * pow(lead, mod - 2, mod) % mod
        vals.append(nxt)
        if len(vals) > order + 1:
            vals.pop(0)
    return vals[-1]


def features(s):
    """Quick look: differences, ratios, gcd, factorisations, residues. Print, then think."""
    print("terms      :", s)
    d = list(s)
    for k in range(1, 4):
        d = [d[i + 1] - d[i] for i in range(len(d) - 1)]
        print(f"diff^{k}     :", d[:15])
    rat = [round(s[i + 1] / s[i], 5) for i in range(len(s) - 1) if s[i]]
    print("ratios     :", rat[-8:])
    print("gcd        :", reduce(math.gcd, [abs(x) for x in s if x], 0))
    print("factorised :", [factorize(abs(x)) if 1 < abs(x) < 10**18 else x for x in s[:12]])
    for q in (2, 3, 4, 5, 7):
        print(f"mod {q}      :", [x % q for x in s[:24]])


# =============================================================================================== number theory
def primes_upto(n):
    if n < 2:
        return []
    sieve = bytearray([1]) * (n + 1)
    sieve[0:2] = b"\x00\x00"
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i::i] = bytearray(len(range(i * i, n + 1, i)))
    return [i for i in range(n + 1) if sieve[i]]


def phi_upto(n):
    ph = list(range(n + 1))
    for i in range(2, n + 1):
        if ph[i] == i:
            for j in range(i, n + 1, i):
                ph[j] -= ph[j] // i
    return ph


def mu_upto(n):
    mu, isp, primes = [1] * (n + 1), [True] * (n + 1), []
    if n >= 0:
        mu[0] = 0
    for i in range(2, n + 1):
        if isp[i]:
            primes.append(i)
            mu[i] = -1
        for p in primes:
            if i * p > n:
                break
            isp[i * p] = False
            if i % p == 0:
                mu[i * p] = 0
                break
            mu[i * p] = -mu[i]
    return mu


def floor_blocks(N):
    """Yield (lo, hi, q) with N // k == q for every k in [lo, hi]; O(sqrt N) blocks."""
    k = 1
    while k <= N:
        q = N // k
        hi = N // q
        yield k, hi, q
        k = hi + 1


def du_sieve(N, small_prefix, g_prefix, h_prefix):
    """Prefix sum F(N) of f, given f*g = h (Dirichlet), g(1)=1, prefix sums of g and h, and F for small n.
    F(n) = H(n) - sum_{k=2..n} g(k) F(n//k). small_prefix: list F[0..L] (L ~ N^(2/3))."""
    L = len(small_prefix) - 1
    memo = {}

    def F(n):
        if n <= L:
            return small_prefix[n]
        if n in memo:
            return memo[n]
        res = h_prefix(n)
        for lo, hi, q in floor_blocks(n):
            if hi < 2:
                continue
            lo = max(lo, 2)
            res -= (g_prefix(hi) - g_prefix(lo - 1)) * F(q)
        memo[n] = res
        return res
    return F(N)


def totient_sum(N):
    L = int(N ** (2 / 3)) + 10
    ph = phi_upto(L)
    pre = list(itertools.accumulate(ph))
    pre[0] = 0
    return du_sieve(N, pre, lambda n: n, lambda n: n * (n + 1) // 2)


def mertens(N):
    L = int(N ** (2 / 3)) + 10
    mu = mu_upto(L)
    pre = list(itertools.accumulate(mu))
    return du_sieve(N, pre, lambda n: n, lambda n: 1 if n >= 1 else 0)


def is_probable_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def factorize(n):
    """Prime factorisation {p: e} (Pollard rho + Miller-Rabin)."""
    if n < 1:
        raise ValueError("n >= 1")
    out = Counter()

    def rho(n):
        if n % 2 == 0:
            return 2
        rng = random.Random(n)
        while True:
            x, c = rng.randrange(2, n), rng.randrange(1, n)
            y, d = x, 1
            while d == 1:
                x = (x * x + c) % n
                y = (y * y + c) % n
                y = (y * y + c) % n
                d = math.gcd(abs(x - y), n)
            if d != n:
                return d

    def go(n):
        if n == 1:
            return
        if is_probable_prime(n):
            out[n] += 1
            return
        for p in (2, 3, 5, 7, 11, 13):
            if n % p == 0:
                out[p] += 1
                go(n // p)
                return
        d = rho(n)
        go(d)
        go(n // d)
    go(n)
    return dict(sorted(out.items()))


def divisors(n):
    ds = [1]
    for p, e in factorize(n).items():
        ds = [d * p ** k for d in ds for k in range(e + 1)]
    return sorted(ds)


def euler_phi(n):
    r = n
    for p in factorize(n):
        r -= r // p
    return r


def crt(rems, mods):
    x, m = 0, 1
    for r, mi in zip(rems, mods):
        g = math.gcd(m, mi)
        if (r - x) % g:
            return None
        l = m // g * mi
        x = (x + (r - x) // g * pow(m // g, -1, mi // g) % (mi // g) * m) % l
        m = l
    return x, m


def binom_mod(n, k, p):
    """C(n, k) mod prime p (Lucas for big n)."""
    if k < 0 or k > n:
        return 0
    res = 1
    while n or k:
        a, b = n % p, k % p
        if b > a:
            return 0
        num = den = 1
        for i in range(b):
            num = num * (a - i) % p
            den = den * (i + 1) % p
        res = res * num * pow(den, p - 2, p) % p
        n //= p
        k //= p
    return res


# =============================================================================================== linear algebra
def matmul_mod(A, B, m):
    Bt = list(zip(*B))
    return [[sum(a * b for a, b in zip(row, col)) % m for col in Bt] for row in A]


def matpow_mod(M, e, m):
    R = [[int(i == j) for j in range(len(M))] for i in range(len(M))]
    while e:
        if e & 1:
            R = matmul_mod(R, M, m)
        M = matmul_mod(M, M, m)
        e >>= 1
    return R


def det_exact(M):
    """Integer determinant (Bareiss, exact)."""
    M = [list(r) for r in M]
    n = len(M)
    if n == 0:
        return 1
    sign, prev = 1, 1
    for k in range(n - 1):
        if M[k][k] == 0:
            sw = next((r for r in range(k + 1, n) if M[r][k] != 0), None)
            if sw is None:
                return 0
            M[k], M[sw] = M[sw], M[k]
            sign = -sign
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                M[i][j] = (M[i][j] * M[k][k] - M[i][k] * M[k][j]) // prev
        prev = M[k][k]
    return sign * M[n - 1][n - 1]


def solve_exact(A, b):
    """Solve A x = b over Q (Fractions). Raises if singular."""
    n = len(A)
    M = [[Fraction(x) for x in row] + [Fraction(bi)] for row, bi in zip(A, b)]
    for c in range(n):
        pr = next(r for r in range(c, n) if M[r][c] != 0)
        M[c], M[pr] = M[pr], M[c]
        pv = M[c][c]
        M[c] = [x / pv for x in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0:
                f = M[r][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]


def markov_absorb(states, transitions, value):
    """Exact expected/absorption values. transitions(s) -> [(prob, s2)]; value(s) -> number for absorbing
    states, None for transient ones. Returns {s: E[value at absorption | start s]} over transient states."""
    trans = [s for s in states if value(s) is None]
    idx = {s: i for i, s in enumerate(trans)}
    A = [[Fraction(0)] * len(trans) for _ in trans]
    b = [Fraction(0)] * len(trans)
    for s in trans:
        i = idx[s]
        A[i][i] += 1
        for pr, t in transitions(s):
            v = value(t)
            if v is None:
                A[i][idx[t]] -= Fraction(pr)
            else:
                b[i] += Fraction(pr) * v
    x = solve_exact(A, b)
    return {s: x[idx[s]] for s in trans}


# =============================================================================================== DP / automata / games
def transfer_count(states, step, n, start_weights, end_weight=lambda s: 1, mod=None):
    """Number (weighted) of length-n walks in a state machine. step(s) -> [(s2, multiplicity)].
    Exact for mod=None (repeated multiplication), matrix power mod p otherwise."""
    idx = {s: i for i, s in enumerate(states)}
    k = len(states)
    M = [[0] * k for _ in range(k)]
    for s in states:
        for t, mult in step(s):
            M[idx[s]][idx[t]] += mult
    v = [start_weights(s) for s in states]
    if mod is None:
        for _ in range(n):
            v = [sum(v[i] * M[i][j] for i in range(k)) for j in range(k)]
        return sum(v[j] * end_weight(states[j]) for j in range(k))
    R = matpow_mod([[x % mod for x in row] for row in M], n, mod)
    return sum(v[i] * R[i][j] * end_weight(states[j]) for i in range(k) for j in range(k)) % mod


def digit_dp(N, base, start, step, accept):
    """Count x in [0, N] whose digits (most significant first) drive a deterministic automaton:
    step(state, digit, is_leading_zero) -> state or None (reject); accept(state) -> bool."""
    digits = []
    x = N
    while True:
        digits.append(x % base)
        x //= base
        if x == 0:
            break
    digits.reverse()

    @lru_cache(None)
    def go(i, state, tight, leading):
        if i == len(digits):
            return 1 if accept(state) else 0
        lim = digits[i] if tight else base - 1
        tot = 0
        for d in range(lim + 1):
            lead = leading and d == 0
            ns = step(state, d, lead)
            if ns is None:
                continue
            tot += go(i + 1, ns, tight and d == lim, lead)
        return tot
    return go(0, start, True, True)


def mex(values):
    s = set(values)
    m = 0
    while m in s:
        m += 1
    return m


def grundy_table(n_max, options):
    """g[n] for single positions 0..n_max; options(n) -> list of tuples of sub-positions (xor-sum)."""
    g = [0] * (n_max + 1)
    for n in range(n_max + 1):
        g[n] = mex(reduce(lambda a, b: a ^ b, (g[x] for x in opt), 0) for opt in options(n))
    return g


def brute_win(position, moves):
    """Ground truth for small impartial games without Grundy theory: position -> True if player to move wins.
    moves(position) -> iterable of next positions (hashable)."""
    @lru_cache(None)
    def win(pos):
        return any(not win(q) for q in moves(pos))
    return win(position)


# =============================================================================================== program search
def search_programs(examples, primitives, max_depth=3, max_results=20, timeout=60):
    """Enumerate compositions f_k(...f_1(x)) of primitives (name, fn) consistent with ALL examples.
    Parameterised primitives: pass them pre-instantiated, e.g. [("rot%d" % k, partial(rot, k=k)) ...].
    Returns list of (names, fn), shortest first. Observational-equivalence pruning keeps it fast."""
    deadline = time.time() + timeout
    inputs = [x for x, _ in examples]
    targets = [y for _, y in examples]

    def key(vals):
        return repr(vals)

    frontier = [((), lambda x: x, inputs)]
    seen = {key(inputs)}
    results = []
    for depth in range(1, max_depth + 1):
        nxt = []
        for names, fn, vals in frontier:
            for pname, p in primitives:
                if time.time() > deadline:
                    return results
                try:
                    out = [p(v) for v in vals]
                except Exception:  # noqa: BLE001
                    continue
                if out == targets:
                    results.append((names + (pname,), (lambda f, g: (lambda x: g(f(x))))(fn, p)))
                    if len(results) >= max_results:
                        return results
                k = key(out)
                if k not in seen:
                    seen.add(k)
                    nxt.append((names + (pname,), (lambda f, g: (lambda x: g(f(x))))(fn, p), out))
        frontier = nxt
    return results


# ---- generic list primitives
def _lp():
    ps = [("reverse", lambda x: x[::-1]), ("sort", sorted), ("sort_desc", lambda x: sorted(x, reverse=True)),
          ("dedupe", lambda x: list(dict.fromkeys(x))), ("abs", lambda x: [abs(v) for v in x]),
          ("neg", lambda x: [-v for v in x]), ("prefix_sum", lambda x: list(itertools.accumulate(x))),
          ("diff", lambda x: [x[i + 1] - x[i] for i in range(len(x) - 1)]),
          ("even_pos", lambda x: x[::2]), ("odd_pos", lambda x: x[1::2]),
          ("running_max", lambda x: list(itertools.accumulate(x, max))),
          ("running_min", lambda x: list(itertools.accumulate(x, min))),
          ("drop_first", lambda x: x[1:]), ("drop_last", lambda x: x[:-1]),
          ("square", lambda x: [v * v for v in x]), ("cumprod_sign", lambda x: [(v > 0) - (v < 0) for v in x])]
    for k in range(1, 5):
        ps.append((f"rotl{k}", lambda x, k=k: x[k % len(x):] + x[:k % len(x)] if x else []))
    for k in range(2, 8):
        ps.append((f"keep_div{k}", lambda x, k=k: [v for v in x if v % k == 0]))
        ps.append((f"mod{k}", lambda x, k=k: [v % k for v in x]))
        ps.append((f"sort_by_mod{k}", lambda x, k=k: sorted(x, key=lambda v: v % k)))
    for t in range(-5, 6):
        ps.append((f"add{t}", lambda x, t=t: [v + t for v in x]))
        ps.append((f"keep_gt{t}", lambda x, t=t: [v for v in x if v > t]))
    for a in range(2, 6):
        ps.append((f"mul{a}", lambda x, a=a: [v * a for v in x]))
    return ps


LIST_PRIMS = _lp()


# ---- generic grid primitives (grid = tuple of tuples of ints)
def grid(rows):
    return tuple(tuple(int(ch) for ch in r) if isinstance(r, str) else tuple(r) for r in rows)


def grid_str(g):
    return ["".join(map(str, r)) for r in g]


def g_objects(g, diagonal=False, by_color=True):
    """Connected components of non-zero cells: list of (color, [(r, c), ...])."""
    H, W = len(g), len(g[0]) if g else 0
    seen, objs = set(), []
    nb = [(1, 0), (-1, 0), (0, 1), (0, -1)] + ([(1, 1), (1, -1), (-1, 1), (-1, -1)] if diagonal else [])
    for r in range(H):
        for c in range(W):
            if g[r][c] and (r, c) not in seen:
                col, stack, cells = g[r][c], [(r, c)], []
                seen.add((r, c))
                while stack:
                    y, x = stack.pop()
                    cells.append((y, x))
                    for dy, dx in nb:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < H and 0 <= nx < W and (ny, nx) not in seen and g[ny][nx] and (not by_color or g[ny][nx] == col):
                            seen.add((ny, nx))
                            stack.append((ny, nx))
                objs.append((col, sorted(cells)))
    return objs


def g_crop(g, cells=None):
    cells = cells or [(r, c) for r, row in enumerate(g) for c, v in enumerate(row) if v]
    if not cells:
        return ()
    ys, xs = [y for y, _ in cells], [x for _, x in cells]
    keep = set(cells)
    return tuple(tuple(g[y][x] if (y, x) in keep else 0 for x in range(min(xs), max(xs) + 1)) for y in range(min(ys), max(ys) + 1))


GRID_PRIMS = [
    ("identity", lambda g: g),
    ("rot90", lambda g: tuple(zip(*g[::-1]))), ("rot180", lambda g: tuple(r[::-1] for r in g[::-1])),
    ("rot270", lambda g: tuple(zip(*g))[::-1]), ("flip_lr", lambda g: tuple(r[::-1] for r in g)),
    ("flip_ud", lambda g: g[::-1]), ("transpose", lambda g: tuple(zip(*g))),
    ("crop_nonzero", lambda g: g_crop(g)),
]


def learn_color_map(examples):
    """If every output cell is a fixed function of the input cell colour (same shape), return that map."""
    mp = {}
    for x, y in examples:
        if len(x) != len(y) or any(len(a) != len(b) for a, b in zip(x, y)):
            return None
        for ra, rb in zip(x, y):
            for a, b in zip(ra, rb):
                if mp.setdefault(a, b) != b:
                    return None
    return mp


# =============================================================================================== search / optimisation
def anneal(init, neighbor, score, iters=200000, t0=1.0, t1=1e-3, seed=0, maximize=True, timebox=None):
    """Simulated annealing. neighbor(state, rng) -> new state; score(state) -> float (None = invalid)."""
    rng = random.Random(seed)
    sign = 1 if maximize else -1
    cur, cs = init, score(init)
    best, bs = cur, cs
    end = time.time() + timebox if timebox else None
    for i in range(iters):
        if end and time.time() > end:
            break
        t = t0 * (t1 / t0) ** (i / max(1, iters - 1))
        cand = neighbor(cur, rng)
        s = score(cand)
        if s is None:
            continue
        if cs is None or sign * (s - cs) >= 0 or rng.random() < math.exp(sign * (s - cs) / t):
            cur, cs = cand, s
            if bs is None or sign * (cs - bs) > 0:
                best, bs = cur, cs
    return best, bs


def continuous_maximize(f, x0, constraints=(), bounds=None, restarts=8, seed=0, jitter=0.05):
    """Maximise f(x) s.t. every g(x) >= 0. Uses scipy SLSQP when available (multi-start), otherwise a
    penalty method with random-direction hill climbing. Returns (x, f(x)) for the best FEASIBLE x found."""
    rng = random.Random(seed)
    try:
        import numpy as np
        from scipy.optimize import minimize
        best = (None, -math.inf)
        for r in range(restarts):
            x = np.array(x0, dtype=float) + (0 if r == 0 else np.array([rng.gauss(0, jitter) for _ in x0]))
            res = minimize(lambda v: -f(v), x, method="SLSQP", bounds=bounds,
                           constraints=[{"type": "ineq", "fun": g} for g in constraints],
                           options={"maxiter": 2000, "ftol": 1e-12})
            v = res.x
            if all(g(v) >= -1e-9 for g in constraints) and f(v) > best[1]:
                best = (list(v), f(v))
        return best
    except ImportError:
        pass
    x = list(x0)

    def pen(v):
        return f(v) - 1e4 * sum(min(0.0, g(v)) ** 2 for g in constraints)
    best = (None, -math.inf)
    for r in range(restarts):
        cur = [a + (0 if r == 0 else rng.gauss(0, jitter)) for a in x]
        val, step = pen(cur), 0.05
        for _ in range(20000):
            cand = [a + rng.gauss(0, step) for a in cur]
            if bounds:
                cand = [min(max(c, lo), hi) for c, (lo, hi) in zip(cand, bounds)]
            v = pen(cand)
            if v > val:
                cur, val = cand, v
            else:
                step *= 0.9995
            if step < 1e-7:
                break
        if all(g(cur) >= -1e-9 for g in constraints) and f(cur) > best[1]:
            best = (cur, f(cur))
    return best


# =============================================================================================== constructions (classical)
def _poly_mulmod(a, b, f, q):
    res = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            res[i + j] = (res[i + j] + x * y) % q
    deg = len(f) - 1
    for i in range(len(res) - 1, deg - 1, -1):
        c = res[i]
        if c:
            for j in range(deg + 1):
                res[i - deg + j] = (res[i - deg + j] - c * f[j]) % q
    return (res + [0] * deg)[:deg]


def singer_difference_set(q):
    """Planar difference set of size q+1 in Z_{q^2+q+1} for a PRIME q (Singer construction via GF(q^3))."""
    if not is_probable_prime(q):
        raise ValueError("this implementation needs a prime q")
    order = q ** 3 - 1
    fac = factorize(order)
    for a, b, c in itertools.product(range(q), repeat=3):
        f = [c, b, a, 1]                         # x^3 + a x^2 + b x + c  (low -> high)
        if c == 0 or any((r ** 3 + a * r * r + b * r + c) % q == 0 for r in range(q)):
            continue                             # reducible cubic (has a root)

        def xpow(e):
            res, base = [1, 0, 0], [0, 1, 0]
            while e:
                if e & 1:
                    res = _poly_mulmod(res, base, f, q)
                base = _poly_mulmod(base, base, f, q)
                e >>= 1
            return res
        if all(xpow(order // p) != [1, 0, 0] for p in fac):
            v = q * q + q + 1
            D, cur = set(), [1, 0, 0]
            for i in range(order):
                if cur[2] == 0:
                    D.add(i % v)
                cur = _poly_mulmod(cur, [0, 1, 0], f, q)
            return sorted(D)
    raise RuntimeError("no primitive cubic found")


def golomb_from_modular(D, v, n=None):
    """Best (shortest) linear Golomb ruler with n marks taken from affine images {t*d + s mod v} of a modular
    ruler D (all differences distinct mod v). Returns sorted marks starting at 0."""
    n = n or len(D)
    best = None
    for t in range(1, v):
        if math.gcd(t, v) != 1:
            continue
        pts = sorted((t * d) % v for d in D)
        k = len(pts)
        for i in range(k):                       # cut the circle at each gap
            seq = pts[i:] + [p + v for p in pts[:i]]
            for j in range(0, k - n + 1):        # best window of n consecutive marks
                w = seq[j:j + n]
                L = w[-1] - w[0]
                if best is None or L < best[0]:
                    best = (L, [x - w[0] for x in w])
    return best[1]


def is_golomb(marks):
    d = [b - a for i, a in enumerate(marks) for b in marks[i + 1:]]
    return len(set(d)) == len(d)


def no3ap_permutation(n):
    """Permutation of 1..n with no 3-term arithmetic progression as a subsequence (even/odd recursion)."""
    def rec(xs):
        if len(xs) <= 2:
            return xs
        return rec(xs[0::2]) + rec(xs[1::2])
    return rec(list(range(1, n + 1)))


def salem_spencer(n):
    """3-AP-free subset of [0, n): numbers whose base-3 digits are all 0 or 1."""
    out = []
    for x in range(n):
        y, ok = x, True
        while y:
            if y % 3 == 2:
                ok = False
                break
            y //= 3
        if ok:
            out.append(x)
    return out


def welch_costas(p):
    """Costas array of order p-1 from a primitive root g mod prime p: row i -> g^i mod p (1-based)."""
    fac = factorize(p - 1)
    g = next(a for a in range(2, p) if all(pow(a, (p - 1) // f, p) != 1 for f in fac))
    return [pow(g, i, p) for i in range(1, p)]


def cap_product(A, B):
    """Product of cap sets in F_3^a and F_3^b is a cap set in F_3^(a+b) (no three collinear points)."""
    return [tuple(a) + tuple(b) for a in A for b in B]


def is_cap(vectors):
    s = set(map(tuple, vectors))
    if len(s) != len(vectors):
        return False
    vs = list(s)
    for i, a in enumerate(vs):
        for b in vs[i + 1:]:
            c = tuple((-x - y) % 3 for x, y in zip(a, b))
            if c in s and c != a and c != b:
                return False
    return True


def lab_help():
    print(__doc__.split("\n\n")[0])
    print("""
EVIDENCE      Ledger (add/test/show hypotheses), crosscheck(fast, slow, inputs), table(f, xs), Timebox(seconds)
SEQUENCES     identify(s) -> verified hypotheses | guess_linear, guess_poly, guess_quasipoly, guess_precursive,
              find_period, periodic_count, poly_fit, bm_exact, bm_mod, lin_nth(c, init, n, mod), prec_nth(h, init, n, p),
              features(s)
NUMBER THEORY primes_upto, phi_upto, mu_upto, floor_blocks(N), du_sieve, totient_sum(N), mertens(N), factorize,
              divisors, euler_phi, is_probable_prime, crt, binom_mod
LINEAR ALG.   matmul_mod, matpow_mod, det_exact (Bareiss), solve_exact (Fractions), markov_absorb(states, trans, value)
DP / GAMES    transfer_count(states, step, n, start, end, mod), digit_dp(N, base, start, step, accept), mex,
              grundy_table(n_max, options), brute_win(position, moves)
PROGRAMS      search_programs(examples, primitives, max_depth), LIST_PRIMS, GRID_PRIMS, grid(), grid_str(),
              g_objects, g_crop, learn_color_map
SEARCH        anneal(init, neighbor, score, ...), continuous_maximize(f, x0, constraints, bounds)
CONSTRUCTIONS singer_difference_set(q), golomb_from_modular(D, v, n), is_golomb, no3ap_permutation, salem_spencer,
              welch_costas(p), cap_product, is_cap
IDEAS (v4)    edge_cells(assumptions, k) -> operator x assumption cells; projections(k) -> cross-domain patterns
              (PATTERN_BANK); IdeaPool: add / attempt_kill / confirm_prediction / top / elites / parents / plateau / show
CRITIC (v6.5)  pkt = pool.packet(brief, author="me") -> paste pkt["prompt"] into a FRESH chat / other model
              (runner: pkt["runner"] as tool code); pool.ingest(reply, source="chat:fresh") -> pool.pending_attacks()
              -> pool.answer_attack(id, n, test); pool.ready() = only externally-reviewed survivors; pool.independence()
DATA (v6.5)   ev = Evidence(): source(name, text, provenance) / source_file(path) seal raw material (sha256 in chain);
              add(summary, provenance, src=, quote=) -> L2 verified only if the quote is IN the sealed source, L1 declared,
              L0 self; ev.gate() needs >=1 verified fact; pool.attach(ev); pool.cite(ev, id, *ns, why=, stance='pro'/'contra');
              pool.ready() = verified-grounded + no pending contra; pool.pending_contra() -> pool.answer_contra(id, k, test);
              strength = distinct sealed sources; pool.grounding(); ground_tags(idea) feeds the Outcomes ledger
OUTCOMES(6.5) oc = Outcomes(); oc.ingest() (grader verdicts, R2); sid = oc.ship(pool, id, p) (ready ideas only; gate=False
              = UNGATED); oc.resolve(sid, held, provenance, ev=, fact=) R2 verified / R1 declared / R0 self, only a
              stronger source replaces a verdict; oc.report(): reality_blind_spot (observed + worst case), calibration,
              adjust(p), pipeline() (do the gates pay off?), rates('op:'/'dom:'); edge_cells / projections /
              pool.parents(outcomes=oc) give their extra picks to generators reality rewarded
PLAN (v6.5)   pl = Plan(goal); pl.premortem(cause, signal=metric) x3+; pl.phase(name, deliverable, budget,
              kill_if=["m < x"], continue_if=["m >= y"], fallback=None); pl.start() (refuses unwatched causes);
              pl.report(name, metrics, spent) -> KILL/PIVOT/CONTINUE/HOLD; pl.amend_phase (no loosening);
              pl.packet()/ingest()/watch(n, metric, phase, rule) for an outside critic; pl.status(); Plan.load(path)
MEMORY (v4)   Memory(): record(tags, representation, outcome), suggest(tags), predict(claim, p) / resolve / calibration
CONTROL (v6)  mem.ingest() graded feedback; mem.table(); ctl = Controller(mem): add(id, kind, value) / next() /
              attempt(id, reached_E) / done() / ledger() -> "_ledger" for the answer JSON; calibrated_p(mem, kind, E)
ATTEST (v6.1) reg = Registry(mem): check(item, cls, fn, inputs, kind, resources) runs + attests a verification method;
              constrain(item) -> binding design for the next check (compliance is checked automatically);
              answer / reason / status(item) / next() / ledger() / certificate(); verify_certificate(cert)
ORACLE(v6.3) reg.oracle(item, predict, holdout, provenance='given'/'live'/'validator'/'self', kind): external truth
              (given/live/validator) can reach E3; a self-written reference caps at E2. Correlation-aware risk.
              check(..., source='model:B') for cross-source; synthesize_verify (None if no rule fits train);
              StepChain(item, mem); oracle_rich(kind) = {G,P,C} only (I,J are not oracle-rich from the solver side)
""")


# =============================================================================================== idea engine (v4)
# Generation is made WIDE by combinatorics done in code (cheap), not by long model prose (expensive):
# the model writes short assumptions once; the code enumerates operator x assumption cells and cross-domain
# projections, picks a diverse subset, and the model answers each cell in ONE line.

ASSUMPTION_OPS = {
    "drop": "remove this assumption entirely - what becomes possible?",
    "invert": "assume the exact opposite - what solution would then be natural?",
    "zero": "push the quantity it involves to zero / nothing - what remains?",
    "infinite": "push it to the extreme / unlimited - what changes first?",
    "swap": "swap the roles of the two things it relates - who does what?",
    "split": "split the thing it is about into two independent parts - handle each differently?",
    "time": "change WHEN it applies (before / after / repeatedly / never) - what does that unlock?",
}

PATTERN_BANK = [
    # (domain, name, mechanism, projection question)
    ("physics", "invariant", "a quantity that never changes under every allowed move", "What is conserved here, and what does that rule out?"),
    ("physics", "potential", "a scalar that every good move decreases", "What could be a potential function that strictly improves?"),
    ("physics", "relaxation", "let a system settle by small local moves under a slowly tightening constraint", "What would annealing / gradual tightening look like here?"),
    ("physics", "coarse-graining", "solve a blurred version, then refine (renormalisation)", "What is the low-resolution version of this problem?"),
    ("physics", "symmetry breaking", "an optimum is often less symmetric than the problem", "Which symmetry should the best answer NOT have?"),
    ("physics", "dimensional analysis", "the answer must scale correctly with every parameter", "How must the answer scale, and what does that force?"),
    ("biology", "variation + selection", "many cheap variants, keep what survives a real test", "What are cheap variants and what is the survival test?"),
    ("biology", "modularity", "independent modules that can evolve separately", "Which parts can be solved independently and recombined?"),
    ("biology", "redundancy", "several weak copies beat one strong one when failures are independent", "Where would independent redundant paths help?"),
    ("biology", "threshold / quorum", "act only when enough independent signals agree", "What independent signals could vote here?"),
    ("biology", "niche", "specialise to an unoccupied region instead of competing head-on", "Which region of the space is nobody covering?"),
    ("economics", "marginal analysis", "spend the next unit where its return is highest", "Where does one more unit of effort pay the most?"),
    ("economics", "price / market", "let a price signal allocate a scarce resource", "What is scarce, and what would its 'price' be?"),
    ("economics", "incentives", "change payoffs so the desired behaviour is the selfish one", "Whose incentives make the bad outcome happen?"),
    ("economics", "auction / matching", "allocate by bids or stable matching", "Is this secretly an assignment or matching problem?"),
    ("economics", "option value", "keep cheap options open until information arrives", "What cheap option preserves flexibility?"),
    ("information", "hashing / fingerprint", "compare compact fingerprints instead of whole objects", "What compact signature would distinguish the cases?"),
    ("information", "error-correcting code", "add structured redundancy so errors can be detected and fixed", "What redundancy would let errors be caught automatically?"),
    ("information", "commitment", "fix a choice before seeing the data, then check it", "What should be committed in advance to avoid fooling ourselves?"),
    ("information", "randomisation", "random choices defeat worst cases and adversaries", "Where would a random choice beat a clever one?"),
    ("information", "compression", "a good model is one that compresses the data", "What is the shortest description that explains all cases?"),
    ("computing", "divide and conquer", "split, solve parts, merge", "What split makes the parts easy and the merge cheap?"),
    ("computing", "memoisation / DP", "reuse answers to repeated sub-problems", "What sub-problem repeats?"),
    ("computing", "duality", "every optimisation has a mirror problem that bounds it", "What is the dual, and what bound does it give?"),
    ("computing", "reduction", "turn it into a solved problem", "Which known problem is this in disguise?"),
    ("computing", "amortisation", "pay a big cost rarely to make every step cheap", "What one-time investment makes everything else cheap?"),
    ("computing", "sketching / sampling", "estimate from a small sample before doing it exactly", "What small sample would tell us the answer's shape?"),
    ("mathematics", "extremal principle", "look at the biggest/smallest/first element", "What does the extreme case force?"),
    ("mathematics", "pigeonhole", "more items than boxes forces a collision", "What are the boxes, and what collision is forced?"),
    ("mathematics", "probabilistic method", "a random object has the property with positive probability", "Would a random choice work on average?"),
    ("mathematics", "transform domain", "move to a space where the operation is simple (generating functions, Fourier, logs)", "In which transformed space is this trivial?"),
    ("mathematics", "fixed point", "the answer is a state that a map leaves unchanged", "What map has the answer as a fixed point?"),
    ("mathematics", "induction on structure", "build the answer for n from n-1", "How does the size-n answer come from smaller ones?"),
    ("mathematics", "double counting", "count the same thing two ways", "What can be counted in two different ways?"),
    ("engineering", "feedback control", "measure the error and correct continuously", "What measurement could steer the process?"),
    ("engineering", "safety margin", "design for the worst case plus margin", "What is the worst case, and how much margin is enough?"),
    ("engineering", "fail-safe default", "make failure land in a harmless state", "What should happen when this fails?"),
    ("engineering", "interfaces", "fix the contract between parts, vary the parts", "What contract would let parts be swapped freely?"),
]


def edge_cells(assumptions, k=12, seed=0, ops=None):
    """Diverse (assumption, operator) cells to answer in ONE line each. Greedy balanced design: each pick uses
    the least-used assumption and the least-used operator, so every assumption and every operator appears
    before any is repeated."""
    ops = list(ops or ASSUMPTION_OPS)
    rng = random.Random(seed)
    pairs = [(a, o) for a in assumptions for o in ops]
    rng.shuffle(pairs)
    use_a, use_o, chosen = Counter(), Counter(), []
    while len(chosen) < min(k, len(pairs)):
        a, o = min((p for p in pairs if p not in chosen), key=lambda p: (use_a[p[0]] + use_o[p[1]], use_o[p[1]]))
        chosen.append((a, o))
        use_a[a] += 1
        use_o[o] += 1
    for i, (a, o) in enumerate(chosen, 1):
        print(f"E{i}. [{o}] {a} -> {ASSUMPTION_OPS[o]}")
    return chosen


def projections(k=8, seed=0, domains=None):
    """k cross-domain patterns, stratified so every domain appears before any repeats."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for row in PATTERN_BANK:
        if domains is None or row[0] in domains:
            by[row[0]].append(row)
    for v in by.values():
        rng.shuffle(v)
    order = sorted(by)
    rng.shuffle(order)
    out, i = [], 0
    while len(out) < k and any(by.values()):
        d = order[i % len(order)]
        if by[d]:
            out.append(by[d].pop())
        i += 1
    for j, (dom, name, mech, q) in enumerate(out, 1):
        print(f"X{j}. {dom}/{name}: {mech}. -> {q}")
    return out


class IdeaPool:
    """Ideas evolve under EXPERIMENTS as the fitness function.

    Each idea is one line + a risky prediction written BEFORE testing + a test (callable or a description of
    the cheapest decisive check). Status: OPEN -> SURVIVED/KILLED. Score rewards surviving many serious kill
    attempts and confirmed risky predictions; diversity is kept by cells (origin x target)."""

    def __init__(self):
        self.ideas = []

    def add(self, text, prediction="", origin="", target="", parents=()):
        idea = {"id": len(self.ideas) + 1, "text": text[:240], "prediction": prediction[:240], "origin": origin,
                "target": target, "parents": list(parents), "status": "OPEN", "kills_survived": 0,
                "confirmed": 0, "failure": None, "gen": 1 + max((self.ideas[p - 1]["gen"] for p in parents), default=0)}
        self.ideas.append(idea)
        return idea["id"]

    def attempt_kill(self, idea_id, test, description=""):
        """test() -> True if the idea SURVIVES this attempt, False (or raises) if it is killed.
        Return value of test may also be (bool, detail)."""
        idea = self.ideas[idea_id - 1]
        try:
            res = test()
        except Exception as e:  # noqa: BLE001 - a crash in the idea's own logic counts as a kill
            res = (False, f"error: {e!r}")
        ok, detail = res if isinstance(res, tuple) else (bool(res), "")
        if ok:
            idea["kills_survived"] += 1
            if idea["status"] == "OPEN":
                idea["status"] = "SURVIVED"
        else:
            idea["status"], idea["failure"] = "KILLED", (description or "kill attempt") + (f": {detail}" if detail else "")
        return ok

    def confirm_prediction(self, idea_id, came_true):
        idea = self.ideas[idea_id - 1]
        if came_true:
            idea["confirmed"] += 1
        else:
            idea["status"], idea["failure"] = "KILLED", "risky prediction failed"

    def score(self, idea):
        if idea["status"] == "KILLED":
            return -1.0
        return idea["kills_survived"] + 2.0 * idea["confirmed"] + (0.5 if idea["prediction"] else 0.0)

    def top(self, k=5):
        live = [i for i in self.ideas if i["status"] != "KILLED"]
        return sorted(live, key=lambda i: (-self.score(i), i["id"]))[:k]

    def elites(self):
        """Best idea per (origin, target) cell: a diverse set of parents for recombination."""
        best = {}
        for i in self.ideas:
            if i["status"] == "KILLED":
                continue
            cell = (i["origin"], i["target"])
            if cell not in best or self.score(i) > self.score(best[cell]):
                best[cell] = i
        return sorted(best.values(), key=lambda i: -self.score(i))

    def parents(self, k=2, seed=0):
        el = self.elites()
        rng = random.Random(seed)
        if len(el) <= k:
            return el
        weights = [max(0.1, self.score(i) + 1) for i in el]
        chosen = []
        while len(chosen) < k:
            pick = rng.choices(el, weights)[0]
            if pick not in chosen:
                chosen.append(pick)
        return chosen

    def plateau(self, rounds=2):
        """True when the best score has not improved over the last `rounds` generations."""
        gens = sorted({i["gen"] for i in self.ideas})
        if len(gens) <= rounds:
            return False
        best_by_gen = [max((self.score(i) for i in self.ideas if i["gen"] <= g), default=-1) for g in gens]
        return best_by_gen[-1] <= best_by_gen[-1 - rounds]

    def show(self, k=8):
        for i in self.top(k):
            print(f"#{i['id']} g{i['gen']} [{i['status']}, kills survived {i['kills_survived']}, confirmed {i['confirmed']}] "
                  f"{i['text']}  | predicts: {i['prediction']}")
        dead = sum(1 for i in self.ideas if i["status"] == "KILLED")
        print(f"pool: {len(self.ideas)} ideas, {dead} killed, {len(self.elites())} elite cells")


# =============================================================================================== independent critic (v6.5)
# The author cannot be his own blind killer: same mind, same blind spots. The critic below is a DIFFERENT
# context (a fresh chat that never saw the work) or a DIFFERENT model. The code enforces three things the
# author cannot fake by good intentions:
#   1. What the critic sees is sealed: problem brief + each idea's text + its risky prediction. Never the
#      author's tests, scores, ranking or reasoning. Order is shuffled and ids relabelled (C1..Cn).
#   2. The critic only PROPOSES attacks. Truth is the test: each KILL becomes a pending attack the author must
#      run (pool.answer_attack). An idea with an unanswered attack is never "ready".
#   3. Independence is measured, not declared: an attack that repeats the author's own earlier kill attempts
#      is flagged ECHO (same blindness) and does not count; a review declared source="self" never counts.

CRITIC_RULES = (
    "You are an independent hostile reviewer. You did not write the items below and you have no stake in them. "
    "For EACH item, find the most concrete way it fails: a specific input, case, scenario, actor or fact that "
    "breaks it, and the cheapest decisive test that would show the failure. Attack the mechanism, not the wording. "
    "Do not grade style and do not suggest improvements. Only answer SURVIVE if you tried hard and could not "
    "break it; then name the strongest test you tried. Reply with exactly ONE json block:\n"
    '{"packet": "<packet id>", "reviews": [{"id": "C1", "verdict": "KILL or SURVIVE", '
    '"failure_case": "...", "test": "...", "confidence": 0.0}]}'
)


def _shingles(text, n=3):
    w = [t for t in "".join(c.lower() if c.isalnum() else " " for c in str(text)).split() if len(t) > 2]
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))} if w else set()


def _overlap(a, b):
    A, B = _shingles(a), _shingles(b)
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def critic_prompt(packet):
    """The ONLY text a critic receives. Rebuilt from the sealed packet fields, so the author cannot add framing."""
    lines = [CRITIC_RULES, "", f"packet id: {packet['packet']}", f"kind: {packet['kind']}", "",
             "PROBLEM:", packet["brief"].strip() or "(none given)", "", "ITEMS:"]
    for it in packet["items"]:
        lines.append(f"{it['id']}. {it['text']}")
        if it.get("prediction"):
            lines.append(f"    claims: {it['prediction']}")
    return "\n".join(lines)


def critic_packet(pool, brief, ids=None, kind="idea", author="", seed=None, path=None):
    """Seal live ideas for an outside critic. Returns the packet dict; packet['prompt'] is what you paste into a
    FRESH chat (or a different model), packet['runner'] is the same thing for the runner's #CRITIC hook."""
    import hashlib, json
    ids = list(ids) if ids else [i["id"] for i in pool.ideas if i["status"] != "KILLED"]
    if not ids:
        raise ValueError("nothing to review: no live ideas")
    body = json.dumps([brief, kind, [(pool.ideas[i - 1]["text"], pool.ideas[i - 1]["prediction"]) for i in ids]])
    pid = hashlib.sha256(body.encode()).hexdigest()[:12]
    rng = random.Random(seed if seed is not None else int(pid, 16))
    order = ids[:]
    rng.shuffle(order)
    items, key = [], {}
    for n, iid in enumerate(order, 1):
        idea = pool.ideas[iid - 1]
        items.append({"id": f"C{n}", "text": idea["text"], "prediction": idea["prediction"]})
        key[f"C{n}"] = iid
    packet = {"packet": pid, "kind": kind, "brief": str(brief)[:3000], "items": items, "author": author}
    packet["prompt"] = critic_prompt(packet)
    packet["runner"] = "#CRITIC\n" + json.dumps({k: packet[k] for k in ("packet", "kind", "brief", "items", "author")})
    pool.packets[pid] = {"key": key, "author": author}
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: packet[k] for k in ("packet", "kind", "brief", "items", "author")}, f, ensure_ascii=False, indent=1)
    return packet


def _critic_json(text):
    import json, re
    for blob in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) + [text[text.find("{"):text.rfind("}") + 1]]):
        try:
            d = json.loads(blob)
            if isinstance(d, dict) and "reviews" in d:
                return d
        except (ValueError, TypeError):
            continue
    return None


def critic_ingest(pool, reply, source):
    """Bring a critic's reply back. source names WHO reviewed ('chat:fresh', 'model:gpt-x', ...); 'self' or the
    packet's own author is stored but never counts as independent. Returns a report dict."""
    d = _critic_json(reply) if isinstance(reply, str) else reply
    if not d:
        raise ValueError("no json block with 'reviews' found in the critic reply")
    pid = str(d.get("packet", ""))
    if pid not in pool.packets:
        raise ValueError(f"packet id {pid!r} does not match any packet sent from this pool (stale or forged reply)")
    meta = pool.packets[pid]
    independent = source.strip().lower() not in ("self", "", meta["author"].strip().lower())
    rep = {"packet": pid, "source": source, "independent": independent, "kills": 0, "survives": 0, "echo": 0,
           "unknown_ids": [], "missing_ids": sorted(set(meta["key"]) - {str(r.get("id")) for r in d["reviews"]})}
    for r in d["reviews"]:
        cid = str(r.get("id"))
        if cid not in meta["key"]:
            rep["unknown_ids"].append(cid)
            continue
        idea = pool.ideas[meta["key"][cid] - 1]
        verdict = "KILL" if str(r.get("verdict", "")).upper().startswith("K") else "SURVIVE"
        attack = f"{r.get('failure_case', '')} | {r.get('test', '')}"
        own = [h for h in idea["self_attacks"] if _overlap(attack, h) >= 0.6]
        echo = bool(own)
        try:
            conf = float(r.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        rec = {"n": len(idea["ext"]) + 1, "packet": pid, "source": source, "verdict": verdict,
               "failure_case": str(r.get("failure_case", ""))[:400], "test": str(r.get("test", ""))[:400],
               "confidence": max(0.0, min(1.0, conf)), "independent": independent and not echo, "echo": echo,
               "status": "PENDING" if verdict == "KILL" else "NO_ATTACK"}
        idea["ext"].append(rec)
        rep["kills" if verdict == "KILL" else "survives"] += 1
        rep["echo"] += echo
    pool.reviews.append(rep)
    return rep


def _pool_init(self):
    self.ideas, self.packets, self.reviews = [], {}, []


_orig_add = IdeaPool.add
_orig_attempt = IdeaPool.attempt_kill
_orig_score = IdeaPool.score


def _pool_add(self, *a, **k):
    iid = _orig_add(self, *a, **k)
    self.ideas[iid - 1].update(ext=[], self_attacks=[], ext_survived=0)
    return iid


def _pool_attempt(self, idea_id, test, description=""):
    self.ideas[idea_id - 1]["self_attacks"].append(description or getattr(test, "__name__", ""))
    return _orig_attempt(self, idea_id, test, description)


def answer_attack(self, idea_id, n, test):
    """Run YOUR test for the critic's attack n on this idea. test() -> True if the idea survives it."""
    idea = self.ideas[idea_id - 1]
    rec = idea["ext"][n - 1]
    if rec["status"] != "PENDING":
        raise ValueError(f"attack {n} on idea {idea_id} is {rec['status']}, not PENDING")
    ok = _orig_attempt(self, idea_id, test, f"external attack {n} ({rec['source']}): {rec['failure_case'][:120]}")
    rec["status"] = "SURVIVED" if ok else "KILLED"
    if ok and rec["independent"]:
        idea["ext_survived"] += 1
    return ok


def pending_attacks(self):
    """Every critic attack you still owe a test for: [(idea_id, n, failure_case, test)]."""
    return [(i["id"], r["n"], r["failure_case"], r["test"]) for i in self.ideas if i["status"] != "KILLED"
            for r in i["ext"] if r["status"] == "PENDING"]


def _reviewed(idea):
    return any(r["independent"] for r in idea["ext"])


def ready(self, k=5):
    """Ideas you may present as tested: alive, reviewed by at least one INDEPENDENT critic, no unanswered attack."""
    ok = [i for i in self.ideas if i["status"] != "KILLED" and _reviewed(i)
          and not any(r["status"] == "PENDING" for r in i["ext"])]
    return sorted(ok, key=lambda i: (-self.score(i), i["id"]))[:k]


def _pool_score(self, idea):
    s = _orig_score(self, idea)
    return s if s < 0 else s + 1.0 * idea.get("ext_survived", 0)


def independence(self):
    """How much of the verdict came from outside. blind_spot = share of the author's survivors that an
    independent critic's attack then killed: the measured size of the author's own blindness."""
    ext = [r for i in self.ideas for r in i["ext"]]
    ind = [r for r in ext if r["independent"]]
    killed_by_ext = sum(1 for r in ind if r["status"] == "KILLED")
    resolved = sum(1 for r in ind if r["status"] in ("KILLED", "SURVIVED"))
    live = [i for i in self.ideas if i["status"] != "KILLED"]
    return {"sources": sorted({r["source"] for r in ind}),
            "live_reviewed": f"{sum(_reviewed(i) for i in live)}/{len(live)}",
            "attacks": len(ext), "independent_attacks": len(ind), "echo": sum(r["echo"] for r in ext),
            "pending": len(self.pending_attacks()),
            "blind_spot": round(killed_by_ext / resolved, 3) if resolved else None}


IdeaPool.__init__ = _pool_init
IdeaPool.add = _pool_add
IdeaPool.attempt_kill = _pool_attempt
IdeaPool.score = _pool_score
IdeaPool.answer_attack = answer_attack
IdeaPool.pending_attacks = pending_attacks
IdeaPool.ready = ready
IdeaPool.independence = independence
IdeaPool.packet = critic_packet
IdeaPool.ingest = critic_ingest


# =============================================================================================== plan engine (v6.5)
# A plan is a chain of phases. Each phase states, BEFORE it starts, what would make you stop (kill_if) and what
# would let you go on (continue_if), as measurable criteria "metric op number", plus a budget. A pre-mortem comes
# first: "it is later and this failed - why?" Every failure cause must name the early signal (a metric) that
# would show it, and must be watched by some phase's kill criterion, or be accepted in writing. start() freezes
# the criteria; later changes are logged, and loosening a stop rule is refused. report() decides
# deterministically, so the decision is made by the numbers you committed to, not by how you feel at that moment.

import re as _re_plan

_CRIT = _re_plan.compile(r"^\s*([A-Za-z_][\w.]*)\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")
_OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def _crit(text):
    m = _CRIT.match(str(text))
    if not m:
        raise ValueError(f"criterion {text!r} must be 'metric op number', e.g. 'signups < 20' or 'error_rate >= 0.05'")
    return {"metric": m.group(1), "op": m.group(2), "value": float(m.group(3)), "text": " ".join(m.groups())}


# =============================================================================================== data before thinking (v6.5)
# A hypothesis formed out of the model's own head is a guess ABOUT the world, not a reading OF it. An idea can
# survive every critic and still describe a world that is not the real one, because author and critic can share
# the same wrong picture. So before an idea counts as tested, part of its support must come from OUTSIDE the
# model - and that must be CHECKED, not declared, exactly as reg derives a level from what ran instead of from
# what the author claims:
#   1. Raw material is SEALED first: ev.source(name, text, provenance) stores the text and its sha256 in a hash
#      chain (the problem files, a tool's real output, a page the app fetched). Nothing can be backdated.
#   2. A fact is VERIFIED (level 2) only if its quote is found verbatim in a sealed source of the same provenance.
#      Declared-external without a checkable quote is level 1; recalled from memory is level 0 (not data).
#   3. Strength counts DISTINCT sealed sources: ten quotes from one page are one stream of evidence, the same way
#      reg.oracle discounts held-out cases that share an answer.
#   4. Every citation says WHAT the evidence shows that the idea depends on (why=...), so grounding is auditable.
#   5. Evidence AGAINST an idea (stance='contra') is a pending attack from reality: the idea is not ready until a
#      test answers it (pool.answer_contra), like a critic's KILL.
# amp_lab fetches nothing (standard library, in-tool). Material comes from the model's own web/tool use, attached
# files, or the runner. Its weak point is the one it cannot close alone: a source's text is whatever was passed in.
# The sha256 in the chain lets anyone match a sealed source against the real file or tool log afterwards.

import os as _os_ev

EVIDENCE_PROV = ("given", "live", "published", "self")
EVIDENCE_EXTERNAL = {"given", "live", "published"}     # support that did NOT come out of the model's own memory
#   given     - shipped WITH the problem (spec, attached files, sample I/O)
#   live      - the observed behaviour of a REAL system queried now (a tool's real output, a running service)
#   published - an EXTERNAL published source gathered now (a paper, a report, official docs, a dataset)
#   self      - recalled or asserted from the model's own memory. NOT data: it shares the model's blind spots.
EVIDENCE_LEVEL = {0: "self-recalled (not data)", 1: "declared external (no checkable quote)",
                  2: "VERIFIED (quote found in a sealed source)"}
MIN_QUOTE = 12                                           # shorter quotes match by accident and verify nothing
STRENGTH_BONUS, STRENGTH_CAP = 0.5, 2                    # score bonus per distinct verified source, capped


def _norm(t):
    return " ".join(str(t).lower().split())


# ----------------------------------------------------------------------- provenance is CHECKED, not declared (v6.6)
# A provenance word is a claim. These rules bind it to something a program can check:
#   given     - the sealed text must BE a problem file: its sha256 is in the kit manifest (KIT_GIVEN_SHA256, written
#               by make_kit into the kit copy) or the runner's (env AMP_GIVEN_SHA256). Seal the WHOLE file.
#   live      - the text must come from the RUNNER's own log of a tool it executed (#LIVE), carried by a receipt
#   published   'id:sha256:mac'. In here only the sha256 can be checked; the mac is checked by the runner AFTER the
#               run with a key that never enters the sandbox (attest_certificate).
#   Track A (the app) has no runner: there a live / published source is a DECLARATION only (L1, never E3).
#   Real proof of provenance exists only in Track B.
# Code that monkeypatches this module can forge any in-process check; that is deliberate, visible in the transcript,
# and does not survive attest_certificate, which re-checks with the runner's / grader's OWN manifest and key.
KIT_GIVEN_SHA256 = frozenset({"039e482263f9644674a926cb5db2e91706298266a1de431ee683039be282af38", "03dc61d1bc15076e6c73708d657793a1ac257d47a8a584947137724e98709f54", "0507c6c128a842a4d7e87e2f1ee1203830858b7d42a6092ac8a53aa65e243d46", "06e91fbdc411f3852bd1e0a3eaf8e4a653ee337d869338f5f7bb6cfdd7efe678", "0793daff28d284ee41825261896edb3f9389afda5e6b190b01b37d4f37911258", "07aa091ef7f30471610c1f7093039af05080be81b51f630225de97e75b3e3ce9", "088c21c5a5344edbbf8eef934130bdb95a75d7c7e01ff27b4fbd7b4bfffa6015", "0a01c6c1c9a0a80d1db8129863a336f12bda04f4dac5cb34910226e1cb821191", "0cde2c85800220097d8365b65d9fd5f78eacab0462e56e0add8bdc12effc2286", "0e5b9570dddbd1630eba74528edf8f052c21c82a16edca1df41994460d77ee5b", "0f0467323463b63e446dd65944bcdda57f53da9f64795046e174470eb1a8571f", "14222b4196b2f42f5fa97f9467227238c1c6ed8f81e0632deda52b285d061f00", "165b78cb01e2b9bcf6921400ff777cdb3bad98af2a2a333897cd6a78d5326e92", "16725927cc0357e3c84016870a74cb2ca1ed0701d5acbfe7f5ba9ba3011ff39e", "196bf41f857d84340efe49495d3138ee6ed6c95a80f4245eb341180279f348b2", "1a847b5f40c5944d8277dc6bd0956a8f49ffb40db4e3e2545045160ea5cb7526", "1d32c619fdcf45905ee9e5570d94d4b72d1ccdeb2010e6ade852e09c5789d2d2", "1efcb83d42e3a83cc32323fd66c03c6509665d669df1aff48ee38be664ff9c5b", "1f9fc70d3e426304415dc7cef82b13178d5843b315330544d6829c694c23bcda", "20234030a29303efc72e23e1a93e3b0da0f3046840bb451e7b6b3f461b77e6f3", "211327f368b8f9c187e3649cb0d4295dc076d999ce7bec34733a6af1329d1cf4", "2679d59a1697ba63fa9a5bb926777e9f66915f4a7dce8aa88ef23e198d0b06d9", "26efb43867a46b1fa0e8a8e502498212577c47e1ed0b739f22389a4dddf16bfb", "2eae53829e997b625bda529907f9c5705356d4125ba62d286ba1aac5f5e75ad9", "32ecb413a13d5b0c03f06da0c0895a049bb640e27676edea9a4d1c9752c34762", "334c50f42c9e9314ee2592b8c8d9d37501613286943252ce9419bf811ab6ccb5", "34c1e184f408e6ecbe479b347cc8577cd55f6d55dba206cbbafbf6a857c4aaf8", "3a911941fbcb34b88be18705a39d5d8cbe6f320ca56586795ead9674b4c7657a", "3d3d566137a2ccdd8b8b09ee82f06c9513cdc05b07b34542d89949e1348050d4", "40f36eead8a30fdea020a2d278115818746a655a7bf5cbe297dac23eccc63230", "414372352e6f96f6a64b663ab693131ddfa70cbe97e747c4e8a2553ad9515088", "434cd6c54374954e65d4e7efc6f997d0eb326b2799c3fcdf77f313b1d38662fa", "450ff22f20b2c58af8a8d5d3fc8373b219f1a8e30915c7fa3916e5a4f42b5ee9", "46a15bc621dfdba7680e6d61773562cff09bb317735669f493a95d17bbcb6dd3", "4763ba545d5b21a73f01c8e620b04b441ba8caf943e6a00fc9611555a176683c", "4bae23ceacbf311fa9f598d79d7d5eec8b7797422f8443b67847e85313301ff9", "4beccce682986ebe01f7ff6e6b5cce704959f0850d6c8c6bea51af0865e0bce2", "509ee36d7a277282ecf4c5239657bfd61e3e58f052f075d1393702655668df18", "50ebb18245cba9533265a696f294aac75c7a5781a7ce5b45245b6c831406edde", "56182915ea386613f5ae86d2c28ab6f34a2549f26b2ea72bbd9c0015e52b685b", "5a2ba0ca47d7630e1efd736d50a1fba6d49d3eb55c27615c70aaaa3167969665", "5b29459f3b14e5735dba57ac118475361b751f3bfeb540253a8cff2cbc24891b", "5e1c433d3af85512b583fbe0cfb6c93ba5995f16766fc52dad8a45a7b43c5140", "60d0f89f7a86160459c65904418601151665a6a952fa12941f49f6af2a84a001", "61d7b5245cdee260d38ae43f3a926f9b0c422ec0abce24ced3bcf6cec60da3f6", "64969c655715eeb7ddc4c9580f637222fd35e29f1f932ff194f50cef9b1a83e8", "65a096a6136951c774b49fe111fb5ab20a6687d80eba9110696f2b15fdc4c8d9", "67b4b6d2b27a8941c08a08352d5d77fc991e5670aa03761f8c4bda2161fef07d", "6896580cea7a672fb3e1bedc042cbc427a62e77bb304a546f014382656fe4c05", "68d21a4b404d20a498af1e4fe91596e5df49e0f0bc3543ca0a172ec023daf349", "6949d439adc27e1b038c5e686379e0cec7e227f32cd731d371a3fc90ba7c6a15", "6b583db924adb0de820ddd1268ee446a6370f52dbf48fb6afb98c34e8220eb87", "6c104eb74b60497262fac71b6d55afcac1a802a0c030904ccc5275741d7f4b15", "6c840dd08909e747e0e209cacda9f373dc32d9cb078d352c775ebfe76a147827", "6e493a119f8fdbb50962a638fd25897a9b3b26ecc85d60cabc364baadc49f8e9", "6fafe1a0f4a9122b07bc7ffab02c6d37e7b8a042b72325b67fd78ce779e96d5b", "6fb20004b246cf8c4e051c82f7a7c93971f84ee482e30687f8de2fe3c10f0ea4", "70c72e561c8636db4b03e583cacfbb4dea9d09531f26344212b4ab71a034621d", "79d64077368b9c1a1fb7870a549264ae056ba6b895bd7f15545146622f8ee397", "7ef0551658fbda5b36b4909b53ee76690154de650f76a89ef07b45378b47a2af", "8090da46f80af7213fb2f8901a58a45f0280db5d0bae885a646b40aec580f518", "80a8b47941827143d394752f4097a28431d61bb9a98328c9babf01360189952c", "82183df54a0bae1ae831cd24b37d1a8d281a221ecd2d3aa34ab5a1805db11210", "83dda80aaec91b74efc6c35dc06e79736e7c94010b1e2e38c869a03aa05c2063", "87fc92c5629df374d0e1ea175d364c3eccb2c061522b2a3c1fe056c861002ab3", "8897211606f78c936df593d73476519161201d3031d50b6dd0f846ead9799ef0", "89daebc90ef56b63f3899bc6c15bf3385777c7252bdbea2093c3efa9930f34f7", "8acb9a00ca956b6c842899485c71bdc7496efabe067b73bc63967206eae406a0", "8b0bf561921e949c2c491975a56439be5c0b0f0ea28074e0a585b652a17aeab9", "8d9042bc4edc4748a934565dbe4e75bf317dc8a230c5b1bd0e8a957b58a901ea", "8efc4c72217501e7f0da42d4f96bfa6e1350b2376c0ab2b64e6d629fdc18b9bb", "8fe39fe28f350a319fb6b4c6ff5e56203659f90303f4b6723cbbc32bb37234fa", "988d6da1130926f3769935774f2b59385628349059cb010db2ec2eed8c2c27c6", "a1d7899c0ab1438624fd0a1ddf685e24f0ebf8e26c51f3b6e10c7ff9a67afdab", "a2b78a644cb129729da76e1f00c2172c49a3e1652910f3c6d1f8e54c7752a70a", "a311684d00b9449eb2e5d64a981ff2606de03bbfe5f443e21d54a1fc7c50d707", "a8074841eb0d9b19184b6112af2fab16b8726c0661b7be6462a84635610e5205", "b3933438cff13eae455d9c2ffb9061845e87dfdf82df0c2225f2810cccfb50b7", "b6815c8188e6154bcaf39b0a8d9638e492f613af59f1a4246ff7f35da31ffae6", "b9d2267496f1197774c93fe19c18c9a67960b8a939767aa144bbc00f4726c96b", "baade14c69fb1710c9637f2f65b01cb4f59d849b8ad35719acd07e25b867f8e7", "bba6033c5015ad75cd93c57cef9389cb88d68df3a19d513d1ca49db06aec8443", "be375f723df70a463a51db61dcafdbb0c692047f8b1e8310da0d75cfee72dd2b", "c0af0592d4d26fe021e2dd4b8d69178bf03ca000366a9f1a3af69f8021262608", "c0baf862c380815d2d52b13bc752aea2387d0c2771be99e248d49615cd355076", "c11a18d50e035b8547a802ad948fbee048af820667f2a265f986265b6bb3c61e", "c179850bacbb068f383b95a96788e28e09da9165bd669e15bcb9557206a6f206", "c32420ee879f58af848606011f09e90c7be7335afa737c445cbdcc125c4e8a91", "c66f8df1adbb54c22783d69892a1613070482f58465bf214df32739d68ac68a3", "cb824de7bd77d9ea747b563ed82b9253add71788c47f98b7956995314d1bdd82", "cc81508ebb295f1863d1b0097f882275946aa6d6923f48206145cffbb0438559", "cda23ec34c7338697df6ee30b17e49ebdf8aefd5cbc748f3a3e35f161cc908c9", "cf27bc84e8e5d63ded562727d4513668075b83322d973b3b1806debbd688773c", "d29d9f1e1f1b9499fbcc258fdf0162f4dcce3987b40064c7b5d49588c64de07b", "d312308ea6676532dac4a8b53ad58738507a28805a7eb31126e797a9b98ba4ab", "d63da01b472ebb518bda800fa0f82df7a12738f175db7c9afc09bc65700ad700", "d6fc9c497fb3239430b4561768029c6a827695e4564d801a26ad45e668840a06", "dba0532900653351dbe8207947f63341185eed2cebd22c2e2c47e88286b83ff3", "dd4f01e2c0d865cc27f99c0b2c1e9ba2cc9f324b602b4b013ba2249630e26e5f", "ddfaf76e96980f5b56c5d2c08e1b7e6f89843b8dac23e43e2159de84eb569df6", "e0ed227b250210a790630cc9609e5d63745220afb9324713035327fe069e157a", "e2d8aab47d1ff363b26092c56b4dba9c898084bd4d3dc3bf42b84e3224520ef6", "e3dc72beb40acc1e175ecdbaf131c139796e41ef127da221ee37f296fa9e680f", "e45ffc26e61fd71ef2b8e638907bdcda4cc87c6b63d225b851564980d98b65c7", "e6c6c15fca1d033e8386232f77dafef6dc683441fc64359f9551ffb00412d1dc", "e7ea15d2c626bbe9d1b6d111792acd399cf5cd24229a77c035b1e8b2072e4e09", "e934b6916c9b39126988ad2f0ae34e6300b0d1bf0ddda794a034852630bb09aa", "ea1f3870e2513a32a6bd71d698e5d9655602dbfc5a99f7bf0abf95dd6200989d", "ef7d19d6091cde9927d0c49db796e473f66187181f5ada94fe666e58c6dfd0fd", "efa9a7c3cae1a7c79417ae6b5f8442417639f6039391e6dea45acd631609367d", "f010c5797ed929231ae9af2aacfd8e49d19817dcdc38abb3b77016582693c17e", "f469082f8e92b7b9a74f389d505e101ee1a1db867e8b8ac9e708659eb50db43c", "f50497b35badee6926dbba1f1e0cf519aab34a5ed46447cf4d5bcc98dadaecbb", "fada31765a0e6e995e69375323131259c9082bef60d5e2b49b006b3e1385be1c", "fb85e5f6b9078b9d89b478ed440cb96c70eb19e4d2fb17d15f7b175aa03f9af3", "fba8819ca53bec66f5feccf48fe82b3b281921e39e5334df452f534ed87f8521", "fc75231ad007ace8c68935c4bc0dd6f09c1f4ef4d89ddcfdbcb234e5a45dc51d", "fca90eae5cc6fca628b43c465acac03b63b69492d9d525c47052b83f5ecd795c", "fdbbbbe48316982f8e84048aa126564468c298e43fe4ddb90d7145db27a85d28", "fdf0ce7c6b93b07de903e65e24727989d727b17030816c7e684f0a98c16d2f25", "fe1100b4bcaf0565c5a363f07fa84e2579574b18fdbdaa600ef70dc43608a608"})   # problem files of this kit
_TOK = _re_plan.compile(r"-?\d+(?:/\d+)?|[a-z0-9_]+")   # clean number / fraction / word tokens: "6." -> "6", "170/201" stays one
CASE_GAP = 8                            # max tokens between the input block and the output block of one example (labels like "Example 1 output:")


def _given_manifest():
    env = _os_ev.environ.get("AMP_GIVEN_SHA256", "")
    return set(KIT_GIVEN_SHA256) | {s.strip() for s in env.split(",") if s.strip()}


def _track():
    return "B" if _os_ev.environ.get("AMP_TRACK") == "B" else "A"


def _parse_receipt(receipt):
    parts = str(receipt or "").strip().split(":")
    return parts if len(parts) == 3 and all(parts) else None


def provenance_check(provenance, text_sha, receipt=None):
    """(attested, why) for raw material sealed under this provenance."""
    if provenance == "given":
        man = _given_manifest()
        if not man:
            return False, "no problem-file manifest in this environment: 'given' is declared only"
        if text_sha in man:
            return True, "sha256 matches a problem file"
        return False, "sha256 matches NO problem file: 'given' must be the whole problem file (ev.source_file)"
    if _track() != "B":
        return False, (f"Track A: a {provenance} source is a DECLARATION only; proof of provenance exists only in "
                       "Track B, where the runner logs the tool output and issues a receipt")
    rc = _parse_receipt(receipt)
    if rc is None:
        return False, f"no runner receipt: {provenance} text must come from the runner's #LIVE log, not from the model"
    if rc[1] != text_sha:
        return False, f"receipt {rc[0]} is for a DIFFERENT text (sha256 mismatch)"
    return True, f"runner receipt {rc[0]} (its mac is checked by the runner after the run)"


def _toks(t):
    return _TOK.findall(str(t).lower())


def _leaves(x):
    if x is None:
        return []
    if isinstance(x, (bool, int, float, Fraction)):
        return [str(x).lower()]
    if isinstance(x, dict):
        return [t for k, v in x.items() for t in _leaves(k) + _leaves(v)]
    if isinstance(x, (list, tuple, set, frozenset)):
        return [t for v in x for t in _leaves(v)]
    return _toks(x)


def case_tokens(args, want):
    return [_leaves(args), _leaves(want)]


def _find_run(sub, toks, start=0):
    """Index of the first place `sub` appears as a CONTIGUOUS run in toks at or after start, else -1."""
    if not sub:
        return start
    for i in range(start, len(toks) - len(sub) + 1):
        if toks[i:i + len(sub)] == sub:
            return i
    return -1


def case_in_tokens(case, toks, gap=CASE_GAP):
    """True if one example really appears in the source: the INPUT block as a contiguous run, then the OUTPUT block
    as a contiguous run within `gap` tokens after it (that gap is the "Example k output:" label). Requiring each
    block to be contiguous is what stops a pair the model INVENTED from being assembled out of digits scattered
    around the problem text; a pair that was genuinely given appears as written and is found."""
    a, w = case
    ain, out = list(a), list(w)
    if not out:
        return False
    if not ain:
        return _find_run(out, toks) != -1
    n = len(ain)
    starts = [i for i in range(len(toks) - n + 1) if toks[i:i + n] == ain]
    for i in starts:                                        # try EVERY place the input block occurs
        j = _find_run(out, toks, i + n)
        if j != -1 and (j - (i + n)) <= gap:
            return True
    return False


class Evidence:
    """Real data gathered BEFORE forming hypotheses, checked against sealed raw material.

        ev = Evidence()
        ev.source_file('PART1.txt', provenance='given')                       # seal the problem as it was given
        ev.source('bench_run', tool_output, provenance='live')                # seal a real tool output
        n = ev.add('p95 rises with cache misses', provenance='live', src='bench_run',
                   quote='p95=840ms at miss_rate=0.31')                       # level 2 if the quote is really there
        ev.gate()                      # [] once >=1 VERIFIED external fact exists
        pool.attach(ev); pool.cite(ev, idea_id, n, why='the idea assumes misses drive latency')
    """

    def __init__(self, path=None):
        self.records, self.head, self.path, self.refs, self.sources = [], "0" * 64, path, {}, {}

    def _append(self, rec):
        rec["prev"] = self.head
        rec["hash"] = _h(self.head + _json.dumps(rec, sort_keys=True, default=str))
        self.head = rec["hash"]
        self.records.append(rec)
        return rec

    # ------------------------------------------------------------------ raw material
    def source(self, name, text, provenance, ref="", receipt=None):
        """Seal raw material from OUTSIDE the model. Returns its sha256 (match it against the real file / log).
        Provenance is CHECKED (provenance_check): 'given' must be a problem file, 'live'/'published' must carry the
        runner's receipt (Track B). An unproven source is still sealed, but facts quoted from it stay L1 (declared)."""
        if provenance not in EVIDENCE_EXTERNAL:
            raise ValueError("a source is material from OUTSIDE the model: provenance must be given / live / published")
        if name in self.sources:
            raise ValueError(f"source {name!r} is already sealed; register new material under a new name")
        text = str(text)
        if len(_norm(text)) < MIN_QUOTE:
            raise ValueError("source text is empty or too short to quote from")
        sha = _h(text.encode("utf-8"))
        attested, pwhy = provenance_check(provenance, sha, receipt)
        rec = self._append({"type": "source", "name": str(name), "provenance": provenance, "ref": str(ref)[:240],
                            "sha256": sha, "chars": len(text), "receipt": str(receipt or "")[:200],
                            "attested": attested, "prov_check": pwhy})
        self.sources[name] = {"text": _norm(text), "tokens": _toks(text), "provenance": provenance, "ref": rec["ref"],
                              "sha256": sha, "receipt": rec["receipt"], "attested": attested, "prov_check": pwhy}
        print(f"source {name!r} sealed [{provenance}] {len(text)} chars sha256={sha[:12]}  provenance "
              + ("PROVEN" if attested else "DECLARED ONLY") + f" ({pwhy})")
        self.save()
        return sha

    def source_file(self, path, provenance="given", name=None, ref="", receipt=None):
        """Seal a file read from disk (an attached problem file, a runner-written #LIVE log)."""
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return self.source(name or _os_ev.path.basename(path), text, provenance, ref or path, receipt=receipt)

    # ------------------------------------------------------------------ facts
    def add(self, summary, provenance="self", ref="", quote="", src=None, note=""):
        """Record one fact. Level 2 needs src= (a sealed source of the same provenance) and a verbatim quote= from it."""
        prov = provenance if provenance in EVIDENCE_PROV else "self"
        level, why = 0, "recalled from the model's own memory"
        if prov in EVIDENCE_EXTERNAL:
            level, why = 1, "external by declaration only: give src= and a verbatim quote= to verify it"
            if src is not None:
                s = self.sources.get(src)
                if s is None:
                    raise ValueError(f"source {src!r} is not sealed; call ev.source(...) first")
                if s["provenance"] != prov:
                    raise ValueError(f"source {src!r} is {s['provenance']}, not {prov}")
                q = _norm(quote)
                if len(q) < MIN_QUOTE:
                    why = f"quote shorter than {MIN_QUOTE} characters cannot verify anything"
                elif q in s["text"] and not s.get("attested"):
                    why = (f"quote is in source {src!r}, but that source's provenance is NOT proven "
                           f"({s.get('prov_check')}): a sealed text proves it did not change, not where it came from")
                elif q in s["text"]:
                    level, why = 2, f"quote found verbatim in sealed source {src!r} of proven provenance"
                else:
                    why = f"quote NOT found in source {src!r}: the fact is not what the source says"
                ref = ref or s["ref"]
        n = len(self.refs) + 1
        key = f"src:{src}" if src is not None and level == 2 else (f"ref:{ref}" if ref else f"n:{n}")
        rec = self._append({"type": "evidence", "n": n, "summary": str(summary)[:400], "provenance": prov,
                            "external": prov in EVIDENCE_EXTERNAL, "level": level, "src": src, "key": key,
                            "quote": str(quote)[:300], "ref": str(ref)[:240], "note": _h(note), "why": why})
        self.refs[n] = rec
        print(f"evidence #{n} L{level} [{prov}] {EVIDENCE_LEVEL[level]}: {rec['summary'][:70]}  ({why})")
        self.save()
        return n

    def external(self, min_level=1):
        return [r for r in self.refs.values() if r["external"] and r["level"] >= min_level]

    def verified(self):
        return self.external(min_level=2)

    def gate(self):
        """What blocks data-first work. [] = at least one VERIFIED external fact to reason from."""
        if self.verified():
            return []
        declared = self.external()
        if declared:
            return [f"{len(declared)} external fact(s) are only declared: seal the raw material with ev.source(...) and "
                    "add each fact with src= and a verbatim quote= so it can be checked"]
        return ["no external evidence yet: seal a given / live / published source and add a quoted fact from it "
                "BEFORE forming hypotheses (a fact from memory is provenance='self' and does not count)"]

    def supports(self, text, thresh=0.6):
        """External facts this text merely RESTATES (a re-discovery, not a new idea). Same overlap as the critic's echo check."""
        return [r["n"] for r in self.external() if _overlap(text, r["summary"] + " " + r["quote"]) >= thresh]

    def certificate(self):
        return {"version": "amp-evidence-6.5", "head": self.head, "records": self.records}

    def save(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                _json.dump(self.certificate(), f, ensure_ascii=False, indent=1)

    def show(self):
        for nm, s in self.sources.items():
            print(f"  source {nm!r} [{s['provenance']}] sha256={s['sha256'][:12]}")
        for r in self.refs.values():
            print(f"  #{r['n']} L{r['level']} [{r['provenance']}] {r['summary'][:80]}" + (f"  <- {r['ref']}" if r["ref"] else ""))
        print(f"evidence: {len(self.sources)} sealed sources, {len(self.refs)} facts, {len(self.verified())} verified")
        return len(self.verified())


_add_before_ev = IdeaPool.add
_ready_before_ev = IdeaPool.ready
_score_before_ev = IdeaPool.score


def _pool_add_ev(self, *a, **k):
    iid = _add_before_ev(self, *a, **k)
    for f in ("evidence", "contra", "restates"):
        self.ideas[iid - 1].setdefault(f, [])
    return iid


def attach(self, ev):
    """Bind the evidence ledger to this pool: from now on ready() requires verified grounding."""
    self.ev = ev
    return self


def cite(self, ev, idea_id, *ns, why="", stance="pro"):
    """Link facts to an idea. why = one sentence on WHAT the fact shows that the idea depends on (or contradicts).
    stance='pro' grounds the idea; stance='contra' is evidence against it: a pending attack until answer_contra()."""
    if stance not in ("pro", "contra"):
        raise ValueError("stance is 'pro' or 'contra'")
    if len(str(why).strip()) < 10:
        raise ValueError("say in one sentence what this evidence shows that the idea depends on (why=...)")
    if getattr(self, "ev", None) is None:
        self.ev = ev
    idea = self.ideas[idea_id - 1]
    for f in ("evidence", "contra", "restates"):
        idea.setdefault(f, [])
    have = {c["n"] for c in idea["evidence"]}
    for n in ns:
        r = ev.refs.get(n)
        if r is None:
            raise ValueError(f"evidence #{n} does not exist in this ledger")
        entry = {"n": n, "provenance": r["provenance"], "level": r["level"], "key": r["key"], "why": str(why)[:240]}
        if stance == "pro":
            if n not in have:
                idea["evidence"].append(entry)
                have.add(n)
        else:
            idea["contra"].append({**entry, "k": len(idea["contra"]) + 1,
                                   "status": "PENDING" if r["level"] >= 1 else "NOTED"})   # self-recalled contra: noted only
    idea["restates"] = sorted(set(ev.supports(idea["text"]) + ev.supports(idea["prediction"])))
    return idea["evidence"]


def answer_contra(self, idea_id, k, test):
    """Run YOUR test against contra-evidence k. test() -> True if the idea survives it; False kills the idea."""
    idea = self.ideas[idea_id - 1]
    c = idea["contra"][k - 1]
    if c["status"] != "PENDING":
        raise ValueError(f"contra-evidence {k} on idea {idea_id} is {c['status']}, not PENDING")
    ok = self.attempt_kill(idea_id, test, f"contra-evidence #{c['n']}: {c['why'][:120]}")
    c["status"] = "SURVIVED" if ok else "KILLED"
    return ok


def pending_contra(self):
    """Evidence against live ideas that you still owe a test for: [(idea_id, k, fact_n, why)]."""
    return [(i["id"], c["k"], c["n"], c["why"]) for i in self.ideas if i["status"] != "KILLED"
            for c in i.get("contra", []) if c["status"] == "PENDING"]


def _strength(idea):
    """Distinct sealed sources behind the idea's VERIFIED pro evidence."""
    return len({c["key"] for c in idea.get("evidence", []) if c["level"] >= 2})


def _grounded(idea):
    return _strength(idea) >= 1


def _gate_on(pool):
    return getattr(pool, "ev", None) is not None or any(i.get("evidence") or i.get("contra") for i in pool.ideas)


def _ready_ev(self, k=5):
    base = _ready_before_ev(self, k=len(self.ideas) + 1)          # externally reviewed, no pending critic attack
    if _gate_on(self):                                            # data-first is in use on this pool
        base = [i for i in base if _grounded(i) and not any(c["status"] == "PENDING" for c in i.get("contra", []))]
    return sorted(base, key=lambda i: (-self.score(i), i["id"]))[:k]


def _score_ev(self, idea):
    s = _score_before_ev(self, idea)
    return s if s < 0 else s + STRENGTH_BONUS * min(STRENGTH_CAP, _strength(idea))


def ground_tags(idea):
    """What the idea rests on, in the shape the Outcomes ledger learns from."""
    ev = idea.get("evidence", [])
    return {"prov": sorted({c["provenance"] for c in ev if c["level"] >= 2}), "max_level": max((c["level"] for c in ev), default=0),
            "sources": _strength(idea), "contra_answered": sum(c["status"] == "SURVIVED" for c in idea.get("contra", [])),
            "restates": bool(idea.get("restates"))}


def grounding(self):
    """How much of the work rests on checked reality vs the model's head, and how much of what is ready is new."""
    live = [i for i in self.ideas if i["status"] != "KILLED"]
    rdy = _ready_ev(self, k=len(self.ideas) + 1)
    declared = [i for i in live if not _grounded(i) and any(c["level"] == 1 for c in i.get("evidence", []))]
    return {"gate": "on" if _gate_on(self) else "off (no ledger attached, nothing cited)",
            "live": len(live), "verified_grounded": sum(_grounded(i) for i in live),
            "declared_only": len(declared), "from_head": sum(not i.get("evidence") for i in live),
            "pending_contra": len(self.pending_contra()), "ready": len(rdy),
            "restatements": sorted(i["id"] for i in rdy if i.get("restates")),
            "novel_ready": sorted(i["id"] for i in rdy if not i.get("restates")),
            "strength": {i["id"]: _strength(i) for i in rdy}}


IdeaPool.add = _pool_add_ev
IdeaPool.ready = _ready_ev
IdeaPool.score = _score_ev
IdeaPool.attach = attach
IdeaPool.cite = cite
IdeaPool.answer_contra = answer_contra
IdeaPool.pending_contra = pending_contra
IdeaPool.grounding = grounding


class Plan:
    """Phases with stop/continue criteria fixed in advance, a pre-mortem that must be covered, and an outside
    critic for the plan itself.

        pl = Plan("goal in one line")
        pl.premortem("nobody uses it", signal="weekly_users", p=0.4)
        pl.phase("pilot", "10 real users try it", budget=14, kill_if=["weekly_users < 5"], continue_if=["weekly_users >= 10"])
        pl.start()                       # refuses while a failure cause is not watched by any stop rule
        pl.report("pilot", {"weekly_users": 3}, spent=9)   # -> KILL / PIVOT / CONTINUE / HOLD
    """

    def __init__(self, goal, path=None):
        self.data = {"goal": str(goal)[:400], "causes": [], "phases": [], "frozen": None, "log": [], "moves": [],
                     "packets": {}, "current": None}
        self.path = path

    # ------------------------------------------------------------------ building
    def premortem(self, cause, signal, p=0.3, phase=""):
        """One reason the plan failed, imagined BEFORE starting. signal = the metric that would show it early."""
        if not _re_plan.match(r"^[A-Za-z_][\w.]*$", str(signal)):
            raise ValueError("signal must be a metric name you will actually measure, e.g. 'weekly_users'")
        c = {"n": len(self.data["causes"]) + 1, "cause": str(cause)[:240], "signal": signal, "p": float(p),
             "phase": phase, "source": "self", "accepted": None}
        self.data["causes"].append(c)
        return c["n"]

    def phase(self, name, deliverable, budget, kill_if, continue_if, fallback=None):
        if self.data["frozen"]:
            raise RuntimeError("plan is started; add phases with amend_phase() so the change is logged")
        if any(p["name"] == name for p in self.data["phases"]):
            raise ValueError(f"phase {name!r} exists")
        if not kill_if or not continue_if:
            raise ValueError("every phase needs at least one kill_if AND one continue_if criterion")
        self.data["phases"].append({"name": name, "deliverable": str(deliverable)[:240], "budget": float(budget),
                                    "kill_if": [_crit(c) for c in kill_if], "continue_if": [_crit(c) for c in continue_if],
                                    "fallback": fallback, "state": "PLANNED", "spent": 0.0, "reports": []})

    def _ph(self, name):
        for p in self.data["phases"]:
            if p["name"] == name:
                return p
        raise KeyError(name)

    def watched(self):
        return {c["metric"] for p in self.data["phases"] for c in p["kill_if"]}

    def uncovered(self):
        """Failure causes no stop rule watches and nobody accepted in writing."""
        w = self.watched()
        return [c for c in self.data["causes"] if c["accepted"] is None and c["signal"] not in w]

    def accept(self, n, reason):
        if len(str(reason).strip()) < 10:
            raise ValueError("write the real reason you accept this risk (at least a sentence)")
        self.data["causes"][n - 1]["accepted"] = str(reason)[:240]

    def problems(self):
        out = []
        if len(self.data["causes"]) < 3:
            out.append(f"pre-mortem has {len(self.data['causes'])} causes; write at least 3 before starting")
        if not self.data["phases"]:
            out.append("no phases")
        for c in self.uncovered():
            out.append(f"cause {c['n']} ({c['cause'][:60]}) is not watched: add a kill_if on '{c['signal']}' or accept() it")
        for p in self.data["phases"]:
            if p["fallback"] and p["fallback"] not in [q["name"] for q in self.data["phases"]]:
                out.append(f"phase {p['name']}: fallback {p['fallback']!r} does not exist")
        return out

    def _fingerprint(self):
        import hashlib, json
        rules = [(p["name"], p["budget"], [c["text"] for c in p["kill_if"]], [c["text"] for c in p["continue_if"]])
                 for p in self.data["phases"]]
        return hashlib.sha256(json.dumps(rules).encode()).hexdigest()[:12]

    def start(self):
        pr = self.problems()
        if pr:
            raise RuntimeError("plan not ready:\n- " + "\n- ".join(pr))
        self.data["frozen"] = self.data["seal"] = self._fingerprint()
        self.data["current"] = self.data["phases"][0]["name"]
        self.data["phases"][0]["state"] = "RUNNING"
        self.save()
        return self.data["frozen"]

    # ------------------------------------------------------------------ changes after start
    def amend_phase(self, name, reason, kill_if=None, continue_if=None, budget=None):
        """Change a phase after start. Adding stop rules or raising the bar is allowed and logged. Removing a stop
        rule, loosening its threshold, lowering the continue bar or raising the budget of a RUNNING phase is a
        goalpost move: refused."""
        if not self.data["frozen"]:
            raise RuntimeError("plan not started; edit freely with phase()")
        p = self._ph(name)
        new_k = [_crit(c) for c in kill_if] if kill_if is not None else p["kill_if"]
        new_c = [_crit(c) for c in continue_if] if continue_if is not None else p["continue_if"]
        new_b = float(budget) if budget is not None else p["budget"]
        loosened = []
        for old in p["kill_if"]:
            same = [c for c in new_k if c["metric"] == old["metric"] and c["op"] == old["op"]]
            if not same:
                loosened.append(f"removed stop rule '{old['text']}'")
            elif old["op"] in ("<", "<=") and max(c["value"] for c in same) < old["value"]:
                loosened.append(f"loosened '{old['text']}'")
            elif old["op"] in (">", ">=") and min(c["value"] for c in same) > old["value"]:
                loosened.append(f"loosened '{old['text']}'")
        for old in p["continue_if"]:
            same = [c for c in new_c if c["metric"] == old["metric"] and c["op"] == old["op"]]
            if not same:
                loosened.append(f"removed continue bar '{old['text']}'")
            elif old["op"] in (">", ">=") and min(c["value"] for c in same) < old["value"]:
                loosened.append(f"lowered '{old['text']}'")
            elif old["op"] in ("<", "<=") and max(c["value"] for c in same) > old["value"]:
                loosened.append(f"lowered '{old['text']}'")
        if p["state"] in ("RUNNING", "DONE", "KILLED") and new_b > p["budget"]:
            loosened.append(f"budget {p['budget']} -> {new_b} on a phase already {p['state']}")
        if loosened and p["state"] != "PLANNED":
            raise RuntimeError("goalpost move refused: " + "; ".join(loosened) +
                               ". If reality changed, kill this phase and write a new plan with a new pre-mortem.")
        self.data["moves"].append({"phase": name, "reason": str(reason)[:240], "loosened": loosened,
                                   "kill_if": [c["text"] for c in new_k], "continue_if": [c["text"] for c in new_c], "budget": new_b})
        p["kill_if"], p["continue_if"], p["budget"] = new_k, new_c, new_b
        self.data["seal"] = self._fingerprint()
        self.save()

    # ------------------------------------------------------------------ decisions
    def report(self, name, metrics, spent):
        """Report measured numbers for the running phase. Returns (decision, why)."""
        if not self.data["frozen"]:
            raise RuntimeError("start() the plan first: criteria must be fixed before results exist")
        p = self._ph(name)
        if p["state"] != "RUNNING":
            raise RuntimeError(f"phase {name} is {p['state']}, not RUNNING")
        p["spent"] = float(spent)
        m = {k: float(v) for k, v in metrics.items()}
        hit = [c["text"] for c in p["kill_if"] if c["metric"] in m and _OPS[c["op"]](m[c["metric"]], c["value"])]
        miss_k = [c["metric"] for c in p["kill_if"] if c["metric"] not in m]
        bar = [c for c in p["continue_if"] if c["metric"] in m and _OPS[c["op"]](m[c["metric"]], c["value"])]
        over = p["spent"] >= p["budget"]
        if hit:
            decision, why = ("PIVOT" if p["fallback"] else "KILL"), "stop rule hit: " + "; ".join(hit)
        elif miss_k:
            decision, why = ("KILL", f"budget spent and stop signals never measured: {miss_k}") if over else \
                            ("HOLD", f"measure these before deciding: {miss_k}")
        elif len(bar) == len(p["continue_if"]):
            decision, why = "CONTINUE", "continue bar met: " + "; ".join(c["text"] for c in bar)
        elif over:
            decision, why = "KILL", f"budget {p['budget']:g} spent and the continue bar is not met"
        else:
            decision, why = "HOLD", f"no stop rule hit, bar not met yet; {p['budget'] - p['spent']:g} budget left"
        p["reports"].append({"metrics": m, "spent": p["spent"], "decision": decision, "why": why})
        self.data["log"].append({"phase": name, "decision": decision, "why": why})
        names = [q["name"] for q in self.data["phases"]]
        if decision == "CONTINUE":
            p["state"] = "DONE"
            nxt = names.index(name) + 1
            self.data["current"] = names[nxt] if nxt < len(names) else None
            if self.data["current"]:
                self._ph(self.data["current"])["state"] = "RUNNING"
        elif decision == "KILL":
            p["state"], self.data["current"] = "KILLED", None
        elif decision == "PIVOT":
            p["state"] = "KILLED"
            self.data["current"] = p["fallback"]
            self._ph(p["fallback"])["state"] = "RUNNING"
        self.save()
        return decision, why

    def status(self):
        d = self.data
        print(f"PLAN: {d['goal']}  [frozen {d['frozen'] or 'no'}; now: {d['current'] or '-'}]")
        for p in d["phases"]:
            print(f"  {p['state']:<8} {p['name']}: {p['deliverable']}  (budget {p['budget']:g}, spent {p['spent']:g})")
            print(f"           stop if {' OR '.join(c['text'] for c in p['kill_if'])} | go on if {' AND '.join(c['text'] for c in p['continue_if'])}")
        for c in d["causes"]:
            mark = "accepted" if c["accepted"] else ("watched" if c["signal"] in self.watched() else "NOT WATCHED")
            print(f"  cause {c['n']} [{c['source']}, p={c['p']:.2f}, {mark}] {c['cause']}  <- signal: {c['signal']}")
        if d["moves"]:
            print(f"  amendments: {len(d['moves'])}")
        return [p["state"] for p in d["phases"]]

    # ------------------------------------------------------------------ outside critic for the plan
    def packet(self, author="", path=None):
        """Seal the plan for an INDEPENDENT critic: goal + phases with their rules. Your pre-mortem is NOT sent,
        so whatever the critic finds is measured against it (echo check)."""
        import hashlib, json
        items = [{"id": f"C{i}", "text": f"PHASE {p['name']}: {p['deliverable']} | budget {p['budget']:g} | stop if "
                  f"{' OR '.join(c['text'] for c in p['kill_if'])} | go on if {' AND '.join(c['text'] for c in p['continue_if'])}",
                  "prediction": ""} for i, p in enumerate(self.data["phases"], 1)]
        pid = hashlib.sha256(json.dumps([self.data["goal"], items]).encode()).hexdigest()[:12]
        pkt = {"packet": pid, "kind": "plan", "brief": "GOAL: " + self.data["goal"] +
               "\nFor a plan, a KILL means: a concrete way this phase fails or wastes the budget that its stop rules "
               "would NOT catch. Put the measurable early signal in 'test'.", "items": items, "author": author}
        pkt["prompt"] = critic_prompt(pkt)
        pkt["runner"] = "#CRITIC\n" + json.dumps({k: pkt[k] for k in ("packet", "kind", "brief", "items", "author")})
        self.data["packets"][pid] = {"key": {it["id"]: p["name"] for it, p in zip(items, self.data["phases"])}, "author": author}
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({k: pkt[k] for k in ("packet", "kind", "brief", "items", "author")}, f, ensure_ascii=False, indent=1)
        return pkt

    def ingest(self, reply, source):
        """Every independent KILL becomes a new failure cause (source = the critic). It blocks nothing until you
        give it a signal with watch(n, metric, phase, rule) or accept(n, reason); until then uncovered() lists it."""
        d = _critic_json(reply) if isinstance(reply, str) else reply
        if not d or str(d.get("packet")) not in self.data["packets"]:
            raise ValueError("reply has no json 'reviews' block for a packet sent from this plan")
        meta = self.data["packets"][str(d["packet"])]
        independent = source.strip().lower() not in ("self", "", meta["author"].strip().lower())
        rep = {"source": source, "independent": independent, "new_causes": [], "echo": 0}
        own = [c["cause"] for c in self.data["causes"] if c["source"] == "self"]
        for r in d.get("reviews", []):
            if str(r.get("id")) not in meta["key"] or not str(r.get("verdict", "")).upper().startswith("K"):
                continue
            text = f"{r.get('failure_case', '')}"
            if not independent or any(_overlap(text, o) >= 0.6 for o in own):
                rep["echo"] += 1
                continue
            self.data["causes"].append({"n": len(self.data["causes"]) + 1, "cause": text[:240], "signal": "",
                                        "p": float(r.get("confidence", 0.5) or 0.5), "phase": meta["key"][str(r["id"])],
                                        "source": source, "accepted": None, "critic_test": str(r.get("test", ""))[:240]})
            rep["new_causes"].append(len(self.data["causes"]))
        self.save()
        return rep

    def watch(self, n, metric, phase, rule):
        """Cover cause n: give it a measurable signal and add the stop rule to that phase (a tightening: allowed
        after start)."""
        c = self.data["causes"][n - 1]
        crit = _crit(rule)
        if crit["metric"] != metric:
            raise ValueError("the rule must be on the cause's signal metric")
        c["signal"] = metric
        p = self._ph(phase)
        if self.data["frozen"]:
            self.amend_phase(phase, f"watch cause {n}", kill_if=[x["text"] for x in p["kill_if"]] + [rule])
        else:
            p["kill_if"].append(crit)

    # ------------------------------------------------------------------ persistence
    def save(self):
        if self.path:
            import json
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path):
        import json
        pl = cls("", path=path)
        with open(path, encoding="utf-8") as f:
            pl.data = json.load(f)
        if pl.data["frozen"] and pl.data.get("seal") != pl._fingerprint():
            raise RuntimeError("plan rules were edited by hand after start (seal mismatch, no logged amendment)")
        return pl

# =============================================================================================== memory across sessions (v4)
class Memory:
    """Which representation worked for which kind of problem - kept across conversations.

    Saved as JSON in the outputs folder (download it, attach it next time). Laplace-smoothed success rates rank
    representations for a new problem by its feature tags, so priors accumulate instead of resetting."""

    def __init__(self, path=None):
        import json
        import os
        self.json, self.os = json, os
        self.path = path or self._default_path()
        self.data = {"records": [], "calibration": []}
        found = self._find_existing()
        if found:
            with open(found, encoding="utf-8") as f:
                self.data = json.load(f)
            self.data.setdefault("calibration", [])

    @staticmethod
    def _default_path():
        import os
        for d in ("/mnt/user-data/outputs", "/mnt/outputs", "."):
            if os.path.isdir(d) and os.access(d, os.W_OK):
                return os.path.join(d, "amp_memory.json")
        return "amp_memory.json"

    def _find_existing(self):
        import glob
        for pat in (self.path, "/mnt/user-data/uploads/*amp_memory*.json", "/mnt/**/*amp_memory*.json"):
            hits = glob.glob(pat, recursive=True)
            if hits:
                return hits[0]
        return None

    def record(self, tags, representation, outcome, note=""):
        """tags: short feature words (e.g. ['count', 'huge-n', 'local-rule']); outcome: 'solved' | 'failed'."""
        self.data["records"].append({"tags": sorted(set(tags)), "rep": representation, "ok": outcome == "solved", "note": note[:120]})
        self.save()

    def suggest(self, tags, k=5):
        tags = set(tags)
        stats = defaultdict(lambda: [0.0, 0.0])
        for r in self.data["records"]:
            w = len(tags & set(r["tags"])) / max(1, len(tags | set(r["tags"])))
            if w > 0:
                stats[r["rep"]][0] += w * r["ok"]
                stats[r["rep"]][1] += w
        ranked = sorted(((rep, (s + 1) / (n + 2), n) for rep, (s, n) in stats.items()), key=lambda t: -t[1])
        for rep, p, n in ranked[:k]:
            print(f"memory: {rep}  success~{p:.2f} (weight {n:.1f})")
        return ranked[:k]

    def predict(self, claim, probability):
        """Calibration: commit a probability BEFORE checking; resolve later. Builds a track record of judgement."""
        self.data["calibration"].append({"claim": claim[:160], "p": float(probability), "true": None})
        self.save()
        return len(self.data["calibration"]) - 1

    def resolve(self, idx, came_true):
        self.data["calibration"][idx]["true"] = bool(came_true)
        self.save()

    def calibration(self):
        done = [c for c in self.data["calibration"] if c["true"] is not None]
        if not done:
            print("calibration: no resolved predictions yet")
            return None
        brier = sum((c["p"] - c["true"]) ** 2 for c in done) / len(done)
        print(f"calibration: {len(done)} resolved, Brier score {brier:.3f} (0 = perfect, 0.25 = coin flip)")
        return brier

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            self.json.dump(self.data, f, indent=1)


# =============================================================================================== v6: calibrated compute controller
# The mechanism: every open item carries an evidence level E0..E4. The probability that an answer at level E is
# right is NOT assumed - it is read from a calibration table learned from GRADED outcomes of earlier sessions
# (Beta-smoothed, per task kind, shrunk towards the pooled table). Effort goes to the item with the highest
# expected points gained per unit of compute:   priority = value * q(kind, E) * (p(kind, E+1) - p(kind, E)) / cost
# where q = learned chance that an escalation attempt from E actually reaches E+1 (decays after failed attempts).
# Greedy marginal-gain allocation is optimal for this budgeted problem when returns per item diminish.

DEFAULT_P = {0: 0.25, 1: 0.50, 2: 0.70, 3: 0.90, 4: 0.96}     # prior P(correct | E) before any feedback
DEFAULT_Q = {0: 0.80, 1: 0.70, 2: 0.55, 3: 0.35}             # prior P(escalation E -> E+1 succeeds)
PRIOR_STRENGTH = 4.0                                          # pseudo-observations behind each prior value


def _mem_table(mem, key):
    return [] if mem is None else mem.data.setdefault(key, [])


def calibrated_p(mem, kind, E):
    """P(correct | kind, E) = Beta posterior: prior DEFAULT_P[E], then pooled outcomes, then kind-specific ones."""
    E = max(0, min(4, int(E)))
    a, b = PRIOR_STRENGTH * DEFAULT_P[E], PRIOR_STRENGTH * (1 - DEFAULT_P[E])
    rows = [r for r in _mem_table(mem, "evidence") if int(r["E"]) == E]
    pooled = [r for r in rows if r.get("kind") != kind]
    own = [r for r in rows if r.get("kind") == kind]
    a += 0.5 * sum(r["ok"] for r in pooled)                   # other kinds count half (partial pooling)
    b += 0.5 * sum(not r["ok"] for r in pooled)
    a += sum(r["ok"] for r in own)
    b += sum(not r["ok"] for r in own)
    return a / (a + b)


def calibrated_q(mem, kind, E):
    E = max(0, min(3, int(E)))
    a, b = PRIOR_STRENGTH * DEFAULT_Q[E], PRIOR_STRENGTH * (1 - DEFAULT_Q[E])
    for r in _mem_table(mem, "escalations"):
        if int(r["from"]) == E:
            w = 1.0 if r.get("kind") == kind else 0.5
            a += w * r["ok"]
            b += w * (not r["ok"])
    return a / (a + b)


class Controller:
    """Evidence-ledger compute controller.  ctl = Controller(mem); ctl.add('Q1', 'I', value=1) ...
    loop:  i = ctl.next()  -> work on i  -> ctl.attempt(i, reached_E)  ... until ctl.done()
    final: ctl.ledger() -> {"Q1": {"E": 3, "p": 0.93}, ...}  (put it in the answer JSON as "_ledger")."""

    def __init__(self, mem=None, eps=0.01):
        self.mem, self.eps, self.items = mem, eps, {}

    def add(self, iid, kind, value=1.0, E=0, cost=1.0):
        self.items[iid] = {"kind": kind, "value": float(value), "E": int(E), "cost": float(cost), "fails": 0}

    def p(self, iid):
        it = self.items[iid]
        return calibrated_p(self.mem, it["kind"], it["E"])

    def priority(self, iid):
        it = self.items[iid]
        if it["E"] >= 4:
            return 0.0
        q = calibrated_q(self.mem, it["kind"], it["E"]) * 0.5 ** it["fails"]
        gain = calibrated_p(self.mem, it["kind"], it["E"] + 1) - calibrated_p(self.mem, it["kind"], it["E"])
        return it["value"] * q * max(gain, 0.0) / max(it["cost"], 1e-9)

    def next(self, show=3):
        ranked = sorted(self.items, key=lambda i: -self.priority(i))
        for i in ranked[:show]:
            it = self.items[i]
            print(f"ctl: {i:6s} kind {it['kind']} E{it['E']} p={self.p(i):.2f} priority={self.priority(i):.4f}")
        return ranked[0] if ranked and self.priority(ranked[0]) > self.eps else None

    def attempt(self, iid, reached_E, cost=None):
        """Report the result of one escalation attempt: reached_E = evidence level now held."""
        it = self.items[iid]
        ok = int(reached_E) > it["E"]
        _mem_table(self.mem, "escalations").append({"kind": it["kind"], "from": it["E"], "ok": ok})
        if ok:
            it["E"], it["fails"] = int(reached_E), 0
        else:
            it["fails"] += 1
        if cost is not None:
            it["cost"] = float(cost)
        if self.mem is not None:
            self.mem.save()

    def done(self):
        return self.next(show=0) is None

    def ledger(self):
        return {i: {"E": it["E"], "p": round(self.p(i), 3), "kind": it["kind"]} for i, it in self.items.items()}

    def expected_score(self):
        return sum(it["value"] * self.p(i) for i, it in self.items.items())


def _memory_ingest(self, path=None):
    """Load graded feedback (amp_feedback*.json produced by the grader) into the calibration table, once per run."""
    import glob
    import json
    paths = [path] if path else sorted(set(glob.glob("/mnt/user-data/uploads/*amp_feedback*.json") + glob.glob("/mnt/**/*amp_feedback*.json", recursive=True)))
    seen = set(self.data.setdefault("ingested", []))
    added = 0
    for pth in paths:
        try:
            fb = json.load(open(pth, encoding="utf-8"))
        except Exception:
            continue
        for run in fb.get("runs", []):
            if run["run"] in seen:
                continue
            seen.add(run["run"])
            for row in run["items"]:
                self.data.setdefault("evidence", []).append({"kind": row["kind"], "E": int(row["E"]), "ok": bool(row["ok"])})
                added += 1
    self.data["ingested"] = sorted(seen)
    if added:
        self.save()
        print(f"memory: ingested {added} graded outcomes from feedback")
    return added


def _memory_table(self):
    """Print the learned P(correct | E) per kind - how much each evidence level can actually be trusted."""
    kinds = sorted({r["kind"] for r in self.data.get("evidence", [])}) or ["*"]
    for k in kinds:
        print(f"calib {k}: " + "  ".join(f"E{e}={calibrated_p(self, k, e):.2f}" for e in range(5)))


Memory.ingest = _memory_ingest
Memory.table = _memory_table


# =============================================================================================== v6.1: attested independence
# Problem with every "two methods agree" check: agreement is worth little when the two methods can fail TOGETHER
# (same helper with the same bug, same representation, method B reusing method A's numbers). Model-level
# correlation can be measured after the fact; here it is PREDICTED BEFORE any outcome from the executed checks:
#   1. Registry.check runs each verification method in isolation under a profiler and records an attested,
#      hash-chained evidence record: bytecode fingerprint, every non-stdlib function actually called, input and
#      output hashes, and lineage (did this method consume another method's outputs?).
#   2. For every agreeing pair of methods it computes independence features from those records
#      (structural similarity, shared-callee overlap, lineage, same representation class).
#   3. A correlated-failure model P(both agree AND both wrong | features, kind) - a logistic model with a prior
#      that is updated from graded outcomes across sessions - turns agreement into a calibrated probability.
#   4. The evidence level is DERIVED from the record (not self-reported), the next check is DESIGNED to cut the
#      predicted shared-failure mode (which callees to avoid, which class to use), and effort goes to the item
#      with the largest predicted drop in error per unit cost.
#   5. certificate() exports the chain; verify_certificate() lets anyone recheck it and re-derive every level.
import dis as _dis
import hashlib as _hashlib
import json as _json
import sys as _sys

PAIR_FEATURES = ("struct_sim", "shared_callees", "lineage", "same_class", "same_source")
# same_source = both methods came from the SAME generator (same model / same temperature). Two methods from one
# model tend to make the SAME mistake, so their agreement is weak evidence however different the code looks - this
# is the correlated-failure hole that sinks a "two methods agree" rule when both methods are the model's own.
PAIR_PRIOR = {"bias": -3.0, "struct_sim": 2.0, "shared_callees": 2.5, "lineage": 4.0, "same_class": 1.5, "same_source": 1.5}
PAIR_PRIOR_PREC = 2.0          # strength of the prior (L2 towards PAIR_PRIOR) when fitting on graded pairs
ORACLE_FALSE_PASS = 0.15       # per-DISTINCT-case chance a held-out check passes a WRONG answer by luck
ORACLE_CORR_DECAY = 0.5        # held-out cases are NOT independent; each extra distinct case counts as < 1 (0 = all redundant)
EXTERNAL_ORACLE_FLOOR = 1e-4   # lowest risk an EXTERNAL oracle (given data / live target / official validator) may claim
SELF_ORACLE_FLOOR = 0.30       # a model-written reference shares the model's understanding: its risk cannot go below this
ORACLE_PROV = ("given", "live", "validator", "self")
EXTERNAL_PROV = {"given", "live", "validator"}     # truth that did NOT come from the model
_PROV_RANK = {"self": 0, "validator": 1, "given": 2, "live": 3}
INDEPENDENT = {"struct_sim": 0.65, "shared_callees": 0.5}   # E3 requires sim <= .65, shared <= .5, no lineage, other class
IDEAL_PAIR = {"struct_sim": 0.1, "shared_callees": 0.0, "lineage": 0, "same_class": 0}
_STD = ("/lib/python", "/lib64/python", "<frozen", "site-packages")


def _h(x):
    return _hashlib.sha256(x if isinstance(x, bytes) else repr(x).encode()).hexdigest()


def _opgrams(fn):
    code = getattr(fn, "__code__", None)
    if code is None:
        return set()
    ops = []

    def walk(c):
        for ins in _dis.get_instructions(c):
            ops.append(ins.opname)
        for k in c.co_consts:
            if hasattr(k, "co_code"):
                walk(k)
    walk(code)
    return {"|".join(ops[i:i + 3]) for i in range(max(0, len(ops) - 2))}


def _jac(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def _traced(fn, args):
    called = set()
    own = getattr(fn, "__code__", None)

    def prof(frame, event, arg):
        if event == "call":
            co = frame.f_code
            if co is not own and not any(s in co.co_filename for s in _STD) and not co.co_name.startswith("<"):
                called.add(co.co_name)
    old = _sys.getprofile()
    _sys.setprofile(prof)
    try:
        out = fn(*args)
    finally:
        _sys.setprofile(old)
    return out, called


def _sigmoid(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def pair_weights(mem=None):
    """MAP logistic weights for P(agree-but-wrong | pair features): prior PAIR_PRIOR, updated from graded pairs."""
    w = dict(PAIR_PRIOR)
    rows = [] if mem is None else mem.data.get("pairs", [])
    if not rows:
        return w
    keys = ["bias"] + list(PAIR_FEATURES)
    for _ in range(200):                                   # Newton-free: damped gradient ascent on the MAP objective
        g = {k: -PAIR_PRIOR_PREC * (w[k] - PAIR_PRIOR[k]) for k in keys}
        for r in rows:
            x = {"bias": 1.0, **{f: float(r.get(f, 0.0)) for f in PAIR_FEATURES}}
            p = _sigmoid(sum(w[k] * x[k] for k in keys))
            for k in keys:
                g[k] += (float(r["wrong"]) - p) * x[k]
        for k in keys:
            w[k] += 0.05 * g[k] / max(1.0, len(rows) / 10)
    return w


def pair_risk(feat, mem=None, w=None):
    w = w or pair_weights(mem)
    return _sigmoid(w["bias"] + sum(w.get(f, PAIR_PRIOR.get(f, 0.0)) * float(feat.get(f, 0.0)) for f in PAIR_FEATURES))


_ORACLE_SRC_PROV = {"given": "given", "live": "live", "validator": "live"}   # validator output comes via #LIVE


def _oracle_provenance(claimed, holdout, ev, src):
    """('ok', src_sha, receipt) if the external provenance is backed by a checkable source, else (reason, None, '')."""
    if ev is None or src is None:
        return (f"provenance='{claimed}' needs ev= and src= naming the sealed source the held-out pairs come from; "
                "a bare word is a declaration", None, "")
    s = getattr(ev, "sources", {}).get(src)
    if s is None:
        return f"source {src!r} is not sealed in ev", None, ""
    if s["provenance"] != _ORACLE_SRC_PROV[claimed]:
        return f"source {src!r} is {s['provenance']}, a '{claimed}' oracle needs a {_ORACLE_SRC_PROV[claimed]} source", None, ""
    if not s.get("attested"):
        return f"source {src!r} provenance is not proven: {s.get('prov_check')}", None, ""
    toks = s.get("tokens") or []
    missing = sum(not case_in_tokens(case_tokens(a, w), toks) for a, w in holdout)
    if missing or not holdout:
        return (f"{missing}/{len(holdout)} held-out pairs are NOT in source {src!r}: they were written, not given",
                None, "")
    return "ok", s["sha256"], s.get("receipt", "")


class Registry:
    """Attested verification registry.
        reg = Registry(mem)
        reg.check('Q1', 'brute', brute, [(n,) for n in range(1, 12)], kind='I')       # method 1
        reg.check('Q1', 'transfer-matrix', fast, [(n,) for n in range(1, 12)])        # method 2, written blind
        reg.answer('Q1', fast_value)             # the reported answer (attested too)
        reg.status('Q1')   -> level, p(correct), agreeing pairs with their risk, what the next check must avoid
        reg.next()         -> the item where one more independent check buys the most
        reg.ledger()       -> {"Q1": {"E", "p", "pairs"}} for "_ledger";  reg.certificate() -> hash chain"""

    def __init__(self, mem=None):
        self.mem, self.records, self.head = mem, [], "0" * 64
        self._vals, self._grams, self._kinds, self._answers, self._reasons, self._cost = {}, {}, {}, {}, set(), {}
        self._constraints, self._oracle = {}, {}
        self.w = pair_weights(mem)

    # -------------------------------------------------------------- recording
    def _append(self, rec):
        rec["prev"] = self.head
        rec["hash"] = _h(self.head + _json.dumps(rec, sort_keys=True, default=str))
        self.head = rec["hash"]
        self.records.append(rec)
        return rec

    def check(self, item, cls, fn, inputs, kind=None, cost=1.0, resources=None, source="self"):
        """resources: names of external things the method consumed besides code (documents, tools, data sources,
        model endpoints). They join the callee set, so two checks that read the same source count as dependent.
        source: who produced this method - "self" (this model), "model:<name>" (a different model / temperature),
        or "oracle" (an external ground truth; prefer Registry.oracle() for that). Two checks with the same source
        are treated as liable to fail together, however different their code looks."""
        if kind:
            self._kinds[item] = kind
        inputs = [tuple(a) if isinstance(a, (list, tuple)) else (a,) for a in inputs]
        prev = [r for r in self.records if r.get("item") == item and r["type"] == "check"]
        spec = {ih for r in prev for ih, _ in r["io"]}                # the shared problem inputs are not lineage
        earlier = {oh for r in prev for _, oh in r["io"]} - spec
        outs, called, t0 = [], set(), time.time()
        for args in inputs:
            o, c = _traced(fn, args)
            outs.append(o)
            called |= c
        lineage = any(_h(a) in earlier for args in inputs for a in args if _h(args) not in spec and _h(a) not in spec)
        called |= {f"res:{r}" for r in (resources or [])}
        con = self._constraints.get(item)
        compliance = None
        if con:
            hit = sorted(set(con["forbid_callees"]) & called)
            compliance = {"constraint": con["hash"], "complies": not hit and cls not in con["forbid_classes"] and not lineage,
                          "violations": hit + ([f"class:{cls}"] if cls in con["forbid_classes"] else []) + (["lineage"] if lineage else [])}
        rec = self._append({"type": "check", "item": item, "kind": self._kinds.get(item), "cls": cls, "source": source,
                            "method": getattr(fn, "__name__", "?"), "code": _h(getattr(getattr(fn, "__code__", None), "co_code", b"")),
                            "callees": sorted(called), "io": [[_h(a), _h(o)] for a, o in zip(inputs, outs)],
                            "lineage": lineage, "seconds": round(time.time() - t0, 3), "compliance": compliance})
        if compliance is not None and not compliance["complies"]:
            print(f"reg: {item} check '{rec['method']}' VIOLATES the design constraint: {compliance['violations']}")
        self._vals[rec["hash"]] = outs
        self._grams[rec["hash"]] = _opgrams(fn)
        self._cost[item] = self._cost.get(item, 0) + float(cost)
        return outs

    def constrain(self, item):
        """Closed loop: turn the predicted shared-failure mode into a binding design constraint for the NEXT check.
        Recorded in the chain; the next check() is tested for compliance automatically."""
        cs = self._checks(item)
        agree = [p for p in self.pairs(item) if p["agree"]]
        if agree:
            best = min(agree, key=lambda p: p["risk"])
            forbid = set(best["shared"])
            classes = {r["cls"] for r in cs if r["method"] in (best["a"], best["b"])}
            before = best["risk"]
        else:
            forbid = {c for r in cs for c in r["callees"]}
            classes = {r["cls"] for r in cs}
            before = 1 - calibrated_p(self.mem, self._kinds.get(item, "*"), 1 if cs else 0)
        after = pair_risk(IDEAL_PAIR, w=self.w)
        rec = self._append({"type": "constraint", "item": item, "forbid_callees": sorted(forbid),
                            "forbid_classes": sorted(classes), "forbid_lineage": True,
                            "predicted_risk_before": round(before, 4), "predicted_risk_after": round(after, 4)})
        self._constraints[item] = rec
        print(f"reg: next check for {item} must not call {sorted(forbid) or '-'}, must not use class {sorted(classes) or '-'}, "
              f"must not read earlier outputs (predicted risk {before:.3f} -> {after:.3f})")
        return rec

    def answer(self, item, value):
        self._answers[item] = value
        self._append({"type": "answer", "item": item, "value": _h(value)})

    def reason(self, item, text):
        self._reasons.add(item)
        self._append({"type": "reason", "item": item, "text": _h(text)})

    # -------------------------------------------------------------- analysis
    def _checks(self, item):
        return [r for r in self.records if r["type"] == "check" and r["item"] == item]

    def pairs(self, item):
        cs, out = self._checks(item), []
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = cs[i], cs[j]
                ia, ib = dict(a["io"]), dict(b["io"])
                common = set(ia) & set(ib)
                if not common:
                    continue
                agree = all(ia[k] == ib[k] for k in common)
                sa, sb = a.get("source", "self"), b.get("source", "self")
                feat = {"struct_sim": round(_jac(self._grams.get(a["hash"], ()), self._grams.get(b["hash"], ())), 3),
                        "shared_callees": round(_jac(set(a["callees"]) - {a["method"], b["method"]},
                                                     set(b["callees"]) - {a["method"], b["method"]}), 3),
                        "lineage": int(a["lineage"] or b["lineage"]), "same_class": int(a["cls"] == b["cls"]),
                        "same_source": int(sa == sb and not (sa == "oracle"))}
                bad = any((r.get("compliance") or {}).get("complies") is False for r in (a, b))
                out.append({"a": a["method"], "b": b["method"], "agree": agree, "common": len(common), **feat, "noncompliant": bad,
                            "oracle": "oracle" in (sa, sb), "risk": round(pair_risk(feat, w=self.w), 4),
                            "shared": sorted((set(a["callees"]) & set(b["callees"])) - {a["method"], b["method"]})})
        return out

    def oracle(self, item, predict, holdout, provenance="self", kind=None, cls="oracle", note="", ev=None, src=None):
        """Check `predict` against held-out (input, known_output) cases. provenance says WHERE the known outputs
        came from, and that is what decides how much the check is worth - because a check is only external truth if
        its answers did not come from the same mind that produced `predict`:
          "given"     - example pairs SHIPPED WITH THE PROBLEM (induction demos, spec I/O) -> external, can reach E3
          "live"      - a live system / real executable answered (e.g. the real server, the reference binary) -> external
          "validator" - an OFFICIAL validator that came with the task scored it -> external
          "self"      - a reference YOU wrote (a brute force, a reimplementation). NOT external: if you misread the
                        problem, your brute and your fast method misread it together. Caps the item at E2 on its own.
        Returns the number of held-out cases that passed. Hold-out cases must be ones `predict` was NOT built on.
        v6.6 - provenance is CHECKED, not declared: an external provenance needs ev= and src= naming a sealed source
        of PROVEN provenance ('given': a problem file; 'live'/'validator': a runner-receipted #LIVE output), and every
        held-out pair must appear in that source's text. Otherwise the check is counted as 'self' (caps at E2)."""
        if kind:
            self._kinds[item] = kind
        holdout = [((h[0] if isinstance(h[0], (list, tuple)) else (h[0],)), h[1]) for h in holdout]
        claimed = provenance if provenance in ORACLE_PROV else "self"
        pcheck, src_sha, receipt = "", None, ""
        if claimed in EXTERNAL_PROV:
            pcheck, src_sha, receipt = _oracle_provenance(claimed, holdout, ev, src)
            if pcheck != "ok":
                print(f"reg: {item} provenance '{claimed}' NOT accepted -> counted as 'self' ({pcheck})")
                provenance = "self"
        passed, oks = 0, []
        for args, want in holdout:
            try:
                ok = predict(*args) == want
            except Exception:
                ok = False
            passed += ok
            oks.append(ok)
        n = len(holdout)
        distinct = len({_h(w) for (a, w), ok in zip(holdout, oks) if ok})   # cases with the SAME answer are not extra evidence
        prov = provenance if provenance in ORACLE_PROV else "self"
        rec = self._append({"type": "oracle", "item": item, "kind": self._kinds.get(item), "cls": cls, "source": "oracle",
                            "provenance": prov, "prov_claimed": claimed, "prov_check": pcheck or "n/a",
                            "src": src, "src_sha": src_sha, "receipt": receipt,
                            "cases": [case_tokens(a, w) for a, w in holdout] if prov in EXTERNAL_PROV else [],
                            "n_holdout": n, "passed": passed, "distinct": distinct,
                            "io": [[_h(a), _h(w)] for a, w in holdout], "note": _h(note), "all_pass": passed == n and n > 0})
        prev = self._oracle.get(item)
        cur = {"n": n, "passed": passed, "distinct": distinct, "prov": prov, "rec": rec["hash"]}
        # keep the STRONGEST verified oracle for the item (external beats self); a failing oracle always overrides
        if passed < n:
            self._oracle[item] = cur
        elif prev is None or prev["passed"] < prev["n"] or _PROV_RANK[prov] >= _PROV_RANK[prev["prov"]]:
            self._oracle[item] = cur
        ext = "EXTERNAL" if prov in EXTERNAL_PROV else "self-written (caps at E2)"
        print(f"reg: {item} oracle[{prov}] on {n} held-out cases ({distinct} distinct): {passed}/{n} pass"
              + (f"  -> VERIFIED, {ext}" if passed == n and n > 0 else "  -> FAILS, answer is wrong"))
        return passed

    def oracle_risk(self, item):
        """P(a verified item is still wrong). Correlation-aware: cases sharing an output add little; a self-written
        reference cannot drop below a floor (it shares the model's understanding). None if not verified."""
        o = self._oracle.get(item)
        if not o or o["passed"] < o["n"] or o["n"] == 0:
            return None
        eff = 1 + ORACLE_CORR_DECAY * (max(1, o["distinct"]) - 1)      # correlated held-out cases are discounted
        risk = ORACLE_FALSE_PASS ** eff
        floor = SELF_ORACLE_FLOOR if o["prov"] not in EXTERNAL_PROV else EXTERNAL_ORACLE_FLOOR
        return round(max(risk, floor), 6)

    def oracle_external(self, item):
        o = self._oracle.get(item)
        return bool(o and o["passed"] == o["n"] and o["n"] > 0 and o["prov"] in EXTERNAL_PROV)

    def level(self, item):
        cs, ps = self._checks(item), self.pairs(item)
        o = self._oracle.get(item)
        if o and o["passed"] < o["n"]:
            return 1                                                  # oracle says the answer is wrong: do not trust it
        if self.oracle_external(item):                                # truth from OUTSIDE the model agrees on held-out cases
            return 4 if item in self._reasons else 3
        if not cs:
            return 2 if self.oracle_risk(item) is not None else 0     # a self-written oracle alone: at most E2
        if any(not p["agree"] for p in ps):
            return 1                                                  # a live disagreement caps the level
        # E3 by agreement needs a pair that is independent AND NOT from the same generator (cross-source / oracle)
        indep = [p for p in ps if p["agree"] and not p["lineage"] and not p["same_class"] and not p["noncompliant"]
                 and not p["same_source"]
                 and p["struct_sim"] <= INDEPENDENT["struct_sim"] and p["shared_callees"] <= INDEPENDENT["shared_callees"]]
        if indep:
            return 4 if item in self._reasons else 3
        return 2 if any(p["agree"] for p in ps) else 1

    def oracle_backed(self, item):
        return self.oracle_external(item)                 # "oracle-backed" means EXTERNAL truth, not a self-written reference

    def p_correct(self, item):
        kind = self._kinds.get(item, "*")
        orisk = self.oracle_risk(item)
        o = self._oracle.get(item)
        if o and o["passed"] < o["n"]:
            return round(ORACLE_FALSE_PASS ** max(0, o["passed"]) * 0.3, 4)   # oracle rejected it: almost certainly wrong
        ps = [p for p in self.pairs(item) if p["agree"]]
        cand = [] if orisk is None else [orisk]
        cand += [p["risk"] for p in ps]
        if any(not p["agree"] for p in self.pairs(item)) and orisk is None:
            return min(0.5, calibrated_p(self.mem, kind, 1))
        if not cand:
            return calibrated_p(self.mem, kind, self.level(item))
        return round(1 - min(cand), 4)                                # the single most trustworthy check decides

    def status(self, item):
        ps = self.pairs(item)
        best = min((p for p in ps if p["agree"]), key=lambda p: p["risk"], default=None)
        avoid = best["shared"] if best else []
        orisk = self.oracle_risk(item)
        o = self._oracle.get(item)
        if orisk is not None:
            otag = f"  ORACLE[{o['prov']}]-VERIFIED (risk {orisk:.4f}" + ("" if o["prov"] in EXTERNAL_PROV else ", self-written -> capped at E2") + ")"
        elif o and o["passed"] < o["n"]:
            otag = "  ORACLE-REJECTED (answer is wrong)"
        else:
            otag = ""
        print(f"{item}: E{self.level(item)}  p={self.p_correct(item):.3f}  checks={len(self._checks(item))}{otag}")
        for p in ps:
            print(f"   {p['a']} ~ {p['b']}: {'agree' if p['agree'] else 'DISAGREE'} on {p['common']}  sim={p['struct_sim']} "
                  f"shared={p['shared_callees']} lineage={p['lineage']} same_class={p['same_class']} same_source={p['same_source']} -> risk {p['risk']}")
        if orisk is None and not any(p.get("oracle") for p in ps):
            print("   NOTE: no external oracle yet. Agreement between the model's own methods can be a shared mistake. "
                  "Prefer reg.oracle(...) on held-out cases, or a second source (source='model:B').")
        ideal = pair_risk(IDEAL_PAIR, w=self.w)
        if best and best["risk"] > ideal + 0.005:
            print(f"   next check: new representation class, avoid callees {avoid or '-'}, no reuse of earlier outputs "
                  f"(predicted risk {best['risk']:.3f} -> {ideal:.3f})")
        return {"E": self.level(item), "p": self.p_correct(item), "pairs": ps}

    def next(self, items=None, value=None, show=3):
        items = items or sorted({r["item"] for r in self.records if r.get("item")})
        ideal = 1 - pair_risk(IDEAL_PAIR, w=self.w)
        gains = []
        for it in items:
            p = self.p_correct(it) if self._checks(it) else calibrated_p(self.mem, self._kinds.get(it, "*"), 0)
            v = (value or {}).get(it, 1.0)
            cost = max(1.0, self._cost.get(it, 1.0) / max(1, len(self._checks(it))))
            gains.append((v * max(0.0, ideal - p) / cost, it, p))
        gains.sort(reverse=True)
        for g, it, p in gains[:show]:
            print(f"reg: {it:6s} p={p:.3f} gain/cost={g:.4f}")
        return gains[0][1] if gains and gains[0][0] > 1e-3 else None

    def ledger(self):
        items = sorted({r["item"] for r in self.records if r.get("item")} | set(self._oracle))
        return {it: {"E": self.level(it), "p": round(self.p_correct(it), 4), "kind": self._kinds.get(it),
                     "oracle": self.oracle_backed(it),                 # True only for EXTERNAL truth
                     "oracle_prov": (self._oracle.get(it) or {}).get("prov"),     # the CHECKED provenance, not the claim
                     "pairs": [[p[f] for f in PAIR_FEATURES] + [int(p["agree"])] for p in self.pairs(it)]} for it in items}

    def certificate(self):
        return {"version": "amp-6.3", "head": self.head, "records": self.records}


def verify_certificate(cert):
    """Recompute the hash chain. Returns (intact, first_bad_index). Anyone can run this on a published certificate."""
    head = "0" * 64
    for i, rec in enumerate(cert["records"]):
        body = {k: v for k, v in rec.items() if k != "hash"}
        if body.get("prev") != head or _h(head + _json.dumps(body, sort_keys=True, default=str)) != rec["hash"]:
            return False, i
        head = rec["hash"]
    return head == cert["head"], None


def attest_certificate(cert, given_texts=(), receipts=None, receipt_ok=None):
    """Re-check every EXTERNAL oracle in a Registry certificate with the checker's OWN material, after the run.
        given_texts : the problem files exactly as delivered (runner: uploads; grader: the kit's PART files)
        receipts    : {receipt_id: output_text} from the runner's own #LIVE log (Track B only)
        receipt_ok  : callable(receipt_str) -> bool that checks the receipt mac with the runner's key
    Returns {"intact", "proven": [items], "unproven": {item: reason}}. An item is proven only if some all-pass oracle
    record for it has external provenance whose source sha256 is a real given file / a real logged output AND whose
    held-out pairs are literally in that text. Nothing the model declared is taken on its word."""
    intact = verify_certificate(cert)[0]
    given = {_h(t.encode("utf-8")): _toks(t) for t in given_texts}
    logged = {rid: (_h(t.encode("utf-8")), _toks(t)) for rid, t in (receipts or {}).items()}
    proven, unproven = set(), {}
    for rec in cert.get("records", []):
        if rec.get("type") != "oracle" or rec.get("provenance") not in EXTERNAL_PROV or not rec.get("all_pass"):
            continue
        it, prov, sha, why = rec.get("item"), rec["provenance"], rec.get("src_sha"), ""
        toks = None
        if not intact:
            why = "certificate hash chain broken"
        elif prov == "given":
            toks = given.get(sha)
            why = "" if toks is not None else "source sha256 is not a problem file"
        else:
            rc = _parse_receipt(rec.get("receipt"))
            if rc is None or rc[0] not in logged:
                why = "no receipt from the runner's log"
            elif logged[rc[0]][0] != sha or rc[1] != sha:
                why = "receipt does not match the logged output"
            elif receipt_ok is None or not receipt_ok(rec.get("receipt")):
                why = "receipt mac invalid (forged)"
            else:
                toks = logged[rc[0]][1]
        if not why and not all(case_in_tokens(c, toks) for c in rec.get("cases") or [[[], []]]):
            why = "held-out pairs are not in the source text"
        if why:
            unproven.setdefault(it, why)
        else:
            proven.add(it)
    return {"intact": intact, "proven": sorted(proven),
            "unproven": {k: v for k, v in unproven.items() if k not in proven}}


def attest_evidence(cert, given_texts=(), receipts=None, receipt_ok=None):
    """Same re-check for an Evidence certificate: which sealed sources are really a problem file / a runner-logged
    output, and which L2 facts quote a source that is NOT. Returns {"intact", "sources": {name: why or 'ok'},
    "facts_unproven": [n, ...]}."""
    intact = verify_certificate(cert)[0]
    given = {_h(t.encode("utf-8")) for t in given_texts}
    logged = {rid: _h(t.encode("utf-8")) for rid, t in (receipts or {}).items()}
    srcs = {}
    for rec in cert.get("records", []):
        if rec.get("type") != "source":
            continue
        sha, prov = rec.get("sha256"), rec.get("provenance")
        if not intact:
            srcs[rec["name"]] = "certificate hash chain broken"
        elif prov == "given":
            srcs[rec["name"]] = "ok" if sha in given else "not a problem file"
        else:
            rc = _parse_receipt(rec.get("receipt"))
            good = (rc is not None and logged.get(rc[0]) == sha == rc[1] and receipt_ok is not None
                    and receipt_ok(rec.get("receipt")))
            srcs[rec["name"]] = "ok" if good else "no valid runner receipt for this text"
    bad = [r["n"] for r in cert.get("records", []) if r.get("type") == "evidence" and r.get("level", 0) >= 2
           and srcs.get(r.get("src")) != "ok"]
    return {"intact": intact, "sources": srcs, "facts_unproven": bad}


def _memory_ingest_pairs(self, fb_runs):
    for run in fb_runs:
        for row in run.get("items", []):
            for pr in row.get("pairs", []):
                if len(pr) == len(PAIR_FEATURES) + 1 and pr[-1]:      # agreeing pairs only
                    self.data.setdefault("pairs", []).append({**dict(zip(PAIR_FEATURES, pr[:-1])), "wrong": not row["ok"]})


_old_ingest = Memory.ingest


def _memory_ingest_v61(self, path=None):
    import glob
    added = _old_ingest(self, path)
    paths = [path] if path else sorted(set(glob.glob("/mnt/user-data/uploads/*amp_feedback*.json") + glob.glob("/mnt/**/*amp_feedback*.json", recursive=True)))
    seen = set(self.data.setdefault("ingested_pairs", []))
    for pth in paths:
        try:
            fb = _json.load(open(pth, encoding="utf-8"))
        except Exception:
            continue
        new = [r for r in fb.get("runs", []) if r["run"] not in seen]
        _memory_ingest_pairs(self, new)
        seen |= {r["run"] for r in new}
    self.data["ingested_pairs"] = sorted(seen)
    self.save()
    return added


Memory.ingest = _memory_ingest_v61


# =============================================================================================== v6.3: oracle-first superiority
# The governing fact: a scaffold that only ORGANISES thinking lifts the strong model as much as the weak one, so the
# strong model stays ahead. A weak model can PASS a strong one only where the answer is checked from OUTSIDE the model
# - executing a synthesised program on held-out cases, a strict validator, a live target - because then being right
# stops depending on the model's priors. These helpers make that the default path and keep the honest scope.

# Which task kinds admit an EXTERNAL oracle (truth from outside the model), and what counts as that oracle.
# Superiority over a stronger model is claimed ONLY on oracle-rich kinds, and ONLY via external provenance.
ORACLE_KIND = {
    "G": ("given", "hold out example pairs SHIPPED WITH THE PROBLEM and verify on them (provenance='given')"),
    "P": ("given", "run on inputs whose outputs the spec/examples give, or against a live reference (provenance='given'/'live')"),
    "C": ("validator", "an official / self-contained strict validator scores the object (provenance='validator')"),
}
# I (insight) is NOT listed: its usual check is a brute force the MODEL writes, which shares the model's reading of
# the problem (provenance='self') and so caps at E2 - a wrong reading makes brute and fast wrong together. Insight
# only becomes oracle-rich when the problem ships sample values to anchor the brute to (then that subset is 'given').
# J (ideas/taste) is NOT oracle-rich from the solver's side: the hidden scorer is not visible while solving.
ORACLE_RICH = set(ORACLE_KIND)


def oracle_rich(kind):
    return kind in ORACLE_RICH


def synthesize_verify(train, holdout, builders, select=None):
    """Program synthesis as an oracle, for ANY task that gives examples (induction, transforms, program-rebuild).
        train    = [(input, output), ...]  cases the program may be built / selected on
        holdout  = [(input, output), ...]  cases kept ASIDE; passing them is the external evidence
        builders = iterable of candidate callables input->output (e.g. from search_programs, or hand-written)
    Returns (best_program_or_None, train_fit, holdout_pass, n_holdout). best is None when NO candidate reproduces
    every train case - a program that does not even fit the examples it was built on must be REJECTED, not applied
    to the queries. The caller does reg.oracle(item, best, holdout, provenance='given') only when best is not None.
    Guarantee: holdout is never used to choose the program, so a holdout pass is real out-of-sample evidence."""
    def fit(f, cases):
        n = 0
        for a, b in cases:
            try:
                n += f(*((a,) if not isinstance(a, (list, tuple)) else a)) == b
            except Exception:
                pass
        return n
    consistent = [(fit(f, train), f) for f in builders]
    consistent = [(n, f) for n, f in consistent if n == len(train)]    # ONLY programs that fit every train case
    if not consistent:
        return None, 0, 0, len(holdout)                                # reject: no program fits the examples
    _, f = (select or (lambda fs: max(fs, key=lambda nf: nf[0])))(consistent)
    return f, fit(f, train), fit(f, holdout), len(holdout)


class StepChain:
    """Step-level verification: the answer is only as trustworthy as its FIRST unverified step. Each step carries a
    check that returns True/False (ideally an external oracle: a computed value, a validator, a re-derivation).
        sc = StepChain('Q1')
        sc.step('reduced mod p', check=lambda: fast(10) % p == brute(10) % p)
        sc.step('period = 34', check=lambda: verify_period(seq, 34), oracle=reg)   # external only if reg proved it
        sc.cut()   -> index of the first step whose check failed or is missing (len = all verified)
        sc.p()     -> product of per-step reliabilities up to the cut (one bad early step collapses the whole chain)"""
    def __init__(self, item, mem=None, p_true=0.98, p_oracle=0.995, p_unchecked=0.6):
        self.item, self.steps = item, []
        # Reliabilities are LEARNED from graded outcomes when available (mem.data['step_rel']), else these priors.
        d = (mem.data.get("step_rel") if mem is not None else None) or {}
        self.p_true = float(d.get("self_checked", p_true))
        self.p_oracle = float(d.get("external", p_oracle))
        self.p_unchecked = float(d.get("unchecked", p_unchecked))

    def step(self, name, check=None, oracle=False):
        ok = None
        if check is not None:
            try:
                ok = bool(check())
            except Exception:
                ok = False
        # v6.6: oracle=True is a declaration and counts as a self check. A step is external only when oracle=reg and
        # reg holds a CHECKED external oracle for this item (provenance proven, held-out pairs found in the source).
        ext = bool(oracle is not True and oracle and hasattr(oracle, "oracle_external") and oracle.oracle_external(self.item))
        self.steps.append({"name": name, "ok": ok, "oracle": ext, "oracle_declared": oracle is True})
        return self

    def cut(self):
        for i, s in enumerate(self.steps):
            if s["ok"] is not True:
                return i
        return len(self.steps)

    def p(self):
        prod = 1.0
        for s in self.steps[: self.cut() + 1]:
            if s["ok"] is True:
                prod *= self.p_oracle if s["oracle"] else self.p_true
            else:
                prod *= self.p_unchecked
                break
        return round(prod, 4)

    def show(self):
        c = self.cut()
        for i, s in enumerate(self.steps):
            mark = "ok " if s["ok"] is True else ("BAD" if s["ok"] is False else " ? ")
            print(f"  [{mark}] step {i}: {s['name']}" + ("   <- chain cut here; nothing after this is trusted" if i == c and c < len(self.steps) else ""))
        print(f"  chain p={self.p()} (verified through step {c}/{len(self.steps)})")
        return self.p()


# =============================================================================================== reality's verdict (v6.5)
# Every gate so far ends INSIDE the session: the critic, the evidence ledger and the plan all decide before the
# world has answered. The idea engine therefore learns nothing about which of its own habits produce ideas that
# HOLD UP: Memory learns which representation solved a graded exact task, never whether an idea was good. This
# ledger closes that loop, as the output twin of the evidence ledger (B is what came in, A is what reality did):
#   1. ship(): an idea you present as tested is recorded WITH the probability you give it now, the operator /
#      domain that generated it, what grounded it and what the critic did. Commitment before the verdict.
#   2. resolve(): only an EXTERNAL verdict counts (an official grader, a live metric, a decision by someone outside).
#      R2 = verified (a sealed fact from the evidence ledger, or the official grader file), R1 = declared external,
#      R0 = your own judgement (stored, teaches nothing). A verdict can only be replaced by a STRONGER source, so
#      results cannot be re-rolled until they look good.
#   3. Learning: Beta-smoothed success rates per generator tag, pooled toward the global rate. edge_cells,
#      projections and pool.parents take outcomes=oc and give their EXTRA picks to what reality rewarded, while
#      every operator and domain still appears (exploration never drops to zero).
#   4. Honesty measures: reality_blind_spot (shipped-as-ready ideas reality killed, with a worst case that counts
#      overdue unresolved ships as failures, so ignoring bad news cannot hide it), calibration of your p, and
#      pipeline(): do gated / grounded / independently-reviewed ideas actually hold up better than the rest?
# Persistence: amp_outcomes.json, append-only hash chain, checked on load. A broken chain disables learning.

import re as _re_out

OUTCOME_PROV = ("given", "live", "validator", "published", "self")
OUTCOME_EXTERNAL = {"given", "live", "validator", "published"}
R_WEIGHT = {0: 0.0, 1: 0.5, 2: 1.0}          # how much a verdict teaches: own judgement nothing, declared half
OUT_PRIOR = 2.0                              # pseudo-observations pulling each tag toward the global rate
_OPS_SET = set(ASSUMPTION_OPS)
_DOM_SET = {r[0] for r in PATTERN_BANK}


def gen_tags(pool, idea, _seen=None):
    """Generator tags of an idea: the operators / domains named in origin or target, inherited from its parents."""
    seen = _seen if _seen is not None else set()
    if idea["id"] in seen:
        return set()
    seen.add(idea["id"])
    toks = set(_re_out.split(r"[^a-z]+", f"{idea.get('origin', '')} {idea.get('target', '')}".lower()))
    t = {f"op:{x}" for x in toks & _OPS_SET} | {f"dom:{x}" for x in toks & _DOM_SET}
    for p in idea.get("parents", []):
        t |= gen_tags(pool, pool.ideas[p - 1], seen)
    return t


def _out_default_path():
    for d in ("/mnt/user-data/outputs", "/mnt/outputs", "."):
        if _os_ev.path.isdir(d) and _os_ev.access(d, _os_ev.W_OK):
            return _os_ev.path.join(d, "amp_outcomes.json")
    return "amp_outcomes.json"


class Outcomes:
    """What reality did to the ideas you shipped, across conversations.

        oc = Outcomes(); oc.ingest()              # earlier ledger + official grader verdicts, if attached
        sid = oc.ship(pool, idea_id, p=0.6)       # only pool.ready() ideas (gate=False records it as UNGATED)
        oc.resolve(sid, held=True, provenance='live', ev=ev, fact=n)   # R2: a verified fact from the evidence ledger
        oc.report()                               # blind spot, calibration, what the pipeline is worth, what to explore
        edge_cells(assumptions, outcomes=oc); projections(outcomes=oc); pool.parents(outcomes=oc)
    """

    def __init__(self, path=None, session=None, load=True):
        self.path = path or _out_default_path()
        self.data = {"version": "amp-outcomes-6.5", "head": "0" * 64, "records": []}
        self.session = session or _h(f"{time.time()}{random.random()}")[:10]
        self.tampered = None
        found = self._find_existing() if load else None
        if found:
            with open(found, encoding="utf-8") as f:
                d = _json.load(f)
            ok, bad = verify_certificate(d)
            if not ok:
                self.tampered = bad if bad is not None else len(d.get("records", []))
                print(f"outcomes: CHAIN BROKEN at record {self.tampered} of {found}: learning is DISABLED for this ledger")
            self.data = d
        self._index()

    def _find_existing(self):
        import glob
        for pat in (self.path, "/mnt/user-data/uploads/*amp_outcomes*.json", "/mnt/**/*amp_outcomes*.json"):
            hits = sorted(glob.glob(pat, recursive=True))
            if hits:
                return hits[0]
        return None

    def _index(self):
        self.ships, self.res = {}, {}
        for r in self.data["records"]:
            if r["type"] == "ship":
                self.ships[r["sid"]] = r
            elif r["type"] == "resolve":
                if r["sid"] not in self.res or r["level"] > self.res[r["sid"]]["level"]:
                    self.res[r["sid"]] = r

    def _append(self, rec):
        rec["prev"] = self.data["head"]
        rec["hash"] = _h(self.data["head"] + _json.dumps(rec, sort_keys=True, default=str))
        self.data["head"] = rec["hash"]
        self.data["records"].append(rec)
        return rec

    def save(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                _json.dump(self.data, f, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ commit
    def ship(self, pool, idea_id, p, kind="J", due_days=30, gate=True, note=""):
        """Record an idea you present as tested, with P(it holds in reality) committed NOW."""
        if not 0.0 <= float(p) <= 1.0:
            raise ValueError("p is your probability that the idea holds up in reality, between 0 and 1")
        idea = pool.ideas[idea_id - 1]
        if idea["status"] == "KILLED":
            raise ValueError(f"idea {idea_id} is KILLED; a dead idea is not shipped")
        gated = idea_id in {i["id"] for i in pool.ready(k=len(pool.ideas) + 1)}
        if gate and not gated:
            raise ValueError(f"idea {idea_id} is not in pool.ready(); ship it with gate=False to record it as UNGATED "
                             "(kept apart, so the ledger can measure what the gates are worth)")
        sid = _h(_norm(idea["text"]) + "|" + _norm(idea["prediction"]))[:12]
        if sid in self.ships:
            print(f"outcomes: {sid} already shipped")
            return sid
        g = ground_tags(idea)
        n_ind = sum(1 for r in idea.get("ext", []) if r["independent"])     # reviews by an independent critic
        tags = gen_tags(pool, idea) | {"gen:evolved" if idea.get("gen", 1) > 1 else "gen:first", f"kind:{kind}",
                                        "gate:ready" if gated else "gate:ungated",
                                        "critic:independent" if n_ind else "critic:none",
                                        "novel:no" if g["restates"] else "novel:yes"}
        tags |= {f"ground:{x}" for x in g["prov"]} or {"ground:none"}
        now = time.time()
        self._append({"type": "ship", "sid": sid, "text": idea["text"], "prediction": idea["prediction"], "p": float(p),
                      "kind": kind, "gated": gated, "tags": sorted(tags), "ground": g,
                      "critic": {"independent_reviews": n_ind, "attacks_survived": idea.get("ext_survived", 0),
                                 "attacks": len(idea.get("ext", []))},
                      "session": self.session, "t": now, "due": now + 86400 * float(due_days), "note": str(note)[:200]})
        self._index()
        self.save()
        print(f"outcomes: shipped {sid} p={float(p):.2f} [{'ready' if gated else 'UNGATED'}] {idea['text'][:60]}")
        return sid

    # ------------------------------------------------------------------ reality answers
    def resolve(self, sid, held, provenance="self", score=None, ref="", ev=None, fact=None, note="", _grader=False):
        """Record what reality did. Only a stronger source may replace an earlier verdict."""
        if sid not in self.ships:
            raise ValueError(f"{sid!r} was never shipped from this ledger")
        prov = provenance if provenance in OUTCOME_PROV else "self"
        level, why = 0, "own judgement: stored, teaches nothing"
        fact_hash = ""
        if prov in OUTCOME_EXTERNAL:
            level, why = 1, "external by declaration: cite a verified fact (ev=, fact=) to make it R2"
            if _grader:
                level, why = 2, "official grader verdict file"
            elif ev is not None and fact is not None:
                r = ev.refs.get(fact)
                if r is None:
                    raise ValueError(f"evidence #{fact} does not exist")
                if r["level"] >= 2:
                    level, why, fact_hash = 2, f"verified fact #{fact} ({r['provenance']})", r["hash"]
                else:
                    why = f"fact #{fact} is only L{r['level']}: not verified, verdict stays R1"
        old = self.res.get(sid)
        if old is not None and level <= old["level"]:
            raise ValueError(f"{sid} already resolved at R{old['level']} ({'held' if old['held'] else 'failed'}); only a "
                             "STRONGER source can replace it (no re-rolling a verdict until it looks good)")
        self._append({"type": "resolve", "sid": sid, "held": bool(held), "score": score, "provenance": prov,
                      "level": level, "ref": str(ref)[:240], "fact": fact_hash, "why": why, "session": self.session,
                      "t": time.time(), "note": str(note)[:200]})
        self._index()
        self.save()
        print(f"outcomes: {sid} -> {'HELD' if held else 'FAILED'} R{level} [{prov}] ({why})")
        return level

    def ingest(self, path=None):
        """Official verdicts written by the grader (amp_feedback*.json, key 'outcomes'): resolved at R2, once."""
        import glob
        paths = [path] if path else sorted(set(glob.glob("/mnt/user-data/uploads/*amp_feedback*.json") +
                                               glob.glob("/mnt/**/*amp_feedback*.json", recursive=True)))
        n = 0
        for pth in paths:
            try:
                with open(pth, encoding="utf-8") as f:
                    fb = _json.load(f)
            except Exception:
                continue
            for o in fb.get("outcomes", []):
                sid = o.get("sid")
                if sid in self.ships and (self.res.get(sid) or {}).get("level", -1) < 2:
                    self.resolve(sid, bool(o.get("held")), provenance="validator", score=o.get("gain"),
                                 ref=f"{o.get('run', '')}:{o.get('task', '')}", _grader=True)
                    n += 1
        return n

    # ------------------------------------------------------------------ learning
    def _done(self, min_level=1):
        return [(self.ships[s], r) for s, r in self.res.items() if r["level"] >= min_level and s in self.ships]

    def _global(self):
        d = self._done()
        s = sum(R_WEIGHT[r["level"]] * r["held"] for _, r in d)
        n = sum(R_WEIGHT[r["level"]] for _, r in d)
        return (s + 1) / (n + 2), n

    def _post(self, tag):
        g, _ = self._global()
        s = n = 0.0
        if self.tampered is None:
            for sh, r in self._done():
                if tag in sh["tags"]:
                    w = R_WEIGHT[r["level"]]
                    s += w * r["held"]
                    n += w
        return OUT_PRIOR * g + s, OUT_PRIOR * (1 - g) + (n - s), n

    def rates(self, prefix=""):
        """{tag: (posterior success rate, weighted evidence)} for tags starting with prefix (e.g. 'op:', 'dom:')."""
        if self.tampered is not None:
            print("outcomes: ledger chain is broken; no learned rates")
            return {}
        tags = sorted({t for sh in self.ships.values() for t in sh["tags"] if t.startswith(prefix)})
        out = {}
        for t in tags:
            a, b, n = self._post(t)
            out[t] = (round(a / (a + b), 3), round(n, 2))
        return out

    def weights(self, prefix, names, rng=None):
        """Thompson-sampled weight per name (an op or a domain). No data -> sampled from the pooled prior."""
        rng = rng or random.Random(0)
        out = {}
        for nm in names:
            a, b, _ = self._post(f"{prefix}{nm}")
            out[nm] = rng.betavariate(max(a, 1e-3), max(b, 1e-3))
        return out

    def multiplier(self, tags):
        """How much more (or less) often ideas with these generator tags held up, vs the global rate. Clipped [0.5, 2]."""
        g, _ = self._global()
        ms = []
        for t in tags:
            if t.startswith(("op:", "dom:")):
                a, b, _ = self._post(t)
                ms.append((a / (a + b)) / g)
        return max(0.5, min(2.0, sum(ms) / len(ms))) if ms else 1.0

    # ------------------------------------------------------------------ honesty measures
    def pending(self):
        now = time.time()
        return [{"sid": s, "text": sh["text"][:60], "overdue": now > sh["due"], "p": sh["p"]}
                for s, sh in self.ships.items() if (self.res.get(s) or {}).get("level", 0) < 1]

    def reality_blind_spot(self):
        """Share of ideas shipped as READY that reality then killed (weighted by verdict strength). worst_case also
        counts overdue unresolved ready ships as failures: not looking at bad news cannot shrink this number."""
        d = [(sh, r) for sh, r in self._done() if sh["gated"]]
        n = sum(R_WEIGHT[r["level"]] for _, r in d)
        f = sum(R_WEIGHT[r["level"]] * (not r["held"]) for _, r in d)
        crit = [(sh, r) for sh, r in d if sh["critic"]["independent_reviews"] > 0]
        cn = sum(R_WEIGHT[r["level"]] for _, r in crit)
        cf = sum(R_WEIGHT[r["level"]] * (not r["held"]) for _, r in crit)
        over = sum(1 for p in self.pending() if p["overdue"] and self.ships[p["sid"]]["gated"])
        return {"observed": round(f / n, 3) if n else None, "worst_case": round((f + over) / (n + over), 3) if n + over else None,
                "critic_passed_reality_failed": round(cf / cn, 3) if cn else None, "weight": round(n, 2), "overdue": over}

    def calibration(self):
        d = [(sh["p"], float(r["held"]), R_WEIGHT[r["level"]]) for sh, r in self._done()]
        W = sum(w for *_, w in d)
        if not W:
            return {"n": 0, "brier": None, "gap": None, "bins": []}
        brier = sum(w * (p - y) ** 2 for p, y, w in d) / W
        gap = sum(w * (p - y) for p, y, w in d) / W              # > 0: you are overconfident
        bins = []
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            b = [(p, y, w) for p, y, w in d if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
            bw = sum(w for *_, w in b)
            if bw:
                bins.append({"p": f"{lo:.1f}-{lo + 0.2:.1f}", "said": round(sum(w * p for p, _, w in b) / bw, 2),
                             "held": round(sum(w * y for _, y, w in b) / bw, 2), "weight": round(bw, 2)})
        return {"n": len(d), "brier": round(brier, 4), "gap": round(gap, 3), "bins": bins}

    def adjust(self, p):
        """Your raw p corrected by your measured over/under-confidence, shrunk by how much evidence there is."""
        c = self.calibration()
        if not c["n"] or self.tampered is not None:
            return float(p)
        W = sum(R_WEIGHT[r["level"]] for _, r in self._done())
        return round(min(0.99, max(0.01, float(p) - c["gap"] * W / (W + 10))), 3)

    def pipeline(self):
        """Do the gates pay off in reality? Success rate of each side of each gate, with its evidence weight."""
        def rate(pred):
            d = [(sh, r) for sh, r in self._done() if pred(sh)]
            n = sum(R_WEIGHT[r["level"]] for _, r in d)
            return (round(sum(R_WEIGHT[r["level"]] * r["held"] for _, r in d) / n, 3) if n else None, round(n, 2))
        return {"ready vs ungated": (rate(lambda s: s["gated"]), rate(lambda s: not s["gated"])),
                "grounded vs from-head": (rate(lambda s: s["ground"]["sources"] > 0), rate(lambda s: s["ground"]["sources"] == 0)),
                "critic-reviewed vs not": (rate(lambda s: s["critic"]["independent_reviews"] > 0),
                                           rate(lambda s: s["critic"]["independent_reviews"] == 0)),
                "novel vs restates": (rate(lambda s: not s["ground"]["restates"]), rate(lambda s: s["ground"]["restates"]))}

    def coverage(self):
        ext = sum(1 for s in self.ships if (self.res.get(s) or {}).get("level", 0) >= 1)
        return {"shipped": len(self.ships), "resolved_external": ext,
                "self_only": sum(1 for s in self.ships if (self.res.get(s) or {}).get("level") == 0)}

    def report(self):
        if self.tampered is not None:
            print(f"outcomes: CHAIN BROKEN at record {self.tampered}; nothing below is learned")
        cov, bs, cal = self.coverage(), self.reality_blind_spot(), self.calibration()
        print(f"outcomes: {cov['shipped']} shipped, {cov['resolved_external']} judged by reality, {cov['self_only']} self-judged only")
        print(f"  reality blind spot: observed {bs['observed']}  worst case {bs['worst_case']}  "
              f"(critic passed, reality failed: {bs['critic_passed_reality_failed']}; overdue {bs['overdue']})")
        print(f"  calibration: Brier {cal['brier']}  gap {cal['gap']} (>0 = overconfident)  " +
              "  ".join(f"{b['p']}: said {b['said']} held {b['held']}" for b in cal["bins"]))
        for k, ((a, na), (b, nb)) in self.pipeline().items():
            print(f"  {k}: {a} (w {na}) vs {b} (w {nb})")
        r = self.rates("op:")
        r.update(self.rates("dom:"))
        if r:
            print("  generators: " + "  ".join(f"{t} {m}" for t, (m, n) in sorted(r.items(), key=lambda kv: -kv[1][0]) if n))
        return {"coverage": cov, "blind_spot": bs, "calibration": cal, "pipeline": self.pipeline()}

    def certificate(self):
        return dict(self.data)


# ------------------------------------------------------------------ generators learn from reality
_edge_cells_v4, _projections_v4, _parents_v4 = edge_cells, projections, IdeaPool.parents


def edge_cells(assumptions, k=12, seed=0, ops=None, outcomes=None):
    """Balanced (assumption, operator) cells. With outcomes=oc, ties in the balanced design go to the operators
    whose ideas held up in reality (Thompson-sampled), so the EXTRA cells follow evidence; every operator still
    appears before any repeats once k >= the number of operators."""
    if outcomes is None or outcomes.tampered is not None:
        return _edge_cells_v4(assumptions, k=k, seed=seed, ops=ops)
    ops = list(ops or ASSUMPTION_OPS)
    rng = random.Random(seed)
    w = outcomes.weights("op:", ops, rng)
    pairs = [(a, o) for a in assumptions for o in ops]
    rng.shuffle(pairs)
    use_a, use_o, chosen = Counter(), Counter(), []
    while len(chosen) < min(k, len(pairs)):
        a, o = min((p for p in pairs if p not in chosen),
                   key=lambda p: (use_a[p[0]] + use_o[p[1]], use_o[p[1]], -w[p[1]]))
        chosen.append((a, o))
        use_a[a] += 1
        use_o[o] += 1
    for i, (a, o) in enumerate(chosen, 1):
        print(f"E{i}. [{o} w{w[o]:.2f}] {a} -> {ASSUMPTION_OPS[o]}")
    return chosen


def projections(k=8, seed=0, domains=None, outcomes=None):
    """k cross-domain patterns, stratified. With outcomes=oc, domains are visited in order of a Thompson sample of
    their real success, so the domains that produced ideas reality kept get the extra picks."""
    if outcomes is None or outcomes.tampered is not None:
        return _projections_v4(k=k, seed=seed, domains=domains)
    rng = random.Random(seed)
    by = defaultdict(list)
    for row in PATTERN_BANK:
        if domains is None or row[0] in domains:
            by[row[0]].append(row)
    for v in by.values():
        rng.shuffle(v)
    w = outcomes.weights("dom:", sorted(by), rng)
    order = sorted(by, key=lambda d: -w[d])
    out, i = [], 0
    while len(out) < k and any(by.values()):
        d = order[i % len(order)]
        if by[d]:
            out.append(by[d].pop())
        i += 1
    for j, (dom, name, mech, q) in enumerate(out, 1):
        print(f"X{j}. {dom}/{name} [w{w[dom]:.2f}]: {mech}. -> {q}")
    return out


def _parents_out(self, k=2, seed=0, outcomes=None):
    """Recombination parents. With outcomes=oc, each elite's weight is scaled by how often ideas from its
    generators held up in reality (multiplier clipped to [0.5, 2], so session evidence still dominates)."""
    if outcomes is None or outcomes.tampered is not None:
        return _parents_v4(self, k=k, seed=seed)
    el = self.elites()
    if len(el) <= k:
        return el
    rng = random.Random(seed)
    weights = [max(0.1, self.score(i) + 1) * outcomes.multiplier(gen_tags(self, i)) for i in el]
    chosen = []
    while len(chosen) < k:
        pick = rng.choices(el, weights)[0]
        if pick not in chosen:
            chosen.append(pick)
    return chosen


IdeaPool.parents = _parents_out
