"""The console's spend reader (#1134): pricing, phases, incremental transcript reading."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import sessions, spend
from agent_tools.console.event_log import Event
from agent_tools.console.spend import AGENT, BATCH, OTHER, PING, SESSION, STANDARD, Key, Tokens
from agent_tools.hosts import model_pricing
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-16"
SINCE = "2026-10-18"


class CountingFile:
    """A binary file whose `read` adds the bytes it returns to the owner's counter."""

    def __init__(self, owner, handle):
        self._owner, self._handle = owner, handle

    def read(self, n=-1):
        data = self._handle.read(n)
        self._owner.bytes += len(data)
        return data

    def seek(self, *args):
        return self._handle.seek(*args)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def close(self):
        return self._handle.close()


class CountingOpener:
    def __init__(self, fail=None):
        self.calls, self.bytes, self.fail = 0, 0, fail

    def __call__(self, path):
        self.calls += 1
        if self.fail is not None and self.fail[0]:
            raise PermissionError("denied")
        return CountingFile(self, open(path, "rb"))


def assistant(mid, day, *, sid="s1", model="claude-sonnet-4-6", input=0, write=0, read=0,
              output=0):
    line = {"type": "assistant", "sessionId": sid, "timestamp": f"{day}T10:00:00.000Z",
            "cwd": "/srv/p00",
            "message": {"id": mid, "model": model,
                        "usage": {"input_tokens": input, "cache_creation_input_tokens": write,
                                  "cache_read_input_tokens": read, "output_tokens": output}}}
    return (json.dumps(line) + "\n").encode()


def priced_input(n, model="claude-sonnet-4-6"):
    return spend.priced(model, {"input_tokens": n})


