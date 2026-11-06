"""Isolated owned-effect reconstruction, kept for the retained review evidence (#605 deleted the projection)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Mapping, Sequence

from agent_tools.review_actual import RECORD_POLICY, RecordView, _run_git, commit_subject, git_diff
from agent_tools.review_forecast import (ForecastError, ancestor, edge_facts, full_commit, history_commit,
    history_commits, tree_entries)
from agent_tools.review_git import HistoryError, _original_walk


class ReconstructionUnavailable(ForecastError):
    """Valid owned evidence exceeds the supported whole-path replay proof."""

    def __init__(self, code: str, commit: str):
        self.code = code
        self.commit = commit
        detail = "merge effects: " if code == "merge_effects_unproved" else ""
        super().__init__(f"projection_unavailable: {detail}independence from excluded effects unproved ({code})")


@dataclass
class Reconstruction:
    repo: Path
    prerequisite_tree: str
    result_tree: str
    commits: tuple[dict, ...]
    ordered_edges: tuple[dict, ...]
    _scratch: tempfile.TemporaryDirectory

    def close(self) -> None:
        self._scratch.cleanup()

    def __enter__(self) -> Reconstruction:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def reconstruct_owned(repo: Path, prerequisite_commit: str,
                      owned_commits: Sequence[str], *,
                      record_policy: Mapping = RECORD_POLICY) -> Reconstruction:
    """Apply verified owned edges to a private index; source objects remain read-only."""
    prerequisite = history_commit(repo, prerequisite_commit)
    requested = tuple(owned_commits)
    if len(set(requested)) != len(requested):
        raise ForecastError("duplicate owned commit")
    for commit in requested:
        full_commit(repo, commit)
        if ancestor(repo, commit, prerequisite_commit):
            raise ForecastError("owned commit is already in prerequisite")
    # Authenticate the complete original closure and every edge before a whole-path
    # refusal can hide invalid later evidence. Preserve both historical orderings.
    try:
        ordered = tuple(c for c in _original_walk(repo, prerequisite_commit, requested,
                        topological=True) if c in set(requested))
        manifest_order = _original_walk(repo, prerequisite_commit, requested, topological=False)
    except HistoryError as exc:
        raise ForecastError("invalid original reconstruction history") from exc
    originals = dict(zip(ordered, history_commits(repo, ordered)))
    facts = {commit: tuple(edge_facts(repo, parent, commit, n, record_policy=record_policy)
             for n, parent in enumerate(originals[commit].parents, 1)) for commit in ordered}
    scratch = tempfile.TemporaryDirectory(prefix="review-owned-")
    target = Path(scratch.name)
    try:
        _run_git(target, "init", "-q")
        objects = Path(_run_git(repo, "rev-parse", "--git-path", "objects").strip())
        if not objects.is_absolute():
            objects = repo / objects
        (target / ".git/objects/info/alternates").write_text(str(objects.resolve()) + "\n", encoding="utf-8")
        prerequisite_tree = prerequisite.tree
        _run_git(target, "read-tree", prerequisite_tree)
        edges = []
        commits = []
        included = set()
        with RecordView(repo) as view:  # one record view for every patch and subject (issue 613)
            for commit in ordered:
                parents = originals[commit].parents
                if not parents:
                    raise ReconstructionUnavailable("owned_root_unproved", commit)
                edges.extend(facts[commit])
                if len(parents) > 1:
                    # A merge can only attest a tree already obtained once from its owned
                    # parents. Reapplying each parent diff would duplicate their effects.
                    if (any(p not in included and not ancestor(repo, p, prerequisite_commit) for p in parents)
                            or _run_git(target, "write-tree").strip() != originals[commit].tree):
                        raise ReconstructionUnavailable("merge_effects_unproved", commit)
                else:
                    parent_tree = history_commit(repo, parents[0]).tree
                    paths = {path for record in edges[-1]["records"]
                             for path in (record["old_path"], record["path"])}
                    before_tree = _run_git(target, "write-tree").strip()
                    # One listing per tree and side, rather than one per path (issue 613).
                    target_entries, source_entries = (tree_entries(target, before_tree, paths),
                                                      tree_entries(repo, parent_tree, paths))
                    if any(target_entries(path) != source_entries(path) for path in paths):
                        raise ReconstructionUnavailable("whole_path_preimage_unproved", commit)
                    patch = git_diff(view, parent_tree, originals[commit].tree, "--binary", "-U10",
                                     record_policy=record_policy)
                    if patch:
                        applied = subprocess.run(["git", "-C", str(target), "apply", "--cached",
                            "--binary", "--whitespace=nowarn", "-"], input=patch, capture_output=True)
                        if applied.returncode:
                            raise ReconstructionUnavailable("patch_application_unproved", commit)
                    after_tree = _run_git(target, "write-tree").strip()
                    target_entries, source_entries = (tree_entries(target, after_tree, paths),
                                                      tree_entries(repo, originals[commit].tree, paths))
                    if any(target_entries(path) != source_entries(path) for path in paths):
                        raise ReconstructionUnavailable("whole_path_postimage_unproved", commit)
                included.add(commit)
                commits.append({"sha": commit, "subject": commit_subject(view, commit)})
        result_tree = _run_git(target, "write-tree").strip()
        # Producer manifest order is its reachable-range order, not replay traversal.
        metadata = {row["sha"]: row for row in commits}
        commits = [metadata[c] for c in manifest_order if c in metadata]
        return Reconstruction(target, prerequisite_tree, result_tree, tuple(commits), tuple(edges), scratch)
    except BaseException:
        scratch.cleanup()
        raise

