"""Contract tests for `plan-amend` (`agent_tools.delivery.plan_amend`, #811).

Pins the contained, all-or-nothing plan edit: one JSON line out, exit 0 applied,
1 refused (nothing written), 2 bad input; containment by lexical path and by
realpath before any read; the Amendments section line, its placement and its
skip rule; bytes outside an edit surviving untouched.

Run: PYTHONPATH=python python3 -m unittest -v tests/test_plan_amend.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import plan_amend

COMMAND = (sys.executable, "-m", "agent_tools.delivery.plan_amend")
LINE_2 = ('- Amendment answering the stop at task 2: in task-2.md, '
          'replaced "old rule" with "new rule".\n')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = self.root / "plan"
        self.dir.mkdir()
        (self.dir / "plan.md").write_bytes(b"# Plan\n\nD5 says old.\n")
        (self.dir / "task-2.md").write_bytes(b"Step 3: old rule here.\n")

    def request(self, edits, stop="the stop at task 2", plan_root=None):
        return {"plan_dir": str(self.dir),
                "plan_root": plan_root or str(self.dir / "plan.md"),
                "stop": stop, "edits": edits}

    def apply(self, request_or_text):
        text = (request_or_text if isinstance(request_or_text, str)
                else json.dumps(request_or_text))
        source = self.root / "in.json"
        source.write_text(text, encoding="utf-8")
        done = subprocess.run([*COMMAND, "apply", "--input", str(source)],
                              capture_output=True, text=True, check=False)
        return done.returncode, json.loads(done.stdout)

    def snapshot(self):
        files = {}
        for base, _, names in os.walk(self.root, followlinks=False):
            for name in names:
                path = Path(base) / name
                if path.is_symlink() or not path.is_file() or path == self.root / "in.json":
                    continue
                files[str(path.relative_to(self.root))] = path.read_bytes()
        return files

    def E(self, name, find, replace):
        return {"file": str(self.dir / name), "find": find, "replace": replace}


class PlanAmendTest(Fixture):
    def test_one_edit_is_written_and_recorded_under_a_new_amendments_section(self):
        code, out = self.apply(self.request([self.E("task-2.md", "old rule", "new rule")]))
        self.assertEqual(code, 0)
        self.assertEqual(out, {"status": "applied", "edits": [
            {"file": str(self.dir / "task-2.md"), "exists": True,
             "occurrences": 1, "already": False}], "refused": []})
        self.assertEqual((self.dir / "task-2.md").read_bytes(), b"Step 3: new rule here.\n")
        self.assertEqual((self.dir / "plan.md").read_bytes(),
                         b'# Plan\n\nD5 says old.\n\n## Amendments\n\n' + LINE_2.encode())

    def test_lines_join_an_existing_amendments_section_before_the_next_heading(self):
        first = ('- Amendment answering the stop at task 1: in task-1.md, '
                 'replaced "a" with "b".\n')
        (self.dir / "plan.md").write_text(
            f"# Plan\n\n## Amendments\n\n{first}\n## Decisions\n\nD1.\n", encoding="utf-8")
        code, _ = self.apply(self.request([self.E("task-2.md", "old rule", "new rule")]))
        self.assertEqual(code, 0)
        self.assertEqual((self.dir / "plan.md").read_text(encoding="utf-8"),
                         f"# Plan\n\n## Amendments\n\n{first}{LINE_2}\n## Decisions\n\nD1.\n")

    def test_edits_apply_in_order_and_may_edit_the_plan_itself(self):
        code, out = self.apply(self.request([
            self.E("plan.md", "says old.", "says new."),
            self.E("task-2.md", "old rule", "new rule"),
            self.E("task-2.md", "new rule", "newer rule")],
            stop="the stop before task 2"))
        self.assertEqual(code, 0)
        self.assertEqual([e["occurrences"] for e in out["edits"]], [1, 1, 1])
        self.assertEqual((self.dir / "task-2.md").read_bytes(), b"Step 3: newer rule here.\n")
        stop = "- Amendment answering the stop before task 2: "
        self.assertEqual(
            (self.dir / "plan.md").read_text(encoding="utf-8"),
            "# Plan\n\nD5 says new.\n\n## Amendments\n\n"
            + stop + 'in plan.md, replaced "says old." with "says new.".\n'
            + stop + 'in task-2.md, replaced "old rule" with "new rule".\n'
            + stop + 'in task-2.md, replaced "new rule" with "newer rule".\n')

    def test_bytes_outside_the_edit_survive(self):
        (self.dir / "plan.md").write_bytes("# Plän".encode())
        (self.dir / "task-2.md").write_bytes("Ünïcode old rule\r\n".encode())
        code, _ = self.apply(self.request([self.E("task-2.md", "old rule", "nëw rule")]))
        self.assertEqual(code, 0)
        self.assertEqual((self.dir / "task-2.md").read_bytes(),
                         "Ünïcode nëw rule\r\n".encode())
        self.assertEqual((self.dir / "plan.md").read_bytes(), (
            '# Plän\n\n## Amendments\n\n- Amendment answering the stop at task 2: '
            'in task-2.md, replaced "old rule" with "nëw rule".\n').encode())

    def test_a_find_missing_or_not_unique_or_an_absent_file_refuses_and_writes_nothing(self):
        task = str(self.dir / "task-2.md")
        plan = str(self.dir / "plan.md")
        cases = {
            "not found": (None, [self.E("task-2.md", "absent", "x")],
                          [{"file": task, "reason": "not found"}], 0),
            "twice": (b"old rule, old rule\n", [self.E("task-2.md", "old rule", "x")],
                      [{"file": task, "reason": "not unique"}], 2),
            "overlap": (b"aaa\n", [self.E("task-2.md", "aa", "x")],
                        [{"file": task, "reason": "not unique"}], 2),
            "missing": (None, [self.E("task-9.md", "x", "y")],
                        [{"file": str(self.dir / "task-9.md"), "reason": "missing"}], 0),
            "unreadable": (b"\xff\xfe", [self.E("task-2.md", "old rule", "x")],
                           [{"file": task, "reason": "unreadable"}], 0),
            "second only": (None, [self.E("task-2.md", "old rule", "new rule"),
                                   self.E("plan.md", "absent", "x")],
                            [{"file": plan, "reason": "not found"}], 0),
        }
        for name, (content, edits, refused, occurrences) in cases.items():
            with self.subTest(name):
                if content is not None:
                    (self.dir / "task-2.md").write_bytes(content)
                before = self.snapshot()
                code, out = self.apply(self.request(edits))
                self.assertEqual(code, 1)
                self.assertEqual(out["status"], "refused")
                self.assertEqual(out["refused"], refused)
                self.assertEqual(out["edits"][-1]["occurrences"], occurrences)
                self.assertEqual(out["edits"][-1]["exists"], name != "missing")
                self.assertEqual(self.snapshot(), before)
                (self.dir / "task-2.md").write_bytes(b"Step 3: old rule here.\n")

    def test_a_path_outside_plan_dir_refuses_before_reading(self):
        outside = self.root / "outside.md"
        outside.write_bytes(b"old rule\n")
        (self.root / "plan-x").mkdir()
        (self.root / "plan-x" / "task.md").write_bytes(b"old rule\n")
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere" / "task.md").write_bytes(b"old rule\n")
        (self.root / "outside-plan.md").write_bytes(b"# Other\n")
        os.symlink(outside, self.dir / "link.md")
        os.symlink(self.root / "elsewhere", self.dir / "sub")
        valid = self.E("task-2.md", "old rule", "new rule")
        cases = {
            "absolute": (str(outside), None),
            "dotdot": (str(self.dir) + "/../outside.md", None),
            "dotdot back inside": (str(self.dir) + "/nowhere/../task-2.md", None),
            "sibling prefix": (str(self.root / "plan-x" / "task.md"), None),
            "file symlink": (str(self.dir / "link.md"), None),
            "dir symlink": (str(self.dir / "sub" / "task.md"), None),
            "plan_root symlink": (str(self.dir / "plan.md"), "plan-root"),
        }
        for name, (path, special) in cases.items():
            with self.subTest(name):
                if special:
                    (self.dir / "plan.md").unlink()
                    os.symlink(self.root / "outside-plan.md", self.dir / "plan.md")
                    edits = [valid]
                else:
                    edits = [{"file": path, "find": "old rule", "replace": "new rule"}]
                before = self.snapshot()
                code, out = self.apply(self.request(edits))
                self.assertEqual(code, 1)
                self.assertEqual(out["status"], "refused")
                self.assertEqual(out["edits"], [])
                self.assertEqual(out["refused"],
                                 [{"file": path, "reason": "outside plan_dir"}])
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(outside.read_bytes(), b"old rule\n")
                self.assertEqual((self.root / "outside-plan.md").read_bytes(), b"# Other\n")
                self.assertEqual((self.root / "elsewhere" / "task.md").read_bytes(),
                                 b"old rule\n")

    def test_an_edit_already_recorded_is_skipped(self):
        for name, edit in {
            "plain": self.E("task-2.md", "old rule", "new rule"),
            "replace contains find": self.E("task-2.md", "old rule", "old rule, amended"),
        }.items():
            with self.subTest(name):
                request = self.request([edit])
                code, _ = self.apply(request)
                self.assertEqual(code, 0)
                after_first = self.snapshot()
                code, out = self.apply(request)
                self.assertEqual(code, 0)
                self.assertEqual(out["status"], "applied")
                self.assertIs(out["edits"][0]["already"], True)
                self.assertEqual(self.snapshot(), after_first)
                (self.dir / "task-2.md").write_bytes(b"Step 3: old rule here.\n")
                (self.dir / "plan.md").write_bytes(b"# Plan\n\nD5 says old.\n")

    def test_a_recorded_line_with_unicode_line_separators_is_still_skipped(self):
        # str.splitlines also breaks on U+2028, U+2029 and U+0085; the section is
        # line-structured by CR and LF only, so such a character never splits a line.
        for mark in ("\u2028", "\u2029", "\u0085"):
            for name, replace in {"in find and replace": f"a{mark}b, amended",
                                  "only in replace": f"c{mark}d"}.items():
                with self.subTest(mark=repr(mark), case=name):
                    (self.dir / "task-2.md").write_bytes(
                        f"Step: a{mark}b here.\n".encode("utf-8"))
                    (self.dir / "plan.md").write_bytes(b"# Plan\n")
                    request = self.request([self.E("task-2.md", f"a{mark}b", replace)])
                    code, _ = self.apply(request)
                    self.assertEqual(code, 0)
                    after_first = self.snapshot()
                    code, out = self.apply(request)
                    self.assertEqual(code, 0)
                    self.assertEqual(out["status"], "applied")
                    self.assertIs(out["edits"][0]["already"], True)
                    self.assertEqual(self.snapshot(), after_first)

    def test_bad_input_exits_2_and_writes_nothing(self):
        good = self.request([self.E("task-2.md", "old rule", "new rule")])

        def varied(**changes):
            return {**good, **changes}

        edit = self.E("task-2.md", "old rule", "new rule")
        cases = {
            "not json": "not json",
            "duplicate key": '{"plan_dir": "/a", "plan_dir": "/b", "plan_root": "/a/p", '
                             '"stop": "s", "edits": []}',
            "duplicate key in a valid request": json.dumps(good)[:-1] + ', "stop": "other"}',
            "no edits": varied(edits=[]),
            "no stop": {k: v for k, v in good.items() if k != "stop"},
            "stop newline": varied(stop="a\nb"),
            "empty find": varied(edits=[{**edit, "find": ""}]),
            "replace not a string": varied(edits=[{**edit, "replace": 1}]),
            "relative plan_dir": varied(plan_dir="plan"),
            "unknown member": varied(x=1),
            "extra edit member": varied(edits=[{**edit, "extra": 1}]),
        }
        for name, case in cases.items():
            with self.subTest(name):
                before = self.snapshot()
                code, out = self.apply(case)
                self.assertEqual(code, 2)
                self.assertEqual(out["status"], "error")
                self.assertTrue(isinstance(out["detail"], str) and out["detail"])
                self.assertEqual(self.snapshot(), before)


class WriteFailureTest(Fixture):
    """A write that fails midway leaves every file as it was, or names what it could not restore."""

    def amend_failing(self, fails):
        """Run the amend with `fails(destination_basename, nth_replace_of_it)` raising OSError when true."""
        real = os.replace
        seen = {}

        def replace(source, destination):
            name = os.path.basename(destination)
            seen[name] = seen.get(name, 0) + 1
            if fails(name, seen[name]):
                raise OSError("injected")
            return real(source, destination)
        request = self.request([self.E("task-2.md", "old rule", "new rule")])
        with mock.patch.object(plan_amend.os, "replace", side_effect=replace):
            return plan_amend.amend(request)

    def temporaries(self):
        return [f for f in os.listdir(self.dir) if f.startswith(".plan-amend-")]

    def test_a_failed_plan_replace_restores_the_task_file_and_leaves_no_temporary(self):
        before = self.snapshot()
        result = self.amend_failing(lambda name, nth: name == "plan.md")
        self.assertEqual(result["status"], "error")
        self.assertIn("injected", result["detail"])
        self.assertEqual(self.snapshot(), before)
        code, out = self.apply(self.request([self.E("task-2.md", "old rule", "new rule")]))
        self.assertEqual((code, out["status"]), (0, "applied"))

    def test_a_failed_restore_names_the_file_left_changed(self):
        result = self.amend_failing(lambda name, nth: name == "plan.md" or (name == "task-2.md" and nth > 1))
        self.assertEqual(result["status"], "error")
        self.assertIn(str(self.dir / "task-2.md"), result["detail"])
        self.assertEqual((self.dir / "plan.md").read_bytes(), b"# Plan\n\nD5 says old.\n")
        self.assertEqual(self.temporaries(), [])


if __name__ == "__main__":
    unittest.main()
