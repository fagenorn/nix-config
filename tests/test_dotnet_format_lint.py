"""The `dotnet-format-lint` command (ADR-delivery-012).

`python -m agent_tools.delivery.dotnet_format_lint --root <root>` checks that the
C# under `<root>/dotnet` is formatted. These tests run it as a child against stub
`nix` and `dotnet` programs written per row, so no SDK is needed: they pin what the
command finds, what it starts, with which argv and environment, and how each
outcome maps to its exit.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery.dotnet_format_lint import format_argv

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERPRETER_KEYS = frozenset({"LC_CTYPE", "__CF_USER_TEXT_ENCODING"})
FIXED_ENV = {
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    "MSBUILDDISABLENODEREUSE": "1",
    "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
    "LANG": "C",
}
NO_SOURCES = "dotnet-format-lint: no .NET sources under dotnet/"
SLNX = '<Solution>\n  <Project Path="A/A.csproj" />\n</Solution>\n'
SLN = ('Microsoft Visual Studio Solution File, Format Version 12.00\n'
       'Project("{9A19103F-16F7-4668-BE54-9A1E7A4F7556}") = "A", "A\\A.csproj",'
       ' "{11111111-1111-1111-1111-111111111111}"\nEndProject\n')
SLN_FOLDER = ('Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "src", "src",'
              ' "{22222222-2222-2222-2222-222222222222}"\nEndProject\n')


def stub_text(log: Path, code: int, lines: list[str]) -> str:
    return (
        f"#!{sys.executable} -I\n"
        "import json, os, sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        "    f.write(json.dumps({'argv': sys.argv, 'env': dict(os.environ),"
        " 'cwd': os.getcwd()}) + '\\n')\n"
        f"for line in {lines!r}:\n"
        "    print(line)\n"
        f"sys.exit({code})\n")


def write_stub(path: Path, log: Path, code: int = 0, lines: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stub_text(log, code, lines or []), "utf-8")
    path.chmod(0o755)
    return path


def read_log(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text("utf-8").splitlines()]


class LintCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.base = Path(self._directory.name).resolve()
        self.root = self.base / "root"
        self.root.mkdir()
        self.stubs = self.base / "stubs"
        self.stubs.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.temp = self.base / "temp"
        self.temp.mkdir()
        self.nix_log = self.base / "nix.log"
        self.dotnet_log = self.base / "dotnet.log"

    def file(self, relative: str, text: str = "x\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        return path

    def outside(self, relative: str, text: str = "x\n") -> Path:
        path = self.base / "outside" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        return path

    def tools(self, with_dotnet: bool = True, code: int = 0) -> Path:
        out = self.base / "tools-out"
        (out / "bin").mkdir(parents=True, exist_ok=True)
        if with_dotnet:
            write_stub(out / "bin" / "dotnet", self.dotnet_log, code)
        return out

    def nix(self, code: int = 0, lines: list[str] | None = None) -> None:
        write_stub(self.stubs / "nix", self.nix_log, code, lines)

    def run_lint(self, root: str | Path | None = None, temp: bool = True):
        for log in (self.nix_log, self.dotnet_log):
            log.unlink(missing_ok=True)
        env = {
            "PATH": f"{self.stubs}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "PYTHONPATH": str(REPO_ROOT / "python"),
            "DOTNET_FORMAT_LINT_LEAK": "1",
        }
        if temp:
            env["TMPDIR"] = str(self.temp)
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.dotnet_format_lint",
             "--root", str(self.root if root is None else root)],
            env=env, capture_output=True, text=True, timeout=60)

    def planted(self) -> Path:
        self.file("dotnet/A/A.cs")
        self.file("dotnet/A/A.csproj")
        return self.file("dotnet/One.slnx", SLNX)


class NoSourcesTest(LintCase):
    def test_no_dotnet_sources_passes_without_starting_a_child(self):
        def readme():
            self.file("dotnet/README.md")

        def only_ignored():
            self.file("dotnet/X/obj/A.cs")
            self.file("dotnet/X/bin/B.cs")

        def linked_root():
            self.outside("dotnet/A/A.cs")
            self.outside("dotnet/A.slnx")
            os.symlink(self.base / "outside" / "dotnet", self.root / "dotnet")

        def linked_file():
            real = self.outside("Real.cs")
            (self.root / "dotnet").mkdir()
            os.symlink(real, self.root / "dotnet" / "Linked.cs")

        def linked_directory():
            self.outside("dir/A.cs")
            (self.root / "dotnet").mkdir()
            os.symlink(self.base / "outside" / "dir", self.root / "dotnet" / "Linked")

        def fifo():
            (self.root / "dotnet").mkdir()
            os.mkfifo(self.root / "dotnet" / "A.cs")

        rows = {"no dotnet": lambda: None, "readme": readme, "ignored": only_ignored,
                "linked root": linked_root, "linked file": linked_file,
                "linked directory": linked_directory, "fifo": fifo}
        for name, arrange in rows.items():
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                arrange()
                self.nix()
                result = self.run_lint()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [NO_SOURCES])
                self.assertEqual(read_log(self.nix_log), [])
                self.assertEqual(read_log(self.dotnet_log), [])


class SolutionTest(LintCase):
    def test_sources_without_exactly_one_solution_fail_before_any_child(self):
        def alone():
            self.file("dotnet/A/A.cs")

        def linked_solution():
            self.file("dotnet/A/A.cs")
            os.symlink(self.outside("Real.slnx"), self.root / "dotnet" / "Linked.slnx")

        def two():
            self.file("dotnet/A/A.cs")
            self.file("dotnet/One.slnx")
            self.file("dotnet/Two.sln")

        rows = [("alone", alone, "no_solution"), ("linked", linked_solution, "no_solution"),
                ("two", two, "several_solutions")]
        for name, arrange, reason in rows:
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                arrange()
                self.nix()
                result = self.run_lint()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stderr.splitlines(), [f"dotnet-format-lint: {reason}"])
                self.assertEqual(read_log(self.nix_log), [])


class ProjectsTest(LintCase):
    def test_sources_outside_the_solution_fail_before_any_child(self):
        def unregistered_project():
            self.planted()
            self.file("dotnet/NewArea/NewArea.csproj")
            self.file("dotnet/NewArea/Bad.cs")

        def loose_source():
            self.planted()
            self.file("dotnet/Loose/Bad.cs")

        def project_without_a_listing():
            self.file("dotnet/A/A.cs")
            self.file("dotnet/A/A.csproj")
            self.file("dotnet/One.slnx", "<Solution />\n")

        def broken_solution():
            self.planted()
            self.file("dotnet/One.slnx", "<Solution>")

        def sln_with_a_solution_folder():
            self.file("dotnet/A/A.cs")
            self.file("dotnet/A/A.csproj")
            self.file("dotnet/Loose/Bad.cs")
            self.file("dotnet/One.sln", SLN + SLN_FOLDER)

        rows = [
            ("sln folder", sln_with_a_solution_folder, "dotnet/Loose/Bad.cs"),
            ("unregistered", unregistered_project,
             "dotnet/NewArea/Bad.cs, dotnet/NewArea/NewArea.csproj"),
            ("loose", loose_source, "dotnet/Loose/Bad.cs"),
            ("unlisted", project_without_a_listing, "dotnet/A/A.cs, dotnet/A/A.csproj"),
            ("broken", broken_solution, "dotnet/A/A.cs, dotnet/A/A.csproj")]
        for name, arrange, listed in rows:
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                arrange()
                self.nix(0, [str(self.tools())])
                result = self.run_lint()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stderr.splitlines(), [
                    f"dotnet-format-lint: projects_outside_solution ({listed})"])
                self.assertEqual(read_log(self.nix_log), [])
                self.assertEqual(read_log(self.dotnet_log), [])

    def test_sources_inside_the_solution_reach_the_formatter(self):
        def slnx_nested():
            self.planted()
            self.file("dotnet/A/Deep/B.cs")

        def sln():
            self.file("dotnet/A/A.cs")
            self.file("dotnet/A/A.csproj")
            self.file("dotnet/One.sln", SLN)

        for name, arrange in {"slnx": slnx_nested, "sln": sln}.items():
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                arrange()
                self.nix(0, [str(self.tools())])
                result = self.run_lint()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ["dotnet-format-lint: passed"])
                self.assertEqual(len(read_log(self.dotnet_log)), 1)


class DiscoveryErrorTest(LintCase):
    def test_an_unreadable_dotnet_directory_fails_instead_of_finding_no_sources(self):
        self.planted()
        directory = self.root / "dotnet"
        directory.chmod(0)
        self.addCleanup(directory.chmod, 0o755)
        if os.access(directory, os.R_OK):
            self.skipTest("the caller can read a directory with no permissions")
        self.nix(0, [str(self.tools())])
        result = self.run_lint()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, "")
        (line,) = result.stderr.splitlines()
        self.assertTrue(line.startswith("dotnet-format-lint: discovery_failed ("), line)
        self.assertEqual(read_log(self.nix_log), [])


class ToolsTest(LintCase):
    def test_a_tools_build_that_gives_no_dotnet_is_tools_unavailable(self):
        self.planted()
        empty = self.tools(with_dotnet=False)
        rows = {"exit 1": (1, [str(empty)]), "two lines": (0, [str(empty), str(empty)]),
                "relative": (0, ["tools-out"]), "no dotnet": (0, [str(empty)])}
        for name, (code, lines) in rows.items():
            with self.subTest(name):
                self.nix(code, lines)
                result = self.run_lint()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stderr.splitlines(),
                                 ["dotnet-format-lint: tools_unavailable"])
                self.assertEqual(read_log(self.dotnet_log), [])


class RunTest(LintCase):
    def test_the_tools_build_and_the_format_run_have_their_exact_argv_and_env(self):
        slnx = self.planted()
        out = self.tools()
        for temp in (True, False):
            with self.subTest(temp=temp):
                self.nix(0, [str(out)])
                result = self.run_lint(temp=temp)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ["dotnet-format-lint: passed"])
                (nix,) = read_log(self.nix_log)
                self.assertEqual(Path(nix["argv"][0]).resolve(),
                                 (self.stubs / "nix").resolve())
                self.assertEqual(Path(nix["cwd"]).resolve(), self.root)
                self.assertEqual(nix["argv"][1:], [
                    "--extra-experimental-features", "nix-command flakes", "build",
                    "--no-link", "--print-out-paths", f"{self.root}#agent-platform.dotnet-tools"])
                self.assertEqual(format_argv(slnx),
                                 ["dotnet", "format", str(slnx), "--verify-no-changes"])
                (dotnet,) = read_log(self.dotnet_log)
                self.assertEqual(Path(dotnet["argv"][0]).resolve(),
                                 (out / "bin" / "dotnet").resolve())
                self.assertEqual(dotnet["argv"][1:],
                                 ["format", str(slnx), "--verify-no-changes"])
                self.assertEqual(Path(dotnet["cwd"]).resolve(), self.root / "dotnet")
                expected = {**FIXED_ENV, "PATH": f"{out}/bin", "HOME": str(self.home)}
                if temp:
                    expected["TMPDIR"] = str(self.temp)
                env = {k: v for k, v in dotnet["env"].items() if k not in INTERPRETER_KEYS}
                self.assertEqual(env, expected)

    def test_dotnet_exits_map_to_the_lint_exit(self):
        self.planted()
        out = self.tools()
        self.nix(0, [str(out)])
        rows = [(2, 1, "dotnet-format-lint: dotnet format would change files"),
                (3, 2, "dotnet-format-lint: dotnet_failed (exit 3)")]
        for dotnet_exit, expected, line in rows:
            with self.subTest(dotnet_exit):
                self.tools(code=dotnet_exit)
                result = self.run_lint()
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr.splitlines(), [line])


class RootTest(LintCase):
    def test_a_relative_or_missing_root_exits_2(self):
        for value in (".", str(self.base / "missing")):
            with self.subTest(value):
                result = self.run_lint(root=value)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.splitlines(), [
                    f"dotnet-format-lint: --root must be an absolute directory: {value}"])


if __name__ == "__main__":
    unittest.main()
