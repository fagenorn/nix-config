"""Lint a repo's CONTEXT-MAP.md against its area glossaries.

Checks that every term in the map's term table resolves to an area file that
actually defines it, that every file is inside its budget, that every governs:
glob matches something real, and that every relative link in the map resolves.

Where the repo has a docs/areas/ directory it also enforces the standard docs
layout: area directories and map rows agree in both directions, ADR records are
NNN-kebab-title.md with a matching `# ADR-<slug>-NNN — Title` header and a number
unique in their directory, every ADR citation under docs/ resolves, no retired
four-digit id survives, and the docs root stays clean. Repos on a legacy layout
have no docs/areas/, so none of that applies to them.

A decision record is a header, an optional `**Formerly:**` line and one
paragraph of at most 1,500 bytes: no section heading, list, quote, fence,
status line or second paragraph. B18 (the size) and B19 (the form) are
per-file violations for the never-rise check, `RECORD_ENFORCERS`, not findings
of this command, so a run neither prints nor fails on them: the records written
before the form are carried by the change's merge base, and only a record that
grows past its base, or that is added, rises. A rename git pairs carries a
record's violations only as a migration of a record: a well-formed new header
with the old title, at most one well-formed Formerly line naming the old record,
the body byte for byte, and at most two bytes of blank lines added, so the
exempted growth is one header and one Formerly line; a superseding record that reuses the old
text, and a file that was no record, are judged as a new record. `added_records`
lists the records a change adds, a migration excluded.

A repository that owns its context-map lint, with its own rules and budgets,
declares it as the `context-map-lint` entry of its project contract's
`commands`. The caller that resolved the contract passes that entry's argv
after `--repo-lint`, which takes every remaining argument, and the entry's
resolved `cwd` as `--repo-lint-cwd`: an absolute directory inside the root,
the root itself when omitted. This tool then runs none of its own checks, the
budgets, layout, ADR ids, citations and docs root included: it runs that
command in that directory and exits with its status, so a map the repository's
lint accepts is never failed here against this tool's budgets. This tool reads
no project policy itself. Without `--repo-lint` nothing changes.

Usage: context-map-lint --repo-root <absolute-root> --context-map <absolute-map> [[--repo-lint-cwd <absolute-dir>] --repo-lint <command> [<arg>...]]
Exits 0 when clean, 1 on findings, 2 on misuse. With --repo-lint the command's
own exit status is passed through unchanged, a 2 of its own included, so there
a 2 is either this tool's misuse or the repository lint's own; a command that
cannot be started exits 2 and one ended by a signal exits 1.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery.never_rise import Enforcer, Snapshot, Verdict, Violation

MAP_BUDGET = 150
AREA_BUDGET_DEFAULT = 200

RESERVED_DIRS = {"areas", "standards", "operations", "guides", "archive"}
ROOT_FILES = {"README.md", "CONTEXT-MAP.md"}
FORMERLY = "**Formerly:**"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
CODE_RE = re.compile(r"`([^`]+)`")
TERM_DEF_RE = re.compile(r"^\*\*([^*]+)\*\*\s*:", re.M)
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
ADR_FILE_RE = re.compile(r"\A(\d{3})-[a-z0-9][a-z0-9-]*\.md\Z")
ADR_HEADER_RE = re.compile(r"\A#\s+ADR-([a-z0-9][a-z0-9-]*)-(\d{3})\s+—\s+\S")
CITATION_RE = re.compile(r"\bADR-([a-z0-9][a-z0-9-]*)-(\d{3})\b")
RETIRED_ID_RE = re.compile(r"\bADR-\d{4}\b")

RECORD_BYTES_CAP = 1500
RECORD_SIZE_RULE = "B18"
RECORD_FORM_RULE = "B19"
FORMERLY_LINE_RE = re.compile(r"^\*\*Formerly:\*\* ADR-[a-z0-9][a-z0-9-]*-\d{3}\s*$")
FORMERLY_BYTES_RE = re.compile(rb"^\*\*Formerly:\*\* ADR-[a-z0-9][a-z0-9-]*-\d{3}\n?\Z")
# A slug is a directory name: a header naming one longer than this is no migration.
MAX_SLUG_BYTES = 64
NEW_HEADER_BYTES_RE = re.compile(
    rb"\A# ADR-(?P<slug>[a-z0-9][a-z0-9-]{0,%d})-(?P<number>\d{3}) \xe2\x80\x94 (?P<title>\S[^\n]*)\Z"
    % (MAX_SLUG_BYTES - 1))
OLD_HEADER_BYTES_RE = re.compile(
    rb"\A#\s+ADR-(?P<slug>[a-z0-9][a-z0-9-]*)-(?P<number>\d{3})\s+\xe2\x80\x94\s+(?P<title>\S[^\n]*)\Z")
MIGRATION_BLANK_BYTES = 2
LABEL_RE = re.compile(r"^ {0,3}(?:\*\*|__)[^*_]{1,40}[.:](?:\*\*|__)")
ORDERED_RE = re.compile(r"^ {0,3}(\d{1,9})[.)](?:[ \t]|$)")
FORM_BREACH_RES = tuple(re.compile(pattern, flags) for pattern, flags in (
    (r"^ {0,3}#{1,6}(?:[ \t]|$)", 0),
    (r"^\s*(?:[-*+]\s+)?[*_]{0,2}status[*_]{0,2}\s*:", re.I),
    (r"^ {0,3}[-*+](?:[ \t]|$)", 0),
    (r"^ {0,3}(?:=+|-+|(?:[*_][ \t]*){3,})[ \t]*$", 0),
    (r"^ {0,3}(?:```|~~~)", 0),
    (r"^ {0,3}>", 0)))


def section(text: str, heading: str) -> str | None:
    match = re.search(rf"^##\s+{heading}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return match.group(1) if match else None


def table_rows(block: str | None) -> list[list[str]]:
    if not block:
        return []
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]


def budget_of(text: str) -> int | None:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    found = re.search(r"^budget:\s*(\d+)", match.group(1), re.M)
    return int(found.group(1)) if found else AREA_BUDGET_DEFAULT


def line_count(text: str) -> int:
    return len(text.splitlines())


def subdirs(parent: Path) -> list[Path]:
    return sorted(path for path in parent.iterdir() if path.is_dir() and not path.name.startswith("."))


def escapes(path: Path, root: Path) -> bool:
    """True when `path`, links followed, resolves outside `root` (already resolved)."""
    resolved = path.resolve()
    return resolved != root and root not in resolved.parents


def escape_finding(path: Path, root: Path) -> str:
    """The finding for a link that leaves the checkout, named by the link, never its target."""
    return f"{os.path.relpath(path, root)}: resolves outside the repository, so it is not read"


def area_dirs_agree(areas_dir: Path, areas: dict, rel_map: str, rel, root: Path) -> list[str]:
    """Every area directory owns a map row, and every map row lands in areas/."""
    errors: list[str] = []
    claimed: set[str] = set()
    for name, (area_file, _globs) in sorted(areas.items()):
        if area_file is None:
            continue
        try:
            claimed.add(area_file.relative_to(areas_dir).parts[0])
        except (ValueError, IndexError):
            errors.append(
                f"{rel_map}: area '{name}' points at {rel(area_file)}, outside docs/areas/ "
                f"— every area lives at docs/areas/<slug>/CONTEXT.md"
            )
    for area_dir in subdirs(areas_dir):
        if escapes(area_dir, root):
            errors.append(escape_finding(area_dir, root))
        elif area_dir.name not in claimed:
            errors.append(f"{rel(area_dir)}: area directory has no row in {rel_map}'s Areas table")
    return errors


def is_record_path(path: str) -> bool:
    """True for a repository-relative POSIX path docs/areas/<slug>/adr/<record>.md."""
    parts = path.split("/")
    return (len(parts) == 5 and parts[0] == "docs" and parts[1] == "areas"
            and bool(parts[2]) and parts[3] == "adr" and bool(ADR_FILE_RE.match(parts[4])))


def record_lines(content: bytes) -> list[str]:
    """The record's decoded lines, a trailing carriage return stripped from each."""
    text = content.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


