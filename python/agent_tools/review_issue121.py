"""Issue-121 retained history: ownership, raw-parent edges, plan anchors and outcomes (issue 234 D2, D5, D17).

`plan_anchors`, `reconstruct_boundary`, `model_121` and `derive_121` each recompute
every edge through `contribution_edges`, whose commits
each have one raw parent, the preceding member. A virtualized history is therefore
`history_unauthenticated`, never an outcome; only CORE's `ReconstructionUnavailable`
is an unavailable route (S9). A measured outcome references its final records in
the model's `records` table (S16).

The model is SOURCE's object, `schema_version` 3: `model_121` reads it from Git and
it exists only in memory. The payload is the compact object, `schema_version` 4,
whose canonical bytes are the bundle file (issue 254). `compact_121` and `expand_121`
map each to the other, and they and `validate_121` are Git-free.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Mapping, Sequence

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import (PACKING_POLICY_SHA256, RECORD_POLICY, RECORD_POLICY_SHA256, FutureCommit,
                                       GenerationError, _split_diff, actual_inputs, actual_inputs_from_trees,
                                       git_diff, select_candidate)
from agent_tools.review_budget import BudgetAuthority
from agent_tools.review_forecast import ForecastError, canonical_bytes, edge_facts, raw_digest, tree_entry
from agent_tools.review_git import HistoryError, original_commit, original_commits, original_range
from agent_tools.review_pack import ReviewRecordSize
from agent_tools.review_projection import ReconstructionUnavailable, reconstruct_owned
from agent_tools.review_task7 import CODES as ESTIMATE_CODES
from agent_tools.review_task7 import TASK8_EFFECT, EstimateError, Task7Pins, compose, derive_task7

KIND = "issue-121-retained-history"
LABELS = ("aggregate.actual", "aggregate.projected", "tasks-1-3", "tasks-4-6", "tasks-7-8")
_TASKS = {"tasks-1-3": (1, 2, 3), "tasks-4-6": (4, 5, 6), "tasks-7-8": (7, 8)}
_ESTIMATED = ("aggregate.projected", "tasks-7-8")  # the outcomes that consume the Task-7 table
_ROUTES = {"aggregate.actual": (), "aggregate.projected": ("estimate",), "tasks-1-3": ("reconstruction",),
           "tasks-4-6": ("prerequisite", "reconstruction"), "tasks-7-8": ("estimate",)}
_STATES = {"measured": ("result_tree", "record_refs", "measurement"), "projection_unavailable": ("failure",)}
_VIOLATIONS = ("root_bytes", "member_bytes", "member_count", "aggregate_bytes")
_REPLAY_CODES = ("owned_root_unproved", "merge_effects_unproved", "whole_path_preimage_unproved",
                 "patch_application_unproved", "whole_path_postimage_unproved")
_POLICY = {"domain": RECORD_POLICY["kind"], "policy_sha256": RECORD_POLICY_SHA256}


class ContributionError(Exception):
    """Retained issue-121 evidence is invalid, not a valid unavailable outcome; `code` names why."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Issue121Pins:
    base: str
    head: str
    assignments: tuple[tuple[str, int, str | None], ...]  # (commit, owner, process reason); owner 0 is process
    plan_prefix: str
    plan_blobs: tuple[tuple[str, str], ...]  # (plan path, pinned blob)
    allowed_signer: bytes
    task_count: int


# Issue 226's twelve process pairs and the eighteen task 1-6 assignments, in raw range order;
# 8e6f0681 is the late Task-3 fix.
_ASSIGNMENTS = """
348ab54e7d997ee6aa18a7c3adba0c8e7be5aba4 0 initial_spec
1f22492b58adda9d46e5e03690a3233754472cfa 0 initial_plan
c5346dc746b13bb9c8aa40462a36e90df1dd1b49 0 standards_disposition
862547ddc35711be56cfa70799d88fcfc2cb4ba6 1
afa5ceba793d0f0db8e897553cb92fac9032ca1a 1
15a20e5347177bb96740bf4da45167452f481d18 1
363c2c7d1d508548cc9a66220ce1ef392c31b1a7 2
d87253f207b74b712569dbe0b4d399fa293be373 2
023278198b8de5ccfa9ffaac447fa68b45f9ee19 0 task2_contract_fix
17d75549e7ceaf5b4d23cbee5b7b6eb3ffdfbbb0 0 design_fix
b2202040bb0e16d1119f32097ec8a70bfbf0a15c 3
e4cd1d6c0701729532ccc954666016850d8ac20f 3
08c9caf0fa9c121dfda905a1c925231168c81381 4
72b47ae25d2c476222c1252859e01a395aef8eb7 4
c31d64e16490926767d355720d23deb3c66b1a08 4
191a2344578c7ca4d245dde4aa04ba058a85e76b 0 task4_contract_fix
4fdbb8c6adc31648ec557c9e0138b505cecf4dd9 5
5e505f5ab2dbc328b2c5a071d86620bbcf05d941 0 task5_plan_fix
36275eb69e8a9b70c307efd496952c9dbb114816 6
d70a08ef2b23a8de0b13a341bc1c94c4e6fe5e1e 6
03c08ffe25d9588c075d8e149d39b5643e8a64d3 6
44afaa06bf0904902ba396c4696a44b2a9a21336 6
a74c4d7a82bcb2f0e7e641d0d784347194d6c5ad 6
1a7560f9d3919cfe11c76b1b5105228220484abd 0 design_budget_fix
8e6f0681908cb1ba3d352be5d26540dab731ffeb 3
11b1e9bcdb310f46f4b400df919276f518214260 6
8a1fedd3dce3d441b7a55b5144a6be12696b55df 0 plan_head_sync
97d566aabdd5b87b6fc5d6949fcd05c23894d7ba 0 design_budget_fix
c150cfca5c591c3114cfbef5b1a15864acc7f39a 0 design_grounding_fix
fe85677c8bd26c808ac69c2ee21b17ff6e262923 0 task7_staging_fix
"""
_PREFIX = ".claude/plans/2026-09-03-issue-121-adoption-v1"
ISSUE_121_PINS = Issue121Pins(
    base="65748f480124515b9d0ee1467e958bbd9d54fc4a", head="fe85677c8bd26c808ac69c2ee21b17ff6e262923",
    assignments=tuple((row[0], int(row[1]), row[2] if len(row) == 3 else None)
                      for row in map(str.split, _ASSIGNMENTS.strip().splitlines())),
    plan_prefix=_PREFIX,
    plan_blobs=((_PREFIX + ".md", "8294252bb15684d9bf6054d7faf84ac98a376923"),
                (_PREFIX + ".tasks/task-7.md", "c8c622dd6389dc844a7fc638c305d2ab71223cb8")),
    allowed_signer=(b"anisanissakkaf@gmail.com ssh-ed25519 "
                    b"AAAAC3NzaC1lZDI1NTE5AAAAICvwSkG1C56YfXa6z8bnb0z9tkts56ZNmkVjibSsftvP\n"),
    task_count=8)


