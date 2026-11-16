"""The console's spend reader (#1134): pricing, phases, incremental transcript reading."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import spend
from agent_tools.console.spend import AGENT, BATCH, OTHER, PING, SESSION, STANDARD, Key, Tokens
from agent_tools.hosts import model_pricing
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

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


if __name__ == "__main__":
    unittest.main()
