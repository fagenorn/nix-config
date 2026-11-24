"""The look gate's own-files carry at the lifecycle guard's merge seam.

These cases borrow the look-gate world of `ClaudePermissionGuardTest` (its fixture, its
helpers and its constants) without inheriting its tests, because that file is past the
file-size bar and may not grow.
"""
import unittest

from agent_tools.delivery import look_marker

from . import test_claude_permission_guard as guard_tests

TIER = "nightly"  # the guard under test comes from a host build


class OwnFilesCarryGuardTest(unittest.TestCase):
    for _name, _member in vars(guard_tests.ClaudePermissionGuardTest).items():
        inherited = _name.startswith(("test_", "__")) or _name in vars(unittest.TestCase)
        if _name in {"setUpClass", "tearDownClass"} or not inherited:
            locals()[_name] = _member
    del _name, _member, inherited

    def own_files_line(self, cid, a, h, association="OWNER"):
        return {"id": cid,
                "body": look_marker.carry_body(
                    1200, 1300, a, h, None, rule=look_marker.OWN_FILES_RULE),
                "updated_at": "2026-11-16T10:00:00Z", "author_association": association}

    def test_an_own_files_carry_admits_an_approval_across_a_main_merge(self):
        a, h, x = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X
        compares = self.merges_world([(h, [a, x])])
        for name, comments in {
            "a pictured approval": [self.look_pics_comment(10, a), self.own_files_line(11, a, h)],
            "a pictureless approval": [self.look_comment(10, head=a), self.own_files_line(11, a, h)],
        }.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, self.look_repo(),
                    self.look_carry_env(comments, compares, look_files={}))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)

    def test_the_look_gate_refuses_each_shape_an_own_files_carry_does_not_cover(self):
        repo = self.look_repo()
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        pics, line = self.look_pics_comment(10, a), self.own_files_line(11, a, h)
        merged = self.merges_world([(h, [a, x])])
        own = self.merges_world([(h, [a, x])])
        own[f"{a}...{h}"] = self.look_compare([self.DOC, self.PAGE])
        edited = self.merges_world([(h, [a, x])])
        edited[f"{self.LOOK_BASE}...{h}"]["files"] = self.look_compare([self.PAGE, self.DOC])["files"]
        many = self.merges_world([(h, [a, x])])
        many[f"{a}...{h}"] = self.look_compare([f"docs/d{n}.md" for n in range(300)])
        diverged = self.merges_world([(h, [a, x])])
        diverged[f"{a}...{h}"]["status"] = "diverged"
        first, *sentences = look_marker.carry_body(1200, 1300, a, h, self.LOOK_DIGEST).split("\n")
        assert first.endswith(" -->")
        both = {**line, "body": "\n".join(
            [first[:-len(" -->")] + " rule=own-files -->"] + sentences)}
        cases = {
            "no line": ([pics], merged),
            "a merge that brought in an own file": ([pics, line], own),
            "a merge that itself edits a file neither side touched": ([pics, line], edited),
            "a one-parent commit": ([pics, line], self.merges_world([(h, [a])])),
            "a pull request commit as second parent": (
                [pics, line], self.merges_world([(t, [a]), (h, [t, a])])),
            "a line naming another head": ([pics, self.own_files_line(11, a, t)], merged),
            "a collaborator's line": (
                [pics, self.own_files_line(11, a, h, association="COLLABORATOR")], merged),
            "a line that was ended": ([pics, line, self.look_end_comment(12, of=11)], merged),
            "a line naming own-files and pictures": ([pics, both], merged),
            "a later changes answer": (
                [pics, line, self.look_comment(12, head=x, answer="changes")], merged),
            "a compare of 300 files": ([pics, line], many),
            "A...H diverged": ([pics, line], diverged),
        }
        for name, (comments, compares) in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo,
                    self.look_carry_env(comments, compares, look_files={}))
                self.assert_look_refusal(result)


if __name__ == "__main__":
    unittest.main()