@contextmanager
def _authenticated():
    """S9: a history-authority failure is invalid evidence, never an outcome."""
    try:
        yield
    except (HistoryError, ForecastError) as exc:
        raise ContributionError("history_unauthenticated") from exc
    except GenerationError as exc:
        _estimate_code(exc)
        raise ContributionError("evidence_unavailable") from exc


def _estimate_code(exc: Exception) -> str:
    if isinstance(exc.__cause__, (HistoryError, ForecastError)):
        raise ContributionError("history_unauthenticated") from exc.__cause__
    return getattr(exc, "code", "")


def _require(condition) -> None:
    if not condition:
        raise ContributionError("invalid_payload")


def _closed(value, *keys) -> dict:
    _require(isinstance(value, dict) and set(value) == set(keys))
    return value


def _same(left, right) -> bool:
    """Canonical equality, so `True` never stands in for `1`."""
    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except (TypeError, ValueError):
        return False


def _hex(value) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{40}", value) is not None


def _digest(value) -> bool:
    return isinstance(value, str) and re.fullmatch("sha256:[0-9a-f]{64}", value) is not None


def _count(value) -> bool:
    return type(value) is int and value >= 0


def _entry(value, file: bool) -> bool:
    """A `tree_entry` fact: a file where the operation has one, else nothing or the directory at that path."""
    if value is None:
        return not file
    return (isinstance(value["mode"], str) and re.fullmatch("[0-7]{6}", value["mode"]) is not None
            and _hex(value["oid"]) and value["kind"] in (("blob", "commit") if file else ("tree",)))


def _identified(row: dict) -> dict:
    return {**row, "id": telemetry_digest(row)}


def _plan_paths(pins: Issue121Pins) -> list[str]:
    return [pins.plan_prefix + ".md", *(f"{pins.plan_prefix}.tasks/task-{n}.md" for n in range(1, pins.task_count + 1))]


def _assigned(pins: Issue121Pins) -> list[dict]:
    """The pins' assignment rows; an owner is 0 (process, with a reason) or a task 1-6, and the last
    row's commit is the pinned head."""
    if (not isinstance(pins, Issue121Pins) or not _hex(pins.base) or not _hex(pins.head)
            or not (isinstance(pins.plan_prefix, str) and pins.plan_prefix and isinstance(pins.allowed_signer, bytes)
                    and pins.allowed_signer and type(pins.task_count) is int and pins.task_count > 0)
            or not isinstance(pins.assignments, tuple) or not isinstance(pins.plan_blobs, tuple)
            or any(not isinstance(row, tuple) or len(row) != 2 or row[0] not in _plan_paths(pins)
                   or not _hex(row[1]) for row in pins.plan_blobs)):
        raise ContributionError("invalid_pins")
    rows = []
    for row in pins.assignments:
        if (not isinstance(row, tuple) or len(row) != 3 or type(row[1]) is not int or not 0 <= row[1] <= 6
                or (row[2] is None) == (row[1] == 0) or not (row[2] is None or isinstance(row[2], str) and row[2])):
            raise ContributionError("assignment_mismatch")
        rows.append({"commit": row[0], "owner": row[1], "reason": row[2]})
    if not rows or rows[-1]["commit"] != pins.head:
        raise ContributionError("assignment_mismatch")
    return rows


def classify(repo: Path, pins: Issue121Pins) -> tuple[dict, ...]:
    """`{commit, owner, reason}` for every commit of the exact raw range, once each, in its order."""
    rows = _assigned(pins)
    with _authenticated():
        commits = original_range(repo, pins.base, pins.head)
    if tuple(row["commit"] for row in rows) != commits:
        raise ContributionError("assignment_mismatch")
    return tuple(rows)


