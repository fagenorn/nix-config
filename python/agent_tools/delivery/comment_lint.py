"""The comment enforcers: no issue reference, no long comment, no placeholder marker (rules B18, B19, B20).

The command `comment-lint --repo-root <absolute directory> [--revision <rev>]
[--repository <owner>/<name>]` reads every tracked text file of a covered stack at the
revision (default `HEAD`) as `agent_tools.delivery.comment_syntax` reads it and prints one
line per violation on stdout, `<rule> <path>:<line>` (`agent_tools.delivery.never_rise.Violation.text`),
the three rules in the order B18, B19, B20 and each rule's lines by path and line. It
exits 1 when it printed any and 0 when none. It exits 2 with `comment-lint: <reason>` on
stderr for a relative or missing root, a root below the repository's top level, an
unresolvable revision, a failed git read or a `--repository` that is not `<owner>/<name>`.
`enforcers(repository)` gives the three rules as count enforcers for the never-rise check,
which, not this command's exit, is the gate.

A file is judged by its committed bytes, decoded as UTF-8 with replacement. A line is a line
of a block in the sense of `comment_syntax`, so text in a string, a heredoc or a block
scalar is never counted, and a file of no known stack is not read.

- B18: a comment line that names an issue or pull request is one violation of the line,
  whatever the number of references on it. The file header is judged too.
- B19: a block that is not in the file header and has more than `MAX_BLOCK_LINES` lines is
  one violation at its first line; a line of such a block whose physical line, without
  trailing whitespace, is longer than `MAX_LINE_CHARS` characters is one violation at that
  line. A block over five lines whose first line is also too wide is one violation, since
  the comparison counts list entries.
- B20: a comment line holding either placeholder marker word that the rule names, upper case and
  as a whole word, is one violation of the line. The file header is judged too.

A reference is, in a comment's text: a link to the repository's own issues or pulls on
github.com; the shorthand `#<n>`; `issue <n>`, `issues <n>` or `pull request <n>`, with an
optional `#` and in any case; `PR <n>` or `PRs <n>`; `GH-<n>`; and `<owner>/<name>#<n>`
for the repository. Every URL is classified whole before the shorthands are read: a link to
the repository's own tracker is a reference, any other URL is an upstream link and is
blanked out, so a shorthand-shaped piece inside it counts for nothing while a shorthand beside
it still does. `<n>` has no leading zero. The repository is `--repository`, and the never-rise
check passes the contract's `bindings.tracker.repo_slug`; with none, only the shorthands
count.
"""

import argparse
import re
import sys
from collections.abc import Callable

from agent_tools.delivery import comment_syntax, never_rise
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation

COMMAND = "comment-lint"
REFERENCE_RULE = "B18"
LENGTH_RULE = "B19"
MARKER_RULE = "B20"
MAX_BLOCK_LINES = 5
MAX_LINE_CHARS = 120

REPOSITORY_FORM = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
URL = re.compile(r"(?i)(?:https?://|www\.|(?<![\w.-])github\.com/)[^\s<>\"')\]`]*")
URL_TRAILING = ".,;:"
SHORTHANDS = (
    re.compile(r"(?<![\w&#/])#[1-9][0-9]*\b"),
    re.compile(r"(?i:\b(?:issues?|pull[ -]requests?)\b)[ \t]*#?[1-9][0-9]*\b"),
    re.compile(r"\bPRs?[ \t]*#?[1-9][0-9]*\b"),
    re.compile(r"\bGH-[1-9][0-9]*\b"),
)
MARKER = re.compile(r"\b(?:TODO|FIXME)\b")


def _own_patterns(repository: str | None) -> tuple[re.Pattern[str], re.Pattern[str]] | None:
    if repository is None or REPOSITORY_FORM.fullmatch(repository) is None:
        return None
    owner, name = (re.escape(part) for part in repository.split("/"))
    link = re.compile(
        rf"(?i)(?:https?://)?(?:www\.)?github\.com/{owner}/{name}/(?:issues|pull)/[1-9][0-9]*")
    short = re.compile(rf"(?i)(?<![\w.-]){owner}/{name}#[1-9][0-9]*")
    return link, short


def references(text: str, repository: str | None) -> bool:
    """True when the comment text names an issue or pull request."""
    own = _own_patterns(repository)
    for url in URL.finditer(text):
        if own is not None and own[0].match(url.group().rstrip(URL_TRAILING)):
            return True
    rest = URL.sub(" ", text)
    return any(pattern.search(rest) for pattern in SHORTHANDS) or (
        own is not None and own[1].search(rest) is not None)


def _lines(path: str, data: bytes):
    """Each block of a file with the file's physical lines."""
    text = data.decode("utf-8", errors="replace")
    physical = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    return comment_syntax.blocks(path, text), physical


def _find(snapshot: Snapshot, rule: str,
          judge: Callable[[comment_syntax.Block, list[str]], list[int]]) -> list[Violation]:
    found: set[tuple[str, int]] = set()
    for path in sorted(snapshot.contents):
        blocks, physical = _lines(path, snapshot.contents[path])
        for block in blocks:
            found.update((path, line) for line in judge(block, physical))
    return [Violation(rule, path, line) for path, line in sorted(found)]


def _numbered(block: comment_syntax.Block):
    return enumerate(block.texts, block.first)


def _reference_lines(repository: str | None):
    def judge(block: comment_syntax.Block, physical: list[str]) -> list[int]:
        return [n for n, text in _numbered(block) if references(text, repository)]
    return judge


def _length_lines(block: comment_syntax.Block, physical: list[str]) -> list[int]:
    if block.header:
        return []
    lines = [block.first] if block.last - block.first + 1 > MAX_BLOCK_LINES else []
    lines += [n for n, _ in _numbered(block) if len(physical[n - 1].rstrip()) > MAX_LINE_CHARS]
    return lines


def _marker_lines(block: comment_syntax.Block, physical: list[str]) -> list[int]:
    return [n for n, text in _numbered(block) if MARKER.search(text)]


def enforcers(repository: str | None) -> tuple[Enforcer, Enforcer, Enforcer]:
    """The rules B18, B19 and B20 as count enforcers, in that order."""
    references_judge = _reference_lines(repository)
    return (
        Enforcer(REFERENCE_RULE, lambda snap: _find(snap, REFERENCE_RULE, references_judge)),
        Enforcer(LENGTH_RULE, lambda snap: _find(snap, LENGTH_RULE, _length_lines)),
        Enforcer(MARKER_RULE, lambda snap: _find(snap, MARKER_RULE, _marker_lines)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--repository")
    args = parser.parse_args(argv)
    if args.repository is not None and REPOSITORY_FORM.fullmatch(args.repository) is None:
        print(f"{COMMAND}: --repository must be <owner>/<name>: {args.repository}",
              file=sys.stderr)
        return 2
    snapshot = never_rise.command_snapshot(COMMAND, args.repo_root, args.revision)
    if snapshot is None:
        return 2
    printed = 0
    for enforcer in enforcers(args.repository):
        for violation in enforcer.find(snapshot):
            print(violation.text())
            printed += 1
    return 1 if printed else 0


if __name__ == "__main__":
    raise SystemExit(main())
