"""The forecast a completed sdd task leaves behind: its ownership evidence, computed from Git (issue 227, D2, D12)."""
from __future__ import annotations

import copy
import os
from pathlib import Path, PurePosixPath

from agent_tools.review_actual import GenerationError, _run_git
from agent_tools.review_forecast import ForecastError, _block, ancestor, canonical_bytes, history_commit

DELIVERY_HEADING = "## Review feasibility delivery"
TASK_HEADING = "## Review feasibility task"


class RecordError(Exception):
    """The evidence cannot be computed; the message is the one-line reason."""


class RangeError(RecordError):
    """The task's commits are not a range of this checkout's history that the evidence can name."""


def _relative(repo: Path, plan: Path) -> PurePosixPath:
    try:
        return PurePosixPath(Path(os.path.realpath(plan)).relative_to(os.path.realpath(repo)).as_posix())
    except ValueError:
        raise RecordError("plan is outside its checkout") from None


def paths(repo: Path, plan: Path, task: int) -> tuple[PurePosixPath, PurePosixPath]:
    """The checkout-relative paths of the plan root and of task `task`'s member."""
    relative = _relative(repo, plan)
    return relative, relative.with_suffix(".tasks") / f"task-{task}.md"


def _committed(repo: Path, commit: str, path: PurePosixPath) -> bytes:
    try:
        return _run_git(repo, "cat-file", "blob", f"{commit}:{path}", binary=True)
    except GenerationError:
        raise RecordError(f"{path} is not committed at {commit[:7]}") from None


def _members(repo: Path, commit: str, plan: PurePosixPath) -> list[PurePosixPath]:
    """The plan's task members committed at `commit`, in task order."""
    directory = plan.with_suffix(".tasks")
    try:
        listed = _run_git(repo, "ls-tree", "-z", "--name-only", commit, f"{directory}/", binary=True)
    except GenerationError:
        raise RecordError(f"cannot list {directory} at {commit[:7]}") from None
    names = {PurePosixPath(name.decode("utf-8")) for name in listed.split(b"\0") if name}
    members = [directory / f"task-{number}.md" for number in range(1, len(names) + 1)]
    if set(members) != names:
        raise RecordError(f"{directory} does not hold task-1.md to task-{len(names)}.md")
    return members


def _blocks(repo: Path, commit: str, plan: PurePosixPath) -> tuple[bytes, dict, list[tuple[bytes, dict]]]:
    try:
        root = _committed(repo, commit, plan)
        delivery = _block(root, DELIVERY_HEADING)
        members = []
        for path in _members(repo, commit, plan):
            raw = _committed(repo, commit, path)
            members.append((raw, _block(raw, TASK_HEADING)))
    except ForecastError as error:
        raise RecordError(str(error)) from None
    return root, delivery, members


def _replace(raw: bytes, heading: str, value: dict) -> bytes:
    """`raw` with the one JSON line under `heading` rendered from `value`."""
    lines = raw.decode("utf-8").split("\n")
    try:
        start = lines.index(heading)
        line = lines.index("```json", start) + 1
    except ValueError:
        raise RecordError(f"cannot place the {heading} block") from None
    lines[line] = canonical_bytes(value).decode("ascii")[:-1]
    replaced = "\n".join(lines).encode("utf-8")
    try:
        if _block(replaced, heading) != value:
            raise RecordError(f"the {heading} block did not take the new value")
    except ForecastError as error:
        raise RecordError(str(error)) from None
    return replaced


def _check_range(repo: Path, evidence: str, base: str, head: str) -> None:
    try:
        if base == head or not ancestor(repo, base, head):
            raise RangeError("the task has no commits over its base")
        if not ancestor(repo, evidence, base):
            raise RangeError("the forecast's evidence head is not behind the task's base")
    except ForecastError as error:
        raise RangeError(str(error)) from None


def _apply(delivery: dict, block: dict, task: int, base: str, head: str, tree: str) -> tuple[dict, dict]:
    delivery, block = copy.deepcopy(delivery), copy.deepcopy(block)
    evidence = delivery["actual_evidence"]
    block["task"]["actual_ranges"].append({"base": base, "head": head})
    if base != evidence["head"]:
        evidence["process_ranges"].append({"base": evidence["head"], "head": base,
                                           "boundaries": [delivery["proposed_boundary"]]})
    evidence["head"], evidence["tree"] = head, tree
    for boundary in delivery["boundaries"]:
        prerequisite = boundary["prerequisite"]
        if prerequisite["kind"] == "completed-tasks" and max(prerequisite["tasks"]) == task:
            prerequisite["commit"], prerequisite["tree"] = head, tree
    return delivery, block


def recorded(repo: Path, plan: Path, task: int, base: str, head: str) -> tuple[bytes, bytes]:
    """The plan root's and task `task`'s member's bytes once the task's commits `base..head` are recorded.

    Both are computed from the bytes committed at `head`: the task's `actual_ranges` gains `base..head`,
    the process commits since the previous evidence head (`C..base`) become a process range, the evidence
    head and tree become `head`, and every `completed-tasks` prerequisite whose highest task is `task`
    gets `head`'s identity. Raises `RangeError` for commits that are not a range over the evidence and
    `RecordError` when a task commit edited a forecast block or a block cannot be read.
    """
    repo = Path(repo)
    relative = _relative(repo, plan)
    at_base = _blocks(repo, base, relative)
    try:
        _check_range(repo, at_base[1]["actual_evidence"]["head"], base, head)
    except (KeyError, TypeError):
        raise RecordError("the forecast has no evidence head") from None
    root, delivery, members = _blocks(repo, head, relative)
    if (delivery, [block for _, block in members]) != (at_base[1], [block for _, block in at_base[2]]):
        raise RecordError("a task commit edited the forecast")
    if not 1 <= task <= len(members):
        raise RecordError(f"task {task} has no member")
    try:
        tree = history_commit(repo, head).tree
        delivery_after, block_after = _apply(delivery, members[task - 1][1], task, base, head, tree)
    except ForecastError as error:
        raise RecordError(str(error)) from None
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RecordError("the forecast blocks do not have the recorded shape") from None
    return (_replace(root, DELIVERY_HEADING, delivery_after),
            _replace(members[task - 1][0], TASK_HEADING, block_after))
