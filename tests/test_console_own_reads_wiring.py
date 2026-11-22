"""The own-read rule's wiring: the manager's settings and its prompt hook (#1620, ADR-console-103).

`tests/test_console_own_reads.py` asks the rule directly. Here the rule is reached the way a manager
reaches it: through the settings file `run_launch` writes (the root it carries and its own
`PermissionRequest` hook command, run by `/bin/sh` against the source `sprint` entry point), through
`sprint.run_prompt`, and in order with the `PreToolUse` judge that runs before it.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agent_tools.console import manager, own_reads, permit, prompt_card
from agent_tools.console import sprint

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TIER = "fast"  # source tree and standard library only

SID = "a" * 16
ALLOW = prompt_card.hook_output("allow") + "\n"
REFUSED = prompt_card.hook_output("deny", manager.REFUSAL) + "\n"


class Tree(unittest.TestCase):
    """A resolved temporary tree: the project root, a sibling directory, the session's saved output, a secret."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp_path = Path(tmp.name).resolve()
        self.root = root = tmp_path / "proj"
        root.mkdir()
        (root / "README.md").write_text("hello\n")
        self.sibling = tmp_path / "sibling"
        self.sibling.mkdir()
        (self.sibling / "note.txt").write_text("no\n")
        self.results = tmp_path / "profile" / "projects" / "-srv-proj" / "s-1" / "tool-results"
        self.results.mkdir(parents=True)
        (self.results / "b1.txt").write_text("saved\n")
        self.secret = tmp_path / "secret" / "id"
        self.secret.parent.mkdir()
        self.secret.write_text("key\n")
        self.env = {"HOME": str(tmp_path / "home"), "CLAUDE_ACCOUNTS_DIR": str(tmp_path / "accounts"),
                    "CLAUDE_CONFIG_DIR": str(tmp_path / "profile")}


