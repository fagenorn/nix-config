"""Run the agent workflow suite's members a branch touches, or the whole suite after a build when a build input changed (ADR-delivery-012).

Usage: `python -m agent_tools.delivery.touched_tests --base REF [--root DIR]
[--source-root DIR]... [--pair SOURCE=TEST]... [--cover SOURCE_GLOB=MEMBER_GLOB]...
[--suite-file PATH] [--build-when GLOB]... [--build-command CMD] [--env-from MEMBER=CMD]...`

A project's `test-touched` recipe runs this module (it has no command-table row, after
`agent_tools.delivery.verification_command`). It reads no project policy: the base, the
source roots, the pairs, the covers, the globs and the build command are all flags. The members
are those of the `agent-workflow-tests` recipe in `<root>/<suite file>` (`--suite-file`, default
`justfile`), read with
`agent_tools.delivery.suite_runner.suite_members`. The changed paths are the lines of
`git diff --no-renames --name-only -z <base>...HEAD`, read from `<root>`, so a non-ASCII path
arrives unquoted.

Selection rules, in member order, then the pair tests in flag order, with no duplicates.
Apart from the pairs, only members are selected, so a nightly or unregistered test never is.

- touched: a changed path that is a member.
- named: for a changed `<dir>/<stem>.py` whose name does not start with `test_`, every member
  named `test_<stem>.py` or starting with `test_<stem>_`.
- importer: for a changed `.py` under a source root, the module is its path relative to the
  root with `/` turned into `.` and `.py` (or `/__init__.py`) dropped. A member is selected
  when its parsed source holds `import M`, `from M import ...` or `from P import name` where
  `P.name` is `M`. Submodules of `M`, a textual prefix, and a mention in a comment or a
  string do not count. A member that does not parse is skipped.
- path: a member whose text holds the changed path, or a member in the same directory whose
  text holds the changed path's file name.
- cover: a member matching one of a `--cover` value's member globs, when a changed path
  matches its source glob (`fnmatch`, so `*` also matches `/`). A cover never selects a
  non-member.
- pair: for a changed `--pair` source, each of its tests, even when it is not a member.

Full rule: `full_because` is every changed path, in diff order, matching a `--build-when` glob
(`fnmatch`, so `*` also matches `/`), and the selection is full when it is not empty. A full
selection builds first, after `test-touched: building with <command>: <path> changed` on
stderr (a non-zero build exit is the result with no suite run), then runs every member, then
the pair tests of changed pair sources that are not members. With no match no build runs and
the selection is the rules above. `--build-when` without `--build-command` is a usage error
(exit 2), as is a `--pair` or `--cover` value with no `=` or an empty side.

Environment member: `--env-from MEMBER=CMD` names a test file that needs variables only a
build gives it. When MEMBER is selected, the build command runs first (unless a full
selection already ran it), then CMD runs from the root and prints one `NAME=VALUE` line per
variable (blank lines are skipped; any other line, or a non-zero exit, is the result with no
suite run: the exit code, or 2 for a bad line), and MEMBER runs through the suite runner on its
own with those variables added to the environment. The other selected members run first, as
without the flag, and the result is the first non-zero exit of the runs. When
`SUITE_RUNNER_REPORT` is set and the selection runs in more than one process, each process
writes its timing report to a temporary file and the runs' reports are merged into one report
at the `SUITE_RUNNER_REPORT` path (resolved against the root) covering the whole selection;
a run that wrote no report adds no rows. `--env-from` without
`--build-command` is a usage error (exit 2), as is a value with no `=` or an empty side, or
the same MEMBER twice.

Selection file: when the environment variable `VERIFIED_TREE_SELECTION` (`SELECTION_ENV`)
names a path, the selection is written there before anything runs, as one line of JSON with
sorted keys: `base`, `changed`, `full`, `full_because` and `selected`, even when nothing is
selected. A file that cannot be written prints `test-touched: cannot write the selection to
<path>: <error>` on stderr and changes no exit code. The build and the suite runner start
without the variable.

.NET rule: `--dotnet-tests` also runs the .NET tests a change touches, and without it none of
this happens (no `sources`, no tools, no `dotnet` key). Only changed paths under the solution
root (`SOLUTION_ROOT`) count, and with none the projects are never listed. Otherwise they are every `.csproj` that
`agent_tools.delivery.dotnet_format_lint.sources` lists there (an `OSError` prints
`test-touched: cannot list the .NET projects: <error>` and returns 2 before anything runs).
A changed file named in `SHARED_BUILD_FILES` selects the whole set. A changed `.cs` or
`.csproj` belongs to the `.csproj` in its nearest ancestor directory holding one (a `.csproj`
counts its own directory); a project whose stem ends `.Tests` is its own target, any other
project's target is the one project whose stem is `<stem>.Tests`. A path with no project, or
with no or several test projects, selects the whole set. With no `.csproj` under the solution
root, no .NET target is selected. Any other path selects nothing. The
whole set is the one solution file (a `Refusal` from `solution` prints `test-touched:
<reason>` and returns 1 before anything runs); otherwise the targets are the sorted test
projects. The selection file gains `dotnet`, the targets, only when there are some. The
Python selection runs first; then, when targets exist, `dotnet test <target>` runs per target
in order through the tools directory, with exactly `child_env(tools)` and none of the caller's environment (a `Refusal` from the tools
prints `test-touched: .NET tools unavailable (<reason>)` and counts as exit 2), and the result
is the first non-zero of all runs. Nothing is "touched" only when no suite member and no
target is selected.

Output: when nothing is selected, on stdout `test-touched: no suite member is touched by
<base>...HEAD`, and the result is 0 (or the build's 0). Otherwise, on stderr,
`test-touched: running <n>: <paths>`, and the result is the exit code of
`agent_tools.delivery.suite_runner` run on the selection from the root. A failing
`git diff`, such as an unknown base, prints git's stderr and returns 2.
"""

