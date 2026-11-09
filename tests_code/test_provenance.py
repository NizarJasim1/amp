"""Provenance is CHECKED, not declared (v6.6):  python -m unittest test_provenance

The two exploits that broke v6.5, kept as regressions:
  1. a WRONG brute force tagged provenance='given' reached E3 / p=0.9999 (nothing checked the pairs were given);
  2. a sentence written from the model's head, sealed as 'live', became an L2 "verified" fact.
Plus the routes that must still work: real problem-file pairs reach E3, a runner-receipted #LIVE output reaches L2,
and the after-run attestation (runner key, grader kit files) catches what an in-process forgery slips past."""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)
import contextlib, io, json, os, shutil, sys, tempfile, unittest
import amp_lab as L
import amp_runner as R

PROBLEM = ("Q7. f is a hidden rule on integers. Examples given with the problem:\n"
           "f(2) = 5\nf(3) = 10\nf(4) = 17\nf(6) = 37\nCompute f(1000).\n")      # truth: n*n + 1
FAKE = "f(2) = 4\nf(3) = 9\nf(4) = 16\nf(6) = 36  (my own reading of the rule)"
BAD_HOLD = [((2,), 4), ((3,), 9), ((4,), 16), ((6,), 36), ((7,), 49), ((8,), 64)]   # the wrong brute's own pairs
GOOD_HOLD = [((2,), 5), ((3,), 10), ((4,), 17), ((6,), 37)]
HEAD = "the service answers 99.9% of reads under 120 ms in production"           # written from the model's head


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: v for k, v in kv.items() if v is not None})
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


SHA = L._h(PROBLEM.encode("utf-8"))


def problem_ev():
    ev = L.Evidence()
    quiet(ev.source, "PART1.txt", PROBLEM, "given")
    return ev


class Exploit1GivenOracle(unittest.TestCase):
    def test_bare_given_word_is_self(self):
        r = L.Registry()
        quiet(r.oracle, "Q7", lambda n: n * n, BAD_HOLD, provenance="given", kind="I")
        self.assertFalse(r.oracle_backed("Q7"))
        self.assertLessEqual(r.level("Q7"), 2)
        self.assertLessEqual(r.p_correct("Q7"), 0.70)
        self.assertEqual(r.ledger()["Q7"]["oracle_prov"], "self")

    def test_pairs_not_in_the_problem_are_refused(self):
        with env(AMP_GIVEN_SHA256=SHA, AMP_TRACK=None):
            ev = problem_ev()
            r = L.Registry()
            quiet(r.oracle, "Q7", lambda n: n * n, BAD_HOLD, provenance="given", kind="I", ev=ev, src="PART1.txt")
        self.assertFalse(r.oracle_backed("Q7"))
        self.assertLessEqual(r.level("Q7"), 2)
        self.assertIn("NOT in source", r.certificate()["records"][-1]["prov_check"])

    def test_fake_problem_file_is_refused(self):
        with env(AMP_GIVEN_SHA256=SHA, AMP_TRACK=None):
            ev = L.Evidence()
            quiet(ev.source, "PART1.txt", FAKE, "given")                  # sealed, but NOT a problem file
            r = L.Registry()
            quiet(r.oracle, "Q7", lambda n: n * n, BAD_HOLD[:4], provenance="given", ev=ev, src="PART1.txt")
        self.assertFalse(ev.sources["PART1.txt"]["attested"])
        self.assertLessEqual(r.level("Q7"), 2)

    def test_real_given_pairs_still_reach_E3(self):
        with env(AMP_GIVEN_SHA256=SHA, AMP_TRACK=None):
            ev = problem_ev()
            r = L.Registry()
            quiet(r.oracle, "Q7", lambda n: n * n + 1, GOOD_HOLD, provenance="given", kind="I", ev=ev, src="PART1.txt")
        self.assertTrue(r.oracle_backed("Q7"))
        self.assertEqual(r.level("Q7"), 3)
        att = L.attest_certificate(json.loads(json.dumps(r.certificate())), [PROBLEM])
        self.assertEqual(att["proven"], ["Q7"])

    def test_grid_examples_match_across_lines(self):
        text = "Example 1 input:\n0080\n0800\nExample 1 output:\n0081\n0811\n"
        self.assertTrue(L.case_in_tokens(L.case_tokens((["0080", "0800"],), ["0081", "0811"]), L._toks(text)))
        self.assertFalse(L.case_in_tokens(L.case_tokens((["0080", "0800"],), ["0081", "0812"]), L._toks(text)))

    def test_forged_certificate_is_caught_after_the_run(self):
        # an in-process forgery (monkeypatching the check) records 'given' with the REAL file's sha256 but its own pairs
        with env(AMP_GIVEN_SHA256=SHA, AMP_TRACK=None):
            ev = problem_ev()
            r = L.Registry()
            saved = L._oracle_provenance
            L._oracle_provenance = lambda claimed, holdout, ev, src: ("ok", SHA, "")
            try:
                quiet(r.oracle, "Q7", lambda n: n * n, BAD_HOLD, provenance="given", ev=ev, src="PART1.txt")
            finally:
                L._oracle_provenance = saved
        self.assertEqual(r.level("Q7"), 3)                                 # in-process it slipped through ...
        att = L.attest_certificate(json.loads(json.dumps(r.certificate())), [PROBLEM])
        self.assertEqual(att["proven"], [])                                # ... the grader's own check does not
        self.assertIn("Q7", att["unproven"])


