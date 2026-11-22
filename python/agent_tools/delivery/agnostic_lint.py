"""Refuse hosting-project specifics in the installed global agent corpus (#572).

Inside the global standards directory only, a link to an issue on this repository's own tracker in
exactly the form `https://github.com/fagenorn/nix-config/issues/<n>` is accepted (#1438); every other
mention of the repository stays refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Optional

from agent_tools.skill_lint import TREE_ROOTS, Snapshot, working_tree

GLOBAL_CORPUS = (
    *TREE_ROOTS,
    "home/common/claude-code/agents",
    "home/common/agent-skills/standards",
    "home/common/agent-guidance/AGENTS.md",
)
# Constants no file in the hosting repo states; the check names and recipes are derived instead.
HOSTING_LITERALS = ("fagenorn/nix-config", "nix-config", "origin/main", "--base main",
                    "home/common/", "python/agent_tools/", "anis-desktop")
# A link to an issue on the hosting tracker is accepted in the global standards only (#1438).
TRACKER_LINK_ROOT = "home/common/agent-skills/standards"
URL_SPAN = re.compile(r"""https?://[^\s()<>\[\]"'`]+""")
ANGLE_DESTINATION = re.compile(r"\]\(<(?P<url>[^<>\n]*)>")
AUTOLINK = re.compile(r"<(?P<url>https?://[^\s<>]*)>")
TRACKER_ISSUE_LINK = re.compile(r"https://github\.com/fagenorn/nix-config/issues/[1-9][0-9]*")
# Every exemption is one (file, token) pair with its reason; evals and LICENSE files are skipped by name.
AGNOSTIC_ALLOW = {
    # retro audits the global environment and legitimately names nix-config as its generator.
    ("home/common/agent-skills/skills/retro/SKILL.md", "nix-config"),
    ("home/common/agent-skills/skills/retro/SKILL.md", "fagenorn/nix-config"),
    ("home/common/agent-skills/skills/retro/SKILL.md", "home/common/"),
}


def opens_token(line: str, start: int) -> bool:
    """Whether a token at `start` begins on its own: at the line start, after whitespace or after `(`/`[`.

    A run of `(`/`[` is looked through, but a run that follows anything but whitespace is inside a
    longer destination, bar the single `(` that opens a link destination straight after `]`.
    """
    first = start
    while first and line[first - 1] in "([":
        first -= 1
    before = line[first - 1:first]
    return not before or before.isspace() or (line[first:start] == "(" and before == "]")


def without_tracker_links(line: str) -> str:
    """The line with each tracker issue link blanked out, the whole destination being that link.

    A link destination is read as CommonMark reads it: `](<...>)` and `<...>` hold everything up to
    the closing `>`, so each is blanked only when that is exactly the issue link; a `<...>` that
    does not open a token (`opens_token`) is part of a longer destination and stays. Any other URL
    is a bare destination or prose: it is blanked (bar trailing punctuation) when it opens a token
    and is followed by whitespace, `)` or the end of the line. Anything else continues the
    destination, and the span stays.
    """
    def exact(match):
        return " " * len(match.group(0)) if TRACKER_ISSUE_LINK.fullmatch(match.group("url")) else match.group(0)

    def autolink(match):
        return exact(match) if opens_token(match.string, match.start()) else match.group(0)

    def blank(match):
        span = match.group(0)
        url = span.rstrip(".,;:!?")
        after = match.string[match.end():match.end() + 1]
        if not opens_token(match.string, match.start()) or (after and not (after.isspace() or after == ")")):
            return span
        return " " + span[len(url):] if TRACKER_ISSUE_LINK.fullmatch(url) else span
    line = ANGLE_DESTINATION.sub(exact, line)
    line = AUTOLINK.sub(autolink, line)
    return URL_SPAN.sub(blank, line)


def hosting_tokens(snapshot):
    """Literal tokens plus `just <recipe>` regexes (from the justfile) and required check names."""
    literals = list(HOSTING_LITERALS)
    protection = snapshot.read(".github/branch-protection.json")
    if protection is not None:
        literals += [c["context"] for c in json.loads(protection)["required_status_checks"]["checks"]]
    literals += sorted({path.split("/")[2] for path in snapshot.list_files("hosts/darwin")
                        if path.count("/") >= 3})  # darwin host directories
    justfile = snapshot.read("justfile")
    recipes = sorted(set(re.findall(
        r"^@?([a-z][a-z0-9_-]*)\b[^:\n]*:(?!=)", (justfile or b"").decode(), re.M)))
    return literals, recipes


def hosting_specifics(snapshot):
    """`path:line:token` for each hosting-project token in the installed global corpus, minus the allowlist."""
    literals, recipes = hosting_tokens(snapshot)
    patterns = [(t, re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(t) + r"(?![A-Za-z0-9_-])"
                               if t[0].isalnum() and t[-1].isalnum() else re.escape(t)))
                for t in literals]
    patterns += [(f"just {r}", re.compile(r"(?<![A-Za-z0-9_-])just " + re.escape(r) + r"(?![A-Za-z0-9_-])"))
                 for r in recipes]
    found = []
    scanned = set()
    for root in GLOBAL_CORPUS:
        for path in (snapshot.list_files(root) or ([root] if snapshot.read(root) is not None else [])):
            parts = path.split("/")
            if "evals" in parts or "__pycache__" in parts or parts[-1].startswith("LICENSE"):
                continue
            if parts[-1].endswith((".pyc", ".png", ".jpg", ".pdf")):
                continue
            scanned.add(root)
            text = (snapshot.read(path) or b"").decode("utf-8", "replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if path.startswith(TRACKER_LINK_ROOT + "/"):
                    line = without_tracker_links(line)
                found.extend(f"{path}:{number}:{token}" for token, pattern in patterns
                             if pattern.search(line) and (path, token) not in AGNOSTIC_ALLOW)
    missing = sorted(set(GLOBAL_CORPUS) - scanned)
    return sorted(found) + [f"{root}: no files scanned" for root in missing]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agnostic-lint")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        lines = hosting_specifics(working_tree(args.root))
    except (ValueError, OSError) as error:
        print(f"agnostic-lint: {' '.join(str(error).split())}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