class RecordParts(NamedTuple):
    """One record's bytes, split exactly: nothing is decoded and no '\\r' is dropped."""
    header: bytes
    formerly: bytes | None
    blank_bytes: int
    body: bytes


def record_parts(content: bytes) -> RecordParts:
    """The header line, a leading Formerly line, the bytes of the blank lines
    around the body, and the body's own bytes, line endings kept.

    The body runs from the first to the last non-blank line after the header
    and one well-formed leading Formerly line; a blank line counts whole, its
    spaces and carriage return included.
    """
    lines = re.findall(rb"[^\n]*\n|[^\n]+", content)
    header = lines[0].rstrip(b"\n") if lines else b""
    rest = lines[1:]
    start, end = 0, len(rest)
    while start < end and not rest[start].strip():
        start += 1
    while end > start and not rest[end - 1].strip():
        end -= 1
    edge = rest[:start] + rest[end:]
    body = rest[start:end]
    formerly = None
    if body and FORMERLY_BYTES_RE.match(body[0]):
        formerly = body[0].rstrip(b"\n")
        body = body[1:]
        after = 0
        while after < len(body) and not body[after].strip():
            after += 1
        edge, body = edge + body[:after], body[after:]
    return RecordParts(header, formerly, sum(len(line) for line in edge), b"".join(body))