import argparse
import ast
import fnmatch
import json
import os
import posixpath
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery.dotnet_format_lint import (
    Refusal, child_env, solution, sources, tools_directory)
from agent_tools.delivery.dotnet_solution import SOLUTION_ROOT
from agent_tools.delivery.suite_runner import (
    REPORT_ENV, REPORT_VERSION, suite_members, write_report)


SELECTION_ENV = "VERIFIED_TREE_SELECTION"
SHARED_BUILD_FILES = ("Directory.Build.props", "Directory.Packages.props",
                      "packages.lock.json", "deps.json")


class DotnetSelection(NamedTuple):
    whole_because: tuple[str, ...]
    test_projects: tuple[str, ...]


def _project_stem(path: str) -> str:
    return posixpath.basename(path)[:-len(".csproj")]


def _owning_project(path: str, projects: Sequence[str]) -> str | None:
    """The one `.csproj` in the path's nearest ancestor directory holding one, if exactly one."""
    by_directory: dict[str, list[str]] = {}
    for project in projects:
        by_directory.setdefault(posixpath.dirname(project), []).append(project)
    directory = posixpath.dirname(path)
    while directory == SOLUTION_ROOT or directory.startswith(f"{SOLUTION_ROOT}/"):
        if directory in by_directory:
            found = by_directory[directory]
            return found[0] if len(found) == 1 else None
        directory = posixpath.dirname(directory)
    return None


