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
ATTEMPT_STATES = frozenset({"active", "handed_off", "stopped", "failed", "merged"})
RESULT_STATES = frozenset({"merged", "stopped", "failed"})
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
        "handoff_path",
        "phase",
        "last_progress_at",
        "phase_action",
        "phase_inputs",
    }
)
LAUNCH_FIELDS = frozenset({"kind", "owner", "worktree", "at"})


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
    if remainder_self_contained:
        return "delegate"
    if not next_needs_context and artifacts_sufficient:
        return "fresh_start"
    if turn_count is None or context_tokens is None:
        return "handoff"
    if (
        turn_count >= turn_ceiling - turn_headroom
        or context_tokens >= context_ceiling - context_headroom
    ):
        return "handoff"
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


def stop_attempt(attempt: dict[str, Any], *, reason: str) -> dict[str, Any]:
    result = terminal_result(
        attempt["issue"], "stopped", f"{reason}; worktree: {attempt['worktree']}"
    )
    attempt["state"] = "stopped"
    attempt["result"] = result
    return result


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
    print_json(state)
    return 0


def command_launch(args: argparse.Namespace) -> int:
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)
    worktree = str(Path(args.worktree).resolve(strict=False))
    run_dir, _, _ = workflow_paths(args.repo_root, args.run_id)
    if not args.owner:
        raise WorkflowError("owner must not be empty")

    def launch(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert state is not None
        issue_key = str(args.issue)
        issue_state = state["issues"].get(issue_key)
        if issue_state is None:
            issue_state = {"issue": args.issue, "attempts": [], "outcome": None}
            state["issues"][issue_key] = issue_state

        attempts = issue_state["attempts"]
        if attempts:
            latest = attempts[-1]
            same_identity = latest["owner"] == args.owner and latest["worktree"] == worktree
            if issue_state["outcome"] is not None:
                if same_identity or issue_state["outcome"]["state"] == "merged":
                    return issue_state["outcome"], False
            if latest["state"] == "handed_off":
                if not same_identity:
                    raise WorkflowError(
                        "handed-off attempt requires matching owner and worktree"
                    )
                if args.resume_handoff is None:
                    raise WorkflowError("handed-off attempt requires --resume-handoff")
                if args.resume_handoff != latest["handoff_path"]:
                    raise WorkflowError(
                        "resume handoff path does not match stored exact path"
                    )
                if now_value >= parse_utc(latest["deadline_at"], "attempt deadline"):
                    raise WorkflowError("cannot resume handoff after attempt deadline")
                validate_handoff_path(run_dir, args.resume_handoff)
                latest["state"] = "active"
                latest["launch_kind"] = "resume"
                latest["launches"].append(
                    {
                        "kind": "resume",
                        "owner": args.owner,
                        "worktree": worktree,
                        "at": now,
                    }
                )
                state["updated_at"] = now
                return latest, True
            if args.resume_handoff is not None:
                raise WorkflowError("attempt does not have a resumable handoff")
            if same_identity and latest["state"] == "active":
                if now_value >= parse_utc(latest["deadline_at"], "attempt deadline"):
                    outcome = stop_attempt(latest, reason="attempt deadline expired")
                    issue_state["outcome"] = outcome
                    state["updated_at"] = now
                    return outcome, True
                latest["launch_kind"] = "resume"
                latest["launches"].append(
                    {
                        "kind": "resume",
                        "owner": args.owner,
                        "worktree": worktree,
                        "at": now,
                    }
                )
                state["updated_at"] = now
                return latest, True

        if len(attempts) >= 2:
            worktrees = ", ".join(attempt["worktree"] for attempt in attempts[:2])
            notes = f"Fresh launch refused after attempts 1 and 2; worktrees: {worktrees}"
            failed = terminal_result(args.issue, "failed", notes)
            latest = attempts[-1]
            latest["state"] = "failed"
            latest["result"] = failed
            issue_state["outcome"] = failed
            state["updated_at"] = now
            return {
                "refused": True,
                "message": (
                    f"refusing fresh launch for issue {args.issue}: attempts 1 and 2 "
                    "already consumed"
                ),
            }, True

        prior_attempt = attempts[-1]["attempt"] if attempts else None
        if attempts and attempts[-1]["state"] in {"active", "handed_off"}:
            stop_attempt(attempts[-1], reason="superseded by fresh retry")
        issue_state["outcome"] = None
        attempt_number = len(attempts) + 1
        deadline = format_utc(now_value + timedelta(minutes=args.budget_minutes))
        event = {
            "kind": "fresh",
            "owner": args.owner,
            "worktree": worktree,
            "at": now,
        }
        attempt = {
            "issue": args.issue,
            "attempt": attempt_number,
            "owner": args.owner,
            "worktree": worktree,
            "started_at": now,
            "deadline_at": deadline,
            "state": "active",
            "launch_kind": "fresh",
            "launches": [event],
            "prior_attempt": prior_attempt,
            "result": None,
            "handoff_path": None,
            "phase": 0,
            "last_progress_at": now,
            "phase_action": None,
            "phase_inputs": None,
        }
        attempts.append(attempt)
        state["updated_at"] = now
        return attempt, True

    result = transact(args.repo_root, args.run_id, launch)
    if isinstance(result, dict) and result.get("refused") is True:
        print(result["message"], file=sys.stderr)
        return 3
    print_json(result)
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
        existing = attempt["result"]
        outcome = issue_state["outcome"]
        if existing is not None or outcome is not None:
            if existing == result and outcome == result:
                return result, False
            raise WorkflowError(
                f"conflicting terminal result for issue {args.issue} attempt {args.attempt}"
            )
        if attempt["state"] != "active":
            raise WorkflowError("finish requires an active attempt")
        if now_value >= parse_utc(attempt["deadline_at"], "attempt deadline"):
            expired = stop_attempt(attempt, reason="attempt deadline expired")
            issue_state["outcome"] = copy.deepcopy(expired)
            state["updated_at"] = now
            return expired, True
        attempt["state"] = result["state"]
        attempt["result"] = copy.deepcopy(result)
        issue_state["outcome"] = copy.deepcopy(result)
        state["updated_at"] = now
        return result, True

    persisted = transact(args.repo_root, args.run_id, finish)
    print_json(persisted)
    return 0


def command_reconcile(args: argparse.Namespace) -> int:
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)

    def reconcile(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert state is not None
        changed = False
        for issue_state in state["issues"].values():
            if issue_state["outcome"] is not None:
                continue
            for attempt in issue_state["attempts"]:
                if attempt["state"] != "active":
                    continue
                deadline = parse_utc(attempt["deadline_at"], "attempt deadline")
                if now_value >= deadline:
                    outcome = stop_attempt(attempt, reason="attempt deadline expired")
                    issue_state["outcome"] = outcome
                    changed = True
        if changed:
            state["updated_at"] = now
        return state, changed

    state = transact(args.repo_root, args.run_id, reconcile)
    print_json(state)
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

    launch = subparsers.add_parser("launch")
    add_run_arguments(launch)
    launch.add_argument("--issue", required=True, type=positive_int)
    launch.add_argument("--owner", required=True)
    launch.add_argument("--worktree", required=True)
    launch.add_argument("--budget-minutes", required=True, type=positive_int)
    launch.add_argument("--resume-handoff")
    launch.set_defaults(handler=command_launch)

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

    reconcile = subparsers.add_parser("reconcile")
    add_run_arguments(reconcile)
    reconcile.set_defaults(handler=command_reconcile)
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
