"""The citation half of the standards lint: an enforcer's citation of a rule id, and the rule index (#1442).

`agent_tools.delivery.standards_lint` is the one lint and the one command; this module is
its library and has no entry point and no command-table row. Its contract, the problem lines
and the `--index` output, is that command's module docstring.

An enforcer names the rule it holds by the citation `standard:<id>` (`agent_tools.delivery.rule_ids`
owns the form). The enforcers are the files the lint reads, and only those: the members
of the justfile's `agent-workflow-tests` recipe (`suite_runner.suite_members`) and the source
file of each module the `lint` verification command runs (`verification_command.members`),
as repository-relative paths under `python/`. A file outside that set is never read. A
repository whose justfile has no such recipe registers no enforcers, so it has no citation problem.

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

The index is, for each rule in order (the bar, then the stacks by filename, then the project
shards by filename, each in heading order):

- `<id>. <title>`, then one line `  <path>` per enforcer citing that id with a well-formed
  citation, sorted by path, each path once;
- then `judged rules: <n>`, the rules no enforcer cites;
- then `enforcers citing nothing: <m>`, the existing registered enforcers whose text holds
  neither a citation (well-formed or not) nor a decision-record id (`ADR-<area>-NNN`); a missing
  enforcer is a problem and is not counted.

A lint member run without `-m` raises `ValueError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery.context_map_lint import CITATION_RE
from agent_tools.delivery.rule_ids import (
    CITATION, CITE, PROJECT_PREFIX, RULE_ID_HEADING, citations, prefix_of, scan)
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


def problems(root: Path, paths: list[str], platform: list[Rule], project: list[Rule]) -> list[str]:
    """One line per missing enforcer, malformed citation and citation of an id in no applicable layer."""
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
    return found


def rule_index(root: Path, paths: list[str], platform: list[Rule], project: list[Rule]) -> list[str]:
    """The index lines: each rule with the enforcers citing it, then the two counts.

    A citation credits a rule of the layer it resolves to, as `problems` resolves it.
    """
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
    return (problems(root, paths, platform, project),
            rule_index(root, paths, platform, project) if with_index else [])
