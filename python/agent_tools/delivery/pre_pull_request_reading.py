"""`pre_pull_request_reading`: whether a delivery begun after a merge listed a local result of a command.

`python -m agent_tools.delivery.pre_pull_request_reading --repo SLUG --merge SHA --command ID`
reads the forge and prints one JSON line `{"status", "since", "pr", "command"}`. The only forge
access is `read(path)`, one `forge_api.api_get`-shaped GET returning parsed JSON; no host clock is
read: the boundary is the forge's committer date of `--merge`.

A candidate is a pull request created after the boundary whose body has an Evidence section. It
counts only when its branch started from a commit that contains the merge (the first commit's first
parent is `ahead` of or `identical` to it). The check is met when a counting candidate's Evidence
section lists a local result of the command: a clause naming it, not preceded in that clause by a CI
name (CI, GitHub, a required or status check, a job, a pipeline, a workflow, a runner, "on the pull request", the
command named as a check or job), with no CI name
anywhere after it on the same logical line (a wrapped continuation line, or a line opening with a CI name
even after a blank line, joins the line above), and followed by a result word (pass, passed, fail, failed)
reached through nothing but counting filler ("all 41 checks ran"), so any other wording between the command
and the result ("postponed", "n/a", "expected to") is no result. A command that opens a list ("conformance,
lint and test-touched passed") shares the result with the names after it, and a result word that opens one
("verification passed: lint, conformance") covers the names after its colon. The repository's own words for
the command ("purpose ci", "ci rules", "as the required check runs it") are not CI names, and neither is the
sentence the delivery programs write, "CI on this pull request runs the full declared verification" (also
reworded, as a subject; after a preposition it is a CI qualifier). The Evidence section runs to the
next heading of its level or higher (a bold or plain "Merge danger" line also ends it). Otherwise
it is not yet (exit 75); a forge failure or a payload of the wrong shape (a body that is not text
included) is `forge_unreadable`, also exit 75. The check never reports not met: the verify block's
expiry ends a hold that never meets.
"""

import argparse
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

NOT_YET = 75
PAGES = 10
PAGE = 100
COUNTING = ("ahead", "identical")
HEADING = re.compile(r"^(?:(#{1,6})\s*)?(?:\*\*)?Evidence:?(?:\*\*)?:?$", re.IGNORECASE)
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s")
BOLD_HEADING = re.compile(r"^\*\*[^*]+\*\*:?$")
CLAUSES = re.compile(r";|\.(?=\s|$)")
CI_WORD = re.compile(r"\b(?:CI|GitHub|(?:required|status)\s+(?:checks?|contexts?)|check\s+(?:runs?|suites?)|merge\s+queue"
                     r"|pipelines?|jobs?|continuous\s+integration|remotely)\b"
                     r"|\b(?:on|in|at|from|via|by|under|within|through)\s+(?:(?:the|this|that|a)\s+)?"
                     r"(?:pull\s+requests?|PRs?)\b"
                     r"|(?-i:\bActions\b)|(?<![\w./-])(?:workflows?|runners?)(?![\w./-])|\.github/workflows",
                     re.IGNORECASE)
PREPOSITION = r"(?:on|in|by|via|under|only|from|as|at|within|through|per|using|with|for|during|against)"
CI_BOILERPLATE = re.compile(rf"(\b{PREPOSITION}\s+)?\bCI\s+(?:on\s+this\s+(?:pull\s+request|PR)\s+)?"
                            r"(?:will\s+|would\s+)?runs?\b[^.;\n]*", re.IGNORECASE)
CI_LEADING = re.compile(rf"^\(?\s*(?:(?:{PREPOSITION}|ran|run|runs|running|executed|the|an?|and|but)\s+)*"
                        rf"(?:{CI_WORD.pattern})", re.IGNORECASE)
CI_LEADING_AFTER_GAP = re.compile(rf"^(?:\(\s*|(?:{PREPOSITION}|ran|run|runs|running|executed)\s+)"
                                  rf"(?:(?:{PREPOSITION}|ran|run|runs|running|executed|the|an?|and|but)\s+)*"
                                  rf"(?:{CI_WORD.pattern})", re.IGNORECASE)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\||#)")
CI_IDIOM = re.compile(r"\bpurpose:?\s+ci\b|\bci\s+rules?\b"
                      r"|\bas\s+the\s+required\s+(?:ci\s+)?check\s+(?:runs\s+it|does)\b", re.IGNORECASE)
