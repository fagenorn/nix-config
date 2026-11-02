"""Select the range ship reviews: the delta since sdd's final review, or the whole branch.

`review-range [--root DIR] --integration-ref REF --head REV
[--final-review-head REV] --max-lines N --max-files N [--artifact-path PATH]...`
prints one canonical JSON object with the keys `route`, `reason`,
`final_review_head`, `head`, `review_base`, `product_lines` and
`product_files`. `route` is `delta` (reason `within_gate`), `empty` (reason
`no_changes`) or `full` (reason `no_final_review_head`,
`final_review_head_not_on_branch`, `foreign_merge`, `sync_not_reproducible` or
`over_gate`); `full` always carries `review_base: null`. The helper never moves
a ref or touches the index or working tree: its only writes are
`merge-tree --write-tree` trees and one unsigned, unreferenced `commit-tree`
base with a fixed identity and date. It exits 0 for every decision, 2 for a
usage error, and 1 with empty stdout and one `review-range: <detail>` stderr
line when no decision can be made.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

from agent_tools import diff_scope


SCRATCH_IDENTITY = {
    "GIT_AUTHOR_NAME": "review-range",
    "GIT_COMMITTER_NAME": "review-range",
    "GIT_AUTHOR_EMAIL": "review-range@invalid",
    "GIT_COMMITTER_EMAIL": "review-range@invalid",
    "GIT_AUTHOR_DATE": "@0 +0000",
    "GIT_COMMITTER_DATE": "@0 +0000",
}


class ReviewRangeError(Exception):
    """A condition under which no decision can be made; main exits 1."""


@dataclass(frozen=True)
class Decision:
    """One review-range decision, serialised key for key by format_json."""

    route: str
    reason: str
    final_review_head: str | None
    head: str
    review_base: str | None
    product_lines: int | None
    product_files: int | None


def _git(
    root: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
    ok: tuple[int, ...] = (0,),
) -> tuple[int, bytes]:
    """Run one git command by argv; return (code, stdout) when the code is in `ok`."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        raise ReviewRangeError("git executable not found on PATH") from None
    if completed.returncode not in ok:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReviewRangeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.returncode, completed.stdout


def _resolve(root: Path, revision: str) -> str | None:
    """The full commit id `revision` names, or None when it names no commit."""
    code, stdout = _git(
        root, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", ok=(0, 1)
    )
    if code == 1:
        return None
    return stdout.decode("utf-8").strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    code, _stdout = _git(
        root, "merge-base", "--is-ancestor", ancestor, descendant, ok=(0, 1)
    )
    return code == 0


def _validate_root(root: Path) -> None:
    message = f"--root is not a git work tree: {root}"
    if not root.is_dir():
        raise ReviewRangeError(message)
    _code, answer = _git(root, "rev-parse", "--is-inside-work-tree")
    if answer.strip() != b"true":
        raise ReviewRangeError(message)


def _first_parent_path(root: Path, base: str, head: str) -> list[tuple[str, ...]] | None:
    """`base..head` on head's first-parent history, oldest first, as (commit, *parents).

    None when `base` is not on that history: it is not an ancestor, or it is
    reached only through a second parent.
    """
    if base == head:
        return []
    if not _is_ancestor(root, base, head):
        return None
    _code, stdout = _git(root, "rev-list", "--first-parent", "--parents", f"{base}..{head}")
    entries = [tuple(line.split()) for line in reversed(stdout.decode("utf-8").splitlines())]
    if not entries or len(entries[0]) < 2 or entries[0][1] != base:
        return None
    return entries


def _sync_parent(
    root: Path, path: Sequence[tuple[str, ...]], integration: str
) -> tuple[bool, str | None]:
    """(ok, P): P is the newest sync's second parent, None on a merge-free path.

    `ok` is False when any merge on the path is not a sync merge, or an earlier
    sync's second parent is not an ancestor of P.
    """
    merges = [entry for entry in path if len(entry) > 2]
    if not merges:
        return True, None
    for entry in merges:
        if len(entry) != 3 or not _is_ancestor(root, entry[2], integration):
            return False, None
    newest = merges[-1][2]
    for entry in merges[:-1]:
        if not _is_ancestor(root, entry[2], newest):
            return False, None
    return True, newest