class PricedTest(unittest.TestCase):
    def test_known_model_uses_table_rates(self):
        tokens = spend.priced("claude-sonnet-4-6", {
            "input_tokens": 1_000_000, "output_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000})
        self.assertEqual((tokens.input, tokens.output, tokens.cache_read, tokens.cache_write),
                         (1_000_000,) * 4)
        self.assertAlmostEqual(tokens.dollars, 22.05)  # 3 + 15 + 0.30 + 3.75
        self.assertIs(tokens.approximate, False)

    def test_unknown_model_is_approximate(self):
        usage = {"input_tokens": 1_000_000}
        tokens = spend.priced("claude-opus-9-9", usage)
        self.assertIs(tokens.approximate, True)
        self.assertEqual(tokens.dollars, model_pricing.usage_cost("claude-opus-9-9", usage)[0])

    def test_unusable_usage_is_none(self):
        for usage in ("x", {"input_tokens": -1}, {"input_tokens": True}, {"output_tokens": 1.5},
                      {"cache_creation": {"ephemeral_1h_input_tokens": -2}}):
            with self.subTest(usage=usage):
                self.assertIsNone(spend.priced("claude-sonnet-4-6", usage))
        self.assertEqual(spend.priced("claude-sonnet-4-6", {}), Tokens())

    def test_add_sums_and_ors_approximate(self):
        self.assertEqual(Tokens(1, 2, 3, 4, 0.5, False) + Tokens(1, 1, 1, 1, 0.25, True),
                         Tokens(2, 3, 4, 5, 0.75, True))
        self.assertEqual(Tokens(dollars=0.123456).wire()["dollars"], 0.1235)


class PhaseTest(unittest.TestCase):
    def test_labels_map_to_phases(self):
        rows = {
            "setup": "setup", "facts-12": "setup", "acquire-3": "setup", "owner-answer": "setup",
            "train-sweep-2": "setup", "plan": "plan", "plan-codex": "plan review",
            "plan-review-again": "plan review", "plan-task-revise": "plan revise",
            "plan-branch-revise": "plan revise", "impl-2": "implement",
            "direct-impl": "implement", "review-2": "task review",
            "rereview-2-1": "task review", "fix-2-1": "task review", "fix-ci": "task review",
            "final-1": "final review", "final-codex": "final review", "fix-wave": "fix wave",
            "fix-wave-review-2": "fix wave", "verify": "verify", "verify-rerun-1": "verify",
            "pr": "land", "merge": "land", "checks-3": "land", "land-pr-12": "land",
            "land-lock-12-1": "land", "land-record-12": "land", "sync-resolve-3": "land",
            "fix-sync-2": "land", "train-merge-4": "land", "close-out": "close-out",
            "close-out-12": "close-out", "land-unlock": "close-out", "hold": "close-out",
            "recover-end-3": OTHER, "nonsense": OTHER,
        }
        for label, phase in rows.items():
            with self.subTest(label=label):
                self.assertEqual(spend.phase_of(label), phase)

    def test_run_program(self):
        self.assertEqual(spend.run_program({"Setup", "Intake"}), BATCH)
        self.assertEqual(spend.run_program({"Setup", "Plan"}), STANDARD)
        self.assertEqual(spend.run_program({"Setup"}), OTHER)


class ReaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.projects = self.tmp / "projects"
        self.slug = self.projects / "-srv-p00"
        self.slug.mkdir(parents=True)
        self.opener = CountingOpener()

    def reader(self, **kwargs):
        return spend.SpendReader(opener=self.opener, **kwargs)

    def transcript(self, sid="s1", *lines):
        path = self.slug / f"{sid}.jsonl"
        path.write_bytes(b"".join(lines))
        return path

    def run_dir(self, run="wf_1", sid="s1"):
        path = self.slug / sid / "subagents" / "workflows" / run
        path.mkdir(parents=True, exist_ok=True)
        return path

    def totals(self, reader):
        return reader.snapshot().totals

    def test_counts_each_message_id_once(self):
        a, b = assistant("A", DAY, input=10), assistant("B", DAY, input=5)
        self.transcript("s1", a, a, b)
        reader = self.reader()
        reader.read([self.projects], SINCE)
        expected = priced_input(10) + priced_input(5)
        self.assertEqual(self.totals(reader), {Key(DAY, "s1", None, None, SESSION): expected})
        self.assertEqual(expected.input, 15)

    def test_a_repeated_message_id_keeps_the_larger_usage(self):
        self.transcript("s1", assistant("A", DAY, input=3, output=1),
                        assistant("A", DAY, input=3, output=50),
                        assistant("A", DAY, input=2, output=7))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        (tokens,) = self.totals(reader).values()
        self.assertEqual((tokens.input, tokens.output), (3, 50))
        self.assertAlmostEqual(tokens.dollars, spend.priced(
            "claude-sonnet-4-6", {"input_tokens": 3, "output_tokens": 50}).dollars)

    def test_a_later_poll_raises_a_message_already_counted(self):
        path = self.transcript("s1", assistant("A", DAY, output=1))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        with open(path, "ab") as handle:
            handle.write(assistant("A", DAY, output=50))
        reader.read([self.projects], SINCE)
        (tokens,) = self.totals(reader).values()
        self.assertEqual(tokens.output, 50)

    def test_changing_the_directory_alias_does_not_reread(self):
        real = self.tmp / "real" / "projects"
        (real / "-srv-p00").mkdir(parents=True)
        path = real / "-srv-p00" / "s1.jsonl"
        path.write_bytes(assistant("A", DAY, input=4))
        links = []
        for name in ("a", "b"):
            (self.tmp / name).mkdir()
            (self.tmp / name / "projects").symlink_to(real)
            links.append(self.tmp / name / "projects")
        reader = self.reader()
        reader.read(links, SINCE)
        before = self.opener.bytes
        line = assistant("B", DAY, input=2)
        with open(path, "ab") as handle:
            handle.write(line)
        reader.read([links[1]], SINCE)
        self.assertEqual(self.opener.bytes - before, len(line))
        reader.read(links[::-1], SINCE)
        self.assertEqual(self.opener.bytes - before, len(line))
        self.assertEqual(sum(t.input for t in self.totals(reader).values()), 6)

    def test_agent_transcript_keyed_by_run_and_agent(self):
        run = self.run_dir()
        (run / "journal.jsonl").write_text(
            '{"type":"started","agentId":"a1","label":"impl-1","phase":"Tasks"}\n'
            '{"type":"started","agentId":"a2","label":"plan","phase":"▸ deliver-standard #5"}\n')
        (run / "agent-a1.jsonl").write_bytes(assistant("M1", DAY, input=7))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        snapshot = reader.snapshot()
        self.assertEqual(snapshot.totals,
                         {Key(DAY, "s1", ("s1", "wf_1"), "a1", AGENT): priced_input(7)})
        self.assertEqual(snapshot.journals, {("s1", "wf_1"): {"a1": "impl-1", "a2": "plan"}})
        self.assertEqual(snapshot.programs, {("s1", "wf_1"): STANDARD})

    def test_shared_projects_tree_read_once(self):
        real = self.tmp / "real" / "projects"
        (real / "-srv-p00").mkdir(parents=True)
        (real / "-srv-p00" / "s1.jsonl").write_bytes(assistant("A", DAY, input=4))
        (real / "-srv-p00" / "s2.jsonl").write_bytes(assistant("B", DAY, sid="s2", input=6))
        links = []
        for name in ("p1", "p2"):
            (self.tmp / name).mkdir()
            (self.tmp / name / "projects").symlink_to(real)
            links.append(self.tmp / name / "projects")
        alone = spend.SpendReader()
        alone.read([real], SINCE)
        reader = self.reader()
        reader.read(links, SINCE)
        self.assertEqual(self.totals(reader), self.totals(alone))
        self.assertEqual(self.opener.calls, 2)

    def test_second_read_costs_only_the_appended_line(self):
        path = self.transcript("s1", assistant("A", DAY, input=1), assistant("B", DAY, input=2))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        before = self.opener.bytes
        line = assistant("C", DAY, input=4)
        with open(path, "ab") as handle:
            handle.write(line)
        reader.read([self.projects], SINCE)
        self.assertEqual(self.opener.bytes - before, len(line))
        self.assertEqual(self.totals(reader)[Key(DAY, "s1", None, None, SESSION)].input, 7)
        bytes_now, calls_now = self.opener.bytes, self.opener.calls
        reader.read([self.projects], SINCE)
        self.assertEqual((self.opener.bytes, self.opener.calls), (bytes_now, calls_now))

    def test_before_window_is_skipped_and_pruned(self):
        path = self.transcript("s1", assistant("A", "2026-10-17", input=1),
                               assistant("B", DAY, input=2))
        reader = self.reader()
        reader.read([self.projects], "2026-10-18")
        self.assertEqual(set(self.totals(reader)), {Key(DAY, "s1", None, None, SESSION)})
        with open(path, "ab") as handle:
            handle.write(assistant("C", "2026-10-20", input=3))
        reader.read([self.projects], "2026-10-18")
        self.assertIn(Key("2026-10-20", "s1", None, None, SESSION), self.totals(reader))
        reader.read([self.projects], "2026-10-21")
        self.assertEqual(set(self.totals(reader)), {Key(DAY, "s1", None, None, SESSION)})

    def test_file_older_than_window_is_not_opened(self):
        path = self.transcript("s1", assistant("A", DAY, input=1))
        old = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).timestamp()
        os.utime(path, (old, old))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        self.assertEqual(self.opener.calls, 0)
        self.assertEqual(self.totals(reader), {})

    def test_names_and_repos(self):
        path = self.transcript(
            "s1", b'{"type":"agent-name","agentName":"p00 sprint 0123456789abcdef",'
                  b'"sessionId":"s1"}\n', assistant("A", DAY, input=1))
        asked = []

        def repo_of(cwd):
            asked.append(cwd)
            return "/srv/p00"

        reader = self.reader(repo_of=repo_of)
        reader.read([self.projects], SINCE)
        with open(path, "ab") as handle:
            handle.write(assistant("B", DAY, input=1))
        reader.read([self.projects], SINCE)
        snapshot = reader.snapshot()
        self.assertEqual(snapshot.names, {"s1": "p00 sprint 0123456789abcdef"})
        self.assertEqual(snapshot.repos, {"s1": "/srv/p00"})
        self.assertEqual(asked, ["/srv/p00"])

    def test_ping_log_counted_once_per_ts_and_conversation(self):
        ping = ('{"event":"ping","ts":"2026-11-16T09:00:00Z","conversation":"c1",'
                '"model":"claude-sonnet-4-6","usage":{"input_tokens":3}}\n')
        log = self.tmp / "proxy.log"
        log.write_text(ping + ping + '{"event":"request","ts":"2026-11-16T09:01:00Z",'
                       '"conversation":"c1","usage":{"input_tokens":9}}\n')
        reader = self.reader()
        reader.read([self.projects], SINCE, log)
        self.assertEqual(self.totals(reader)[Key(DAY, None, None, None, PING)].input, 3)

    def test_line_without_session_id_keys_none(self):
        line = json.loads(assistant("A", DAY, input=2))
        del line["sessionId"]
        self.transcript("s1", (json.dumps(line) + "\n").encode())
        reader = self.reader()
        reader.read([self.projects], SINCE)
        self.assertEqual(set(self.totals(reader)), {Key(DAY, None, None, None, SESSION)})

    def test_missing_and_unreadable_contribute_nothing(self):
        reader = self.reader()
        reader.read([self.tmp / "absent"], SINCE)
        self.assertEqual(self.totals(reader), {})
        self.transcript("s1", assistant("A", DAY, input=1))
        self.opener.fail = [True]
        reader.read([self.projects], SINCE)
        self.assertEqual(self.totals(reader), {})
        self.opener.fail = None
        reader.read([self.projects], SINCE)
        self.assertEqual(self.totals(reader)[Key(DAY, "s1", None, None, SESSION)].input, 1)

    def test_a_read_whose_every_root_fails_to_list_says_so_and_a_missing_root_does_not(self):
        self.transcript("s1", assistant("A", DAY, input=1))
        failing = [True]

        def scandir(directory):
            if failing[0] and os.path.realpath(directory) == os.path.realpath(self.projects):
                raise PermissionError(13, "denied")
            return os.scandir(directory)

        reader = self.reader(scandir=scandir)
        self.assertIs(reader.roots_unreadable, False)
        reader.read([self.projects], SINCE)
        self.assertEqual((reader.roots_unreadable, self.totals(reader)), (True, {}))
        reader.read([self.projects, self.projects.parent / "other"], SINCE)
        self.assertIs(reader.roots_unreadable, False)
        failing[0] = False
        reader.read([self.projects], SINCE)
        self.assertEqual(reader.roots_unreadable, False)
        reader.read([self.projects.parent / "absent"], SINCE)
        self.assertIs(reader.roots_unreadable, False)

    def test_failed_listing_keeps_cursors(self):
        path = self.transcript("s1", assistant("A", DAY, input=1), assistant("B", DAY, input=2))
        failing = [False]

        def scandir(directory):
            if failing[0] and Path(directory) == self.slug:
                raise PermissionError(13, "denied")
            return os.scandir(directory)

        reader = self.reader(scandir=scandir)
        reader.read([self.projects], SINCE)
        calls, totals = self.opener.calls, self.totals(reader)
        failing[0] = True
        reader.read([self.projects], SINCE)
        self.assertEqual((self.opener.calls, self.totals(reader)), (calls, totals))
        failing[0] = False
        before = self.opener.bytes
        line = assistant("C", DAY, input=4)
        with open(path, "ab") as handle:
            handle.write(line)
        reader.read([self.projects], SINCE)
        self.assertEqual(self.opener.bytes - before, len(line))
        self.assertEqual(self.totals(reader)[Key(DAY, "s1", None, None, SESSION)].input, 7)

    def test_session_subagent_transcript_counts_for_the_session(self):
        self.transcript("s1", assistant("A", DAY, input=1))
        sub = self.slug / "s1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-x1.jsonl").write_bytes(assistant("B", DAY, input=9))
        reader = self.reader()
        reader.read([self.projects], SINCE)
        self.assertEqual(self.totals(reader),
                         {Key(DAY, "s1", None, None, SESSION): priced_input(1) + priced_input(9)})
        self.assertEqual(self.totals(reader)[Key(DAY, "s1", None, None, SESSION)].input, 10)


