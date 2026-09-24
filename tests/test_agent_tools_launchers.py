"""Installed-layout seam for the agent_tools launchers (#175 D8, D11; parent D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Every
`.agents/bin` entry that names the package must be a generated launcher, and
each launcher must run its store module even with a fake `agent_tools` on the
`PYTHONPATH`, `NIX_PYTHONPATH` (with a `.pth` file) and working-directory
channels.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
PACKAGE_BYTES = b"agent_tools"
# `writeShellScript` prepends the shebang and appends a newline to the body.
LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I -m agent_tools\.(?P<module>[a-z][a-z0-9_]*) "\$@"\n*'
)
MARKER = "HOSTILE agent_tools IMPORTED"
HOSTILE_EXIT = 97
TIMEOUT_SECONDS = 60


class AgentToolsLauncherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the launchers the Nix build installs"
            )
        cls.root = Path(root)

    def setUp(self):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.hostile = Path(scratch.name).resolve()
        package = self.hostile / "agent_tools"
        package.mkdir()
        (package / "__init__.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )
        # A site directory's .pth `import` line runs at startup, so this puts
        # the fake package ahead of the environment's site-packages.
        (self.hostile / "hostile.pth").write_text(
            f"import sys; sys.path.insert(0, {str(self.hostile)!r})\n",
            encoding="utf-8",
        )

    def launchers(self):
        """{command: (environment python, module)} for every entry naming the package."""
        found = {}
        for entry in sorted((self.root / ".agents" / "bin").iterdir()):
            data = entry.read_bytes()
            if PACKAGE_BYTES not in data:
                continue
            match = LAUNCHER.fullmatch(data)
            self.assertIsNotNone(
                match, f"{entry} names agent_tools but is not a generated launcher")
            found[entry.name] = (match["python"].decode(), match["module"].decode())
        return found

    def run_child(self, argv, env, cwd):
        return subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, check=False)

    def hostile_env(self):
        return dict(os.environ, PYTHONPATH=str(self.hostile),
                    NIX_PYTHONPATH=str(self.hostile))

    def test_the_command_table_generates_agent_evidence(self):
        self.assertIn("agent-evidence", self.launchers())

    def test_each_launcher_is_named_for_its_module(self):
        for name, (_python, module) in self.launchers().items():
            with self.subTest(launcher=name):
                self.assertEqual(name, module.replace("_", "-"))

    def test_a_hostile_agent_tools_on_every_channel_is_ignored(self):
        for name in self.launchers():
            with self.subTest(launcher=name):
                completed = self.run_child(
                    [str(self.root / ".agents" / "bin" / name), "--help"],
                    self.hostile_env(), self.hostile)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.startswith(f"usage: {name} "),
                                completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_each_hostile_channel_is_live_without_the_launcher(self):
        # Each control opens exactly one channel, so a dead channel cannot hide
        # behind a live one.
        clean = {key: value for key, value in os.environ.items()
                 if key not in ("PYTHONPATH", "NIX_PYTHONPATH")}
        pythonpath_only = dict(clean, PYTHONPATH=str(self.hostile))
        nix_only = dict(clean, NIX_PYTHONPATH=str(self.hostile))
        for name, (python, module) in self.launchers().items():
            plain = [python, "-m", f"agent_tools.{module}", "--help"]
            controls = {
                # (a) PYTHONPATH alone reaches a plain run.
                "not isolated, PYTHONPATH only": (plain, pythonpath_only, self.root),
                # (a') the working directory alone reaches a plain run.
                "not isolated, working directory only": (plain, clean, self.hostile),
                # (b) -I alone leaves NIX_PYTHONPATH open, so the unset line
                # is load-bearing; if nixpkgs stops honouring it, this control
                # and that line go together (D11).
                "isolated, NIX_PYTHONPATH only": (
                    [python, "-I", "-m", f"agent_tools.{module}", "--help"],
                    nix_only, self.root),
            }
            for control, (argv, env, cwd) in controls.items():
                with self.subTest(launcher=name, control=control):
                    completed = self.run_child(argv, env, cwd)
                    self.assertEqual(completed.returncode, HOSTILE_EXIT, completed.stderr)
                    self.assertIn(MARKER, completed.stderr)


if __name__ == "__main__":
    unittest.main()
