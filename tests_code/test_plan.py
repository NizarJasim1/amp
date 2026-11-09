"""Plan engine (v6.5):  python -m unittest test_plan"""
import os as _os, sys as _sys
_B = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_B, _os.path.join(_B, "..", "src"), _os.path.join(_B, "..", "runner")):
    if _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)
import json, os, tempfile, unittest
import amp_lab as L
import amp_runner as R


def base(path=None):
    pl = L.Plan("get 50 paying users for the tool in 60 days", path=path)
    pl.premortem("nobody finds it", signal="visits", p=0.4)
    pl.premortem("they try it and leave", signal="week2_retention", p=0.3)
    pl.premortem("they use it but will not pay", signal="paid", p=0.5)
    pl.phase("pilot", "10 users try it", budget=14, kill_if=["visits < 100", "week2_retention < 0.2"],
             continue_if=["week2_retention >= 0.4"], fallback="pivot")
    pl.phase("paid", "ask for money", budget=30, kill_if=["paid < 5"], continue_if=["paid >= 50"])
    pl.phase("pivot", "narrow to one niche", budget=14, kill_if=["visits < 50"], continue_if=["visits >= 200"])
    return pl


class Build(unittest.TestCase):
    def test_bad_criteria_and_missing_rules(self):
        pl = L.Plan("g")
        with self.assertRaises(ValueError):
            pl.phase("a", "x", 1, kill_if=["it feels slow"], continue_if=["users > 1"])
        with self.assertRaises(ValueError):
            pl.phase("a", "x", 1, kill_if=[], continue_if=["users > 1"])
        with self.assertRaises(ValueError):
            pl.premortem("x", signal="not a metric!")

    def test_start_refuses_thin_or_unwatched_premortem(self):
        pl = L.Plan("g"); pl.phase("a", "x", 5, kill_if=["users < 1"], continue_if=["users >= 3"])
        pl.premortem("no users", signal="users")
        with self.assertRaisesRegex(RuntimeError, "at least 3"):
            pl.start()
        pl.premortem("too slow", signal="latency_ms"); pl.premortem("costs too much", signal="cost")
        with self.assertRaisesRegex(RuntimeError, "not watched"):
            pl.start()
        with self.assertRaises(ValueError):
            pl.accept(2, "ok")
        pl.accept(2, "latency is irrelevant at this scale, measured last month")
        pl.watch(3, "cost", "a", "cost > 100")
        self.assertTrue(pl.start())


class Decide(unittest.TestCase):
    def test_decisions_follow_committed_numbers(self):
        pl = base(); pl.start()
        self.assertEqual(pl.report("pilot", {"visits": 300}, spent=3)[0], "HOLD")          # retention not measured
        self.assertEqual(pl.report("pilot", {"visits": 300, "week2_retention": 0.3}, spent=5)[0], "HOLD")
        self.assertEqual(pl.report("pilot", {"visits": 300, "week2_retention": 0.5}, spent=8)[0], "CONTINUE")
        self.assertEqual(pl.data["current"], "paid")
        self.assertEqual(pl.report("paid", {"paid": 3}, spent=10)[0], "KILL")
        self.assertIsNone(pl.data["current"])

    def test_pivot_and_budget_kill(self):
        pl = base(); pl.start()
        d, why = pl.report("pilot", {"visits": 40, "week2_retention": 0.9}, spent=2)
        self.assertEqual(d, "PIVOT"); self.assertIn("visits < 100", why); self.assertEqual(pl.data["current"], "pivot")
        self.assertEqual(pl.report("pivot", {"visits": 120}, spent=14)[0], "KILL")          # bar unmet, budget gone

    def test_unmeasured_stop_signal_at_budget_end_kills(self):
        pl = base(); pl.start()
        self.assertEqual(pl.report("pilot", {"week2_retention": 0.5}, spent=14)[0], "KILL")

    def test_no_reporting_before_start(self):
        with self.assertRaises(RuntimeError):
            base().report("pilot", {"visits": 1}, spent=1)


class Goalposts(unittest.TestCase):
    def test_loosening_refused_tightening_logged(self):
        pl = base(); pl.start()
        for kw in ({"kill_if": ["visits < 50", "week2_retention < 0.2"]},          # looser stop
                   {"kill_if": ["week2_retention < 0.2"]},                          # removed stop
                   {"continue_if": ["week2_retention >= 0.3"]},                     # lower bar
                   {"budget": 30}):                                                 # more money mid-phase
            with self.assertRaisesRegex(RuntimeError, "goalpost"):
                pl.amend_phase("pilot", "results look bad", **kw)
        pl.amend_phase("pilot", "stricter", kill_if=["visits < 150", "week2_retention < 0.2"])
        self.assertEqual(len(pl.data["moves"]), 1)
        pl.amend_phase("paid", "not started yet, free to change", kill_if=["paid < 2"])    # PLANNED phase: allowed

    def test_hand_edit_detected_on_load(self):
        d = tempfile.mkdtemp(); f = os.path.join(d, "plan.json")
        pl = base(f); pl.start(); pl.amend_phase("pilot", "stricter", kill_if=["visits < 150", "week2_retention < 0.2"])
        L.Plan.load(f)                                                               # logged change: fine
        data = json.load(open(f)); data["phases"][0]["kill_if"][0]["text"] = "visits < 1"
        json.dump(data, open(f, "w"))
        with self.assertRaisesRegex(RuntimeError, "by hand"):
            L.Plan.load(f)


class Critic(unittest.TestCase):
    def test_outside_critic_adds_causes_that_block_until_watched(self):
        pl = base()
        pkt = pl.packet(author="model:A")
        self.assertNotIn("nobody finds it", pkt["prompt"])                          # pre-mortem stays sealed
        self.assertIn("stop if", pkt["prompt"])
        out = R.critic_call(pkt["runner"], R.Mock({}), {"provider": "mock", "model": "B"}, {"model": "A"}, tempfile.mkdtemp())
        rep = pl.ingest(out.split("\n", 1)[1], source="model:B")
        self.assertEqual(len(rep["new_causes"]), 1)
        with self.assertRaisesRegex(RuntimeError, "not watched"):
            pl.start()
        pl.watch(rep["new_causes"][0], "empty_runs", "pilot", "empty_runs > 3")
        self.assertTrue(pl.start())

    def test_self_review_and_echo_add_nothing(self):
        pl = base(); pkt = pl.packet(author="me")
        rv = lambda case: "```json\n" + json.dumps({"packet": pkt["packet"], "reviews": [
            {"id": "C1", "verdict": "KILL", "failure_case": case, "test": "t", "confidence": 0.5}]}) + "\n```"
        self.assertEqual(pl.ingest(rv("budget overrun on hosting"), source="me")["new_causes"], [])
        self.assertEqual(pl.ingest(rv("they try it and leave"), source="chat:fresh")["echo"], 1)


if __name__ == "__main__":
    unittest.main()