TODAY = "2026-11-16"
SPRINT_NAME = (b'{"type":"agent-name","agentName":"p00 sprint 0123456789abcdef",'
               b'"sessionId":"s1"}\n')
PING_LINE = ('{"event":"ping","ts":"2026-11-16T09:00:00Z","conversation":"c1",'
             '"model":"claude-sonnet-4-6","usage":{"input_tokens":3}}\n')


class ViewCase(unittest.TestCase):
    """A projects tree read into a snapshot, and the view over it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.projects = self.tmp / "projects"
        self.slug = self.projects / "-srv-p00"
        self.slug.mkdir(parents=True)
        self.run = self.slug / "s1" / "subagents" / "workflows" / "wf_1"
        self.run.mkdir(parents=True)
        self.log = self.tmp / "proxy.log"

    def write(self, path, *lines):
        path.write_bytes(b"".join(lines))

    def basic(self):
        m1 = assistant("M1", TODAY, input=10)
        self.write(self.slug / "s1.jsonl", m1, m1, assistant("M2", TODAY, input=20))
        self.write(self.run / "journal.jsonl",
                   b'{"type":"started","agentId":"a1","label":"plan","phase":"Plan"}\n'
                   b'{"type":"started","agentId":"a2","label":"impl-1","phase":"Tasks"}\n')
        m3 = assistant("M3", TODAY, input=100, output=1)
        self.write(self.run / "agent-a1.jsonl", m3, m3, assistant("M4", TODAY, input=200))
        self.write(self.run / "agent-a2.jsonl", assistant("M5", TODAY, input=1000))

    def view(self, project_of=None, profiles=None, questions=None):
        reader = spend.SpendReader(repo_of=lambda cwd: cwd)
        reader.read([self.projects], SINCE, self.log if self.log.exists() else None)
        extra = {} if questions is None else {"questions": questions}
        return spend.spend_view(
            reader.snapshot(), today=TODAY,
            project_of={"/srv/p00": "p00"}.get if project_of is None else project_of,
            profiles={"s1": "p1"} if profiles is None else profiles, **extra)

    def today(self, **kwargs):
        return self.view(**kwargs)["days"][-1]


def question_transcript():
    """The bytes of a question session's transcript: its prompt, a streamed repeat, one more message."""
    prompt = {"type": "user", "sessionId": "q1", "cwd": "/srv/p00",
              "timestamp": "2026-11-16T09:59:00.000Z",
              "message": {"role": "user",
                          "content": "You answer one question about this project for its owner, "
                                     "started by the console. The question: why?"}}
    q1 = assistant("Q1", TODAY, sid="q1", input=40)
    return (json.dumps(prompt) + "\n").encode(), q1, q1, assistant("Q2", TODAY, sid="q1", output=5)


