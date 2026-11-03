"""Write the canonical review-feasibility forecast blocks from a planner's estimate (issue 559)."""
from __future__ import annotations

import math
import os
from pathlib import Path, PurePosixPath
import tempfile

from agent_tools.review_actual import _run_git
from agent_tools.review_budget import BudgetAuthority
from agent_tools.review_forecast import (ForecastError, _block, _records, canonical_bytes, full_commit,
                                         history_commit, path_name, read_regular, strict_json,
                                         tree_entry, validate_boundaries)
from agent_tools.review_record import DELIVERY_HEADING, TASK_HEADING

RECORD_BASE_BYTES = 2560
LINE_BYTES = 128
REVISION_BYTES = 4096
RECORDING_BYTES_PER_TASK = 256
ALLOWANCE_LINE_BYTES = 64
SUBJECT_BYTES = 64
TASK_SUBJECTS = 3
PROCESS_SUBJECTS_BEYOND_TASKS = 4
BOUNDARY = "all"
ACCEPTANCE = "Every task of the plan is complete and the declared verification passes"
SETTLE_RENDERS = 8

_KEYS = {"add": ("path", "change", "added_lines"),
         "modify": ("path", "change", "added_lines", "deleted_lines"),
         "delete": ("path", "change")}

HELP = f"""Write the root's "{DELIVERY_HEADING}" block and each task member's
"{TASK_HEADING}" block from an estimate, then print {{"written":[...]}}:
the repository-relative paths whose bytes changed, the root first. Nothing is
committed. Rerun it after any edit that changes a task's files.

The estimate (--input FILE, or - for stdin) is one JSON object with one tasks
entry per task member, in task order:

  {{"tasks":[{{"files":[{{"path":"src/a.py","change":"add","added_lines":120}},{{"path":"src/b.py","change":"modify","added_lines":30,"deleted_lines":10}},{{"path":"old.py","change":"delete"}}]}}]}}

An add has path, change and added_lines, a modify adds deleted_lines, and a
delete has path and change only. Line counts are integers >= 0. A path appears
once per task, is never the spec, the root or a member, and its change must fit
the path's state walked task by task from the base tree.

Sizing: a task record's record_bytes is {RECORD_BASE_BYTES} plus {LINE_BYTES} per added or deleted
line, cumulative per path, and a delete of a base file is charged that file's
bytes and lines once. A process record (the spec, the root, each member) is
{RECORD_BASE_BYTES} + its bytes + its lines + {REVISION_BYTES} + {RECORDING_BYTES_PER_TASK} per task, and its added_lines add
({REVISION_BYTES} + {RECORDING_BYTES_PER_TASK} per task) / {ALLOWANCE_LINE_BYTES}, rounded up. Each task is budgeted {TASK_SUBJECTS} commit subjects
of {SUBJECT_BYTES} bytes, and the process the task count + {PROCESS_SUBJECTS_BEYOND_TASKS}.
"""


def _lines(raw: bytes) -> int:
    return raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)


def _repo_path(repo: Path, target: Path, what: str) -> str:
    try:
        relative = Path(os.path.realpath(target)).relative_to(os.path.realpath(repo)).as_posix()
    except ValueError as exc:
        raise ForecastError(f"{what} is outside the repository") from exc
    return path_name(relative)


class _Estimate:
    """Validate an estimate against the base tree, walking each path's state task by task."""

    def __init__(self, repo: Path, base: str, reserved: set[str]) -> None:
        self.repo, self.base, self.reserved = repo, base, reserved
        self.entries: dict[str, dict | None] = {}
        self.present: dict[str, bool] = {}

    def base_entry(self, path: str) -> dict | None:
        if path not in self.entries:
            self.entries[path] = tree_entry(self.repo, self.base, path)
        return self.entries[path]

    def parse(self, raw: bytes, count: int) -> list[list[dict]]:
        try:
            value = strict_json(raw)
        except ForecastError as exc:
            raise ForecastError(f"estimate: {exc}") from exc
        if not isinstance(value, dict) or set(value) != {"tasks"}:
            raise ForecastError("estimate must be a JSON object with exactly the key tasks")
        tasks = value["tasks"]
        if not isinstance(tasks, list) or len(tasks) != count:
            raise ForecastError(f"tasks must be a list with one entry per task member ({count})")
        for i, task in enumerate(tasks):
            if not isinstance(task, dict) or set(task) != {"files"}:
                raise ForecastError(f"tasks[{i}] must be a JSON object with exactly the key files")
            if not isinstance(task["files"], list):
                raise ForecastError(f"tasks[{i}].files must be a list")
        return [self._task(i, task["files"]) for i, task in enumerate(tasks)]

    def _task(self, i: int, files: list) -> list[dict]:
        seen: set[str] = set()
        for j, entry in enumerate(files):
            self._entry(f"tasks[{i}].files[{j}]", entry, seen)
        return files

    def _entry(self, label: str, entry: object, seen: set[str]) -> None:
        if not isinstance(entry, dict):
            raise ForecastError(f"{label} must be a JSON object")
        change = entry.get("change")
        if change not in _KEYS:
            raise ForecastError(f"{label}.change must be add, modify or delete")
        keys = _KEYS[change]
        if set(entry) != set(keys):
            raise ForecastError(f"{label} must have exactly the keys {', '.join(keys)}")
        try:
            path = path_name(entry["path"])
        except ForecastError as exc:
            raise ForecastError(f"{label}.path: {exc}") from exc
        if path in self.reserved:
            raise ForecastError(f"{label}.path names the spec, the plan root or a task member")
        if path in seen:
            raise ForecastError(f"{label}.path repeats a path of {label.split('.files')[0]}")
        seen.add(path)
        for key in keys[2:]:
            if type(entry[key]) is not int or entry[key] < 0:
                raise ForecastError(f"{label}.{key} must be an integer >= 0")
        found = self.base_entry(path)
        if found is not None and found["kind"] != "blob":
            raise ForecastError(f"{label}.path is not a blob at the base")
        present = self.present.setdefault(path, found is not None)
        if change == "add" and present:
            raise ForecastError(f"{label}.change add needs an absent path, "
                                "but the path exists after the base and earlier tasks")
        if change != "add" and not present:
            raise ForecastError(f"{label}.change {change} needs a present path, "
                                "but the path is absent after the base and earlier tasks")
        self.present[path] = change != "delete"


