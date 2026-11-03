"""agent-costs --report owners (issue 432, spec test seam 1)."""
import json
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .owner_transcripts import (
    FINISH, RUN, STDERR_LINE, Session, at, cost, finish_reply, gate_reply, ping_cost, ping_line,
    progress, request_line)

DAY, HOUR = 86_400, 3_600


def report(root, *extra):
    completed = subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--format",
         "json", "--days", "0", "--projects-dir", str(root), *extra],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def run(root, *argv):
    """agent-costs over `root` with `argv`; the completed process, its exit status unchecked."""
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--projects-dir", str(root), *argv],
        capture_output=True, text=True, check=False)


TOP_KEYS = ["kind", "schema_version", "window", "start_grouping", "pricing", "lineages", "arms",
            "projects", "boots", "simulated", "calibration", "pings", "comparison", "unattributed",
            "interrupted", "unmatched"]
LINEAGE_KEYS = ["key", "run_id", "issue", "arm", "trial", "verdict", "direct", "launches",
                "handoffs", "boots", "deaths", "long_child_waits", "peak_context", "owner_dollars",
                "total_dollars", "delivered", "phase_reached", "phase7_entered", "gate_calls",
                "measured_gate_calls", "help_calls", "absolute_path_calls", "project", "started",
                "owner_ping_dollars", "ping_dollars"]


