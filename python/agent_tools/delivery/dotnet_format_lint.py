"""The `dotnet-format` lint member: the .NET sources are formatted (ADR-delivery-012).

Usage: `python -m agent_tools.delivery.dotnet_format_lint --root <absolute directory>`

`just lint` runs this module as its last member (`agent_tools.delivery.verification_command`).
It reads the .NET sources under `<root>/dotnet` (`agent_tools.delivery.dotnet_solution`)
and runs `dotnet format <solution> --verify-no-changes` over the one solution there.

Discovery. A source is a regular file whose name ends `.cs`, `.csproj`, `.slnx` or
`.sln`, found without following a symlink and outside any directory named `bin` or
`obj`. When `<root>/dotnet` is itself linked, nothing under it is read. A linked
directory is not entered, and a linked file or a name that is not a regular file is not
a source. With no source the command prints `dotnet-format-lint: no .NET sources under
dotnet/` on stdout, exits 0 and starts no child. With sources, the solution is the one
direct child of `<root>/dotnet` with a `.slnx` or `.sln` suffix that is a regular file
and not a link: none prints `dotnet-format-lint: no_solution` and several print
`dotnet-format-lint: several_solutions`, each on stderr with exit 1, before any child
starts.

Completeness. `dotnet format <solution>` reads only the projects the solution lists, so a
discovered source it would never read must fail the check: a `.csproj` the solution does not
list, or a `.cs` with no listed project in its directory or above it (a solution that cannot be
parsed lists none). That prints `dotnet-format-lint: projects_outside_solution (<paths>)`,
the paths relative to the root and comma separated, on stderr, exits 1 and starts no child.
A directory or file under `<root>/dotnet` that cannot be read prints `dotnet-format-lint:
discovery_failed (<reason>)` on stderr and exits 2; it is never read as empty.

Tools. The SDK comes only from `nix build --no-link --print-out-paths
<root>#agent-platform.dotnet-tools`, run from the root with stdin closed. That is a
passthru of the platform package, in no launcher's closure, so the SDK is built only
when a lint judges .NET sources and the `agent-platform` package stays free of it. The
build must print exactly one absolute path whose `bin` holds an executable `dotnet`;
any other outcome prints `dotnet-format-lint: tools_unavailable` on stderr and exits 2.

The run. `dotnet` runs by its command name, `dotnet format <solution> --verify-no-changes`,
from `<root>/dotnet` with stdin closed and output inherited, on a `PATH` that is the
tools directory alone and an environment of only that `PATH`, the caller's `HOME` and
`TMPDIR` (so MSBuild's and NuGet's temporary files stay in the caller's temporary
directory), `LANG` `C` and settings that switch off telemetry, first-run work and every
build node that would outlive the run. Exit 0 prints `dotnet-format-lint: passed` and
exits 0. Exit 2, the formatter's verdict, prints `dotnet-format-lint: dotnet format
would change files` on stderr and exits 1. Any other exit N, a process that cannot
start or one that runs past 900 seconds prints `dotnet-format-lint: dotnet_failed
(exit N)` (`(cannot start)`, `(timeout)`) and exits 2.

A `--root` that is relative or not a directory prints `dotnet-format-lint: --root must
be an absolute directory: <value>` and exits 2.
"""

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from agent_tools.delivery.dotnet_solution import SOLUTION_ROOT
from agent_tools.delivery.promotion_schema import symlinked_component

COMMAND = "dotnet-format-lint"
TOOLS_ATTRIBUTE = "agent-platform.dotnet-tools"
SOURCE_SUFFIXES = (".cs", ".csproj", ".slnx", ".sln")
SOLUTION_SUFFIXES = (".slnx", ".sln")
IGNORED_DIRECTORIES = frozenset({"bin", "obj"})
SLN_PROJECT = re.compile(r'^Project\("[^"]*"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"', re.MULTILINE)
TIMEOUT_SECONDS = 900
CHECK_FAILED_EXIT = 2
FIXED_ENV = {
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    "MSBUILDDISABLENODEREUSE": "1",
    "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
    "LANG": "C",
}


