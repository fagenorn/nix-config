"""Offline tests for agent_tools.run_profile on synthetic Workflow run dirs (#715).

Run: just agent-workflow-tests
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from agent_tools import run_profile

RELAY = "[Workflow harness — user request] The harness relays the user request:\n  deliver #99"
# Two records of one message id whose per-field maxima fall in different records:
# max per field = input 10 (A), cache_creation 5 (B), cache_read 100 (A), output 3 (B).
# Keeping the first record, the last one, or summing both gives a different result.
U1A = {"input_tokens": 10, "cache_creation_input_tokens": 2,
       "cache_read_input_tokens": 100, "output_tokens": 1}
U1B = {"input_tokens": 4, "cache_creation_input_tokens": 5,
       "cache_read_input_tokens": 60, "output_tokens": 3}


def user(text, ts="2026-11-08T10:00:00Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


def reply(mid, usage, content=(), ts="2026-11-08T10:05:00Z"):
    message = {"usage": usage, "content": list(content)}
    if mid is not None:
        message["id"] = mid
    return {"type": "assistant", "timestamp": ts, "message": message}


def tool(tid):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {}}


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write((record if isinstance(record, str) else json.dumps(record)) + "\n")


def make_run(root, name, agents, journal=True):
    """agents: (agent_id, label, phase, records, result, meta) tuples."""
    run = Path(root) / name
    run.mkdir()
    lines = [{"type": "launched"}, "not json", [1]]
    for aid, label, phase, records, result, meta in agents:
        write_jsonl(run / f"agent-{aid}.jsonl", records)
        if meta is not None:
            with open(run / f"agent-{aid}.meta.json", "w", encoding="utf-8") as handle:
                json.dump(meta, handle)
        if label is not None:
            lines.append({"type": "started", "key": aid, "agentId": aid, "label": label, "phase": phase})
            lines.append({"type": "result", "key": aid, "agentId": aid, "result": result})
    if journal:
        write_jsonl(run / "journal.jsonl", lines)
    return run


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.batch = make_run(root, "wf_batch", [
            ("a1", "setup", "Setup", [user("Set up the run"), reply("s1", {"input_tokens": 100, "output_tokens": 10})],
             {"ok": True, "slug": "acme/widgets"}, {"model": "sonnet", "workflowPhase": "Other", "description": "other"}),
            ("a2", "land-merge-12", "Land", [user("Merge PR 7"), reply("m-a2", {"input_tokens": 50, "output_tokens": 5})],
             {"merged": True}, None),
            ("a3", "plan", "▸ deliver-standard", [
                user(RELAY), user("Issue #12 of acme/widgets: plan it"),
                reply("m1", U1A, [{"type": "text", "text": "planning"}], ts="2026-11-08T10:10:00Z"),
                reply("m1", U1B, [tool("t1")], ts="2026-11-08T10:20:00Z"),
                reply("m2", {"input_tokens": 1, "output_tokens": 1}, ts="2026-11-08T10:30:00Z")],
             {"status": "planned"}, None),
            ("a4", "close-out-12", "Land", [user("Issue #12 of acme/widgets: close out"),
                                            reply("m-a4", {"input_tokens": 20, "output_tokens": 10})],
             {"issue_state": "CLOSED", "released": True}, None),
            ("a5", "impl-1", "▸ deliver-standard #2", [
                user("Issue #34 of acme/widgets: task 1"),
                reply("m-a5", {"input_tokens": 900, "cache_creation_input_tokens": 50, "output_tokens": 50})],
             {"status": "done"}, None),
        ])
        self.child = make_run(root, "wf_child", [
            ("b1", "setup", "Setup", [reply("m-b1", {"input_tokens": 10})], {"ok": True, "slug": "other/repo"}, None),
            ("b2", "plan-revise", "Plan", [
                {"type": "user", "timestamp": "2026-11-08T10:00:00Z",
                 "message": {"role": "user", "content": [{"type": "text", "text": "Issue #12 of other/repo: revise"}]}},
                reply("m-b2", {"input_tokens": 7})], {"status": "planned"}, None),
            ("b3", "close-out", "Ship", [user("Issue #12 of other/repo: close out"), reply("m-b3", {"input_tokens": 3})],
             {"issue_state": "OPEN", "released": True}, None),  # a held issue: released, left OPEN
            ("b4", "close-out", "▸ deliver-standard #3", [user("Issue #40 of other/repo: close out"),
                                                          reply("m-b4", {"input_tokens": 2})],
             {"issue_state": "OPEN", "released": False}, None),
            ("b5", "close-out", "▸ deliver-standard #4", [user("Issue #41 of other/repo: close out"),
                                                          reply("m-b5", {"input_tokens": 4})],
             {"issue_state": "CLOSED", "released": False}, None),  # closed but not released
        ])
        self.bare = make_run(root, "wf_bare", [
            ("c1", None, None, [reply("m-c1", {"input_tokens": 5})], None,
             {"workflowPhase": "Plan", "description": "plan-revise-2", "model": "opus"}),
            ("c2", None, None, [user("no issue here"), reply("m-c2", {"input_tokens": 1})], None, None),
        ], journal=False)
        self.report = run_profile.profile_runs([self.batch, self.child, self.bare])

    def agent(self, aid):
        return next(a for a in self.report["agents"] if a["agent_id"] == aid)


class DedupTest(Fixture):
    def test_a_repeated_message_id_counts_its_usage_once_and_keeps_its_tool_call(self):
        stats = run_profile.agent_stats(self.batch / "agent-a3.jsonl")
        self.assertEqual(stats, {"fresh": 20, "cache_read": 100, "output": 4, "tools": 1,
                                 "minutes": 30.0, "first_prompt": "Issue #12 of acme/widgets: plan it",
                                 "read_error": None})

    def test_assistant_records_without_an_id_each_count(self):
        path = Path(self.tmp.name) / "agent-noid.jsonl"
        write_jsonl(path, [reply(None, {"input_tokens": 4}, [tool("x")]), reply(None, {"input_tokens": 4}, [tool("x")])])
        stats = run_profile.agent_stats(path)
        self.assertEqual((stats["fresh"], stats["tools"], stats["minutes"]), (8, 1, 0.0))

    def test_a_line_that_is_not_valid_utf8_is_skipped(self):
        path = Path(self.tmp.name) / "agent-trunc.jsonl"
        good = json.dumps(reply("m", {"input_tokens": 3}))
        with open(path, "wb") as handle:
            handle.write(b'{"type":"user","message":{"content":"Issue #5 x"}}\n')
            handle.write(b'{"type":"assistant","message":{"content":"caf\xff"}}\n')  # bad byte mid-file
            handle.write(good.encode("utf-8") + b"\n")
            handle.write(b'{"type":"assistant","message":{"id":"z","content":[{"type":"text","text":"caf\xc3')
        stats = run_profile.agent_stats(path)  # the cut final line must not raise
        self.assertEqual((stats["fresh"], stats["first_prompt"]), (3, "Issue #5 x"))


class ReadFailureTest(Fixture):
    def test_a_transcript_that_cannot_be_opened_is_reported_incomplete(self):
        run = make_run(self.tmp.name, "wf_bad", [("g1", "setup", "Setup", [reply("m", {"input_tokens": 2})],
                                                  {"slug": "a/b"}, None)])
        (run / "agent-g2.jsonl").mkdir()  # globbed as a transcript; opening it raises OSError
        report = run_profile.profile_runs([run])
        self.assertEqual([(i["run"], i["file"]) for i in report["incomplete"]], [("wf_bad", "agent-g2.jsonl")])
        self.assertIn("IsADirectoryError", report["incomplete"][0]["error"])
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            code = run_profile.main([str(run), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out.getvalue())["incomplete"]), 1)
        self.assertIn("incomplete evidence: wf_bad/agent-g2.jsonl", err.getvalue())

    def test_a_read_error_mid_file_keeps_the_records_read_and_flags_the_file(self):
        class Flaky:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def __iter__(self):
                yield json.dumps(reply("m", {"input_tokens": 6})).encode("utf-8") + b"\n"
                raise OSError("read error")
        path = Path(self.tmp.name) / "agent-flaky.jsonl"
        with mock.patch.object(run_profile, "open", return_value=Flaky(), create=True):
            stats = run_profile.agent_stats(path)
        self.assertEqual(stats["fresh"], 6)
        self.assertEqual(stats["read_error"], "OSError: read error")

    def test_an_absent_journal_and_meta_are_not_incomplete(self):
        self.assertEqual(self.report["incomplete"], [])
        self.assertEqual(run_profile.main([str(self.bare)]), 0)


class FamilyTest(Fixture):
    def test_label_family_strips_every_numeric_part(self):
        for label, family in (("land-lock-12-1", "land-lock"), ("renew-12-land", "renew-land"),
                              ("impl-1", "impl"), ("fix-2-3", "fix"), ("setup", "setup"), ("", "")):
            with self.subTest(label=label):
                self.assertEqual(run_profile.label_family(label), family)

    def test_families_sum_agents_and_tokens(self):
        families = {f["family"]: f for f in self.report["families"]}
        self.assertEqual((families["close-out"]["agents"], families["close-out"]["fresh"]), (4, 39))
        self.assertEqual((families["plan-revise"]["agents"], families["plan-revise"]["fresh"]), (2, 12))
        self.assertEqual((families["setup"]["agents"], families["setup"]["fresh"]), (2, 120))
        self.assertEqual([f["family"] for f in self.report["families"][:2]], ["impl", "setup"])

    def test_phase_totals_come_from_the_journal(self):
        phases = {(p["run"], p["phase"]): p for p in self.report["phases"]}
        land = phases[("wf_batch", "Land")]
        self.assertEqual((land["agents"], land["fresh"]), (2, 85))
        self.assertNotIn(("wf_batch", "Other"), phases)


class AttributionTest(Fixture):
    def test_batch_label_suffix_names_the_issue_only_in_batch_phases(self):
        self.assertEqual(run_profile.label_issue("land-lock-12-1", "Land"), 12)
        self.assertEqual(run_profile.label_issue("renew-12-land", "Land"), 12)
        self.assertEqual(run_profile.label_issue("facts-683", "Intake"), 683)
        self.assertIsNone(run_profile.label_issue("impl-1", "Tasks"))
        self.assertIsNone(run_profile.label_issue("land-lock-1", "Ship"))
        self.assertIsNone(run_profile.label_issue("setup", "Setup"))

    def test_other_agents_take_the_first_issue_of_their_first_prompt(self):
        self.assertEqual(run_profile.prompt_issue("Issue #12 of x: see #99"), 12)
        self.assertIsNone(run_profile.prompt_issue("no issue"))

    def test_an_explicit_issue_reference_beats_an_earlier_pull_request_number(self):
        # The landing-lock prompt of deliver-standard.js, whose PR number comes first.
        lock = ("Take the cross-host landing lock of the branch main for PR #800 of issue #715 "
                "of acme/widgets at the head abc.")
        self.assertEqual(run_profile.prompt_issue(lock), 715)
        self.assertEqual(run_profile.prompt_issue("Push the branch b of PR #800 at the head abc."), None)
        self.assertEqual(run_profile.prompt_issue("see #5, then Issue #7"), 7)
        self.assertEqual(run_profile.prompt_issue("PR #8 then #9"), 9)

    def test_a_pull_request_number_does_not_steal_the_issues_tokens(self):
        root = self.tmp.name
        run = make_run(root, "wf_lock", [
            ("l1", "setup", "Setup", [reply("ms", {"input_tokens": 1})], {"slug": "acme/widgets"}, None),
            ("l2", "land-lock-715", "Ship", [
                user("Take the cross-host landing lock of the branch main for PR #800 of issue #715 of acme/widgets."),
                reply("ml", {"input_tokens": 30})], {}, None),
            ("l3", "close-out", "Ship", [user("Issue #715 of acme/widgets: close out"),
                                         reply("mc", {"input_tokens": 5})],
             {"issue_state": "CLOSED", "released": True}, None)])
        report = run_profile.profile_runs([run])
        self.assertEqual([r["agent_id"] for r in report["agents"] if r["issue"] == 715], ["l2", "l3"])
        self.assertEqual([(r["issue"], r["agents"], r["fresh"]) for r in report["issues"]], [(715, 2, 35)])
        self.assertEqual(self.agent("a3")["issue"], 12)  # the relay's #99 is skipped
        self.assertEqual(self.agent("a5")["issue"], 34)  # impl-1 is a counter, not issue 1
        self.assertEqual(self.agent("b2")["issue"], 12)  # list-form prompt
        self.assertIsNone(self.agent("a1")["issue"])

    def test_missing_journal_and_meta_fall_back(self):
        c1, c2 = self.agent("c1"), self.agent("c2")
        self.assertEqual((c1["phase"], c1["label"], c1["family"], c1["model"], c1["slug"]),
                         ("Plan", "plan-revise-2", "plan-revise", "opus", None))
        self.assertEqual((c2["phase"], c2["label"], c2["model"], c2["issue"]), ("", "", "?", None))
        self.assertEqual(self.agent("a1")["phase"], "Setup")  # journal wins over meta


class IssueTest(Fixture):
    def test_issues_are_scoped_by_repository_slug(self):
        rows = {(r["slug"], r["issue"]): r for r in self.report["issues"]}
        self.assertEqual(rows[("acme/widgets", 12)], {"slug": "acme/widgets", "issue": 12, "agents": 3,
                                                       "fresh": 105, "cache_read": 100, "planner_calls": 1})
        self.assertEqual(rows[("other/repo", 12)], {"slug": "other/repo", "issue": 12, "agents": 2,
                                                     "fresh": 10, "cache_read": 0, "planner_calls": 1})
        self.assertEqual(self.agent("b3")["slug"], "other/repo")
        self.assertEqual([r["slug"] for r in self.report["runs"]], ["acme/widgets", "other/repo", None])

    def test_only_issues_with_a_released_close_out_are_counted(self):
        keys = [(r["slug"], r["issue"]) for r in self.report["issues"]]
        # other/repo#12 counts through an OPEN, released close-out (a held issue);
        # #41's CLOSED, unreleased close-out does not count; #34 and #40 have none released.
        self.assertEqual(keys, [("acme/widgets", 12), ("other/repo", 12)])


class CommandTest(Fixture):
    def test_json_output_with_a_journal_present(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.run_profile", str(self.batch), str(self.child),
             "--json", "--top", "2"], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        doc = json.loads(completed.stdout)
        self.assertEqual(sorted(doc), ["agents", "families", "incomplete", "issues", "phases", "runs"])
        self.assertEqual([a["agent_id"] for a in doc["agents"]], ["a5", "a1"])
        self.assertEqual(len(doc["families"]), 2)
        self.assertEqual([(r["slug"], r["issue"]) for r in doc["issues"]], [("acme/widgets", 12), ("other/repo", 12)])
        self.assertEqual(doc["runs"][0], {"run": "wf_batch", "slug": "acme/widgets", "journal": True, "agents": 5})

    def test_text_output_prints_each_table(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_profile.main([str(self.batch), str(self.child), str(self.bare)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        for heading in ("run | phase | agents | fresh tok | cache-read tok | agent-min",
                        "Top agents by fresh tokens", "By label family",
                        "Per issue (successful terminal result)"):
            self.assertIn(heading, text)
        self.assertIn("acme/widgets#12 | 3 | 105 | 100 | 1", text)

    def test_a_missing_run_dir_exits_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = run_profile.main([str(Path(self.tmp.name) / "absent")])
        self.assertEqual(code, 2)
        self.assertIn("agent-run-profile: not a directory:", err.getvalue())

    def test_top_below_one_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            run_profile.main([str(self.batch), "--top", "0"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
