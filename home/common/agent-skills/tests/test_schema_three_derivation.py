"""The four values a schema-3 contract does not author, derived from the repository's files.

Every case stages a repository under a temporary directory and reads
`agent_tools.project_contract.derived_values` through its public names only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import adopt_planning, derived_values
from agent_tools.project_contract.derived_values import (
    PLATFORM,
    PROJECT_ID,
    REPO_SLUG,
    REQUIRED_CHECKS,
    TREE_MANIFEST,
    Underivable,
    derive,
    platform_interval,
    remote_slug,
    required_checks,
    store_path,
)

TIER = "fast"

ORIGIN = '[remote "origin"]\n\turl = git@github.com:o/r.git\n'


class DerivationCase(unittest.TestCase):
    def root(self) -> Path:
        path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def fifo(self, path: Path) -> None:
        """A FIFO with no writer at `path`; a blocking read of it would never return."""
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        previous = signal.signal(signal.SIGALRM, self.hung)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        signal.alarm(20)
        self.addCleanup(signal.alarm, 0)

    @staticmethod
    def hung(signum, frame):
        raise AssertionError("a derivation source read blocked on a FIFO")

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def git_config(self, root: Path, text: str) -> None:
        self.write(root / ".git" / "config", text)

    def protection(self, root: Path, text: str) -> None:
        self.write(root / ".github" / "branch-protection.json", text)

    def manifest(self, root: Path, version: str) -> None:
        self.write(root / TREE_MANIFEST, json.dumps({"platform_version": version}))

    def full_root(self) -> Path:
        root = self.root()
        self.git_config(root, "[remote \"origin\"]\n\turl = git@github.com:fagenorn/scratch.git\n")
        self.protection(root, json.dumps(
            {"required_status_checks": {"strict": True,
                                        "checks": [{"context": "B"}, {"context": "A"}]}}))
        self.manifest(root, "2.4.1")
        return root


class DeriveTest(DerivationCase):
    def test_derive_reads_all_four_values_from_a_repository(self):
        result = derive(self.full_root())
        self.assertEqual(result.violations, [])
        self.assertEqual(result.values, {
            "/project/id": "fagenorn/scratch",
            "/bindings/tracker/repo_slug": "fagenorn/scratch",
            "/bindings/vcs/merge/required_checks": ["B", "A"],
            "/platform": {"min_inclusive": "2.4.1", "max_exclusive": "3.0.0"},
        })

    def test_derive_turns_each_failure_into_a_named_violation(self):
        root = self.root()
        result = derive(root)
        self.assertEqual(result.values, {})
        self.assertEqual(sorted((v["pointer"], v["repair_id"]) for v in result.violations), [
            ("/bindings/tracker/repo_slug", "contract.tracker.not_derivable"),
            ("/bindings/vcs/merge/required_checks", "contract.vcs.not_derivable"),
            ("/platform", "contract.platform.not_derivable"),
            ("/project/id", "contract.project.not_derivable"),
        ])
        by_pointer = {v["pointer"]: v["message"] for v in result.violations}
        self.assertEqual(by_pointer[PROJECT_ID], by_pointer[REPO_SLUG])
        for violation in result.violations:
            self.assertNotIn(str(root), violation["message"])

    def test_a_null_protection_source_leaves_the_checks_out_without_a_violation(self):
        root = self.full_root()
        self.protection(root, json.dumps({"required_status_checks": None}))
        result = derive(root)
        self.assertEqual(result.violations, [])
        self.assertNotIn(REQUIRED_CHECKS, result.values)
        self.assertIn(PLATFORM, result.values)

    def test_derivation_starts_no_child_process_and_opens_no_connection(self):
        root = self.full_root()
        expected = derive(root).values
        with mock.patch("subprocess.Popen", side_effect=AssertionError), \
                mock.patch("socket.socket", side_effect=AssertionError):
            self.assertEqual(derive(root).values, expected)

    def test_the_remote_spelling_has_one_home(self):
        self.assertIs(adopt_planning.normalize_remote_url, derived_values.normalize_remote_url)


class StorePathTest(unittest.TestCase):
    def test_the_store_path_is_the_path_nix_computes(self):
        self.assertEqual(
            store_path("sha256-3GnIGIy15bMduoS9RnWqKTmsJLWThla42UFtm0S7+us=", "/nix/store"),
            "/nix/store/xxf7z4ziia7hlfbccd7xk4fc5qx2mvi2-source")
        with self.assertRaises(Underivable):
            store_path("sha512-AAAA", "/nix/store")


class RemoteTest(DerivationCase):
    def slug(self, config: str) -> str:
        root = self.root()
        self.git_config(root, config)
        return remote_slug(root)

    def test_remote_spellings(self):
        for url in ("git@github.com:o/r.git", "https://github.com/o/r",
                    "ssh://git@github.com/o/r.git", '"git@github.com:o/r.git"',
                    "git@github.com:o/r.git # note"):
            with self.subTest(url=url):
                self.assertEqual(self.slug(f'[remote "origin"]\n\turl = {url}\n'), "o/r")
        with self.subTest("first url wins"):
            self.assertEqual(self.slug(
                '[remote "origin"]\n\turl = git@github.com:o/r.git\n\turl = git@github.com:x/y.git\n'),
                "o/r")
        with self.subTest("a differently cased subsection is not origin"):
            with self.assertRaises(Underivable) as raised:
                self.slug('[remote "Origin"]\n\turl = git@github.com:o/r.git\n')
            self.assertIn("git remote origin", raised.exception.message)
        with self.subTest("an unrecognised spelling"):
            with self.assertRaises(Underivable) as raised:
                self.slug('[remote "origin"]\n\turl = gh:o/r\n')
            self.assertIn("recognised", raised.exception.message)

    def test_a_comment_after_a_tab_is_not_part_of_the_url(self):
        for gap in ("\t", " \t", "\t ", "  "):
            for marker in ("#", ";"):
                with self.subTest(gap=gap, marker=marker):
                    self.assertEqual(self.slug(
                        f'[remote "origin"]\n\turl = git@github.com:o/r.git{gap}{marker} note\n'),
                        "o/r")

    def test_a_config_that_is_a_fifo_is_refused_without_blocking(self):
        root = self.root()
        self.fifo(root / ".git" / "config")
        with self.assertRaises(Underivable) as raised:
            remote_slug(root)
        self.assertIn("git config", raised.exception.message)

    def test_a_linked_worktree_reads_the_common_config(self):
        base = self.root()
        self.git_config(base / "main", ORIGIN)
        self.write(base / "main" / ".git" / "worktrees" / "wt" / "commondir", "../..\n")
        self.write(base / "wt" / ".git", "gitdir: ../main/.git/worktrees/wt\n")
        self.assertEqual(remote_slug(base / "wt"), "o/r")
        with self.assertRaises(Underivable) as raised:
            remote_slug(self.root())
        self.assertIn("git config", raised.exception.message)


class ProtectionTest(DerivationCase):
    def test_protection_sources(self):
        for name, text, expected in (
                ("null", '{"required_status_checks": null}', []),
                ("empty", '{"required_status_checks": {"checks": []}}', [])):
            with self.subTest(name):
                root = self.root()
                self.protection(root, text)
                self.assertEqual(required_checks(root), expected)
        refused = (
            ("invalid json", "{"),
            ("contexts only", '{"required_status_checks": {"contexts": ["A"]}}'),
            ("duplicate", '{"required_status_checks": {"checks": [{"context": "A"}, {"context": "A"}]}}'),
            ("non-string", '{"required_status_checks": {"checks": [{"context": 3}]}}'),
        )
        for name, text in refused:
            with self.subTest(name):
                root = self.root()
                self.protection(root, text)
                with self.assertRaises(Underivable) as raised:
                    required_checks(root)
                self.assertIn(".github/branch-protection.json", raised.exception.message)
        with self.subTest("absent"):
            with self.assertRaises(Underivable) as raised:
                required_checks(self.root())
            self.assertIn(".github/branch-protection.json", raised.exception.message)


    def test_a_protection_source_nested_past_the_recursion_limit_is_refused(self):
        root = self.root()
        self.protection(root, "[" * 200000)
        with self.assertRaises(Underivable) as raised:
            required_checks(root)
        self.assertIn(".github/branch-protection.json", raised.exception.message)

    def test_a_protection_source_that_is_a_fifo_is_refused_without_blocking(self):
        root = self.root()
        self.fifo(root / ".github" / "branch-protection.json")
        with self.assertRaises(Underivable) as raised:
            required_checks(root)
        self.assertIn(".github/branch-protection.json", raised.exception.message)


class PlatformTest(DerivationCase):
    NAR = "sha256-" + base64.b64encode(hashlib.sha256(b"rev").digest()).decode()

    def lock(self, root: Path, lock: object) -> None:
        self.write(root / "devenv.lock", lock if isinstance(lock, str) else json.dumps(lock))

    def locked_root(self, store: Path, version: object = "2.0.0") -> Path:
        root = self.root()
        self.lock(root, {"nodes": {"root": {"inputs": {"agent-platform": "agent-platform_2"}},
                                    "agent-platform_2": {"locked": {"narHash": self.NAR}}},
                         "root": "root", "version": 7})
        if version is not None:
            self.write(Path(store_path(self.NAR, str(store))) / TREE_MANIFEST,
                       json.dumps({"platform_version": version}))
        return root

    def interval(self, root: Path, store: Path):
        with mock.patch.object(derived_values, "STORE_DIR", str(store)):
            return platform_interval(root)

    def test_a_locked_revision_is_read_from_the_store(self):
        store = self.root()
        self.assertEqual(self.interval(self.locked_root(store), store),
                         {"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"})

    def test_a_lock_that_cannot_name_the_input_is_refused(self):
        store = self.root()
        cases = (
            ("no lock", None),
            ("bad json", "{"),
            ("no input", {"nodes": {"root": {"inputs": {}}}, "root": "root"}),
            ("follows", {"nodes": {"root": {"inputs": {"agent-platform": ["x"]}}}, "root": "root"}),
            ("list nodes", {"nodes": [], "root": 0}),
            ("string nodes", {"nodes": "", "root": 0}),
        )
        for name, lock in cases:
            with self.subTest(name):
                root = self.root()
                if lock is not None:
                    self.lock(root, lock)
                with self.assertRaises(Underivable) as raised:
                    self.interval(root, store)
                self.assertIn("devenv.lock", raised.exception.message)

    def test_a_missing_store_entry_and_a_bad_manifest_are_refused(self):
        store = self.root()
        with self.subTest("missing store entry"):
            with self.assertRaises(Underivable) as raised:
                self.interval(self.locked_root(store, version=None), store)
            self.assertIn("Nix store", raised.exception.message)
        with self.subTest("bad manifest version"):
            other = self.root()
            with self.assertRaises(Underivable) as raised:
                self.interval(self.locked_root(other, version="2.1"), other)
            self.assertIn("platform manifest", raised.exception.message)

    def test_a_lock_or_manifest_nested_past_the_recursion_limit_is_refused(self):
        store = self.root()
        with self.subTest("lock"):
            root = self.root()
            self.lock(root, "[" * 200000)
            with self.assertRaises(Underivable) as raised:
                self.interval(root, store)
            self.assertIn("devenv.lock", raised.exception.message)
        with self.subTest("manifest"):
            root = self.root()
            self.write(root / TREE_MANIFEST, "[" * 200000)
            with self.assertRaises(Underivable) as raised:
                platform_interval(root)
            self.assertIn("platform manifest", raised.exception.message)

    def test_a_lock_or_manifest_that_is_a_fifo_is_refused_without_blocking(self):
        store = self.root()
        with self.subTest("lock"):
            root = self.root()
            self.fifo(root / "devenv.lock")
            with self.assertRaises(Underivable) as raised:
                self.interval(root, store)
            self.assertIn("devenv.lock", raised.exception.message)
        with self.subTest("manifest"):
            root = self.root()
            self.fifo(root / TREE_MANIFEST)
            with self.assertRaises(Underivable) as raised:
                platform_interval(root)
            self.assertIn("platform manifest", raised.exception.message)

    def test_the_platforms_own_tree_never_opens_the_lock(self):
        root = self.root()
        self.manifest(root, "3.2.0")
        self.lock(root, "not json")
        self.assertEqual(platform_interval(root),
                         {"min_inclusive": "3.2.0", "max_exclusive": "4.0.0"})


if __name__ == "__main__":
    unittest.main()