class Refusal(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _is_regular(path: Path) -> bool:
    return stat.S_ISREG(os.lstat(path).st_mode)


def _raise(error: OSError) -> None:
    raise error


def sources(root: Path) -> list[Path]:
    """The .NET source files under `<root>/dotnet`, never through a link.

    A directory or file that cannot be read raises its `OSError`: it is never read as empty.
    """
    base = root / SOLUTION_ROOT
    if symlinked_component(root, SOLUTION_ROOT) is not None or not base.is_dir():
        return []
    found: list[Path] = []
    for directory, names, files in os.walk(base, followlinks=False, onerror=_raise):
        names[:] = sorted(n for n in names if n not in IGNORED_DIRECTORIES)
        found.extend(
            path for path in (Path(directory) / f for f in sorted(files))
            if path.name.endswith(SOURCE_SUFFIXES) and _is_regular(path))
    return found


def solution(root: Path) -> Path:
    """The one solution file directly in `<root>/dotnet`."""
    base = root / SOLUTION_ROOT
    found = sorted(
        path for path in base.iterdir()
        if path.name.endswith(SOLUTION_SUFFIXES) and not path.is_symlink() and path.is_file())
    if not found:
        raise Refusal("no_solution")
    if len(found) > 1:
        raise Refusal("several_solutions")
    return found[0]


def listed_projects(chosen: Path) -> set[Path]:
    """The `.csproj` files the solution `chosen` lists, as normalised absolute paths.

    A `.slnx` lists `Project` `Path` attributes, a `.sln` the second quoted field of `Project(...)`
    lines; an entry that is no `.csproj` (a `.sln` solution folder) is not listed, nor is any
    entry of a solution that cannot be read or parsed.
    """
    try:
        text = chosen.read_text("utf-8")
        if chosen.suffix == ".slnx":
            names = [e.get("Path", "") for e in ElementTree.fromstring(text).iter("Project")]
        else:
            names = SLN_PROJECT.findall(text)
    except (OSError, UnicodeDecodeError, ElementTree.ParseError):
        return set()
    return {Path(os.path.normpath(chosen.parent / name.replace("\\", "/")))
            for name in names if name.endswith(".csproj")}


def outside_solution(root: Path, chosen: Path, found: Sequence[Path]) -> list[Path]:
    """The sources `dotnet format <solution>` never reads: it reads only the listed projects.

    A `.csproj` the solution does not list is outside, and so is a `.cs` with no listed
    project in its own directory or above it.
    """
    projects = listed_projects(chosen)
    directories = {project.parent for project in projects}
    base = root / SOLUTION_ROOT

    def covered(path: Path) -> bool:
        if path.name.endswith(".csproj"):
            return path in projects
        if not path.name.endswith(".cs"):
            return True
        return any(parent in directories for parent in (path.parent, *path.parent.parents)
                   if parent == base or base in parent.parents)

    return [path for path in found if not covered(path)]


def tools_directory(root: Path) -> str:
    """The `bin` directory of the built .NET tools, when it holds an executable `dotnet`."""
    argv = ["nix", "--extra-experimental-features", "nix-command flakes", "build",
            "--no-link", "--print-out-paths", f"{root}#{TOOLS_ATTRIBUTE}"]
    try:
        done = subprocess.run(
            argv, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("tools_unavailable") from None
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) != 1 or not os.path.isabs(lines[0]):
        raise Refusal("tools_unavailable")
    tools = f"{lines[0]}/bin"
    if shutil.which("dotnet", path=tools) is None:
        raise Refusal("tools_unavailable")
    return tools


def format_argv(solution: Path) -> list[str]:
    return ["dotnet", "format", str(solution), "--verify-no-changes"]


def child_env(tools: str) -> dict[str, str]:
    env = {"PATH": tools, "HOME": os.environ.get("HOME", "")}
    if "TMPDIR" in os.environ:
        env["TMPDIR"] = os.environ["TMPDIR"]
    return {**env, **FIXED_ENV}


def _say(stream, line: str) -> None:
    print(f"{COMMAND}: {line}", file=stream, flush=True)


def run(root: Path) -> int:
    try:
        found = sources(root)
        if not found:
            _say(sys.stdout, f"no .NET sources under {SOLUTION_ROOT}/")
            return 0
        chosen = solution(root)
        stray = outside_solution(root, chosen, found)
        if stray:
            raise Refusal("projects_outside_solution", ", ".join(
                path.relative_to(root).as_posix() for path in stray))
        tools = tools_directory(root)
    except Refusal as refusal:
        _say(sys.stderr, f"{refusal.reason} ({refusal.detail})" if refusal.detail
             else refusal.reason)
        return 1 if refusal.reason in (
            "no_solution", "several_solutions", "projects_outside_solution") else 2
    except OSError as error:
        _say(sys.stderr, f"discovery_failed ({error.strerror or type(error).__name__})")
        return 2
    try:
        code = subprocess.run(
            format_argv(chosen), cwd=root / SOLUTION_ROOT, env=child_env(tools),
            stdin=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS).returncode
    except OSError:
        _say(sys.stderr, "dotnet_failed (cannot start)")
        return 2
    except subprocess.TimeoutExpired:
        _say(sys.stderr, "dotnet_failed (timeout)")
        return 2
    if code == 0:
        _say(sys.stdout, "passed")
        return 0
    if code == CHECK_FAILED_EXIT:
        _say(sys.stderr, "dotnet format would change files")
        return 1
    _say(sys.stderr, f"dotnet_failed (exit {code})")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_absolute() or not root.is_dir():
        _say(sys.stderr, f"--root must be an absolute directory: {args.root}")
        return 2
    return run(root)


if __name__ == "__main__":
    sys.exit(main())
