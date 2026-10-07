"""Lint the authored skill trees against rules L1–L5, and own the skill-tree knowledge instruction_load shares."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Callable, Optional

from agent_tools.agent_model_matrix import AGENTS_PATH, MATRIX_PATH, parse_matrix
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal


SHARED_TREE = "home/common/agent-skills/skills"
CLAUDE_TREE = "home/common/claude-code/skills"
CODEX_TREE = "home/common/codex/skills"
TREE_ROOTS = (SHARED_TREE, CLAUDE_TREE, CODEX_TREE)
AGENTS_DIR = AGENTS_PATH.as_posix()
EXCLUDED_DIRS = ("evals", "scripts")
REFLOW_WIDTH = 100
DEBT_PATH = "home/common/agent-skills/skill-lint-debt.json"
TRIGGERS = ("Use when", "Use for", "Use to", "Use before", "Use after", "Invoke before")
XML = re.compile(r"<[A-Za-z/]")

Reader = Callable[[str], Optional[bytes]]
Lister = Callable[[str], list[str]]

BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_-])"
BOUNDARY_AFTER = r"(?![A-Za-z0-9_-])"
BASENAME_BEFORE = r"(?<![A-Za-z0-9_.-])(?<![A-Za-z0-9_-]/)"   # not inside "<skill>/<file>"
MD_TOKEN = re.compile(BASENAME_BEFORE + r"([A-Za-z0-9_-]+\.md)" + BOUNDARY_AFTER)

_FRONTMATTER_LINE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?")
_BLOCK_SCALARS = (">", "|", ">-", "|-", ">+", "|+")
_NAME = re.compile(r"[a-z0-9-]+")


@dataclass(frozen=True)
class Snapshot:
    """A repository state: read one file, and list every file under a prefix."""

    read: Reader
    list_files: Lister


def tree_reader(root: Path) -> Reader:
    """Read repository-relative POSIX paths under `root`, matching names exactly."""

    def read(path: str) -> Optional[bytes]:
        current = Path(root)
        try:
            for part in path.split("/"):
                if part not in os.listdir(current):
                    return None
                current = current / part
            return current.read_bytes() if current.is_file() else None
        except OSError:
            return None

    return read


def read_listed(snapshot: Snapshot, path: str) -> bytes:
    """The bytes of a file `snapshot` listed: one that then reads as None is an error, not empty."""
    raw = snapshot.read(path)
    if raw is None:
        raise ValueError(f"cannot read {path}")
    return raw


def tree_lister(root: Path) -> Lister:
    """List the sorted repository-relative POSIX paths of regular files under a prefix."""

    def list_files(prefix: str) -> list[str]:
        found = []
        for directory, _, names_here in os.walk(Path(root) / prefix, followlinks=False):
            for name in names_here:
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    found.append(Path(os.path.relpath(path, root)).as_posix())
        return sorted(found)

    return list_files


def working_tree(root: Path) -> Snapshot:
    return Snapshot(tree_reader(root), tree_lister(root))


def split_member(member: object) -> Optional[tuple[str, str]]:
    """`(skill, file)` for a `<skill>/<file>` spelling, else None."""
    parts = member.split("/") if isinstance(member, str) else []
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def names(source: str, text: str, target: str) -> bool:
    """Whether document `source`, whose content is `text`, names `target`."""
    parts = split_member(target)
    if parts is None:
        return False
    skill, name = parts
    if re.search(BOUNDARY_BEFORE + re.escape(target) + BOUNDARY_AFTER, text):
        return True
    source_parts = split_member(source)
    if source_parts is not None and source_parts[0] == skill and re.search(
        BASENAME_BEFORE + re.escape(name) + BOUNDARY_AFTER, text
    ):
        return True
    return name == "SKILL.md" and f"`{skill}`" in text


def reflowed_lines(text: str) -> int:
    """Lines of `text`, each counted once per hundred decoded characters it spans."""
    return sum(max(1, math.ceil(len(line) / REFLOW_WIDTH)) for line in text.splitlines())


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """The single-line scalar fields of a leading `---` block, and the body after it."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("frontmatter: no opening --- line")
    close = next(
        (index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == "---"),
        None,
    )
    if close is None:
        raise ValueError("frontmatter: no closing --- line")
    fields: dict[str, str] = {}
    for raw in lines[1:close]:
        line = raw.rstrip("\r\n")
        match = _FRONTMATTER_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"frontmatter: cannot read line {line!r}")
        key, value = match.group(1), (match.group(2) or "").strip()
        if value in _BLOCK_SCALARS:
            raise ValueError(f"frontmatter: {key} is a block scalar")
        if value.startswith("#"):
            value = ""  # YAML reads a value that opens with `#` as a comment: no value
        if value[:1] in ("\"", "'") or value[-1:] in ("\"", "'"):
            if len(value) < 2 or value[0] != value[-1]:
                raise ValueError(f"frontmatter: {key} has an unterminated quote")
            value = value[1:-1]
        if key in fields:
            raise ValueError(f"frontmatter: duplicate key {key}")
        fields[key] = value
    return fields, "".join(lines[close + 1:])


