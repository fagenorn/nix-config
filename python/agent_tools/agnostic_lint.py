"""Refuse hosting-project specifics in the installed global agent corpus (#572)."""

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
                    "home/common/", "python/agent_tools/")
# Every exemption is one (file, token) pair with its reason; evals and LICENSE files are skipped by name.
AGNOSTIC_ALLOW = {
    # retro audits the global environment and legitimately names nix-config as its generator.
    ("home/common/agent-skills/skills/retro/SKILL.md", "nix-config"),
    ("home/common/agent-skills/skills/retro/SKILL.md", "fagenorn/nix-config"),
    ("home/common/agent-skills/skills/retro/SKILL.md", "home/common/"),
}


def hosting_tokens(snapshot):
    """Literal tokens plus `just <recipe>` regexes (from the justfile) and required check names."""
    literals = list(HOSTING_LITERALS)
    protection = snapshot.read(".github/branch-protection.json")
    if protection is not None:
        literals += [c["context"] for c in json.loads(protection)["required_status_checks"]["checks"]]
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
