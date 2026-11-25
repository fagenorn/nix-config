"""Tests for the hooks `adopt-project apply` installs with the global hooks path masked.

The fixture models a host whose global git configuration sets a managed
`core.hooksPath`, and a dev shell that installs a project's hooks the way
devenv's git-hooks installer does: refused while any hooks path is visible,
and writing a local hooks path on every stale-link shell entry.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import adopt_apply, adopt_inspection, hook_install

from .test_adopt_apply import ApplyTestCase, apply_repo
from .test_adopt_project import commit, git, write

TIER = "integration"  # git sandboxes, spawned sh and git

CHAIN_HOOK = Path(__file__).resolve().parents[2] / "claude-code/git-hooks/chain-hook"
CONFIG_VARIABLE = "FIXTURE_HOOKS_CONFIG"
DECLARED = "{ pkgs, ... }: {\n  git-hooks.hooks.needs-dev-shell.enable = true;\n}\n"
UNDECLARED = "{ pkgs, ... }: {\n  packages = [ pkgs.hello ];\n}\n"
HELLO_FAILURE = "needs-dev-shell: hello not found"
PASSED = "needs-dev-shell....Passed"

INSTALLER_SCRIPT = r"""
echo "dev-shell sees global hooks path: $(git config --global --get core.hooksPath || echo none)"
echo "dev-shell sees local hooks path: $(git config --local --get core.hooksPath || echo none)"
top=$(git rev-parse --show-toplevel)
common=$(git rev-parse --path-format=absolute --git-common-dir)
if [ "$(readlink "$top/.pre-commit-config.yaml")" != "$FIXTURE_HOOKS_CONFIG" ]; then
  ln -sf "$FIXTURE_HOOKS_CONFIG" "$top/.pre-commit-config.yaml"
  for hook in pre-commit prepare-commit-msg commit-msg pre-push; do
    if grep -q '^# fixture-installed-hook' "$common/hooks/$hook" 2>/dev/null; then
      rm -f "$common/hooks/$hook"
    fi
  done
  git config --local --unset-all core.hooksPath
  if [ -n "$(git config --get core.hooksPath)" ]; then
    echo "Refusing to install hooks because core.hooksPath is configured outside this repository" >&2
  else
    mkdir -p "$common/hooks"
    {
      echo '#!/bin/sh'
      echo '# fixture-installed-hook'
      echo '[ "$DEV_SHELL_ENTERED" = 1 ] || { echo "needs-dev-shell: hello not found" >&2; exit 7; }'
      echo 'echo "needs-dev-shell....Passed"'
    } > "$common/hooks/pre-commit"
    chmod 755 "$common/hooks/pre-commit"
  fi
  git config --local core.hooksPath "$common/hooks"