def text(root, *extra):
    """The owner report's text output over `root` (all time), which must exit 0."""
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--days", "0",
         "--projects-dir", str(root), *extra], capture_output=True, text=True, check=True).stdout


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

    def test_a_clean_exit_trial_with_no_matching_session_is_a_listed_gap(self):
        session = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo")
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()
        rows = [{"skill": "from-issue", "id": 8, "trial": 1, "verdict": "PASS",
                 "workdir": "/private/tmp/eval-from-issue-8.T1", "tree_rev": "a" * 40,
                 "policy": None, "claude_exit": 0},
                {"skill": "from-issue", "id": 8, "trial": 2, "verdict": "PASS",
                 "workdir": "/tmp/eval-from-issue-8.T2", "tree_rev": "a" * 40,
                 "policy": None, "claude_exit": 0}]
        results = self.root / "results.jsonl"
        results.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        doc = report(self.root, "--eval-results", str(results), "--eval", "from-issue:8")
        self.assertEqual([row["trial"] for row in doc["lineages"]], [1])
        self.assertEqual(doc["unmatched"], [{"trial": 2, "tree_rev": "a" * 40, "claude_exit": 0}])
        self.assertEqual(doc["interrupted"], [])

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

    def assert_usage_errors(self, *argvs):
        """Each argv is refused by a rule of agent-costs: exit 2 and nothing on stdout."""
        for argv in argvs:
            with self.subTest(argv=argv):
                completed = run(self.root, *argv)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""), completed.stderr)
                self.assertNotIn("unrecognized arguments", completed.stderr)

    def started_corpus(self):
        """Issue 7 starts on day 1 (2026-10-26T09:00Z) and spends until day 6, the report end;
        issue 8 starts the evening before 2026-10-25 and delivers on day 1; issue 9 starts on
        day 2.5; s4 is no owner's and calls on days 1 and 5."""
        s7 = Session(self.root, session="s7")
        g = s7.call(None, DAY, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, DAY + 5, g, gate_reply("continue"))
        s7.call(None, 3 * DAY + 12 * HOUR, context=21_000, write=21_000, ttl="1h")
        s7.call(None, 6 * DAY, context=22_000, write=22_000, ttl="1h")
        s7.write()
        s8 = Session(self.root, session="s8")
        g = s8.call(None, -10 * HOUR, context=20_000, write=20_000, ttl="1h",
                    bash=progress(3, action_id="8:1:1"))
        s8.result(None, -10 * HOUR + 5, g, gate_reply("continue", issue=8))
        f = s8.call(None, DAY, context=21_000, write=1_000, ttl="1h", bash=FINISH)
        s8.result(None, DAY + 5, f, finish_reply(8))
        s8.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 2 * DAY + 12 * HOUR, context=25_000, write=25_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 2 * DAY + 12 * HOUR + 5, g, gate_reply("continue", issue=9))
        s9.write()
        s4 = Session(self.root, session="s4")
        s4.call(None, DAY, context=10_000, write=10_000, ttl="1h")
        s4.call(None, 5 * DAY, context=11_000, write=1_000, ttl="1h")
        s4.write()
        return {7: cost(20_000, 20_000, write_price=8.0) + cost(21_000, 21_000, write_price=8.0)
                + cost(22_000, 22_000, write_price=8.0),
                9: cost(25_000, 25_000, write_price=8.0),
                "s4": cost(10_000, 10_000, write_price=8.0)}

    def test_a_start_window_counts_whole_settled_lineages_that_started_inside_it(self):
        costs = self.started_corpus()
        doc = report(self.root, "--started", "2026-10-25..2026-10-28")
        [row] = doc["lineages"]
        self.assertEqual((row["issue"], row["arm"], row["started"]),
                         (7, "live", "2026-10-26T09:00:00Z"))
        self.assertAlmostEqual(row["owner_dollars"], costs[7], places=9)   # days 3.5 and 6 too
        [arm] = doc["arms"]
        self.assertEqual((arm["n"], arm["delivered"]), (1, 0))   # issue 8's delivery is out
        self.assertEqual(doc["window"], "started 2026-10-25T00:00:00Z → 2026-10-28T00:00:00Z")
        grouping = doc["start_grouping"]
        self.assertEqual((grouping["settle_days"], grouping["report_end"]),
                         (4, "2026-10-31T09:00:00Z"))
        [window] = grouping["windows"]
        self.assertEqual((window["arm"], window["since"], window["before"],
                          window["unsettled"]["lineages"]),
                         ("live", "2026-10-25T00:00:00Z", "2026-10-28T00:00:00Z", 1))
        self.assertAlmostEqual(window["unsettled"]["dollars"], costs[9], places=9)
        lost = doc["unattributed"]
        self.assertEqual((lost["transcripts"], lost["unresolved_owners"]), (1, 0))
        self.assertAlmostEqual(lost["dollars"], costs["s4"], places=9)   # its day-5 call is out

    def test_settle_days_zero_counts_the_young_lineage_too(self):
        self.started_corpus()
        doc = report(self.root, "--started", "2026-10-25T00:00:00+00:00..2026-10-28T00:00:00Z",
                     "--settle-days", "0")
        self.assertEqual([(row["issue"], row["arm"]) for row in doc["lineages"]],
                         [(7, "live"), (9, "live")])
        self.assertEqual(doc["start_grouping"]["windows"][0]["unsettled"],
                         {"lineages": 0, "dollars": 0.0})

    def issueless_owner(self):
        """One owner whose action ID names no issue, with one call at T0 (2026-10-25T09:00Z)."""
        session = Session(self.root, session="s1")
        session.call(None, 0, context=20_000, write=20_000, ttl="1h",
                     bash=progress(3, action_id="x:1:1"))
        session.write()

    def test_an_event_window_still_counts_an_owner_without_an_issue_whose_calls_are_outside_it(self):
        self.issueless_owner()
        for extra in ([], ["--events-since", at(3600), "--events-before", at(7200)]):
            with self.subTest(extra=extra):
                self.assertEqual(report(self.root, *extra)["unattributed"]["unresolved_owners"], 1)

    def test_start_mode_counts_an_owner_without_an_issue_only_for_calls_inside_the_window(self):
        self.issueless_owner()
        for window, expected in (("2026-10-25..2026-10-26", (1, 1)),
                                 ("2026-10-26..2026-10-27", (0, 0))):
            with self.subTest(window=window):
                lost = report(self.root, "--started", window, "--settle-days", "0")["unattributed"]
                self.assertEqual((lost["unresolved_owners"], lost["transcripts"]), expected)

    def test_start_mode_usage_errors(self):
        window = "2026-10-25..2026-10-28"
        self.assert_usage_errors(
            ["--report", "boot", "--started", window],
            ["--settle-days", "4"],
            ["--report", "owners", "--settle-days", "4"],
            ["--report", "owners", "--started", window, "--events-since", at(0),
             "--events-before", at(60)],
            ["--report", "owners", "--started", window, "--eval-results", "r.jsonl",
             "--eval", "from-issue:8"],
            ["--report", "owners", "--started", window, "--settle-days", "-1"],
            ["--report", "owners", "--started", "2026-10-25"],
            ["--report", "owners", "--started", "2026-10-28..2026-10-25"],
            ["--report", "owners", "--started", "2026-10-25..2026-10-25"],
            ["--report", "owners", "--started", "2026-10-25..2026-10-32"],
            ["--report", "owners", "--started", "2026-10-25T00:00:00..2026-10-28"])

    def test_the_version_2_document_keys(self):
        self.chain(Session(self.root)).write()
        doc = report(self.root)
        self.assertEqual((list(doc), doc["schema_version"]), (TOP_KEYS, 2))
        self.assertEqual(list(doc["lineages"][0]), LINEAGE_KEYS)
        self.assertEqual((doc["start_grouping"], doc["pings"], doc["comparison"]), (None, None, None))

    def test_text_output_prints_projects_comparison_pings_and_unsettled(self):
        self.two_windows()
        log = self.root / "proxy.log"
        log.write_text(ping_line(30 * HOUR + 300, "s9", "k9", read=15_000), encoding="utf-8")
        out = text(self.root, "--baseline", "2026-10-25..2026-10-26", "--started",
                   "2026-10-26..2026-10-28", "--settle-days", "0", "--proxy-log", str(log))
        for line in ("Owner report (baseline ", "; settled 0d before ", "\nProjects (",
                     "\nComparison (", "\n$ / delivered: baseline ",
                     f"\nPings: 1 ping lines read from {log}; attributed ",
                     "\nUnsettled: 0 baseline lineages", "\nUnsettled: 0 candidate lineages"):
            self.assertIn(line, out)
        plain = text(self.root)
        self.assertIn("\nPings: not read (pass --proxy-log PATH)", plain)
        self.assertIn("\nProjects (", plain)
        for absent in ("\nComparison (", "\nUnsettled: "):
            self.assertNotIn(absent, plain)

    def test_eval_text_prints_no_pings_line(self):
        session = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo")
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()
        results = self.root / "results.jsonl"
        results.write_text(json.dumps({
            "skill": "from-issue", "id": 8, "trial": 1, "verdict": "PASS",
            "workdir": "/private/tmp/eval-from-issue-8.T1", "tree_rev": "a" * 40, "policy": None,
            "claude_exit": 0}) + "\n", encoding="utf-8")
        out = text(self.root, "--eval-results", str(results), "--eval", "from-issue:8")
        self.assertIn("\nProjects (", out)
        self.assertNotIn("Pings:", out)

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

    def test_a_boot_the_event_window_cuts_is_left_out_of_the_boots(self):
        # o1 boots from t = 10, dispatches w1 at t = 20 (out until t = 200) and registers at
        # t = 120; o2 boots from t = 10 and registers at t = 120 with no child. The window opens
        # at t = 50, so each boot's first calls are outside it: o1's counted boot would start at
        # a call with a child out (no call left), o2's at its registering call (start 50k, not 30k).
        session = Session(self.root)
        for owner, action in (("o1", "7:1:1"), ("o2", "8:1:1")):
            dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
            session.child(owner, tool_use_id=dispatch)
            session.call(owner, 10, context=30_000, write=30_000)
            if owner == "o1":
                work = session.call(owner, 20, context=40_000, write=10_000, agent_tool=True)
                session.child("w1", tool_use_id=work, parent=owner)
                session.call("w1", 30, context=20_000, write=20_000)
                session.call("w1", 200, context=21_000, write=1_000)
            gate = session.call(owner, 120, context=50_000, write=10_000,
                                bash=progress(3, action_id=action))
            session.result(owner, 121, gate, gate_reply("continue", issue=int(action[0])))
        session.write()
        for extra in ((), ("--sweep",)):
            with self.subTest(extra=extra):
                doc = report(self.root, "--events-since", at(50), "--events-before", at(1_000), *extra)
                self.assertEqual(doc["boots"], [])
                self.assertEqual(len(doc["lineages"]), 2)
                if extra:
                    self.assertEqual(doc["calibration"]["boots"], [])

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

    def test_an_event_window_clips_deliveries_with_the_spend(self):
        # the keeper's finish reply comes at t = 20, before a window opening at t = 50; the
        # owner's call at t = 100 keeps the lineage in that window
        session = Session(self.root)
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        session.result(None, 5, g, gate_reply("continue"))
        keeper = session.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("k1", tool_use_id=keeper)
        f = session.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        session.result("k1", 25, f, finish_reply(7))
        session.call(None, 100, context=22_000, write=1_000, ttl="1h")
        session.write()
        for since, delivered in ((0, True), (50, False)):
            with self.subTest(since=since):
                doc = report(self.root, "--events-since", at(since), "--events-before", at(1_000))
                [row] = doc["lineages"]
                self.assertEqual((row["delivered"], doc["arms"][0]["delivered"]),
                                 (delivered, int(delivered)))

    def assert_rows(self, actual, expected):
        """`actual` equals `expected` row for row and key for key, in order; floats to 9 places."""
        self.assertEqual(len(actual), len(expected))
        for got, want in zip(actual, expected):
            self.assertEqual(list(got), list(want))
            for name, value in want.items():
                if isinstance(value, float):
                    self.assertAlmostEqual(got[name], value, places=9, msg=name)
                else:
                    self.assertEqual(got[name], value, name)

    def test_project_rows_and_owner_dollars_per_lineage(self):
        delivered = Session(self.root, session="s1")
        g = delivered.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        delivered.result(None, 5, g, gate_reply("continue"))
        keeper = delivered.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        delivered.child("k1", tool_use_id=keeper)
        f = delivered.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        delivered.result("k1", 25, f, finish_reply(7))
        delivered.write()
        other = Session(self.root, project="-Users-me-other", session="s2", cwd="/Users/me/other")
        g8 = other.call(None, 0, context=30_000, write=30_000, ttl="1h",
                        bash=progress(3, action_id="8:1:1", repo_root="/Users/me/other"))
        other.result(None, 5, g8, gate_reply("continue", issue=8))
        other.write()
        doc = report(self.root)
        owner7 = cost(20_000, 20_000, write_price=8.0) + cost(21_000, 1_000, write_price=8.0)
        total7 = owner7 + cost(15_000, 15_000)
        owner8 = cost(30_000, 30_000, write_price=8.0)
        self.assertEqual([(row["owner_ping_dollars"], row["ping_dollars"]) for row in doc["lineages"]],
                         [(0.0, 0.0), (0.0, 0.0)])
        self.assert_rows(doc["arms"], [{
            "arm": "live", "n": 2, "delivered": 1, "delivery_rate": 0.5,
            "dollars_per_delivered": total7 + owner8,
            "owner_dollars_per_lineage": (owner7 + owner8) / 2, "sd": None,
            "undelivered_dollars": owner8, "ping_dollars": 0.0, "peak_p50": 21_000,
            "peak_p90": 30_000}])
        self.assert_rows(doc["projects"], [
            {"arm": "live", "project": "other", "n": 1, "delivered": 0, "delivery_rate": 0.0,
             "dollars_per_delivered": None, "owner_dollars_per_lineage": owner8,
             "owner_dollars": owner8, "owner_ping_dollars": 0.0, "total_dollars": owner8,
             "ping_dollars": 0.0},
            {"arm": "live", "project": "repo", "n": 1, "delivered": 1, "delivery_rate": 1.0,
             "dollars_per_delivered": total7, "owner_dollars_per_lineage": owner7,
             "owner_dollars": owner7, "owner_ping_dollars": 0.0, "total_dollars": total7,
             "ping_dollars": 0.0}])

    def test_a_lineage_s_project_is_its_registering_repo_root_and_its_start_its_first_owner_call(self):
        # o1 registers against /Users/me/repo while its records sit in another repository's
        # worktree; the dispatching root is no owner, so the lineage starts at o1's first call,
        # with or without an event window that cuts that call
        session = Session(self.root, cwd="/Users/me/other/.worktrees/worktree-issue-7")
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        session.call("o1", 10, context=20_000, write=20_000)
        g = session.call("o1", 20, context=30_000, write=10_000, bash=progress(3))
        session.result("o1", 21, g, gate_reply("continue"))
        session.write()
        for extra in ((), ("--events-since", at(15), "--events-before", at(1_000))):
            with self.subTest(extra=extra):
                [row] = report(self.root, *extra)["lineages"]
                self.assertEqual((row["project"], row["started"]), ("repo", "2026-10-25T09:00:10Z"))

    def test_an_unexpanded_repo_root_takes_the_project_of_the_records_cwd(self):
        session = Session(self.root, project="-Users-me-other--worktrees-worktree-issue-8",
                          cwd="/Users/me/other/.worktrees/worktree-issue-8")
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h",
                         bash=progress(3, action_id="8:1:1", repo_root='"$R"'))
        session.result(None, 5, g, gate_reply("continue", issue=8))
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual(row["project"], "other")

    def test_an_eval_trial_row_takes_the_project_and_start_of_its_first_lineage(self):
        # issue 9 starts first, but the trial's first lineage is issue 7 (lineages sort by issue)
        later = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo", session="s1")
        g9 = later.call(None, 0, context=20_000, write=20_000, ttl="1h",
                        bash=progress(3, action_id="9:1:1", repo_root="/Users/me/zed"))
        later.result(None, 5, g9, gate_reply("continue", issue=9))
        later.write()
        first = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo", session="s2")
        g7 = first.call(None, 30, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        first.result(None, 35, g7, gate_reply("continue"))
        first.write()
        results = self.root / "results.jsonl"
        results.write_text(json.dumps({
            "skill": "from-issue", "id": 8, "trial": 1, "verdict": "PASS",
            "workdir": "/private/tmp/eval-from-issue-8.T1", "tree_rev": "a" * 40, "policy": None,
            "claude_exit": 0}) + "\n", encoding="utf-8")
        [row] = report(self.root, "--eval-results", str(results), "--eval", "from-issue:8")["lineages"]
        self.assertEqual((row["project"], row["started"]), ("repo", "2026-10-25T09:00:30Z"))

    def two_windows(self):
        """Baseline (2026-10-25): issue 7 (repo, delivered) and issue 8 (other, through an
        unexpanded "$R"); candidate (2026-10-26 from 15:00Z): issue 9 (repo, delivered by its
        keeper k9) and issue 10 (repo)."""
        s7 = Session(self.root, session="s7")
        g = s7.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, 5, g, gate_reply("continue"))
        f = s7.call(None, 60, context=21_000, write=1_000, ttl="1h", bash=FINISH)
        s7.result(None, 65, f, finish_reply(7))
        s7.write()
        s8 = Session(self.root, project="-Users-me-other--worktrees-worktree-issue-8", session="s8",
                     cwd="/Users/me/other/.worktrees/worktree-issue-8")
        g = s8.call(None, HOUR, context=30_000, write=30_000, ttl="1h",
                    bash=progress(3, action_id="8:1:1", repo_root='"$R"'))
        s8.result(None, HOUR + 5, g, gate_reply("continue", issue=8))
        s8.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 30 * HOUR, context=40_000, write=40_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 30 * HOUR + 5, g, gate_reply("continue", issue=9))
        keeper = s9.call(None, 30 * HOUR + 10, context=41_000, write=1_000, ttl="1h", agent_tool=True)
        s9.child("k9", tool_use_id=keeper)
        f = s9.call("k9", 30 * HOUR + 20, context=15_000, write=15_000, bash=FINISH)
        s9.result("k9", 30 * HOUR + 25, f, finish_reply(9))
        s9.write()
        s10 = Session(self.root, session="s10")
        g = s10.call(None, 31 * HOUR, context=50_000, write=50_000, ttl="1h",
                     bash=progress(3, action_id="10:1:1"))
        s10.result(None, 31 * HOUR + 5, g, gate_reply("continue", issue=10))
        s10.write()
        return {7: cost(20_000, 20_000, write_price=8.0) + cost(21_000, 1_000, write_price=8.0),
                8: cost(30_000, 30_000, write_price=8.0),
                9: cost(40_000, 40_000, write_price=8.0) + cost(41_000, 1_000, write_price=8.0),
                "k9": cost(15_000, 15_000), 10: cost(50_000, 50_000, write_price=8.0)}

    def test_a_two_window_comparison_by_arm_and_project(self):
        c = self.two_windows()
        doc = report(self.root, "--baseline", "2026-10-25..2026-10-26",
                     "--started", "2026-10-26..2026-10-28", "--settle-days", "0")
        self.assertEqual([(row["issue"], row["arm"], row["project"]) for row in doc["lineages"]],
                         [(7, "baseline", "repo"), (8, "baseline", "other"),
                          (9, "candidate", "repo"), (10, "candidate", "repo")])
        self.assertEqual(doc["window"], "baseline 2026-10-25T00:00:00Z → 2026-10-26T00:00:00Z; "
                                        "candidate 2026-10-26T00:00:00Z → 2026-10-28T00:00:00Z")
        self.assertEqual([window["arm"] for window in doc["start_grouping"]["windows"]],
                         ["baseline", "candidate"])
        base_owner, cand_owner = (c[7] + c[8]) / 2, (c[9] + c[10]) / 2
        cand_spend = c[9] + c["k9"] + c[10]
        self.assert_rows(doc["arms"], [
            {"arm": "baseline", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": c[7] + c[8], "owner_dollars_per_lineage": base_owner,
             "sd": None, "undelivered_dollars": c[8], "ping_dollars": 0.0, "peak_p50": 21_000,
             "peak_p90": 30_000},
            {"arm": "candidate", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": cand_spend, "owner_dollars_per_lineage": cand_owner,
             "sd": None, "undelivered_dollars": c[10], "ping_dollars": 0.0, "peak_p50": 41_000,
             "peak_p90": 50_000}])
        self.assert_rows(doc["projects"], [
            {"arm": "baseline", "project": "other", "n": 1, "delivered": 0, "delivery_rate": 0.0,
             "dollars_per_delivered": None, "owner_dollars_per_lineage": c[8],
             "owner_dollars": c[8], "owner_ping_dollars": 0.0, "total_dollars": c[8],
             "ping_dollars": 0.0},
            {"arm": "baseline", "project": "repo", "n": 1, "delivered": 1, "delivery_rate": 1.0,
             "dollars_per_delivered": c[7], "owner_dollars_per_lineage": c[7],
             "owner_dollars": c[7], "owner_ping_dollars": 0.0, "total_dollars": c[7],
             "ping_dollars": 0.0},
            {"arm": "candidate", "project": "repo", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": cand_spend, "owner_dollars_per_lineage": cand_owner,
             "owner_dollars": c[9] + c[10], "owner_ping_dollars": 0.0, "total_dollars": cand_spend,
             "ping_dollars": 0.0}])
        comparison = doc["comparison"]
        self.assertEqual(list(comparison),
                         ["owner_dollars_per_lineage_ratio", "dollars_per_delivered_ratio", "projects"])
        self.assertAlmostEqual(comparison["owner_dollars_per_lineage_ratio"], cand_owner / base_owner,
                               places=9)
        self.assertAlmostEqual(comparison["dollars_per_delivered_ratio"], cand_spend / (c[7] + c[8]),
                               places=9)
        self.assert_rows(comparison["projects"], [
            {"project": "other", "owner_dollars_per_lineage_ratio": None, "delivery_rate_change": None},
            {"project": "repo", "owner_dollars_per_lineage_ratio": cand_owner / c[7],
             "delivery_rate_change": -0.5}])

    def test_a_window_with_no_lineage_keeps_an_arm_row_with_n_0(self):
        self.two_windows()
        doc = report(self.root, "--baseline", "2026-10-25..2026-10-26",
                     "--started", "2026-11-01..2026-11-02", "--settle-days", "0")
        self.assertEqual([arm["arm"] for arm in doc["arms"]], ["baseline", "candidate"])
        self.assert_rows(doc["arms"][1:], [{
            "arm": "candidate", "n": 0, "delivered": 0, "delivery_rate": None,
            "dollars_per_delivered": None, "owner_dollars_per_lineage": None, "sd": None,
            "undelivered_dollars": 0.0, "ping_dollars": 0.0, "peak_p50": 0, "peak_p90": 0}])
        self.assertEqual([(row["arm"], row["project"]) for row in doc["projects"]],
                         [("baseline", "other"), ("baseline", "repo")])
        comparison = doc["comparison"]
        self.assertEqual((comparison["owner_dollars_per_lineage_ratio"],
                          comparison["dollars_per_delivered_ratio"]), (None, None))

    def test_the_replay_runs_over_one_start_window(self):
        self.two_windows()
        doc = report(self.root, "--started", "2026-10-25..2026-10-28", "--settle-days", "0",
                     "--policy", "slim=boot=slim")
        self.assertEqual((len(doc["lineages"]), doc["comparison"]), (4, None))
        self.assertTrue(doc["calibration"]["identity_matches"])

    def test_comparison_usage_errors(self):
        started = ["--report", "owners", "--started", "2026-10-26..2026-10-28"]
        self.assert_usage_errors(
            ["--report", "boot", "--baseline", "2026-10-25..2026-10-26"],
            ["--report", "owners", "--baseline", "2026-10-25..2026-10-26"],
            started + ["--baseline", "2026-10-27..2026-10-29"],
            started + ["--baseline", "2026-10-26..2026-10-28"],
            started + ["--baseline", "2026-10-25"],
            started + ["--baseline", "2026-10-25..2026-10-26", "--policy", "slim=boot=slim"],
            started + ["--baseline", "2026-10-25..2026-10-26", "--sweep"])

    def test_pings_are_priced_and_attributed_or_unattributed_within_the_event_window(self):
        session = Session(self.root)
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        g = session.call("o1", 10, context=30_000, write=30_000, bash=progress(3))
        session.result("o1", 11, g, gate_reply("continue"))
        work = session.call("o1", 20, context=31_000, write=1_000, agent_tool=True)
        session.child("w1", tool_use_id=work, parent="o1")
        session.call("w1", 30, context=20_000, write=20_000)
        session.write()
        log = self.root / "proxy.log"
        log.write_text("".join([
            ping_line(100, "s1", "o1", read=31_000),
            ping_line(110, "s1", "w1", read=20_000, model="claude-opus-9"),   # priced approximately
            ping_line(120, "s1", "o1", priced=False),
            ping_line(130, "s9", "x1", read=40_000),                          # no such transcript
            ping_line(5_000, "s9", "x1", read=40_000),
            ping_line(5_000, "s1", "o1", read=31_000),
            request_line(140), STDERR_LINE,
            '{"event":"ping","conversation":"0123456789ab"}\n',               # no ts
        ]), encoding="utf-8")
        owner, worker, lost = ping_cost(31_000), ping_cost(20_000), ping_cost(40_000)
        window = ("--events-since", at(0), "--events-before", at(1_000))
        for extra, attributed, unattributed in (
                (window, (3, owner + worker, owner), (1, lost)),
                ((), (4, 2 * owner + worker, 2 * owner), (2, 2 * lost))):
            with self.subTest(extra=extra):
                doc = report(self.root, "--proxy-log", str(log), *extra)
                pings = doc["pings"]
                self.assertEqual((pings["log"], pings["lines"], pings["skipped_lines"],
                                  pings["unpriced"], pings["attributed"]["pings"],
                                  pings["unattributed"]["pings"]),
                                 (str(log), 6, 2, 1, attributed[0], unattributed[0]))
                self.assertAlmostEqual(pings["attributed"]["dollars"], attributed[1], places=9)
                self.assertAlmostEqual(pings["attributed"]["owner_dollars"], attributed[2], places=9)
                self.assertAlmostEqual(pings["unattributed"]["dollars"], unattributed[1], places=9)
                self.assertEqual(doc["pricing"]["approximate_calls"], 1)
                [row] = doc["lineages"]
                self.assertAlmostEqual(row["owner_dollars"], cost(30_000, 30_000) + cost(31_000, 1_000),
                                       places=9)   # calls only
                self.assertAlmostEqual(row["owner_ping_dollars"], attributed[2], places=9)
                self.assertAlmostEqual(row["ping_dollars"], attributed[1], places=9)
                [arm] = doc["arms"]
                self.assertAlmostEqual(arm["ping_dollars"], attributed[1], places=9)
                self.assertAlmostEqual(arm["owner_dollars_per_lineage"],
                                       row["owner_dollars"] + attributed[2], places=9)
                self.assertAlmostEqual(arm["undelivered_dollars"],
                                       row["total_dollars"] + attributed[1], places=9)

    def test_a_left_out_lineage_s_pings_are_neither_attributed_nor_unattributed(self):
        s7 = Session(self.root, session="s7")
        g = s7.call(None, DAY, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, DAY + 5, g, gate_reply("continue"))
        s7.call(None, 6 * DAY, context=21_000, write=1_000, ttl="1h")
        s7.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 2 * DAY + 12 * HOUR, context=25_000, write=25_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 2 * DAY + 12 * HOUR + 5, g, gate_reply("continue", issue=9))
        s9.write()
        log = self.root / "proxy.log"
        log.write_text("".join([
            ping_line(DAY + 300, "s7", read=20_000),                   # settled issue 7's root
            ping_line(6 * DAY + 300, "s7", read=21_000),               # ... after the start window
            ping_line(2 * DAY + 12 * HOUR + 300, "s9", read=25_000),   # unsettled issue 9's root
            ping_line(DAY + 600, "s0", "x1", read=40_000),             # no transcript, in the window
            ping_line(4 * DAY, "s0", "x1", read=40_000),               # no transcript, after it
        ]), encoding="utf-8")
        doc = report(self.root, "--started", "2026-10-25..2026-10-28", "--proxy-log", str(log))
        self.assertEqual([row["issue"] for row in doc["lineages"]], [7])
        self.assertEqual(doc["start_grouping"]["windows"][0]["unsettled"]["lineages"], 1)
        pings = doc["pings"]
        self.assertEqual((pings["lines"], pings["attributed"]["pings"],
                          pings["unattributed"]["pings"]), (5, 2, 1))
        # an attributed ping counts in full, even after the start window (PR-02)
        self.assertAlmostEqual(pings["attributed"]["owner_dollars"],
                               ping_cost(20_000) + ping_cost(21_000), places=9)
        [row] = doc["lineages"]
        self.assertAlmostEqual(row["owner_ping_dollars"], ping_cost(20_000) + ping_cost(21_000),
                               places=9)
        self.assertAlmostEqual(pings["unattributed"]["dollars"], ping_cost(40_000), places=9)

    def test_proxy_log_usage_errors_and_an_unreadable_log(self):
        self.assert_usage_errors(
            ["--report", "boot", "--proxy-log", "proxy.log"],
            ["--report", "owners", "--proxy-log", "proxy.log", "--eval-results", "r.jsonl",
             "--eval", "from-issue:8"])
        completed = run(self.root, "--report", "owners", "--proxy-log", str(self.root / "missing.log"))
        self.assertEqual((completed.returncode, completed.stdout), (1, ""))
        self.assertTrue(completed.stderr.startswith("cannot read proxy log: "), completed.stderr)

    def test_a_ping_whose_usage_cannot_be_priced_is_skipped(self):
        session = Session(self.root)
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()

        def bad(seconds, **usage):
            """An owner ping whose `usage` is the priced one with `usage`'s fields replaced."""
            entry = json.loads(ping_line(seconds, "s1", read=20_000))
            entry["usage"].update(usage)
            return json.dumps(entry) + "\n"   # NaN and Infinity as Python's json writes them

        log = self.root / "proxy.log"
        log.write_text("".join([
            ping_line(100, "s1", read=20_000),
            bad(110, input_tokens="oops"),
            bad(120, cache_read_input_tokens=float("nan")),
            bad(130, output_tokens=-5),
            bad(140, input_tokens=True),
            bad(150, cache_creation="x"),
            bad(160, cache_creation={"ephemeral_1h_input_tokens": float("inf")}),
            ping_line(200, "s1", read=20_000),
        ]), encoding="utf-8")
        doc = report(self.root, "--proxy-log", str(log))
        pings = doc["pings"]
        self.assertEqual((pings["lines"], pings["skipped_lines"], pings["unpriced"],
                          pings["attributed"]["pings"], pings["unattributed"]["pings"]),
                         (2, 6, 0, 2, 0))
        self.assertAlmostEqual(pings["attributed"]["owner_dollars"], 2 * ping_cost(20_000), places=9)
        [row] = doc["lineages"]
        self.assertAlmostEqual(row["ping_dollars"], 2 * ping_cost(20_000), places=9)
