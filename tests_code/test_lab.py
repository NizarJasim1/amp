import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner"), _os.path.join(_B, "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)
import itertools, math, random, unittest
from fractions import Fraction
import amp_lab as L

class Seq(unittest.TestCase):
    def test_linear(self):
        fib = [0, 1]
        for _ in range(30): fib.append(fib[-1] + fib[-2])
        h = L.guess_linear(fib)
        self.assertEqual([int(c) for c in h["coeffs"]], [1, 1])
        self.assertEqual(L.lin_nth(h["coeffs"], fib[:2], 90), 2880067194370816120)
        self.assertEqual(L.lin_nth(h["coeffs"], fib[:2], 10**18, L.P2), L.lin_nth([1, 1], [0, 1], 10**18, L.P2))
        rng = random.Random(1); self.assertIsNone(L.guess_linear([rng.randint(0, 10**9) for _ in range(20)]))

    def test_poly_quasi_period(self):
        h = L.guess_poly([n**3 - 2*n for n in range(10)]); self.assertEqual(h["degree"], 3)
        self.assertEqual(h["f"](100), 100**3 - 200)
        q = L.guess_quasipoly([n * n // 2 for n in range(30)]); self.assertEqual(q["period"], 2)
        self.assertEqual(q["f"](1001), 1001 * 1001 // 2)
        seq = [0] * 7 + [i % 5 for i in range(60)]
        self.assertEqual(L.find_period(seq), (7, 5))
        flags = [x == 0 for x in seq] + [False] * 0
        self.assertEqual(L.periodic_count(flags, 7, 5, len(seq) - 1, start=1), sum(flags[1:]))

    def test_precursive(self):
        a = [1, 1, 0, 0, 2]
        for n in range(5, 25): a.append((n+1)*a[n-1]-(n-2)*a[n-2]-(n-5)*a[n-3]+(n-3)*a[n-4])
        h = L.guess_precursive(a[1:], max_order=4, max_degree=1, offset=1)
        self.assertIsNotNone(h)
        ref = [x % L.P2 for x in a]
        b = [1, 1, 0, 0, 2]
        for n in range(5, 3001): b.append(((n+1)*b[n-1]-(n-2)*b[n-2]-(n-5)*b[n-3]+(n-3)*b[n-4]) % L.P2)
        self.assertEqual(L.prec_nth(h, a[1:1 + h["order"] + 1], 3000, L.P2), b[3000])
        catalan = [math.comb(2*n, n) // (n + 1) for n in range(20)]
        hc = L.guess_precursive(catalan, max_order=1, max_degree=1)
        self.assertEqual(hc["order"], 1)

    def test_identify_runs(self):
        out = L.identify([2**n + n for n in range(20)], verbose=False)
        self.assertTrue(any(h["kind"] == "linear" for h in out))

class NT(unittest.TestCase):
    def test_sums(self):
        for N in (1, 10, 1000, 54321):
            self.assertEqual(L.totient_sum(N), sum(L.phi_upto(N)[1:]))
            self.assertEqual(L.mertens(N), sum(L.mu_upto(N)[1:]))
        self.assertEqual(L.totient_sum(10**8), 3039635516365908)
    def test_factor(self):
        n = 1000000007 * 998244353 * 2**5
        self.assertEqual(L.factorize(n), {2: 5, 998244353: 1, 1000000007: 1})
        self.assertEqual(L.euler_phi(36), 12)
        self.assertEqual(L.divisors(12), [1, 2, 3, 4, 6, 12])
        self.assertEqual(L.crt([2, 3], [3, 5]), (8, 15))

        self.assertEqual(L.binom_mod(10, 3, 7), math.comb(10, 3) % 7)
    def test_blocks(self):
        N = 1000
        self.assertEqual(sum((hi - lo + 1) * q for lo, hi, q in L.floor_blocks(N)), sum(N // k for k in range(1, N + 1)))

class LA(unittest.TestCase):
    def test_det_solve_markov(self):
        self.assertEqual(L.det_exact([[2, 1], [7, 4]]), 1)
        self.assertEqual(L.solve_exact([[2, 1], [1, 3]], [3, 5]), [Fraction(4, 5), Fraction(7, 5)])
        # gambler's ruin on 0..4 from 2 with fair coin: P(reach 4) = 1/2
        res = L.markov_absorb(range(5), lambda s: [(Fraction(1, 2), s - 1), (Fraction(1, 2), s + 1)],
                              lambda s: 1 if s == 4 else (0 if s == 0 else None))
        self.assertEqual(res[2], Fraction(1, 2))

class DPGames(unittest.TestCase):
    def test_transfer_digit(self):
        # binary strings of length n with no "11": Fibonacci
        cnt = L.transfer_count([0, 1], lambda s: [(0, 1)] + ([(1, 1)] if s == 0 else []), 10, lambda s: 1 if s == 0 else 0)
        self.assertEqual(cnt, 144)
        self.assertEqual(L.transfer_count([0, 1], lambda s: [(0, 1)] + ([(1, 1)] if s == 0 else []), 10, lambda s: 1 if s == 0 else 0, mod=L.P2), 144)
        c = L.digit_dp(1000, 10, 0, lambda st, d, lead: None if d == 4 else (st + d) % 3, lambda st: st == 0)
        self.assertEqual(c, sum(1 for x in range(0, 1001) if '4' not in str(x) and sum(map(int, str(x))) % 3 == 0))
    def test_grundy(self):
        g = L.grundy_table(60, lambda n: [(n - s,) for s in (1, 3, 4) if n >= s])
        for n in range(1, 25):
            self.assertEqual(g[n] == 0, not L.brute_win(n, lambda m: [m - s for s in (1, 3, 4) if m >= s]))

class Programs(unittest.TestCase):
    def test_list_search(self):
        ex = [([3, 1, 2], [4, 3, 2]), ([5, 5, 0], [6, 6, 1]), ([], [])]
        res = L.search_programs(ex, L.LIST_PRIMS, max_depth=2)
        self.assertTrue(res)
        f = res[0][1]
        self.assertEqual(f([9, 7, 8]), [10, 9, 8])
    def test_grid(self):
        g = L.grid(["120", "003"])
        self.assertEqual(L.grid_str(dict(L.GRID_PRIMS)["rot90"](g)), ["01", "02", "30"])
        self.assertEqual(len(L.g_objects(L.grid(["110", "001"]))), 2)
        self.assertEqual(L.learn_color_map([(L.grid(["12"]), L.grid(["34"]))]), {1: 3, 2: 4})

class Search(unittest.TestCase):
    def test_anneal(self):
        best, val = L.anneal([0] * 10, lambda s, r: [v ^ (r.random() < 0.2) for v in s], lambda s: sum(s), iters=5000)
        self.assertEqual(val, 10)
    def test_continuous(self):
        x, v = L.continuous_maximize(lambda z: z[0] + z[1], [0.1, 0.1], constraints=[lambda z: 1 - z[0]**2 - z[1]**2])
        self.assertAlmostEqual(v, math.sqrt(2), places=4)

class Constructions(unittest.TestCase):
    def test_singer_golomb(self):
        for q in (2, 3, 5, 7):
            D = L.singer_difference_set(q); v = q * q + q + 1
            self.assertEqual(len(D), q + 1)
            diffs = sorted((a - b) % v for a in D for b in D if a != b)
            self.assertEqual(diffs, list(range(1, v)))
        D = L.singer_difference_set(29)
        marks = L.golomb_from_modular(D, 29 * 29 + 29 + 1, 30)
        self.assertTrue(L.is_golomb(marks)); self.assertEqual(len(marks), 30)
        print("Golomb 30 marks from Singer(29):", marks[-1])
    def test_misc(self):
        p = L.no3ap_permutation(200); pos = {v: i for i, v in enumerate(p)}
        self.assertFalse(any(min(pos[a], pos[c]) < pos[(a + c) // 2] < max(pos[a], pos[c]) for a in range(1, 201) for c in range(a + 2, 201, 2)))
        S = set(L.salem_spencer(500))
        self.assertFalse(any(2 * b - a in S for a in S for b in S if b > a))
        cost = L.welch_costas(11)
        vecs = {(i, j) for i in range(len(cost)) for j in range(i + 1, len(cost))}
        self.assertEqual(len({(j - i, cost[j] - cost[i]) for i, j in vecs}), len(vecs))
        A = [(0,), (1,)]; B = [(0, 0), (0, 1), (1, 0), (1, 1)]
        self.assertTrue(L.is_cap(L.cap_product(A, B)))

if __name__ == "__main__":
    unittest.main()


class IdeasMemory(unittest.TestCase):
    def test_edge_cells_cover(self):
        A = ["inputs are integers", "order matters", "one player"]
        cells = L.edge_cells(A, k=10)
        self.assertEqual(len(cells), 10)
        self.assertEqual({a for a, _ in cells}, set(A))
        self.assertGreaterEqual(len({o for _, o in cells}), 6)
        self.assertEqual(len(set(cells)), 10)

    def test_projections_stratified(self):
        pr = L.projections(k=7, seed=3)
        self.assertEqual(len({d for d, *_ in pr}), 7)

    def test_pool_evolution(self):
        pool = L.IdeaPool()
        a = pool.add("idea A", "predicts X", origin="invert", target="a1")
        b = pool.add("idea B", "", origin="physics/invariant", target="a2")
        c = pool.add("idea C", "predicts Y", origin="invert", target="a1")
        self.assertTrue(pool.attempt_kill(a, lambda: True))
        self.assertTrue(pool.attempt_kill(a, lambda: (True, "held on n=1..50")))
        self.assertFalse(pool.attempt_kill(b, lambda: 1 / 0))
        pool.confirm_prediction(c, True)
        self.assertEqual(pool.ideas[b - 1]["status"], "KILLED")
        self.assertEqual([i["id"] for i in pool.top(2)], [a, c])
        self.assertEqual(len(pool.elites()), 1)                    # same (origin, target) cell: one elite
        d = pool.add("child", "", origin="merge", target="a1", parents=[a, c])
        self.assertEqual(pool.ideas[d - 1]["gen"], 2)
        self.assertFalse(pool.plateau(2))

    def test_memory_roundtrip(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "amp_memory.json")
        m = L.Memory(path)
        m.record(["count", "huge-n", "local-rule"], "transfer matrix", "solved")
        m.record(["count", "huge-n"], "brute force", "failed")
        m.record(["game", "huge-n"], "grundy + period", "solved")
        top = m.suggest(["count", "huge-n", "local-rule"])
        self.assertEqual(top[0][0], "transfer matrix")
        i = m.predict("claim", 0.8); m.resolve(i, True)
        self.assertAlmostEqual(m.calibration(), 0.04)
        m2 = L.Memory(path)
        self.assertEqual(len(m2.data["records"]), 3)
