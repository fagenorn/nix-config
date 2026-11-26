"""`pre_pull_request_reading`: whether a delivery begun after a merge listed a local result of a command.

`python -m agent_tools.delivery.pre_pull_request_reading --repo SLUG --merge SHA --command ID`
reads the forge and prints one JSON line `{"status", "since", "pr", "command"}`. The only forge
access is `read(path)`, one `forge_api.api_get`-shaped GET returning parsed JSON; no host clock is
read: the boundary is the forge's committer date of `--merge`.

A candidate is a pull request created after the boundary whose body has an Evidence section. It
counts only when its branch started from a commit that contains the merge (the first commit's first
parent is `ahead` of or `identical` to it). The check is met when a counting candidate's Evidence
section lists a local result of the command: a clause naming it, not preceded in that clause by the
word CI, and followed by a result word (pass, passed, fail, failed). Otherwise it is not yet (exit
75); a forge failure or a payload of the wrong shape is `forge_unreadable`, also exit 75. The
check never reports not met: the verify block's expiry ends a hold that never meets.
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
HEADING = re.compile(r"^(?:#{1,6}\s*)?(?:\*\*)?Evidence(?:\*\*)?:?$", re.IGNORECASE)
SECTION_END = re.compile(r"^#{1,6}\s")
CLAUSES = re.compile(r"\n|;|\.(?=\s|$)")
CI_WORD = re.compile(r"\bCI\b", re.IGNORECASE)
RESULT_WORD = re.compile(r"\b(?:pass|passed|fail|failed)\b", re.IGNORECASE)

Read = Callable[[str], Any]


class Unreadable(Exception):
    """A forge answer of the wrong shape: printed as `forge_unreadable`."""


def evidence_section(body: str | None) -> str | None:
    """The lines after the first Evidence heading of `body` up to the next heading, or None."""
    lines, found = (body or "").splitlines(), None
    for index, line in enumerate(lines):
        if HEADING.match(line.strip()):
            found = index + 1
            break
    if found is None:
        return None
    section = []
    for line in lines[found:]:
        if SECTION_END.match(line) or line.strip().lower().startswith("merge danger"):
            break
        section.append(line)
    return "\n".join(section)


def ran_locally(section: str, command: str) -> bool:
    """Whether a clause of `section` names `command` with no CI before it and a result word after it."""
    named = re.compile(r"(?<![\w./-])" + re.escape(command) + r"(?![\w./-])", re.IGNORECASE)
    for clause in CLAUSES.split(section):
        for occurrence in named.finditer(clause):
            if not CI_WORD.search(clause[:occurrence.start()]) and RESULT_WORD.search(clause[occurrence.end():]):
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


def _pulls_after(read: Read, slug: str, boundary: datetime) -> list[dict]:
    """The pull requests created after `boundary`, read newest first."""
    found = []
    for page in range(1, PAGES + 1):
        pulls = _list(read(f"repos/{slug}/pulls?state=all&sort=created&direction=desc"
                           f"&per_page={PAGE}&page={page}"), "pulls")
        found += [p for p in pulls if _when(p["created_at"]) > boundary]
        if len(pulls) < PAGE or _when(pulls[-1]["created_at"]) <= boundary:
            return found
    raise Unreadable(f"the pull requests after the merge exceed {PAGES * PAGE}")


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
    for pull in _pulls_after(read, slug, _when(since)):
        section = evidence_section(pull.get("body"))
        if section is not None:
            candidates.append((_when(pull["created_at"]), pull["number"], section))
    for _, number, section in sorted(candidates, key=lambda c: (c[0], c[1])):
        if ran_locally(section, command) and _started_after(read, slug, merge, number):
            return 0, {"status": "met", "since": since, "pr": number, "command": command}
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
    except (ForgeError, Unreadable, KeyError, IndexError, TypeError, ValueError) as error:
        _print({"status": "forge_unreadable", "reason": str(error)})
        return NOT_YET
    _print(document)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
