"""The written form of a standard's rule id in its heading (#1438).

A rule heading is `### B12. Fail loud`: the heading hashes, one id (capital
letters then a number with no leading zero), a full stop, then the title.
`agent_tools.delivery.rule_reader.RULE_ID_HEADING` is the single home of that form
(with the fence-aware `scan`) and `without_rule_id` removes
the one id from a matching `###` rule heading, leaving every other line (a
heading of another level included) unchanged.

An enforcer names a rule by the citation `standard:<id>`, as in `standard:B12`
(#1442). `citations` returns every citation in a text with its 1-based line and
whether its token is a well-formed id; the project shards' ids carry
`rule_reader.PROJECT_PREFIX` and resolve against the project's own shards.

A citation is `standard:` not glued to a word and followed with no space by a run of
non-space characters. Its token is that run less the sentence punctuation closing it (`.`,
`,`, a closing bracket or quote, a backtick), or the run whole when only punctuation remains.
So any such run that is no id is malformed, whatever its first or following character is;
`standard:` followed by a space or the end of the text is prose and no citation.

A suppression marker is `suppress-standard:<id> <reason>` (#1459): the literal
`SUPPRESS`, not glued to a word, then at once a token, then free text. `markers`
returns the first marker of each line (1-based, numbered as the lines of the file are
counted) as a `Marker(line, rule, reason)`. `rule` is the token when it is a well-formed
id, else `None` (a token that is no id is discarded, never part of the reason). The
reason is the text after the token, stripped, less one trailing `-->` or `*/` comment
closer. A marker is reasoned (`is_reasoned`) when it names a rule and its reason holds
a letter or a digit; any other marker is bare. In a Python file (`is_python`, `markers(text,
python=True)`) a marker is read only inside a comment token, so text in a string literal,
a docstring included, is no marker; a file the Python tokenizer rejects is read as far as
it tokenized. Any other file is read by line.

`rule_reader.scan` reads a Markdown file the way CommonMark renders it, skipping fences, indented
code and HTML blocks. `rule_headings` and `layer_problems` report each bad rule heading
with one of three reasons (two ids, no well-formed id, a level other than
`###`). `prefix_table` reads a README's `## Rule ids` table through `scan`.
"""

import io
import re
import tokenize
from typing import NamedTuple

from agent_tools.delivery.context_map_lint import CODE_RE, section, table_rows
from agent_tools.delivery.rule_reader import HEADING_LINE, RULE_ID_HEADING, SECOND_ID, rule_match, scan

RULE_ID = re.compile(r"[A-Z]+[1-9][0-9]*")
CITE = "standard:"
CITATION = re.compile(r"(?<![A-Za-z0-9_-])standard:(?P<token>\S+)")
SENTENCE_END = ".,;:!?)]}'\"`*"
SUPPRESS = "suppress-standard:"
SUPPRESSION = re.compile(r"(?<![A-Za-z0-9_-])suppress-standard:(?P<token>\S*)(?P<rest>.*)")
COMMENT_CLOSERS = ("-->", "*/")


class Citation(NamedTuple):
    line: int
    token: str
    well_formed: bool


def citations(text: str) -> list[Citation]:
    """Every citation in `text`, in order, with its 1-based line and whether its token is a rule id."""
    return [
        Citation(text.count("\n", 0, match.start()) + 1, token, RULE_ID.fullmatch(token) is not None)
        for match in CITATION.finditer(text)
        for token in [_token(match["token"])]]


def is_reasoned(rule: str | None, reason: str) -> bool:
    """Whether a marker naming `rule` with `reason` suppresses: it names a rule and says why."""
    return rule is not None and any(c.isalnum() for c in reason)


class Marker(NamedTuple):
    line: int
    rule: str | None
    reason: str

    @property
    def reasoned(self) -> bool:
        return is_reasoned(self.rule, self.reason)


def is_python(path: str) -> bool:
    """Whether `path` names a Python source file, whose markers are read from comments only."""
    return path.endswith((".py", ".pyi"))


def _comment_columns(text: str) -> dict[int, int]:
    """The column where the comment of each 1-based line starts, for the lines that tokenize."""
    columns: dict[int, int] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                columns[token.start[0]] = token.start[1]
    except (tokenize.TokenError, SyntaxError):
        pass
    return columns