class SpendViewTest(ViewCase):
    def test_a_question_sessions_spend_is_its_projects_and_the_questions_aspect(self):
        self.basic()
        self.write(self.slug / "q1.jsonl", *question_transcript())
        d = self.today(questions={"q1": "work"})
        self.assertEqual({k: t["input"] for k, t in d["aspect"].items()},
                         {"outside_sprint": 30, "deliveries": 1300, "questions": 40})
        self.assertEqual(d["aspect"]["questions"]["output"], 5)
        self.assertEqual(d["project"]["p00"]["input"], 1370)
        self.assertEqual(d["session"]["q1"]["input"], 40)
        self.assertEqual({k: t["input"] for k, t in d["account"].items()},
                         {"p1": 1330, "work": 40})
        self.assertNotIn("q1", d["sprint"])
        self.assertEqual(d["total"]["input"], 1370)
        for dimension in ("aspect", "project", "session", "account"):
            self.assertEqual(sum(t["input"] for t in d[dimension].values()), 1370, dimension)

    def test_without_its_question_row_a_question_session_is_outside_sprint(self):
        self.basic()
        self.write(self.slug / "q1.jsonl", *question_transcript())
        d = self.today()
        self.assertEqual({k: t["input"] for k, t in d["aspect"].items()},
                         {"outside_sprint": 70, "deliveries": 1300})
        self.assertEqual(d["account"]["unattributed"]["input"], 40)

    def test_a_question_session_named_like_a_sprint_is_still_a_question(self):
        self.write(self.slug / "q1.jsonl",
                   b'{"type":"agent-name","agentName":"p00 sprint 0123456789abcdef",'
                   b'"sessionId":"q1"}\n',
                   assistant("Q1", TODAY, sid="q1", input=40))
        d = self.today(questions={"q1": "work"})
        self.assertEqual({k: t["input"] for k, t in d["aspect"].items()}, {"questions": 40})
        self.assertEqual(d["sprint"]["0123456789abcdef"]["input"], 40)

    def test_a_seen_profile_wins_over_the_question_rows_profile(self):
        self.write(self.slug / "q1.jsonl", assistant("Q1", TODAY, sid="q1", input=40))
        d = self.today(profiles={"q1": "p9"}, questions={"q1": "work"})
        self.assertEqual(set(d["account"]), {"p9"})

    def test_session_run_and_phase_equal_unique_message_sums(self):
        self.basic()
        d = self.today()
        self.assertEqual(d["session"]["s1"]["input"], 1330)
        self.assertEqual(d["run"]["wf_1"]["input"], 1300)
        self.assertEqual(d["total"]["input"], 1330)
        plan = priced_input(100) + priced_input(200)
        plan = plan + spend.priced("claude-sonnet-4-6", {"output_tokens": 1})
        self.assertEqual(set(d["phase"]), {"plan", "implement"})
        self.assertEqual((d["phase"]["plan"]["input"], d["phase"]["plan"]["output"]), (300, 1))
        self.assertEqual(d["phase"]["plan"]["dollars"], plan.wire()["dollars"])
        self.assertEqual(d["phase"]["implement"], priced_input(1000).wire())

    def test_dimension_sums_equal_total(self):
        self.basic()
        d = self.today()
        for dimension in ("session", "project", "account", "aspect"):
            with self.subTest(dimension=dimension):
                self.assertEqual(sum(t["input"] for t in d[dimension].values()),
                                 d["total"]["input"])
        self.assertEqual({k: t["input"] for k, t in d["aspect"].items()},
                         {"outside_sprint": 30, "deliveries": 1300})

    def test_project_and_account(self):
        self.basic()
        d = self.today()
        self.assertEqual(set(d["project"]), {"p00"})
        self.assertEqual(set(d["account"]), {"p1"})
        self.assertEqual(d["project"]["p00"]["input"], 1330)
        d = self.today(project_of=lambda repo: None, profiles={})
        self.assertEqual(set(d["project"]), {"unattributed"})
        self.assertEqual(set(d["account"]), {"unattributed"})
        self.assertEqual(d["project"]["unattributed"]["input"], 1330)

    def test_sprint_and_aspect(self):
        self.basic()
        m1 = assistant("M1", TODAY, input=10)
        self.write(self.slug / "s1.jsonl", SPRINT_NAME, m1, assistant("M2", TODAY, input=20))
        self.write(self.slug / "s2.jsonl", assistant("M6", TODAY, sid="s2", input=4))
        self.log.write_text(PING_LINE)
        d = self.today()
        self.assertEqual({k: t["input"] for k, t in d["sprint"].items()},
                         {"0123456789abcdef": 1330, "unattributed": 3})
        self.assertEqual(d["aspect"]["managers"]["input"], 30)
        self.assertEqual(d["aspect"]["outside_sprint"]["input"], 4)
        self.assertEqual(d["aspect"]["deliveries"]["input"], 1300)
        self.assertEqual(d["aspect"]["keepalive"]["input"], 3)
        for dimension in ("session", "project"):
            self.assertEqual(d[dimension]["unattributed"]["input"], 3)
        self.assertEqual(d["account"]["unattributed"]["input"], 7)  # the ping and s2, no profile

    def test_sprint_and_run_phase_break_each_item_down_by_phase(self):
        self.basic()
        self.write(self.slug / "s1.jsonl", SPRINT_NAME,
                   assistant("M1", TODAY, input=10, write=7, read=40),
                   assistant("M2", TODAY, input=20, read=5, output=3))
        self.write(self.run / "agent-a2.jsonl",
                   assistant("M5", TODAY, input=1000, write=11, read=900, output=4))
        d = self.today()
        sid = "0123456789abcdef"

        def counts(t):
            return (t["input"], t["cache_write"], t["cache_read"], t["output"])

        sprint = d["sprint_phase"][sid]
        run = d["run_phase"]["wf_1"]
        self.assertEqual({p: counts(t) for p, t in sprint.items()},
                         {"manager": (30, 7, 45, 3), "plan": (300, 0, 0, 1),
                          "implement": (1000, 11, 900, 4)})
        self.assertEqual({p: counts(t) for p, t in run.items()},
                         {"plan": (300, 0, 0, 1), "implement": (1000, 11, 900, 4)})
        self.assertEqual(counts(d["sprint"][sid]), (1330, 18, 945, 8))
        self.assertEqual(counts(d["run"]["wf_1"]), (1300, 11, 900, 5))
        for phases, whole in ((sprint, d["sprint"][sid]), (run, d["run"]["wf_1"])):
            self.assertEqual(tuple(sum(c) for c in zip(*(counts(t) for t in phases.values()))),
                             counts(whole))
            self.assertAlmostEqual(sum(t["dollars"] for t in phases.values()),
                                   whole["dollars"], places=4)
            for phase in ("plan", "implement"):
                self.assertEqual(phases[phase]["dollars"], d["phase"][phase]["dollars"])
        self.assertGreater(sprint["manager"]["dollars"], 0)

    def project_items_view(self, totals, *, journals=None, names=None, repos=None):
        snap = spend.Snapshot(totals, journals or {}, {}, names or {}, repos or {})
        view = spend.spend_view(snap, today=TODAY, project_of={"/srv/p00": "p00",
                                                               "/srv/p01": "p01"}.get,
                                profiles={})
        return view["days"][-1]

    def test_project_items_keep_two_projects_runs_with_one_run_id_apart(self):
        journals = {("s1", "wf_1"): {"a1": "impl-1"}, ("s2", "wf_1"): {"a1": "impl-1"}}
        d = self.project_items_view(
            {Key(TODAY, "s1", ("s1", "wf_1"), "a1", AGENT): Tokens(input=100),
             Key(TODAY, "s2", ("s2", "wf_1"), "a1", AGENT): Tokens(input=7)},
            journals=journals, repos={"s1": "/srv/p00", "s2": "/srv/p01"})
        self.assertEqual(d["project_items"]["p00"]["run"]["wf_1"],
                         {"implement": Tokens(input=100).wire()})
        self.assertEqual(d["project_items"]["p01"]["run"]["wf_1"],
                         {"implement": Tokens(input=7).wire()})
        self.assertEqual(d["run_phase"]["wf_1"], {"implement": Tokens(input=107).wire()})

    def test_project_items_hold_a_managers_sprint_under_its_project(self):
        sid = "0123456789abcdef"
        d = self.project_items_view(
            {Key(TODAY, "s1", None, None, SESSION): Tokens(input=30, output=2)},
            names={"s1": f"p00 sprint {sid}"}, repos={"s1": "/srv/p00"})
        self.assertEqual(d["project_items"]["p00"]["sprint"][sid],
                         {spend.MANAGER_PHASE: Tokens(input=30, output=2).wire()})
        self.assertNotIn("p01", d["project_items"])

    def test_an_unattributed_project_or_an_empty_day_has_no_project_items(self):
        sid = "0123456789abcdef"
        d = self.project_items_view(
            {Key(TODAY, "s1", None, None, SESSION): Tokens(input=30)},
            names={"s1": f"p00 sprint {sid}"})
        self.assertEqual(d["project_items"], {})
        self.assertEqual(d["sprint_phase"][sid], {spend.MANAGER_PHASE: Tokens(input=30).wire()})
        self.basic()
        self.assertEqual(self.view()["days"][0]["project_items"], {})

    def test_unattributed_items_have_no_phase_breakdown(self):
        run = self.slug / "s1" / "subagents" / "workflows" / "wf_2"
        run.mkdir(parents=True)
        self.write(run / "agent-a9.jsonl", assistant("A", TODAY, input=6))
        self.log.write_text(PING_LINE)
        d = self.today()
        self.assertEqual(d["run_phase"], {})
        self.assertNotIn("unattributed", d["sprint_phase"])
        self.assertEqual(set(d["run"]), {"unattributed"})

    def test_an_empty_day_has_empty_item_breakdowns(self):
        self.basic()
        empty = self.view()["days"][0]
        self.assertEqual(empty["sprint_phase"], {})
        self.assertEqual(empty["run_phase"], {})

    def test_thirty_days_oldest_first(self):
        self.basic()
        self.write(self.slug / "s3.jsonl", assistant("M7", "2026-10-17", sid="s3", input=7))
        v = self.view()
        self.assertEqual(len(v["days"]), 30)
        self.assertEqual(v["days"][0]["day"], "2026-10-18")
        self.assertEqual(v["days"][-1]["day"], TODAY)
        empty = v["days"][0]
        self.assertEqual(empty["total"], Tokens().wire())
        for dimension in spend.DIMENSIONS:
            self.assertEqual(empty[dimension], {})
        snap = spend.Snapshot({Key("2026-10-17", "s1", None, None, SESSION): priced_input(5)},
                              {}, {}, {}, {})
        outside = spend.spend_view(snap, today=TODAY, project_of=lambda repo: None, profiles={})
        self.assertTrue(all(day["total"] == Tokens().wire() for day in outside["days"]))

    def test_approximate_marks_the_day_and_the_view(self):
        self.write(self.slug / "s1.jsonl",
                   assistant("A", TODAY, model="claude-opus-9-9", input=5),
                   assistant("B", "2026-11-15", input=5))
        v = self.view()
        self.assertIs(v["days"][-1]["total"]["approximate"], True)
        self.assertIs(v["days"][-2]["total"]["approximate"], False)
        self.assertIs(v["approximate"], True)
        self.write(self.slug / "s1.jsonl", assistant("A", TODAY, input=5))
        v = self.view()
        self.assertIs(v["days"][-1]["total"]["approximate"], False)
        self.assertIs(v["approximate"], False)


