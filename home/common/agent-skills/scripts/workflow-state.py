#!/usr/bin/env python3

import argparse
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Callable


SCHEMA_VERSION = 1
CONTROL_INTERFACE_VERSION = 1
ATTEMPT_STATES = frozenset({"active", "handed_off", "stopped", "failed", "merged"})
RESULT_STATES = frozenset({"merged", "stopped", "failed"})
RESULT_SOURCES = frozenset({"owner", "expiry", "superseded", "refused"})
RESULT_FIELDS = (
    "issue",
    "state",
    "pr_url",
    "merge_sha",
    "issue_closed",
    "discussion_items",
    "notes",
)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PHASE_ACTIONS = frozenset({"continue", "fresh_start", "handoff", "delegate"})
PHASE_INPUT_FIELDS = (
    "turn_count",
    "context_tokens",
    "turn_ceiling",
    "context_ceiling",
    "turn_headroom",
    "context_headroom",
    "next_needs_context",
    "artifacts_sufficient",
    "remainder_self_contained",
)
STATE_FIELDS = frozenset(
    {"schema_version", "run_id", "created_at", "updated_at", "issues"}
)
ISSUE_FIELDS = frozenset({"issue", "attempts", "outcome"})
ATTEMPT_FIELDS = frozenset(
    {
        "issue",
        "attempt",
        "owner",
        "worktree",
        "started_at",
        "deadline_at",
        "state",
        "launch_kind",
        "launches",
        "prior_attempt",
        "result",
        "finished_at",
        "result_source",
        "handoff_path",
        "phase",
        "last_progress_at",
        "phase_action",
        "phase_inputs",
    }
)
LAUNCH_FIELDS = frozenset({"kind", "owner", "worktree", "at"})

BOOTSTRAP_FIELDS = frozenset({"interface_version", "run_id", "requirements"})
BOOTSTRAP_REQUIREMENT_FIELDS = frozenset(
    {"issue", "attempt", "owner", "action_id", "recorded_worktree"}
)
CONTROL_REQUEST_FIELDS = frozenset(
    {
        "interface_version",
        "now",
        "max_parallel",
        "attempt_budget_minutes",
        "issues",
        "tracker",
        "owners",
        "worktrees",
    }
)
TRACKER_OBSERVATION_FIELDS = frozenset(
    {"issue", "state", "open_blockers", "decision_blockers"}
)
TRACKER_STATES = frozenset({"open", "closed"})
DECISION_BLOCKER_FIELDS = frozenset({"issue", "url"})
OWNER_OBSERVATION_FIELDS = frozenset(
    {"event_id", "issue", "attempt", "launch", "state"}
)
OWNER_OBSERVATION_STATES = frozenset({"unavailable"})
WORKTREE_OBSERVATION_FIELDS = frozenset({"issue", "recorded", "candidate"})
RECORDED_WORKTREE_FIELDS = frozenset({"path", "state"})
RECORDED_WORKTREE_STATES = frozenset(
    {"matching_issue_branch", "absent", "mismatch"}
)
CANDIDATE_WORKTREE_FIELDS = frozenset({"path", "state"})
CANDIDATE_WORKTREE_STATES = frozenset({"absent"})
CONTROL_RESPONSE_FIELDS = frozenset(
    {
        "interface_version",
        "run_id",
        "now",
        "summaries",
        "deltas",
        "actions",
        "next_deadline",
    }
)
CONTROL_SUMMARY_FIELDS = frozenset(
    {
        "issue",
        "state",
        "attempt",
        "owner",
        "worktree",
        "deadline_at",
        "blockers",
        "result",
    }
)
CONTROL_SUMMARY_STATES = frozenset(
    {
        "queued",
        "blocked",
        "fogged",
        "active",
        "handed_off",
        "merged",
        "stopped",
        "failed",
        "closed",
    }
)
CONTROL_BLOCKER_FIELDS = frozenset({"kind", "issue", "url"})
CONTROL_BLOCKER_KINDS = frozenset({"issue", "decision"})
CONTROL_DELTA_FIELDS = frozenset({"issue", "attempt", "kind", "state"})
CONTROL_DELTA_KINDS = frozenset(
    {"expired", "spawned", "resumed", "retried", "retry_refused"}
)
CONTROL_DISPATCH_FIELDS = frozenset(
    {
        "id",
        "kind",
        "issue",
        "attempt",
        "owner",
        "worktree",
        "handoff_path",
        "deadline_at",
    }
)
CONTROL_DISPATCH_KINDS = frozenset({"spawn", "resume", "retry"})
CONTROL_WAIT_FIELDS = frozenset({"id", "kind", "wake_on", "deadline_at"})
CONTROL_WAKE_EVENTS = frozenset(
    {"owner_notification", "tracker_change", "deadline"}
)
CONTROL_FINALIZE_FIELDS = frozenset({"id", "kind"})


class WorkflowError(Exception):
    pass