def contribution_edges(repo: Path, pins: Issue121Pins, classes: Sequence[dict]) -> tuple[dict, ...]:
    """One `edge_facts` row per commit from its one raw parent, with `owner`, `id` and, per record,
    `hunk_header_sha256` over the `@@` lines of the `--binary -U10` chunk that is `record_sha256`."""
    expected = classify(repo, pins)
    if not isinstance(classes, Sequence) or list(classes) != list(expected):
        raise ContributionError("class_table_mismatch")
    edges = []
    with _authenticated():
        parent, *chain = original_commits(repo, (pins.base, *(row["commit"] for row in expected)))
        for row, commit in zip(expected, chain):
            if commit.parents != (parent.oid,):
                raise ContributionError("history_nonlinear")
            edge = edge_facts(repo, parent.oid, commit.oid, 1)
            chunks = _split_diff(git_diff(repo, parent.tree, commit.tree, "--binary", "-U10"))
            if [raw_digest(chunk) for chunk in chunks] != [record["record_sha256"] for record in edge["records"]]:
                raise ContributionError("edge_record_mismatch")
            for record, chunk in zip(edge["records"], chunks):
                headers = [line for line in chunk.split(b"\n") if line.startswith(b"@@")]
                record["hunk_header_sha256"] = raw_digest(b"\n".join(headers))
            edges.append(_identified({**edge, "owner": row["owner"]}))
            parent = commit
    return tuple(edges)


def plan_anchors(repo: Path, pins: Issue121Pins) -> list[dict]:
    """Each plan path's latest raw writer, verified against the pinned signer alone."""
    return _anchors(repo, pins, contribution_edges(repo, pins, classify(repo, pins)))


def _written(edges: Sequence[dict], path: str) -> list[tuple]:
    """`(commit, resulting entry)` per edge record that writes `path`, in edge order."""
    return [(edge["commit"], r["after"]) for edge in edges for r in edge["records"] if r["path"] == path]


def _anchors(repo: Path, pins: Issue121Pins, edges: Sequence[dict]) -> list[dict]:
    pinned, signer, rows, verified = dict(pins.plan_blobs), raw_digest(pins.allowed_signer), [], set()
    with _authenticated(), tempfile.TemporaryDirectory(prefix="review-issue121-signers-") as scratch:
        trust, revoked = Path(scratch) / "allowed-signers", Path(scratch) / "revoked"
        trust.write_bytes(pins.allowed_signer)
        revoked.write_bytes(b"")
        head_tree = original_commit(repo, pins.head).tree
        for path in _plan_paths(pins):
            entry = tree_entry(repo, head_tree, path)
            if entry is None or entry["kind"] != "blob" or pinned.get(path, entry["oid"]) != entry["oid"]:
                raise ContributionError("anchor_blob_mismatch")
            written = _written(edges, path)
            writer, after = written[-1] if written else (_writer(repo, pins.base, path, entry), entry)
            if after != entry:
                raise ContributionError("anchor_blob_mismatch")
            if writer not in verified:
                _verify(repo, writer, trust, revoked)
                verified.add(writer)
            rows.append(_identified({"path": path, "commit": writer, "blob": entry["oid"], "signer_sha256": signer}))
    return rows


def _writer(repo: Path, oid: str, path: str, entry: dict) -> str:
    """The latest raw writer at or before `oid`, following a parent that holds the same entry."""
    while True:
        commit = original_commit(repo, oid)
        same = [c.oid for c in original_commits(repo, commit.parents) if tree_entry(repo, c.tree, path) == entry]
        if not same:
            return oid
        oid = same[0]


def _verify(repo: Path, commit: str, trust: Path, revoked: Path) -> None:
    checked = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), "-c", "gpg.format=ssh", "-c", "gpg.ssh.program=ssh-keygen",
         "-c", f"gpg.ssh.allowedSignersFile={trust}", "-c", f"gpg.ssh.revocationFile={revoked}",
         "verify-commit", commit], capture_output=True, env=dict(os.environ, GIT_NO_REPLACE_OBJECTS="1"))
    if checked.returncode:
        raise ContributionError("anchor_signature_invalid")


def _qualifying(classes: Sequence[dict], dependencies: Sequence[int], base: str) -> list[str]:
    """Prefix ends, the base first, whose product commits are exactly the dependencies' commits."""
    required = {row["commit"] for row in classes if row["owner"] in dependencies}
    seen, result = set(), [] if required else [base]
    for row in classes:
        seen |= {row["commit"]} if row["owner"] else set()
        if seen == required:
            result.append(row["commit"])
    return result


def _interleaved(classes: Sequence[dict], dependencies: Sequence[int]) -> set[str]:
    """Product commits of other tasks that precede the last dependency commit."""
    last = max(n for n, row in enumerate(classes) if row["owner"] in dependencies)
    return {row["commit"] for row in classes[:last] if row["owner"] and row["owner"] not in dependencies}


