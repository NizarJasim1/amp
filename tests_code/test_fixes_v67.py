"""Regression tests for the v6.7 fixes:  python -m unittest test_fixes_v67 -v"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)

import contextlib
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile

import amp_runner as R
import grade as G
from sandbox import Sandbox, resolve_user

KIT = os.path.join(_B, "..", "kit")
SANDBOX_USER = os.environ.get("AMP_SANDBOX_USER", "amp-sandbox")


def _user_exists(name):
    try:
        resolve_user(name)
        return True
    except KeyError:
        return False


class SandboxIsolation(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.chmod(self.d, 0o711)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_env_is_built_from_scratch(self):
        """A secret under a name WITHOUT 'KEY' in it used to pass the name filter; nothing is inherited now."""
        os.environ["ANTHROPIC_AUTH"] = "s3cr3t-value"
        try:
            s = Sandbox(os.path.join(self.d, "w"), timeout=20)
            out = s.run("import os; print(sorted(os.environ))")
            s.close()
        finally:
            os.environ.pop("ANTHROPIC_AUTH")
        self.assertNotIn("ANTHROPIC_AUTH", out)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0 and _user_exists(SANDBOX_USER),
                         "needs root and the sandbox user (the Docker image has both)")
    def test_separate_user_cannot_read_runner_environ(self):
        os.environ["FAKE_PROVIDER_KEY"] = "sk-must-not-leak"
        try:
            s = Sandbox(os.path.join(self.d, "w"), timeout=20, user=SANDBOX_USER)
            out = s.run("import os\ntry:\n    print(b'sk-must-not-leak' in open(f'/proc/{os.getppid()}/environ','rb').read())\n"
                        "except Exception as e:\n    print('denied', type(e).__name__)")
            s.close()
        finally:
            os.environ.pop("FAKE_PROVIDER_KEY")
        self.assertIn("denied", out)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0 and _user_exists(SANDBOX_USER),
                         "needs root and the sandbox user")
    def test_probe_finds_readable_answer_key_and_runner_files(self):
        kit = os.path.join(self.d, "kit")
        os.makedirs(os.path.join(kit, "sealed"))
        keys = os.path.join(kit, "sealed", "KEYS.json")
        open(keys, "w").write("{}")
        os.chmod(keys, 0o644)
        runs = os.path.join(self.d, "runs")
        os.makedirs(runs)
        old = os.umask(0o077)
        try:
            leaks = R.check_isolation(kit, runs, SANDBOX_USER)
            self.assertEqual(leaks, [os.path.abspath(keys)])     # environ and runs/ are safe, the 644 key is not
            os.chmod(keys, 0o600)
            self.assertEqual(R.check_isolation(kit, runs, SANDBOX_USER), [])
        finally:
            os.umask(old)

    def test_probe_same_user_reports_leaks(self):
        runs = os.path.join(self.d, "runs")
        leaks = R.check_isolation(os.path.join(self.d, "nokit"), runs, None)
        self.assertTrue(any(p.endswith("/environ") for p in leaks))
        self.assertTrue(any(p.endswith(".isolation_canary") for p in leaks))


class Verifier(unittest.TestCase):
    def test_compared_model_as_verifier_is_refused(self):
        rows = [{"model": "48"}, {"model": "55"}]
        cfg = {"models": {"48": {"provider": "mock", "verifier": "55"}, "55": {"provider": "mock"}}}
        self.assertTrue(R.check_verifiers(cfg, rows))
        cfg["models"]["48"]["verifier"] = "os1"
        self.assertEqual(R.check_verifiers(cfg, rows), [])

    def test_example_config_passes(self):
        cfg = json.load(open(os.path.join(_B, "..", "runner", "providers.example.json")))
        self.assertEqual(R.check_verifiers(cfg, [{"model": "48"}, {"model": "55"}]), [])


def _write_run(d, rid, answers, meta=None, attest=None, cert=None):
    json.dump(answers, open(os.path.join(d, f"{rid}.json"), "w"))
    if meta is not None:
        json.dump(meta, open(os.path.join(d, f"{rid}_meta.json"), "w"))
    if attest is not None:
        json.dump({"track": "B", "registry": attest}, open(os.path.join(d, f"{rid}_attest.json"), "w"))
    if cert is not None:
        json.dump(cert, open(os.path.join(d, f"{rid}_cert.json"), "w"))


class GraderInputs(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.plan = {"R001": {"seed": 1}, "R002": {"seed": 1}}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _both(self):
        loose = os.path.join(self.d, "loose")
        os.makedirs(loose)
        _write_run(loose, "R001", {"Q1": "5", "_ledger": {"Q1": {"E": 3, "oracle": True}}}, meta={"track": "api", "tokens": {"in": 7}},
                   attest={"intact": True, "proven": ["Q1"]}, cert={"c": 1})
        json.dump({"I1": "code"}, open(os.path.join(loose, "R001_p5.json"), "w"))
        zdir = os.path.join(self.d, "zipped")
        os.makedirs(zdir)
        with zipfile.ZipFile(os.path.join(zdir, "runs.zip"), "w") as z:
            for f in os.listdir(loose):
                z.write(os.path.join(loose, f), f"some/folder/{f}")
        return loose, zdir

    def test_zip_and_folder_are_read_the_same(self):
        loose, zdir = self._both()
        a = G.Inputs([loose]).runs(self.plan)
        b = G.Inputs([zdir]).runs(self.plan)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        r = b["R001"]
        self.assertEqual(r["meta"]["track"], "api")
        self.assertEqual(r["attest"]["proven"], ["Q1"])
        self.assertEqual(r["cert"], {"c": 1})
        self.assertEqual(set(r["answers"]), {"Q1", "_ledger", "I1"})       # side files are NOT merged into answers

    def test_explicit_folder_is_the_only_run_source(self):
        inp = G.Inputs([self.d])
        self.assertEqual(inp.run_dirs, [os.path.abspath(self.d)])
        self.assertNotIn("/mnt/user-data/uploads", inp.run_dirs)

    def test_conflicting_copies_are_reported(self):
        loose = os.path.join(self.d, "c")
        os.makedirs(loose)
        _write_run(loose, "R001", {"Q1": "5"})
        json.dump({"Q1": "6"}, open(os.path.join(loose, "R001 (1).json"), "w"))
        inp = G.Inputs([loose])
        self.assertEqual(inp.runs(self.plan)["R001"]["answers"]["Q1"], "5")
        self.assertTrue(any("two different copies" in w for w in inp.warnings))

    def test_tests_from_zip_and_folder(self):
        loose = os.path.join(self.d, "k")
        os.makedirs(os.path.join(loose, "tests", "T3"))
        open(os.path.join(loose, "tests", "T3", "PART1.txt"), "w").write("p1")
        with zipfile.ZipFile(os.path.join(loose, "tests.zip"), "w") as z:
            z.writestr("tests/T4/PART2.txt", "p2")
        t = G.Inputs([loose]).tests()
        self.assertEqual((t[3]["PART1"], t[4]["PART2"]), ("p1", "p2"))


class GraderProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = json.load(open(os.path.join(KIT, "sealed", "KEYS.json")))["1"]

    def test_unchecked_oracle_claim_is_capped(self):
        ans = {"_ledger": {"Q1": {"E": 3, "p": 0.99, "oracle": True}, "Q2": {"E": 3, "p": 0.9}}}
        g = G.grade_run(ans, self.key, os.path.join(KIT, "grader"), run_ideas=False)
        self.assertFalse(g["oracle"]["Q1"])
        self.assertEqual(g["E"]["Q1"], 2)
        self.assertEqual((g["prov_unchecked"], g["prov_refuted"]), (["Q1"], []))
        self.assertEqual(g["E"]["Q2"], 3)                                  # no oracle claim: E untouched

    def test_proven_claim_survives(self):
        ans = {"_ledger": {"Q1": {"E": 3, "p": 0.99, "oracle": True}}}
        g = G.grade_run(ans, self.key, os.path.join(KIT, "grader"), run_ideas=False, attest={"intact": True, "proven": ["Q1"]})
        self.assertTrue(g["oracle"]["Q1"])
        self.assertEqual(g["E"]["Q1"], 3)


class Feedback(unittest.TestCase):
    def test_feedback_is_per_model_and_full_only(self):
        plan = {"R1": {"condition": "FULL", "model": "48"}, "R2": {"condition": "FULL", "model": "55"},
                "R3": {"condition": "BON5", "model": "48"}}

        def g(gain):
            return {"E": {k: 2 for k in G.EXACT}, "items": {k: True for k in G.EXACT}, "pairs": {k: [] for k in G.EXACT},
                    "gain": {"I1": gain}, "shipped": {"I1": "sid"}}
        fb = G.feedback({"R1": g(0.1), "R2": g(0.2), "R3": g(0.3)}, plan)
        self.assertEqual(sorted(fb), ["48", "55"])
        self.assertEqual([r["run"] for r in fb["48"]["runs"]], ["R1"])
        self.assertEqual([o["run"] for o in fb["48"]["outcomes"]], ["R1"])   # BON5@48 and FULL@55 do not leak in

    def test_runner_takes_the_model_file(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "results"))
            open(os.path.join(d, "results", "amp_feedback_48.json"), "w").write("{}")
            self.assertTrue(R.feedback_file(d, "48").endswith("amp_feedback_48.json"))
            self.assertIsNone(R.feedback_file(d, "55"))
        finally:
            shutil.rmtree(d)


class KitConsistency(unittest.TestCase):
    def test_prereg_hashes_match_the_shipped_files(self):
        text = open(os.path.join(KIT, "PREREG.md"), encoding="utf-8").read()
        rows = re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", text)
        self.assertGreater(len(rows), 10)
        for path, h in rows:
            self.assertEqual(hashlib.sha256(open(os.path.join(KIT, path), "rb").read()).hexdigest(), h, path)

    def test_prereg_counts_match_the_plan(self):
        rows = list(csv.DictReader(open(os.path.join(KIT, "plan.csv"), encoding="utf-8")))
        text = open(os.path.join(KIT, "PREREG.md"), encoding="utf-8").read()
        n_abl = len({r["condition"] for r in rows if r["tier"].startswith("2")})
        self.assertIn(f"all {n_abl} ablations", text)
        self.assertIn(f"{len(rows)} runs in `plan.csv`", text)
        readme = open(os.path.join(_B, "..", "README.md"), encoding="utf-8").read()
        self.assertIn(f"{len(rows)} runs", readme)

    def test_grader_copy_is_the_source(self):
        for f in ("grade.py", "stats6.py", "arena5.py"):
            self.assertEqual(open(os.path.join(KIT, "grader", f), "rb").read(),
                             open(os.path.join(_B, "..", "src", f), "rb").read(), f)


if __name__ == "__main__":
    unittest.main()
