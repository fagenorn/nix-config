"""The aggregating transcript read (#1274): per-record attribution, the join, counts and sums only.

Run: just agent-workflow-tests
"""

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import project_question, spend
from agent_tools.console.transcript_digest import (
    PhaseFigures, RunDigest, TranscriptsUnreadable, project_runs)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
SINCE = "2026-11-01"
P01, P00 = "/srv/p01", "/srv/p00"
PROJECTS = {P01: "owner/p01", P00: "owner/p00"}
TOKEN = "ghp_" + "A1b2" * 9


def repo_of(cwd):
    if cwd.startswith(P01):
        return P01
    return P00 if cwd.startswith(P00) else None


def message(mid, stamp, cwd, *, input=0, output=0, tool=None, text=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool is not None:
        content.append({"type": "tool_use", "id": tool, "name": "Read", "input": {"p": text}})
    line = {"type": "assistant", "sessionId": "s1", "timestamp": stamp,
            "message": {"id": mid, "model": "claude-sonnet-4-6", "content": content,
                        "usage": {"input_tokens": input, "output_tokens": output}}}
    if cwd is not None:
        line["cwd"] = cwd
    return (json.dumps(line) + "\n").encode()


def started(agent, label, phase="Tasks"):
    line = {"type": "started", "agentId": agent, "label": label, "phase": phase}
    return (json.dumps(line) + "\n").encode()


class Tree(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(os.path.realpath(tmp.name))
        self.tree = self.tmp / "projects"

    def run_dir(self, run, sid="s1", slug="-srv-p01"):
        path = self.tree / slug / sid / "subagents" / "workflows" / run
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, run, agent, *lines, journal=None, **where):
        directory = self.run_dir(run, **where)
        if journal is not None:
            (directory / "journal.jsonl").write_bytes(b"".join(journal))
        path = directory / f"agent-{agent}.jsonl"
        path.write_bytes(b"".join(lines))
        return path

    def read(self, run_issues=None, project="owner/p01", since=SINCE, **extra):
        extra.setdefault("repo_of", repo_of)
        return project_runs([self.tree], project, PROJECTS.get, since, run_issues or {}, **extra)


def summed(digest, field):
    return sum(getattr(figures, field) for run in digest for figures in run.phases.values())


def summed_tokens(digest, field):
    return sum(getattr(figures.tokens, field) for run in digest for figures in run.phases.values())


class DigestTest(Tree):
    def test_only_the_projects_own_runs_are_read(self):
        self.write("wf_a", "a1",
                   message("m1", "2026-11-17T08:00:00Z", P01 + "/.worktrees/x", input=100,
                           tool="t1"),
                   message("m2", "2026-11-17T08:10:00Z", P01 + "/.worktrees/x", input=50),
                   journal=[started("a1", "impl-1")])
        self.write("wf_b", "b1", message("m3", "2026-11-17T08:00:00Z", P00, input=900))
        result = self.read({"wf_a": [7]})
        self.assertEqual(len(result), 1)
        run = result[0]
        self.assertIsInstance(run, RunDigest)
        self.assertEqual((run.issues, run.script), ((7,), spend.STANDARD))
        self.assertEqual((run.started_at, run.ended_at), ("2026-11-17T08:00:00+00:00",
                                                         "2026-11-17T08:10:00+00:00"))
        self.assertEqual(run.seconds, 600)
        self.assertIs(type(run.seconds), int)
        tokens = spend.priced("claude-sonnet-4-6", {"input_tokens": 150})
        self.assertEqual(dict(run.phases), {"implement": PhaseFigures(1, 2, 1, 600, tokens)})
        self.assertEqual(summed_tokens(result, "input"), 150)

    def test_each_record_counts_only_under_its_own_checkout(self):
        self.write("wf_a", "a1",
                   message("m1", "2026-11-17T08:00:00Z", P01 + "/.worktrees/x", input=100),
                   message("m2", "2026-11-17T08:01:00Z", None, input=50),
                   journal=[started("a1", "impl-1")])
        self.write("wf_a", "a2", message("m3", "2026-11-17T08:02:00Z", P00, input=900))
        result = self.read()
        self.assertEqual(summed(result, "agents"), 1)
        self.assertEqual(summed_tokens(result, "input"), 100)

    def test_a_message_repeated_in_two_files_counts_once_at_its_largest_usage(self):
        self.write("wf_a", "a1",
                   *(message("m1", "2026-11-17T08:00:00Z", P01, output=n) for n in (5, 9, 7)),
                   journal=[started("a1", "impl-1"), started("a2", "review-1")])
        self.write("wf_a", "a2", message("m1", "2026-11-17T08:00:01Z", P01, output=12))
        result = self.read()
        self.assertEqual(summed(result, "messages"), 1)
        self.assertEqual(result[0].phases["implement"].tokens.output, 12)

    def test_records_before_since_count_nothing(self):
        self.write("wf_a", "a1",
                   message("m1", "2026-10-01T08:00:00Z", P01, input=100),
                   message("m2", "2026-11-17T08:00:00Z", P01, input=7),
                   journal=[started("a1", "impl-1")])
        result = self.read(since="2026-11-10")
        self.assertEqual((summed(result, "messages"), summed_tokens(result, "input")), (1, 7))
        old = self.write("wf_b", "b1", message("m3", "2026-11-17T08:00:00Z", P01, input=5))
        os.utime(old, (1_700_000_000, 1_700_000_000))
        self.assertEqual(summed_tokens(self.read(since="2026-11-10"), "input"), 7)

    def test_a_bad_line_is_skipped(self):
        path = self.write("wf_a", "a1",
                          message("m1", "2026-11-17T08:00:00Z", P01, input=1),
                          journal=[started("a1", "impl-1")])
        path.write_bytes(path.read_bytes() + b"\xff\xfe{\n[1]\n"
                         + message("m2", "2026-11-17T08:01:00Z", P01, input=2))
        result = self.read()
        self.assertEqual((summed(result, "messages"), summed_tokens(result, "input")), (2, 3))

    def test_an_agent_without_a_journal_label_is_unattributed(self):
        self.write("wf_a", "a1", message("m1", "2026-11-17T08:00:00Z", P01, input=1))
        result = self.read()
        self.assertEqual(list(result[0].phases), [spend.UNATTRIBUTED])
        self.assertEqual(result[0].script, spend.OTHER)

    def test_a_worktree_cwd_maps_through_its_main_checkout(self):
        root = self.tmp / "checkout"
        (root / ".git").mkdir(parents=True)
        (root / "sub").mkdir()
        self.write("wf_a", "a1", message("m1", "2026-11-17T08:00:00Z", str(root / "sub"), input=1))
        result = project_runs([self.tree], "owner/p01", {str(root): "owner/p01"}.get, SINCE, {})
        self.assertEqual(len(result), 1)

    def test_an_absent_root_is_empty(self):
        self.assertEqual(project_runs([self.tmp / "none"], "owner/p01", PROJECTS.get, SINCE, {}),
                         ())

    def test_every_root_unreadable_raises(self):
        self.write("wf_a", "a1", message("m1", "2026-11-17T08:00:00Z", P01, input=1))
        other = self.tmp / "other"
        other.mkdir()

        def scandir(path):
            if os.fspath(path) in {os.path.realpath(other), os.path.realpath(self.tree)} \
                    and not self.readable:
                raise PermissionError("denied")
            return os.scandir(path)

        def read(*roots):
            return project_runs(roots, "owner/p01", PROJECTS.get, SINCE, {}, repo_of=repo_of,
                                scandir=scandir)

        self.readable = False
        with self.assertRaises(TranscriptsUnreadable):
            read(self.tree, other)

        def one_failing(path):
            if os.fspath(path) == os.path.realpath(other):
                raise PermissionError("denied")
            return os.scandir(path)

        result = project_runs([other, self.tree], "owner/p01", PROJECTS.get, SINCE, {},
                              repo_of=repo_of, scandir=one_failing)
        self.assertEqual(len(result), 1)


class DigestCredentialTest(Tree):
    def test_no_transcript_text_reaches_the_digest(self):
        sid, run = f"sid-{TOKEN}", f"wf_{TOKEN}"
        cwd = f"{P01}/{TOKEN}"
        line = json.loads(message("m1", "2026-11-17T08:00:00Z", cwd, input=3, tool="t1",
                                  text=TOKEN))
        line["sessionId"] = TOKEN
        self.write(run, "a1", (json.dumps(line) + "\n").encode(), sid=sid,
                   journal=[started("a1", f"impl-{TOKEN}")])
        result = self.read({run: [7]})
        self.assertEqual(result[0].issues, (7,))

        def strings(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield from strings(key)
                    yield from strings(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    yield from strings(item)
            elif isinstance(value, str):
                yield value

        for digest in result:
            for text in strings(dataclasses.asdict(digest)):
                self.assertNotIn(TOKEN, text)
            self.assertIn(digest.script, {spend.BATCH, spend.STANDARD, spend.OTHER})
            for phase in digest.phases:
                self.assertIn(phase, (*spend.PHASES, spend.OTHER, spend.UNATTRIBUTED))
        self.assertFalse(project_question.credential_shaped(repr(result)))


class ImportTest(unittest.TestCase):
    def python(self, code):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                              text=True)

    def test_the_digest_loads_without_the_view(self):
        done = self.python("import sys, agent_tools.console.transcript_digest;"
                           "print('agent_tools.console.view' in sys.modules)")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "False"), done.stderr)
        again = self.python("import agent_tools.console.transcript_digest\n"
                            "import agent_tools.console.question_records\n"
                            "import agent_tools.console.view")
        self.assertEqual(again.returncode, 0, again.stderr)


if __name__ == "__main__":
    unittest.main()