def _prerequisite(repo: Path, pins: Issue121Pins, classes, dependencies: list[int], value) -> str | None:
    """The authenticated prerequisite commit, or None when no prefix has the dependency closure."""
    if not dependencies and isinstance(value, Mapping) and dict(value) == {"kind": "delivery-base"}:
        return pins.base
    if (not dependencies or not isinstance(value, Mapping) or set(value) != {"kind", "tasks", "commit", "tree"}
            or value["kind"] != "completed-tasks" or not _same(value["tasks"], dependencies)):
        raise ContributionError("invalid_prerequisite")
    qualifying = _qualifying(classes, dependencies, pins.base)
    if value["commit"] is None and value["tree"] is None and not qualifying:
        return None
    if value["commit"] not in qualifying or value["tree"] != original_commit(repo, value["commit"]).tree:
        raise ContributionError("invalid_prerequisite")
    return value["commit"]


def _failed(row: dict, stage: str, code: str, refs: list[str]) -> tuple[dict, list]:
    return {**row, "state": "projection_unavailable", "failure": {"stage": stage, "code": code,
                                                                  "evidence_refs": refs}}, []


def _package(base: str, head: str) -> str:
    return f"review-{base[:7]}..{head[:7]}.json"


def _measured(row: dict, tree: str, inputs: list, authority: BudgetAuthority, records: list[dict],
              transform=None) -> tuple[dict, list]:
    candidate = select_candidate(inputs, authority.limits, transform=transform, measurement_only=True)
    measurement = {"package_name": inputs[0].package_name, "packing_policy_sha256": PACKING_POLICY_SHA256,
                   "artifact_policy_sha256": authority.policy_sha256, "metrics": dict(candidate.metrics),
                   "budget_status": candidate.status, "violations": list(candidate.violations)}
    return {**row, "state": "measured", "result_tree": tree, "record_refs": [r["id"] for r in records],
            "measurement": measurement}, records


def _lineage(edges: Sequence[dict]) -> dict[str, list[str]]:
    """Each path's edge ids in edge order: the edges that record it or a path it was renamed from."""
    lineage: dict[str, set] = {}
    for edge in edges:
        for record in edge["records"]:
            old, new = record["old_path"], record["path"]
            lineage[new] = lineage.get(old, set()) | lineage.get(new, set()) | {edge["id"]}
            if old != new:  # the rename also ends the old path's record
                lineage[old] = lineage.get(old, set()) | {edge["id"]}
    return {path: [edge["id"] for edge in edges if edge["id"] in ids] for path, ids in lineage.items()}


def _actual(label: str, item, edges: Sequence[dict]) -> list[dict]:
    """Whole initial-context final records, each with its ordered, non-empty edge lineage."""
    lineage, rows = _lineage(edges), []
    for record in sorted(item.records, key=lambda r: r.path):
        refs = lineage.get(record.path)
        if not refs:
            raise ContributionError("record_lineage_missing")
        if record.generated_evidence is not None:  # a compact summary is not the whole record
            raise ContributionError("record_evidence_incomplete")
        rows.append(_identified({"kind": "actual", "scope": label, "path": record.path,
                                 "record_bytes": len(record.payload), "record_sha256": raw_digest(record.payload),
                                 "edge_ids": refs}))
    return rows


def _bounds(table: dict) -> list[dict]:
    """Each Task-7 table row's record and line bound (a move adds and deletes no line)."""
    return [{"path": row["new_path"], "record_bytes": row["record_bytes"],
             "added_lines": row["output"]["lines"] if row["operation"] != "move" else 0,
             "deleted_lines": row["input"]["lines"] if row["operation"] == "write" else 0} for row in table["rows"]]


def _estimated(label: str, rows: list[dict], subjects: list[int]):
    """Estimate records and the transform that measures them in place of a candidate's records."""
    future = tuple(FutureCommit(telemetry_digest({"boundary": label, "subject": n})[7:47], size)
                   for n, size in enumerate(subjects))

    def transform(item):
        return replace(item, records=tuple(ReviewRecordSize(r["path"], r["record_bytes"]) for r in rows),
                       future_commits=future, source_diff_bytes=sum(r["record_bytes"] for r in rows),
                       stat={"files_changed": len(rows), "insertions": sum(r["added_lines"] for r in rows),
                             "deletions": sum(r["deleted_lines"] for r in rows)})
    return [_identified({"kind": "estimate", "scope": label, **row}) for row in rows], transform


def _boundary(repo: Path, pins: Issue121Pins, classes, edges, label: str, tasks: list[int], prerequisite,
              authority: BudgetAuthority) -> tuple[dict, list]:
    dependencies = list(range(1, tasks[0]))
    selected = [edge for edge in edges if edge["owner"] in tasks]
    commit = _prerequisite(repo, pins, classes, dependencies, prerequisite)
    row = {"boundary": label, "prerequisite": dict(prerequisite), "edge_ids": [e["id"] for e in selected],
           "estimate_refs": []}
    if commit is None:
        dependency = [edge for edge in edges if edge["owner"] in dependencies]
        try:
            reconstruct_owned(repo, pins.base, [edge["commit"] for edge in dependency]).close()
        except ReconstructionUnavailable as exc:
            return _failed(row, "prerequisite", "dependency_unavailable",
                           [edge["id"] for edge in dependency if edge["commit"] == exc.commit])
        late = _interleaved(classes, dependencies)
        return _failed(row, "prerequisite", "prerequisite_composition_unsupported",
                       [edge["id"] for edge in edges if edge["commit"] in late])
    try:
        rebuilt = reconstruct_owned(repo, commit, [edge["commit"] for edge in selected])
    except ReconstructionUnavailable as exc:
        return _failed(row, "reconstruction", exc.code,
                       [edge["id"] for edge in selected if edge["commit"] == exc.commit])
    with rebuilt:
        head = selected[-1]["commit"] if selected else commit
        inputs = list(actual_inputs_from_trees(
            rebuilt.repo, rebuilt.prerequisite_tree, rebuilt.result_tree, base=commit, head=head,
            commits=rebuilt.commits, package_name=_package(commit, head), limits=authority.limits))
        return _measured(row, rebuilt.result_tree, inputs, authority, _actual(label, inputs[0], selected))


