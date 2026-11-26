"""`pre_pull_request_reading`: whether a delivery begun after a merge listed a local result of a command.

`python -m agent_tools.delivery.pre_pull_request_reading --repo SLUG --merge SHA --command ID`
reads the forge and prints one JSON line `{"status", "since", "pr", "command"}`. The only forge
access is `read(path)`, one `forge_api.api_get`-shaped GET returning parsed JSON; no host clock is
read: the boundary is the forge's committer date of `--merge`.

A candidate is a pull request created after the boundary whose body has an Evidence section. It
counts only when its branch started from a commit that contains the merge (the first commit's first
parent is `ahead` of or `identical` to it). The check is met when a counting candidate's Evidence
section lists a local result of the command: a clause naming it, not preceded in that clause by a CI
name (CI, GitHub Actions, a required or status check, a pipeline), with no CI name anywhere after it
on the same logical line (the idioms "purpose ci" and "ci rules" excepted; a wrapped continuation
line joins the line above), and followed by a result word (pass, passed, fail, failed) in its own
comma part or in a later one, with no skip, negation, n/a, none, timeout or pending word in the parts
up to the result (so a list such as "conformance, lint and test-touched passed" counts). The sentence
the delivery programs write, "CI on this pull request runs the full declared verification", is not
a CI qualifier and is ignored. The Evidence section runs to the
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
CI_WORD = re.compile(r"\b(?:CI|GitHub\s+Actions|(?:required|status)\s+checks?|pipelines?|continuous\s+integration)\b"
                     r"|\.github/workflows", re.IGNORECASE)
CI_BOILERPLATE = re.compile(r"(\b(?:on|in|by|via|under|only|from)\s+)?\bCI\s+on\s+this\s+pull\s+request\s+runs\s+"
                            r"the\s+full\s+declared\s+verification\b", re.IGNORECASE)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\||#)")
CI_IDIOM = re.compile(r"(?:--)?\bpurpose\s+ci\b|\bci\s+rules?\b", re.IGNORECASE)
NEGATION = re.compile(r"\b(?:skip|skipped|skipping|not|never|without|pending|todo|unknown|deferred|blocked"
                      r"|waiting|running|unavailable|none|n/a|na|later|soon|will|would|should|shall|timeout"
                      r"|timed\s*out|cancell?ed|aborted|crashed|errored)\b"
                      r"|\bno\b(?!\s+(?:fail\w*|error\w*|issues?|problems?|warnings?|regress\w*))|n't",
                      re.IGNORECASE)
RESULT_WORD = re.compile(r"\b(?:pass|passed|fail|failed)\b", re.IGNORECASE)

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


def _without_boilerplate(section: str) -> str:
    """`section` without the delivery programs' sentence about CI, unless a preposition makes it a qualifier."""
    return CI_BOILERPLATE.sub(lambda m: m.group(0) if m.group(1) else "", section)


def _logical_lines(section: str) -> list[str]:
    """The lines of `section`, each indented, parenthesised or plain non-item line after a text line joined to it."""
    joined: list[str] = []
    for line in section.splitlines():
        continues = joined and joined[-1].strip() and line.strip() and not LIST_ITEM.match(line)
        if continues and (line[0].isspace() or line.lstrip().startswith("(") or CI_WORD.match(line.lstrip())):
            joined[-1] += " " + line.strip()
        else:
            joined.append(line)
    return joined


def ran_locally(section: str, command: str) -> bool:
    """Whether a clause of `section` names `command` with no CI before it, none after it on its line, and a result."""
    named = re.compile(r"(?<![\w./-])" + re.escape(command) + r"(?![\w./-])", re.IGNORECASE)
    for line in _logical_lines(_without_boilerplate(section)):
        clauses = CLAUSES.split(line)
        for index, clause in enumerate(clauses):
            for occurrence in named.finditer(clause):
                after = clause[occurrence.end():]
                rest_of_line = " ".join([after, *clauses[index + 1:]])
                if CI_WORD.search(clause[:occurrence.start()]) or CI_WORD.search(CI_IDIOM.sub("", rest_of_line)):
                    continue
                if _result_follows(after):
                    return True
    return False


def _result_follows(after: str) -> bool:
    """Whether a result word follows in `after`, in its own comma part or a later one, with no negation before it."""
    for part in after.split(","):
        result = RESULT_WORD.search(part)
        if NEGATION.search(part[:result.start()] if result else part):
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