fi
DEV_SHELL_ENTERED=1 exec "$@"
"""
INSTALLER = ["sh", "-c", INSTALLER_SCRIPT, "dev-shell"]


def managed_hooks(directory: Path) -> Path:
    """The managed pass-through shims, one per commit hook."""
    managed = directory / "managed"
    managed.mkdir(parents=True)
    template = CHAIN_HOOK.read_text("utf-8")
    text = template.replace("@git@", shutil.which("git") or "git").replace("@gitlfs@", "")
    for name in hook_install.COMMIT_HOOKS:
        path = managed / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
    return managed


def fake_global(directory: Path, managed: Path) -> Path:
    """A global gitconfig that sets the managed hooks path."""
    path = directory / "gitconfig"
    path.write_text(
        f"[core]\n\thooksPath = {managed}\n"
        "[user]\n\tname = t\n\temail = t@example.invalid\n"
        "[commit]\n\tgpgsign = false\n", encoding="utf-8")
    return path


def declared_repo(home: Path, *, text: str = DECLARED, commands: dict | None = None,
                  **kwargs) -> Path:
    """`apply_repo` whose `HEAD` also tracks a `devenv.nix`."""
    root = apply_repo(home, commands=commands or {"dev-shell": INSTALLER}, **kwargs)
    write(root, "devenv.nix", text)
    commit(root, "add devenv.nix")
    return root


def broken_install(tail: str) -> dict:
    """A dev shell that writes a local hooks path during the install, then runs `tail`."""
    return {"dev-shell": [
        "sh", "-c",
        'if [ "$1" = true ]; then git config --local core.hooksPath '
        '"$(git rev-parse --path-format=absolute --git-common-dir)/hooks"; '
        f'{tail}; fi; exec "$@"', "dev-shell"]}


class HookInstallApplyTest(ApplyTestCase):
    def setUp(self) -> None:
        super().setUp()
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory, True)
        self.managed = managed_hooks(directory)
        self.global_config = fake_global(directory, self.managed)
        config = directory / "store" / "hooks-config.yaml"
        config.parent.mkdir()
        config.write_text("repos: []\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(self.global_config),
            "GIT_CONFIG_SYSTEM": os.devnull,
            CONFIG_VARIABLE: str(config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def verification(self, plan_id: str) -> dict:
        return self.stored_document(plan_id)["verification"]

    def planned(self, root: Path) -> str:
        return self.ready_plan(root)["plan"]["plan_id"]

    def test_a_missing_dev_shell_hook_is_installed_runs_in_the_adoption_commit_and_refuses_a_later_commit_outside_the_shell(
            self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        self.assertTrue((root / ".git/hooks/pre-commit").is_file())
        verification = self.verification(plan_id)
        self.assertIn(PASSED, verification["commit_output"]["lines"])
        self.assertEqual(verification["hook_install"], {"installed": ["pre-commit"]})
        outside = subprocess.run(
            ["git", "-C", str(root), "commit", "--allow-empty", "-m", "outside"],
            capture_output=True, text=True, check=False, timeout=120,
            env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
        self.assertNotEqual(outside.returncode, 0)
        self.assertIn(HELLO_FAILURE, outside.stderr)

    def test_a_project_whose_hooks_directory_holds_its_hooks_is_not_changed(self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        hook = write(root, ".git/hooks/pre-commit", "#!/bin/sh\necho own hook\n")
        hook.chmod(0o755)
        plan_id = self.planned(root)
        before = (hook.read_bytes(), hook.stat().st_mtime_ns,
                  sorted(os.listdir(root / ".git/hooks")), hook_install.local_hooks_paths(root))
        self.succeed(root, plan_id)
        after = (hook.read_bytes(), hook.stat().st_mtime_ns,
                 sorted(os.listdir(root / ".git/hooks")), hook_install.local_hooks_paths(root))
        self.assertEqual(after, before)
        self.assertEqual(before[3], [])
        self.assertNotIn("hook_install", self.verification(plan_id))

    def test_a_repository_that_sets_its_own_hooks_path_is_left_alone(self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        git(root, "config", "core.hooksPath", ".githooks")
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        self.assertFalse((root / ".git/hooks/pre-commit").exists())
        self.assertEqual(hook_install.local_hooks_paths(root), [".githooks"])
        self.assertNotIn("hook_install", self.verification(plan_id))

    def test_the_install_leaves_no_local_hooks_path_for_the_commit_or_after_it(self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        lines = self.verification(plan_id)["commit_output"]["lines"]
        self.assertIn("dev-shell sees local hooks path: none", lines)
        code = subprocess.run(
            ["git", "-C", str(root), "config", "--local", "--get-all", "core.hooksPath"],
            check=False, capture_output=True).returncode
        self.assertEqual(code, 1)

    def test_only_the_install_command_has_the_global_hooks_path_masked(self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        lines = self.verification(plan_id)["commit_output"]["lines"]
        self.assertIn(f"dev-shell sees global hooks path: {self.managed}", lines)
        self.assertNotIn("dev-shell sees global hooks path: none", lines)

    def test_a_failed_install_that_wrote_a_hooks_path_is_retained_leaves_none_and_never_commits(
            self):
        root = declared_repo(self.home, commit_environment="dev-shell",
                             commands=broken_install("echo install broke >&2; exit 9"))
        plan_id = self.planned(root)
        base = git(root, "rev-parse", "HEAD").strip()
        payload = self.assert_retained(root, plan_id, base, "adopt.commit.failed")
        lines = payload["error"]["commit_output"]["lines"]
        self.assertEqual(
            lines[0], "the hook install through the commit environment command dev-shell exited 9")
        self.assertIn("install broke", lines)
        self.assertEqual(hook_install.local_hooks_paths(root), [])

    def test_an_install_that_times_out_after_writing_a_hooks_path_leaves_none(self):
        root = declared_repo(self.home, commit_environment="dev-shell",
                             commands=broken_install("sleep 30"))
        plan_id = self.planned(root)
        base = git(root, "rev-parse", "HEAD").strip()
        with mock.patch.object(adopt_apply, "ENVIRONMENT_TIMEOUT_SECONDS", 2):
            payload = self.assert_retained(root, plan_id, base, "adopt.commit.failed")
        self.assertEqual(
            payload["error"]["commit_output"]["lines"][0],
            "the hook install through the commit environment command dev-shell "
            "did not finish within 2 seconds")
        self.assertEqual(hook_install.local_hooks_paths(root), [])

    def test_a_hooks_path_the_install_cannot_remove_fails_the_install(self):
        root = declared_repo(self.home, commit_environment="dev-shell")
        plan_id = self.planned(root)
        base = git(root, "rev-parse", "HEAD").strip()
        real = adopt_inspection.run_git

        def refusing(repo, *args, **kwargs):
            if "--unset-all" in args and "core.hooksPath" in args:
                return 255, b""
            return real(repo, *args, **kwargs)

        with mock.patch.object(adopt_inspection, "run_git", refusing):
            payload = self.assert_retained(root, plan_id, base, "adopt.commit.failed")
        self.assertEqual(
            payload["error"]["commit_output"]["lines"][0],
            "the hook install left a hooks path in the repository's configuration "
            "that could not be removed")

    def test_without_a_commit_environment_nothing_is_installed(self):
        root = declared_repo(self.home)
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        self.assertFalse((root / ".git/hooks/pre-commit").exists())
        verification = self.verification(plan_id)
        self.assertNotIn("hook_install", verification)
        self.assertIn("commit_output", verification)

    def test_a_dev_shell_that_declares_no_git_hooks_is_not_entered_for_an_install(self):
        root = declared_repo(self.home, text=UNDECLARED, commit_environment="dev-shell")
        plan_id = self.planned(root)
        self.succeed(root, plan_id)
        self.assertFalse((root / ".git/hooks/pre-commit").exists())
        self.assertNotIn("hook_install", self.verification(plan_id))


class HookInstallRuleTest(unittest.TestCase):
    def test_installed_names_only_executable_commit_hooks(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory, True)
        for name, mode in (("pre-commit", 0o755), ("commit-msg", 0o644), ("post-commit", 0o755)):
            path = directory / name
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(mode)
        self.assertEqual(hook_install.installed(directory), ["pre-commit"])
        self.assertEqual(hook_install.installed(directory / "missing"), [])
        empty = directory / "empty"
        empty.mkdir()
        self.assertTrue(hook_install.left_alone(None, directory))
        self.assertTrue(hook_install.left_alone(".githooks", empty))
        self.assertFalse(hook_install.left_alone(None, empty))
        self.assertTrue(stat.S_IMODE((directory / "pre-commit").stat().st_mode) & 0o100)

    def test_declares_hooks_reads_a_devenv_git_hooks_setting(self):
        for text in ("{\n  git-hooks.hooks.x.enable = true;\n}", "git-hooks = {",
                     "  pre-commit.hooks.y.enable = true;",
                     "{ ... }: { git-hooks.hooks.shellcheck.enable = true; }",
                     "{ git-hooks = { hooks.x.enable = true; }; }",
                     "{ git-hooks.hooks.x.enable = false; git-hooks.hooks.y.enable = true; }",
                     "/* c */ { git-hooks.hooks.x.enable = true; }",
                     "{ pkgs, ... }:\n{\n  scripts.clean.exec = \"rm -rf build/*\";\n"
                     "  git-hooks.hooks.shellcheck.enable = true;\n  /* formatting */\n"
                     "  languages.nix.enable = true;\n}\n",
                     '{ ... }: { env.U = "http://x/#a"; git-hooks.hooks.x.enable = true; }',
                     "{ s = ''\n  echo # not a comment /*\n  ''${x}\n''; git-hooks.hooks.x.enable = true; /* a */ }",
                     '{ s = "a ${"b /*" + c} d"; git-hooks.hooks.x.enable = true; /* a */ }',
                     "{ git-hooks.hooks.x = { enable = false; }; git-hooks.hooks.y = { enable = true; }; }",
                     "{ git-hooks.hooks.x = { entry = \"a\"; }; }",
                     "{ ... }: { config.git-hooks.hooks.shellcheck.enable = true; }",
                     "{ config.git-hooks = { hooks.x.enable = true; }; }",
                     "{ pkgs, ... }: let pre-commit = pkgs.pre-commit; in { packages = [ pre-commit ]; "
                     "git-hooks.hooks.x.enable = true; }",
                     "{ git-hooks.hooks.a.enable = false; git-hooks.hooks.a.entry = \"t\"; "
                     "git-hooks.hooks.b.entry = \"t\"; }",
                     "let h = { hooks.x.enable = true; }; in { git-hooks = h; }",
                     "let cfg = { hooks.x.enable = true; }; in { pre-commit = cfg; }",
                     "let git-hooks = { hooks.x.enable = true; }; in { inherit git-hooks; }",
                     "let git-hooks = import ./hooks.nix { inherit pkgs; }; in { inherit git-hooks; }",
                     "let git-hooks.hooks.shellcheck.enable = true; in { inherit git-hooks; }",
                     "let pre-commit.hooks.x = { enable = true; }; in { config = { inherit pre-commit; }; }",
                     "{ pkgs, ... }: { inherit pkgs git-hooks; }",
                     "{ cfg, ... }: { inherit (cfg) git-hooks; }",
                     "{ git-hooks.hooks.${name}.enable = true; }"):
            self.assertTrue(hook_install.declares_hooks(text), text)
        for text in ("# git-hooks.hooks.x", 'scripts.a.exec = "pre-commit run";', "{ }",
                     "{\n  git-hooks.hooks.shellcheck.enable = false;\n}",
                     "  git-hooks.hooks.shellcheck.enable = false;",
                     "{ pre-commit.hooks.x.enable =\n false; }",
                     "{ config.git-hooks.hooks.x.enable = false; }",
                     "{ packages = [ config.git-hooks.package ]; }",
                     "{ pkgs, ... }: let pre-commit = pkgs.pre-commit; in { packages = [ pre-commit ]; }",
                     "{ pkgs, ... }: let pre-commit = pkgs.pre-commit; in { packages = [ pre-commit.out ]; }",
                     "let pre-commit = pkgs.callPackage ./pc.nix { }; in { packages = [ pre-commit ]; }",
                     "let pre-commit = pkgs.pre-commit.override { x = 1; }; in { packages = [ pre-commit ]; }",
                     "{ pkgs, ... }: let inherit (pkgs) pre-commit; in { packages = [ pre-commit.out ]; }",
                     "{ pkgs, ... }: { packages = with pkgs; [ pre-commit.out ]; }",
                     "{ pkgs, ... }: { packages = [ pkgs.pre-commit ]; env.X = pre-commit.out; }",
                     "let git-hooks.hooks.x.enable = true; in { }",
                     "let git-hooks = { hooks.x.enable = false; }; in { inherit git-hooks; }",
                     "let git-hooks = import ./h.nix { }; in { packages = [ git-hooks.package ]; }",
                     "{ git-hooks.hooks.check.enable = false; git-hooks.hooks.check.entry = \"true\"; }",
                     "{ git-hooks.hooks.check.entry = \"true\"; git-hooks.hooks.check.enable = false; }",
                     "{ git-hooks.hooks.check = { entry = \"a\"; }; git-hooks.hooks.check.enable = false; }",
                     "/* git-hooks.hooks.x.enable = true; */ { }",
                     "{\n  git-hooks.hooks.x = { enable = false; };\n}",
                     "{\n  git-hooks = { hooks.x.enable = false; };\n}",
                     "{ git-hooks = { hooks.x = { enable = false; entry = \"a\"; }; hooks.y.enable = false; }; }",
                     '{ s = "git-hooks.hooks.x.enable = true;"; t = "/*"; } /* c */',
                     "{ s = ''\n  git-hooks.hooks.x.enable = true;\n''; }"):
            self.assertFalse(hook_install.declares_hooks(text), text)


if __name__ == "__main__":
    unittest.main()
