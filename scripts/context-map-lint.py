#!/usr/bin/env python3
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

Usage: context-map-lint [REPO_ROOT]   (default: cwd)
Exits 0 when clean or when the repo has no map yet, 1 on findings, 2 on misuse.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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


def find_map(root: Path) -> Path | None:
    config = root / ".claude" / "skills.config.json"
    if config.is_file():
        try:
            configured = json.loads(config.read_text()).get("docPaths", {}).get("contextMap")
        except (json.JSONDecodeError, AttributeError):
            configured = None
        if configured:
            return root / configured
    for candidate in (root / "docs" / "CONTEXT-MAP.md", root / "CONTEXT-MAP.md"):
        if candidate.is_file():
            return candidate
    return None


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


def area_dirs_agree(areas_dir: Path, areas: dict, rel_map: str, rel) -> list[str]:
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
        if area_dir.name not in claimed:
            errors.append(f"{rel(area_dir)}: area directory has no row in {rel_map}'s Areas table")
    return errors


def index_records(areas_dir: Path, rel) -> tuple[dict[tuple[str, str], Path], list[str]]:
    """Index docs/areas/*/adr/ by (slug, number), checking each record's shape."""
    index: dict[tuple[str, str], Path] = {}
    errors: list[str] = []
    for area_dir in subdirs(areas_dir):
        adr_dir = area_dir / "adr"
        if not adr_dir.is_dir():
            continue
        slug = area_dir.name
        taken: dict[str, Path] = {}
        for record in sorted(adr_dir.glob("*.md")):
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


def check_citations(docs: Path, index: dict[tuple[str, str], Path], rel) -> list[str]:
    """Every ADR citation under docs/ resolves; no retired four-digit id survives."""
    errors: list[str] = []
    for doc in sorted(docs.rglob("*.md")):
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


def check_docs_root(docs: Path, rel) -> list[str]:
    """The docs root holds two files and the reserved directories, plus whatever README routes."""
    errors: list[str] = []
    readme = docs / "README.md"
    routed = readme.read_text() if readme.is_file() else ""
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


def check(root: Path) -> list[str]:
    def rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return str(path)

    errors: list[str] = []
    areas_dir = (root / "docs" / "areas").resolve()
    map_path = find_map(root)
    if map_path is None:
        if areas_dir.is_dir():
            return ["docs/areas/: areas exist but no context map was found — the map is what names them"]
        return []
    if not map_path.is_file():
        return [f"{rel(map_path)}: configured context map does not exist"]

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
            except (ValueError, IndexError):
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
    if areas_dir.is_dir():
        errors += area_dirs_agree(areas_dir, areas, rel_map, rel)
        records, record_errors = index_records(areas_dir, rel)
        errors += record_errors
        errors += check_citations(areas_dir.parent, records, rel)
        errors += check_docs_root(areas_dir.parent, rel)

    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[1] if len(argv) == 2 else ".").resolve()
    if not root.is_dir():
        print(f"context-map-lint: not a directory: {root}", file=sys.stderr)
        return 2

    errors = check(root)
    if not errors:
        print(f"context-map-lint: {root} OK")
        return 0
    print(f"context-map-lint: {len(errors)} problem(s) in {root}\n", file=sys.stderr)
    for error in errors:
        print(f"  {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
