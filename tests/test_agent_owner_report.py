"""agent-costs --report owners (issue 432, spec test seam 1)."""
import json
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .owner_transcripts import FINISH, RUN, Session, at, cost, finish_reply, gate_reply, progress


def report(root, *extra):
    completed = subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--format",
         "json", "--days", "0", "--projects-dir", str(root), *extra],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


class OwnerReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def chain(session):
        """Root owner (launch 1) hands off at Phase 2; owner a2 (launch 2) boots 29k → 98k."""
        g1 = session.call(None, 0, context=40_000, write=40_000, ttl="1h", bash=progress(1))
        session.result(None, 5, g1, gate_reply("continue"))
        session.measured(None, g1, 40_000)
        g2 = session.call(None, 60, context=120_000, write=80_000, ttl="1h", bash=progress(2))
        session.result(None, 65, g2, gate_reply("handoff"))
        session.measured(None, g2, 120_000)
        fin = session.call(None, 70, context=121_000, write=1_000, ttl="1h",
                           bash=progress(2, handoff="/r/.superpowers/workflows/x/handoffs/h.md"))
        session.result(None, 75, fin, gate_reply("handoff", handoff_path="h.md"))
        dispatch = session.call(None, 80, context=122_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("a2", tool_use_id=dispatch)
        for second, context in ((100, 29_000), (110, 50_000), (120, 75_000)):
            session.call("a2", second, context=context, write=context - 20_000 if context > 29_000 else 29_000)
        g3 = session.call("a2", 130, context=98_000, write=23_000,
                          bash=progress(3, action_id="7:1:2"))
        session.result("a2", 135, g3, gate_reply("continue", launch=2))
        session.measured("a2", g3, 98_000)
        work = session.call("a2", 140, context=99_000, write=1_000, agent_tool=True)
        session.child("w1", tool_use_id=work, parent="a2")
        session.call("w1", 150, context=30_000, write=30_000)
        session.result("a2", 400, work, "worker done")
        session.call("a2", 401, context=101_000, write=2_000)
        session.result(None, 402, dispatch, "a2 returned")
        return session

    def test_a_relaunched_owner_boot_from_29k_to_98k(self):
        self.chain(Session(self.root)).write()
        boots = report(self.root)["boots"]
        self.assertEqual(boots, [{"phase_group": "0-5", "count": 1, "b_p50": 98_000,
                                  "b_p90": 98_000, "start_p50": 29_000, "calls_p50": 4,
                                  "slimmable_p50": 0}])

    def test_a_two_launch_handoff_chain_with_a_worker_child(self):
        self.chain(Session(self.root)).write()
        [row] = report(self.root)["lineages"]
        self.assertEqual((row["run_id"], row["issue"], row["launches"], row["handoffs"],
                          row["boots"], row["peak_context"]), (RUN, 7, 2, 1, 1, 122_000))
        self.assertAlmostEqual(row["total_dollars"] - row["owner_dollars"], cost(30_000, 30_000),
                               places=9)
        self.assertEqual((row["gate_calls"], row["measured_gate_calls"]), (4, 3))
        self.assertEqual(row["long_child_waits"], 0)  # a2's gaps are under 300 s

    def test_a_six_minute_gap_rewrite_is_a_death_priced_as_a_5_minute_write(self):
        session = Session(self.root)
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        g = session.call("o1", 10, context=60_000, write=60_000, bash=progress(5))
        session.result("o1", 15, g, gate_reply("continue"))
        session.call("o1", 375, context=60_500, write=60_500)
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual(row["deaths"], 1)
        self.assertAlmostEqual(row["owner_dollars"],
                               cost(60_000, 60_000) + cost(60_500, 60_500), places=9)

    def test_dollars_per_delivered_issue_counts_undelivered_spend(self):
        delivered = Session(self.root, session="s1")
        g = delivered.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        delivered.result(None, 5, g, gate_reply("continue"))
        keeper = delivered.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        delivered.child("k1", tool_use_id=keeper)
        f = delivered.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        delivered.result("k1", 25, f, finish_reply(7))
        delivered.write()
        other = Session(self.root, project="-Users-me-other", session="s2")
        g8 = other.call(None, 0, context=30_000, write=30_000, ttl="1h",
                        bash=progress(3, action_id="8:1:1"))
        other.result(None, 5, g8, gate_reply("continue", issue=8))
        other.write()
        doc = report(self.root)
        rows = {row["issue"]: row for row in doc["lineages"]}
        self.assertEqual((rows[7]["delivered"], rows[8]["delivered"]), (True, False))
        [arm] = doc["arms"]
        self.assertEqual((arm["arm"], arm["n"], arm["delivered"]), ("live", 2, 1))
        self.assertAlmostEqual(arm["dollars_per_delivered"],
                               rows[7]["total_dollars"] + rows[8]["total_dollars"], places=9)
        self.assertAlmostEqual(arm["undelivered_dollars"], rows[8]["total_dollars"], places=9)
        self.assertIsNone(arm["sd"])

    def test_eval_grouping_two_arms_two_trials(self):
        rows, dollars = [], {}
        for index, (rev, verdict, write, exit_code) in enumerate(
                (("a" * 40, "PASS", 20_000, 0), ("a" * 40, "PASS", 40_000, 0),
                 ("b" * 40, "PASS", 30_000, 0), ("b" * 40, "FAIL", 50_000, 0),
                 ("b" * 40, "PASS", 60_000, 124)), 1):   # trial 5 timed out with its asserts passing
            workdir = f"/private/tmp/eval-from-issue-8.T{index}"
            session = Session(self.root, project=workdir.replace("/", "-").replace(".", "-") + "-repo",
                              session=f"s{index}")
            g = session.call(None, 0, context=write, write=write, ttl="1h", bash=progress(6))
            session.result(None, 5, g, gate_reply("continue"))
            session.write()
            dollars[index] = cost(write, write, write_price=8.0)
            rows.append({"skill": "from-issue", "id": 8, "trial": index, "verdict": verdict,
                         "workdir": workdir, "tree_rev": rev, "policy": None,
                         "claude_exit": exit_code})
        results = self.root / "results.jsonl"
        results.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        doc = report(self.root, "--eval-results", str(results), "--eval", "from-issue:8")
        arms = {arm["arm"]: arm for arm in doc["arms"]}
        a, b = arms["aaaaaaaaaaaa/default"], arms["bbbbbbbbbbbb/default"]
        self.assertEqual((a["n"], a["delivered"], b["n"], b["delivered"]), (2, 2, 2, 1))
        self.assertAlmostEqual(a["dollars_per_delivered"], (dollars[1] + dollars[2]) / 2, places=9)
        self.assertAlmostEqual(a["sd"], statistics.stdev([dollars[1], dollars[2]]), places=9)
        self.assertAlmostEqual(b["dollars_per_delivered"], dollars[3] + dollars[4], places=9)
        self.assertEqual(sorted(row["verdict"] for row in doc["lineages"]),
                         ["FAIL", "PASS", "PASS", "PASS"])
        self.assertEqual(doc["interrupted"], [{"trial": 5, "tree_rev": "b" * 40, "claude_exit": 124}])

    def test_an_unknown_model_is_priced_approximately(self):
        session = Session(self.root)
        g = session.call(None, 0, context=10_000, write=10_000, ttl="1h", model="claude-opus-9",
                         bash=progress(1))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()
        self.assertEqual(report(self.root)["pricing"]["approximate_calls"], 1)

    def test_phase_seven_entry_and_an_owner_long_child_wait(self):
        session = Session(self.root)
        g5 = session.call(None, 0, context=50_000, write=50_000, ttl="1h", bash=progress(5))
        session.result(None, 5, g5, gate_reply("continue"))
        child = session.call(None, 10, context=51_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("i1", tool_use_id=child)
        session.call("i1", 20, context=20_000, write=20_000)
        session.call("i1", 500, context=21_000, write=1_000)
        session.result(None, 510, child, "done")
        g6 = session.call(None, 520, context=52_000, write=1_000, ttl="1h", bash=progress(6))
        session.result(None, 525, g6, gate_reply("delegate"))
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual((row["phase7_entered"], row["long_child_waits"], row["phase_reached"]),
                         (True, 1, 7))

    def test_owners_report_refuses_foreign_flags(self):
        for extra in (["--project", "x"], ["--artifacts", "docs"], ["--eval", "from-issue:8"],
                      ["--context-threshold", "5"]):
            with self.subTest(extra=extra):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners",
                     "--projects-dir", str(self.root), *extra],
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 2)

    def test_text_output_prints_the_six_tables(self):
        self.chain(Session(self.root)).write()
        out = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--days", "0",
             "--projects-dir", str(self.root)], capture_output=True, text=True, check=True).stdout
        for heading in ("Lineages", "Arms", "Fresh-owner boots by phase", "Simulated arms",
                        "Calibration", "Pricing: "):
            self.assertIn(heading, out)

    def test_a_boot_counts_stale_task_reads_and_their_persisted_rereads_as_slimmable(self):
        session = Session(self.root)
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        stale = session.call("o1", 100, context=20_000, write=20_000, read_file="/r/.tasks/task-3.md")
        session.result("o1", 101, stale, "task three\nOutput saved to: /tmp/persisted-1.txt\n")
        again = session.call("o1", 110, context=30_000, write=10_000, read_file="/tmp/persisted-1.txt")
        session.result("o1", 111, again, "the same text")
        review = session.call("o1", 120, context=36_000, write=6_000,
                              bash=f"sdd-gate review --run-id {RUN} --task 5")
        session.result("o1", 121, review, "ok")
        resumed = session.call("o1", 130, context=40_000, write=4_000, read_file="/r/.tasks/task-5.md")
        session.result("o1", 131, resumed, "task five")
        handoff = session.call("o1", 140, context=45_000, write=5_000,
                               read_file="/r/.superpowers/workflows/x/ship-handoff.md")
        session.result("o1", 141, handoff, "ship handoff")
        gate = session.call("o1", 150, context=60_000, write=15_000, bash=progress(6, action_id="7:1:2"))
        session.result("o1", 151, gate, gate_reply("continue", launch=2))
        session.write()
        [boot] = report(self.root)["boots"]
        # growth after each Read: 10k (task 3), 6k (its saved output), 5k (task 5, kept), 15k (ship-handoff)
        self.assertEqual((boot["phase_group"], boot["calls_p50"], boot["slimmable_p50"]),
                         ("6-7", 6, 10_000 + 6_000 + 15_000))

    def test_an_sdd_gate_owner_takes_its_identity_from_a_peer_with_its_action_id(self):
        session = Session(self.root)
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(3, action_id="9:1:1"))
        session.result(None, 5, g, gate_reply("continue", issue=9))
        dispatch = session.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        session.call("o1", 20, context=15_000, write=15_000,
                     bash=f"sdd-gate review --run-id {RUN} --action-id 9:1:1 --task 2")
        session.write()
        doc = report(self.root)
        [row] = doc["lineages"]
        self.assertEqual((row["issue"], row["launches"]), (9, 2))
        self.assertEqual(doc["unattributed"]["unresolved_owners"], 0)

    def test_an_owner_without_any_identity_is_unattributed_with_its_spend(self):
        session = Session(self.root)
        session.call(None, 0, context=15_000, write=15_000, ttl="1h",
                     bash=f"sdd-gate review --run-id {RUN} --action-id 9:1:1 --task 2")
        session.write()
        doc = report(self.root)
        self.assertEqual(doc["lineages"], [])
        self.assertEqual(doc["unattributed"]["unresolved_owners"], 1)
        self.assertAlmostEqual(doc["unattributed"]["dollars"], cost(15_000, 15_000, write_price=8.0),
                               places=9)

    def test_an_event_window_counts_only_the_calls_that_start_inside_it(self):
        self.chain(Session(self.root)).write()
        doc = report(self.root, "--events-since", at(90), "--events-before", at(200))
        [row] = doc["lineages"]
        self.assertEqual((row["launches"], row["handoffs"], row["boots"], row["peak_context"]),
                         (1, 0, 1, 99_000))
        a2 = [cost(29_000, 29_000), cost(50_000, 30_000), cost(75_000, 55_000),
              cost(98_000, 23_000), cost(99_000, 1_000)]
        self.assertAlmostEqual(row["owner_dollars"], sum(a2), places=9)
        self.assertAlmostEqual(row["total_dollars"] - row["owner_dollars"], cost(30_000, 30_000),
                               places=9)