SYMBOLS = "\u2190-\u2bff\U0001f000-\U0001faff\ufe0f"
PUNCT = rf"[\s:()\[\]|*_`'\"=>/%.\u2013\u2014{SYMBOLS}-]"
FILLER = re.compile(rf"(?:{PUNCT}|\d+(?:\.\d+)?\s*(?:ms|s|secs?|seconds?|m|mins?|minutes?)\b|\d+"
                    r"|--(?!no\b|no-|skip|dry|without|only)[a-z][\w-]*"
                    r"|(?:all|every|ran|runs?|checks?|rules?|tests?|suites?|members?|is|are|was|were"
                    r"|has|have|been|now|locally|and|the|of|in|took|finished|completed|results?|ok|clean|green"
                    r"|no\s+(?:fail\w*|error\w*|issues?|problems?|warnings?|regress\w*))\b)*", re.IGNORECASE)
NAME = r"[A-Za-z][\w-]*"
LIST_PART = re.compile(rf"\s*(?:and\s+)?{NAME}(?:\s+and\s+{NAME})*\s*")
LIST_START = re.compile(r"\s*(?:,|and\b)", re.IGNORECASE)
RESULT_WORD = re.compile(r"\b(?:pass|passed|fail|failed)\b", re.IGNORECASE)
LISTED_UNDER = re.compile(rf"\b(?:pass|passed|fail|failed)\s*:\s*(?:{NAME}\s*(?:,|\band\b)\s*)*", re.IGNORECASE)
LIST_TAIL = re.compile(rf"(?:\s*(?:,|\band\b)\s*{NAME})*\s*", re.IGNORECASE)
NEGATION = re.compile(r"\b(?:not|never|no|without|cannot)\b|n't", re.IGNORECASE)

Read = Callable[[str], Any]


class Unreadable(Exception):
    """A forge answer of the wrong shape: printed as `forge_unreadable`."""


def _ends_section(line: str, level: int | None) -> bool:
    """Whether `line` is a heading that closes an Evidence section opened at markdown `level` (None: not a # heading)."""
    heading = MARKDOWN_HEADING.match(line)
    if heading and (level is None or len(heading.group(1)) <= level):
        return True
    if heading is None and level is None and BOLD_HEADING.match(line.strip()):
        return True
    return line.strip().lstrip("#*").strip().lower().startswith("merge danger")


def evidence_section(body: Any) -> str | None:
    """The lines after the first Evidence heading of `body` up to the next heading of its level, or None."""
    if body is not None and not isinstance(body, str):
        raise Unreadable(f"a pull request body is not text: {type(body).__name__}")
    lines, found, level = (body or "").splitlines(), None, None
    for index, line in enumerate(lines):
        match = HEADING.match(line.strip())
        if match:
            found, level = index + 1, len(match.group(1)) if match.group(1) else None
            break
    if found is None:
        return None
    section = []
    for line in lines[found:]:
        if _ends_section(line, level):
            break
        section.append(line)
    return "\n".join(section)


def _normalized(section: str) -> str:
    """`section` without the repository's own words for the command and the delivery programs' sentence about CI.

    The sentence ("CI on this pull request runs ...", also reworded) is dropped only as a subject: after a
    preposition ("on CI on this pull request runs ...") it stays a CI qualifier.
    """
    section = CI_IDIOM.sub("", section)
    return CI_BOILERPLATE.sub(lambda m: m.group(0) if m.group(1) else "", section)


def _logical_lines(section: str) -> list[str]:
    """The lines of `section`, each wrapped continuation (indented, parenthesised or opening with a CI name) joined.

    Across a blank line only a parenthesis or a preposition-led CI phrase ("(in CI)", "on CI") joins: a new
    paragraph that merely opens with a CI name ("The required checks run ...") is not a qualifier.
    """
    joined: list[str] = []
    for line in section.splitlines():
        text, last = line.strip(), next((i for i in range(len(joined) - 1, -1, -1) if joined[i].strip()), None)
        gap = last is not None and last != len(joined) - 1
        leading = CI_LEADING_AFTER_GAP if gap else CI_LEADING
        if text and last is not None and not LIST_ITEM.match(line) and leading.match(text):
            joined[last] += " " + text
        elif text and last == len(joined) - 1 and not LIST_ITEM.match(line) and (line[0].isspace() or text[0] == "("):
            joined[last] += " " + text
        else:
            joined.append(line)
    return joined


def ran_locally(section: str, command: str) -> bool:
    """Whether a clause of `section` names `command` with no CI before it, none after it on its line, and a result.

    The command named as a CI check or job ("in the Conformance check", "(Conformance job)") is a CI name.
    """
    named = re.compile(r"(?<![\w./-])" + re.escape(command) + r"(?![\w./-])", re.IGNORECASE)
    ci_named = re.compile(r"(?:\b(?:the|this|in|on|via|by|from|at|under)\s+|\(\s*)(?<![\w./-])" + re.escape(command)
                          + r"\s+(?:check|job|workflow|context|status)s?\b", re.IGNORECASE)
    for line in _logical_lines(_normalized(section)):
        line = ci_named.sub(" CI ", line)
        clauses = CLAUSES.split(line)
        for index, clause in enumerate(clauses):
            for occurrence in named.finditer(clause):
                after = clause[occurrence.end():]
                if CI_WORD.search(clause[:occurrence.start()]) or CI_WORD.search(" ".join([after, *clauses[index + 1:]])):
                    continue
                if _result_follows(after) or _listed_under_result(clause[:occurrence.start()], after):
                    return True
    return False


