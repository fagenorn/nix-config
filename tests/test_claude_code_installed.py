"""Installed seam for the generated Claude Code settings and launchers (issue 425 D6).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
generated settings artifact, found in ./result's closure as
`just show-claude-settings` finds it, as CLAUDE_SETTINGS_PATH, and the built
Claude Code package as CLAUDE_CODE_PACKAGE. Each launcher runs from that
package's bin against a stub binary named by CLAUDE_BIN, with HOME and the
working directory in a temporary directory and the calling session's account
variables removed.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INSTALLED_RECIPE = "just agent-installed-skill-tests"
SETTINGS_ENV = "CLAUDE_SETTINGS_PATH"
INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
GIT_HOOK_NAMES = (
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit",
    "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout",
    "post-merge", "pre-receive", "update", "proc-receive", "post-receive", "post-update",
    "pre-auto-gc", "post-rewrite", "sendemail-validate", "p4-changelist",
    "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit",
)
# Hidden from the model's skill listing while /<name> still runs it (issue 425 D1).
HIDDEN = "user-invocable-only"
EXPECTED_SKILL_OVERRIDES = {
    "artifact-design": HIDDEN,
    "artifact-diagramming": HIDDEN,
    "artifact-capabilities": HIDDEN,
    "dataviz": HIDDEN,
    "anthropic-skills:docx": HIDDEN,
    "anthropic-skills:pptx": HIDDEN,
    "anthropic-skills:xlsx": HIDDEN,
    "anthropic-skills:pdf": HIDDEN,
    "anthropic-skills:google-workspace": HIDDEN,
    "anthropic-skills:morning": HIDDEN,
    "anthropic-skills:import-memory": HIDDEN,
    "anthropic-skills:skill-creator": HIDDEN,
}
# The plugin's skill-creator is the copy kept listed (issue 425 D2).
EXPECTED_PLUGINS = {
    "skill-creator@claude-plugins-official": True,
    "codex@nix-codex": True,
}
PACKAGE_ENV = "CLAUDE_CODE_PACKAGE"
CONNECTORS = "ENABLE_CLAUDEAI_MCP_SERVERS"
# The calling session's account state, removed so it cannot steer a launch.
ACCOUNT_VARIABLES = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_ACCOUNT",
    "CLAUDE_ACCOUNTS_DIR",
    "CLAUDE_CODE_PLUGIN_DIRS",
    "CLAUDE_ACCOUNT_LAUNCHER",
)
TIMEOUT_SECONDS = 60
# Stands in for the real binary through CLAUDE_BIN and records what it was handed.
STUB = (
    "import json, os, sys\n"
    "with open(os.environ['CLAUDE_STUB_RECORD'], 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'argv': sys.argv[1:], 'env': dict(os.environ)}, handle)\n"
)


class ClaudeSettingsInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get(SETTINGS_ENV)
        if path is None:
            raise unittest.SkipTest(
                f"{SETTINGS_ENV} is unset; run `{INSTALLED_RECIPE}` to check "
                "the settings the Nix build generates"
            )
        cls.settings = json.loads(Path(path).read_text(encoding="utf-8"))

    def test_skill_overrides_hide_exactly_the_listed_skills(self):
        self.assertEqual(self.settings.get("skillOverrides"), EXPECTED_SKILL_OVERRIDES)

    def test_the_kept_skill_creator_is_the_plugin_copy(self):
        self.assertEqual(self.settings.get("enabledPlugins"), EXPECTED_PLUGINS)

    def test_commits_and_prs_carry_no_attribution(self):
        # Issue 619: no Co-Authored-By trailer, PR line or session link anywhere.
        self.assertEqual(self.settings.get("attribution"),
                         {"commit": "", "pr": "", "sessionUrl": False})
        self.assertNotIn("includeCoAuthoredBy", self.settings)


class ClaudeLaunchersInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = os.environ.get(PACKAGE_ENV)
        if package is None:
            raise unittest.SkipTest(
                f"{PACKAGE_ENV} is unset; run `{INSTALLED_RECIPE}` to check "
                "the launchers the Nix build installs"
            )
        cls.bin = Path(package) / "bin"

    def launch(self, name, extra_env):
        """Run `<package>/bin/<name> --version` against the stub; return what the stub saw."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        stub = root / "claude"
        stub.write_text(f"#!{sys.executable}\n{STUB}", encoding="utf-8")
        stub.chmod(0o755)
        record = root / "record.json"
        env = {key: value for key, value in os.environ.items()
               if key not in ACCOUNT_VARIABLES and key != CONNECTORS}
        env.update(HOME=str(root), CLAUDE_BIN=str(stub), CLAUDE_STUB_RECORD=str(record))
        env.update(extra_env)
        result = subprocess.run(
            [str(self.bin / name), "--version"], cwd=root, env=env,
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(record.read_text(encoding="utf-8"))

    def test_plain_claude_leaves_claude_ai_connectors_alone(self):
        seen = self.launch("claude", {})
        self.assertEqual(seen["argv"], ["--version"])
        self.assertNotIn(CONNECTORS, seen["env"])

    def test_only_the_two_launchers_are_installed(self):
        names = {"claude", "claude-account", "claude-" "orchestrate"}
        self.assertEqual({p.name for p in self.bin.iterdir()} & names, {"claude", "claude-account"})


class LauncherSourceTest(unittest.TestCase):
    def test_the_module_writes_no_orchestration_launcher(self):
        text = (Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix").read_text(encoding="utf-8")
        self.assertNotIn("claude-" "orchestrate", text)
        self.assertNotIn("ENABLE_CLAUDEAI_MCP_SERVERS", text)


class GitHooksInstalledTest(unittest.TestCase):
    """Issue 672: the generated global git config points core.hooksPath at the managed
    hooks, whose pre-push runs the guard on the very policy inputs of the PreToolUse hook."""

    @classmethod
    def setUpClass(cls):
        if INSTALLED_HOME_ENV not in os.environ or SETTINGS_ENV not in os.environ:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} or {SETTINGS_ENV} is unset; run "
                f"`{INSTALLED_RECIPE}` to check the hooks the Nix build installs"
            )
        home = Path(os.environ[INSTALLED_HOME_ENV])
        config = subprocess.run(
            ["git", "config", "--file", str(home / ".config/git/config"), "core.hooksPath"],
            capture_output=True, text=True, check=True)
        cls.hooks = Path(config.stdout.strip())
        settings = json.loads(Path(os.environ[SETTINGS_ENV]).read_text(encoding="utf-8"))
        guards = [hook["command"] for entry in settings["hooks"]["PreToolUse"]
                  for hook in entry["hooks"]
                  if hook.get("command", "").endswith("/bin/claude-bash-lifecycle-guard")]
        cls.guard_wrapper = Path(guards[0]).read_text(encoding="utf-8")

    def test_hooks_path_is_the_managed_store_directory(self):
        self.assertTrue(str(self.hooks).startswith("/nix/store/"), self.hooks)
        self.assertTrue(self.hooks.name.endswith("-agent-git-hooks"), self.hooks)
        self.assertEqual(sorted(p.name for p in self.hooks.iterdir()),
                         sorted((*GIT_HOOK_NAMES, "pre-push")))
        for path in self.hooks.iterdir():
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_pre_push_reads_the_same_policy_as_the_pretooluse_guard(self):
        pre_push = (self.hooks / "pre-push").read_text(encoding="utf-8")
        exec_line = next(l for l in pre_push.splitlines() if l.startswith("exec "))
        guard_line = next(l for l in self.guard_wrapper.splitlines() if l.startswith("exec "))
        self.assertTrue(exec_line.startswith(guard_line.removesuffix(' "$@"')
                                             + " --mode pre-push "), exec_line)
        self.assertTrue(exec_line.endswith(' -- "$@"'), exec_line)

    def test_the_shims_serve_git_lfs(self):
        shim = (self.hooks / "post-commit").read_text(encoding="utf-8")
        self.assertRegex(shim, r"lfs='/nix/store/[^']+/bin/git-lfs'")
        self.assertIn("--git-lfs-bin /nix/store/",
                      (self.hooks / "pre-push").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
