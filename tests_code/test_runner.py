"""Track B pipeline tests (offline, mock model):  python -m unittest test_runner"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner"), _os.path.join(_B, "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "runner"))
import amp_runner as R  # noqa: E402
from sandbox import Sandbox  # noqa: E402


class SandboxT(unittest.TestCase):
    def test_persistence_timeout_and_paths(self):
        d = tempfile.mkdtemp()
        s = Sandbox(d, timeout=3)
        s.run("x = 41")
        self.assertIn("42", s.run("x + 1"))
        s.run("open('/mnt/user-data/outputs/f.txt', 'w').write('hi')")
        self.assertTrue(os.path.exists(os.path.join(d, "outputs", "f.txt")))
        self.assertIn("restarted", s.run("import time; time.sleep(10)"))
        self.assertIn("NameError", s.run("x"))
        os.environ["FAKE_API_KEY"] = "secret"
        s2 = Sandbox(d, timeout=5)
        self.assertNotIn("secret", s2.run("import os; print(os.environ.get('FAKE_API_KEY'))"))
        s.close()
        s2.close()
        shutil.rmtree(d)


class RunnerT(unittest.TestCase):
    def test_mock_run_writes_all_files(self):
        kit = next((k for k in (os.path.join(HERE, "kit"), os.path.join(HERE, "..", "kit")) if os.path.exists(k)), "")
        if not os.path.exists(kit):
            self.skipTest("kit not built")
        runs = tempfile.mkdtemp()
        rows = list(__import__("csv").DictReader(open(os.path.join(kit, "plan.csv"))))
        meta = R.run_one(rows[0], kit, runs, {"models": {rows[0]["model"]: {"provider": "mock"}}, "limits": {"tool_timeout": 30}})
        rid = rows[0]["run_id"]
        for suffix in (".json", "_p5.json", "_meta.json", ".transcript.jsonl"):
            self.assertTrue(os.path.exists(os.path.join(runs, rid + suffix)), suffix)
        self.assertEqual(meta["track"], "api")
        self.assertIn("Q1", json.load(open(os.path.join(runs, rid + ".json"))))
        shutil.rmtree(runs)

    def test_last_json(self):
        self.assertEqual(R.last_json('a ```json\n{"a": 1}\n``` b ```json\n{"b": 2}\n```'), {"b": 2})
        self.assertEqual(R.last_json("no json"), {})


if __name__ == "__main__":
    unittest.main()
