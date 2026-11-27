"""GitBuilder: the bump commit built in a scratch worktree with the proven revision's own tools.

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, lock_bump_tree
from agent_tools.console.lock_bump_tree import BumpRefused, Built, GitBuilder, branch_for, bumped_lock
from tests.test_console_lock_bump_tree import REV_A, REV_B, document, dumped, record

TIER = "integration"  # it builds a sandbox git repository and runs git

REV_C = "c" * 40
SLUG = "octo/fixture"
MANIFEST = {"project_schema_versions": [3],
            "migrations": [{"id": "platform-constants.retire", "from_schema": 2, "to_schema": 3}]}


def git(*args, cwd=None):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout.strip()


def write_script(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + text)
    path.chmod(0o755)


class BuildFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolation = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
        isolation.start()
        self.addCleanup(isolation.stop)
        self.origin = self.tmp / "origin.git"
        self.seed = self.tmp / "seed"
        self.root = self.tmp / "root"
        self.git("init", "--bare", "-q", "-b", "main", str(self.origin))
        self.git("init", "-q", "-b", "main", str(self.seed))
        for key, value in (("user.name", "Test"), ("user.email", "t@example.com")):
            self.git("config", key, value, cwd=self.seed)
        self.git("remote", "add", "origin", str(self.origin), cwd=self.seed)
        self.publish({"devenv.lock": dumped(document()), ".agents/project.json": b'{"schema_version": 3}',
                      "AGENTS.md": b"old\n"})
        self.git("clone", "-q", str(self.origin), str(self.root))
        signer = self.tmp / "signer"
        self.signer_log = self.tmp / "signer.log"
        write_script(signer, f"echo called >> {self.signer_log}\ncat >/dev/null\n"
                             "echo '[GNUPG:] SIG_CREATED ' >&2\n"
                             "printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nc3R1Yg==\\n-----END PGP SIGNATURE-----\\n'\n")
        for key, value in (("user.name", "Test"), ("user.email", "t@example.com"), ("commit.gpgsign", "true"),
                           ("gpg.format", "openpgp"), ("gpg.program", str(signer))):
            self.git("config", key, value, cwd=self.root)
        self.resolved = self.tmp / "resolved.json"
        self.resolved.write_text(json.dumps({"bindings": {"vcs": {"commit": {"signed": False}}}}))
        self.migrations_log = self.tmp / "migrations.log"
        self.token = self.tmp / "token"
        self.fail = self.tmp / "fail"
        self.pkg = self.make_package(record(REV_B))
        self.package_calls = []
        self.origin_calls = []
        self.builder = GitBuilder("octo/platform", package=self.package, origin_check=self.check_origin)

    def git(self, *args, cwd=None):
        code, out = git(*args, cwd=cwd)
        self.assertEqual(code, 0, f"git {args}: {out}")
        return out

    def publish(self, files):
        for name, data in files.items():
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", "--all", cwd=self.seed)
        self.git("commit", "-q", "-m", "seed", cwd=self.seed)
        self.git("push", "-q", "origin", "main", cwd=self.seed)

    def make_package(self, revision):
        pkg = self.tmp / "pkg"
        share = pkg / "share" / "agent-platform"
        share.mkdir(parents=True, exist_ok=True)
        (share / "platform-revision.json").write_text(json.dumps({"schema_version": 1, **revision}))
        (share / "platform-manifest.json").write_text(json.dumps(MANIFEST))
        write_script(pkg / "bin" / "resolve-project",
                     f'echo "${{GH_TOKEN:-unset}}" > {self.token}\n[ -e {self.fail} ] && exit 1\n'
                     'case "$1" in\nwrite-projections) printf \'generated\\n\' > "$3/AGENTS.md";;\n'
                     f'resolve) cat {self.resolved};;\nesac\n')
        write_script(pkg / "bin" / "adopt-project",
                     f'echo "$@" >> {self.migrations_log}\nprintf \'{{"schema_version": 3}}\' > "$5/.agents/project.json"\n')
        return pkg

    def package(self, revision, cancel):
        self.package_calls.append(revision)
        return self.pkg

    def check_origin(self, root, slug):
        self.origin_calls.append((root, slug))

    def pushed(self, branch):
        return self.git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=self.origin)

    def show(self, branch, path):
        return self.git("show", f"{branch}:{path}", cwd=self.origin)

    def trees(self):
        listing = self.git("worktree", "list", "--porcelain", cwd=self.root)
        return [line for line in listing.splitlines() if line.startswith("worktree ")]


class BuildTest(BuildFixture):
    def test_a_build_pushes_one_commit_holding_the_lock_and_the_projections(self):
        branch = branch_for(REV_B)
        main_before = self.pushed("main")
        built = self.builder.build(self.root, SLUG, "main", REV_B)
        self.assertEqual(built, Built(branch, self.pushed(branch)))
        locked = json.loads(self.show(branch, "devenv.lock"))["nodes"]["agent-platform"]["locked"]
        self.assertEqual(locked, record(REV_B))
        self.assertEqual(self.show(branch, "AGENTS.md"), "generated")
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", branch, cwd=self.origin).split()[1:],
                         [main_before])
        self.assertEqual(self.pushed("main"), main_before)
        self.assertEqual(len(self.trees()), 1)
        self.assertFalse(self.migrations_log.exists())
        self.assertNotIn("gpgsig", self.git("cat-file", "commit", branch, cwd=self.origin))
        self.assertFalse(self.signer_log.exists())

    def test_the_pin_is_read_from_the_fetched_base(self):
        lock = bumped_lock(dumped(document()), record(REV_C))
        self.publish({"devenv.lock": lock})
        self.assertEqual(self.builder.pin(self.root, SLUG, "main"), REV_C)
        self.assertEqual(self.origin_calls, [(self.root, SLUG)])

    def test_a_contract_on_a_retired_schema_is_migrated_in_the_bump(self):
        self.publish({".agents/project.json": b'{"schema_version": 2}'})
        self.git("fetch", "-q", cwd=self.root)
        branch = self.builder.build(self.root, SLUG, "main", REV_B).branch
        words = self.migrations_log.read_text().splitlines()
        self.assertEqual(len(words), 1)
        self.assertTrue(words[0].startswith("migrate --migration platform-constants.retire --repo-root "))
        tree = Path(words[0].split("--repo-root ")[1])
        self.assertEqual((tree.name, tree.parent.name.startswith("lock-bump-")), ("tree", True))
        self.assertEqual(json.loads(self.show(branch, ".agents/project.json"))["schema_version"], 3)

    def test_a_failed_projection_pushes_nothing_and_removes_the_worktree(self):
        self.fail.write_text("")
        scratch = Path(tempfile.mkdtemp(dir=self.tmp))
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            with self.assertRaises(BumpRefused):
                self.builder.build(self.root, SLUG, "main", REV_B)
        code, _ = git("rev-parse", "--verify", f"refs/heads/{branch_for(REV_B)}", cwd=self.origin)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.trees()), 1)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_children_run_without_repository_selectors_or_tokens(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.tmp / "nowhere"), "GH_TOKEN": "secret"}):
            self.builder.build(self.root, SLUG, "main", REV_B)
        self.assertTrue(self.pushed(branch_for(REV_B)))
        self.assertEqual(self.token.read_text().strip(), "unset")

    def test_a_cancel_raises_cancelled_and_removes_the_worktree(self):
        event = threading.Event()

        def cancelling(revision, cancel):
            cancel.set()
            return self.pkg

        builder = GitBuilder("octo/platform", package=cancelling, origin_check=self.check_origin)
        with self.assertRaises(approve.Cancelled):
            builder.build(self.root, SLUG, "main", REV_B, cancel=event)
        code, _ = git("rev-parse", "--verify", f"refs/heads/{branch_for(REV_B)}", cwd=self.origin)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.trees()), 1)

    def test_an_existing_bump_branch_holding_the_bump_is_reused_without_a_second_build(self):
        branch = branch_for(REV_B)
        first = self.builder.build(self.root, SLUG, "main", REV_B)
        self.package_calls.clear()
        self.assertEqual(self.builder.build(self.root, SLUG, "main", REV_B), first)
        self.assertEqual(self.package_calls, [])
        self.assertEqual(self.pushed(branch), first.commit)

    def test_an_existing_bump_branch_that_is_unchanged_main_is_refused_not_reused(self):
        branch = branch_for(REV_B)
        self.git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=self.root)
        with self.assertRaisesRegex(BumpRefused, "does not lock"):
            self.builder.build(self.root, SLUG, "main", REV_B)
        self.assertEqual(self.package_calls, [])

    def test_verify_refuses_a_head_the_branch_is_no_longer_at(self):
        built = self.builder.build(self.root, SLUG, "main", REV_B)
        self.builder.verify(self.root, SLUG, REV_B, built.commit)
        with self.assertRaisesRegex(BumpRefused, "not at"):
            self.builder.verify(self.root, SLUG, REV_B, self.pushed("main"))

    def test_a_package_of_another_revision_is_refused_before_a_worktree(self):
        self.make_package(record(REV_C))
        with self.assertRaises(BumpRefused):
            self.builder.build(self.root, SLUG, "main", REV_B)
        code, _ = git("rev-parse", "--verify", f"refs/heads/{branch_for(REV_B)}", cwd=self.origin)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.trees()), 1)

    def test_a_contract_that_asks_for_signing_signs_the_bump(self):
        self.resolved.write_text(json.dumps({"bindings": {"vcs": {"commit": {"signed": True}}}}))
        self.git("config", "commit.gpgsign", "false", cwd=self.root)
        branch = self.builder.build(self.root, SLUG, "main", REV_B).branch
        self.assertIn("gpgsig", self.git("cat-file", "commit", branch, cwd=self.origin))
        self.assertEqual(len(self.signer_log.read_text().splitlines()), 1)

    def test_an_unresolvable_signing_policy_is_refused_before_a_commit(self):
        self.resolved.write_text(json.dumps({"bindings": {}}))
        with self.assertRaisesRegex(BumpRefused, "signing"):
            self.builder.build(self.root, SLUG, "main", REV_B)
        code, _ = git("rev-parse", "--verify", f"refs/heads/{branch_for(REV_B)}", cwd=self.origin)
        self.assertNotEqual(code, 0)
        self.assertFalse(self.signer_log.exists())
        self.assertEqual(len(self.trees()), 1)

    def test_the_default_origin_check_refuses_a_checkout_of_another_repository(self):
        self.publish({"AGENTS.md": b"newer\n"})
        before = self.git("rev-parse", "refs/remotes/origin/main", cwd=self.root)
        builder = GitBuilder("octo/platform", package=self.package)
        with self.assertRaises(BumpRefused):
            builder.pin(self.root, SLUG, "main")
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main", cwd=self.root), before)


if __name__ == "__main__":
    unittest.main()