class UnattributedTest(ViewCase):
    def test_line_without_session_id(self):
        line = json.loads(assistant("A", TODAY, input=2))
        del line["sessionId"]
        self.write(self.slug / "s1.jsonl", (json.dumps(line) + "\n").encode())
        d = self.today()
        for dimension in ("session", "project", "account", "aspect", "sprint"):
            with self.subTest(dimension=dimension):
                self.assertEqual({k: t["input"] for k, t in d[dimension].items()},
                                 {"unattributed": 2})

    def test_run_without_journal(self):
        run = self.slug / "s1" / "subagents" / "workflows" / "wf_2"
        run.mkdir(parents=True)
        self.write(run / "agent-a9.jsonl", assistant("A", TODAY, input=6))
        d = self.today()
        self.assertEqual({k: t["input"] for k, t in d["run"].items()}, {"unattributed": 6})
        self.assertEqual({k: t["input"] for k, t in d["phase"].items()}, {"unattributed": 6})
        self.assertEqual(set(d["aspect"]), {"deliveries"})

    def test_agent_the_journal_never_started(self):
        self.write(self.run / "journal.jsonl",
                   b'{"type":"started","agentId":"a1","label":"plan","phase":"Plan"}\n')
        self.write(self.run / "agent-a7.jsonl", assistant("A", TODAY, input=8))
        d = self.today()
        self.assertEqual(d["run"]["wf_1"]["input"], 8)
        self.assertEqual({k: t["input"] for k, t in d["phase"].items()}, {"unattributed": 8})

    def test_unknown_label_is_other_not_unattributed(self):
        self.write(self.run / "journal.jsonl",
                   b'{"type":"started","agentId":"a1","label":"recover-end-3","phase":"Plan"}\n')
        self.write(self.run / "agent-a1.jsonl", assistant("A", TODAY, input=8))
        self.assertEqual(set(self.today()["phase"]), {"other"})


