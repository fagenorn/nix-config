"""The engine's one reader of rule ids: the `###` rule headings of the standards layers.

A rule heading is `### B12. Fail loud`: the heading hashes, one id (capital letters then a number
with no leading zero), a full stop, then the title. `RULE_ID_HEADING` is the form's single home.
This module is the engine's only reader of rule ids (by owner ruling), so it imports nothing from `agent_tools`: importing it brings no other delivery
module into the engine package.

`scan` reads a Markdown file the way CommonMark renders it, skipping fences, indented code and HTML
blocks, so a rule commented out or shown as an example defines nothing. The platform layer is
`the-bar.md` and each `stacks/*.md` of the platform standards directory (`platform_rules`); the
project layer is each `*.md` of the project's standards directory except `README.md`
(`project_rules`). A shard is read only when it is a regular file, so a pipe or a directory named
`*.md` is never opened. A heading names a rule only when it has one id (`rule_match`): one whose
title opens with a second id (`### P98. P99. Example`) defines none.

`known_ids` is the ids a citation may name: the platform layer's ids that do not carry the project
prefix (`P`), united with the project layer's ids that do. A layer whose read raises `OSError` or
`ValueError` (a missing `the-bar.md`, a missing directory, undecodable text) adds no id; `known_ids`
never raises.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

RULE_ID_HEADING = re.compile(
    r"^(?P<hashes>#{1,6}) (?P<prefix>[A-Z]+)(?P<number>[1-9][0-9]*)\. (?P<title>\S.*)$")
SECOND_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]+[0-9]+\.(?=\s|$)")
PROJECT_PREFIX = "P"
PROJECT_STANDARDS = "docs/standards"
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_LINE = re.compile(r"^ {0,3}(?:(?:>|[-*+]|[0-9]+[.)])[ \t]+ {0,3}|>)*#{1,6}(\s|$)")


def prefix_of(rule_id: str) -> str:
    """The leading capital letters of `rule_id` (`PY3` is `PY`)."""
    return re.match(r"[A-Z]*", rule_id)[0]


BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|"
    "div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|"
    "legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|"
    "table|tbody|td|tfoot|th|thead|title|tr|track|ul")
ATTRIBUTE = r"""\s+[A-Za-z_:][\w:.-]*(?:\s*=\s*(?:[^\s"'=<>`]+|'[^']*'|"[^"]*"))?"""
# CommonMark HTML blocks 1-5 end at a marker on a line; 6 and 7 end at a blank line (7 cannot
# interrupt a paragraph).
HTML_MARKED = (
    (re.compile(r" {0,3}<(?:pre|script|style|textarea)(?:\s|>|$)", re.I),
     re.compile(r"</(?:pre|script|style|textarea)>", re.I)),
    (re.compile(r" {0,3}<!--"), re.compile(r"-->")),
    (re.compile(r" {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r" {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r" {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
)
HTML_BLANK_END = re.compile(rf" {{0,3}}</?(?:{BLOCK_TAGS})(?:\s|/?>|$)", re.I)
HTML_LONE_TAG = re.compile(
    rf" {{0,3}}(?:<[A-Za-z][A-Za-z0-9-]*(?:{ATTRIBUTE})*\s*/?>|</[A-Za-z][A-Za-z0-9-]*\s*>)\s*$")
LIST_MARKER = re.compile(r"( *)([-*+]|[0-9]{1,9}[.)])( +|$)")
THEMATIC_BREAK = re.compile(r" *([-*_])(?: *\1){2,} *")


def scan(text: str):
    """`(line number, line, content)` of every line outside a ``` or ~~~ fence, indented code and an HTML block.

    The fence, indented-code and HTML lines are excluded. `content` is the line with the content column of the
    list item it continues removed, which is how it reads when rendered; `line` is as written.
    An HTML block opens at CommonMark's seven start conditions and ends at its end condition.
    """
    fence: tuple[str, int] | None = None
    html: re.Pattern | None = None   # the end marker of an open block 1-5
    until_blank = False              # an open block 6 or 7
    paragraph = False
    columns: list[int] = []
    for number, raw in enumerate(text.removesuffix("\n").split("\n"), 1):
        line = raw.rstrip()
        indent = len(line) - len(line.lstrip(" "))
        popped = False
        if line:
            while columns and indent < columns[-1]:
                columns.pop()
                popped = True
            if popped:  # the list item ends, and with it any fence or HTML block it holds
                fence, html, until_blank = None, None, False
        content = line[min(columns[-1] if columns else 0, indent):]
        if fence is not None:
            char, size = fence
            if re.fullmatch(rf" {{0,3}}{re.escape(char)}{{{size},}}[ \t]*", content):
                fence = None
            continue
        if html is not None:
            if html.search(line):
                html, paragraph = None, False
            continue
        if until_blank:
            if line:
                continue
            until_blank = False
        if not line:
            paragraph = False
            continue
        if not paragraph and len(content) - len(content.lstrip(" ")) >= 4:
            continue   # indented code: four columns past the content column, not a paragraph continuation
        rest, opens_item = content, False   # `rest` is what follows the list markers of the line
        while True:
            item = LIST_MARKER.match(rest)
            if not item or THEMATIC_BREAK.fullmatch(rest):
                break
            if paragraph and not popped and not opens_item and (
                    item.end() == len(rest) or (item[2][-1] in ".)" and int(item[2][:-1]) != 1)):
                break  # an empty item or an ordered one not starting at 1 cannot interrupt a paragraph
            spaces = len(item[3])
            columns.append((columns[-1] if columns else 0) + len(item[1]) + len(item[2])
                           + (spaces if 0 < spaces < 5 else 1))
            rest = rest[len(item[1]) + len(item[2]) + (spaces if 0 < spaces < 5 else min(spaces, 1)):]
            opens_item = True
        opened = FENCE_OPEN.match(rest)
        if opened:
            fence, paragraph = (opened.group(1)[0], len(opened.group(1))), False
            continue
        marked = next((end for start, end in HTML_MARKED if start.match(rest)), None)
        if marked:
            paragraph = False
            if not marked.search(rest):
                html = marked
            continue
        if HTML_BLANK_END.match(rest) or ((opens_item or not paragraph) and HTML_LONE_TAG.match(rest)):
            until_blank, paragraph = True, False
            continue
        paragraph = not HEADING_LINE.match(content)
        yield number, line, content


def rule_match(line: str):
    """The id match of a well-formed rule heading (a `###` heading with one id), else None."""
    found = RULE_ID_HEADING.match(line)
    if found and found["hashes"] == "###" and not SECOND_ID.search(found["title"]):
        return found
    return None


class Rule(NamedTuple):
    id: str
    title: str


def _headings(path: Path) -> list[Rule]:
    rules = []
    for _, _, line in scan(path.read_text("utf-8")):
        match = rule_match(line)
        if match:
            rules.append(Rule(match["prefix"] + match["number"], match["title"]))
    return rules


def platform_rules(directory: Path) -> list[Rule]:
    """The rules of `the-bar.md`, then of each `stacks/*.md` by name, in file order."""
    bar = directory / "the-bar.md"
    if not bar.is_file():
        raise ValueError(f"{directory} has no the-bar.md")
    rules = _headings(bar)
    for shard in sorted((directory / "stacks").glob("*.md")):
        if shard.is_file():
            rules += _headings(shard)
    return rules


def project_rules(directory: Path) -> list[Rule]:
    """The rules of each `*.md` of `directory` but `README.md`, by name, in file order."""
    rules: list[Rule] = []
    for shard in sorted(directory.glob("*.md")):
        if shard.name != "README.md" and shard.is_file():
            rules += _headings(shard)
    return rules


def known_ids(platform: Path, project: Path) -> frozenset[str]:
    """The ids a citation may name: platform ids that are not `P` ids, and project `P` ids; never raises."""
    ids: set[str] = set()
    try:
        ids |= {r.id for r in platform_rules(platform) if prefix_of(r.id) != PROJECT_PREFIX}
    except (OSError, ValueError):
        pass
    try:
        ids |= {r.id for r in project_rules(project) if prefix_of(r.id) == PROJECT_PREFIX}
    except (OSError, ValueError):
        pass
    return frozenset(ids)