def _listed_under_result(before: str, after: str) -> bool:
    """Whether the command is a name in a list a result word opens ("verification passed: lint, conformance")."""
    opening = LISTED_UNDER.search(before)
    while opening and opening.end() != len(before):
        opening = LISTED_UNDER.search(before, opening.start() + 1)
    return bool(opening and not NEGATION.search(before[:opening.start()]) and LIST_TAIL.fullmatch(after))


def _result_follows(after: str) -> bool:
    """Whether `after` (the text after the command) reaches a result word through nothing but known filler.

    A command that opens a list ("conformance, lint and test-touched passed") shares the result with the names
    listed after it. Otherwise only counting words ("all 41 checks ran") may stand between the command and its
    result, so any other wording ("postponed", "n/a", "expected to") means no result of this command.
    """
    parts, listing = after.split(","), bool(LIST_START.match(after))
    for position, part in enumerate(parts):
        result = RESULT_WORD.search(part)
        before = part[:result.start()] if result else part
        if listing:
            fits = LIST_PART.fullmatch(before) or (not before.strip() and (result or position == 0))
        else:
            fits = FILLER.fullmatch(before)
        if not fits:
            return False
        if result:
            return True
    return False


def _when(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise Unreadable(f"unreadable timestamp {value!r}") from None


def _list(payload: Any, what: str) -> list:
    if not isinstance(payload, list):
        raise Unreadable(f"{what} is not an array")
    return payload


def _pulls_after(read: Read, slug: str, boundary: datetime) -> tuple[list[dict], bool]:
    """The pull requests created after `boundary`, read newest first, and whether the list is complete."""
    found = []
    for page in range(1, PAGES + 1):
        pulls = _list(read(f"repos/{slug}/pulls?state=all&sort=created&direction=desc"
                           f"&per_page={PAGE}&page={page}"), "pulls")
        found += [p for p in pulls if _when(p["created_at"]) > boundary]
        if len(pulls) < PAGE or _when(pulls[-1]["created_at"]) <= boundary:
            return found, True
    return found, False


def _started_after(read: Read, slug: str, merge: str, number: int) -> bool:
    """Whether the branch of pull request `number` started from a commit that contains `merge`."""
    commits = _list(read(f"repos/{slug}/pulls/{number}/commits?per_page=100"), "commits")
    if not commits:
        raise Unreadable(f"pull request {number} lists no commits")
    start = commits[0]["parents"][0]["sha"]
    status = read(f"repos/{slug}/compare/{merge}...{start}")["status"]
    if status not in (*COUNTING, "behind", "diverged"):
        raise Unreadable(f"unknown comparison status {status!r}")
    return status in COUNTING


def reading(read: Read, slug: str, merge: str, command: str) -> tuple[int, dict]:
    since = read(f"repos/{slug}/commits/{merge}")["commit"]["committer"]["date"]
    candidates = []
    pulls, complete = _pulls_after(read, slug, _when(since))
    for pull in pulls:
        section = evidence_section(pull.get("body"))
        if section is not None:
            candidates.append((_when(pull["created_at"]), pull["number"], section))
    for _, number, section in sorted(candidates, key=lambda c: (c[0], c[1])):
        if ran_locally(section, command) and _started_after(read, slug, merge, number):
            return 0, {"status": "met", "since": since, "pr": number, "command": command}
    if not complete:
        raise Unreadable(f"the pull requests after the merge reach {PAGES * PAGE} and none read met")
    return NOT_YET, {"status": "not_yet", "since": since, "pr": None, "command": command}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pre_pull_request_reading", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="the repository slug, owner/name")
    parser.add_argument("--merge", required=True, help="the commit whose merge starts the reading")
    parser.add_argument("--command", required=True, help="the command id a delivery lists a result of")
    return parser


def _print(document: Mapping) -> None:
    print(json.dumps(document, sort_keys=True))


def main(argv: list[str] | None = None, *, read: Read = forge_api.api_get) -> int:
    args = build_parser().parse_args(argv)
    try:
        code, document = reading(read, args.repo, args.merge, args.command)
    except (ForgeError, Unreadable, AttributeError, KeyError, IndexError, TypeError, ValueError) as error:
        _print({"status": "forge_unreadable", "reason": str(error)})
        return NOT_YET
    _print(document)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