@dataclass(frozen=True)
class SkillDir:
    tree: str
    name: str
    path: str
    skill_md: Optional[str]
    references: tuple[str, ...]
    payloads: tuple[str, ...]


def _dispatch_sites(snapshot: Snapshot) -> list[dict]:
    source = MATRIX_PATH.as_posix()
    raw = snapshot.read(source)
    if raw is None:
        raise ValueError(f"matrix: {source} is absent")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"matrix: cannot load {source}: {error}") from error
    sites = parse_matrix(text, source).get("dispatch_sites")
    if not isinstance(sites, list):
        raise ValueError(f"matrix: {source}: dispatch_sites must be a list")
    return [
        site for site in sites
        if isinstance(site, dict)
        and isinstance(site.get("path"), str)
        and isinstance(site.get("call"), str)
    ]


def skill_dirs(snapshot: Snapshot) -> list[SkillDir]:
    """Every skill directory of the three trees, with its references and payloads classified."""
    sites = _dispatch_sites(snapshot)
    found: list[SkillDir] = []
    for root in TREE_ROOTS:
        files = snapshot.list_files(root)
        skills = sorted({
            parts[0]
            for parts in (path[len(root) + 1:].split("/") for path in files)
            if len(parts) > 1
        })
        if not any(f"{root}/{name}/SKILL.md" in files for name in skills):
            raise ValueError(f"{root}: no skill found")
        for name in skills:
            path = f"{root}/{name}"
            docs = sorted(
                file for file in files
                if file.startswith(path + "/") and file.endswith(".md")
                and file[len(path) + 1:].split("/")[0] not in EXCLUDED_DIRS
            )
            skill_md = f"{path}/SKILL.md"
            call_names = {
                token
                for site in sites if site["path"].startswith(path + "/")
                for token in MD_TOKEN.findall(site["call"])
            }
            others = [doc for doc in docs if doc != skill_md]
            payloads = tuple(
                doc for doc in others
                if doc.endswith("-prompt.md") or doc.rsplit("/", 1)[-1] in call_names
            )
            found.append(SkillDir(
                tree=root,
                name=name,
                path=path,
                skill_md=skill_md if skill_md in files else None,
                references=tuple(doc for doc in others if doc not in payloads),
                payloads=payloads,
            ))
    return found


@dataclass(frozen=True, order=True)
class Violation:
    key: str
    text: str


def has_contents(text: str) -> bool:
    """Whether the first `## ` heading outside code fences is `## Contents`, followed by a list."""
    lines = text.splitlines()
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line.startswith("## "):
            continue
        if line != "## Contents":
            return False
        following = next((rest for rest in lines[index + 1:] if rest.strip()), "")
        return following.startswith(("- ", "1. "))
    return False


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _frontmatter_violations(directory: SkillDir, path: str, fields: dict[str, str]) -> list[Violation]:
    found: list[Violation] = []

    def add(rule: str, text: str) -> None:
        found.append(Violation(f"{rule} {path}", text))

    name = fields.get("name")
    if name is None:
        add("L1", "missing name")
    else:
        if name != directory.name:
            add("L1", f"name {name!r} differs from its directory {directory.name!r}")
        if len(name) > 64:
            add("L1", "name is longer than 64 characters")
        if not _NAME.fullmatch(name):
            add("L1", "name must match [a-z0-9-]+")
        if "anthropic" in name or "claude" in name:
            add("L1", "name contains 'anthropic' or 'claude'")
        if XML.search(name):
            add("L1", "name contains XML")
    description = fields.get("description")
    if description is None:
        add("L1", "missing description")
    elif not description:
        add("L1", "description is empty")
    else:
        if len(description) > 1024:
            add("L1", "description is longer than 1024 characters")
        if XML.search(description):
            add("L1", "description contains XML")
        if description.startswith(("I ", "You ")):
            add("L5", "description opens with 'I ' or 'You '")
        if not any(trigger in description for trigger in TRIGGERS):
            add("L5", "description has no trigger clause "
                      "(Use when, Use for, Use to, Use before, Use after, Invoke before)")
    return found


