"""Lint the authored skill trees against rules L1–L5, and own the skill-tree knowledge instruction_load shares."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from typing import Callable, Optional

from agent_tools.agent_model_matrix import AGENTS_PATH, MATRIX_PATH, parse_matrix


SHARED_TREE = "home/common/agent-skills/skills"
CLAUDE_TREE = "home/common/claude-code/skills"
CODEX_TREE = "home/common/codex/skills"
TREE_ROOTS = (SHARED_TREE, CLAUDE_TREE, CODEX_TREE)
AGENTS_DIR = AGENTS_PATH.as_posix()
EXCLUDED_DIRS = ("evals", "scripts")
REFLOW_WIDTH = 100

Reader = Callable[[str], Optional[bytes]]
Lister = Callable[[str], list[str]]

BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_-])"
BOUNDARY_AFTER = r"(?![A-Za-z0-9_-])"
BASENAME_BEFORE = r"(?<![A-Za-z0-9_.-])(?<![A-Za-z0-9_-]/)"   # not inside "<skill>/<file>"
MD_TOKEN = re.compile(BASENAME_BEFORE + r"([A-Za-z0-9_-]+\.md)" + BOUNDARY_AFTER)

_FRONTMATTER_LINE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?")
_BLOCK_SCALARS = (">", "|", ">-", "|-", ">+", "|+")


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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
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
