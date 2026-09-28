"""Seam 1 for deployment verification and `superseded` (#127 D9, D24, D26, D32)."""

import hashlib
import json
import unittest

from .promotion_test_support import (NULL_DIGEST, LifecycleFixture, draft, duplicate,
                                     write_bundle, write_json)

HERE = "fagenorn/nix-config"
DESTINATION = "home/common/agent-skills/standards/the-bar.md"
HEADING = "### Investigate before changing"
LEFTOVER = b"Investigate before changing.\n"


class DeploymentTest(LifecycleFixture, unittest.TestCase):
    def authorized(self, duplicates, name="c.json", with_destination=True):
        path = self.capture(draft(local_duplicates=duplicates), name=name)
        self.walk(path, "authorized", "approved")
        if with_destination:
            target = self.root / DESTINATION
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# The bar\n{HEADING}\n", encoding="utf-8")
        return path

    def put(self, relative, data=LEFTOVER):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_promotion_records_removed_retained_and_deferred(self):
        self.put("docs/keep.md")
        path = self.authorized([
            duplicate(HERE, "docs/lesson.md", hashlib.sha256(LEFTOVER).hexdigest()),
            duplicate(HERE, "docs/keep.md", disposition="project_only_residue"),
            duplicate("fagenorn/argus", "AGENTS.md"),
            duplicate("fagenorn/argus", "CLAUDE.md")])
        after = self.step(path, "promoted")
        self.assertEqual(after["deployment"], {
            "verified_repository": HERE, "removed": ["docs/lesson.md"],
            "retained": ["docs/keep.md"], "deferred_repositories": ["fagenorn/argus"]})
        self.assertEqual([after["state"], after["history"][-1]["actor"]], ["promoted", None])
        self.assertTrue((self.root / "docs/keep.md").exists())

    def test_the_destination_is_checked_before_any_duplicate(self):
        self.put("docs/lesson.md")
        path = self.authorized([duplicate(HERE, "docs/lesson.md",
                                          hashlib.sha256(LEFTOVER).hexdigest())],
                               with_destination=False)
        self.assert_refused(path, "promoted", "destination_missing")
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + " code\n", encoding="utf-8")
        self.assert_refused(path, "promoted", "destination_missing")

    def test_an_unchanged_leftover_is_duplicate_present(self):
        self.put("docs/lesson.md")
        path = self.authorized([duplicate(HERE, "docs/lesson.md",
                                          hashlib.sha256(LEFTOVER).hexdigest())])
        payload = self.assert_refused(path, "promoted", "duplicate_present")
        self.assertEqual(payload["error"]["violations"][0]["pointer"],
                         "/local_duplicates/0/path")
        self.assertTrue((self.root / "docs/lesson.md").exists())

    def test_anything_but_absent_or_identical_needs_reconciliation(self):
        digest = hashlib.sha256(LEFTOVER).hexdigest()
        real = self.put("real/lesson.md")
        cases = {
            "drifted": lambda: self.put("docs/lesson.md", b"edited\n"),
            "null_digest": lambda: self.put("docs/lesson.md"),
            "directory": lambda: (self.root / "docs/lesson.md").mkdir(parents=True),
            "leaf_link": lambda: ((self.root / "docs").mkdir(),
                                  (self.root / "docs/lesson.md").symlink_to(real)),
            "parent_link": lambda: (self.root / "docs").symlink_to(
                real.parent, target_is_directory=True),
        }
        for index, (name, make) in enumerate(cases.items()):
            with self.subTest(case=name):
                for leftover in ("docs/lesson.md", "docs"):
                    target = self.root / leftover
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.is_dir():
                        target.rmdir()
                sha = NULL_DIGEST if name == "null_digest" else digest
                path = self.authorized([duplicate(HERE, "docs/lesson.md", sha)],
                                       name=f"{index}.json")
                make()
                self.assert_refused(path, "promoted", "promotion_reconciliation_required")

    def test_a_null_digest_with_the_file_gone_is_removed(self):
        path = self.authorized([duplicate(HERE, "docs/lesson.md", NULL_DIGEST)])
        self.assertEqual(self.step(path, "promoted")["deployment"]["removed"],
                         ["docs/lesson.md"])

    def test_a_hand_edited_authorized_candidate_gains_nothing(self):
        path = self.capture()
        document = json.loads(path.read_text(encoding="utf-8"))
        classification = {"rule": 4, "rule_id": "standard_layer",
                          "declared_layer": "standard_layer", "overridden_by_rule_1": False}
        write_json(path, dict(document, state="authorized", classification=None))
        payload = self.assert_refused(path, "promoted", "transition_not_permitted")
        self.assertEqual(payload["error"]["violations"][0]["pointer"], "/classification")
        write_json(path, dict(document, state="authorized", classification=classification))
        self.assert_refused(path, "promoted", "evidence_unresolvable")
        bundle = json.loads(write_bundle(self.root, self.BUNDLE, "unmeasured")
                            .read_text(encoding="utf-8"))
        write_json(path, dict(document, state="authorized", classification=classification,
                              evidence={"bundle_path": self.BUNDLE,
                                        "bundle_id": bundle["bundle_id"],
                                        "state": "approved", "gate_contract": "issue-70",
                                        "gate_version": 1}))
        self.assert_refused(path, "promoted", "evidence_unmeasured")

    def test_a_rule_one_candidate_passes_the_same_gates(self):
        """D26: a duplicate-of-platform lesson earns no evidence exemption."""
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + "\n", encoding="utf-8")
        path = self.capture(draft(local_duplicates=[]))
        self.walk(path, "decision_ready", "unmeasured")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["classification"]["rule"], 1)
        self.assert_refused(path, "authorized", "evidence_unmeasured",
                            "--authorized-by", "fagenorn")


class SupersededTest(LifecycleFixture, unittest.TestCase):
    NEW = "sha256:" + "a" * 64

    def promoted(self):
        path = self.capture(draft(local_duplicates=[]))
        self.walk(path, "authorized", "approved")
        target = self.root / DESTINATION
        target.parent.mkdir(parents=True)
        target.write_text(HEADING + "\n", encoding="utf-8")
        self.step(path, "promoted")
        return path

    def test_superseded_is_the_only_edge_out_of_promoted(self):
        path = self.promoted()
        for target, flags in (("rejected", ("--rationale", "x")), ("evaluating", ()),
                              ("withdrawn", ("--rationale", "x"))):
            with self.subTest(target=target):
                self.assert_refused(path, target, "transition_not_permitted", *flags)
        self.assert_refused(path, "superseded", None, exit_code=2)
        self.assert_refused(path, "superseded", None, "--superseded-by", "sha256:xyz",
                            exit_code=2)
        after = self.step(path, "superseded", "--superseded-by", self.NEW)
        self.assertEqual([after["state"], after["history"][-1]["rationale"]],
                         ["superseded", f"superseded by {self.NEW}"])
        self.assert_refused(path, "promoted", "transition_not_permitted")

    def test_authorized_can_still_be_rejected(self):
        path = self.capture()
        self.walk(path, "authorized", "approved")
        after = self.step(path, "rejected", "--rationale", "drift incorporated elsewhere")
        self.assertEqual(after["state"], "rejected")