def _directory_violations(snapshot: Snapshot, directory: SkillDir) -> list[Violation]:
    if directory.skill_md is None:
        return [Violation(f"L1 {directory.path}/SKILL.md", "missing SKILL.md")]
    path = directory.skill_md
    try:
        text = read_listed(snapshot, path).decode("utf-8")
    except UnicodeDecodeError:
        return [Violation(f"L1 {path}", "SKILL.md is not UTF-8")]
    found: list[Violation] = []
    try:
        fields, body = parse_frontmatter(text)
    except ValueError as error:
        found.append(Violation(f"L1 {path}", str(error)))
        body = text
    else:
        found.extend(_frontmatter_violations(directory, path, fields))
    lines = reflowed_lines(body)
    if lines > 500:
        found.append(Violation(f"L2 {path}", f"body is {lines} reflowed lines, over 500"))
    for reference in directory.references:
        reference_text = read_listed(snapshot, reference).decode("utf-8", "replace")
        lines = reflowed_lines(reference_text)
        if lines > 100 and not has_contents(reference_text):
            found.append(Violation(
                f"L3 {reference}",
                f"{lines} reflowed lines and no ## Contents list before its first other ## heading"))
        if not names(f"{directory.name}/SKILL.md", text,
                     f"{directory.name}/{_basename(reference)}"):
            found.append(Violation(f"L4a {reference}", "not named in its SKILL.md"))
        for other in directory.references:
            if other != reference and names(f"{directory.name}/{_basename(reference)}",
                                            reference_text,
                                            f"{directory.name}/{_basename(other)}"):
                found.append(Violation(
                    f"L4b {reference} names {_basename(other)}",
                    f"names the sibling reference file {_basename(other)}"))
    return found


def violations(snapshot: Snapshot) -> list[Violation]:
    """Every L1-L5 violation of the three skill trees, sorted, without duplicates."""
    found: list[Violation] = []
    for directory in skill_dirs(snapshot):
        found.extend(_directory_violations(snapshot, directory))
    return sorted(set(found))


def load_debt(raw: bytes) -> list[str]:
    """The debt keys of the committed debt file, which must be sorted and unique."""
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_literal,
        )
    except ValueError as error:
        raise ValueError(f"cannot load {DEBT_PATH}: {error}") from error
    debt = document.get("debt") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != {"debt"}
        or not isinstance(debt, list)
        or not all(isinstance(key, str) for key in debt)
        or debt != sorted(set(debt))
    ):
        raise ValueError(f'{DEBT_PATH}: must be {{"debt": [sorted unique keys]}}')
    return debt


def lint(snapshot: Snapshot) -> list[str]:
    """One failure line per unlisted violation, then one per stale debt key."""
    raw = snapshot.read(DEBT_PATH)
    if raw is None:
        raise ValueError(f"{DEBT_PATH} is absent")
    debt = load_debt(raw)
    found = violations(snapshot)
    listed = set(debt)
    produced = {violation.key for violation in found}
    lines = [f"{v.key}: {v.text}" for v in found if v.key not in listed]
    lines.extend(
        f"{key}: stale debt entry; delete it from {DEBT_PATH}"
        for key in debt if key not in produced
    )
    return lines


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="skill-lint")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="lint the skill trees against the debt file")
    check.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        lines = lint(working_tree(args.root))
    except (ValueError, OSError) as error:
        print(f"skill-lint: {' '.join(str(error).split())}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
