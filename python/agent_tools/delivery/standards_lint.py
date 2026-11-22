"""Lint the structure of the three standards layers: the index, the globs, the ids and the caps.

Layer 0 (`the-bar.md`) and Layer 1 (`stacks/*.md`) live in the platform standards
directory; Layer 2 is the repository's `docs/standards/` directory, a README index
plus one shard per file. The lint checks shapes only: whether a rule restates a
higher layer, or is process filed as a standard, stays with the reviewer.

Usage: standards-lint --repo-root <absolute dir> [--platform-standards <absolute dir>]
The platform directory defaults to the installed platform's standards directory
(`AGENT_PLATFORM_ROOT/standards`, else `$HOME/.agents/standards`).

Exits 0 with empty stdout and stderr when clean. Exits 1 with one problem per
stdout line, in this order, each `<label>: <reason>`. A platform file's label is
its path under the platform directory (`the-bar.md`, `stacks/python.md`,
`acceptance-planning.md`); a repository file's label is its path under the
repository root (`docs/standards/README.md`). Exits 2 with one stderr line
`standards-lint: <reason>` and empty stdout for a relative path, a missing
directory or a platform directory with no `the-bar.md`; an argparse usage error
exits 2 too. The lint reads no project policy.

Checks, in output order:
1. The platform. For `the-bar.md`, then each `stacks/*.md` by name: the size cap
   and the heading cap; then the rule-id problems of the bar and of the stacks
   together, where a stack file with no row in the README's `## Rule ids` table
   reports `has no prefix row in README.md`; then `acceptance-planning.md`.
2. The Layer 2 index, when `docs/standards` is a directory: a missing README
   beside shards, an index over 40 lines, a header with no `governs` column, a
   row naming no shard, a missing shard, or a shard an earlier row names, a
   `governs` cell that is prose, holds no code-span glob, holds a span that is no
   path glob, or one made only of `*` and `/`, and a shard with no row.
3. The Layer 2 shards: the size cap, the heading cap, a numbered item written
   without its `### P<n>.` heading (`line <n>: no well-formed id: <line>`), and
   the rule-id problems of the shards together.
4. The hint files, when `.agents/knowledge/hints` is a directory: each entry by
   name that is not a regular file named in `hint_phases.HINT_FILES`, then a hint
   file over the 60-line budget.

Reason formats: `is <n> bytes, over 8192`; `line <n>: heading is <n> characters,
over 100`; `index is <n> lines, over 40`; `row <k> names no shard`; `row names a
missing shard <target>`; `row <k> repeats the shard <target>`; `<shard> governs
prose, not path globs: <cell>`; `<shard> governs no path glob`; `<shard> governs
`<glob>`, which is not a path glob` or `which matches every path`; `has no row in
docs/standards/README.md`; `.agents/knowledge/hints/<name>: named for no delivery
phase that reads hints` and `.agents/knowledge/hints/<name>: is <n> lines, over
60`. A planning rule is a top-level `- ` item of the
`## Rules` section of `acceptance-planning.md`, found by its place and never by
the id it should carry: `line <n>: no well-formed id: <line>`, `more than one
id`, `<id> should carry the prefix R`, `<id> repeats the id`, `rule title is <n>
characters, over 100`, and `no planning rule` when the section holds none.

Caps: a shard is at most 8192 bytes, a heading line at most 100 characters, the
Layer 2 index at most 40 lines, a hint file at most 60 lines.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from agent_tools.delivery import hint_phases
from agent_tools.delivery.context_map_lint import CODE_RE, LINK_RE
from agent_tools.delivery.rule_ids import (
    HEADING_LINE, REASON_NO_ID, REASON_TWO_IDS, SECOND_ID, layer_problems, numbered_items,
    prefix_table, scan)
from agent_tools.project_contract import agent_platform

COMMAND = "standards-lint"
INDEX_MAX_LINES = 40
SHARD_MAX_BYTES = 8192
HEADING_MAX_CHARS = 100
HINT_MAX_LINES = 60
LAYER2_DIR = "docs/standards"
PLANNING_RULES = "acceptance-planning.md"
NOT_GLOB_RE = re.compile(r"\s")
PLANNING_RULE = re.compile(
    r"^- \*\*(?P<prefix>[A-Z]+)(?P<number>[1-9][0-9]*)\. (?P<title>[^*]*?)\*\*")
PLANNING_SECTION = "## Rules"
INDEX_LABEL = f"{LAYER2_DIR}/README.md"
TOP_HEADING = re.compile(r"^#{1,2} ")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def size_problems(label: str, path: Path) -> list[str]:
    size = len(path.read_bytes())
    return [f"{label}: is {size} bytes, over {SHARD_MAX_BYTES}"] if size > SHARD_MAX_BYTES else []


def heading_length_problems(label: str, text: str) -> list[str]:
    return [f"{label}: line {number}: heading is {len(line)} characters, over {HEADING_MAX_CHARS}"
            for number, line, content in scan(text)
            if HEADING_LINE.match(content) and len(line) > HEADING_MAX_CHARS]


def planning_rule_problems(text: str) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    candidates = 0
    in_section = False
    for number, line, _ in scan(text):
        if in_section and TOP_HEADING.match(line):
            in_section = False
        if line == PLANNING_SECTION:
            in_section = True
            continue
        if not in_section or not line.startswith("- "):
            continue
        candidates += 1
        found = PLANNING_RULE.match(line)
        if not found:
            problems.append(f"line {number}: {REASON_NO_ID}: {line}")
            continue
        name = f"{found['prefix']}{found['number']}"
        if SECOND_ID.search(found["title"]):
            problems.append(f"line {number}: {REASON_TWO_IDS}: {line}")
        elif found["prefix"] != "R":
            problems.append(f"line {number}: {name} should carry the prefix R")
        elif name in seen:
            problems.append(f"line {number}: {name} repeats the id")
        elif len(found.group(0)) > HEADING_MAX_CHARS:
            problems.append(
                f"line {number}: rule title is {len(found.group(0))} characters, over {HEADING_MAX_CHARS}")
        seen.add(name)
    return problems or ([] if candidates else ["no planning rule"])


def platform_problems(platform: Path) -> list[str]:
    readme = platform / "README.md"
    table = prefix_table(read(readme)) if readme.is_file() else {}
    problems: list[str] = []
    bar = platform / "the-bar.md"
    stacks = sorted((platform / "stacks").glob("*.md"))
    files = ([bar] if bar.is_file() else []) + stacks
    for path in files:
        label = path.relative_to(platform).as_posix()
        problems += size_problems(label, path) + heading_length_problems(label, read(path))
    if bar.is_file():
        problems += layer_problems([("the-bar.md", table.get("the-bar.md", ""), read(bar))])
    rows: list[tuple[str, str, str]] = []
    for path in stacks:
        label = path.relative_to(platform).as_posix()
        if label in table:
            rows.append((label, table[label], read(path)))
        else:
            problems.append(f"{label}: has no prefix row in README.md")
    problems += layer_problems(rows)
    planning = platform / PLANNING_RULES
    if planning.is_file():
        problems += [f"{PLANNING_RULES}: {problem}" for problem in planning_rule_problems(read(planning))]
    return problems


def governs_problems(shard: str, cell: str) -> list[str]:
    prefix = f"{INDEX_LABEL}: {shard} governs"
    spans = CODE_RE.findall(cell)
    leftover = re.sub(r"[,\s]", "", CODE_RE.sub("", cell))
    if leftover:
        return [f"{prefix} prose, not path globs: {cell.strip()}"]
    if not spans:
        return [f"{prefix} no path glob"]
    problems = []
    for glob in spans:
        if NOT_GLOB_RE.search(glob) or glob.startswith("/") or ".." in glob.split("/"):
            problems.append(f"{prefix} `{glob}`, which is not a path glob")
        elif set(glob) <= {"*", "/"}:
            problems.append(f"{prefix} `{glob}`, which matches every path")
    return problems


def index_table(text: str) -> list[list[str]]:
    """The rows of the first run of rendered `|` lines, separator rows dropped, the header first.

    A line inside a fence or an HTML block (a comment included) is not rendered and breaks the run.
    """
    rows: list[list[str]] = []
    previous = None
    for number, line, _ in scan(text):
        line = line.strip()
        if not line.startswith("|") or (previous is not None and number != previous + 1):
            if rows:
                break
            continue
        previous = number
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not all(set(cell) <= set("-: ") for cell in cells):
            rows.append(cells)
    return rows


def index_problems(repo: Path) -> list[str]:
    directory = repo / LAYER2_DIR
    if not directory.is_dir():
        return []
    shards = sorted(path.name for path in directory.glob("*.md") if path.is_file() and path.name != "README.md")
    readme = directory / "README.md"
    if not readme.is_file():
        return [f"{INDEX_LABEL}: missing, but the directory holds shards"] if shards else []
    text = read(readme)
    problems: list[str] = []
    count = len(text.splitlines())
    if count > INDEX_MAX_LINES:
        problems.append(f"{INDEX_LABEL}: index is {count} lines, over {INDEX_MAX_LINES}")
    table = index_table(text)
    header, body = (table[0], table[1:]) if table else ([], [])
    governs = header.index("governs") if "governs" in header else None
    if governs is None:
        problems.append(f"{INDEX_LABEL}: index has no governs column")
    named: set[str] = set()
    for k, cells in enumerate(body, 1):
        link = LINK_RE.search(cells[0])
        if not link:
            problems.append(f"{INDEX_LABEL}: row {k} names no shard")
            continue
        target = link.group(1)
        while target.startswith("./"):
            target = target[2:]
        if target not in shards:
            problems.append(f"{INDEX_LABEL}: row names a missing shard {target}")
        if target in named:
            problems.append(f"{INDEX_LABEL}: row {k} repeats the shard {target}")
        named.add(target)
        if governs is not None:
            problems += governs_problems(target, cells[governs] if governs < len(cells) else "")
    problems += [f"{LAYER2_DIR}/{name}: has no row in {INDEX_LABEL}" for name in shards if name not in named]
    return problems


def shard_problems(repo: Path, table: dict[str, str]) -> list[str]:
    directory = repo / LAYER2_DIR
    if not directory.is_dir():
        return []
    problems: list[str] = []
    files: list[tuple[str, str, str]] = []
    paths = sorted(path for path in directory.glob("*.md") if path.is_file() and path.name != "README.md")
    for path in paths:
        label = f"{LAYER2_DIR}/{path.name}"
        text = read(path)
        problems += size_problems(label, path) + heading_length_problems(label, text)
        lines = text.splitlines()
        problems += [f"{label}: line {n}: {REASON_NO_ID}: {lines[n - 1]}" for n in numbered_items(text)]
        files.append((label, table.get(f"{LAYER2_DIR}/", "P"), text))
    return problems + layer_problems(files)


def hint_problems(repo: Path) -> list[str]:
    directory = repo / hint_phases.HINT_DIR
    if not directory.is_dir():
        return []
    problems: list[str] = []
    for path in sorted(directory.iterdir(), key=lambda entry: entry.name):
        label = f"{hint_phases.HINT_DIR}/{path.name}"
        if not path.is_file() or path.name not in hint_phases.HINT_FILES:
            problems.append(f"{label}: named for no delivery phase that reads hints")
            continue
        count = len(read(path).splitlines())
        if count > HINT_MAX_LINES:
            problems.append(f"{label}: is {count} lines, over {HINT_MAX_LINES}")
    return problems


def lint(repo: Path, platform: Path) -> list[str]:
    readme = platform / "README.md"
    table = prefix_table(read(readme)) if readme.is_file() else {}
    return platform_problems(platform) + index_problems(repo) + shard_problems(repo, table) + hint_problems(repo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--platform-standards")
    args = parser.parse_args(argv)
    repo = Path(args.repo_root)
    platform = Path(args.platform_standards) if args.platform_standards else agent_platform.standards_dir()
    for name, path in (("--repo-root", repo), ("--platform-standards", platform)):
        if not path.is_absolute():
            print(f"{COMMAND}: {name} must be absolute: {path}", file=sys.stderr)
            return 2
        if not path.is_dir():
            print(f"{COMMAND}: not a directory: {path}", file=sys.stderr)
            return 2
    if not (platform / "the-bar.md").is_file():
        print(f"{COMMAND}: no the-bar.md in {platform}", file=sys.stderr)
        return 2
    problems = lint(repo, platform)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
