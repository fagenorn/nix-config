"""The lock edit, branch names and required migrations of a lock bump.

Run: just agent-workflow-tests
"""
import json
import unittest

from agent_tools.project_contract import lock_bump_tree
from agent_tools.project_contract.lock_bump_tree import BumpRefused, branch_for, bumped_lock, pinned_revision, required_migrations
from tests.accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

REV_A = "a" * 40
REV_B = "b" * 40
HASH = "sha256-" + "A" * 43 + "="


def record(rev, repo="platform"):
    return {"type": "github", "owner": "octo", "repo": repo, "rev": rev, "narHash": HASH, "lastModified": 1700000000}


def document(with_platform=True):
    nodes = {
        "root": {"inputs": {"nixpkgs": "nixpkgs"}},
        "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "c" * 40,
                               "narHash": HASH, "lastModified": 1}},
    }
    if with_platform:
        nodes["root"]["inputs"]["agent-platform"] = "agent-platform"
        nodes["agent-platform"] = {"flake": False, "locked": record(REV_A),
                                   "original": {"owner": "octo", "repo": "platform", "type": "github"}}
    return {"nodes": nodes, "root": "root", "version": 7}


def dumped(doc, newline=True):
    return (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + ("\n" if newline else "")).encode()


MANIFEST = {"project_schema_versions": [2, 3],
            "migrations": [{"id": "bindings-deploy.retire", "from_schema": 1, "to_schema": 2},
                           {"id": "platform-constants.retire", "from_schema": 2, "to_schema": 3}]}


class LockTest(unittest.TestCase):
    def test_a_bumped_lock_pins_the_new_revision_and_keeps_every_other_node(self):
        expected = document()
        expected["nodes"]["agent-platform"]["locked"] = record(REV_B)
        self.assertEqual(bumped_lock(dumped(document()), record(REV_B)), dumped(expected))

    def test_a_lock_without_a_trailing_newline_stays_without_one(self):
        self.assertFalse(bumped_lock(dumped(document(), newline=False), record(REV_B)).endswith(b"\n"))

    def test_the_pinned_revision_is_the_entrys_rev(self):
        self.assertEqual(pinned_revision(dumped(document())), REV_A)

    def test_a_lock_without_a_platform_entry_is_refused(self):
        lock = dumped(document(with_platform=False))
        with self.assertRaises(BumpRefused):
            pinned_revision(lock)
        with self.assertRaises(BumpRefused):
            bumped_lock(lock, record(REV_B))

    def test_a_record_of_another_repository_is_refused(self):
        with self.assertRaises(BumpRefused):
            bumped_lock(dumped(document()), record(REV_B, repo="other"))

    def test_a_malformed_record_is_refused(self):
        broken = record(REV_B)
        del broken["narHash"]
        with self.assertRaises(BumpRefused):
            bumped_lock(dumped(document()), broken)


class MigrationTest(unittest.TestCase):
    def test_a_supported_schema_needs_no_migration(self):
        self.assertEqual(required_migrations(MANIFEST, 3), [])

    def test_a_retired_schema_with_one_step_to_a_supported_schema_runs_that_step(self):
        manifest = {**MANIFEST, "project_schema_versions": [3]}
        self.assertEqual(required_migrations(manifest, 2), ["platform-constants.retire"])

    def test_a_chain_stops_at_the_first_supported_schema(self):
        manifest = {**MANIFEST, "project_schema_versions": [2, 3]}
        self.assertEqual(required_migrations(manifest, 1), ["bindings-deploy.retire"])

    def test_a_chain_through_a_retired_intermediate_schema_is_refused_before_any_step(self):
        manifest = {**MANIFEST, "project_schema_versions": [3]}
        with self.assertRaisesRegex(BumpRefused, "bindings-deploy.retire.*schema 2"):
            required_migrations(manifest, 1)

    def test_a_schema_with_no_forward_step_is_refused(self):
        with self.assertRaises(BumpRefused):
            required_migrations({**MANIFEST, "project_schema_versions": [3]}, 4)

    def test_an_ambiguous_forward_step_is_refused(self):
        manifest = {"project_schema_versions": [3],
                    "migrations": [{"id": "a", "from_schema": 2, "to_schema": 3},
                                   {"id": "b", "from_schema": 2, "to_schema": 3}]}
        with self.assertRaises(BumpRefused):
            required_migrations(manifest, 2)

    def test_a_migration_cycle_is_refused(self):
        manifest = {"project_schema_versions": [5],
                    "migrations": [{"id": "a", "from_schema": 2, "to_schema": 3},
                                   {"id": "b", "from_schema": 3, "to_schema": 2}]}
        with self.assertRaises(BumpRefused):
            required_migrations(manifest, 2)


class BranchTest(unittest.TestCase):
    def test_branch_names_round_trip_and_refuse_other_shapes(self):
        self.assertEqual(lock_bump_tree.revision_of_branch(branch_for(REV_A)), REV_A)
        self.assertIsNone(lock_bump_tree.revision_of_branch("lock-bump-" + REV_A.upper()))
        self.assertIsNone(lock_bump_tree.revision_of_branch("adopt-0123456789ab"))
        with self.assertRaises(ValueError):
            branch_for("abc")


if __name__ == "__main__":
    unittest.main()