def _context(pins: Issue121Pins, task7_pins: Task7Pins, authority: BudgetAuthority) -> None:
    """The Task-7 prerequisite is this range's head, and limits come from a budget description."""
    if (not isinstance(task7_pins, Task7Pins) or task7_pins.prerequisite_commit != pins.head
            or not isinstance(authority, BudgetAuthority)):
        raise ContributionError("invalid_pins")


def reconstruct_boundary(repo: Path, pins: Issue121Pins, *, boundary: str, prerequisite: Mapping,
                         edges: Sequence[dict], table: dict, task7_pins: Task7Pins,
                         authority: BudgetAuthority) -> dict:
    """One closed outcome row for a `tasks-N`/`tasks-N-M` selector over owners 1-6, after the caller's
    complete edge table equals a fresh recomputation. The prerequisite is the delivery base from task 1,
    else a commit/tree whose product closure is exactly the earlier tasks, or null/null when none exists.
    `table` and `task7_pins` are `derive_121`'s estimate context; no selector reads the table."""
    match = re.fullmatch(r"tasks-([1-6])(?:-([1-6]))?", boundary) if isinstance(boundary, str) else None
    if match is None or (match[2] and int(match[2]) <= int(match[1])):
        raise ContributionError("invalid_selector")
    classes = classify(repo, pins)
    fresh = contribution_edges(repo, pins, classes)
    if not isinstance(edges, Sequence) or not _same(list(edges), list(fresh)):
        raise ContributionError("edge_table_mismatch")
    _anchors(repo, pins, fresh)
    _context(pins, task7_pins, authority)
    tasks = list(range(int(match[1]), int(match[2] or match[1]) + 1))
    with _authenticated():
        return _boundary(repo, pins, classes, fresh, boundary, tasks, prerequisite, authority)[0]


def _model(repo: Path, pins: Issue121Pins, task7_pins: Task7Pins, authority: BudgetAuthority) -> tuple:
    """`(model, Task-7 table or None)`. Without a derivable Task-7 table both table outcomes are
    unavailable at stage `estimate`, with no estimate ref."""
    classes = classify(repo, pins)
    edges = contribution_edges(repo, pins, classes)
    anchors = _anchors(repo, pins, edges)
    _context(pins, task7_pins, authority)
    limits = authority.limits
    with _authenticated():
        base_tree, head_tree = (c.tree for c in original_commits(repo, (pins.base, pins.head)))
        try:
            table, unestimated = derive_task7(repo, task7_pins), None
        except EstimateError as exc:
            table, unestimated = None, _estimate_code(exc)
        refs, estimate = ([] if table is None else [telemetry_digest(table)]), unestimated
        base_row = {"prerequisite": {"kind": "delivery-base"}, "edge_ids": [e["id"] for e in edges]}
        inputs = list(actual_inputs(repo, pins.base, pins.head, _package(pins.base, pins.head), limits))
        actual = _measured({"boundary": LABELS[0], **base_row, "estimate_refs": []}, head_tree, inputs,
                           authority, _actual(LABELS[0], inputs[0], edges))
        row = {"boundary": LABELS[1], **base_row, "estimate_refs": refs}
        if table is not None:
            try:
                composed = compose(repo, table, task7_pins, base_tree=base_tree, final_tree=head_tree, limits=limits)
            except EstimateError as exc:
                estimate = _estimate_code(exc)
        subjects = None if table is None else table["projection_estimate"]["commit_subject_bytes"]
        projected = (_failed(row, "estimate", estimate, []) if estimate else
                     _measured(row, head_tree, inputs, authority, *_estimated(LABELS[1], list(composed), subjects)))
        qualifying = _qualifying(classes, [1, 2, 3], pins.base)
        middle = qualifying[-1] if qualifying else None
        boundaries = [
            _boundary(repo, pins, classes, edges, "tasks-1-3", [1, 2, 3], {"kind": "delivery-base"}, authority),
            _boundary(repo, pins, classes, edges, "tasks-4-6", [4, 5, 6],
                      {"kind": "completed-tasks", "tasks": [1, 2, 3], "commit": middle,
                       "tree": middle and original_commit(repo, middle).tree}, authority)]
        row = {"boundary": LABELS[4], "prerequisite": {"kind": "completed-tasks", "tasks": [1, 2, 3, 4, 5, 6],
                                                     "commit": pins.head, "tree": head_tree},
               "edge_ids": [], "estimate_refs": refs}
        if table is None:
            boundaries.append(_failed(row, "estimate", unestimated, []))
        else:  # future-only: no owned commit, so the prerequisite tree is the result (D5)
            empty = list(actual_inputs_from_trees(repo, head_tree, head_tree, base=pins.head, head=pins.head,
                                                  commits=(), package_name=_package(pins.head, pins.head),
                                                  limits=limits))
            boundaries.append(_measured(row, head_tree, empty, authority,
                                        *_estimated(LABELS[4], _bounds(table), subjects)))
    outcomes = [actual, projected, *boundaries]
    derived = {"schema_version": 3, "kind": KIND, "range": {"base": pins.base, "head": pins.head},
               "classes": list(classes), "edges": list(edges), "anchors": anchors,
               "records": [record for _, records in outcomes for record in records],
               "aggregate": {"actual": actual[0], "projected": projected[0]},
               "boundaries": [row for row, _ in boundaries], "operational_effects": [dict(TASK8_EFFECT)],
               "record_table_policy": dict(_POLICY)}
    return derived, table


