"""Read-only complete delivery projection and isolated owned-effect reconstruction."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import subprocess
import tempfile
from typing import Sequence

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import (PACKING_POLICY_SHA256, CandidateInput, FutureCommit, _run_git,
    actual_inputs, actual_inputs_from_trees, git_diff, select_candidate)
from agent_tools.review_budget import BudgetAuthority, describe
from agent_tools.review_forecast import (ForecastError, ForecastPlan, ancestor, canonical_bytes,
    closed, commit_range, digest, edge_facts, full_commit, identity, integer, load_plan,
    name, path_name, strict_json, tree_entry, history_commit, history_commits, _ownership)
from agent_tools.review_git import HistoryError, original_edge, _original_walk
from agent_tools.review_pack import ReviewRecordSize


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
                      owned_commits: Sequence[str]) -> Reconstruction:
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
    facts = {commit: tuple(edge_facts(repo, parent, commit, n)
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
                if any(tree_entry(target, before_tree, path) != tree_entry(repo, parent_tree, path)
                       for path in paths):
                    raise ReconstructionUnavailable("whole_path_preimage_unproved", commit)
                patch = git_diff(repo, parent_tree, originals[commit].tree, "--binary", "-U10")
                if patch:
                    applied = subprocess.run(["git", "-C", str(target), "apply", "--cached",
                        "--binary", "--whitespace=nowarn", "-"], input=patch, capture_output=True)
                    if applied.returncode:
                        raise ReconstructionUnavailable("patch_application_unproved", commit)
                after_tree = _run_git(target, "write-tree").strip()
                if any(tree_entry(target, after_tree, path) != tree_entry(repo, originals[commit].tree, path)
                       for path in paths):
                    raise ReconstructionUnavailable("whole_path_postimage_unproved", commit)
            included.add(commit)
            subject = _run_git(repo, "show", "-s", "--format=%s", commit, binary=True)
            commits.append({"sha": commit, "subject": subject.removesuffix(b"\n").decode("utf-8")})
        result_tree = _run_git(target, "write-tree").strip()
        # Producer manifest order is its reachable-range order, not replay traversal.
        metadata = {row["sha"]: row for row in commits}
        commits = [metadata[c] for c in manifest_order if c in metadata]
        return Reconstruction(target, prerequisite_tree, result_tree, tuple(commits), tuple(edges), scratch)
    except BaseException:
        scratch.cleanup()
        raise


def _package_name(value: object) -> str:
    path_name(value)
    if Path(value).name != value or Path(value).suffix != ".json" or not Path(value).stem:
        raise ForecastError("invalid package name")
    return value


def _included(plan: ForecastPlan, boundary: dict) -> tuple[dict, ...]:
    return tuple(r for r in plan.records if any(b["boundary"] == boundary["id"] for b in r["bounds"]))


def _completed_effects(plan: ForecastPlan, records: tuple[dict, ...], boundary: dict,
                       completed: int, actual: CandidateInput, candidate: tuple[Path, str]) -> None:
    paths = {r.path for r in actual.records}
    for record in records:
        if record["last_task"] > completed:
            continue
        effects = [r for edge in plan.ownership.edges
                   if plan.ownership.owners[edge["commit"]] == record["owner"]
                   and (record["owner"] or boundary["id"] in plan.ownership.process_memberships[edge["commit"]])
                   for r in edge["records"] if r["path"] == record["path"] or r["old_path"] == record["path"]]
        if not effects:
            raise ForecastError("completed contribution has no owned actual effect")
        if record["path"] not in paths:
            if record["change"] != "delete" or not any(r["operation"] == "D" for r in effects):
                raise ForecastError("completed contribution has no final actual effect")
            # Absence is proven in the candidate's own tree, never the full delivery head.
            if tree_entry(*candidate, record["path"]) is not None:
                raise ForecastError("completed deletion is not proven absent")


def _project_input(plan: ForecastPlan, boundary: dict, completed: int,
                   actual: CandidateInput, candidate: tuple[Path, str]) -> CandidateInput:
    records = _included(plan, boundary)
    _completed_effects(plan, records, boundary, completed, actual, candidate)
    latest = {}
    for record in records:
        latest[record["path"]] = record
    projected = {record.path: record for record in actual.records}
    future_lines = {"insertions": 0, "deletions": 0}
    changed = False
    for path, record in latest.items():
        if record["last_task"] <= completed:
            continue
        bound = next(b for b in record["bounds"] if b["boundary"] == boundary["id"])
        current = projected.get(path)
        size = bound["record_bytes"]
        # Generated evidence is an observed-record exception only. Unfinished
        # effects need their entire ordinary record, even on a generated path.
        if current is None or size > len(current.payload) or current.generated_evidence is not None:
            size = max(size, current.source_bytes if current is not None else 0)
            projected[path] = ReviewRecordSize(path, size)
            changed = True
        observed = {"insertions": 0, "deletions": 0}
        in_hunk = False
        for line in current.payload.splitlines() if current is not None else ():
            if line.startswith(b"@@ "):
                in_hunk = True
            elif in_hunk and line.startswith(b"+"):
                observed["insertions"] += 1
            elif in_hunk and line.startswith(b"-"):
                observed["deletions"] += 1
        future_lines["insertions"] += max(0, bound["added_lines"] - observed["insertions"])
        future_lines["deletions"] += max(0, bound["deleted_lines"] - observed["deletions"])
    future_subjects = []
    for task in plan.tasks:
        if task["id"] in boundary["tasks"] and task["id"] > completed:
            future_subjects.extend(task["commit_subject_bytes"])
    if max(boundary["tasks"]) > completed:
        future_subjects.extend(boundary["process_commit_subject_bytes"])
    future_commits = tuple(FutureCommit(
        telemetry_digest({"boundary": boundary["id"], "subject": number})[7:47], amount)
        for number, amount in enumerate(future_subjects))
    if not changed and not future_subjects and not any(future_lines.values()):
        return actual
    ordered = tuple(projected[path] for path in sorted(projected))
    stat = {"files_changed": len(ordered),
            "insertions": actual.stat["insertions"] + future_lines["insertions"],
            "deletions": actual.stat["deletions"] + future_lines["deletions"]}
    return replace(actual, records=ordered, future_commits=future_commits, stat=stat,
                   source_diff_bytes=sum(r.source_bytes for r in ordered))


def _prerequisite(plan: ForecastPlan, boundary: dict, completed: int) -> str | None:
    # Evidence can outlive a plan load. Authenticate original edge membership
    # before comparing freshly rebuilt facts, preserving the history error cause.
    try:
        for edge in plan.ownership.edges:
            original_edge(plan.repo, edge["parent"], edge["commit"], edge["parent_ordinal"])
    except HistoryError as exc:
        raise ForecastError("invalid original prerequisite edge") from exc
    if _ownership(plan.repo, plan.base, plan.head, plan.delivery, plan.tasks, plan.boundaries) != plan.ownership:
        raise ForecastError("prerequisite ownership evidence changed")
    prerequisite = boundary["prerequisite"]
    if prerequisite["kind"] == "delivery-base":
        return plan.base
    if any(task > completed for task in prerequisite["tasks"]):
        return None
    commit = full_commit(plan.repo, prerequisite["commit"])
    if (not ancestor(plan.repo, plan.base, commit)
            or not ancestor(plan.repo, commit, plan.ownership.evidence_head)
            or prerequisite["tree"] != history_commit(plan.repo, commit).tree):
        raise ForecastError("eligible prerequisite commit/tree mismatch")
    through = set(commit_range(plan.repo, plan.base, commit))
    expected = {c for c, owner in plan.ownership.owners.items() if owner in prerequisite["tasks"]}
    observed = {c for c in through if plan.ownership.owners[c] != 0}
    if observed != expected:
        raise ForecastError("eligible prerequisite product ownership mismatch")
    return commit


def _recommend(plan: ForecastPlan, completed: int, package_name: str,
               authority: BudgetAuthority) -> dict | None:
    if completed == len(plan.tasks):
        return None
    passing = []
    for order, boundary in enumerate(plan.boundaries):
        if boundary["id"] == plan.delivery["proposed_boundary"] or completed + 1 not in boundary["tasks"]:
            continue
        prerequisite = _prerequisite(plan, boundary, completed)
        if prerequisite is None:
            continue
        owned = tuple(c for c in plan.ownership.ordered_commits
                      if not ancestor(plan.repo, c, prerequisite)
                      and (plan.ownership.owners[c] in boundary["tasks"]
                           or (plan.ownership.owners[c] == 0
                               and boundary["id"] in plan.ownership.process_memberships[c])))
        with reconstruct_owned(plan.repo, prerequisite, owned) as rebuilt:
            source_head = owned[-1] if owned else prerequisite
            inputs = actual_inputs_from_trees(rebuilt.repo, rebuilt.prerequisite_tree, rebuilt.result_tree,
                base=prerequisite, head=source_head, commits=rebuilt.commits,
                package_name=package_name, limits=authority.limits)
            candidate = select_candidate(inputs, authority.limits,
                transform=lambda item: _project_input(plan, boundary, completed, item,
                                                     (rebuilt.repo, rebuilt.result_tree)),
                measurement_only=True)
            if candidate.status != "within_budget":
                continue
            row = {"id": boundary["id"], "tasks": boundary["tasks"], "prerequisite_commit": prerequisite,
                   "prerequisite_tree": rebuilt.prerequisite_tree, "actual_tree": rebuilt.result_tree,
                   "source_head": source_head, "contributions_sha256": telemetry_digest(rebuilt.ordered_edges),
                   "process_forecast_sha256": telemetry_digest({
                       "package": boundary["process_package"], "subjects": boundary["process_commit_subject_bytes"],
                       "records": [r for r in _included(plan, boundary) if r["owner"] == 0]}),
                   "metrics": dict(candidate.metrics), "budget_status": candidate.status, "violations": []}
            passing.append((len(boundary["tasks"]), candidate.metrics["total_bytes"], order, row))
    return min(passing, key=lambda value: value[:3])[3] if passing else None


def project(repo: Path, plan: Path, base: str, head: str, completed_through: int,
            package_name: str | None = None) -> dict:
    authority = describe("review-package")
    forecast = load_plan(repo, plan, base, head, authority)
    integer(completed_through, "completed-through")
    if completed_through > len(forecast.tasks):
        raise ForecastError("completed-through exceeds complete task set")
    for task in forecast.tasks:
        if task["id"] > completed_through and not task["commit_subject_bytes"] and any(
                record["change"] in {"add", "modify"}
                and tree_entry(repo, head, record["path"]) is None for record in task["records"]):
            raise ForecastError("future task content lacks a commit subject forecast")
    package_name = _package_name(package_name or f"review-{base[:7]}..{head[:7]}.json")
    boundary = next(b for b in forecast.boundaries if b["id"] == forecast.delivery["proposed_boundary"])
    # Null prerequisite identities are permitted only while their dependencies remain unfinished.
    for row in forecast.boundaries:
        pre = row["prerequisite"]
        if pre["kind"] == "completed-tasks" and max(pre["tasks"]) <= completed_through and pre["commit"] is None:
            raise ForecastError("completed prerequisite lacks immutable identities")
    actual_count = 0
    projected_count = 0
    def transform(item: CandidateInput) -> CandidateInput:
        nonlocal actual_count, projected_count
        projected = _project_input(forecast, boundary, completed_through, item, (forecast.repo, head))
        actual_count, projected_count = len(item.records), len(projected.records)
        return projected
    candidate = select_candidate(actual_inputs(repo, base, head, package_name, authority.limits),
                                 authority.limits, transform=transform, measurement_only=True)
    recommendation = _recommend(forecast, completed_through, package_name, authority) if candidate.status == "over_budget" else None
    result = {"schema_version": 3, "kind": "review-feasibility-result",
              "state": "complete" if candidate.status == "within_budget" else "decompose_required",
              "budget_status": candidate.status, "base": base, "head": head, "tree": forecast.tree,
              "plan_package_sha256": forecast.plan_package_sha256, "forecast_sha256": forecast.forecast_sha256,
              "packing_policy_sha256": PACKING_POLICY_SHA256, "artifact_policy_sha256": authority.policy_sha256,
              "actual_evidence_sha256": forecast.ownership.digest, "package_name": package_name,
              "completed_through": completed_through, "boundary": boundary["id"],
              "actual_record_count": actual_count, "projected_record_count": projected_count,
              "metrics": dict(candidate.metrics), "violations": list(candidate.violations),
              "recommended_boundary": recommendation}
    validate_result(canonical_bytes(result), 0 if candidate.status == "within_budget" else 3, authority)
    return result


def _metrics(value: object, authority: BudgetAuthority) -> list[str]:
    metrics = closed(value, "root_bytes total_bytes file_count largest_member_bytes", "metrics")
    for key, amount in metrics.items():
        integer(amount, key)
    if (metrics["file_count"] < 1 or metrics["root_bytes"] < 1
            or metrics["total_bytes"] < metrics["root_bytes"] + metrics["largest_member_bytes"]
            or metrics["total_bytes"] > metrics["root_bytes"] + metrics["largest_member_bytes"] * (metrics["file_count"] - 1)
            or (metrics["file_count"] == 1 and (metrics["largest_member_bytes"] or metrics["total_bytes"] != metrics["root_bytes"]))):
        raise ForecastError("inconsistent metrics")
    limits = authority.limits
    return [key for key, over in (
        ("root_bytes", metrics["root_bytes"] > limits.root_max_bytes),
        ("member_bytes", metrics["largest_member_bytes"] > limits.member_max_bytes),
        ("member_count", metrics["file_count"] - 1 > limits.max_members),
        ("aggregate_bytes", metrics["total_bytes"] > limits.aggregate_max_bytes)) if over]


def validate_result(raw: bytes, producer_exit: int, authority: BudgetAuthority) -> bytes:
    """Validate bounded canonical wire bytes before any consumer treats them as success."""
    if type(raw) is not bytes or not raw or len(raw) > authority.report_wire_max_bytes:
        raise ForecastError("result exceeds report wire bound")
    if type(producer_exit) is not int or producer_exit not in {0, 3}:
        raise ForecastError("invalid producer exit")
    value = closed(strict_json(raw), "schema_version kind state budget_status base head tree "
        "plan_package_sha256 forecast_sha256 packing_policy_sha256 artifact_policy_sha256 actual_evidence_sha256 "
        "package_name completed_through boundary actual_record_count projected_record_count metrics violations recommended_boundary", "result")
    if canonical_bytes(value) != raw:
        raise ForecastError("noncanonical result")
    if type(value["schema_version"]) is not int or value["schema_version"] != 3 or value["kind"] != "review-feasibility-result":
        raise ForecastError("unknown result schema")
    for field in ("base", "head", "tree"):
        identity(value[field], field)
    for field in ("plan_package_sha256", "forecast_sha256", "packing_policy_sha256", "artifact_policy_sha256", "actual_evidence_sha256"):
        digest(value[field])
    if value["packing_policy_sha256"] != PACKING_POLICY_SHA256 or value["artifact_policy_sha256"] != authority.policy_sha256:
        raise ForecastError("result policy identity mismatch")
    _package_name(value["package_name"])
    name(value["boundary"])
    for field in ("completed_through", "actual_record_count", "projected_record_count"):
        integer(value[field], field)
    if value["actual_record_count"] > value["projected_record_count"]:
        raise ForecastError("projection omitted actual records")
    violations = _metrics(value["metrics"], authority)
    if (value["violations"] != violations
            or value["budget_status"] != ("over_budget" if violations else "within_budget")
            or value["state"] != ("decompose_required" if violations else "complete")
            or producer_exit != (3 if violations else 0)):
        raise ForecastError("result budget/state/exit mismatch")
    recommended = value["recommended_boundary"]
    if recommended is not None:
        closed(recommended, "id tasks prerequisite_commit prerequisite_tree actual_tree source_head contributions_sha256 process_forecast_sha256 metrics budget_status violations", "recommendation")
        if not violations or name(recommended["id"]) == value["boundary"]:
            raise ForecastError("invalid recommendation boundary")
        tasks = recommended["tasks"]
        if (not isinstance(tasks, list) or not tasks or any(type(n) is not int or n < 1 for n in tasks)
                or tasks != sorted(set(tasks)) or value["completed_through"] + 1 not in tasks):
            raise ForecastError("invalid recommendation tasks")
        for field in ("prerequisite_commit", "prerequisite_tree", "actual_tree", "source_head"):
            identity(recommended[field], field)
        for field in ("contributions_sha256", "process_forecast_sha256"):
            digest(recommended[field])
        if (_metrics(recommended["metrics"], authority) or recommended["budget_status"] != "within_budget"
                or recommended["violations"] != []):
            raise ForecastError("recommendation is not within budget")
    return raw