def dotnet_selection(changed: Sequence[str], projects: Sequence[str]) -> DotnetSelection:
    whole: list[str] = []
    tests: set[str] = set()
    for path in changed:
        if not path.startswith(f"{SOLUTION_ROOT}/"):
            continue
        if posixpath.basename(path) in SHARED_BUILD_FILES:
            whole.append(path)
        elif path.endswith((".cs", ".csproj")):
            project = _owning_project(path, projects)
            stem = _project_stem(project) if project else ""
            if project and stem.endswith(".Tests"):
                tests.add(project)
                continue
            matches = [p for p in projects if _project_stem(p) == f"{stem}.Tests"] if project else []
            if len(matches) == 1:
                tests.add(matches[0])
            else:
                whole.append(path)
    if whole:
        return DotnetSelection(tuple(whole), ())
    return DotnetSelection((), tuple(sorted(tests)))


class GitError(RuntimeError):
    pass


def changed_paths(root: Path, base: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--no-renames", "--name-only", "-z", f"{base}...HEAD"],
        capture_output=True)
    if result.returncode != 0:
        raise GitError(result.stderr.decode("utf-8", errors="replace").rstrip("\n"))
    return [name.decode("utf-8", errors="replace")
            for name in result.stdout.split(b"\0") if name]


def build_trigger(changed: Sequence[str], globs: Sequence[str]) -> str | None:
    for path in changed:
        if any(fnmatch.fnmatchcase(path, glob) for glob in globs):
            return path
    return None


def module_name(path: str, source_roots: Sequence[str]) -> str | None:
    for root in source_roots:
        prefix = root.rstrip("/") + "/"
        if not path.startswith(prefix) or not path.endswith(".py"):
            continue
        parts = path[len(prefix):-len(".py")].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            return ".".join(parts)
    return None


def imports_module(text: str, module: str) -> bool:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == module:
                return True
            if any(f"{node.module}.{alias.name}" == module for alias in node.names):
                return True
    return False


def select(changed: Sequence[str], members: Sequence[str], read: Callable[[str], str], *,
           source_roots: Sequence[str] = (),
           pairs: Mapping[str, Sequence[str]] = {},
           covers: Mapping[str, Sequence[str]] = {}) -> list[str]:
    modules = [m for m in (module_name(p, source_roots) for p in changed) if m]
    stems = [Path(p).stem for p in changed
             if p.endswith(".py") and not Path(p).name.startswith("test_")]
    selected: list[str] = []
    for member in members:
        name = Path(member).name
        text = read(member)
        if (member in changed
                or any(name == f"test_{s}.py" or name.startswith(f"test_{s}_") for s in stems)
                or any(imports_module(text, m) for m in modules)
                or any(fnmatch.fnmatchcase(member, g)
                       for source, globs in covers.items()
                       if any(fnmatch.fnmatchcase(p, source) for p in changed)
                       for g in globs)
                or any(p in text or (Path(p).parent == Path(member).parent
                                     and Path(p).name in text) for p in changed)):
            selected.append(member)
    for source, tests in pairs.items():
        if source in changed:
            selected.extend(t for t in tests if t not in selected)
    return selected


def selection(changed: Sequence[str], members: Sequence[str], read: Callable[[str], str], *,
              source_roots: Sequence[str] = (),
              pairs: Mapping[str, Sequence[str]] = {},
              covers: Mapping[str, Sequence[str]] = {},
              build_globs: Sequence[str] = ()) -> dict:
    full_because = [p for p in changed if any(fnmatch.fnmatchcase(p, g) for g in build_globs)]
    if full_because:
        selected = list(members)
        for source, tests in pairs.items():
            if source in changed:
                selected.extend(t for t in tests if t not in selected)
    else:
        selected = select(changed, members, read, source_roots=source_roots,
                          pairs=pairs, covers=covers)
    return {"changed": list(changed), "full": bool(full_because),
            "full_because": full_because, "selected": selected}


