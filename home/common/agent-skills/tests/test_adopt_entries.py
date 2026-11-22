"""The guard and edge cases of adoption's hint move and entry-file conversion (#1468).

The issue-named cases sit in `test_adopt_apply.py`; the fixtures and the
test-free bases are imported from it, never a class with tests, so neither file
collects the other's tests.
"""

from __future__ import annotations

import json
import unittest

from agent_tools.project_contract import adopt_links

from .test_adopt_apply import CleanApplyTestCase, apply_repo, hinted_apply_repo
from .test_adopt_project import PLAN_MEMBERS, git


class HintMoveGuardTest(CleanApplyTestCase):
    def test_a_hints_binding_follows_the_move_as_a_directory_and_as_a_file(self):
        root = self.owned(hinted_apply_repo(self.home))
        document = self.ready_plan(root)
        result = self.succeed(root, document["plan"]["plan_id"])
        contract = json.loads(git(
            root, "show", f"{result['branch']}:.agents/project.json"))
        self.assertEqual(
            contract["bindings"]["paths"]["hints"],
            [".agents/knowledge/hints", ".agents/knowledge/hints/planning.md"])

    def test_a_plan_with_no_hints_has_no_open_items_member(self):
        root = self.owned(apply_repo(self.home))
        document = self.ready_plan(root)
        self.assertEqual(sorted(document["plan"]), PLAN_MEMBERS)


class PointInTimeRecordTest(unittest.TestCase):
    def test_a_point_in_time_record_is_never_an_inbound_rewrite(self):
        texts = {"docs/adr/001.md": "[a](../../a.md)\n",
                 ".agents/artifacts/plans/p.md": "[a](../../../a.md)\n",
                 "docs/g.md": "[a](../a.md)\n"}
        paths = set(texts) | {"a.md"}
        result = adopt_links.plan_link_rewrites(
            texts, paths, [("a.md", "b/a.md")], [])
        self.assertEqual(sorted(result.files), ["docs/g.md"])
        self.assertEqual(result.summary["unrewritable"], [])
        self.assertEqual(result.summary["already_broken"], 0)


if __name__ == "__main__":
    unittest.main()