def _task_blocks(repo: Path, tasks: list[list[dict]], estimate: _Estimate) -> list[dict]:
    last = {entry["path"]: number for number, entries in enumerate(tasks, 1) for entry in entries}
    totals: dict[str, dict] = {}
    deleted_base: set[str] = set()
    blocks = []
    for number, entries in enumerate(tasks, 1):
        records = []
        for position, entry in enumerate(entries, 1):
            path, change = entry["path"], entry["change"]
            total = totals.setdefault(path, {"added": 0, "deleted": 0, "charge": 0, "ids": []})
            if change == "delete":
                found = estimate.base_entry(path)
                if found is not None and path not in deleted_base:
                    deleted_base.add(path)
                    blob = _run_git(repo, "cat-file", "blob", found["oid"], binary=True)
                    total["charge"] += len(blob) + _lines(blob)
                    total["deleted"] += _lines(blob)
            else:
                added, deleted = entry["added_lines"], entry.get("deleted_lines", 0)
                total["added"] += added
                total["deleted"] += deleted
                total["charge"] += LINE_BYTES * (added + deleted)
            record_id = f"r{number}-{position}"
            total["ids"].append(record_id)
            records.append({"id": record_id, "owner": number, "path": path, "change": change,
                            "last_task": last[path], "bounds": [_bound(
                                total["added"], total["deleted"], RECORD_BASE_BYTES + total["charge"],
                                total["ids"])]})
        blocks.append({"schema_version": 3, "kind": "review-feasibility-task",
                       "task": {"id": number, "commit_subject_bytes": [SUBJECT_BYTES] * TASK_SUBJECTS,
                                "actual_ranges": [], "records": records}})
    return blocks


def _bound(added: int, deleted: int, size: int, covers: list[str]) -> dict:
    return {"boundary": BOUNDARY, "added_lines": added, "deleted_lines": deleted, "record_bytes": size,
            "support": {"kind": "authored-cumulative/v1", "covers": list(covers)}}


def _replaced(text: str, heading: str, block: dict) -> str:
    section = f"{heading}\n\n```json\n{canonical_bytes(block).decode('ascii')}```\n"
    lines, bare = text.splitlines(keepends=True), text.splitlines()
    if heading not in bare:
        if not text:
            return section
        return text + ("" if text.endswith("\n") else "\n") + "\n" + section
    start = bare.index(heading)
    end = next((i for i in range(start + 1, len(bare)) if bare[i].startswith("## ")), len(lines))
    return "".join(lines[:start]) + section + ("\n" if end < len(lines) else "") + "".join(lines[end:])


def _read_text(repo: Path, path: str, heading: str) -> str:
    try:
        text = read_regular(repo, path).decode("utf-8")
    except UnicodeError as exc:
        raise ForecastError(f"{path} is not UTF-8") from exc
    if text.splitlines().count(heading) > 1:
        raise ForecastError(f'{path}: "{heading}" appears more than once')
    if heading in text.splitlines():
        try:
            block = _block(text.encode("utf-8"), heading)
        except ForecastError:
            return text  # a block that does not parse is simply replaced
        recorded = (block.get("actual_evidence", {}).get("process_ranges")
                    if heading == DELIVERY_HEADING and isinstance(block.get("actual_evidence"), dict)
                    else block.get("task", {}).get("actual_ranges")
                    if heading == TASK_HEADING and isinstance(block.get("task"), dict) else None)
        if recorded not in (None, []):
            raise ForecastError(f"{path}: its forecast block carries recorded evidence, "
                                "which sdd-gate record owns")
    return text


def _process_bound(raw: bytes, count: int) -> tuple[int, int]:
    allowance = REVISION_BYTES + RECORDING_BYTES_PER_TASK * count
    lines = _lines(raw)
    return (RECORD_BASE_BYTES + len(raw) + lines + allowance,
            lines + math.ceil(allowance / ALLOWANCE_LINE_BYTES))


