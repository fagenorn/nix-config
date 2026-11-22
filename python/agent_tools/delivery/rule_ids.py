"""The written form of a standard's rule id in its heading (#1438).

A rule heading is `### B12. Fail loud`: the heading hashes, one id (capital
letters then a number with no leading zero), a full stop, then the title.
`RULE_ID_HEADING` is the single home of that form and `without_rule_id` removes
the one id from a matching `###` rule heading, leaving every other line (a
heading of another level included) unchanged.

An enforcer names a rule by the citation `standard:<id>`, as in `standard:B12`
(#1442). `citations` returns every citation in a text with its 1-based line and
whether its token is a well-formed id, and `PROJECT_PREFIX` is the prefix of the
project shards' ids, which resolve against the project's own shards.

A citation is `standard:` not glued to a word and followed with no space by a run of
non-space characters. Its token is that run less the sentence punctuation closing it (`.`,
`,`, a closing bracket or quote, a backtick), or the run whole when only punctuation remains.
So any such run that is no id is malformed, whatever its first or following character is;
`standard:` followed by a space or the end of the text is prose and no citation.
"""

import re
from typing import NamedTuple

RULE_ID = re.compile(r"[A-Z]+[1-9][0-9]*")
RULE_ID_HEADING = re.compile(
    r"^(?P<hashes>#{1,6}) (?P<prefix>[A-Z]+)(?P<number>[1-9][0-9]*)\. (?P<title>\S.*)$")
CITE = "standard:"
CITATION = re.compile(r"(?<![A-Za-z0-9_-])standard:(?P<token>\S+)")
SENTENCE_END = ".,;:!?)]}'\"`*"
PROJECT_PREFIX = "P"


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


def _token(run: str) -> str:
    """`run` without the sentence punctuation that closes it, or `run` whole when only that remains."""
    return run.rstrip(SENTENCE_END) or run


def prefix_of(rule_id: str) -> str:
    """The leading capital letters of `rule_id` (`PY3` is `PY`)."""
    return re.match(r"[A-Z]*", rule_id)[0]


def without_rule_id(line: str) -> str:
    """`line` without its one rule id when it is a `###` rule-id heading, else `line`."""
    match = RULE_ID_HEADING.match(line)
    return f"{match['hashes']} {match['title']}" if match and match["hashes"] == "###" else line