def _parse_mapping(parser: argparse.ArgumentParser, flag: str, shape: str,
                   values: Sequence[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for value in values:
        source, separator, target = value.partition("=")
        if not separator or not source or not target:
            parser.error(f"{flag} {value!r}: expected {shape}")
        mapping.setdefault(source, []).append(target)
    return mapping


def parse_pairs(parser: argparse.ArgumentParser, values: Sequence[str]) -> dict[str, list[str]]:
    return _parse_mapping(parser, "--pair", "SOURCE=TEST", values)


def parse_covers(parser: argparse.ArgumentParser, values: Sequence[str]) -> dict[str, list[str]]:
    return _parse_mapping(parser, "--cover", "SOURCE_GLOB=MEMBER_GLOB", values)


class ExactEnv(dict):
    """An environment a launch gets whole, in place of the caller's plus an overlay."""


def default_execute(argv: list[str], cwd: Path, extra: Mapping[str, str] | None = None) -> int:
    if isinstance(extra, ExactEnv):
        return subprocess.run(argv, cwd=cwd, env=dict(extra)).returncode
    env = {k: v for k, v in os.environ.items() if k != SELECTION_ENV}
    env.update(extra or {})
    return subprocess.run(argv, cwd=cwd, env=env).returncode


def default_capture(argv: list[str], cwd: Path) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != SELECTION_ENV}
    result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, text=True)
    return result.returncode, result.stdout


