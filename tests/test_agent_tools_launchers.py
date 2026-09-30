"""Installed-layout seam for the agent_tools launchers (#175 D8, D11; #179 D8; #177 D9; parent D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Every
`.agents/bin` entry that names the package, other than `NOT_LAUNCHERS`, must be a
generated launcher, and
each launcher must run its store module even with a fake `agent_tools` and a fake
top-level `agent_platform` on the
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
# Flat installed scripts that name the package without being launchers: only
# `workflow-state`, whose transitional lookups run `agent_tools.resolve_project`
# and import `agent_tools.host_admission` from source (#177 D6, D13). #178
# deletes this entry with them.
NOT_LAUNCHERS = ("workflow-state",)
# The commands #175, #179 and #177 accepted as launchers: a floor, not the full
# set, which the command table in lib/agent-tools.nix owns (#175 D8).
LAUNCHER_FLOOR = ("adopt-project", "agent-evidence", "agent-model-matrix", "conformance",
                  "context-map-lint", "diff-scope", "resolve-project", "review-package")
# Legacy commands may treat --help as misuse, including parser-backed commands
# with help disabled; pin each existing exit/stdout/stderr contract.
MISUSE_USAGE = {"context-map-lint": "Usage: context-map-lint --repo-root "}


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
        # A bare `import agent_platform` was the old resolver bootstrap's
        # adversary; a launcher must never reach this one (#177 D9).
        (self.hostile / "agent_platform.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )

    def launchers(self):
        """{command: (environment python, module)} for every entry naming the package."""
        found = {}
        for entry in sorted((self.root / ".agents" / "bin").iterdir()):
            data = entry.read_bytes()
            if entry.name in NOT_LAUNCHERS:
                self.assertIsNone(LAUNCHER.fullmatch(data),
                                  f"{entry} is a generated launcher; drop it from NOT_LAUNCHERS")
                continue
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

    def test_the_command_table_generates_each_deployed_command(self):
        launchers = self.launchers()
        for name in LAUNCHER_FLOOR:
            with self.subTest(launcher=name):
                self.assertIn(name, launchers)

    def test_each_launcher_is_named_for_its_module(self):
        for name, (_python, module) in self.launchers().items():
            with self.subTest(launcher=name):
                self.assertEqual(name, module.replace("_", "-"))

    def dependency_env(self):
        home = self.hostile / 'dependencies'
        bins = self.hostile / 'dependency-bin'
        if not home.exists():
            home.mkdir(); bins.mkdir()
            (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
            (bins / 'python3').symlink_to(self.launchers()['review-package'][0])
        return dict(os.environ, HOME=str(home),
                    PATH=str(bins) + os.pathsep + str(self.root / '.agents/bin')
                    + os.pathsep + os.environ['PATH'])

    def hostile_env(self):
        return dict(self.dependency_env(), PYTHONPATH=str(self.hostile),
                    NIX_PYTHONPATH=str(self.hostile))

    def test_a_hostile_agent_tools_on_every_channel_is_ignored(self):
        for name in self.launchers():
            with self.subTest(launcher=name):
                completed = self.run_child(
                    [str(self.root / '.agents/bin' / name), '--help'],
                    self.hostile_env(), self.hostile)
                if name == 'review-package':
                    self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                                     (2, '', 'review-package: invalid invocation\n'))
                elif name in MISUSE_USAGE:
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertEqual(completed.stdout, '')
                    self.assertIn(MISUSE_USAGE[name], completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertTrue(completed.stdout.startswith(f'usage: {name} '), completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_each_hostile_channel_is_live_without_the_launcher(self):
        # Each control opens exactly one channel, so a dead channel cannot hide
        # behind a live one.
        clean = {key: value for key, value in self.dependency_env().items()
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


    def test_relocated_actual_command_matches_source(self):
        import json
        import sys
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'actual-parity'
        top.mkdir()
        repo = top / 'repo'; repo.mkdir()
        home = top / 'home'; home.mkdir()
        (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
        env = {k: v for k, v in os.environ.items() if k not in
               ('PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        env.update(HOME=str(home), PYTHONPATH=str(source / 'python'),
                   PATH=self.dependency_env()['PATH'])
        def git(*args):
            result = subprocess.run(['git', *args], cwd=repo, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.decode().strip()
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test'); git('config', 'commit.gpgsign', 'false')
        (repo / 'value.txt').write_text('before\n')
        git('add', '-A'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
        (repo / 'value.txt').write_text('after\n')
        (repo / 'plan.md').write_text('# Plan\n\n## Task index\n\nTask 1 — Case — value.txt — full — '
                                    '[task-1.md](plan.tasks/task-1.md)\n')
        (repo / 'plan.tasks').mkdir(); (repo / 'plan.tasks/task-1.md').write_text('# Task 1\n')
        git('add', '-A'); git('commit', '-qm', 'change'); head = git('rev-parse', 'HEAD')
        roots = []
        for label in ('source', 'built'):
            out = top / label; out.mkdir(); root = out / 'review.json'; roots.append(root)
            childenv = dict(env)
            argv = [sys.executable, '-m', 'agent_tools.review_package']
            if label == 'built':
                argv = [str(self.root / '.agents/bin/review-package')]
                childenv.update(PYTHONPATH=str(self.hostile), NIX_PYTHONPATH=str(self.hostile))
            produced = subprocess.run([*argv, str(repo / 'plan.md'), base, head, str(root)],
                                      cwd=repo, env=childenv, capture_output=True)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            self.assertNotIn(MARKER.encode(), produced.stdout + produced.stderr)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json'], env=env, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(produced.stdout)['artifact']['metrics'],
                             json.loads(checked.stdout)['metrics'])
        self.assertEqual(roots[0].read_bytes(), roots[1].read_bytes())
        for member in roots[0].with_suffix('.shards').iterdir():
            self.assertEqual(member.read_bytes(), (roots[1].with_suffix('.shards') / member.name).read_bytes())

if __name__ == "__main__":
    unittest.main()