def parse_utc(value: str, label: str = "time") -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise WorkflowError(f"invalid {label}: expected an RFC3339 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise WorkflowError(f"invalid {label}: expected an RFC3339 UTC timestamp")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return parsed


def literal_boolean(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("expected literal true or false")


def require_plain_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorkflowError(f"invalid {label}")
    return value


def validate_result(value: Any, *, expected_issue: int | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or tuple(value.keys()) != RESULT_FIELDS:
        if not isinstance(value, dict) or set(value) != set(RESULT_FIELDS):
            raise WorkflowError(
                "invalid terminal result: fields must be exactly "
                + ", ".join(RESULT_FIELDS)
            )
    issue = require_plain_int(value["issue"], "terminal result issue", minimum=1)
    if expected_issue is not None and issue != expected_issue:
        raise WorkflowError(
            f"terminal result issue {issue} does not match requested issue {expected_issue}"
        )
    if value["state"] not in RESULT_STATES:
        raise WorkflowError("invalid terminal result state")
    for field in ("pr_url", "merge_sha"):
        if value[field] is not None and not isinstance(value[field], str):
            raise WorkflowError(f"invalid terminal result {field}: expected string or null")
    if not isinstance(value["issue_closed"], bool):
        raise WorkflowError("invalid terminal result issue_closed: expected boolean")
    if not isinstance(value["discussion_items"], list):
        raise WorkflowError("invalid terminal result discussion_items: expected list")
    if not isinstance(value["notes"], str) or len(value["notes"]) > 500:
        raise WorkflowError("invalid terminal result notes: expected at most 500 characters")
    return {field: copy.deepcopy(value[field]) for field in RESULT_FIELDS}


def validate_launch_event(value: Any, *, owner: str, worktree: str) -> None:
    if not isinstance(value, dict) or set(value) != LAUNCH_FIELDS:
        raise WorkflowError("invalid launch event")
    if not isinstance(value["kind"], str) or value["kind"] not in {"fresh", "resume"}:
        raise WorkflowError("invalid launch kind")
    if value["owner"] != owner or value["worktree"] != worktree:
        raise WorkflowError("invalid launch identity")
    parse_utc(value["at"], "launch time")


def select_phase_action(
    *,
    turn_count: int | None,
    context_tokens: int | None,
    turn_ceiling: int,
    context_ceiling: int,
    turn_headroom: int,
    context_headroom: int,
    next_needs_context: bool,
    artifacts_sufficient: bool,
    remainder_self_contained: bool,
) -> str:
    """Select the phase-boundary action from the phase budget and the three booleans.

    The phase budget is the turn and context ceilings with their headrooms; this
    function never sees the attempt budget's wall clock, and ``delegate`` does not
    reset it. ``fresh_start`` comes first because a disposable conversation with
    sufficient artifacts is the cheapest transition at any budget level. Unknown
    usage and at-ceiling usage both yield ``handoff`` before ``delegate`` is
    considered, so a persisted ``delegate`` implies measured usage strictly below
    both ceilings.
    """
    if not next_needs_context and artifacts_sufficient:
        return "fresh_start"
    if turn_count is None or context_tokens is None:
        return "handoff"
    if (
        turn_count >= turn_ceiling - turn_headroom
        or context_tokens >= context_ceiling - context_headroom
    ):
        return "handoff"
    if remainder_self_contained:
        return "delegate"
    if not next_needs_context:
        return "handoff"
    return "continue"


def validate_phase_inputs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or tuple(value.keys()) != PHASE_INPUT_FIELDS:
        if not isinstance(value, dict) or set(value) != set(PHASE_INPUT_FIELDS):
            raise WorkflowError(
                "invalid phase inputs: fields must be exactly "
                + ", ".join(PHASE_INPUT_FIELDS)
            )
    for field in ("turn_count", "context_tokens"):
        if value[field] is not None:
            require_plain_int(value[field], f"phase input {field}")
    for field in (
        "turn_ceiling",
        "context_ceiling",
        "turn_headroom",
        "context_headroom",
    ):
        require_plain_int(value[field], f"phase input {field}")
    if value["turn_headroom"] >= value["turn_ceiling"]:
        raise WorkflowError("turn headroom must be smaller than turn ceiling")
    if value["context_headroom"] >= value["context_ceiling"]:
        raise WorkflowError("context headroom must be smaller than context ceiling")
    for field in (
        "next_needs_context",
        "artifacts_sufficient",
        "remainder_self_contained",
    ):
        if not isinstance(value[field], bool):
            raise WorkflowError(f"invalid phase input {field}: expected boolean")
    return value


def validate_attempt(value: Any, *, issue: int, expected_number: int) -> None:
    if not isinstance(value, dict) or set(value) != ATTEMPT_FIELDS:
        raise WorkflowError("invalid attempt schema")
    if value["issue"] != issue or value["attempt"] != expected_number:
        raise WorkflowError("invalid attempt identity")
    if not isinstance(value["owner"], str) or not value["owner"]:
        raise WorkflowError("invalid attempt owner")
    if not isinstance(value["worktree"], str) or not Path(value["worktree"]).is_absolute():
        raise WorkflowError("invalid attempt worktree")
    started_at = parse_utc(value["started_at"], "attempt start time")
    deadline_at = parse_utc(value["deadline_at"], "attempt deadline")
    last_progress_at = parse_utc(value["last_progress_at"], "attempt progress time")
    if not started_at <= last_progress_at <= deadline_at:
        raise WorkflowError("invalid attempt timestamp order")
    if not isinstance(value["state"], str) or value["state"] not in ATTEMPT_STATES:
        raise WorkflowError("invalid attempt state")
    if not isinstance(value["launch_kind"], str) or value["launch_kind"] not in {
        "fresh",
        "resume",
    }:
        raise WorkflowError("invalid attempt launch kind")
    if not isinstance(value["launches"], list) or not value["launches"]:
        raise WorkflowError("invalid attempt launches")
    previous_launch_at = started_at
    for event in value["launches"]:
        validate_launch_event(event, owner=value["owner"], worktree=value["worktree"])
        launch_at = parse_utc(event["at"], "launch time")
        if not previous_launch_at <= launch_at <= deadline_at:
            raise WorkflowError("invalid launch timestamp order")
        previous_launch_at = launch_at
    if value["launches"][0]["kind"] != "fresh":
        raise WorkflowError("invalid attempt launches: first event must be fresh")
    if value["launch_kind"] != value["launches"][-1]["kind"]:
        raise WorkflowError("attempt launch kind does not match latest launch event")
    expected_prior = None if expected_number == 1 else expected_number - 1
    if value["prior_attempt"] != expected_prior:
        raise WorkflowError("invalid prior attempt identity")
    result = value["result"]
    if result is not None:
        result = validate_result(result, expected_issue=issue)
    if value["state"] in {"active", "handed_off"}:
        if result is not None:
            raise WorkflowError("nonterminal attempt must not carry a terminal result")
    elif result is None or result["state"] != value["state"]:
        raise WorkflowError("terminal attempt state and result must match")
    result_source = value["result_source"]
    if (result is None) != (value["finished_at"] is None) or (result is None) != (
        result_source is None
    ):
        raise WorkflowError(
            "attempt result, finish time and result source must all be null "
            "or all be set"
        )
    if result is not None:
        if not isinstance(result_source, str) or result_source not in RESULT_SOURCES:
            raise WorkflowError("invalid attempt result source")
        finished_at = parse_utc(value["finished_at"], "attempt finish time")
        if finished_at < started_at:
            raise WorkflowError("invalid attempt finish time order")
        if result_source == "expiry" and finished_at < deadline_at:
            raise WorkflowError(
                "expiry finish time must not precede the attempt deadline"
            )
    if value["handoff_path"] is not None:
        if not isinstance(value["handoff_path"], str) or not Path(
            value["handoff_path"]
        ).is_absolute():
            raise WorkflowError("invalid attempt handoff path")
    require_plain_int(value["phase"], "attempt phase")
    if (value["phase_action"] is None) != (value["phase_inputs"] is None):
        raise WorkflowError("phase action and inputs must both be null or both be set")
    if value["phase_action"] is not None:
        if (
            not isinstance(value["phase_action"], str)
            or value["phase_action"] not in PHASE_ACTIONS
        ):
            raise WorkflowError("invalid phase action")
        phase_inputs = validate_phase_inputs(value["phase_inputs"])
        if select_phase_action(**phase_inputs) != value["phase_action"]:
            raise WorkflowError("phase action does not match persisted inputs")
    if value["state"] == "handed_off":
        if value["phase_action"] != "handoff" or value["handoff_path"] is None:
            raise WorkflowError("handed-off attempt requires a durable handoff")


def validate_state(value: Any, *, run_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != STATE_FIELDS:
        raise WorkflowError("invalid workflow state schema")
    if value["schema_version"] != SCHEMA_VERSION:
        raise WorkflowError(
            f"unsupported workflow state schema version: {value['schema_version']!r}"
        )
    if value["run_id"] != run_id:
        raise WorkflowError("workflow state run identity does not match requested run")
    created_at = parse_utc(value["created_at"], "run creation time")
    updated_at = parse_utc(value["updated_at"], "run update time")
    if updated_at < created_at:
        raise WorkflowError("invalid run timestamp order")
    if not isinstance(value["issues"], dict):
        raise WorkflowError("invalid workflow issues")
    for issue_key, issue_value in value["issues"].items():
        if not isinstance(issue_key, str) or not issue_key.isdecimal():
            raise WorkflowError("invalid issue identity")
        issue = int(issue_key)
        if issue <= 0 or str(issue) != issue_key:
            raise WorkflowError("invalid issue identity")
        if not isinstance(issue_value, dict) or set(issue_value) != ISSUE_FIELDS:
            raise WorkflowError("invalid issue schema")
        if (
            isinstance(issue_value["issue"], bool)
            or not isinstance(issue_value["issue"], int)
            or issue_value["issue"] != issue
        ):
            raise WorkflowError("invalid issue identity")
        attempts = issue_value["attempts"]
        if not isinstance(attempts, list) or len(attempts) > 2:
            raise WorkflowError("invalid attempts list")
        for number, attempt in enumerate(attempts, start=1):
            validate_attempt(attempt, issue=issue, expected_number=number)
            started_at = parse_utc(attempt["started_at"], "attempt start time")
            if started_at < created_at:
                raise WorkflowError("attempt starts before run creation")
            for launch in attempt["launches"]:
                if parse_utc(launch["at"], "launch time") > updated_at:
                    raise WorkflowError("launch occurs after run update time")
        if issue_value["outcome"] is not None:
            validate_result(issue_value["outcome"], expected_issue=issue)
            if not attempts or attempts[-1]["result"] != issue_value["outcome"]:
                raise WorkflowError("issue outcome does not match its latest attempt")
    return value


def workflow_paths(repo_root_value: str, run_id: str) -> tuple[Path, Path, Path]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise WorkflowError("invalid run_id")
    supplied_root = Path(repo_root_value).absolute()
    root_status = path_status(supplied_root)
    if root_status is None:
        raise WorkflowError("repository root does not exist")
    if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
        raise WorkflowError("repository root must be a non-symlink directory")
    repo_root = supplied_root.resolve(strict=True)
    workflows_dir = repo_root / ".superpowers" / "workflows"
    ensure_directory(repo_root / ".superpowers", ".superpowers")
    ensure_directory(workflows_dir, "workflows")
    run_dir = workflows_dir / run_id
    ensure_directory(run_dir, "run directory")
    return run_dir, run_dir / "state.json", run_dir / "state.lock"


def path_status(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def ensure_directory(path: Path, label: str) -> None:
    status = path_status(path)
    if status is None:
        try:
            path.mkdir()
        except FileExistsError:
            status = path_status(path)
        else:
            status = path_status(path)
    if status is None or stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise WorkflowError(f"{label} must be a non-symlink directory")


def require_regular_path(path: Path, label: str, *, allow_missing: bool) -> bool:
    status = path_status(path)
    if status is None:
        if allow_missing:
            return False
        raise WorkflowError(f"{label} does not exist")
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise WorkflowError(f"{label} must be a non-symlink regular file")
    return True


def verify_open_file(path: Path, descriptor: int, label: str) -> None:
    path_info = path.lstat()
    file_info = os.fstat(descriptor)
    if (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or not stat.S_ISREG(file_info.st_mode)
        or (path_info.st_dev, path_info.st_ino) != (file_info.st_dev, file_info.st_ino)
    ):
        raise WorkflowError(f"{label} changed while being opened")


def open_existing_regular(path: Path, label: str, flags: int) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags | no_follow)
    try:
        verify_open_file(path, descriptor, label)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def open_existing_directory(path: Path, label: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        path_info = path.lstat()
        directory_info = os.fstat(descriptor)
        if (
            stat.S_ISLNK(path_info.st_mode)
            or not stat.S_ISDIR(path_info.st_mode)
            or not stat.S_ISDIR(directory_info.st_mode)
            or (path_info.st_dev, path_info.st_ino)
            != (directory_info.st_dev, directory_info.st_ino)
        ):
            raise WorkflowError(f"{label} changed while being opened")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def validate_handoff_path(run_dir: Path, path_value: str) -> str:
    handoffs_dir = run_dir / "handoffs"
    candidate = Path(os.path.abspath(path_value))
    candidate_status = path_status(candidate)
    if candidate_status is None:
        raise WorkflowError("handoff path does not exist")
    if stat.S_ISLNK(candidate_status.st_mode) or not stat.S_ISREG(
        candidate_status.st_mode
    ):
        raise WorkflowError("handoff path must be a non-symlink regular file")
    try:
        resolved_handoffs = handoffs_dir.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        relative = resolved_candidate.relative_to(resolved_handoffs)
    except (FileNotFoundError, ValueError) as error:
        raise WorkflowError(
            "handoff path must be beneath this run's handoffs directory"
        ) from error
    if relative == Path("."):
        raise WorkflowError("handoff path must name a file")

    directory_descriptor = open_existing_directory(
        handoffs_dir, "handoffs directory"
    )
    try:
        parts = relative.parts
        for part in parts[:-1]:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            child_descriptor = os.open(part, flags, dir_fd=directory_descriptor)
            try:
                if not stat.S_ISDIR(os.fstat(child_descriptor).st_mode):
                    raise WorkflowError("handoff parent must be a non-symlink directory")
            except BaseException:
                os.close(child_descriptor)
                raise
            os.close(directory_descriptor)
            directory_descriptor = child_descriptor

        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=directory_descriptor)
        try:
            if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise WorkflowError("handoff path must be a non-symlink regular file")
        finally:
            os.close(file_descriptor)
    finally:
        os.close(directory_descriptor)
    return str(candidate)


def open_stable_lock(lock_path: Path) -> int:
    require_regular_path(lock_path, "state lock", allow_missing=True)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | no_follow,
            0o600,
        )
    except FileExistsError:
        descriptor = open_existing_regular(lock_path, "state lock", os.O_RDWR)
    else:
        try:
            verify_open_file(lock_path, descriptor, "state lock")
        except BaseException:
            os.close(descriptor)
            raise
    return descriptor


def ensure_gitignore(workflows_dir: Path) -> None:
    gitignore = workflows_dir / ".gitignore"
    require_regular_path(gitignore, "workflows .gitignore", allow_missing=True)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            gitignore,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            0o644,
        )
    except FileExistsError:
        descriptor = open_existing_regular(
            gitignore, "workflows .gitignore", os.O_RDONLY
        )
        with os.fdopen(descriptor, encoding="utf-8") as source:
            patterns = source.read().splitlines()
        if "*" not in patterns:
            raise WorkflowError("workflows .gitignore must contain '*'")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        verify_open_file(gitignore, output.fileno(), "workflows .gitignore")
        output.write("*\n")
        output.flush()
        os.fsync(output.fileno())
    fsync_directory(workflows_dir)


def read_locked_state(state_path: Path, run_id: str) -> dict[str, Any]:
    require_regular_path(state_path, "workflow state", allow_missing=False)
    try:
        descriptor = open_existing_regular(state_path, "workflow state", os.O_RDONLY)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            value = json.load(source)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid workflow state JSON: {error}") from error
    return validate_state(value, run_id=run_id)


def fsync_directory(directory: Path) -> None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_state(run_dir: Path, state_path: Path, state: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=run_dir,
            prefix=".state.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(state, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, state_path)
        temporary_path = None
        fsync_directory(run_dir)
    except BaseException as original_error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise cleanup_error from original_error
        raise


Mutation = Callable[[dict[str, Any] | None], tuple[Any, bool]]


def transact(
    repo_root: str, run_id: str, mutation: Mutation, *, allow_missing: bool = False
) -> Any:
    run_dir, state_path, lock_path = workflow_paths(repo_root, run_id)
    require_regular_path(state_path, "workflow state", allow_missing=True)
    require_regular_path(lock_path, "state lock", allow_missing=True)
    ensure_gitignore(run_dir.parent)
    lock_descriptor = open_stable_lock(lock_path)
    with os.fdopen(lock_descriptor, "r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state_exists = require_regular_path(
            state_path, "workflow state", allow_missing=True
        )
        if state_exists:
            current = read_locked_state(state_path, run_id)
            state = copy.deepcopy(current)
        elif allow_missing:
            state = None
        else:
            raise WorkflowError(f"workflow run {run_id!r} is not initialized")
        result, changed = mutation(state)
        if changed:
            if state is None:
                if allow_missing and isinstance(result, dict):
                    state = result
                else:
                    raise WorkflowError("internal error: changed transaction has no state")
            validate_state(state, run_id=run_id)
            atomic_write_state(run_dir, state_path, state)
        return result


def terminal_result(issue: int, state: str, notes: str) -> dict[str, Any]:
    if len(notes) > 500:
        raise WorkflowError("generated terminal notes exceed 500 characters")
    return {
        "issue": issue,
        "state": state,
        "pr_url": None,
        "merge_sha": None,
        "issue_closed": False,
        "discussion_items": [],
        "notes": notes,
    }


def retain_worktree(notes: str, worktree: str) -> str:
    if worktree in notes:
        return notes
    suffix = f"worktree: {worktree}"
    if len(suffix) > 500:
        raise WorkflowError("worktree path is too long for terminal notes")
    if not notes:
        return suffix
    separator = "; "
    prefix = notes[: 500 - len(separator) - len(suffix)].rstrip()
    return f"{prefix}{separator}{suffix}" if prefix else suffix


def finish_time(attempt: dict[str, Any], now: str) -> str:
    """Clamp a terminal finish instant to at least the attempt's own start.

    ``launch`` deliberately leaves its ``--now`` unguarded, so a dispatcher may
    hand a terminal writer an instant earlier than the attempt it is closing
    began. Clamping keeps the record truthful — the attempt ended no earlier
    than it began — and keeps the ``finished_at >= started_at`` invariant
    satisfiable instead of bricking every later read of the run.
    """
    started_at = parse_utc(attempt["started_at"], "attempt start time")
    return now if parse_utc(now, "finish time") >= started_at else attempt["started_at"]


def stop_attempt(
    attempt: dict[str, Any], *, reason: str, now: str, source: str
) -> dict[str, Any]:
    """Stamp a terminal stopped record.

    ``source`` says who ended the attempt and must be a member of ``RESULT_SOURCES``;
    ``now`` is the already-formatted RFC3339 UTC instant at which the record was
    written, which for an ``expiry`` is at or after the attempt budget's
    ``deadline_at``.
    """
    result = terminal_result(
        attempt["issue"], "stopped", f"{reason}; worktree: {attempt['worktree']}"
    )
    attempt["state"] = "stopped"
    attempt["result"] = result
    attempt["finished_at"] = finish_time(attempt, now)
    attempt["result_source"] = source
    return result


def require_exact_fields(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkflowError(f"invalid {label} fields")
    return value


def require_absolute_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise WorkflowError(f"invalid {label} path")
    return value


def validate_tracker_observation(value: Any) -> dict[str, Any]:
    observation = require_exact_fields(
        value, TRACKER_OBSERVATION_FIELDS, "tracker observation"
    )
    require_plain_int(observation["issue"], "tracker issue", minimum=1)
    if (
        not isinstance(observation["state"], str)
        or observation["state"] not in TRACKER_STATES
    ):
        raise WorkflowError("invalid tracker state")
    blockers = observation["open_blockers"]
    if not isinstance(blockers, list):
        raise WorkflowError("invalid tracker open blocker")
    seen_open: set[int] = set()
    for blocker in blockers:
        require_plain_int(blocker, "tracker open blocker", minimum=1)
        if blocker in seen_open:
            raise WorkflowError("duplicate tracker open blocker")
        seen_open.add(blocker)
    decisions = observation["decision_blockers"]
    if not isinstance(decisions, list):
        raise WorkflowError("invalid decision blockers")
    seen_decisions: set[int] = set()
    for decision in decisions:
        decision = require_exact_fields(
            decision, DECISION_BLOCKER_FIELDS, "decision blocker"
        )
        decision_issue = require_plain_int(
            decision["issue"], "decision blocker issue", minimum=1
        )
        if decision_issue in seen_decisions:
            raise WorkflowError("duplicate decision blocker")
        seen_decisions.add(decision_issue)
        if not isinstance(decision["url"], str):
            raise WorkflowError("invalid decision blocker url")
    return observation


def validate_owner_observation(value: Any) -> dict[str, Any]:
    observation = require_exact_fields(
        value, OWNER_OBSERVATION_FIELDS, "owner observation"
    )
    if not isinstance(observation["event_id"], str) or not observation["event_id"]:
        raise WorkflowError("invalid owner event_id")
    require_plain_int(observation["issue"], "owner issue", minimum=1)
    require_plain_int(observation["attempt"], "owner attempt", minimum=1)
    require_plain_int(observation["launch"], "owner launch", minimum=1)
    if (
        not isinstance(observation["state"], str)
        or observation["state"] not in OWNER_OBSERVATION_STATES
    ):
        raise WorkflowError("invalid owner state")
    return observation


def validate_worktree_observation(value: Any) -> dict[str, Any]:
    observation = require_exact_fields(
        value, WORKTREE_OBSERVATION_FIELDS, "worktree observation"
    )
    require_plain_int(observation["issue"], "worktree issue", minimum=1)
    recorded = observation["recorded"]
    if recorded is not None:
        recorded = require_exact_fields(
            recorded, RECORDED_WORKTREE_FIELDS, "recorded"
        )
        require_absolute_path(recorded["path"], "recorded")
        if (
            not isinstance(recorded["state"], str)
            or recorded["state"] not in RECORDED_WORKTREE_STATES
        ):
            raise WorkflowError("invalid recorded state")
    candidate = observation["candidate"]
    if candidate is not None:
        candidate = require_exact_fields(
            candidate, CANDIDATE_WORKTREE_FIELDS, "candidate"
        )
        require_absolute_path(candidate["path"], "candidate")
        if (
            not isinstance(candidate["state"], str)
            or candidate["state"] not in CANDIDATE_WORKTREE_STATES
        ):
            raise WorkflowError("invalid candidate state")
    return observation


def validate_control_request(value: Any) -> dict[str, Any]:
    request = require_exact_fields(value, CONTROL_REQUEST_FIELDS, "control request")
    if (
        type(request["interface_version"]) is not int
        or request["interface_version"] != CONTROL_INTERFACE_VERSION
    ):
        raise WorkflowError("unsupported control interface version")
    if not isinstance(request["now"], str):
        raise WorkflowError("invalid control now: expected an RFC3339 UTC timestamp")
    request["now"] = format_utc(parse_utc(request["now"], "control now"))
    require_plain_int(request["max_parallel"], "max_parallel", minimum=1)
    require_plain_int(
        request["attempt_budget_minutes"], "attempt_budget_minutes", minimum=1
    )

    issues = request["issues"]
    if not isinstance(issues, list):
        raise WorkflowError("invalid control issues")
    seen_issues: set[int] = set()
    for issue in issues:
        require_plain_int(issue, "control issue", minimum=1)
        if issue in seen_issues:
            raise WorkflowError("duplicate control issue")
        seen_issues.add(issue)

    tracker = request["tracker"]
    if not isinstance(tracker, list):
        raise WorkflowError("invalid tracker observations")
    tracker_issues: set[int] = set()
    for raw_observation in tracker:
        observation = validate_tracker_observation(raw_observation)
        issue = observation["issue"]
        if issue in tracker_issues:
            raise WorkflowError("duplicate tracker observation")
        tracker_issues.add(issue)
    if tracker_issues != seen_issues:
        raise WorkflowError("tracker observations must match requested issues")

    owners = request["owners"]
    if not isinstance(owners, list):
        raise WorkflowError("invalid owner observations")
    owner_event_ids: set[str] = set()
    owner_identities: set[tuple[int, int, int]] = set()
    for raw_observation in owners:
        observation = validate_owner_observation(raw_observation)
        if observation["issue"] not in seen_issues:
            raise WorkflowError("owner observation outside requested issues")
        if observation["event_id"] in owner_event_ids:
            raise WorkflowError("duplicate owner event_id")
        owner_event_ids.add(observation["event_id"])
        identity = (
            observation["issue"], observation["attempt"], observation["launch"]
        )
        if identity in owner_identities:
            raise WorkflowError("duplicate owner observation")
        owner_identities.add(identity)

    worktrees = request["worktrees"]
    if not isinstance(worktrees, list):
        raise WorkflowError("invalid worktree observations")
    worktree_issues: set[int] = set()
    for raw_observation in worktrees:
        observation = validate_worktree_observation(raw_observation)
        issue = observation["issue"]
        if issue in worktree_issues:
            raise WorkflowError("duplicate worktree observation")
        worktree_issues.add(issue)
        if issue not in seen_issues:
            raise WorkflowError("worktree observation outside requested issues")
    return request


def load_control_request(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        raise WorkflowError("request file path must be absolute")
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid control request JSON: {error}") from error
    except (OSError, UnicodeError) as error:
        raise WorkflowError(f"cannot read control request file: {error}") from error
    return validate_control_request(value)


def bootstrap_response(state: dict[str, Any]) -> dict[str, Any]:
    requirements = []
    for issue_key in sorted(state["issues"], key=int):
        issue_state = state["issues"][issue_key]
        if not issue_state["attempts"]:
            continue
        attempt = issue_state["attempts"][-1]
        launch = len(attempt["launches"])
        requirements.append(
            {
                "issue": attempt["issue"],
                "attempt": attempt["attempt"],
                "owner": attempt["owner"],
                "action_id": f"{attempt['issue']}:{attempt['attempt']}:{launch}",
                "recorded_worktree": attempt["worktree"],
            }
        )
    return {
        "interface_version": CONTROL_INTERFACE_VERSION,
        "run_id": state["run_id"],
        "requirements": requirements,
    }


def command_init_run(args: argparse.Namespace) -> int:
    now = format_utc(parse_utc(args.now, "--now"))

    def initialize(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        if state is not None:
            return state, False
        created = {
            "schema_version": SCHEMA_VERSION,
            "run_id": args.run_id,
            "created_at": now,
            "updated_at": now,
            "issues": {},
        }
        state = created
        return state, True

    state = transact(
        args.repo_root, args.run_id, initialize, allow_missing=True
    )
    print_json(bootstrap_response(state))
    return 0


def control_blockers(tracker: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"kind": "issue", "issue": issue, "url": None}
        for issue in tracker["open_blockers"]
    ] + [
        {"kind": "decision", "issue": item["issue"], "url": item["url"]}
        for item in tracker["decision_blockers"]
    ]


def canonical_worktree_path(path_value: str) -> str:
    """Return a comparison identity that resolves aliases in existing parents."""
    return os.path.normcase(str(Path(path_value).resolve(strict=False)))


def new_control_attempt(
    *, issue: int, attempt_number: int, worktree: str, now: str, deadline_at: str
) -> dict[str, Any]:
    owner = f"{issue}:{attempt_number}"
    return {
        "issue": issue,
        "attempt": attempt_number,
        "owner": owner,
        "worktree": worktree,
        "started_at": now,
        "deadline_at": deadline_at,
        "state": "active",
        "launch_kind": "fresh",
        "launches": [
            {"kind": "fresh", "owner": owner, "worktree": worktree, "at": now}
        ],
        "prior_attempt": None if attempt_number == 1 else attempt_number - 1,
        "result": None,
        "finished_at": None,
        "result_source": None,
        "handoff_path": None,
        "phase": 0,
        "last_progress_at": now,
        "phase_action": None,
        "phase_inputs": None,
    }


def control_summary(
    *,
    issue: int,
    tracker: dict[str, Any],
    issue_state: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers = control_blockers(tracker)
    latest = None
    if issue_state is not None and issue_state["attempts"]:
        latest = issue_state["attempts"][-1]
    if tracker["state"] == "closed" and latest is None:
        state_name = "closed"
    elif tracker["decision_blockers"] and latest is None:
        state_name = "fogged"
    elif tracker["open_blockers"] and latest is None:
        state_name = "blocked"
    elif latest is None:
        state_name = "queued"
    else:
        state_name = latest["state"]
        blockers = []
    result = None
    if latest is not None and latest["result"] is not None:
        result = {
            field: copy.deepcopy(latest["result"][field]) for field in RESULT_FIELDS
        }
    return {
        "issue": issue,
        "state": state_name,
        "attempt": None if latest is None else latest["attempt"],
        "owner": None if latest is None else latest["owner"],
        "worktree": None if latest is None else latest["worktree"],
        "deadline_at": None if latest is None else latest["deadline_at"],
        "blockers": blockers,
        "result": result,
    }


def command_control(args: argparse.Namespace) -> int:
    request = load_control_request(args.request_file)
    now = request["now"]
    now_value = parse_utc(now, "control now")
    run_dir, _, _ = workflow_paths(args.repo_root, args.run_id)
    tracker_by_issue = {item["issue"]: item for item in request["tracker"]}
    worktree_by_issue = {item["issue"]: item for item in request["worktrees"]}

    def control(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert state is not None
        if now_value < parse_utc(state["updated_at"], "run update time"):
            raise WorkflowError("control time must not move backward")

        # Validate every ledger-dependent observation before deriving or applying
        # transitions.  Only an observation for the latest launch of the latest
        # attempt is current; older, valid identities are harmless stale notices.
        unavailable: set[tuple[int, int, int]] = set()
        for observation in request["owners"]:
            issue_state = state["issues"].get(str(observation["issue"]))
            if issue_state is None or observation["attempt"] > len(
                issue_state["attempts"]
            ):
                raise WorkflowError("unknown owner observation identity")
            attempt = issue_state["attempts"][observation["attempt"] - 1]
            if observation["launch"] > len(attempt["launches"]):
                raise WorkflowError("unknown owner observation identity")
            if (
                observation["attempt"] == len(issue_state["attempts"])
                and observation["launch"] == len(attempt["launches"])
            ):
                unavailable.add(
                    (
                        observation["issue"], observation["attempt"],
                        observation["launch"],
                    )
                )

        for issue, observation in worktree_by_issue.items():
            recorded = observation["recorded"]
            if recorded is None:
                continue
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or not issue_state["attempts"]:
                raise WorkflowError("recorded worktree has no ledger attempt")
            if recorded["path"] != issue_state["attempts"][-1]["worktree"]:
                raise WorkflowError("recorded worktree path does not match ledger")

        # Expiry is projected first.  The actual records are written only after
        # all proposals, replay exceptions and candidate exclusivity are valid.
        expiring: set[int] = set()
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None:
                continue
            if not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            if (
                latest["state"] in {"active", "handed_off"}
                and now_value >= parse_utc(latest["deadline_at"], "attempt deadline")
            ):
                expiring.add(latest["issue"])

        occupied = 0
        for issue_state in state["issues"].values():
            if not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            identity = (
                latest["issue"], latest["attempt"], len(latest["launches"])
            )
            if (
                latest["issue"] not in expiring
                and latest["state"] == "active"
                and identity not in unavailable
            ):
                occupied += 1
        capacity = max(0, request["max_parallel"] - occupied)

        proposals: list[dict[str, Any]] = []

        # D6 pass one: resumptions.  A handed-off attempt and a current owner
        # disappearance both release capacity before selection.
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if capacity <= 0 or issue in expiring or issue_state is None:
                continue
            latest = issue_state["attempts"][-1]
            identity = (issue, latest["attempt"], len(latest["launches"]))
            if not (
                latest["state"] == "handed_off"
                or (latest["state"] == "active" and identity in unavailable)
            ):
                continue
            if latest["state"] == "handed_off":
                validate_handoff_path(run_dir, latest["handoff_path"])
            observation = worktree_by_issue.get(issue)
            if (
                observation is None
                or observation["recorded"] is None
                or observation["recorded"]["state"] != "matching_issue_branch"
            ):
                raise WorkflowError(
                    "resume control action requires a matching recorded worktree observation"
                )
            proposals.append(
                {
                    "kind": "resume", "issue": issue,
                    "attempt": latest["attempt"], "path": latest["worktree"],
                    "uses_candidate": False,
                }
            )
            capacity -= 1

        def ready_for_new_work(issue: int) -> bool:
            tracker = tracker_by_issue[issue]
            return (
                tracker["state"] == "open"
                and not tracker["open_blockers"]
                and not tracker["decision_blockers"]
            )

        def retryable(latest: dict[str, Any], *, projected_expiry: bool) -> bool:
            return projected_expiry or (
                latest["state"] == "failed"
                and latest["result_source"] == "owner"
            ) or (
                latest["state"] == "stopped"
                and latest["result_source"] == "expiry"
            )

        # D6 pass two: retry once, or durably refuse the third attempt.
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or not ready_for_new_work(issue):
                continue
            latest = issue_state["attempts"][-1]
            if not retryable(latest, projected_expiry=issue in expiring):
                continue
            if latest["attempt"] >= 2:
                proposals.append(
                    {
                        "kind": "refuse", "issue": issue,
                        "attempt": latest["attempt"], "path": latest["worktree"],
                        "uses_candidate": False,
                    }
                )
                continue
            if capacity <= 0:
                continue
            observation = worktree_by_issue.get(issue)
            if observation is None:
                raise WorkflowError(
                    "retry control action requires a verified worktree observation"
                )
            if (
                observation["recorded"] is not None
                and observation["recorded"]["state"] == "matching_issue_branch"
            ):
                path = latest["worktree"]
                uses_candidate = False
            elif observation["candidate"] is not None:
                path = observation["candidate"]["path"]
                uses_candidate = True
            else:
                raise WorkflowError(
                    "retry control action requires a verified worktree observation"
                )
            proposals.append(
                {
                    "kind": "retry", "issue": issue, "attempt": 2,
                    "path": path, "uses_candidate": uses_candidate,
                }
            )
            capacity -= 1

        # D6 pass three: first spawns.
        for issue in request["issues"]:
            if capacity <= 0 or not ready_for_new_work(issue):
                continue
            issue_state = state["issues"].get(str(issue))
            if issue_state is not None and issue_state["attempts"]:
                continue
            observation = worktree_by_issue.get(issue)
            if observation is None or observation["candidate"] is None:
                raise WorkflowError(
                    "fresh control action requires an absent candidate worktree"
                )
            proposals.append(
                {
                    "kind": "spawn", "issue": issue, "attempt": 1,
                    "path": observation["candidate"]["path"],
                    "uses_candidate": True,
                }
            )
            capacity -= 1

        dispatch_proposals = [
            proposal for proposal in proposals
            if proposal["kind"] in CONTROL_DISPATCH_KINDS
        ]

        # D16 validates the complete accepted retry/spawn candidate set against
        # itself and every durable path before any launch is appended.
        selected_paths: dict[str, int] = {}
        durable_paths: dict[str, set[int]] = {}
        for issue_state in state["issues"].values():
            for attempt in issue_state["attempts"]:
                key = canonical_worktree_path(attempt["worktree"])
                durable_paths.setdefault(key, set()).add(attempt["issue"])
        for proposal in dispatch_proposals:
            if not proposal["uses_candidate"]:
                continue
            issue = proposal["issue"]
            key = canonical_worktree_path(proposal["path"])
            if key in selected_paths:
                raise WorkflowError("candidate worktree path is shared by accepted actions")
            if any(other_issue != issue for other_issue in durable_paths.get(key, set())):
                raise WorkflowError("candidate worktree path aliases another issue")
            selected_paths[key] = issue

        # D13 is the only case in which a durable issue may still present the
        # consumed absent-candidate fact.  It is valid solely for an actionless,
        # exact replay of the first active launch.
        actionless_replay = not dispatch_proposals
        proposal_by_issue = {proposal["issue"]: proposal for proposal in proposals}
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            observation = worktree_by_issue.get(issue)
            candidate = None if observation is None else observation["candidate"]
            if candidate is None:
                continue
            proposal = proposal_by_issue.get(issue)
            if (
                proposal is not None
                and proposal["kind"] == "retry"
                and proposal["uses_candidate"]
                and proposal["path"] == candidate["path"]
                and candidate["path"] != latest["worktree"]
            ):
                continue
            identity = (issue, latest["attempt"], len(latest["launches"]))
            replay = (
                actionless_replay
                and issue not in expiring
                and proposal is None
                and latest["state"] == "active"
                and identity not in unavailable
                and candidate["path"] == latest["worktree"]
                and len(latest["launches"]) == 1
                and latest["launches"][0]["at"] == now
                and latest["started_at"] == now
            )
            if not replay:
                raise WorkflowError(
                    "current control action requires a recorded worktree observation"
                )

        fresh_deadline = format_utc(
            now_value + timedelta(minutes=request["attempt_budget_minutes"])
        )
        deltas: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []

        refusal_issues = {
            proposal["issue"] for proposal in proposals
            if proposal["kind"] == "refuse"
        }
        for issue in request["issues"]:
            if issue not in expiring:
                continue
            issue_state = state["issues"][str(issue)]
            latest = issue_state["attempts"][-1]
            outcome = stop_attempt(
                latest, reason="attempt deadline expired", now=now, source="expiry"
            )
            issue_state["outcome"] = outcome
            if issue not in refusal_issues:
                deltas.append(
                    {
                        "issue": issue, "attempt": latest["attempt"],
                        "kind": "expired", "state": "stopped",
                    }
                )

        for proposal in proposals:
            issue = proposal["issue"]
            issue_state = state["issues"].get(str(issue))
            if proposal["kind"] == "resume":
                assert issue_state is not None
                attempt = issue_state["attempts"][-1]
                attempt["state"] = "active"
                attempt["launch_kind"] = "resume"
                attempt["launches"].append(
                    {
                        "kind": "resume", "owner": attempt["owner"],
                        "worktree": attempt["worktree"], "at": now,
                    }
                )
                delta_kind = "resumed"
                action_kind = "resume"
            elif proposal["kind"] == "retry":
                assert issue_state is not None
                attempt = new_control_attempt(
                    issue=issue, attempt_number=2, worktree=proposal["path"],
                    now=now, deadline_at=fresh_deadline,
                )
                issue_state["attempts"].append(attempt)
                issue_state["outcome"] = None
                delta_kind = "retried"
                action_kind = "retry"
            elif proposal["kind"] == "spawn":
                attempt = new_control_attempt(
                    issue=issue, attempt_number=1, worktree=proposal["path"],
                    now=now, deadline_at=fresh_deadline,
                )
                state["issues"][str(issue)] = {
                    "issue": issue, "attempts": [attempt], "outcome": None,
                }
                delta_kind = "spawned"
                action_kind = "spawn"
            else:
                assert proposal["kind"] == "refuse" and issue_state is not None
                latest = issue_state["attempts"][-1]
                worktrees = ", ".join(
                    attempt["worktree"] for attempt in issue_state["attempts"][:2]
                )
                result = terminal_result(
                    issue, "failed",
                    f"Fresh retry refused after attempts 1 and 2; worktrees: {worktrees}",
                )
                latest["state"] = "failed"
                latest["result"] = result
                latest["finished_at"] = finish_time(latest, now)
                latest["result_source"] = "refused"
                issue_state["outcome"] = copy.deepcopy(result)
                deltas.append(
                    {
                        "issue": issue, "attempt": latest["attempt"],
                        "kind": "retry_refused", "state": "failed",
                    }
                )
                continue

            launch_ordinal = len(attempt["launches"])
            deltas.append(
                {
                    "issue": issue, "attempt": attempt["attempt"],
                    "kind": delta_kind, "state": "active",
                }
            )
            actions.append(
                {
                    "id": f"{issue}:{attempt['attempt']}:{launch_ordinal}",
                    "kind": action_kind,
                    "issue": issue,
                    "attempt": attempt["attempt"],
                    "owner": attempt["owner"],
                    "worktree": attempt["worktree"],
                    "handoff_path": attempt["handoff_path"],
                    "deadline_at": attempt["deadline_at"],
                }
            )

        changed = bool(expiring or proposals)
        if changed:
            state["updated_at"] = now

        summaries = [
            control_summary(
                issue=issue,
                tracker=tracker_by_issue[issue],
                issue_state=state["issues"].get(str(issue)),
            )
            for issue in request["issues"]
        ]
        deadlines = []
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None:
                continue
            if not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            if latest["state"] in {"active", "handed_off"}:
                deadlines.append(latest["deadline_at"])
        next_deadline = min(deadlines, key=lambda value: parse_utc(value)) if deadlines else None

        pending_external = False
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            tracker = tracker_by_issue[issue]
            if issue_state is None or not issue_state["attempts"]:
                if tracker["state"] != "closed":
                    pending_external = True
                continue
            latest = issue_state["attempts"][-1]
            if (
                tracker["state"] == "open"
                and retryable(latest, projected_expiry=False)
                and latest["attempt"] < 2
            ):
                pending_external = True

        if next_deadline is None and not pending_external:
            actions.append({"id": "finalize", "kind": "finalize"})
        elif next_deadline is None:
            actions.append(
                {
                    "id": "wait:external",
                    "kind": "wait",
                    "wake_on": ["owner_notification", "tracker_change"],
                    "deadline_at": None,
                }
            )
        else:
            actions.append(
                {
                    "id": f"wait:{next_deadline}",
                    "kind": "wait",
                    "wake_on": [
                        "owner_notification", "tracker_change", "deadline"
                    ],
                    "deadline_at": next_deadline,
                }
            )
        response = {
            "interface_version": CONTROL_INTERFACE_VERSION,
            "run_id": args.run_id,
            "now": now,
            "summaries": summaries,
            "deltas": deltas,
            "actions": actions,
            "next_deadline": next_deadline,
        }
        return response, changed

    response = transact(args.repo_root, args.run_id, control)
    print_json(response)
    return 0


def load_result_file(path_value: str, issue: int) -> dict[str, Any]:
    try:
        with Path(path_value).open(encoding="utf-8") as source:
            value = json.load(source)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid result file JSON: {error}") from error
    return validate_result(value, expected_issue=issue)


def command_progress(args: argparse.Namespace) -> int:
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)
    phase_inputs = {
        "turn_count": args.turn_count,
        "context_tokens": args.context_tokens,
        "turn_ceiling": args.turn_ceiling,
        "context_ceiling": args.context_ceiling,
        "turn_headroom": args.turn_headroom,
        "context_headroom": args.context_headroom,
        "next_needs_context": args.next_needs_context,
        "artifacts_sufficient": args.artifacts_sufficient,
        "remainder_self_contained": args.remainder_self_contained,
    }
    validate_phase_inputs(phase_inputs)
    action = select_phase_action(**phase_inputs)
    if args.handoff_path is not None and action != "handoff":
        raise WorkflowError("handoff path is only valid for a handoff action")
    run_dir, _, _ = workflow_paths(args.repo_root, args.run_id)

    def progress(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert state is not None
        issue_state = state["issues"].get(str(args.issue))
        if issue_state is None:
            raise WorkflowError(f"unknown issue identity: {args.issue}")
        if args.attempt > len(issue_state["attempts"]):
            raise WorkflowError(
                f"unknown attempt identity: issue {args.issue} attempt {args.attempt}"
            )
        attempt = issue_state["attempts"][args.attempt - 1]
        if attempt["state"] != "active":
            raise WorkflowError("progress requires an active attempt")
        if args.phase < attempt["phase"]:
            raise WorkflowError("phase must not move backward")
        if now_value < parse_utc(attempt["last_progress_at"], "attempt progress time"):
            raise WorkflowError("progress time must not move backward")
        if now_value >= parse_utc(attempt["deadline_at"], "attempt deadline"):
            raise WorkflowError("cannot record progress at or after attempt deadline")

        handoff_path = None
        if args.handoff_path is not None:
            handoff_path = validate_handoff_path(run_dir, args.handoff_path)
        attempt["phase"] = args.phase
        attempt["last_progress_at"] = now
        attempt["phase_action"] = action
        attempt["phase_inputs"] = copy.deepcopy(phase_inputs)
        if handoff_path is not None:
            attempt["state"] = "handed_off"
            attempt["handoff_path"] = handoff_path
        state["updated_at"] = now
        return attempt, True

    persisted = transact(args.repo_root, args.run_id, progress)
    print_json(persisted)
    return 0


def command_finish(args: argparse.Namespace) -> int:
    """Record an owner's reported terminal result for one attempt.

    A finish at or after the attempt budget's ``deadline_at`` records the reported
    result rather than a synthetic expiry: the wall clock bounds how long an owner
    may keep working, not whether the work it finished is real. The stopped record
    that ``control`` writes when the attempt budget runs out is therefore provisional
    — ``result_source == "expiry"`` on the issue's latest attempt, and only there, is
    overwritten by the owner's own report.
    """
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)
    result = load_result_file(args.result_file, args.issue)

    def finish(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert state is not None
        issue_state = state["issues"].get(str(args.issue))
        if issue_state is None:
            raise WorkflowError(f"unknown issue identity: {args.issue}")
        if args.attempt > len(issue_state["attempts"]):
            raise WorkflowError(
                f"unknown attempt identity: issue {args.issue} attempt {args.attempt}"
            )
        attempt = issue_state["attempts"][args.attempt - 1]
        if result["state"] in {"stopped", "failed"}:
            result["notes"] = retain_worktree(result["notes"], attempt["worktree"])
        if now_value < parse_utc(attempt["last_progress_at"], "attempt progress time"):
            raise WorkflowError("finish time must not move backward")
        existing = attempt["result"]
        outcome = issue_state["outcome"]
        if existing == result and outcome == result:
            return result, False
        if (
            args.attempt == len(issue_state["attempts"])
            and attempt["result_source"] == "expiry"
            and outcome == existing
        ):
            attempt["state"] = result["state"]
            attempt["result"] = copy.deepcopy(result)
            attempt["finished_at"] = now
            attempt["result_source"] = "owner"
            issue_state["outcome"] = copy.deepcopy(result)
            state["updated_at"] = now
            return result, True
        if existing is not None or outcome is not None:
            raise WorkflowError(
                f"conflicting terminal result for issue {args.issue} attempt {args.attempt}"
            )
        if attempt["state"] != "active":
            raise WorkflowError("finish requires an active attempt")
        attempt["state"] = result["state"]
        attempt["result"] = copy.deepcopy(result)
        attempt["finished_at"] = now
        attempt["result_source"] = "owner"
        issue_state["outcome"] = copy.deepcopy(result)
        state["updated_at"] = now
        return result, True

    persisted = transact(args.repo_root, args.run_id, finish)
    print_json(persisted)
    return 0


def print_json(value: Any) -> None:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflow-state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_run_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--repo-root", required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--now", required=True)

    init_run = subparsers.add_parser("init-run")
    add_run_arguments(init_run)
    init_run.set_defaults(handler=command_init_run)

    control = subparsers.add_parser("control")
    control.add_argument("--repo-root", required=True)
    control.add_argument("--run-id", required=True)
    control.add_argument("--request-file", required=True)
    control.set_defaults(handler=command_control)

    finish = subparsers.add_parser("finish")
    add_run_arguments(finish)
    finish.add_argument("--issue", required=True, type=positive_int)
    finish.add_argument("--attempt", required=True, type=positive_int)
    finish.add_argument("--result-file", required=True)
    finish.set_defaults(handler=command_finish)

    progress = subparsers.add_parser("progress")
    add_run_arguments(progress)
    progress.add_argument("--issue", required=True, type=positive_int)
    progress.add_argument("--attempt", required=True, type=positive_int)
    progress.add_argument("--phase", required=True, type=nonnegative_int)
    progress.add_argument("--turn-count", type=nonnegative_int)
    progress.add_argument("--context-tokens", type=nonnegative_int)
    progress.add_argument("--turn-ceiling", type=nonnegative_int, default=120)
    progress.add_argument("--context-ceiling", type=nonnegative_int, default=150000)
    progress.add_argument("--turn-headroom", type=nonnegative_int, default=2)
    progress.add_argument("--context-headroom", type=nonnegative_int, default=10000)
    progress.add_argument("--next-needs-context", required=True, type=literal_boolean)
    progress.add_argument("--artifacts-sufficient", required=True, type=literal_boolean)
    progress.add_argument(
        "--remainder-self-contained", required=True, type=literal_boolean
    )
    progress.add_argument("--handoff-path")
    progress.set_defaults(handler=command_progress)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (WorkflowError, OSError) as error:
        print(f"workflow-state: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