def parse_assignments(output: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.isidentifier():
            raise ValueError(f"not a NAME=VALUE line: {line!r}")
        assignments[name] = value
    return assignments


def merge_reports(reports: Sequence[Mapping]) -> dict:
    """One timing report over the runs' reports: counts and times summed, rows slowest first."""
    rows = sorted((row for report in reports for row in report["timings"]),
                  key=lambda row: -row["seconds"])
    return {
        "version": REPORT_VERSION,
        "members": sum(report["members"] for report in reports),
        "passed": sum(report["passed"] for report in reports),
        "failed": sum(report["failed"] for report in reports),
        "jobs": max(report["jobs"] for report in reports),
        "wall_seconds": round(sum(report["wall_seconds"] for report in reports), 1),
        "member_seconds": sum(report["member_seconds"] for report in reports),
        "cpu_seconds": round(sum(report["cpu_seconds"] for report in reports), 1),
        "timings": rows,
    }


def _say(stream, line: str) -> None:
    print(line, file=stream, flush=True)


def main(argv: Sequence[str] | None = None, *,
         execute: Callable[..., int] | None = None,
         capture: Callable[[list[str], Path], tuple[int, str]] | None = None,
         dotnet_tools: Callable[[Path], str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touched-tests")
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--cover", action="append", default=[])
    parser.add_argument("--suite-file", default="justfile")
    parser.add_argument("--build-when", action="append", default=[])
    parser.add_argument("--build-command", default=None)
    parser.add_argument("--env-from", action="append", default=[])
    parser.add_argument("--dotnet-tests", action="store_true")
    args = parser.parse_args(argv)
    pairs = parse_pairs(parser, args.pair)
    covers = parse_covers(parser, args.cover)
    if args.build_when and not args.build_command:
        parser.error("--build-when needs --build-command")
    env_commands = _parse_mapping(parser, "--env-from", "MEMBER=CMD", args.env_from)
    if env_commands and not args.build_command:
        parser.error("--env-from needs --build-command")
    for member, commands in env_commands.items():
        if len(commands) > 1:
            parser.error(f"--env-from names {member!r} twice")
    run = execute or default_execute
    capture_output = capture or default_capture
    root = Path(args.root) if args.root else Path.cwd()
    try:
        changed = changed_paths(root, args.base)
    except GitError as error:
        _say(sys.stderr, str(error))
        return 2

    def read(path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    members = suite_members(read(args.suite_file))
    chosen = selection(changed, members, read, source_roots=args.source_root, pairs=pairs,
                       covers=covers, build_globs=args.build_when)
    dotnet_targets: list[str] = []
    if args.dotnet_tests and any(p.startswith(f"{SOLUTION_ROOT}/") for p in changed):
        try:
            projects = [p.relative_to(root).as_posix() for p in sources(root)
                        if p.name.endswith(".csproj")]
        except OSError as error:
            _say(sys.stderr, f"test-touched: cannot list the .NET projects: {error}")
            return 2
        picked = dotnet_selection(changed, projects)
        if picked.whole_because and projects:
            try:
                dotnet_targets = [solution(root).relative_to(root).as_posix()]
            except Refusal as refusal:
                _say(sys.stderr, f"test-touched: {refusal.reason}")
                return 1
        elif projects:
            dotnet_targets = list(picked.test_projects)
        if dotnet_targets:
            chosen = {**chosen, "dotnet": dotnet_targets}
    target = os.environ.get(SELECTION_ENV)
    if target:
        document = json.dumps({"base": args.base, **chosen}, sort_keys=True,
                              separators=(",", ":")) + "\n"
        try:
            Path(target).write_text(document, encoding="utf-8")
        except OSError as error:
            _say(sys.stderr, f"test-touched: cannot write the selection to {target}: {error}")

    built = chosen["full"]
    if built:
        _say(sys.stderr, f"test-touched: building with {args.build_command}: "
                         f"{chosen['full_because'][0]} changed")
        code = run(shlex.split(args.build_command), root)
        if code != 0:
            return code
    selected = chosen["selected"]
    if not selected and not dotnet_targets:
        _say(sys.stdout, f"test-touched: no suite member is touched by {args.base}...HEAD")
        return 0
    prepared: dict[str, dict[str, str]] = {}
    for member in selected:
        if member not in env_commands:
            continue
        if not built:
            _say(sys.stderr, f"test-touched: building with {args.build_command}: "
                             f"{member} needs its build environment")
            code = run(shlex.split(args.build_command), root)
            if code != 0:
                return code
            built = True
        code, output = capture_output(shlex.split(env_commands[member][0]), root)
        if code != 0:
            return code
        try:
            prepared[member] = parse_assignments(output)
        except ValueError as error:
            _say(sys.stderr, f"test-touched: {env_commands[member][0]}: {error}")
            return 2
    if selected:
        _say(sys.stderr, f"test-touched: running {len(selected)}: {' '.join(selected)}")
    runner = [sys.executable, "-m", "agent_tools.delivery.suite_runner"]
    plain = [m for m in selected if m not in prepared]
    launches: list[tuple[list[str], dict[str, str] | None]] = []
    if plain:
        launches.append((plain, None))
    launches.extend(([member], prepared[member]) for member in selected if member in prepared)
    report_value = os.environ.get(REPORT_ENV, "")
    merging = bool(report_value) and len(launches) > 1
    results: list[int] = []
    with tempfile.TemporaryDirectory(prefix="touched-tests-report-") as scratch:
        parts: list[Path] = []
        for index, (members_run, extra) in enumerate(launches):
            argv_run = [*runner, *members_run]
            if merging:
                parts.append(Path(scratch) / f"{index}.json")
                extra = {**(extra or {}), REPORT_ENV: str(parts[-1])}
            results.append(run(argv_run, root) if extra is None
                           else run(argv_run, root, extra))
        written = [json.loads(part.read_text(encoding="utf-8"))
                   for part in parts if part.is_file()]
        if written:
            write_report(root / report_value, merge_reports(written))
    if dotnet_targets:
        try:
            tools = (dotnet_tools or tools_directory)(root)
        except Refusal as refusal:
            _say(sys.stderr, f"test-touched: .NET tools unavailable ({refusal.reason})")
            results.append(2)
        else:
            for dotnet_target in dotnet_targets:
                _say(sys.stderr, f"test-touched: dotnet test {dotnet_target}")
                results.append(run([f"{tools}/dotnet", "test", dotnet_target], root,
                                   ExactEnv(child_env(tools))))
    return next((code for code in results if code != 0), 0)

if __name__ == "__main__":
    sys.exit(main())