def markers(text: str, python: bool = False) -> list[Marker]:
    """The first suppression marker of each line of `text`, in order, with its 1-based line.

    With `python`, only a marker inside a comment is read.
    """
    found = []
    comments = _comment_columns(text) if python and SUPPRESS in text else {}
    for number, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if python:
            if number not in comments:
                continue
            line = line[comments[number]:]
        match = SUPPRESSION.search(line)
        if match is None:
            continue
        reason = match["rest"].strip()
        for closer in COMMENT_CLOSERS:
            if reason.endswith(closer):
                reason = reason.removesuffix(closer).strip()
                break
        token = match["token"]
        found.append(Marker(number, token if RULE_ID.fullmatch(token) else None, reason))
    return found


def _token(run: str) -> str:
    """`run` without the sentence punctuation that closes it, or `run` whole when only that remains."""
    return run.rstrip(SENTENCE_END) or run




def without_rule_id(line: str) -> str:
    """`line` without its one rule id when it is a `###` rule-id heading, else `line`."""
    match = RULE_ID_HEADING.match(line)
    return f"{match['hashes']} {match['title']}" if match and match["hashes"] == "###" else line


REASON_TWO_IDS = "more than one id"
REASON_NO_ID = "no well-formed id"
REASON_LEVEL = "a rule heading is ###"
NUMBERED_ITEM = re.compile(r"^[0-9]+[.)] ")




def unfenced(text: str):
    """`(line number, line)` of every line `scan` keeps."""
    for number, line, _ in scan(text):
        yield number, line


def rule_headings(text: str) -> tuple[list[tuple[str, int, int]], list[str]]:
    ids: list[tuple[str, int, int]] = []
    problems: list[str] = []
    seen_heading = False
    for number, _, line in scan(text):
        if not HEADING_LINE.match(line):
            continue
        first, seen_heading = not seen_heading, True
        if first and line.startswith("# "):
            continue
        found = rule_match(line)
        if found:
            ids.append((found["prefix"], int(found["number"]), number))
        else:
            match = RULE_ID_HEADING.match(line)
            if match and SECOND_ID.search(match["title"]):
                reason = REASON_TWO_IDS
            elif match:
                reason = REASON_LEVEL
            else:
                reason = REASON_NO_ID
            problems.append(f"line {number}: {reason}: {line}")
    return ids, problems


def sections(text: str) -> dict[str, str]:
    """Rule id to the body between its heading and the next heading of any level."""
    bodies: dict[str, list[str]] = {}
    current = None
    for _, raw, line in scan(text):
        if HEADING_LINE.match(line):
            found = rule_match(line)
            current = f"{found['prefix']}{found['number']}" if found else None
            if current:
                bodies[current] = []
        elif current:
            bodies[current].append(raw)
    return {key: "".join(f"{line}\n" for line in lines) for key, lines in bodies.items()}


def numbered_items(text: str) -> list[int]:
    return [number for number, line in unfenced(text) if NUMBERED_ITEM.match(line)]


def layer_problems(files: list[tuple[str, str, str]]) -> list[str]:
    problems: list[str] = []
    seen: dict[tuple[str, int], str] = {}
    for label, expected, text in files:
        ids, bad = rule_headings(text)
        problems += [f"{label}: {problem}" for problem in bad]
        if not ids and not bad:
            problems.append(f"{label}: no rule heading")
        for prefix, number, line in ids:
            name = f"{prefix}{number}"
            if prefix != expected:
                problems.append(f"{label}: line {line}: {name} should carry the prefix {expected}")
            if (prefix, number) in seen:
                problems.append(f"{label}: line {line}: {name} repeats the id in {seen[(prefix, number)]}")
            seen.setdefault((prefix, number), label)
        for name, body in sections(text).items():
            if not body.strip():
                problems.append(f"{label}: {name} has no body")
    return problems


def prefix_table(readme_text: str) -> dict[str, str]:
    table: dict[str, str] = {}
    rendered = "".join(f"{line}\n" for _, line, _ in scan(readme_text))
    for cells in table_rows(section(rendered, "Rule ids")):
        if len(cells) < 2:
            continue
        keys, values = CODE_RE.findall(cells[0]), CODE_RE.findall(cells[1])
        if keys and values:
            table[keys[0]] = values[0]
    return table
