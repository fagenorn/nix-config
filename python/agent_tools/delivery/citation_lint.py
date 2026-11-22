"""The citation half of the standards lint: an enforcer's citation of a rule id, a suppression's rule id, and the rule index (#1442, #1459).

`agent_tools.delivery.standards_lint` is the one lint and the one command; this module is
its library and has no entry point and no command-table row. Its contract, the problem lines
and the `--index` output, is that command's module docstring.

An enforcer names the rule it holds by the citation `standard:<id>` (`agent_tools.delivery.rule_ids`
owns the form). The enforcers are the files the lint reads, and only those: the members
of the justfile's `agent-workflow-tests` recipe (`suite_runner.suite_members`) and the source
file of each module the `lint` verification command runs (`verification_command.members`),
as repository-relative paths under `python/`. A file outside that set is never read. A
repository whose justfile has no such recipe registers no enforcers, so it has no citation problem.

A suppression marker (`suppress-standard:<id> <reason>`, `agent_tools.delivery.rule_ids.markers`)
is read in every tracked file of the repository, not only in an enforcer: the files `git ls-files`
lists, less a symlink, a file that is not a regular file and a binary file (a NUL in its first
`never_rise.BINARY_PROBE_BYTES` bytes), each decoded as UTF-8 with replacement. A root with no `.git`
entry reads none; a root `git` cannot list raises `ValueError`. A marker that names no id is no
problem here.

A rule is a `###` rule-id heading outside a fence and an HTML comment or block
(`agent_tools.delivery.rule_ids.scan`, the reading the heading test uses), so a rule commented
out or shown as an example defines nothing. The platform layer is `the-bar.md` and each
`stacks/*.md` of the platform standards directory; the project layer is each `*.md` of the
repository's `docs/standards` except `README.md`. A well-formed citation resolves against
exactly one layer by its prefix: an id with the project prefix (`P`) against the project layer,
any other id against the platform layer. A project id never resolves against the platform and
a platform id never against the project.

`check` returns the problem lines and, when asked, the index lines:

- `<path>: registered enforcer is missing`
- `<path>:<line>: malformed citation standard:<token>` (a token that is no rule id)
- `<path>:<line>: cites <id>, which is in no applicable layer`
- `<path>:<line>: suppresses <id>, which is in no applicable layer` (a marker, reasoned or bare,
  naming an id that resolves against no rule of its layer, as a citation resolves), after every
  enforcer problem, in file then line order

The index is, for each rule in order (the bar, then the stacks by filename, then the project
shards by filename, each in heading order):

- `<id>. <title>`, then one line `  <path>` per enforcer citing that id with a well-formed
  citation, sorted by path, each path once;
- then, when `n > 0`, one line `  reasoned suppressions: <n>`, the reasoned markers naming that
  rule in the layer it resolves to (a bare marker is counted by no one here);
- then `judged rules: <n>`, the rules no enforcer cites;
- then `enforcers citing nothing: <m>`, the existing registered enforcers whose text holds
  neither a citation (well-formed or not) nor a decision-record id (`ADR-<area>-NNN`); a missing
  enforcer is a problem and is not counted.

A lint member run without `-m` raises `ValueError`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery.context_map_lint import CITATION_RE
from agent_tools.delivery.never_rise import BINARY_PROBE_BYTES, SELECTION_VARIABLES
from agent_tools.delivery.rule_ids import (
    CITATION, CITE, PROJECT_PREFIX, RULE_ID_HEADING, Marker, citations, markers, prefix_of, scan)
from agent_tools.delivery.suite_runner import SUITE_RECIPE, suite_members
from agent_tools.delivery.verification_command import members

PACKAGE_SOURCE = "python"
PROJECT_STANDARDS = "docs/standards"


class Rule(NamedTuple):
    id: str
    title: str


def _headings(path: Path) -> list[Rule]:
    rules = []
    for _, _, line in scan(path.read_text("utf-8")):
        match = RULE_ID_HEADING.match(line)
        if match and match["hashes"] == "###":
            rules.append(Rule(match["prefix"] + match["number"], match["title"]))
    return rules


def platform_rules(directory: Path) -> list[Rule]:
    """The rules of `the-bar.md`, then of each `stacks/*.md` by name, in file order."""
    bar = directory / "the-bar.md"
    if not bar.is_file():
        raise ValueError(f"{directory} has no the-bar.md")
    rules = _headings(bar)
    for shard in sorted((directory / "stacks").glob("*.md")):
        rules += _headings(shard)
    return rules


def project_rules(directory: Path) -> list[Rule]:
    """The rules of each `*.md` of `directory` but `README.md`, by name, in file order."""
    rules: list[Rule] = []
    for shard in sorted(directory.glob("*.md")):
        if shard.name != "README.md":
            rules += _headings(shard)
    return rules


def enforcers(root: Path) -> list[str]:
    """The registered enforcers: the suite's members and the `lint` command's module sources."""
    paths = set(suite_members((root / "justfile").read_text("utf-8")))
    for member in members("lint", root):
        if "-m" not in member.argv:
            raise ValueError(f"lint member {member.id} runs no module")
        module = member.argv[member.argv.index("-m") + 1]
        paths.add(PACKAGE_SOURCE + "/" + module.replace(".", "/") + ".py")
    return sorted(paths)


def _citations_of(root: Path, path: str):
    return citations((root / path).read_text("utf-8"))


def tracked_markers(root: Path) -> list[tuple[str, Marker]]:
    """Each suppression marker of each tracked text file of `root`, as (path, marker).

    The path is repository-relative and POSIX; the order is `git ls-files` order, then line order.
    """
    if not (root / ".git").exists():
        return []
    env = {k: v for k, v in os.environ.items() if k not in SELECTION_VARIABLES}
    try:
        listing = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                                 capture_output=True, env=env)
    except OSError:
        listing = None
    if listing is None or listing.returncode != 0:
        raise ValueError(f"cannot list the tracked files of {root}")
    found: list[tuple[str, Marker]] = []
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        content = path.read_bytes()
        if b"\0" in content[:BINARY_PROBE_BYTES]:
            continue
        text = content.decode("utf-8", errors="replace")
        found += [(name, marker) for marker in markers(text)]
    return found


def problems(root: Path, paths: list[str], platform: list[Rule], project: list[Rule],
             marks: list[tuple[str, Marker]]) -> list[str]:
    """One line per missing enforcer, malformed citation, citation of an id in no applicable layer,
    then suppression of an id in no applicable layer."""
    layers = {True: {rule.id for rule in project}, False: {rule.id for rule in platform}}
    found: list[str] = []
    for path in paths:
        if not (root / path).is_file():
            found.append(f"{path}: registered enforcer is missing")
            continue
        for citation in _citations_of(root, path):
            if not citation.well_formed:
                found.append(f"{path}:{citation.line}: malformed citation {CITE}{citation.token}")
            elif citation.token not in layers[prefix_of(citation.token) == PROJECT_PREFIX]:
                found.append(f"{path}:{citation.line}: cites {citation.token}, "
                             "which is in no applicable layer")
    for path, marker in marks:
        if marker.rule is not None and marker.rule not in layers[prefix_of(marker.rule) == PROJECT_PREFIX]:
            found.append(f"{path}:{marker.line}: suppresses {marker.rule}, "
                         "which is in no applicable layer")
    return found


def rule_index(root: Path, paths: list[str], platform: list[Rule], project: list[Rule],
               marks: list[tuple[str, Marker]]) -> list[str]:
    """The index lines: each rule with the enforcers citing it and its reasoned suppressions, then the two counts.

    A citation or a reasoned suppression credits a rule of the layer it resolves to, as `problems`
    resolves it.
    """
    reasoned: dict[tuple[bool, str], int] = {}
    for _, marker in marks:
        if marker.reasoned:
            key = (prefix_of(marker.rule) == PROJECT_PREFIX, marker.rule)
            reasoned[key] = reasoned.get(key, 0) + 1
    citing: dict[tuple[bool, str], set[str]] = {}
    nothing = 0
    for path in paths:
        if not (root / path).is_file():
            continue
        text = (root / path).read_text("utf-8")
        for citation in citations(text):
            if citation.well_formed:
                layer = prefix_of(citation.token) == PROJECT_PREFIX
                citing.setdefault((layer, citation.token), set()).add(path)
        if not CITATION.search(text) and not CITATION_RE.search(text):
            nothing += 1
    lines: list[str] = []
    judged = 0
    for layer, rules in ((False, platform), (True, project)):
        for rule in rules:
            lines.append(f"{rule.id}. {rule.title}")
            cited = sorted(citing.get((layer, rule.id), ()))
            lines += [f"  {path}" for path in cited]
            if reasoned.get((layer, rule.id)):
                lines.append(f"  reasoned suppressions: {reasoned[(layer, rule.id)]}")
            judged += not cited
    return lines + [f"judged rules: {judged}", f"enforcers citing nothing: {nothing}"]


def check(root: Path, platform_directory: Path, with_index: bool) -> tuple[list[str], list[str]]:
    """The problem lines and, when `with_index`, the index lines, for the repository at `root`."""
    justfile = root / "justfile"
    registered = justfile.is_file() and SUITE_RECIPE in justfile.read_text("utf-8").splitlines()
    paths = enforcers(root) if registered else []
    platform = platform_rules(platform_directory)
    project_directory = root / PROJECT_STANDARDS
    project = project_rules(project_directory) if project_directory.is_dir() else []
    marks = tracked_markers(root)
    return (problems(root, paths, platform, project, marks),
            rule_index(root, paths, platform, project, marks) if with_index else [])