class SessionProfilesTest(unittest.TestCase):
    @staticmethod
    def event(seq, kind, **payload):
        return Event(seq, "2026-11-16T10:00:00+00:00", kind, None, payload)

    def test_gone_keeps_the_profile(self):
        events = [self.event(1, sessions.SEEN, session_id="s1", profile="p1"),
                  self.event(2, sessions.GONE, session_id="s1")]
        self.assertEqual(spend.session_profiles(events), {"s1": "p1"})

    def test_latest_profile_wins_and_folds_incrementally(self):
        known = {"s1": "p1"}
        self.assertEqual(
            spend.session_profiles([self.event(1, sessions.PROFILE, session_id="s1", profile="p2")],
                                   known),
            {"s1": "p2"})
        self.assertEqual(known, {"s1": "p1"})
        ignored = [self.event(2, sessions.SEEN, session_id="s1"),
                   self.event(3, sessions.SEEN, session_id=7, profile="p3"),
                   self.event(4, sessions.HOOK, session_id="s1", profile="p4")]
        self.assertEqual(spend.session_profiles(ignored, known), {"s1": "p1"})


class QuestionSessionsTest(unittest.TestCase):
    @staticmethod
    def event(seq, kind, **payload):
        return Event(seq, "2026-11-16T10:00:00+00:00", kind, "owner/p00", payload)

    def test_an_asked_row_maps_its_session_to_its_profile(self):
        events = [self.event(1, "project_question.asked", question_id="a" * 16, question="why?",
                             profile="work", session_id="q1")]
        self.assertEqual(spend.question_sessions(events), {"q1": "work"})

    def test_other_rows_are_ignored_and_the_fold_is_incremental(self):
        known = {"q0": "p1"}
        asked = "project_question.asked"
        events = [self.event(1, asked, profile="work"),
                  self.event(2, asked, profile="work", session_id=""),
                  self.event(3, asked, profile="work", session_id=7),
                  self.event(4, asked, session_id="q3"),
                  self.event(5, sessions.SEEN, session_id="s1", profile="p2"),
                  self.event(6, asked, session_id="q2", profile="work")]
        got = spend.question_sessions(events, known)
        self.assertEqual(got, {"q0": "p1", "q2": "work"})
        self.assertEqual(known, {"q0": "p1"})


