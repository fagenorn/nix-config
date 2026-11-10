"""Installed-layout seam for the agent_tools launchers (#175 D8, D11; #179 D8; #177 D9; parent D9).

Run: just agent-installed-skill-tests. The installed and retained recipes build
first and pass AGENT_SKILLS_INSTALLED_HOME and AGENT_TOOLS_SYSTEM_RESULT. The
system closure must hold one package build, with every agent-tools launcher
execing one environment that imports that build. Every installed `.agents/bin`
entry that names the package must be a generated launcher. Each launcher must run its store module even with a fake `agent_tools`
and a fake top-level `agent_platform` on the `PYTHONPATH`, `NIX_PYTHONPATH` (with
a `.pth` file) and working-directory channels.
"""

import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
SYSTEM_RESULT_ENV = "AGENT_TOOLS_SYSTEM_RESULT"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
PACKAGE_BYTES = b"agent_tools"
# `launcherScript` (lib/agent-tools.nix) writes a `-p` shebang line, then the body and a newline.
LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I -m agent_tools\.(?P<module>[a-z][a-z0-9_]*) "\$@"\n*'
)
MARKER = "HOSTILE agent_tools IMPORTED"
HOSTILE_EXIT = 97
TIMEOUT_SECONDS = 60
# The commands #175, #179, #177, #249, #264, #279, #353, #403, #424, #623, #624 and #697 accepted as launchers: a floor, not the
# full set, which the command table in lib/agent-tools.nix owns (#175 D8).
LAUNCHER_FLOOR = ("adopt-project", "agent-model-matrix", "artifact-budget", "conformance",
                  "context-map-lint", "diff-scope", "forge-claim", "forge-issue", "lane-triage",
                  "owner-actions", "resolve-project")
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

    def system_closure(self) -> list[Path]:
        value = os.environ.get(SYSTEM_RESULT_ENV)
        self.assertIsNotNone(value, f"{SYSTEM_RESULT_ENV}={value!r} is unset")
        result = Path(value)
        self.assertTrue(result.is_absolute() and result.exists(),
                        f"{SYSTEM_RESULT_ENV}={value!r} is not an existing absolute path")
        done = subprocess.run(["nix-store", "--query", "--requisites", str(result)],
                              capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                              check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        paths = sorted(Path(line) for line in done.stdout.splitlines() if line)
        self.assertTrue(paths, f"{SYSTEM_RESULT_ENV}={value!r} has an empty closure")
        return paths

    def package_builds(self) -> set[Path]:
        with (Path(__file__).resolve().parents[1] / "python/pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
        package = re.compile(r"[0-9a-z]{32}-python[^-]+-"
                             + re.escape(project["name"]) + "-" + re.escape(project["version"]))
        return {path for path in self.system_closure() if package.fullmatch(path.name)}

    def closure_launchers(self) -> list[tuple[Path, str]]:
        launchers = []
        for path in self.system_closure():
            if not re.fullmatch(r"[0-9a-z]{32}-agent-tools-.+", path.name):
                continue
            self.assertTrue(path.is_file(), f"{path} is not a launcher file")
            data = path.read_bytes()
            match = LAUNCHER.fullmatch(data)
            self.assertIsNotNone(match, f"{path} is not a recognized agent-tools launcher")
            launchers.append((path, match["python"].decode()))
        return launchers

    def test_the_system_closure_holds_one_agent_tools_build(self):
        builds = self.package_builds()
        self.assertEqual(len(builds), 1, f"agent_tools builds: {sorted(map(str, builds))}")

    def test_every_launcher_in_the_system_closure_execs_one_environment(self):
        launchers = self.closure_launchers()
        self.assertTrue(launchers, "the system closure has no agent-tools launchers")
        pythons = {python for _path, python in launchers}
        self.assertEqual(len(pythons), 1,
                         f"launcher environments: {sorted(pythons)}; "
                         f"launchers: {[str(path) for path, _python in launchers]}")
        paths = {path.resolve() for path, _python in launchers}
        for entry in sorted((self.root / ".agents/bin").iterdir()):
            if PACKAGE_BYTES in entry.read_bytes():
                with self.subTest(entry=str(entry)):
                    self.assertIn(entry.resolve(), paths,
                                  f"{entry} -> {entry.resolve()} is outside closure launchers")

    def test_each_system_closure_environment_imports_agent_tools_from_the_closure_build(self):
        builds = self.package_builds()
        self.assertEqual(len(builds), 1, f"agent_tools builds: {sorted(map(str, builds))}")
        build, = builds
        pythons = {python for _path, python in self.closure_launchers()}
        self.assertTrue(pythons, "the system closure has no agent-tools environments")
        clean = {key: value for key, value in os.environ.items() if key not in
                 ("NIX_PYTHONPATH", "NIX_PYTHONPREFIX", "NIX_PYTHONEXECUTABLE")}
        for python in sorted(pythons):
            with self.subTest(python=python):
                done = self.run_child(
                    [python, "-I", "-c", "import agent_tools; print(agent_tools.__file__)"],
                    clean, self.hostile)
                self.assertEqual(done.returncode, 0, done.stderr)
                imported = Path(done.stdout.strip()).resolve()
                self.assertIn(build, imported.parents,
                              f"{python} imports {imported}, outside {build}")

    def test_the_command_table_generates_each_deployed_command(self):
        launchers = self.launchers()
        for name in LAUNCHER_FLOOR:
            with self.subTest(launcher=name):
                self.assertIn(name, launchers)

    def test_the_installed_home_holds_no_module_library(self):
        # Issue 689: every helper runs from the store; nothing is imported from ~/.agents/lib.
        library = self.root / ".agents/lib"
        self.assertFalse(library.exists(), sorted(str(p) for p in library.rglob("*")))

    def test_artifact_budget_runs_the_installed_policy_from_its_launcher(self):
        entry = self.root / ".agents/bin/artifact-budget"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "handoff.md"
            root.write_text("# Handoff\n", encoding="utf-8")
            env = dict(self.hostile_env(), HOME=str(self.root))
            checked = self.run_child([str(entry), "check", "--kind", "handoff", "--root", str(root),
                                      "--format", "json"], env, self.hostile)
            report = subprocess.run([str(entry), "validate-report", "--boundary", "producer",
                                     "--input", "-"], env=env, cwd=self.hostile,
                                    input='{"state":"failed","artifact":null,"notes":"installed"}',
                                    capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "within_budget")
        self.assertEqual((report.returncode, report.stderr), (0, ""))
        self.assertEqual(json.loads(report.stdout),
                         {"state": "failed", "artifact": None, "notes": "installed"})
        for done in (checked, report):
            self.assertNotIn(MARKER, done.stdout + done.stderr)

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
            (bins / 'python3').symlink_to(self.launchers()['resolve-project'][0])
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
                if name in MISUSE_USAGE:
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


if __name__ == "__main__":
    unittest.main()
