"""`agent_tools.verification.protection_tree`: the protection-matches-tree verify check."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.system import forge_api
from agent_tools.verification import protection_tree

from tests.test_verify_checks import CHECKS, ROOT, committed_mode, forge, run_from_root


class ProtectionMatchesTreeTest(unittest.TestCase):
    PROT = "repos/o/r/branches/main/protection/required_status_checks"
    LABELS = "repos/o/r/labels?per_page=100"
    TREE = {"required_status_checks": {"strict": True, "checks": [
        {"context": "Nix Eval", "app_id": 15368}, {"context": "Conformance", "app_id": 15368}]}}

    def check(self, live, labels, root, absent=("retired-label",)):
        gets = {self.PROT: {"checks": live}}
        patches = forge(gets, {self.LABELS: labels})
        with patches[0], patches[1]:
            return protection_tree.protection_matches_tree("o/r", "main", root, absent)

    def root(self, tmp, tree=None):
        (Path(tmp) / ".github").mkdir()
        (Path(tmp) / ".github" / "branch-protection.json").write_text(json.dumps(tree or self.TREE))
        return Path(tmp)

    def test_agreement_is_met_and_each_difference_is_not(self):
        agreed = [{"context": "Nix Eval", "app_id": 15368}, {"context": "Conformance", "app_id": 15368}]
        with tempfile.TemporaryDirectory() as tmp:
            root = self.root(tmp)
            with self.subTest("agreement"):
                self.assertEqual(self.check(agreed, [[{"name": "bug"}]], root),
                                 (0, {"met": True, "missing": [], "extra": [], "labels_present": []}))
            with self.subTest("an extra live check"):
                code, report = self.check(
                    agreed + [{"context": "Old Gate", "app_id": 15368}], [[{"name": "bug"}]], root)
                self.assertEqual((code, report["extra"], report["missing"], report["met"]),
                                 (1, [["Old Gate", 15368]], [], False))
            with self.subTest("a missing live check"):
                code, report = self.check(agreed[:1], [[{"name": "bug"}]], root)
                self.assertEqual((code, report["missing"], report["extra"]),
                                 (1, [["Conformance", 15368]], []))
            with self.subTest("the same context bound to another app"):
                code, report = self.check(
                    [agreed[0], {"context": "Conformance", "app_id": 1}], [[{"name": "bug"}]], root)
                self.assertEqual((code, report["extra"], report["missing"]),
                                 (1, [["Conformance", 1]], [["Conformance", 15368]]))
            with self.subTest("the absent label is present, whatever its case"):
                code, report = self.check(agreed, [[{"name": "Retired-Label"}]], root)
                self.assertEqual((code, report["labels_present"]), (1, ["Retired-Label"]))
            with self.subTest("labels on every page are read"):
                code, report = self.check(agreed, [[{"name": "bug"}], [{"name": "retired-label"}]], root)
                self.assertEqual((code, report["labels_present"]), (1, ["retired-label"]))

    def test_a_tree_app_id_that_is_absent_null_or_minus_one_is_any_app(self):
        tree = {"required_status_checks": {"checks": [
            {"context": "A"}, {"context": "B", "app_id": None}, {"context": "C", "app_id": -1}]}}
        live = [{"context": "A", "app_id": -1}, {"context": "B"}, {"context": "C", "app_id": None}]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check(live, [[]], self.root(tmp, tree))[0], 0)

    def test_a_forge_error_exits_2(self):
        with mock.patch.object(forge_api, "api_pages", side_effect=forge_api.ForgeError("payload_invalid")), \
                mock.patch.object(forge_api, "api_get", return_value={"checks": []}):
            self.assertEqual(protection_tree.main(
                ["--repo", "o/r", "--base", "main"]), 2)

    def test_a_bad_label_page_or_tree_file_exits_2(self):
        agreed = [{"context": "Nix Eval", "app_id": 15368}, {"context": "Conformance", "app_id": 15368}]
        with tempfile.TemporaryDirectory() as tmp:
            root = self.root(tmp)
            for name, labels in (("an object page", [{"name": "x"}]), ("a nameless label", [[{"id": 1}]]),
                                 ("a non-string name", [[{"name": 3}]])):
                with self.subTest(name), self.assertRaises(forge_api.ForgeError):
                    self.check(agreed, labels, root)
        for name, text in (("malformed", "{"), ("no checks", "{}")):
            with tempfile.TemporaryDirectory() as tmp, self.subTest(name):
                (Path(tmp) / ".github").mkdir()
                (Path(tmp) / ".github" / "branch-protection.json").write_text(text)
                with self.assertRaises(forge_api.ForgeError):
                    self.check(agreed, [[]], Path(tmp))
        with tempfile.TemporaryDirectory() as tmp, self.subTest("unreadable"):
            with self.assertRaises(forge_api.ForgeError):
                self.check(agreed, [[]], Path(tmp))


class ProtectionMatchesTreeCommandTest(unittest.TestCase):
    def test_the_wrapper_is_committed_executable_and_refuses_bad_usage(self):
        self.assertEqual(committed_mode(f"{CHECKS}/protection-matches-tree"), "100755")
        self.assertEqual(run_from_root([str(ROOT / CHECKS / "protection-matches-tree")]).returncode, 2)
