"""Outcomes ledger - reality's verdict on shipped ideas (v6.5):  python -m unittest test_outcomes"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)
import contextlib, io, json, os, random, shutil, tempfile, unittest
import amp_lab as L

BENCH = "run 7: p95=840ms at miss_rate=0.31; p95=210ms at miss_rate=0.02; errors=0"


# v6.6: these tests exercise the quote logic on sources whose provenance IS proven, the way the runner proves it in
# Track B (problem-file manifest + #LIVE receipts). The provenance checks themselves live in test_provenance.
_ENV = {}


def setUpModule():
    for k, v in (("AMP_TRACK", "B"), ("AMP_GIVEN_SHA256", "")):
        _ENV[k] = os.environ.get(k)
        os.environ[k] = v


def tearDownModule():
    for k, v in _ENV.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def RC(text, rid="L1"):
    return f"{rid}:{L._h(text.encode('utf-8'))}:testmac"


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def ready_pool(specs=(("cache per user id", "cuts p95 by 40%", "invert"),
                      ("shard by region", "no cross-region writes", "biology"),
                      ("drop the queue", "fewer timeouts", "zero"))):
    """Ideas past an independent critic and grounded in one verified fact: all ready()."""
    p = L.IdeaPool()
    ids = [p.add(t, pr, origin=o) for t, pr, o in specs]
    pkt = p.packet("make the API fast", author="me")
    rv = [{"id": it["id"], "verdict": "SURVIVE", "failure_case": "", "test": "x", "confidence": 0.6} for it in pkt["items"]]
    p.ingest("```json\n" + json.dumps({"packet": pkt["packet"], "reviews": rv}) + "\n```", source="chat:fresh")
    ev = L.Evidence()
    quiet(ev.source, "bench", BENCH, "live", receipt=RC(BENCH))
    n = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
    p.attach(ev)
    for i in ids:
        p.cite(ev, i, n, why="the idea assumes misses drive latency")
    return p, ids, ev


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "amp_outcomes.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def oc(self, **k):
        return L.Outcomes(path=self.path, session="s1", **k)


class Ship(Base):
    def test_only_ready_ideas_ship_unless_marked_ungated(self):
        p = L.IdeaPool()
        a = p.add("raw idea", "x", origin="swap")
        oc = self.oc()
        with self.assertRaises(ValueError):
            oc.ship(p, a, p=0.5)                                       # not reviewed, not grounded
        sid = quiet(oc.ship, p, a, p=0.5, gate=False)
        self.assertFalse(oc.ships[sid]["gated"])
        self.assertIn("gate:ungated", oc.ships[sid]["tags"])
        with self.assertRaises(ValueError):
            oc.ship(p, a, p=1.5)

    def test_tags_record_generator_grounding_and_critic(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        sid = quiet(oc.ship, p, a, p=0.7)
        t = oc.ships[sid]["tags"]
        for x in ("op:invert", "gate:ready", "critic:independent", "ground:live", "gen:first", "novel:yes", "kind:J"):
            self.assertIn(x, t)
        self.assertEqual(quiet(oc.ship, p, a, p=0.7), sid)            # same idea -> same sid, shipped once
        self.assertEqual(len(oc.ships), 1)

    def test_child_inherits_parent_generators(self):
        p = L.IdeaPool()
        a = p.add("a", "x", origin="invert")
        b = p.add("b", "y", origin="biology")
        c = p.add("child", "z", origin="recombine", parents=(a, b))
        self.assertEqual(L.gen_tags(p, p.ideas[c - 1]), {"op:invert", "dom:biology"})

    def test_killed_idea_cannot_ship(self):
        p, (a, b, c), ev = ready_pool()
        p.attempt_kill(a, lambda: False, "broke")
        with self.assertRaises(ValueError):
            self.oc().ship(p, a, p=0.5, gate=False)


class Resolve(Base):
    def test_levels(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        s1, s2, s3 = (quiet(oc.ship, p, i, p=0.6) for i in (a, b, c))
        self.assertEqual(quiet(oc.resolve, s1, True), 0)                               # own judgement
        self.assertEqual(quiet(oc.resolve, s2, True, provenance="live"), 1)            # declared
        n = quiet(ev.add, "fast at low miss", provenance="live", src="bench", quote="p95=210ms at miss_rate=0.02")
        self.assertEqual(quiet(oc.resolve, s3, True, provenance="live", ev=ev, fact=n), 2)   # verified fact
        d = quiet(ev.add, "someone said so", provenance="published", ref="u")
        self.assertEqual(quiet(oc.resolve, s1, False, provenance="published", ev=ev, fact=d), 1)  # L1 fact stays R1

    def test_no_rerolling_only_stronger_source_replaces(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        sid = quiet(oc.ship, p, a, p=0.6)
        quiet(oc.resolve, sid, False, provenance="live")
        with self.assertRaises(ValueError):
            oc.resolve(sid, True, provenance="live")                    # same strength: refused
        with self.assertRaises(ValueError):
            oc.resolve(sid, True)                                       # weaker: refused
        n = quiet(ev.add, "fast at low miss", provenance="live", src="bench", quote="p95=210ms at miss_rate=0.02")
        quiet(oc.resolve, sid, True, provenance="live", ev=ev, fact=n)  # stronger: allowed
        self.assertTrue(oc.res[sid]["held"])
        with self.assertRaises(ValueError):
            oc.resolve("nope", True)

    def test_self_verdicts_teach_nothing(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        for i in (a, b, c):
            quiet(oc.resolve, quiet(oc.ship, p, i, p=0.9), False)
        self.assertEqual(oc.calibration()["n"], 0)
        self.assertIsNone(oc.reality_blind_spot()["observed"])
        self.assertEqual(oc.coverage()["self_only"], 3)


class Persistence(Base):
    def test_reload_and_tamper(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        sid = quiet(oc.ship, p, a, p=0.6)
        quiet(oc.resolve, sid, True, provenance="validator")
        oc2 = self.oc()
        self.assertIn(sid, oc2.ships)
        self.assertTrue(oc2.res[sid]["held"])
        with open(self.path) as f:
            d = json.load(f)
        d["records"][1]["held"] = False                                 # rewrite a verdict after the fact
        with open(self.path, "w") as f:
            json.dump(d, f)
        oc3 = quiet(self.oc)
        self.assertIsNotNone(oc3.tampered)
        self.assertEqual(quiet(oc3.rates), {})
        cells = quiet(L.edge_cells, ["a", "b"], k=4, outcomes=oc3)      # falls back to the plain design
        self.assertEqual(cells, quiet(L.edge_cells, ["a", "b"], k=4))

    def test_grader_ingest_is_r2_and_once(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        s1, s2 = quiet(oc.ship, p, a, p=0.6), quiet(oc.ship, p, b, p=0.6)
        fb = os.path.join(self.d, "amp_feedback.json")
        json.dump({"runs": [], "outcomes": [{"run": "R001", "task": "I1", "sid": s1, "held": True, "gain": 0.2},
                                            {"run": "R001", "task": "I2", "sid": s2, "held": False, "gain": -0.1},
                                            {"run": "R001", "task": "I3", "sid": "unknown", "held": True}]}, open(fb, "w"))
        self.assertEqual(quiet(oc.ingest, fb), 2)
        self.assertEqual((oc.res[s1]["level"], oc.res[s2]["level"]), (2, 2))
        self.assertEqual(quiet(oc.ingest, fb), 0)


class Learning(Base):
    def history(self, oc, wins, losses):
        """Fake history: ideas from `wins` ops held, from `losses` ops failed, all graded by the official grader."""
        for k in range(6):
            for op, held in [(o, True) for o in wins] + [(o, False) for o in losses]:
                p = L.IdeaPool()
                i = p.add(f"{op} idea {k}", "x", origin=op)
                quiet(oc.resolve, quiet(oc.ship, p, i, p=0.5, gate=False), held, provenance="validator", _grader=True)

    def test_rates_pool_toward_global(self):
        oc = self.oc()
        self.history(oc, ["invert"], ["swap"])
        r = oc.rates("op:")
        self.assertGreater(r["op:invert"][0], 0.7)
        self.assertLess(r["op:swap"][0], 0.3)

    def test_edge_cells_extra_picks_follow_reality_but_all_ops_stay(self):
        oc = self.oc()
        self.history(oc, ["invert"], ["swap", "drop"])
        n = len(L.ASSUMPTION_OPS)
        hits = 0
        for seed in range(20):
            cells = quiet(L.edge_cells, ["a1", "a2", "a3"], k=n + 1, seed=seed, outcomes=oc)
            ops = [o for _, o in cells]
            self.assertEqual(set(ops), set(L.ASSUMPTION_OPS))          # exploration: every operator appears
            hits += ops.count("invert") == 2                           # the one extra cell
        self.assertGreaterEqual(hits, 15)

    def test_projections_order_by_reality(self):
        oc = self.oc()
        for k in range(6):
            p = L.IdeaPool()
            i = p.add(f"bio {k}", "x", origin="biology")
            quiet(oc.resolve, quiet(oc.ship, p, i, p=0.5, gate=False), True, provenance="validator", _grader=True)
            j = p.add(f"phys {k}", "y", origin="physics")
            quiet(oc.resolve, quiet(oc.ship, p, j, p=0.5, gate=False), False, provenance="validator", _grader=True)
        first = [quiet(L.projections, k=1, seed=s, outcomes=oc)[0][0] for s in range(20)]
        self.assertGreaterEqual(first.count("biology"), 7)            # chance is 20/7 ~ 3; untested domains still explored
        self.assertLessEqual(first.count("physics"), 1)               # what reality rejected almost never leads

    def test_parents_weighted_by_reality(self):
        oc = self.oc()
        self.history(oc, ["invert"], ["swap"])
        p = L.IdeaPool()
        good = p.add("g", "x", origin="invert", target="t1")
        bad = p.add("b", "y", origin="swap", target="t2")
        mid = p.add("m", "z", origin="zero", target="t3")
        picks = [i["id"] for s in range(200) for i in p.parents(k=1, seed=s, outcomes=oc)]
        self.assertGreater(picks.count(good), picks.count(bad))
        self.assertEqual(L.IdeaPool.parents(p, k=1, seed=3), p.parents(k=1, seed=3))   # no oc: unchanged


class Honesty(Base):
    def test_blind_spot_worst_case_counts_overdue(self):
        p, (a, b, c), ev = ready_pool()
        oc = self.oc()
        s1 = quiet(oc.ship, p, a, p=0.8)
        s2 = quiet(oc.ship, p, b, p=0.8)
        quiet(oc.ship, p, c, p=0.8, due_days=-1)                       # overdue, never resolved
        quiet(oc.resolve, s1, True, provenance="validator", _grader=True)
        quiet(oc.resolve, s2, False, provenance="validator", _grader=True)
        bs = oc.reality_blind_spot()
        self.assertEqual(bs["observed"], 0.5)
        self.assertAlmostEqual(bs["worst_case"], 2 / 3, places=3)
        self.assertEqual(bs["critic_passed_reality_failed"], 0.5)
        self.assertEqual(bs["overdue"], 1)

    def test_calibration_and_adjust(self):
        oc = self.oc()
        for k in range(10):
            p = L.IdeaPool()
            i = p.add(f"idea {k}", "x", origin="time")
            quiet(oc.resolve, quiet(oc.ship, p, i, p=0.9, gate=False), k < 3, provenance="validator", _grader=True)
        c = oc.calibration()
        self.assertAlmostEqual(c["gap"], 0.6, places=3)                 # said 0.9, held 0.3
        self.assertLess(oc.adjust(0.9), 0.65)
        self.assertGreater(oc.adjust(0.9), 0.3)                         # shrunk, not fully trusted on 10 cases

    def test_pipeline_compares_gated_vs_ungated(self):
        oc = self.oc()
        p, ids, ev = ready_pool()
        for i in ids:
            quiet(oc.resolve, quiet(oc.ship, p, i, p=0.7), True, provenance="validator", _grader=True)
        for k in range(3):
            q = L.IdeaPool()
            j = q.add(f"untested {k}", "x")
            quiet(oc.resolve, quiet(oc.ship, q, j, p=0.7, gate=False), False, provenance="validator", _grader=True)
        (ready, _), (ungated, _) = oc.pipeline()["ready vs ungated"]
        self.assertEqual((ready, ungated), (1.0, 0.0))
        rep = quiet(oc.report)
        self.assertEqual(rep["coverage"]["shipped"], 6)


if __name__ == "__main__":
    unittest.main()
