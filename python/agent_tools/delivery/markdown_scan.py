"""The lines of a Markdown text that render as text, not as a fence or an HTML block (#1442).

`scan` yields every line outside a ``` or ~~~ fence and an HTML block, so a heading
commented out or shown as an example is not read as a heading. The standards lint
(`agent_tools.delivery.standards_lint`) and the rule-heading test read standards
through it, so both agree on what a rule heading is.
"""

import re
from typing import Iterator

from agent_tools.delivery.look_marker import FENCE_OPEN

HEADING_LINE = re.compile(r"^ {0,3}(?:(?:>|[-*+]|[0-9]+[.)])[ \t]+ {0,3}|>)*#{1,6}(\s|$)")


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


def scan(text: str) -> Iterator[tuple[int, str, str]]:
    """`(line number, line, content)` of every line outside a ``` or ~~~ fence and an HTML block.

    The fence and HTML lines are excluded. `content` is the line with the content column of the
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
