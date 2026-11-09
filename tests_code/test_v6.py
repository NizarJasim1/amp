"""Tests for the v6 measurement backbone:  python -m unittest test_v6 -v"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner"), _os.path.join(_B, "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import math
import os
import random
import re
import unittest

import amp_lab as L
import bench_gen as B
import conditions as C
import grade as G
import stats6 as S


def _given(text, name="PART1.txt"):
    """v6.6: an external 'given' oracle must point at a sealed PROBLEM FILE that contains its held-out pairs."""
    import contextlib as _cl, io as _io
    ev, old = L.Evidence(), os.environ.get("AMP_GIVEN_SHA256")
    os.environ["AMP_GIVEN_SHA256"] = L._h(text.encode("utf-8"))
    try:
        with _cl.redirect_stdout(_io.StringIO()):
            ev.source(name, text, "given")
    finally:
        os.environ.pop("AMP_GIVEN_SHA256") if old is None else os.environ.__setitem__("AMP_GIVEN_SHA256", old)
    return ev



class Stats(unittest.TestCase):
    def test_holm_known_values(self):
        self.assertEqual([round(p, 4) for p in S.holm([0.01, 0.04, 0.03])], [0.03, 0.06, 0.06])

    def test_signflip_exact(self):
        self.assertAlmostEqual(S.signflip_p([1, 1, 1, 1]), 2 / 16)       # only all-plus and all-minus reach |4|
        self.assertEqual(S.signflip_p([0, 0, 0]), 1.0)

    def test_null_is_not_significant_and_shift_is(self):
        rng = random.Random(0)
        x = [rng.gauss(0, 1) for _ in range(30)]
        y = [v + rng.gauss(0, 0.1) for v in x]
        self.assertGreater(S.paired_summary(x, y)["p"], 0.01)
        z = [v + 0.5 for v in x]
        r = S.paired_summary(z, x)
        self.assertLess(r["p"], 0.001)
        self.assertTrue(r["ci"][0] <= 0.5 <= r["ci"][1])

    def test_gap_recovery_recovers_planted_ratio(self):
        rng = random.Random(1)
        c = [rng.uniform(0.2, 0.4) for _ in range(40)]
        b = [v + 0.3 + rng.gauss(0, 0.02) for v in c]
        a = [v + 0.15 + rng.gauss(0, 0.02) for v in c]
        r = S.gap_recovery(a, b, c)
        self.assertTrue(r["ci"][0] < 0.5 < r["ci"][1])
        self.assertFalse(r["gap_unstable"])

    def test_cliff_and_power(self):
        self.assertEqual(S.cliffs_delta([2, 3], [0, 1]), 1.0)
        self.assertGreater(S.n_for_power(0.2, 0.05), S.n_for_power(0.2, 0.2))


class Protocols(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(os.path.join(C.HERE, "AMP_v6.src.md"), encoding="utf-8").read()

    def test_markers_balanced(self):
        opens = re.findall(r"\[\[(!?[A-Z]+)\]\]", self.src)
        closes = re.findall(r"\[\[/(!?[A-Z]+)\]\]", self.src)
        self.assertEqual(sorted(opens), sorted(closes))
        self.assertTrue(set(o.lstrip("!") for o in opens) <= set(C.MODULES))

    def test_each_ablation_removes_only_its_module(self):
        full = C.render(self.src, set())
        self.assertNotIn("[[", full)
        for m in C.MODULES:
            var = C.render(self.src, {m})
            self.assertNotIn("[[", var)
            self.assertLess(len(var), len(full) + 600, m)
            kept = set(re.findall(r"`(\w+)\(", var))
            if m == "EV":
                self.assertNotIn("Controller", var)
            if m == "IDEA":
                self.assertNotIn("edge_cells(assumptions", var)
            if m == "BLIND":
                self.assertNotIn("BLIND", var)
            if m == "MEM":
                self.assertNotIn("mem.ingest", var)
            if m == "LAB":
                self.assertNotIn("amp_lab", var)
            _ = kept

    def test_conditions_complete(self):
        for name, (proto, lab, mem, desc) in C.CONDITIONS.items():
            self.assertTrue(desc)
            if proto and proto.startswith("BASE"):
                self.assertTrue(os.path.exists(os.path.join(C.HERE, "baselines", proto)))


class Generators(unittest.TestCase):
    def test_every_q_family_self_verifies_and_is_deterministic(self):
        for fam in B.Q_FAMILIES:
            for seed in range(3):
                outs = []
                for _ in range(2):
                    rng = random.Random(f"t{seed}")
                    for _ in range(100):
                        try:
                            outs.append(fam(rng))
                            break
                        except B.Reject:
                            continue
                self.assertEqual(outs[0], outs[1], fam.__name__)
                self.assertTrue(outs[0][1])

    def test_distinct_tests_per_seed(self):
        a, ka = B.build(101)
        b, kb = B.build(102)
        self.assertNotEqual(a["PART1"], b["PART1"])
        self.assertNotEqual(ka["Q1"], kb["Q1"])

    def test_grid_rules_reproduce_examples(self):
        for seed in range(15):
            task, ans = B.make_g(random.Random(seed), "G")
            self.assertEqual(len(ans), 2)
            self.assertTrue(all(isinstance(r, str) for g in ans for r in g))


class Controller(unittest.TestCase):
    def test_priority_prefers_low_evidence_items(self):
        ctl = L.Controller(None)
        ctl.add("a", "I")
        ctl.add("b", "I")
        ctl.attempt("a", 3)
        self.assertEqual(ctl.next(show=0), "b")

    def test_feedback_moves_calibration(self):
        class M:
            data = {"evidence": [{"kind": "I", "E": 3, "ok": False}] * 20}

            def save(self):
                pass
        self.assertLess(L.calibrated_p(M(), "I", 3), 0.3)
        self.assertGreater(L.calibrated_p(M(), "G", 3), L.calibrated_p(M(), "I", 3))   # other kinds only partly pooled

    def test_failed_attempts_lower_priority(self):
        ctl = L.Controller(None)
        ctl.add("a", "G")
        p0 = ctl.priority("a")
        ctl.attempt("a", 0)
        self.assertLess(ctl.priority("a"), p0)


class Grader(unittest.TestCase):
    def test_perfect_run_and_invalid_constructions(self):
        _, key = B.build(7)
        ans = {k: key[k] for k in G.EXACT}
        ans["C3"] = [0, 1, 2]
        g = G.grade_run(ans, key, C.HERE, run_ideas=False)
        self.assertEqual(g["exact"], 1.0)
        self.assertIsNone(g["C3"])
        self.assertEqual(g["ideas"], 0.0)

    def test_confidence_falls_back_to_ledger(self):
        _, key = B.build(8)
        ans = {"_ledger": {"Q1": {"E": 3, "p": 0.9}}}
        g = G.grade_run(ans, key, C.HERE, run_ideas=False)
        self.assertEqual(g["conf"]["Q1"], 0.9)
        self.assertEqual(g["E"]["Q1"], 3)
        self.assertTrue(math.isfinite(g["brier"]))


if __name__ == "__main__":
    unittest.main()


def _helper(n):
    return n * (n + 1) // 2


def _m_brute(n):
    return sum(range(n + 1))


def _m_helper_a(n):
    return _helper(n)


def _m_helper_b(n):
    return _helper(n) + 0


def _m_loop(n):
    t = 0
    for k in range(n):
        t += k + 1
    return t


class Attested(unittest.TestCase):
    def test_shared_helper_is_caught_and_capped(self):
        r = L.Registry()
        r.check("X", "closed", _m_helper_a, range(1, 10), kind="I")
        r.check("X", "closed2", _m_helper_b, range(1, 10))
        p = r.pairs("X")[0]
        self.assertEqual(p["shared"], ["_helper"])
        self.assertLess(r.level("X"), 3)
        self.assertLess(r.p_correct("X"), 0.5)

    def test_independent_pair_reaches_E3(self):
        r = L.Registry()
        r.check("X", "brute", _m_brute, range(1, 10), kind="I", source="self")
        r.check("X", "loop", _m_loop, range(1, 10), source="model:B")   # cross-source: real independence
        self.assertEqual(r.level("X"), 3)
        self.assertGreater(r.p_correct("X"), 0.9)
        r.reason("X", "triangular numbers")
        self.assertEqual(r.level("X"), 4)

    def test_disagreement_caps_level(self):
        r = L.Registry()
        r.check("X", "brute", _m_brute, range(1, 10))
        r.check("X", "wrong", lambda n: n * n, range(1, 10))
        self.assertEqual(r.level("X"), 1)

    def test_lineage_detected(self):
        r = L.Registry()
        out = r.check("Y", "brute", _m_brute, [(20,)])
        r.check("Y", "copy", lambda v: v, [(out[0],)])
        self.assertTrue(r.records[-1]["lineage"])

    def test_certificate_tamper_evident(self):
        r = L.Registry()
        r.check("X", "brute", _m_brute, range(1, 5))
        r.answer("X", 10)
        cert = json.loads(json.dumps(r.certificate()))
        self.assertEqual(L.verify_certificate(cert), (True, None))
        cert["records"][0]["callees"] = ["forged"]
        self.assertFalse(L.verify_certificate(cert)[0])

    def test_graded_pairs_move_the_risk_model(self):
        class M:
            data = {"pairs": [{"struct_sim": 0.1, "shared_callees": 0.0, "lineage": 0, "same_class": 0, "wrong": True}] * 40}
        f = {"struct_sim": 0.1, "shared_callees": 0.0, "lineage": 0, "same_class": 0}
        self.assertGreater(L.pair_risk(f, M()), 3 * L.pair_risk(f, None))


class ClosedLoop(unittest.TestCase):
    def test_constraint_forbids_shared_helper_and_checks_compliance(self):
        r = L.Registry()
        r.check("X", "closed", _m_helper_a, range(1, 8), kind="I")
        r.check("X", "closed2", _m_helper_b, range(1, 8))
        con = r.constrain("X")
        self.assertIn("_helper", con["forbid_callees"])
        r.check("X", "brute", _m_helper_a, range(1, 8))           # violates: calls the forbidden helper
        self.assertFalse(r.records[-1]["compliance"]["complies"])
        self.assertLess(r.level("X"), 3)
        r.check("X", "loop", _m_loop, range(1, 8))                # complies
        self.assertTrue(r.records[-1]["compliance"]["complies"])
        self.assertEqual(L.verify_certificate(json.loads(json.dumps(r.certificate()))), (True, None))

    def test_shared_resources_count_as_dependence(self):
        r = L.Registry()
        r.check("D", "retrieval-a", _m_brute, range(1, 6), resources=["doc:17"])
        r.check("D", "retrieval-b", _m_loop, range(1, 6), resources=["doc:17"])
        self.assertEqual(r.pairs("D")[0]["shared"], ["res:doc:17"])
        self.assertLess(r.level("D"), 3)


class OracleFirst(unittest.TestCase):
    def test_same_source_agreement_capped_crosssource_reaches_E3(self):
        r = L.Registry()
        r.check("X", "a", _m_brute, range(1, 8), kind="I", source="self")
        r.check("X", "b", _m_loop, range(1, 8), source="self")
        self.assertEqual(r.level("X"), 2)                       # two of the model's own methods: not independent
        r.check("X", "c", _m_loop, range(1, 8), source="model:B")
        self.assertEqual(r.level("X"), 3)                       # a different source breaks the correlation

    def test_external_oracle_verifies_and_rejects(self):
        r = L.Registry()
        hold = [((10,), 20), ((7,), 14), ((3,), 6)]
        ev = _given("Examples given with the problem: f(10) = 20, f(7) = 14, f(3) = 6.")
        r.oracle("G1", lambda x: 2 * x, hold, provenance="given", kind="G", ev=ev, src="PART1.txt")
        self.assertTrue(r.oracle_backed("G1"))
        self.assertEqual(r.level("G1"), 3)
        self.assertGreater(r.p_correct("G1"), 0.9)
        r.oracle("G2", lambda x: x + 1, hold, provenance="given", kind="G", ev=ev, src="PART1.txt")
        self.assertFalse(r.oracle_backed("G2"))
        self.assertEqual(r.level("G2"), 1)
        self.assertLess(r.p_correct("G2"), 0.4)

    def test_self_written_reference_caps_at_E2(self):
        # the reported bug: a brute force the model wrote, agreeing with a fast method, must NOT reach E3/p=1
        r = L.Registry()
        bad = [(k, k * k) for k in range(1, 14)]        # a WRONG understanding, 13 cases
        r.oracle("Q1", lambda n: n * n, bad, provenance="self", kind="I")
        self.assertFalse(r.oracle_backed("Q1"))
        self.assertLessEqual(r.level("Q1"), 2)
        self.assertLessEqual(r.p_correct("Q1"), 0.70)

    def test_correlated_holdout_is_discounted(self):
        r = L.Registry()
        ev = _given("A: " + " ".join(f"in {i} out 0;" for i in range(6)) + " B: " + " ".join(f"in {i} out {i};" for i in range(6)))
        r.oracle("A", lambda x: 0, [((i,), 0) for i in range(6)], provenance="given", ev=ev, src="PART1.txt")   # 1 distinct output
        r.oracle("B", lambda x: x, [((i,), i) for i in range(6)], provenance="given", ev=ev, src="PART1.txt")   # 6 distinct outputs
        self.assertGreater(r.oracle_risk("A"), r.oracle_risk("B") * 5)

    def test_synthesize_verify_rejects_when_nothing_fits_train(self):
        train, hold = [((1,), 2), ((2,), 5)], [((9,), 18)]   # neither candidate fits both train cases
        f, tf, hp, n = L.synthesize_verify(train, hold, [lambda x: x * 2, lambda x: x + 1])
        self.assertIsNone(f)
        train2, hold2 = [((1,), 2), ((2,), 4)], [((9,), 18)]
        f2, tf2, hp2, n2 = L.synthesize_verify(train2, hold2, [lambda x: x * 2, lambda x: x + 1])
        self.assertEqual((tf2, hp2, f2(5)), (2, 1, 10))

    def test_oracle_backed_in_ledger_and_certificate(self):
        r = L.Registry()
        ev = _given("Sample I/O: 3 -> 6, 4 -> 8, 5 -> 10")
        r.oracle("G1", lambda x: 2 * x, [((3,), 6), ((4,), 8), ((5,), 10)], provenance="given", kind="G", ev=ev, src="PART1.txt")
        self.assertTrue(r.ledger()["G1"]["oracle"])
        self.assertEqual(r.ledger()["G1"]["oracle_prov"], "given")
        self.assertEqual(L.verify_certificate(json.loads(json.dumps(r.certificate())))[0], True)

    def test_stepchain_cuts_at_first_bad_step(self):
        sc = L.StepChain("Q")
        sc.step("ok1", check=lambda: True, oracle=True)
        sc.step("bad", check=lambda: False)
        sc.step("later", check=lambda: True)
        self.assertEqual(sc.cut(), 1)
        self.assertLess(sc.p(), 0.7)

    def test_oracle_rich_gate_excludes_I_and_J(self):
        self.assertTrue(all(L.oracle_rich(k) for k in ("G", "P", "C")))
        self.assertFalse(L.oracle_rich("I"))      # model-written brute is not external
        self.assertFalse(L.oracle_rich("J"))      # hidden scorer invisible at solve time
