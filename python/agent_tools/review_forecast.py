"""Closed committed forecast packages, boundary graphs and Git ownership evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal, telemetry_digest
from agent_tools.review_actual import (SHA_RE, _run_git, _split_diff, git_diff)
from agent_tools.review_budget import BudgetAuthority
from agent_tools.review_git import (HistoryError, original_commit, original_commits, original_range,
                                    original_ancestor, original_edge)


class ForecastError(Exception):
    """A forecast is malformed, uncommitted or unsupported by its evidence."""


def closed(value: object, keys: str, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ForecastError(f"invalid {label} fields")
    return value


def integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ForecastError(f"invalid {label}")
    return value


def identity(value: object, label: str = "commit") -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ForecastError(f"invalid {label} identity")
    return value


def digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ForecastError("invalid digest")
    return value


def name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None:
        raise ForecastError("invalid identifier")
    return value


def path_name(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ForecastError("invalid path")
    path = PurePosixPath(value)
    if (path.is_absolute() or str(path) != value or value == "."
            or any(part in {".", "..", ".git"} for part in path.parts)):
        raise ForecastError("unsafe path")
    return value


def ordinals(value: object, count: int) -> list[int]:
    if (not isinstance(value, list) or not value
            or any(type(n) is not int or not 1 <= n <= count for n in value)
            or value != sorted(set(value))):
        raise ForecastError("invalid task ordinals")
    return value


def subjects(value: object) -> list[int]:
    if not isinstance(value, list):
        raise ForecastError("invalid subject forecasts")
    for item in value:
        integer(item, "subject byte bound")
    return value


def process_paths(package: dict) -> list[str]:
    return [package["spec"], package["plan"], *package["tasks"]]


def validate_boundaries(boundaries: list[dict], task_count: int, proposed: str) -> tuple[dict, ...]:
    """Validate containment and dependency graphs without changing input order."""
    integer(task_count, "task count", 1)
    name(proposed)
    if not isinstance(boundaries, list) or not boundaries:
        raise ForecastError("missing boundaries")
    by_id = {}
    for row in boundaries:
        closed(row, "id parent tasks acceptance depends_on prerequisite process_package "
               "process_forecast_ids process_commit_subject_bytes", "boundary")
        key = name(row["id"])
        if key in by_id:
            raise ForecastError("duplicate boundary")
        by_id[key] = row
        if row["parent"] is not None:
            name(row["parent"])
        ordinals(row["tasks"], task_count)
        if not isinstance(row["acceptance"], str) or not row["acceptance"].strip():
            raise ForecastError("missing standalone acceptance")
        deps = row["depends_on"]
        if not isinstance(deps, list) or len(set(map(name, deps))) != len(deps):
            raise ForecastError("invalid dependencies")
        package = closed(row["process_package"], "spec plan tasks", "process package")
        path_name(package["spec"])
        plan = PurePosixPath(path_name(package["plan"]))
        expected = [str(plan.with_suffix(".tasks") / f"task-{n}.md")
                    for n in range(1, len(row["tasks"]) + 1)]
        if (plan.suffix != ".md" or package["tasks"] != expected
                or len(set(process_paths(package))) != len(expected) + 2):
            raise ForecastError("invalid process package members")
        ids = row["process_forecast_ids"]
        if (not isinstance(ids, list) or len(ids) != len(expected) + 2
                or len(set(map(name, ids))) != len(ids)):
            raise ForecastError("invalid process forecast identities")
        subjects(row["process_commit_subject_bytes"])
    roots = [r for r in boundaries if r["parent"] is None]
    if len(roots) != 1 or roots[0]["id"] != proposed or roots[0]["tasks"] != list(range(1, task_count + 1)):
        raise ForecastError("root must be the complete proposed delivery")
    children = {key: [] for key in by_id}
    for row in boundaries:
        parent = row["parent"]
        if parent is not None:
            if parent not in by_id or parent == row["id"]:
                raise ForecastError("invalid parent")
            children[parent].append(row)
    visited = set()
    def visit(key: str) -> None:
        if key in visited:
            raise ForecastError("containment cycle")
        visited.add(key)
        parts = children[key]
        if parts:
            tasks = [task for child in parts for task in child["tasks"]]
            if sorted(tasks) != by_id[key]["tasks"]:
                raise ForecastError("children must partition parent tasks")
        for child in parts:
            visit(child["id"])
    visit(proposed)
    if len(visited) != len(boundaries):
        raise ForecastError("unreachable boundary")
    dependency_tasks = {}
    active = set()
    def dependencies(key: str) -> set[int]:
        if key in active:
            raise ForecastError("dependency cycle")
        if key in dependency_tasks:
            return dependency_tasks[key]
        active.add(key)
        row = by_id[key]
        tasks = set()
        for dep in row["depends_on"]:
            if dep not in by_id or max(by_id[dep]["tasks"]) >= min(row["tasks"]):
                raise ForecastError("dependency must be a preceding disjoint delivery")
            tasks.update(by_id[dep]["tasks"])
            tasks.update(dependencies(dep))
        active.remove(key)
        dependency_tasks[key] = tasks
        return tasks
    for row in boundaries:
        tasks = dependencies(row["id"])
        prerequisite = row["prerequisite"]
        if not tasks:
            if prerequisite != {"kind": "delivery-base"}:
                raise ForecastError("unexpected prerequisite")
        else:
            closed(prerequisite, "kind tasks commit tree", "prerequisite")
            if (prerequisite["kind"] != "completed-tasks"
                    or ordinals(prerequisite["tasks"], task_count) != sorted(tasks)):
                raise ForecastError("prerequisite task closure mismatch")
            if prerequisite["commit"] is None and prerequisite["tree"] is None:
                continue
            identity(prerequisite["commit"])
            identity(prerequisite["tree"], "tree")
    return tuple(boundaries)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def strict_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except (ValueError, UnicodeError) as exc:
        raise ForecastError("invalid JSON") from exc


def raw_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_regular(repo: Path, relative: str, limit: int | None = None) -> bytes:
    """Read through no-follow directory descriptors, including intermediate parents."""
    parts = PurePosixPath(path_name(relative)).parts
    fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        # Non-blocking so a FIFO or device is refused below instead of hanging the open.
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(child)
            if not stat.S_ISREG(before.st_mode):
                raise ForecastError("package member is not regular")
            if limit is not None and before.st_size > limit:
                raise ForecastError("input exceeds byte bound")
            with os.fdopen(child, "rb", closefd=False) as stream:
                raw = stream.read() if limit is None else stream.read(limit + 1)
            after = os.fstat(child)
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ForecastError("package changed during read")
            if limit is not None and len(raw) > limit:
                raise ForecastError("input exceeds byte bound")
            return raw
        finally:
            os.close(child)
    finally:
        os.close(fd)


def tree_entry(repo: Path, tree: str, path: str) -> dict | None:
    raw = _run_git(repo, "ls-tree", "-z", tree, "--", path, binary=True)
    if not raw:
        return None
    rows = raw.split(b"\0")
    if len(rows) != 2 or rows[1] or b"\t" not in rows[0]:
        raise ForecastError("ambiguous tree entry")
    metadata, found = rows[0].split(b"\t", 1)
    mode, kind, oid = metadata.decode("ascii").split()
    if found != path.encode("utf-8"):
        raise ForecastError("tree path mismatch")
    return {"mode": mode, "kind": kind, "oid": identity(oid, "object")}


def committed_bytes(repo: Path, head: str, path: str) -> bytes:
    entry = tree_entry(repo, head, path)
    if entry is None or entry["kind"] != "blob" or entry["mode"] not in {"100644", "100755"}:
        raise ForecastError("package is not a committed regular file")
    raw = read_regular(repo, path)
    if raw != _run_git(repo, "cat-file", "blob", entry["oid"], binary=True):
        raise ForecastError("dirty package bytes")
    # An index-only edit is dirty even when the worktree was restored manually.
    if _run_git(repo, "diff", "--cached", "--name-only", head, "--", path):
        raise ForecastError("dirty package index")
    return raw


def full_commit(repo: Path, value: str) -> str:
    identity(value)
    history_commit(repo, value)
    return value


def history_commit(repo: Path, value: str):
    try:
        return original_commit(repo, value)
    except HistoryError as exc:
        raise ForecastError("invalid original history") from exc


def history_commits(repo: Path, values: Sequence[str]):
    try:
        return original_commits(repo, values)
    except HistoryError as exc:
        raise ForecastError("invalid original history") from exc


def ancestor(repo: Path, base: str, head: str) -> bool:
    try:
        return original_ancestor(repo, base, head)
    except HistoryError as exc:
        raise ForecastError("invalid original ancestry") from exc


def commit_range(repo: Path, base: str, head: str) -> tuple[str, ...]:
    """Expand Git reachability differences, including disjoint branch endpoints."""
    try:
        return original_range(repo, base, head)
    except HistoryError as exc:
        raise ForecastError("invalid original range") from exc


def _block(raw: bytes, heading: str) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ForecastError("non-UTF8 forecast") from exc
    lines = text.splitlines()
    if lines.count(heading) != 1:
        raise ForecastError("ambiguous forecast section")
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start:end]).strip()
    match = re.fullmatch(r"```json\n([^\n]+)\n```", body)
    if match is None:
        raise ForecastError("forecast section must contain one canonical JSON block")
    encoded = match.group(1).encode("utf-8") + b"\n"
    value = strict_json(encoded)
    if not isinstance(value, dict) or canonical_bytes(value) != encoded:
        raise ForecastError("noncanonical forecast block")
    return value


def edge_facts(repo: Path, parent: str, commit: str, ordinal: int) -> dict:
    """Bind all original parent edges to independently read tree and record facts."""
    try:
        parent_commit, child_commit = original_edge(repo, parent, commit, ordinal)
    except HistoryError as exc:
        raise ForecastError("invalid original edge") from exc
    parent_tree, commit_tree = parent_commit.tree, child_commit.tree
    status = git_diff(repo, parent_tree, commit_tree, "--name-status", "-z").split(b"\0")
    if status[-1] != b"":
        raise ForecastError("invalid Git status framing")
    status.pop()
    chunks = _split_diff(git_diff(repo, parent_tree, commit_tree, "--binary", "-U10"))
    facts = []
    while status:
        operation = status.pop(0).decode("ascii")
        old = path_name(status.pop(0).decode("utf-8"))
        new = path_name(status.pop(0).decode("utf-8")) if operation == "R100" else old
        if operation not in {"A", "M", "D", "T", "R100"}:
            raise ForecastError("unsupported Git record operation")
        facts.append({"operation": operation, "path": new, "old_path": old,
                      "before": tree_entry(repo, parent_tree, old), "after": tree_entry(repo, commit_tree, new)})
    if len(chunks) != len(facts):
        raise ForecastError("Git edge record coverage mismatch")
    for item, chunk in zip(facts, chunks):
        item.update(record_bytes=len(chunk), record_sha256=raw_digest(chunk))
    return {"parent": parent, "commit": commit, "parent_ordinal": ordinal, "records": facts}


@dataclass(frozen=True)
class Ownership:
    evidence_head: str
    owners: Mapping[str, int]
    process_memberships: Mapping[str, tuple[str, ...]]
    ordered_commits: tuple[str, ...]
    edges: tuple[dict, ...]
    digest: str


@dataclass(frozen=True)
class ForecastPlan:
    repo: Path
    path: Path
    base: str
    head: str
    tree: str
    delivery: dict
    tasks: tuple[dict, ...]
    boundaries: tuple[dict, ...]
    records: tuple[dict, ...]
    ownership: Ownership
    plan_package_sha256: str
    forecast_sha256: str


def _records(delivery: dict, tasks: tuple[dict, ...], boundaries: tuple[dict, ...]) -> tuple[dict, ...]:
    count = len(tasks)
    gathered = []
    seen = set()
    prefixes = {row["id"]: {} for row in boundaries}
    horizons = {row["id"]: {} for row in boundaries}
    for owner, records in [(0, delivery["process_records"]), *((t["id"], t["records"]) for t in tasks)]:
        if not isinstance(records, list):
            raise ForecastError("invalid contribution list")
        for record in records:
            closed(record, "id owner path change last_task bounds", "contribution")
            record_id = name(record["id"])
            if record_id in seen or type(record["owner"]) is not int or record["owner"] != owner:
                raise ForecastError("duplicate or incorrect contribution owner")
            seen.add(record_id)
            path_name(record["path"])
            horizon = integer(record["last_task"], "contribution horizon", 1)
            if not max(owner, 1) <= horizon <= count:
                raise ForecastError("invalid contribution horizon")
            if record["change"] not in {"add", "modify", "delete", "rename", "fileless"}:
                raise ForecastError("unknown contribution operation")
            if record["change"] in {"rename", "fileless"}:
                raise ForecastError("projection_unavailable: operation requires retained adapter proof")
            bounds = record["bounds"]
            if not isinstance(bounds, list) or not bounds:
                raise ForecastError("missing cumulative bounds")
            required = [b["id"] for b in boundaries if owner in b["tasks"]] if owner else [
                b["id"] for b in boundaries if record_id in b["process_forecast_ids"]]
            if [b.get("boundary") for b in bounds if isinstance(b, dict)] != required:
                raise ForecastError("incomplete or unordered boundary membership")
            for bound in bounds:
                closed(bound, "boundary added_lines deleted_lines record_bytes support", "bound")
                member = next(row for row in boundaries if row["id"] == bound["boundary"])
                previous_horizon = horizons[bound["boundary"]].get(record["path"], 0)
                if horizon < previous_horizon or (owner and horizon not in member["tasks"]):
                    raise ForecastError("contribution horizon disagrees with boundary membership")
                horizons[bound["boundary"]][record["path"]] = horizon
                for field in ("added_lines", "deleted_lines", "record_bytes"):
                    integer(bound[field], field)
                support = closed(bound["support"], "kind covers", "cumulative support")
                prefix = prefixes[bound["boundary"]].setdefault(record["path"], [])
                prefix.append(record_id)
                if support["kind"] != "authored-cumulative/v1" or support["covers"] != prefix:
                    raise ForecastError("incomplete ordered same-path provenance")
            gathered.append(record)
    by_id = {r["id"]: r for r in gathered}
    for boundary in boundaries:
        selected = [by_id.get(key) for key in boundary["process_forecast_ids"]]
        if (any(r is None or r["owner"] != 0 for r in selected)
                or [r["path"] for r in selected] != process_paths(boundary["process_package"])):
            raise ForecastError("process package forecast mismatch")
    return tuple(gathered)


def _ownership(repo: Path, base: str, head: str, delivery: dict, tasks: tuple[dict, ...],
               boundaries: tuple[dict, ...]) -> Ownership:
    evidence = closed(delivery["actual_evidence"], "kind head tree process_ranges", "actual evidence")
    if evidence["kind"] != "git-range-ownership/v1":
        raise ForecastError("unknown ownership evidence")
    checkpoint = identity(evidence["head"])
    checkpoint_commit = history_commit(repo, checkpoint)
    if identity(evidence["tree"], "tree") != checkpoint_commit.tree:
        raise ForecastError("evidence tree mismatch")
    if not ancestor(repo, base, checkpoint):
        raise ForecastError("delivery base is not an evidence ancestor")
    complete = commit_range(repo, base, checkpoint)
    closure = {base, *complete}
    if not ancestor(repo, checkpoint, head):
        raise ForecastError("evidence is not an invocation prefix")
    positions = {sha: n for n, sha in enumerate(complete)}
    owners = {}
    memberships = {}
    by_id = {b["id"]: b for b in boundaries}
    ranges = []
    for task in tasks:
        ranges.append((task["id"], task["actual_ranges"]))
    ranges.append((0, evidence["process_ranges"]))
    for owner, rows in ranges:
        if not isinstance(rows, list):
            raise ForecastError("invalid ownership ranges")
        previous = -1
        for row in rows:
            closed(row, "base head" if owner else "base head boundaries", "ownership range")
            if row["base"] not in closure or row["head"] not in closure:
                raise ForecastError("ownership endpoints outside delivery closure")
            commits = commit_range(repo, row["base"], row["head"])
            if not commits or any(c not in positions or c in owners for c in commits):
                raise ForecastError("empty, overlapping or out-of-range ownership")
            earliest = min(positions[c] for c in commits)
            if earliest <= previous:
                raise ForecastError("ownership ranges are not topologically ordered")
            previous = earliest
            if owner == 0:
                member_ids = row["boundaries"]
                if (not isinstance(member_ids, list) or not member_ids
                        or member_ids != [b["id"] for b in boundaries if b["id"] in member_ids]):
                    raise ForecastError("invalid observed process membership")
                for commit in commits:
                    memberships[commit] = tuple(member_ids)
            for commit in commits:
                owners[commit] = owner
    if set(owners) != set(complete):
        raise ForecastError("ownership must classify every evidence commit")
    tail = commit_range(repo, checkpoint, head)
    sequence = (*complete, *tail)
    held = dict(zip(sequence, history_commits(repo, sequence)))
    previous = checkpoint
    for commit in tail:
        parents = held[commit].parents
        if parents != (previous,):
            raise ForecastError("metadata tail is not a first-parent chain")
        owners[commit] = 0
        memberships[commit] = (delivery["proposed_boundary"],)
        previous = commit
    edges = []
    for commit in (*complete, *tail):
        parents = held[commit].parents
        for ordinal, parent in enumerate(parents, 1):
            edge = edge_facts(repo, parent, commit, ordinal)
            if owners[commit] == 0:
                allowed = {path for key in memberships[commit] for path in process_paths(by_id[key]["process_package"])}
                if any(r["path"] not in allowed or r["old_path"] not in allowed for r in edge["records"]):
                    raise ForecastError("process ownership contains undeclared paths")
            edges.append(edge)
    logical = {"evidence": evidence, "task_ranges": [t["actual_ranges"] for t in tasks],
               "commits": [{"commit": c, "owner": owners[c], "boundaries": list(memberships.get(c, ()))}
                           for c in (*complete, *tail)], "edges": edges,
               "metadata_tail": list(tail)}
    return Ownership(checkpoint, owners, memberships, (*complete, *tail), tuple(edges), telemetry_digest(logical))


def _derivation(repo: Path, head: str, derived: object) -> None:
    if derived is None:
        return
    closed(derived, "kind path anchor_sha256", "derivation")
    if derived["kind"] != "retained-anchor/v2":
        raise ForecastError("unsupported derivation")
    anchor_path = path_name(derived["path"])
    anchor_raw = committed_bytes(repo, head, anchor_path)
    anchor = closed(strict_json(anchor_raw), "schema_version kind tool issue_121 issue_100 archive estimate payload", "anchor")
    if (type(anchor["schema_version"]) is not int or anchor["schema_version"] != 2
            or anchor["kind"] != "review-feasibility-derivation-anchor"
            or canonical_bytes(anchor) != anchor_raw
            or telemetry_digest(anchor) != digest(derived["anchor_sha256"])):
        raise ForecastError("retained anchor identity mismatch")
    if any(not isinstance(anchor[key], dict) for key in ("tool", "issue_121", "issue_100", "archive", "estimate")):
        raise ForecastError("invalid anchor provenance groups")
    payload = closed(anchor["payload"], "encoding members", "anchor payload")
    expected = ["derivation-witness.json", "issue-100-derived.json", "issue-121.json", "task7-estimate.json"]
    if payload["encoding"] != "canonical-json-ascii-lf/v1" or not isinstance(payload["members"], list):
        raise ForecastError("invalid anchor payload encoding")
    for member in payload["members"]:
        closed(member, "path bytes raw_sha256", "anchor payload member")
    if [member["path"] for member in payload["members"]] != expected:
        raise ForecastError("invalid anchor payload closure")
    for member in payload["members"]:
        integer(member["bytes"], "payload bytes")
        if not isinstance(member["raw_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", member["raw_sha256"]) is None:
            raise ForecastError("invalid raw payload digest")
        path = str(PurePosixPath(anchor_path).parent / member["path"])
        raw = committed_bytes(repo, head, path)
        if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["raw_sha256"]:
            raise ForecastError("retained payload identity mismatch")


def load_plan(repo: Path, plan: Path, base: str, head: str, authority: BudgetAuthority) -> ForecastPlan:
    """Load the complete checked package and bind its exact bytes to immutable Git."""
    repo = repo.resolve()
    plan = plan.absolute()
    alias = next((parent for parent in plan.parents if parent.resolve() == repo), None)
    if alias is None:
        raise ForecastError("plan is outside repository")
    plan = repo / plan.relative_to(alias)
    full_commit(repo, base)
    full_commit(repo, head)
    if _run_git(repo, "rev-parse", "HEAD").strip() != head or not ancestor(repo, base, head):
        raise ForecastError("invocation head or base mismatch")
    relative = path_name(plan.relative_to(repo).as_posix())
    checked = authority.check("implementation-plan", plan)
    if checked.status != "within_budget":
        raise ForecastError("plan package exceeds budget")
    raw = committed_bytes(repo, head, relative)
    delivery = _block(raw, "## Review feasibility delivery")
    closed(delivery, "schema_version kind delivery_base proposed_boundary boundaries process_records actual_evidence derived_from", "delivery")
    if (type(delivery["schema_version"]) is not int or delivery["schema_version"] != 3
            or delivery["kind"] != "review-feasibility-delivery" or delivery["delivery_base"] != base):
        raise ForecastError("delivery version, kind or base mismatch")
    count = checked.metrics["file_count"] - 1
    if count < 1:
        raise ForecastError("missing indexed tasks")
    paths = [relative, *(str(PurePosixPath(relative).with_suffix(".tasks") / f"task-{i}.md") for i in range(1, count + 1))]
    # NUL-terminated names are unquoted, so non-ASCII member paths compare as UTF-8.
    listed = _run_git(repo, "ls-tree", "-r", "-z", "--name-only", head, "--",
                      str(PurePosixPath(relative).with_suffix(".tasks")), binary=True)
    committed_members = [member.decode("utf-8") for member in listed.split(b"\0")[:-1]]
    if set(committed_members) != set(paths[1:]):
        raise ForecastError("committed member set differs from complete index")
    package = [{"path": relative, "raw_sha256": raw_digest(raw)}]
    tasks = []
    for number, member in enumerate(paths[1:], 1):
        content = committed_bytes(repo, head, member)
        package.append({"path": member, "raw_sha256": raw_digest(content)})
        block = _block(content, "## Review feasibility task")
        closed(block, "schema_version kind task", "task block")
        task = closed(block["task"], "id commit_subject_bytes actual_ranges records", "task")
        if (type(block["schema_version"]) is not int or block["schema_version"] != 3
                or block["kind"] != "review-feasibility-task"
                or type(task["id"]) is not int or task["id"] != number):
            raise ForecastError("task version, kind or ordinal mismatch")
        subjects(task["commit_subject_bytes"])
        tasks.append(task)
    boundaries = validate_boundaries(delivery["boundaries"], count, delivery["proposed_boundary"])
    proposed = next(b for b in boundaries if b["id"] == delivery["proposed_boundary"])
    if proposed["process_package"]["plan"] != relative or proposed["process_package"]["tasks"] != paths[1:]:
        raise ForecastError("root process package differs from committed plan")
    committed_bytes(repo, head, proposed["process_package"]["spec"])
    _derivation(repo, head, delivery["derived_from"])
    records = _records(delivery, tuple(tasks), boundaries)
    for boundary in boundaries:
        if not boundary["process_commit_subject_bytes"] and any(
                tree_entry(repo, head, path) is None
                for path in process_paths(boundary["process_package"])):
            raise ForecastError("future process package lacks a commit subject forecast")
    ownership = _ownership(repo, base, head, delivery, tuple(tasks), boundaries)
    tree = history_commit(repo, head).tree
    return ForecastPlan(repo, plan, base, head, tree, delivery, tuple(tasks), boundaries, records,
                        ownership, telemetry_digest(package), telemetry_digest({"delivery": delivery, "tasks": tasks}))