def model_121(repo: Path, pins: Issue121Pins, task7_pins: Task7Pins, authority: BudgetAuthority) -> dict:
    """The schema-3 model, read from Git as SOURCE's derivation reads it."""
    return _model(repo, pins, task7_pins, authority)[0]


def derive_121(repo: Path, pins: Issue121Pins, task7_pins: Task7Pins, authority: BudgetAuthority) -> dict:
    """The validated schema-4 payload of the model `model_121` returns."""
    model, table = _model(repo, pins, task7_pins, authority)
    payload = compact_121(model)
    validate_121(payload, pins, table)
    return payload


def _pack(m: dict) -> dict:
    """The schema-4 members of model `m`: paths and tree entries interned in sorted tables, rows as lists,
    and none of the members `expand_121` recomputes."""
    edges = m["edges"]
    position = {edge["id"]: n for n, edge in enumerate(edges)}
    facts = [r for edge in edges for r in edge["records"]]
    paths = sorted({p for r in facts for p in (r["path"], r["old_path"])} | {r["path"] for r in m["records"]}
                   | {a["path"] for a in m["anchors"]})
    at, groups = {p: i for i, p in enumerate(paths)}, {}
    for r in facts:
        for e in (r["before"], r["after"]):
            if e is not None:
                groups.setdefault((e["mode"], e["kind"]), set()).add(e["oid"])
    entries, index = [], {}
    for key in sorted(groups):
        for oid in sorted(groups[key]):
            index[(*key, oid)] = len(index)
        entries.append([*key, sorted(groups[key])])

    def ref(e):
        return None if e is None else index[(e["mode"], e["kind"], e["oid"])]

    def fact(r):
        return [r["operation"], at[r["path"]], ref(r["before"]), ref(r["after"]), r["record_bytes"], r["record_sha256"],
                r["hunk_header_sha256"], *([at[r["old_path"]]] if r["old_path"] != r["path"] else [])]
    records = {}
    for r in m["records"]:
        slot = records.setdefault(r["scope"], {"kind": r["kind"], "rows": []})
        slot["rows"].append([at[r["path"]], r["record_bytes"], *(
            (r["record_sha256"],) if r["kind"] == "actual" else (r["added_lines"], r["deleted_lines"]))])

    def outcome(row):
        out = {k: v for k, v in row.items() if k not in ("boundary", "edge_ids", "record_refs")}
        if "failure" in out:
            out["failure"] = {**out["failure"], "evidence_refs": [position[i] for i in out["failure"]["evidence_refs"]]}
        return out
    (signer,) = {a["signer_sha256"] for a in m["anchors"]}
    classes = [[c["commit"], c["owner"], *([] if c["reason"] is None else [c["reason"]])] for c in m["classes"]]
    return {"schema_version": 4, "kind": m["kind"], "range": m["range"], "classes": classes,
            "paths": paths, "entries": entries, "edges": [[fact(r) for r in edge["records"]] for edge in edges],
            "signer_sha256": signer, "anchors": [[at[a["path"]], a["commit"], a["blob"]] for a in m["anchors"]],
            "records": records,
            "outcomes": [outcome(r) for r in (m["aggregate"]["actual"], m["aggregate"]["projected"], *m["boundaries"])],
            "operational_effects": m["operational_effects"], "record_table_policy": m["record_table_policy"]}


def compact_121(model: dict) -> dict:
    """The schema-4 payload of `model`. Pure. A model that `expand_121` of its payload does not equal
    canonically, a malformed model included, is `invalid_payload`."""
    try:
        payload = _pack(model)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ContributionError("invalid_payload") from exc
    _require(_same(expand_121(payload), model))
    return payload


def _rows(value, *sizes: int) -> list:
    """`value`, a list of lists whose lengths are among `sizes`."""
    _require(isinstance(value, list) and all(isinstance(row, list) and len(row) in sizes for row in value))
    return value


def _at(rows: list, index):
    """`rows[index]`, for an in-range `int` that is not a `bool`."""
    _require(type(index) is int and 0 <= index < len(rows))
    return rows[index]


