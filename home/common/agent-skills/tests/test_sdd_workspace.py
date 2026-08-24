from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
WORKSPACE = ROOT / "home/common/agent-skills/skills/sdd/scripts/sdd-workspace"

GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


def git_env():
    """A hermetic git environment: no user/system config, no signing.

    The fixture below runs `git commit`, and this repository's author has
    `commit.gpgsign=true` with an SSH signing key in global config. Inherited,
    that makes every fixture commit really signed — so the suite passes only
    where that key exists and is usable, and errors in `make_primary` anywhere
    else. `just agent-workflow-tests` runs this suite as a whole-repo gate, so
    "anywhere else" means any other maintainer's checkout.

    GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM is preferred over the temp-`HOME`
    isolation in test_review_package.py: that suite needs a temp HOME anyway to
    stand up an importable module home, while this fixture needs nothing from
    HOME. Nulling both config files also covers ambient config generally rather
    than just signing, so an aliased `commit`, a hooksPath, or a templateDir
    cannot reach the fixture either.

    Every variable that relocates git's repository, work tree, index or object
    store is dropped too, so an invoking session exporting one of them cannot
    redirect this suite's scratch repositories — or the `sdd-workspace` run
    under test, whose whole job is resolving checkout identity from git. The
    tuple is duplicated from test_ship_release_contracts.py rather than
    imported: these suites share no helper module (issue 31's D10). A blanket
    GIT_* sweep is rejected because it would also drop GIT_EXEC_PATH and
    GIT_TEMPLATE_DIR, which a Nix-provided git may rely on.
    """
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        }
    )
    return env


class SddWorkspaceTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, env=git_env(),
            capture_output=True, text=True,
        ).stdout

    def make_primary(self, directory: Path, name: str = "main") -> tuple[Path, Path]:
        """A real primary checkout with one commit. Returns (primary, plan)."""
        primary = directory / name
        primary.mkdir()
        self.git(primary, "init", "-q")
        self.git(primary, "config", "user.name", "Fixture")
        self.git(primary, "config", "user.email", "fixture@example.test")
        plan = primary / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        self.git(primary, "add", "-A")
        self.git(primary, "commit", "-q", "-m", "seed")
        return primary, plan

    def add_worktree(self, primary: Path, path: Path, branch: str) -> Path:
        self.git(primary, "worktree", "add", "-q", "-b", branch, str(path))
        plan = path / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        return plan

    def invoke(self, cwd: Path, plan: Path, env: dict[str, str] | None = None):
        return subprocess.run(
            [str(WORKSPACE), str(plan)], cwd=cwd, env=env or git_env(),
            capture_output=True, text=True, check=False,
        )

    def test_primary_checkout_uses_the_primary_bucket(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            result = self.invoke(primary, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(primary / ".superpowers/sdd/primary/plan"),
            )
            self.assertTrue(Path(result.stdout.strip()).is_dir())

    def test_linked_worktree_buckets_under_the_primary_and_leaves_no_nest(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            primary, _ = self.make_primary(base)
            worktree = base / "one"
            plan = self.add_worktree(primary, worktree, "issue-102")
            result = self.invoke(worktree, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(primary / ".superpowers/sdd/wt-one/plan"),
            )
            self.assertFalse((worktree / ".superpowers").exists())

    def test_submodule_working_tree_resolves_to_its_own_toplevel(self):
        """A submodule's common dir is <super>/.git/modules/<name> — not `.git`."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            child, _ = self.make_primary(base, "child")
            parent, _ = self.make_primary(base, "parent")
            self.git(parent, "-c", "protocol.file.allow=always",
                     "submodule", "add", "-q", str(child), "sub")
            self.git(parent, "commit", "-q", "-m", "add submodule")
            checkout = parent / "sub"
            result = self.invoke(checkout, checkout / "plan.md")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(checkout / ".superpowers/sdd/primary/plan"),
            )
            self.assertFalse((parent / ".superpowers").exists())

    def test_separate_git_dir_checkout_resolves_to_its_own_toplevel(self):
        """`git init --separate-git-dir=<gd>` gives a common dir named <gd>."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            checkout = base / "sep"
            subprocess.run(
                ["git", "init", "-q", "--separate-git-dir", str(base / "gd"),
                 str(checkout)], check=True, env=git_env(),
            )
            plan = checkout / "plan.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            result = self.invoke(checkout, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(checkout / ".superpowers/sdd/primary/plan"),
            )

    def test_two_worktrees_running_one_plan_do_not_share_a_ledger(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            primary, _ = self.make_primary(base)
            first = self.add_worktree(primary, base / "one", "issue-102")
            second = self.add_worktree(primary, base / "two", "issue-103")
            one = Path(self.invoke(base / "one", first).stdout.strip())
            two = Path(self.invoke(base / "two", second).stdout.strip())
            self.assertNotEqual(one, two)
            (one / "progress.md").write_text("# SDD ledger\n", encoding="utf-8")
            self.assertFalse((two / "progress.md").exists())

    def test_workspace_base_self_ignores(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            self.invoke(primary, plan)
            ignore = primary / ".superpowers/sdd/.gitignore"
            self.assertEqual(ignore.read_bytes(), b"*\n")

    def test_unresolvable_checkout_identity_refuses_and_creates_nothing(self):
        """A Git dir that is neither the common dir nor <common>/worktrees/<name>.

        Driven by a decoy bare repository inside the common dir (D15): a
        GIT_DIR that is not itself a repository makes `git rev-parse` fail
        outright, so the script would refuse before ever comparing git dir to
        common dir and the identity branch this test is about would go
        unexercised. The decoy keeps both rev-parse calls succeeding and lands
        exactly on the mismatch.
        """
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            common = primary / ".git"
            decoy = common / "decoy.git"
            subprocess.run(["git", "init", "-q", "--bare", str(decoy)],
                           check=True, env=git_env())
            env = git_env()
            env["GIT_DIR"] = str(decoy)
            env["GIT_COMMON_DIR"] = str(common)
            result = self.invoke(primary, plan, env)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "cannot resolve checkout identity\n")
            self.assertFalse((primary / ".superpowers").exists())

    def test_missing_plan_file_still_refuses(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, _ = self.make_primary(Path(raw).resolve())
            result = self.invoke(primary, primary / "absent.md")
            self.assertEqual(result.returncode, 2)
            self.assertFalse((primary / ".superpowers").exists())


if __name__ == "__main__":
    unittest.main()
