"""Tests for reading an outline run's store (`agent_tools.delivery.outline_record`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import outline_record
from agent_tools.delivery.outline_record import RecordError

from .outline_runs import RunTree

TIER = "fast"

PLANNER = {"kind": "agent", "role": "planner", "reply": "outline.reply.json"}
STEPS = [
    {"id": "start", "kind": "call"},
    {"id": "plan-preflight", "kind": "command", "command": "issue-setup", "subcommand": "plan-preflight"},
    {"id": "outline", **PLANNER},
    {"id": "outline-fix", **PLANNER},
    {"id": "outline-revise", **PLANNER},
    {"id": "outline-note", "kind": "command", "command": "issue-setup", "subcommand": "outline-note"},
    {"id": "build", "kind": "call"},
]
SLICE_STEPS = [{"id": "build", "kind": "command", "command": "issue-setup", "subcommand": "outline-slice"}]


def reply(second: str) -> dict:
    return {"approach": "Do it.", "rejected": "Not that.",
            "slices": [{"n": 1, "change": "first", "files": ["a.py"], "test": "t1", "assertion": "a1"},
                       {"n": 2, "change": second, "files": ["b.py", "c.py"], "test": "t2", "assertion": "a2"}],
            "criteria": [{"id": "AC1", "kind": "code", "slice": 1, "text": "one"}],
            "risks": ["r1"], "questions": ["q1"]}


A = reply("second")
B = reply("second, revised")
INPUTS = {"holder": "host-a/x", "issue": 7}


class OutlineRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tree = RunTree(self, self.tmp / "runs")
        self.root = self.tree.run("outline", STEPS, issue=7, inputs=INPUTS)

    def test_approved_is_the_posted_note_result_not_a_later_outline_reply(self):
        self.tree.result(self.root, "outline", 1, A)
        self.tree.result(self.root, "outline-note", 1,
                         {"verdict": "posted", "comment_id": 9, "outline": A, "text": "T"})
        self.tree.result(self.root, "outline-revise", 1, B)

        self.assertEqual(outline_record.approved(self.root)["outline"], A)
        self.assertEqual(outline_record.outline(self.root),
                         {member: B[member] for member in outline_record.OUTLINE_MEMBERS})

    def test_outline_is_the_latest_reply_of_any_outline_step(self):
        self.tree.result(self.root, "outline", 1, A)
        self.tree.result(self.root, "outline-fix", 1, B)
        self.assertEqual(outline_record.outline(self.root)["slices"], B["slices"])

        empty = self.tree.run("outline", STEPS, issue=7, inputs=INPUTS)
        with self.assertRaises(RecordError) as caught:
            outline_record.outline(empty)
        self.assertEqual(caught.exception.code, "plan_missing")

    def test_snapshot_reads_the_latest_start_and_plan_preflight_results(self):
        self.tree.result(self.root, "start", 1, {
            "items": [], "details": "SETUP FACT", "merged_refs": [{"closes": False, "number": 5}],
            "branch": "x", "worktree_path": "/x"})
        self.tree.result(self.root, "plan-preflight", 1, {
            "branch": "issue-7-a", "worktree_path": "/w/a", "integration_branch": "main",
            "issue_text": "# t", "routed": True, "route_detail": "d"})
        self.tree.result(self.root, "plan-preflight", 2, {
            "branch": "issue-7-earlier-title", "worktree_path": "/w/earlier", "integration_branch": "main",
            "issue_text": "# t", "routed": True, "route_detail": "d"})

        snapshot = outline_record.snapshot(self.root)

        self.assertEqual(snapshot["branch"], "issue-7-earlier-title")
        self.assertEqual(snapshot["worktree_path"], "/w/earlier")
        self.assertEqual(snapshot["details"], "SETUP FACT")
        self.assertEqual(snapshot["merged_refs"], [{"closes": False, "number": 5}])

    def test_approved_skips_a_note_that_did_not_post(self):
        posted = {"verdict": "posted", "comment_id": 9, "outline": A, "text": "T"}
        self.tree.result(self.root, "outline-note", 1, posted)
        self.tree.result(self.root, "outline-note", 2, {"verdict": "error"})
        self.assertEqual(outline_record.approved(self.root), posted)

        only_error = self.tree.run("outline", STEPS, issue=7, inputs=INPUTS)
        self.tree.result(only_error, "outline-note", 1, {"verdict": "error"})
        with self.assertRaises(RecordError) as caught:
            outline_record.approved(only_error)
        self.assertEqual(caught.exception.code, "plan_missing")

    def test_built_maps_each_slice_to_its_latest_done_child_with_a_build_result(self):
        x1, x2 = {"status": "done", "commit": "1"}, {"status": "done", "commit": "2"}
        b1 = self.tree.run("outline-build", STEPS, issue=7, inputs=INPUTS, parent=self.root.name)
        b2 = self.tree.run("outline-build", STEPS, issue=7, inputs=INPUTS, parent=self.root.name)
        self.tree.call(self.root, "build", 1, b1, 0, 2)
        self.tree.call(self.root, "build", 1, b2, 1, 2)

        def slice_run(parent, item, index, *, done, build=None):
            child = self.tree.run("outline-slice", SLICE_STEPS, issue=7, parent=parent.name,
                                  inputs={**INPUTS, "item": item})
            if build is not None:
                self.tree.result(child, "build", 1, build)
            if done:
                self.tree.done(child)
            self.tree.call(parent, "slices", 1, child, index, 3)

        slice_run(b1, 1, 0, done=True, build=x1)
        slice_run(b1, 2, 1, done=False)
        slice_run(b1, 3, 2, done=False, build={"status": "partial"})
        slice_run(b2, 1, 0, done=True)
        slice_run(b2, 2, 1, done=True, build=x2)
        stray = self.tree.run("outline-slice", SLICE_STEPS, issue=7, inputs={**INPUTS, "item": 3})
        self.tree.result(stray, "build", 1, {"status": "stray"})
        self.tree.done(stray)

        self.assertEqual(outline_record.built(self.root), {1: x1, 2: x2})

    def test_render_writes_the_outline_template_exactly(self):
        outline = {**A, "questions": [],
                   "criteria": [{"id": "AC1", "kind": "code", "slice": 1, "text": "one"},
                                {"id": "AC2", "kind": "human", "slice": 2, "text": "two"}]}
        expected = (
            "# Outline of issue #7\n\n"
            "## Approach\nDo it.\n\n"
            "## Rejected alternative\nNot that.\n\n"
            "## Slices\n"
            "### Slice 1: first\n- Files: a.py\n- Proving test: t1: a1\n"
            "### Slice 2: second\n- Files: b.py, c.py\n- Proving test: t2: a2\n\n"
            "## Acceptance criteria\n- AC1 (code, slice 1): one\n- AC2 (human, slice 2): two\n\n"
            "## Risks\n- r1\n\n"
            "## Owner questions\n- none\n")
        self.assertEqual(outline_record.render(7, outline), expected)

    def test_root_run_refuses_an_unknown_holder_or_issue(self):
        for holder, issue in (("h/nope", 7), ("nohost", 7), (f"h/{self.root.name}", 8)):
            with self.subTest(holder=holder, issue=issue):
                with self.assertRaises(RecordError) as caught:
                    outline_record.root_run(holder, issue)
                self.assertEqual(caught.exception.code, "run_unknown")
        self.assertEqual(outline_record.root_run(f"h/{self.root.name}", 7), self.root)


if __name__ == "__main__":
    unittest.main()
