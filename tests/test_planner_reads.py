"""Tests for the planner's read files of an outline run (`agent_tools.delivery.planner_reads`)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import engine_ledger, planner_reads

from .outline_runs import RunTree

TIER = "fast"

STEPS = [{"id": "outline", "kind": "agent", "role": "planner"},
         {"id": "design-review", "kind": "agent", "role": "reviewer-lite"},
         {"id": "outline-fix", "kind": "agent", "role": "planner"}]


def read_line(path: str) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "reading"},
        {"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": path}}]}})


class PlannerReadsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.projects = self.tmp / "projects"
        self.run = RunTree(self, self.tmp / "runs").run("outline", STEPS, issue=7, inputs={"issue": 7})
        for name, session in (("outline.1.json", "s1"), ("outline.1.resume.json", "s1"),
                              ("outline-fix.1.json", "s3"), ("design-review.1.json", "s2")):
            engine_ledger.store_session_file(self.run, name, json.dumps({"session": session}).encode("utf-8"))
        self.transcript("-x", "s1", [read_line("/r/a.py"), read_line("/r/b.py"), read_line("/r/a.py")])
        self.transcript("-y", "s3", [read_line("/r/c.py")])
        self.transcript("-x", "s2", [read_line("/r/z.py")])

    def transcript(self, directory: str, session: str, lines: list[str]) -> Path:
        path = self.projects / directory / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_the_read_files_of_every_planner_session_of_the_run_in_order(self):
        self.assertEqual(planner_reads.planner_reads(self.run, [self.projects]),
                         ["/r/a.py", "/r/b.py", "/r/c.py"])

    def test_a_transcript_line_that_is_not_a_read_call_is_skipped(self):
        path = self.transcript("-x", "s1", [
            "not json", "[1]", json.dumps({"type": "user", "message": {"content": "hi"}}),
            json.dumps({"message": {"content": [{"type": "tool_use", "name": "Grep",
                                                 "input": {"file_path": "/r/g.py"}}]}}),
            read_line("/r/a.py")])
        self.assertEqual(planner_reads.read_files(path), ["/r/a.py"])

    def test_a_read_path_holding_a_unicode_line_separator_stays_one_record(self):
        for separator in (" ", " ", "\x85"):
            with self.subTest(separator=repr(separator)):
                path = f"/r/a{separator}b.py"
                literal = json.dumps(json.loads(read_line(path)), ensure_ascii=False)
                transcript = self.transcript("-x", "s1", [literal, read_line("/r/after.py")])
                self.assertIn(separator, transcript.read_text(encoding="utf-8"))
                self.assertEqual(planner_reads.read_files(transcript), [path, "/r/after.py"])

    def test_a_session_with_no_transcript_adds_nothing(self):
        (self.projects / "-y" / "s3.jsonl").unlink()
        self.assertEqual(planner_reads.planner_reads(self.run, [self.projects]), ["/r/a.py", "/r/b.py"])

    def test_projects_roots_puts_the_config_dir_first_without_repeats(self):
        home = self.tmp / "home"
        self.assertEqual(planner_reads.projects_roots({"CLAUDE_CONFIG_DIR": str(home / ".claude")}, home),
                         (home / ".claude" / "projects",))
        other = self.tmp / "other"
        self.assertEqual(planner_reads.projects_roots({"CLAUDE_CONFIG_DIR": str(other)}, home),
                         (other / "projects", home / ".claude" / "projects"))
        self.assertEqual(planner_reads.projects_roots({}, home), (home / ".claude" / "projects",))


if __name__ == "__main__":
    unittest.main()