def is_record_migration(old: bytes, new: bytes) -> bool:
    """True when a move left the record's substance alone, the whole difference
    bounded: the new header is well formed and keeps the old title; a leading
    Formerly line is well formed and names the old record (or repeats the old
    one); the body is byte for byte the old body; and the blank lines around it
    grow by at most `MIGRATION_BLANK_BYTES`. Nothing else may differ, so a
    migration adds no more than one header and one Formerly line."""
    before, after = record_parts(old), record_parts(new)
    old_header = OLD_HEADER_BYTES_RE.match(before.header)
    new_header = NEW_HEADER_BYTES_RE.match(after.header)
    if old_header is None or new_header is None or old_header["title"] != new_header["title"]:
        return False
    names_old = b"**Formerly:** ADR-" + old_header["slug"] + b"-" + old_header["number"]
    if after.formerly not in (None, names_old, before.formerly):
        return False
    return (before.body == after.body
            and after.blank_bytes <= before.blank_bytes + MIGRATION_BLANK_BYTES)


def form_breaches(content: bytes) -> list[int]:
    """The 1-based line of each breach of the record form, in line order."""
    lines = record_lines(content)
    breaches: set[int] = set()
    blocks: list[list[int]] = []
    previous_blank = True
    in_list = False
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            previous_blank = True
            in_list = False
            continue
        ordered = ORDERED_RE.match(line)
        # An ordered item starts a list at the top of a block, as "1.", or after
        # another item; any other number in mid-paragraph is prose.
        starts_list = ordered is not None and (
            previous_blank or in_list or int(ordered.group(1)) == 1)
        in_list = starts_list or any(
            pattern.match(line) for pattern in FORM_BREACH_RES[2:3])
        if (starts_list or any(pattern.match(line) for pattern in FORM_BREACH_RES)
                or (not previous_blank and LABEL_RE.match(line))):
            breaches.add(number)
        if previous_blank:
            blocks.append([])
        blocks[-1].append(number)
        previous_blank = False
    if blocks and len(blocks[0]) == 1 and FORMERLY_LINE_RE.match(lines[blocks[0][0] - 1]):
        blocks = blocks[1:]
    if not blocks:
        return [1]
    breaches.update(block[0] for block in blocks[1:])
    return sorted(breaches)


def record_violations(path: str, content: bytes) -> list[Violation]:
    """The B18 violation, then the B19 violation, of one record; at most one of each."""
    found = []
    if len(content) > RECORD_BYTES_CAP:
        line = content[:RECORD_BYTES_CAP].count(b"\n") + 1
        found.append(Violation(RECORD_SIZE_RULE, path, line, len(content)))
    breaches = form_breaches(content)
    if breaches:
        found.append(Violation(RECORD_FORM_RULE, path, breaches[0], len(breaches)))
    return found


def _record_violations_of(snapshot: Snapshot, rule: str) -> list[Violation]:
    return [violation for path in sorted(snapshot.blobs) if is_record_path(path)
            for violation in record_violations(path, snapshot.blobs[path])
            if violation.rule == rule]