def _synced_base(root: Path, reviewed: str, synced: str) -> str | None:
    """The deterministic scratch commit of `reviewed` merged with `synced`, or None on conflict."""
    code, stdout = _git(
        root, "merge-tree", "--write-tree", "--no-messages", reviewed, synced, ok=(0, 1)
    )
    if code == 1:
        return None
    tree = stdout.decode("utf-8").splitlines()[0].strip()
    env = {**os.environ, **SCRATCH_IDENTITY}
    _code, commit = _git(
        root,
        "commit-tree",
        "--no-gpg-sign",
        "-p",
        reviewed,
        "-p",
        synced,
        "-m",
        f"review-range base: {reviewed} synced with {synced}",
        tree,
        env=env,
    )
    return commit.decode("utf-8").strip()


def decide(
    root: Path,
    *,
    head: str,
    final_review_head: str | None,
    integration_ref: str,
    max_lines: int,
    max_files: int,
    artifact_paths: Sequence[bytes],
) -> Decision:
    """Select delta, empty or full for the branch at `head` (D2, D3)."""
    _validate_root(root)
    head_oid = _resolve(root, head)
    if head_oid is None:
        raise ReviewRangeError(f"cannot resolve --head {head}")
    integration_oid = _resolve(root, integration_ref)
    if integration_oid is None:
        raise ReviewRangeError(f"cannot resolve --integration-ref {integration_ref}")

    def full(reason: str, reviewed: str | None, lines=None, files=None) -> Decision:
        return Decision("full", reason, reviewed, head_oid, None, lines, files)

    if final_review_head is None:
        return full("no_final_review_head", None)
    reviewed = _resolve(root, final_review_head)
    if reviewed is None:
        return full("final_review_head_not_on_branch", None)
    path = _first_parent_path(root, reviewed, head_oid)
    if path is None:
        return full("final_review_head_not_on_branch", reviewed)
    synced_ok, synced = _sync_parent(root, path, integration_oid)
    if not synced_ok:
        return full("foreign_merge", reviewed)
    if synced is None:
        review_base = reviewed
    else:
        review_base = _synced_base(root, reviewed, synced)
        if review_base is None:
            return full("sync_not_reproducible", reviewed)
    try:
        result = diff_scope.measure(root, review_base, head_oid, artifact_paths)
    except diff_scope.DiffScopeError as error:
        raise ReviewRangeError(str(error)) from None
    lines, files = result.changed_lines, result.changed_files
    if files == 0 and sum(result.excluded.values()) == 0:
        return Decision("empty", "no_changes", reviewed, head_oid, review_base, 0, 0)
    if lines > max_lines or files > max_files:
        return full("over_gate", reviewed, lines, files)
    return Decision("delta", "within_gate", reviewed, head_oid, review_base, lines, files)


def format_json(decision: Decision) -> str:
    """One line of canonical JSON for the decision."""
    payload = asdict(decision)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def _non_negative(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative: {text}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-range", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="the git work tree to decide in (default: the current directory)",
    )
    parser.add_argument("--integration-ref", required=True, metavar="REF",
                        help="the integration branch a sync merge brings in")
    parser.add_argument("--head", required=True, metavar="REV",
                        help="the post-sync ship head")
    parser.add_argument("--final-review-head", metavar="REV",
                        help="the head sdd's final review saw")
    parser.add_argument("--max-lines", required=True, type=_non_negative, metavar="N",
                        help="the gate's product-line threshold (inclusive)")
    parser.add_argument("--max-files", required=True, type=_non_negative, metavar="N",
                        help="the gate's product-file threshold (inclusive)")
    parser.add_argument(
        "--artifact-path",
        action="append",
        default=[],
        metavar="PATH",
        help="repository-relative path holding this run's own artifacts; repeatable",
    )
    return parser


def _one_line(error: Exception) -> str:
    return "; ".join(line.strip() for line in str(error).splitlines() if line.strip())


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact_paths = tuple(
            diff_scope.normalize_artifact_path(value) for value in args.artifact_path
        )
        decision = decide(
            Path(args.root),
            head=args.head,
            final_review_head=args.final_review_head,
            integration_ref=args.integration_ref,
            max_lines=args.max_lines,
            max_files=args.max_files,
            artifact_paths=artifact_paths,
        )
    except (ReviewRangeError, diff_scope.DiffScopeError) as error:
        print(f"review-range: {_one_line(error)}", file=sys.stderr)
        return 1
    sys.stdout.write(format_json(decision))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