def expand_121(payload: dict) -> dict:
    """The schema-3 model that the schema-4 `payload` encodes. Pure: it reads the payload alone and leaves
    it unchanged. Anything but the closed version-4 object of this kind is `invalid_payload`, and so are
    a value of the wrong type where one is read, a row of the wrong length and an index that is not an
    in-range `int`. Ids, edge identity, lineage and outcome references are recomputed, never read."""
    c = _closed(payload, "schema_version", "kind", "range", "classes", "paths", "entries", "edges", "signer_sha256",
                "anchors", "records", "outcomes", "operational_effects", "record_table_policy")
    paths, slots, stored = c["paths"], c["records"], c["outcomes"]
    _require(type(c["schema_version"]) is int and c["schema_version"] == 4 and c["kind"] == KIND
             and isinstance(paths, list) and all(isinstance(path, str) for path in paths)
             and isinstance(c["edges"], list) and isinstance(slots, dict)
             and isinstance(stored, list) and len(stored) == len(LABELS))
    entries = []
    for mode, kind, oids in _rows(c["entries"], 3):
        _require(isinstance(oids, list))
        entries.extend({"mode": mode, "kind": kind, "oid": oid} for oid in oids)

    def entry(index):
        return None if index is None else dict(_at(entries, index))
    classes = [{"commit": r[0], "owner": r[1], "reason": r[2] if len(r) > 2 else None}
               for r in _rows(c["classes"], 2, 3)]
    edges, parent = [], _closed(c["range"], "base", "head")["base"]
    for row, facts in zip(classes, c["edges"]):
        records = [{"operation": r[0], "path": _at(paths, r[1]), "old_path": _at(paths, r[7] if len(r) > 7 else r[1]),
                    "before": entry(r[2]), "after": entry(r[3]), "record_bytes": r[4], "record_sha256": r[5],
                    "hunk_header_sha256": r[6]} for r in _rows(facts, 7, 8)]
        edges.append(_identified({"parent": parent, "commit": row["commit"], "parent_ordinal": 1, "records": records,
                                  "owner": row["owner"]}))
        parent = row["commit"]
    anchors = [_identified({"path": _at(paths, path), "commit": commit, "blob": blob,
                            "signer_sha256": c["signer_sha256"]}) for path, commit, blob in _rows(c["anchors"], 3)]
    selected = {label: [e for e in edges if label.startswith("aggregate.") or e["owner"] in _TASKS[label]]
                for label in LABELS}
    records, refs = [], {label: [] for label in LABELS}
    for label in LABELS:
        if label not in slots:
            continue
        slot = _closed(slots[label], "kind", "rows")
        _require(slot["kind"] in ("actual", "estimate"))
        actual, lineage = slot["kind"] == "actual", _lineage(selected[label])
        for r in _rows(slot["rows"], 3 if actual else 4):
            row = {"kind": slot["kind"], "scope": label, "path": _at(paths, r[0]), "record_bytes": r[1]}
            row.update({"record_sha256": r[2], "edge_ids": lineage.get(row["path"])} if actual
                       else {"added_lines": r[2], "deleted_lines": r[3]})
            records.append(_identified(row))
            refs[label].append(records[-1]["id"])
    outcomes = []
    for label, row in zip(LABELS, stored):
        _require(isinstance(row, dict))
        row = {**row, "boundary": label, "edge_ids": [e["id"] for e in selected[label]]}
        if row.get("state") == "measured":
            row["record_refs"] = refs[label]
        else:
            failure = row.get("failure")
            _require(isinstance(failure, dict) and isinstance(failure.get("evidence_refs"), list))
            row["failure"] = {**failure, "evidence_refs": [_at(edges, n)["id"] for n in failure["evidence_refs"]]}
        outcomes.append(row)
    return {"schema_version": 3, "kind": KIND, "range": c["range"], "classes": classes, "edges": edges,
            "anchors": anchors, "records": records, "aggregate": {"actual": outcomes[0], "projected": outcomes[1]},
            "boundaries": outcomes[2:], "operational_effects": c["operational_effects"],
            "record_table_policy": c["record_table_policy"]}


def _validate_tables(model: dict, pins: Issue121Pins, classes: list[dict]) -> None:
    """One edge per class, anchors on the plan paths, records unique by scope and path."""
    edges, anchors, records = model["edges"], model["anchors"], model["records"]
    _require(len(edges) == len(classes))
    for edge in edges:
        for record in edge["records"]:
            _require(_count(record["record_bytes"]) and _digest(record["record_sha256"])
                     and _digest(record["hunk_header_sha256"]))
            operation, path, old = record["operation"], record["path"], record["old_path"]
            _require(operation in ("A", "M", "D", "T", "R100") and path and old
                     and (operation == "R100") == (path != old) and _entry(record["before"], operation != "A")
                     and _entry(record["after"], operation != "D"))
    paths, pinned = _plan_paths(pins), dict(pins.plan_blobs)
    _require(len(anchors) == len(paths))
    for anchor, path in zip(anchors, paths):
        _require(anchor["path"] == path and _hex(anchor["commit"]) and _hex(anchor["blob"])
                 and pinned.get(path, anchor["blob"]) == anchor["blob"]
                 and anchor["signer_sha256"] == raw_digest(pins.allowed_signer))
        # As `_anchors` derives it: the latest edge that writes the path is its writer and leaves its blob.
        # A path the range never writes was last written at or before the base, which no edge here names.
        for commit, after in _written(edges, path)[-1:]:
            _require(anchor["commit"] == commit and after is not None
                     and _same([after["kind"], after["oid"]], ["blob", anchor["blob"]]))
    keys = []
    for record in records:
        _require(record["path"] and _count(record["record_bytes"]))
        if record["kind"] == "actual":
            _require(_digest(record["record_sha256"]) and record["edge_ids"])
        else:
            _require(_count(record["added_lines"]) and _count(record["deleted_lines"]))
        keys.append((LABELS.index(record["scope"]), record["path"]))
    _require(keys == sorted(set(keys)))