SHARE_LABELS = {"setup": "setup", "plan": "plan", "plan review": "plan-review",
                "plan revise": "plan-revise", "implement": "impl-1", "task review": "review-1",
                "final review": "final-1", "fix wave": "fix-wave", "verify": "verify",
                "land": "land-pr-5", "close-out": "close-out-5"}


class CheckSharesTest(unittest.TestCase):
    """`check-shares` over a tree whose batch run holds the reference shares, in thousandths."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.projects = self.tmp / "projects"
        slug = self.projects / "-srv-p00" / "s1" / "subagents" / "workflows"
        batch, standard = slug / "wf_b", slug / "wf_s"
        batch.mkdir(parents=True)
        standard.mkdir()
        started = []
        self.agents = {}
        for index, (phase, share) in enumerate(spend.REFERENCE_BATCH_SHARES.items()):
            agent, label = f"a{index}", SHARE_LABELS[phase]
            started.append({"type": "started", "agentId": agent, "label": label, "phase": "Setup"})
            self.agents[phase] = batch / f"agent-{agent}.jsonl"
            self.agents[phase].write_bytes(
                assistant(f"M{index}", "2026-11-12", input=round(share * 1000)))
        started.append({"type": "started", "agentId": "ax", "label": "setup", "phase": "Intake"})
        (batch / "journal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in started))
        (standard / "journal.jsonl").write_text(
            '{"type":"started","agentId":"b1","label":"impl-1","phase":"Plan"}\n'
            '{"type":"started","agentId":"b2","label":"impl-1","phase":"Tasks"}\n')
        (standard / "agent-b1.jsonl").write_bytes(
            assistant("S1", "2026-11-12", input=1_000_000))

    def move(self, source, target, tokens):
        for phase, delta in ((source, -tokens), (target, tokens)):
            path = self.agents[phase]
            line = json.loads(path.read_text())
            line["message"]["usage"]["input_tokens"] += delta
            path.write_text(json.dumps(line) + "\n")

    def check(self, *extra):
        argv = ["check-shares", "--projects", str(self.projects), "--from", "2026-11-09",
                "--to", "2026-11-16", *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = spend.main(argv)
        lines = out.getvalue().splitlines()
        return code, json.loads(lines[0]) if lines else None

    def test_reference_table(self):
        self.assertEqual(set(spend.REFERENCE_BATCH_SHARES), set(spend.PHASES))
        self.assertLessEqual(abs(sum(spend.REFERENCE_BATCH_SHARES.values()) - 100.0), 0.05)

    def test_shares_within_tolerance_exit_0(self):
        code, line = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(line["off"], [])
        self.assertEqual(line["tokens"], 100_000)
        self.assertAlmostEqual(line["shares"]["implement"], 28.0)
        self.assertEqual(line["program"], "deliver-batch")
        self.assertEqual(line["reference"], spend.REFERENCE_BATCH_SHARES)
        self.assertEqual(line["tolerance"], 3.0)

    def test_a_phase_off_by_more_than_the_tolerance_exits_1(self):
        self.move("implement", "plan", 4_000)
        code, line = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(line["off"], ["plan", "implement"])

    def test_within_tolerance_boundary(self):
        self.move("implement", "plan", 2_900)
        code, line = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(line["off"], [])

    def test_no_batch_tokens_exit_75(self):
        argv = ["check-shares", "--projects", str(self.projects), "--from", "2026-11-13",
                "--to", "2026-11-16"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(spend.main(argv), 75)

    def test_from_after_to_is_a_usage_error(self):
        argv = ["check-shares", "--projects", str(self.projects), "--from", "2026-11-16",
                "--to", "2026-11-09"]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(spend.main(argv), 2)

    def test_a_basic_or_week_date_is_read_as_the_day_it_names(self):
        for start, end in (("20261109", "20261116"), ("20261109", "2026-11-16"),
                           ("2026-W46-1", "2026-W47-1")):
            argv = ["check-shares", "--projects", str(self.projects), "--from", start,
                    "--to", end]
            out = io.StringIO()
            with self.subTest(start=start, end=end), contextlib.redirect_stdout(out):
                self.assertEqual(spend.main(argv), 0)
            line = json.loads(out.getvalue().splitlines()[0])
            self.assertEqual((line["from"], line["to"], line["tokens"]),
                             ("2026-11-09", "2026-11-16", 100_000))

    def test_runs_as_a_module_from_the_root(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.console.spend", "check-shares",
             "--projects", str(empty)],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": "python"}, capture_output=True, text=True,
            timeout=60)
        self.assertEqual(done.returncode, 75)
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