class Exploit2LiveEvidence(unittest.TestCase):
    def test_track_a_live_is_a_declaration(self):
        with env(AMP_TRACK=None):
            ev = L.Evidence()
            quiet(ev.source, "bench", HEAD, "live")
            n = quiet(ev.add, "reads are fast", provenance="live", src="bench", quote="99.9% of reads under 120 ms")
        self.assertEqual(ev.refs[n]["level"], 1)
        self.assertNotEqual(ev.gate(), [])

    def test_track_b_live_without_receipt_is_a_declaration(self):
        with env(AMP_TRACK="B"):
            ev = L.Evidence()
            quiet(ev.source, "bench", HEAD, "live")
            n = quiet(ev.add, "reads are fast", provenance="live", src="bench", quote="99.9% of reads under 120 ms")
        self.assertEqual(ev.refs[n]["level"], 1)

    def test_receipt_for_another_text_is_refused(self):
        work = tempfile.mkdtemp()
        os.makedirs(os.path.join(work, "uploads"))
        live = R.LiveLog({"svc": {"cmd": [sys.executable, "-c", "print('p95=840ms at miss_rate=0.31')"]}}, work)
        out = live.run("#LIVE svc\n")
        rc = out.split("receipt='")[1].split("'")[0]
        with env(AMP_TRACK="B"):
            ev = L.Evidence()
            quiet(ev.source, "bench", HEAD, "live", receipt=rc)            # a real receipt, glued onto a written text
            n = quiet(ev.add, "reads are fast", provenance="live", src="bench", quote="99.9% of reads under 120 ms")
        self.assertEqual(ev.refs[n]["level"], 1)
        shutil.rmtree(work)

    def test_forged_mac_is_caught_by_the_runner(self):
        work = tempfile.mkdtemp()
        os.makedirs(os.path.join(work, "uploads"))
        live = R.LiveLog({}, work)
        forged = f"L1:{L._h(HEAD.encode('utf-8'))}:{'0' * 32}"              # right sha256, made-up mac
        with env(AMP_TRACK="B"):
            ev = L.Evidence()
            quiet(ev.source, "bench", HEAD, "live", receipt=forged)
            n = quiet(ev.add, "reads are fast", provenance="live", src="bench", quote="99.9% of reads under 120 ms")
        self.assertEqual(ev.refs[n]["level"], 2)                           # in-process only the sha can be checked
        rep = L.attest_evidence(json.loads(json.dumps(ev.certificate())), [], live.texts, live.ok)
        self.assertNotEqual(rep["sources"]["bench"], "ok")
        self.assertIn(n, rep["facts_unproven"])
        shutil.rmtree(work)

    def test_runner_logged_live_output_is_proven(self):
        work = tempfile.mkdtemp()
        os.makedirs(os.path.join(work, "uploads"))
        code = "import sys; [print(f'f({n}) = {n*n+1}') for n in map(int, sys.stdin.read().split())]"
        live = R.LiveLog({"ref": {"cmd": [sys.executable, "-c", code]}}, work)
        out = live.run("#LIVE ref\n2 3 4 6\n")
        rc = out.split("receipt='")[1].split("'")[0]
        with env(AMP_TRACK="B"):
            ev = L.Evidence()
            quiet(ev.source_file, os.path.join(work, "uploads", "live_L1.txt"), provenance="live", receipt=rc)
            n = quiet(ev.add, "ref says f(6)=37", provenance="live", src="live_L1.txt", quote="f(4) = 17 f(6) = 37")
            r = L.Registry()
            quiet(r.oracle, "Q7", lambda k: k * k + 1, GOOD_HOLD, provenance="live", ev=ev, src="live_L1.txt")
        self.assertEqual(ev.refs[n]["level"], 2)
        self.assertEqual(r.level("Q7"), 3)
        self.assertTrue(live.ok(rc))
        self.assertEqual(L.attest_evidence(json.loads(json.dumps(ev.certificate())), [], live.texts, live.ok)["facts_unproven"], [])
        self.assertEqual(L.attest_certificate(json.loads(json.dumps(r.certificate())), [], live.texts, live.ok)["proven"], ["Q7"])
        shutil.rmtree(work)


class StepAndGrader(unittest.TestCase):
    def test_declared_step_oracle_is_a_self_check(self):
        a, b = L.StepChain("Q"), L.StepChain("Q")
        a.step("s", check=lambda: True, oracle=True)
        b.step("s", check=lambda: True)
        self.assertEqual(a.p(), b.p())

    def test_grader_caps_unproven_oracle_claim(self):
        import grade as G
        kit = os.path.join(_B, "..", "kit")
        with open(os.path.join(kit, "sealed", "KEYS.json"), encoding="utf-8") as f:
            keys = json.load(f)["1"]
        ans = {"_ledger": {G.EXACT[0]: {"E": 3, "p": 0.9999, "oracle": True}}}
        g = G.grade_run(ans, keys, os.path.join(kit, "grader"), run_ideas=False,
                        attest={"intact": True, "proven": [], "unproven": {G.EXACT[0]: "x"}})
        self.assertFalse(g["oracle"][G.EXACT[0]])
        self.assertEqual(g["E"][G.EXACT[0]], 2)


if __name__ == "__main__":
    unittest.main()