def find_record_size(snapshot: Snapshot) -> list[Violation]:
    return _record_violations_of(snapshot, RECORD_SIZE_RULE)


def find_record_form(snapshot: Snapshot) -> list[Violation]:
    return _record_violations_of(snapshot, RECORD_FORM_RULE)


RECORD_SIZE_ENFORCER = Enforcer(
    RECORD_SIZE_RULE, find_record_size, per_file=True, carries=is_record_migration,
    exempts_carried=True,  # a move adds header and Formerly bytes the cap must not count
    carries_from=is_record_path, reads=is_record_path)
RECORD_FORM_ENFORCER = Enforcer(
    RECORD_FORM_RULE, find_record_form, per_file=True, carries=is_record_migration,
    carries_from=is_record_path, reads=is_record_path)
RECORD_ENFORCERS = (RECORD_SIZE_ENFORCER, RECORD_FORM_ENFORCER)


def added_records(verdict: Verdict) -> list[str]:
    """The records a change adds, a migration (a record moved, its body unchanged) excluded."""
    listed = []
    for path in sorted(verdict.added):
        if not is_record_path(path):
            continue
        source = verdict.renamed.get(path)
        if (source is not None and is_record_path(source)
                and is_record_migration(*verdict.rename_blobs[path])):
            continue
        listed.append(path)
    return listed


def index_records(areas_dir: Path, rel, root: Path) -> tuple[dict[tuple[str, str], Path], list[str]]:
    """Index docs/areas/*/adr/ by (slug, number), checking each record's shape."""
    index: dict[tuple[str, str], Path] = {}
    errors: list[str] = []
    for area_dir in subdirs(areas_dir):
        adr_dir = area_dir / "adr"
        if escapes(area_dir, root):
            continue  # reported once by area_dirs_agree
        if escapes(adr_dir, root):
            errors.append(escape_finding(adr_dir, root))
            continue
        if not adr_dir.is_dir():
            continue
        slug = area_dir.name
        taken: dict[str, Path] = {}
        for record in sorted(adr_dir.glob("*.md")):
            if escapes(record, root):
                errors.append(escape_finding(record, root))
                continue
            rel_record = rel(record)
            name_match = ADR_FILE_RE.match(record.name)
            if not name_match:
                errors.append(
                    f"{rel_record}: ADR filename must be NNN-kebab-title.md "
                    f"— an adr/ directory holds records and nothing else, it indexes itself"
                )
                continue
            number = name_match.group(1)
            if number in taken:
                errors.append(f"{rel_record}: number {number} is already {rel(taken[number])} — numbers are unique per directory")
            taken.setdefault(number, record)
            index[(slug, number)] = record

            header = next(iter(record.read_text().splitlines()), "")
            header_match = ADR_HEADER_RE.match(header)
            if not header_match:
                errors.append(f"{rel_record}: first line must be `# ADR-{slug}-{number} — Title`, found `{header[:60]}`")
            elif header_match.group(1) != slug:
                errors.append(f"{rel_record}: header claims area '{header_match.group(1)}' but the record lives in '{slug}'")
            elif header_match.group(2) != number:
                errors.append(f"{rel_record}: header number {header_match.group(2)} does not match the filename's {number}")
    return index, errors


def check_citations(docs: Path, index: dict[tuple[str, str], Path], rel, root: Path) -> list[str]:
    """Every ADR citation under docs/ resolves; no retired four-digit id survives."""
    errors: list[str] = []
    for doc in sorted(docs.rglob("*.md")):
        if escapes(doc, root):
            errors.append(escape_finding(doc, root))
            continue
        try:
            text = doc.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        archived = doc.relative_to(docs).parts[0] == "archive"
        rel_doc = rel(doc)
        for number, line in enumerate(text.splitlines(), 1):
            if FORMERLY in line:
                continue  # a Formerly line points at where a record used to be, by design
            for slug, serial in CITATION_RE.findall(line):
                if (slug, serial) not in index:
                    errors.append(f"{rel_doc}:{number}: cites ADR-{slug}-{serial}, which has no record under docs/areas/{slug}/adr/")
            if archived:
                continue  # docs/archive/ records what happened; its citations are history
            for retired in RETIRED_ID_RE.findall(line):
                errors.append(f"{rel_doc}:{number}: {retired} is a retired four-digit id — cite the record's current ADR-<slug>-NNN")
    return errors