class SettingsTest(Tree):
    """What `run_launch` writes for a manager carries its root, and its own hook command reads it."""

    def launched_settings(self):
        directory = self.tmp / "settings"
        launch = manager.new_launch(SID, "owner/p01", "make it resumable", str(self.root), "work",
                                    "s3cret", directory)

        def run(argv, **kwargs):
            kwargs["stderr"].write(b"")
            return subprocess.CompletedProcess(argv, 0)

        manager.run_launch(launch, platform="linux", run=run,
                           environ={"PATH": "/p", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/x"})
        return json.loads(launch.settings.read_text())

    def test_the_settings_carry_the_root_the_prompt_hook_reads(self):
        settings = self.launched_settings()
        self.assertEqual(settings["env"][manager.ROOT_ENV], str(self.root))
        [hook] = settings["hooks"]["PermissionRequest"][0]["hooks"]
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stand_in = bin_dir / "sprint"
        stand_in.write_text(f'#!/bin/sh\nexec {sys.executable} -m agent_tools.console.sprint "$@"\n')
        stand_in.chmod(0o755)
        env = {key: value for key, value in settings["env"].items()
               if key not in (manager.ID_ENV, manager.SECRET_ENV)}
        env.update(self.env, PATH=f"{bin_dir}:/usr/bin:/bin",
                   PYTHONPATH=str(Path(sprint.__file__).resolve().parents[2]))

        def run(command, cwd):
            stdin = json.dumps({"session_id": "s-1", "cwd": str(cwd), "tool_name": "Bash",
                                "tool_input": {"command": command}})
            return subprocess.run(["/bin/sh", "-c", hook["command"]], input=stdin,
                                  capture_output=True, text=True, env=env).stdout

        # The hook trusts the root the settings carry, never the `cwd` the session reports: from a
        # sibling directory an absolute read of the project passes and a relative read of the sibling
        # does not.
        self.assertEqual(run(f"cat {self.root}/README.md", self.sibling), ALLOW)
        self.assertEqual(run("cat README.md", self.root), ALLOW)
        for command in ("cat note.txt", f"cat {self.secret}"):
            with self.subTest(command):
                decision = json.loads(run(command, self.sibling))["hookSpecificOutput"]["decision"]
                self.assertEqual(decision["behavior"], "deny")

    def test_an_inherited_root_never_reaches_the_client(self):
        launch = manager.new_launch(SID, "owner/p01", "make it resumable", str(self.root), "work",
                                    "s3cret", self.tmp / "settings")
        calls = []

        def run(argv, **kwargs):
            calls.append(kwargs)
            kwargs["stderr"].write(b"")
            return subprocess.CompletedProcess(argv, 0)

        manager.run_launch(launch, platform="linux", run=run, environ={
            "PATH": "/p", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/x", manager.ROOT_ENV: "/elsewhere"})
        self.assertNotIn(manager.ROOT_ENV, calls[0]["env"])


class PromptTest(Tree):
    """`sprint.run_prompt` allows an own read with no request and sends every other command to the console."""

    def run_prompt(self, command, cwd, env, **tool):
        """The exit code, the printed text and the requests sent to the console (each answered Refused)."""
        sent, out = [], StringIO()

        def fake(port, method, path, body=None, headers=None):
            sent.append(json.loads(body)["phase"])
            raise sprint.Refused("sprint: console unreachable")

        stdin = json.dumps({"session_id": "s-1", "tool_name": "Bash", "tool_input": {"command": command, **tool},
                            **({} if cwd is None else {"cwd": str(cwd)})})
        with mock.patch.object(sprint, "ask", side_effect=fake), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sys, "stdin", StringIO(stdin)), redirect_stdout(out):
            code = sprint.run_prompt(sprint.build_parser().parse_args(["permit", "--prompt"]))
        return code, out.getvalue(), sent

    def environment(self, **change):
        return {**self.env, manager.ID_ENV: SID, manager.SECRET_ENV: "secret",
                manager.ROOT_ENV: str(self.root), **change}

    def test_an_own_read_is_allowed_without_a_card(self):
        env = self.environment()
        for command in (f"sed -n 1,5p {self.results}/b1.txt", "cat README.md"):
            with self.subTest(command):
                self.assertEqual(self.run_prompt(command, self.root, env), (0, ALLOW, []))
        without_root = {key: value for key, value in env.items() if key != manager.ROOT_ENV}
        for label, command, environ, cwd in (
                ("outside", f"cat {self.secret}", env, self.root),
                ("pipe", "cat README.md | head", env, self.root),
                ("no root", "cat README.md", without_root, self.root),
                ("no cwd", "cat README.md", env, None)):
            with self.subTest(label):
                self.assertEqual(self.run_prompt(command, cwd, environ), (0, REFUSED, ["ask"]))

    def test_an_own_read_that_asks_to_leave_the_sandbox_is_still_refused(self):
        refusal = prompt_card.hook_output("deny", prompt_card.SANDBOX_TEXT) + "\n"
        for flag in (True, "yes", 0):
            with self.subTest(flag):
                self.assertEqual(
                    self.run_prompt(f"sed -n 1,5p {self.results}/b1.txt", self.root, self.environment(),
                                    dangerouslyDisableSandbox=flag), (0, refusal, []))


class JudgeOrderTest(Tree):
    """A read that quotes a merge is judged by `sprint permit` first, whatever the own-read rule says."""

    def test_a_read_quoting_a_merge_is_denied_before_the_own_read_hook_runs(self):
        (self.root / "README.md").write_text("gh pr merge 7\n")
        command = "grep 'gh pr merge' README.md"
        grant = permit.Grant(slug="o/r", root=str(self.root), strategy="merge", delete_branch=True,
                             branch_pattern="issue-<num>-<slug>", issues=frozenset({12}),
                             others=frozenset())

        def unread(*_):
            raise AssertionError("the judge read the forge for a command that is no merge of ours")

        # The `PreToolUse` hook consults the console for any command that mentions a merge, and the
        # judge denies this one; the card-less allow sits in the later `PermissionRequest` hook, so the
        # rule alone would admit the read but never gets to run.
        self.assertTrue(permit.mentions(command))
        self.assertEqual(permit.judge(command, grant, permit.Forge(unread, unread, unread)).decision,
                         permit.DENY)
        self.assertTrue(own_reads.allowed(command, str(self.root), "s-1", str(self.root), (), {}))


if __name__ == "__main__":
    unittest.main()
