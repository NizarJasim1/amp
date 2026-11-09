"""Data-first evidence ledger (v6.5):  python -m unittest test_evidence"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)
import contextlib, io, json, os, shutil, tempfile, unittest
import amp_lab as L

BENCH = "run 7: p95=840ms at miss_rate=0.31; p95=210ms at miss_rate=0.02; errors=0"
SPEC = "The service must answer 99% of reads under 300 ms. Writes may be slower."
WHY = "the idea assumes cache misses drive latency"


# v6.6: these tests exercise the quote logic on sources whose provenance IS proven, the way the runner proves it in
# Track B (problem-file manifest + #LIVE receipts). The provenance checks themselves live in test_provenance.
_ENV = {}


def setUpModule():
    for k, v in (("AMP_TRACK", "B"), ("AMP_GIVEN_SHA256", L._h(SPEC.encode("utf-8")))):
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


def reviewed_pool():
    """Ideas already past an independent critic with no pending attacks: only grounding is left to decide ready()."""
    p = L.IdeaPool()
    a = p.add("cache per user id", "cuts p95 latency by 40%")
    b = p.add("shard by region", "no cross-region writes")
    pkt = p.packet("make the API fast", author="me")
    rv = [{"id": it["id"], "verdict": "SURVIVE", "failure_case": "", "test": "x", "confidence": 0.6} for it in pkt["items"]]
    p.ingest("```json\n" + json.dumps({"packet": pkt["packet"], "reviews": rv}) + "\n```", source="chat:fresh")
    return p, a, b


def ledger():
    ev = L.Evidence()
    quiet(ev.source, "bench", BENCH, "live", receipt=RC(BENCH))
    quiet(ev.source, "spec", SPEC, "given")
    return ev


class Levels(unittest.TestCase):
    def test_verified_declared_self(self):
        ev = ledger()
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        d = quiet(ev.add, "a paper says so", provenance="published", ref="https://x")
        s = quiet(ev.add, "I recall caches help", provenance="self")
        u = quiet(ev.add, "?", provenance="hearsay")
        self.assertEqual([ev.refs[n]["level"] for n in (v, d, s, u)], [2, 1, 0, 0])
        self.assertEqual(ev.refs[u]["provenance"], "self")

    def test_quote_must_really_be_in_the_source(self):
        ev = ledger()
        n = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=999ms at miss_rate=0.31")
        self.assertEqual(ev.refs[n]["level"], 1)                     # invented number -> not verified
        self.assertIn("NOT found", ev.refs[n]["why"])
        short = quiet(ev.add, "x", provenance="live", src="bench", quote="p95")
        self.assertEqual(ev.refs[short]["level"], 1)                 # too short to verify
        ws = quiet(ev.add, "x", provenance="live", src="bench", quote="P95=840MS   at miss_rate=0.31")
        self.assertEqual(ev.refs[ws]["level"], 2)                    # case / whitespace do not matter

    def test_source_rules(self):
        ev = ledger()
        with self.assertRaises(ValueError):
            ev.source("mine", "something long enough to quote", "self")      # own memory is not a source
        with self.assertRaises(ValueError):
            quiet(ev.source, "bench", "other text that is long enough", "live")   # cannot overwrite a sealed source
        with self.assertRaises(ValueError):
            ev.add("x", provenance="published", src="bench", quote="p95=840ms at miss_rate=0.31")  # provenance mismatch
        with self.assertRaises(ValueError):
            ev.add("x", provenance="live", src="nowhere", quote="p95=840ms at miss_rate=0.31")

    def test_source_file_and_hash(self):
        d = tempfile.mkdtemp()
        pth = os.path.join(d, "PART1.txt")
        open(pth, "w", encoding="utf-8").write(SPEC)
        ev = L.Evidence()
        h = quiet(ev.source_file, pth, provenance="given")
        self.assertEqual(h, L._h(SPEC.encode("utf-8")))              # matchable against the real file
        n = quiet(ev.add, "reads need <300ms", provenance="given", src="PART1.txt", quote="99% of reads under 300 ms")
        self.assertEqual(ev.refs[n]["level"], 2)
        shutil.rmtree(d)


class Gate(unittest.TestCase):
    def test_gate_needs_a_verified_fact(self):
        ev = L.Evidence()
        self.assertIn("no external evidence", ev.gate()[0])
        quiet(ev.add, "a paper says so", provenance="published", ref="u")
        self.assertIn("only declared", ev.gate()[0])                  # declared external is not enough
        quiet(ev.source, "spec", SPEC, "given")
        quiet(ev.add, "reads <300ms", provenance="given", src="spec", quote="answer 99% of reads under 300 ms")
        self.assertEqual(ev.gate(), [])

    def test_ready_needs_verified_grounding(self):
        p, a, b = reviewed_pool()
        self.assertEqual(sorted(i["id"] for i in p.ready()), [a, b])   # no ledger attached: gate off (noDATA)
        ev = ledger()
        p.attach(ev)
        self.assertEqual(p.ready(), [])                                # attached: nothing grounded yet
        dec = quiet(ev.add, "a blog says so", provenance="published", ref="u")
        p.cite(ev, a, dec, why=WHY)
        self.assertEqual(p.ready(), [])                                # declared-only grounds nothing
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        p.cite(ev, a, v, why=WHY)
        self.assertEqual([i["id"] for i in p.ready()], [a])
        g = p.grounding()
        self.assertEqual((g["gate"], g["verified_grounded"], g["from_head"]), ("on", 1, 1))

    def test_self_citation_grounds_nothing(self):
        p, a, b = reviewed_pool()
        ev = L.Evidence()
        n = quiet(ev.add, "I think this is how it works", provenance="self")
        p.cite(ev, a, n, why=WHY)
        self.assertEqual(p.ready(), [])

    def test_why_is_required(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        n = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        with self.assertRaises(ValueError):
            p.cite(ev, a, n)
        with self.assertRaises(ValueError):
            p.cite(ev, a, 99, why=WHY)


class Strength(unittest.TestCase):
    def test_same_source_counts_once(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        n1 = quiet(ev.add, "slow at high miss", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        n2 = quiet(ev.add, "fast at low miss", provenance="live", src="bench", quote="p95=210ms at miss_rate=0.02")
        base = p.score(p.ideas[a - 1])
        p.cite(ev, a, n1, n2, why=WHY)
        self.assertEqual(p.grounding()["strength"][a], 1)             # two quotes, one stream
        n3 = quiet(ev.add, "reads must be <300ms", provenance="given", src="spec", quote="99% of reads under 300 ms")
        p.cite(ev, a, n3, why="the target the idea must meet")
        self.assertEqual(p.grounding()["strength"][a], 2)
        self.assertAlmostEqual(p.score(p.ideas[a - 1]) - base, 2 * L.STRENGTH_BONUS)

    def test_restatement_flagged_but_kept(self):
        p, a, b = reviewed_pool()
        ev = L.Evidence()
        quiet(ev.source, "blog", "we found that a cache per user id cuts p95 latency by 40% in production", "published",
              receipt=RC("we found that a cache per user id cuts p95 latency by 40% in production", "L2"))
        n = quiet(ev.add, "cache per user id cuts p95 latency by 40%", provenance="published", src="blog",
                  quote="a cache per user id cuts p95 latency by 40%")
        p.cite(ev, a, n, why=WHY)
        g = p.grounding()
        self.assertIn(a, g["restatements"])
        self.assertNotIn(a, g["novel_ready"])


class Contra(unittest.TestCase):
    def test_contra_blocks_until_answered(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        c = quiet(ev.add, "no errors under load", provenance="live", src="bench", quote="errors=0")
        p.cite(ev, a, v, why=WHY)
        p.cite(ev, a, c, why="if errors are zero the queue is not the bottleneck", stance="contra")
        self.assertEqual(p.ready(), [])                                # unanswered evidence against it
        (iid, k, n, _), = p.pending_contra()
        self.assertTrue(quiet(p.answer_contra, iid, k, lambda: True))
        self.assertEqual([i["id"] for i in p.ready()], [a])
        with self.assertRaises(ValueError):
            p.answer_contra(iid, k, lambda: True)

    def test_contra_can_kill(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        p.cite(ev, a, v, why=WHY)
        p.cite(ev, a, v, why="same run shows latency fine at low miss", stance="contra")
        quiet(p.answer_contra, a, 1, lambda: (False, "broke"))
        self.assertEqual(p.ideas[a - 1]["status"], "KILLED")
        self.assertEqual(p.ready(), [])

    def test_self_contra_is_noted_not_blocking(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        s = quiet(ev.add, "I doubt it", provenance="self")
        p.cite(ev, a, v, why=WHY)
        p.cite(ev, a, s, why="my own doubt about the mechanism", stance="contra")
        self.assertEqual(p.pending_contra(), [])
        self.assertEqual([i["id"] for i in p.ready()], [a])


class Chain(unittest.TestCase):
    def test_tamper_detected_and_save(self):
        d = tempfile.mkdtemp()
        pth = os.path.join(d, "amp_evidence.json")
        ev = L.Evidence(path=pth)
        quiet(ev.source, "bench", BENCH, "live", receipt=RC(BENCH))
        quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        with open(pth) as f:
            cert = json.load(f)
        self.assertEqual(L.verify_certificate(cert), (True, None))
        cert["records"][1]["level"] = 2
        cert["records"][1]["quote"] = "p95=10ms"                     # rewrite the fact after the fact
        self.assertFalse(L.verify_certificate(cert)[0])
        shutil.rmtree(d)

    def test_ground_tags_for_outcomes(self):
        p, a, b = reviewed_pool()
        ev = ledger()
        v = quiet(ev.add, "misses drive p95", provenance="live", src="bench", quote="p95=840ms at miss_rate=0.31")
        p.cite(ev, a, v, why=WHY)
        t = L.ground_tags(p.ideas[a - 1])
        self.assertEqual((t["prov"], t["max_level"], t["sources"]), (["live"], 2, 1))


if __name__ == "__main__":
    unittest.main()
