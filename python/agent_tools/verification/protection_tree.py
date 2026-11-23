"""The `protection-matches-tree` verify check.

`protection-matches-tree --repo R --base B [--absent-label L ...]` (`protection_matches_tree`), run
through the wrapper `home/common/verify-pending/checks/protection-matches-tree` as
`python -m agent_tools.verification.protection_tree`, is met when the live `(context, app_id)`
requirements of B's protection, read as `required-checks` reads them
(`verify_checks._required_checks`), equal those of `.github/branch-protection.json` in the
repository root (the block's commit) and no label of R has a name equal to an L, compared
case-insensitively. It is not met otherwise, and the report names `missing` (in the tree, not
live), `extra` (live, not in the tree) and `labels_present`; it exits 2 on a forge error or an
unreadable or malformed tree file. It only reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_tools.system import forge_api
from agent_tools.verification.verify_checks import Requirement, _is_int, _invalid, _repo, _required_checks


def _tree_requirements(root: Path) -> set[Requirement]:
    """The `(context, app_id)` pairs of `<root>/.github/branch-protection.json`, an absent, null or
    -1 `app_id` read as any app, as `_required_checks` reads the live ones."""
    try:
        tree = json.loads((root / ".github" / "branch-protection.json").read_text())
    except (OSError, ValueError) as error:
        raise _invalid(f"branch-protection.json is unreadable: {error}") from error
    block = tree.get("required_status_checks") if isinstance(tree, dict) else None
    entries = block.get("checks") if isinstance(block, dict) else None
    if not isinstance(entries, list):
        raise _invalid("branch-protection.json has no required_status_checks.checks list")
    found: set[Requirement] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("context"), str):
            raise _invalid("branch-protection.json check has no context")
        app_id = entry.get("app_id")
        if app_id is not None and not _is_int(app_id):
            raise _invalid("branch-protection.json app_id is not an integer or null")
        found.add((entry["context"], None if app_id == -1 else app_id))
    return found


def _label_names(repo: str) -> list[str]:
    names = []
    for page in forge_api.api_pages(f"repos/{repo}/labels?per_page=100"):
        if not isinstance(page, list):
            raise _invalid("label page is not a list")
        for label in page:
            if not isinstance(label, dict) or not isinstance(label.get("name"), str):
                raise _invalid("label has no name")
            names.append(label["name"])
    return names


def _order(item: Requirement) -> tuple[str, bool, int]:
    return (item[0], item[1] is not None, item[1] or 0)


def protection_matches_tree(repo: str, base: str, root: Path,
                            absent_labels: Sequence[str]) -> tuple[int, dict]:
    """Met when the live required checks equal the tree's and no label is named in `absent_labels`."""
    wanted = _tree_requirements(root)
    live = set(_required_checks(repo, base))
    gone = {name.casefold() for name in absent_labels}
    present = sorted(name for name in _label_names(repo) if name.casefold() in gone)
    missing, extra = sorted(wanted - live, key=_order), sorted(live - wanted, key=_order)
    report = {"met": not (missing or extra or present), "missing": [list(r) for r in missing],
              "extra": [list(r) for r in extra], "labels_present": present}
    return (0 if report["met"] else 1), report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protection-matches-tree")
    parser.add_argument("--repo", type=_repo, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--absent-label", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        code, report = protection_matches_tree(args.repo, args.base, Path.cwd(), args.absent_label)
    except forge_api.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