def _expected_prerequisite(label: str, pins: Issue121Pins, classes: list[dict], given) -> dict:
    if label not in ("tasks-4-6", "tasks-7-8"):
        return {"kind": "delivery-base"}
    dependencies = list(range(1, _TASKS[label][0]))
    qualifying = _qualifying(classes, dependencies, pins.base)
    commit = qualifying[-1] if qualifying else None
    tree = given.get("tree") if commit and isinstance(given, dict) and _hex(given.get("tree")) else None
    _require(commit is None or tree is not None)
    return {"kind": "completed-tasks", "tasks": dependencies, "commit": commit, "tree": tree}


def _validate_failure(label: str, failure, selection: list[str], edges: list[dict], classes: list[dict],
                      null: bool) -> None:
    stage, code, refs = (_closed(failure, "stage", "code", "evidence_refs")[k]
                         for k in ("stage", "code", "evidence_refs"))
    _require(isinstance(stage, str) and stage in _ROUTES[label] and isinstance(code, str)
             and (stage == "prerequisite") == null)
    if stage == "estimate":
        _require(code in ESTIMATE_CODES and refs == [])
    elif stage == "reconstruction":
        _require(code in _REPLAY_CODES and len(refs) == 1 and refs[0] in selection)
    elif code == "dependency_unavailable":
        _require(len(refs) == 1 and refs[0] in [edge["id"] for edge in edges if edge["owner"] in (1, 2, 3)])
    else:
        late = _interleaved(classes, [1, 2, 3])
        _require(code == "prerequisite_composition_unsupported"
                 and refs == [edge["id"] for edge in edges if edge["commit"] in late])


def _validate_measurement(value, name: str) -> None:
    measurement = _closed(value, "package_name", "packing_policy_sha256", "artifact_policy_sha256", "metrics",
                          "budget_status", "violations")
    metrics = _closed(measurement["metrics"], "root_bytes", "total_bytes", "file_count", "largest_member_bytes")
    violations = measurement["violations"]
    _require(measurement["package_name"] == name and measurement["packing_policy_sha256"] == PACKING_POLICY_SHA256
             and _digest(measurement["artifact_policy_sha256"]) and all(map(_count, metrics.values()))
             and isinstance(violations, list) and violations == [v for v in _VIOLATIONS if v in violations]
             and measurement["budget_status"] == ("over_budget" if violations else "within_budget"))


def validate_121(payload: dict, pins: Issue121Pins, table: dict | None) -> dict:
    """Git-free: the model of a schema-4 `payload`. In order, the pins are checked, the payload is expanded,
    an expansion whose shape or references the pins and `table` (`derive_121`'s Task-7 table, or None when
    it derived none) do not determine is refused, and so is a payload that is not `compact_121` of it."""
    classes = _assigned(pins)
    model = expand_121(payload)
    _require(_same([model[k] for k in ("range", "classes", "operational_effects", "record_table_policy")],
                   [{"base": pins.base, "head": pins.head}, classes, [TASK8_EFFECT], _POLICY]))
    _validate_tables(model, pins, classes)
    edges, records, aggregate = model["edges"], model["records"], model["aggregate"]
    try:
        bounds = None if table is None else [{"kind": "estimate", "scope": "tasks-7-8", **r} for r in _bounds(table)]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ContributionError("invalid_payload") from exc
    for label, row in zip(LABELS, [aggregate["actual"], aggregate["projected"], *model["boundaries"]]):
        _require(isinstance(row.get("state"), str) and row["state"] in _STATES)
        _closed(row, "boundary", "state", "prerequisite", "edge_ids", "estimate_refs", *_STATES[row["state"]])
        whole = label.startswith("aggregate.")
        prerequisite = _expected_prerequisite(label, pins, classes, row["prerequisite"])
        estimated = label in _ESTIMATED
        _require(_same(row["prerequisite"], prerequisite)
                 and _same(row["estimate_refs"], [telemetry_digest(table)] if estimated and table is not None else []))
        scoped = [record for record in records if record["scope"] == label]
        null = label == "tasks-4-6" and prerequisite["commit"] is None
        if row["state"] == "projection_unavailable":
            _require(not scoped)
            _validate_failure(label, row["failure"], row["edge_ids"], edges, classes, null)
            # A table fully determines tasks-7-8; only an underived one fails it, as it fails the projection.
            _require(label != "tasks-7-8"
                     or table is None and _same(row["failure"], aggregate["projected"].get("failure")))
            continue
        _require(not null and not (estimated and table is None) and _hex(row["result_tree"]))
        start = prerequisite.get("commit") or pins.base
        owned = [c["commit"] for c in classes if c["owner"] in _TASKS.get(label, ())]
        _validate_measurement(row["measurement"], _package(start, pins.head if whole else (owned or [start])[-1]))
        for record in scoped:
            _require(record["kind"] == ("estimate" if estimated else "actual"))
        if label == "tasks-7-8":
            _require(row["result_tree"] == prerequisite["tree"]
                     and _same([{k: v for k, v in r.items() if k != "id"} for r in scoped], bounds))
    _require(_same(compact_121(model), payload))
    return model


def unavailable_ids(model: dict) -> tuple[str, ...]:
    """The labels of a validated model's unavailable outcomes, in outcome order."""
    rows = [model["aggregate"]["actual"], model["aggregate"]["projected"], *model["boundaries"]]
    return tuple(row["boundary"] for row in rows if row["state"] == "projection_unavailable")