def _process_records(repo: Path, base: str, paths: list[str], sizes: list[tuple[int, int]],
                     count: int) -> list[dict]:
    ids = ["s", "p", *(f"t{n}" for n in range(1, count + 1))]
    records = []
    for record_id, path, (size, added) in zip(ids, paths, sizes):
        found = tree_entry(repo, base, path)
        if found is not None and found["kind"] != "blob":
            raise ForecastError(f"{path} is not a blob at the base")
        records.append({"id": record_id, "owner": 0, "path": path,
                        "change": "add" if found is None else "modify", "last_task": count,
                        "bounds": [_bound(added, 0, size, [record_id])]})
    return records


def _delivery(base: str, base_tree: str, package: dict, records: list[dict], count: int) -> dict:
    return {"schema_version": 3, "kind": "review-feasibility-delivery", "delivery_base": base,
            "proposed_boundary": BOUNDARY,
            "boundaries": [{"id": BOUNDARY, "parent": None, "tasks": list(range(1, count + 1)),
                            "acceptance": ACCEPTANCE, "depends_on": [],
                            "prerequisite": {"kind": "delivery-base"}, "process_package": package,
                            "process_forecast_ids": [record["id"] for record in records],
                            "process_commit_subject_bytes":
                                [SUBJECT_BYTES] * (count + PROCESS_SUBJECTS_BEYOND_TASKS)}],
            "process_records": records,
            "actual_evidence": {"kind": "git-range-ownership/v1", "head": base, "tree": base_tree,
                                "process_ranges": []},
            "derived_from": None}


def _settled_root(repo: Path, base: str, base_tree: str, root_text: str, package: dict,
                  sizes: list[tuple[int, int]], count: int) -> tuple[dict, str]:
    """Re-render the root until its own process record covers the root as written."""
    paths = [package["spec"], package["plan"], *package["tasks"]]
    root_size = (0, 0)
    for _ in range(SETTLE_RENDERS):
        records = _process_records(repo, base, paths, [sizes[0], root_size, *sizes[1:]], count)
        delivery = _delivery(base, base_tree, package, records, count)
        text = _replaced(root_text, DELIVERY_HEADING, delivery)
        needed = _process_bound(text.encode("utf-8"), count)
        merged = (max(root_size[0], needed[0]), max(root_size[1], needed[1]))
        if merged == root_size:
            return delivery, text
        root_size = merged
    raise ForecastError("the root's process record did not settle")


def _replace_file(target: Path, raw: bytes) -> None:
    mode = target.stat().st_mode & 0o7777
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        os.chmod(name, mode)
        os.replace(name, target)
    except OSError:
        Path(name).unlink(missing_ok=True)
        raise


def write_forecast(repo: Path, plan: Path, base: str, spec: Path, raw: bytes,
                   authority: BudgetAuthority) -> list[str]:
    """Write the forecast blocks and return the repository-relative paths whose bytes changed."""
    if len(raw) > authority.report_wire_max_bytes:
        raise ForecastError(f"estimate exceeds the {authority.report_wire_max_bytes}-byte report wire bound")
    root = _repo_path(repo, plan, "plan")
    spec_path = _repo_path(repo, spec, "spec")
    full_commit(repo, base)
    base_tree = history_commit(repo, base).tree
    count = authority.check("implementation-plan", repo / root).metrics["file_count"] - 1
    if count < 1:
        raise ForecastError("missing indexed tasks")
    members = [str(PurePosixPath(root).with_suffix(".tasks") / f"task-{n}.md") for n in range(1, count + 1)]
    if spec_path == root or spec_path in members:
        raise ForecastError("spec is the plan root or a task member")
    root_text = _read_text(repo, root, DELIVERY_HEADING)
    member_texts = [_read_text(repo, member, TASK_HEADING) for member in members]
    spec_bytes = read_regular(repo, spec_path)
    estimate = _Estimate(repo, base, {spec_path, root, *members})
    tasks = estimate.parse(raw, count)
    task_blocks = _task_blocks(repo, tasks, estimate)
    new_members = [_replaced(text, TASK_HEADING, block) for text, block in zip(member_texts, task_blocks)]
    package = {"spec": spec_path, "plan": root, "tasks": members}
    sizes = [_process_bound(spec_bytes, count), *(_process_bound(text.encode("utf-8"), count)
                                                   for text in new_members)]
    delivery, new_root = _settled_root(repo, base, base_tree, root_text, package, sizes, count)
    try:
        boundaries = validate_boundaries(delivery["boundaries"], count, BOUNDARY)
        _records(delivery, tuple(block["task"] for block in task_blocks), boundaries)
    except ForecastError as exc:
        raise ForecastError(f"forecast self-check failed: {exc}") from exc
    changed = []
    for path, text in zip([root, *members], [new_root, *new_members]):
        encoded = text.encode("utf-8")
        if encoded != read_regular(repo, path):
            _replace_file(repo / path, encoded)
            changed.append(path)
    return changed