def check_docs_root(docs: Path, rel, root: Path) -> list[str]:
    """The docs root holds two files and the reserved directories, plus whatever README routes."""
    errors: list[str] = []
    readme = docs / "README.md"
    routed = readme.read_text() if readme.is_file() and not escapes(readme, root) else ""
    for entry in sorted(docs.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.name not in ROOT_FILES:
            errors.append(
                f"{rel(entry)}: the docs root holds only README.md and CONTEXT-MAP.md "
                f"— move this under areas/, standards/, operations/, guides/ or archive/"
            )
        elif entry.is_dir() and entry.name not in RESERVED_DIRS and f"{entry.name}/" not in routed:
            errors.append(
                f"{rel(entry)}: not a reserved docs directory "
                f"— give it a row in docs/README.md's routing table, or fold it into a reserved one"
            )
    return errors


def check(root: Path, map_path: Path) -> list[str]:
    def rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return str(path)

    errors: list[str] = []
    areas_dir = (root / "docs" / "areas").resolve()
    if not map_path.is_file():
        return [f"{rel(map_path)}: selected context map does not exist"]

    text = map_path.read_text()
    rel_map = rel(map_path)

    if line_count(text) > MAP_BUDGET:
        errors.append(f"{rel_map}: {line_count(text)} lines, budget {MAP_BUDGET} — the map is an index, not a store")

    # Relative links in the map must resolve.
    for target in LINK_RE.findall(text):
        target = target.split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (map_path.parent / target).exists():
            errors.append(f"{rel_map}: broken link -> {target}")

    # Areas table: name -> (file, globs).
    areas: dict[str, tuple[Path | None, list[str]]] = {}
    for row in table_rows(section(text, "Areas")):
        if len(row) < 4:
            errors.append(f"{rel_map}: Areas row needs 4 cells (Area | Context file | Gist | governs): {' | '.join(row)}")
            continue
        name, link_cell, _gist, governs_cell = row[0], row[1], row[2], row[3]
        link = LINK_RE.search(link_cell)
        area_file = None
        if not link:
            errors.append(f"{rel_map}: area '{name}' has no link to a context file")
        else:
            area_file = (map_path.parent / link.group(1).split("#", 1)[0]).resolve()
        globs = CODE_RE.findall(governs_cell)
        if not globs:
            errors.append(f"{rel_map}: area '{name}' declares no `governs:` globs")
        for pattern in globs:
            try:
                matched = next(root.glob(pattern), None)
            except (ValueError, IndexError, NotImplementedError):
                matched = None
                errors.append(f"{rel_map}: area '{name}' has an unparseable glob `{pattern}`")
                continue
            if matched is None:
                errors.append(f"{rel_map}: area '{name}' glob `{pattern}` matches no existing path")
        areas[name] = (area_file, globs)

    if not areas:
        errors.append(f"{rel_map}: no '## Areas' table found")

    # Area files: budget, and the terms they define.
    defined: dict[Path, set[str]] = {}
    for name, (area_file, _globs) in areas.items():
        if area_file is None:
            continue
        if root.resolve() not in area_file.parents:
            # Contained before it is opened: an area file the map points outside
            # the checkout is a finding, never read.
            errors.append(f"{rel_map}: area '{name}' points at {rel(area_file)}, outside the repository")
            continue
        if not area_file.is_file():
            errors.append(f"{rel_map}: area '{name}' points at missing file {rel(area_file)}")
            continue
        area_text = area_file.read_text()
        rel_area = rel(area_file)
        budget = budget_of(area_text)
        if budget is None:
            errors.append(f"{rel_area}: missing front-matter (needs `area:` and `budget:`)")
        elif line_count(area_text) > budget:
            errors.append(f"{rel_area}: {line_count(area_text)} lines, budget {budget} — consolidate or split")
        defined[area_file] = {term.strip() for term in TERM_DEF_RE.findall(area_text)}

    # Terms table: every term resolves to an area that defines it.
    listed: set[str] = set()
    for row in table_rows(section(text, "Terms")):
        if len(row) < 2:
            errors.append(f"{rel_map}: Terms row needs 2 cells (Term | Area): {' | '.join(row)}")
            continue
        term = row[0].strip("*` ")
        area = row[1].strip()
        listed.add(term)
        if area not in areas:
            errors.append(f"{rel_map}: term '{term}' names unknown area '{area}'")
            continue
        area_file = areas[area][0]
        if area_file is None or area_file not in defined:
            continue
        if term not in defined[area_file]:
            errors.append(f"{rel_map}: term '{term}' is not defined in {rel(area_file)} (expected a `**{term}**:` entry)")

    # And every defined term is listed exactly once in the map.
    for area_file, terms in defined.items():
        for term in sorted(terms - listed):
            errors.append(f"{rel(area_file)}: term '{term}' is defined but missing from the map's term table")

    # The standard docs layout — only where the repo has adopted it.
    if areas_dir.is_dir() and root.resolve() not in areas_dir.parents:
        # Contained before it is listed: a docs/areas that resolves outside the
        # checkout is a finding, and neither it nor its siblings are read.
        errors.append("docs/areas: resolves outside the repository, so docs/ is not linted")
    elif areas_dir.is_dir():
        contained = root.resolve()
        errors += area_dirs_agree(areas_dir, areas, rel_map, rel, contained)
        records, record_errors = index_records(areas_dir, rel, contained)
        errors += record_errors
        errors += check_citations(areas_dir.parent, records, rel, contained)
        errors += check_docs_root(areas_dir.parent, rel, contained)
        errors = list(dict.fromkeys(errors))  # a link is reported once, by the first check to meet it

    return errors


def run_repo_lint(command: list[str], cwd: Path) -> int:
    """Defer to the repository's own lint: its exit status is this tool's."""
    try:
        status = subprocess.run(command, cwd=cwd).returncode
    except OSError as error:
        print(f"context-map-lint: cannot run the repository's lint {command[0]}: {error}", file=sys.stderr)
        return 2
    return status if status >= 0 else 1


def main(argv: list[str]) -> int:
    supplied_cwd = None
    if argv[5:6] == ["--repo-lint-cwd"] and argv[7:8] == ["--repo-lint"]:
        supplied_cwd = Path(argv[6])
        argv = argv[:5] + argv[7:]
    repo_lint = argv[6:] if argv[5:6] == ["--repo-lint"] else None
    if repo_lint is not None:
        argv = argv[:5]
    if len(argv) != 5 or argv[1] != "--repo-root" or argv[3] != "--context-map" or repo_lint == []:
        print(__doc__, file=sys.stderr)
        return 2
    supplied_root = Path(argv[2])
    supplied_map = Path(argv[4])
    if not supplied_root.is_absolute() or not supplied_map.is_absolute():
        print("context-map-lint: --repo-root and --context-map must be absolute", file=sys.stderr)
        return 2
    root = supplied_root.resolve()
    if not root.is_dir():
        print(f"context-map-lint: not a directory: {root}", file=sys.stderr)
        return 2
    map_path = supplied_map.resolve()
    try:
        map_path.relative_to(root)
    except ValueError:
        print(f"context-map-lint: context map is outside repository root: {map_path}", file=sys.stderr)
        return 2

    if repo_lint is not None:
        if supplied_cwd is None:
            return run_repo_lint(repo_lint, root)
        if not supplied_cwd.is_absolute():
            print("context-map-lint: --repo-lint-cwd must be absolute", file=sys.stderr)
            return 2
        lint_cwd = supplied_cwd.resolve()
        if not lint_cwd.is_dir() or not lint_cwd.is_relative_to(root):
            print(f"context-map-lint: --repo-lint-cwd is not a directory inside the repository root: {lint_cwd}", file=sys.stderr)
            return 2
        return run_repo_lint(repo_lint, lint_cwd)

    errors = check(root, map_path)
    if not errors:
        print(f"context-map-lint: {root} OK")
        return 0
    print(f"context-map-lint: {len(errors)} problem(s) in {root}\n", file=sys.stderr)
    for error in errors:
        print(f"  {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
