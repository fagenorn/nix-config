"""The written form of a standard's rule id in its heading (#1438).

A rule heading is `### B12. Fail loud`: the heading hashes, one id (capital
letters then a number with no leading zero), a full stop, then the title.
`RULE_ID_HEADING` is the single home of that form and `without_rule_id` removes
the one id from a matching line, leaving every other line unchanged.
"""

import re

RULE_ID_HEADING = re.compile(
    r"^(?P<hashes>#{1,6}) (?P<prefix>[A-Z]+)(?P<number>[1-9][0-9]*)\. (?P<title>\S.*)$")


def without_rule_id(line: str) -> str:
    """`line` without its one rule id when it is a rule-id heading, else `line`."""
    match = RULE_ID_HEADING.match(line)
    return f"{match['hashes']} {match['title']}" if match else line
