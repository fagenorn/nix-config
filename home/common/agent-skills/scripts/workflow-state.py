#!/usr/bin/env python3

import argparse
import copy
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable


SCHEMA_VERSION = 2
PRIOR_SCHEMA_VERSION = SCHEMA_VERSION - 1
CONTROL_INTERFACE_VERSION = 1
DIRECT_OWNER_INTERFACE_VERSION = 1
ATTEMPT_STATES = frozenset(
    {"active", "handed_off", "suspended", "stopped", "failed", "merged"}
)
RESULT_STATES = frozenset({"merged", "stopped", "failed"})
RESULT_SOURCES = frozenset({"owner", "expiry", "superseded", "refused", "stalled"})
SYNTHETIC_RESULT_SOURCES = frozenset({"expiry", "stalled"})
BLOCKED_ON_VALUES = frozenset(
    {"usage_limit", "transport", "human_gate", "external", "unknown"}
)
OWNER_BLOCKED_ON_VALUES = BLOCKED_ON_VALUES - {"unknown"}
AUTO_RESUMABLE_BLOCKED_ON = frozenset({"usage_limit", "transport", "unknown"})
STALL_LIMIT = 3
RESULT_FIELDS = (
    "issue",
    "state",
    "pr_url",
    "merge_sha",
    "issue_closed",
    "discussion_items",
    "detail_state",
    "report_path",
    "notes",
)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MERGE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIRECT_RUN_ID_PATTERN = re.compile(r"^direct-([1-9][0-9]*)-([0-9]{6})$")
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
    {"schema_version", "run_id", "created_at", "updated_at", "prior_run", "issues"}
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
        "blocked_on",
        "suspend_phase",
        "stalled_resumes",
    }
)
SUSPENSION_DEFAULTS = {
    "blocked_on": None,
    "suspend_phase": None,
    "stalled_resumes": 0,
}
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
DIRECT_OWNER_REQUEST_FIELDS = frozenset(
    {
        "interface_version",
        "issue",
        "now",
        "attempt_budget_minutes",
        "new_run",
        "owner_unavailable",
        "tracker",
        "worktree",
        "forge",
    }
)
FORGE_OBSERVATION_FIELDS = frozenset({"state", "url", "merge_sha"})
FORGE_STATES = frozenset({"none", "open", "closed", "merged"})
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
        "blocked_on",
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
        "suspended",
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
    if value["detail_state"] not in {"none", "present", "unpublished"}:
        raise WorkflowError("invalid terminal result detail_state")
    if value["report_path"] is not None and not isinstance(value["report_path"], str):
        raise WorkflowError("invalid terminal result report_path: expected string or null")
    if not isinstance(value["notes"], str):
        raise WorkflowError("invalid terminal result notes: expected string")
    return {field: copy.deepcopy(value[field]) for field in RESULT_FIELDS}


def artifact_budget_paths() -> tuple[list[str], Path | None]:
    """Resolve the Task-1 CLI and its repository/installed policy."""

    def trusted_policy(path: Path) -> Path | None:
        """Resolve a policy path for an explicit ``--policy`` argument.

        artifact-budget resolves only its own default policy path; an explicit
        ``--policy`` symlink is refused by its ``O_NOFOLLOW`` read. The installed
        policy is a store symlink under home-manager, so pass the resolved target.
        """
        try:
            return path.resolve(strict=True)
        except (OSError, RuntimeError):
            return None

    script_dir = Path(__file__).resolve().parent
    source_module = script_dir / "artifact_budget.py"
    source_policy = script_dir.parent / "artifact-budget-policy.json"
    if source_module.is_file() and source_policy.is_file():
        return [sys.executable, str(source_module)], trusted_policy(source_policy)
    installed_cli = Path(__file__).parent / "artifact-budget"
    installed_policy = Path(__file__).parent.parent / "share/artifact-budget-policy.json"
    if not installed_cli.is_file():
        installed_cli = Path.home() / ".agents/bin/artifact-budget"
    return [str(installed_cli)], (
        trusted_policy(installed_policy) if installed_policy.is_file() else None
    )


def artifact_budget_validate(
    command: str,
    input_path: Path | None = None,
    *,
    boundary: str | None = None,
    input_bytes: bytes | None = None,
) -> dict[str, Any]:
    if (input_path is None) == (input_bytes is None):
        raise WorkflowError("artifact-budget validation requires exactly one input")
    argv, policy = artifact_budget_paths()
    argv.append(command)
    if boundary is not None:
        argv.extend(("--boundary", boundary))
    argv.extend(("--input", "-" if input_bytes is not None else str(input_path)))
    if policy is not None:
        argv.extend(("--policy", str(policy)))
    completed = subprocess.run(argv, input=input_bytes, capture_output=True, check=False)
    if completed.returncode != 0 or not completed.stdout:
        raise WorkflowError(f"artifact-budget {command} rejected the terminal result")
    try:
        canonical = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkflowError(f"artifact-budget {command} returned invalid canonical JSON") from error
    if not isinstance(canonical, dict):
        raise WorkflowError(f"artifact-budget {command} returned a non-object")
    return canonical


def validate_ship_summary_value(value: dict[str, Any]) -> dict[str, Any]:
    wire = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return artifact_budget_validate(
        "validate-report", boundary="ship-summary", input_bytes=wire
    )


def validate_launch_event(value: Any, *, owner: str, worktree: str) -> None:
    if not isinstance(value, dict) or set(value) != LAUNCH_FIELDS:
        raise WorkflowError("invalid launch event")
    if not isinstance(value["kind"], str) or value["kind"] not in {"fresh", "resume"}:
        raise WorkflowError("invalid launch kind")
    if value["owner"] != owner or value["worktree"] != worktree:
        raise WorkflowError("invalid launch identity")
    parse_utc(value["at"], "launch time")


def is_reserved_direct_run_id(run_id: str) -> bool:
    """Return whether ``run_id`` is owned exclusively by direct-owner."""
    match = DIRECT_RUN_ID_PATTERN.fullmatch(run_id)
    return match is not None and int(match.group(2)) >= 1


def select_phase_action(
    *,
    run_id: str,
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
    """Select the phase-boundary action from run identity and phase inputs.

    The phase budget is the turn and context ceilings with their headrooms; this
    function never sees the attempt budget's wall clock, and ``delegate`` does not
    reset it. Reserved module-owned direct runs select a self-contained remainder
    first, then an eligible ``fresh_start``, known near-ceiling usage, work that
    needs no context, and otherwise ``continue``. Every non-direct run retains the
    complete order: eligible ``fresh_start``, known near-ceiling usage, measured
    self-contained delegation, work that needs no context, then ``continue``.

    Unmeasurable usage is not a budget signal. A harness that exposes no
    authoritative context-token count would otherwise pin every non-direct run to
    ``handoff`` at its first phase gate, so an unknown count only withholds
    ``delegate`` -- which still requires usage measured below both ceilings.
    """
    if is_reserved_direct_run_id(run_id):
        if remainder_self_contained:
            return "delegate"
        if not next_needs_context and artifacts_sufficient:
            return "fresh_start"
        if (
            turn_count is not None
            and turn_count >= turn_ceiling - turn_headroom
        ) or (
            context_tokens is not None
            and context_tokens >= context_ceiling - context_headroom
        ):
            return "handoff"
        if not next_needs_context:
            return "handoff"
        return "continue"

    if not next_needs_context and artifacts_sufficient:
        return "fresh_start"
    if (
        turn_count is not None
        and turn_count >= turn_ceiling - turn_headroom
    ) or (
        context_tokens is not None
        and context_tokens >= context_ceiling - context_headroom
    ):
        return "handoff"
    if (
        remainder_self_contained
        and turn_count is not None
        and context_tokens is not None
    ):
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


def validate_attempt(
    value: Any, *, issue: int, expected_number: int, run_id: str
) -> None:
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
    if value["state"] in {"active", "handed_off", "suspended"}:
        if result is not None:
            raise WorkflowError("nonterminal attempt must not carry a terminal result")
    elif result is None or result["state"] != value["state"]:
        raise WorkflowError("terminal attempt state and result must match")
    if value["state"] == "suspended":
        if (
            not isinstance(value["blocked_on"], str)
            or value["blocked_on"] not in BLOCKED_ON_VALUES
        ):
            raise WorkflowError("invalid suspended attempt cause")
    elif value["blocked_on"] is not None:
        raise WorkflowError("only a suspended attempt carries a suspension cause")
    if value["suspend_phase"] is not None:
        require_plain_int(value["suspend_phase"], "attempt suspend phase")
    require_plain_int(value["stalled_resumes"], "attempt stalled resumes")
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
        if select_phase_action(run_id=run_id, **phase_inputs) != value["phase_action"]:
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
    prior_run = value["prior_run"]
    if prior_run is not None:
        if not isinstance(prior_run, str) or not RUN_ID_PATTERN.fullmatch(prior_run):
            raise WorkflowError("invalid prior run identity")
        if prior_run == run_id:
            raise WorkflowError("run cannot precede itself")
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
            validate_attempt(
                attempt, issue=issue, expected_number=number, run_id=run_id
            )
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


def resolve_repo_root(repo_root_value: str) -> Path:
    supplied_root = Path(repo_root_value).absolute()
    root_status = path_status(supplied_root)
    if root_status is None:
        raise WorkflowError("repository root does not exist")
    if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
        raise WorkflowError("repository root must be a non-symlink directory")
    return supplied_root.resolve(strict=True)


def ensure_workflows_directory(repo_root: Path) -> Path:
    workflows_dir = repo_root / ".superpowers" / "workflows"
    ensure_directory(repo_root / ".superpowers", ".superpowers")
    ensure_directory(workflows_dir, "workflows")
    return workflows_dir


def workflow_paths(repo_root_value: str, run_id: str) -> tuple[Path, Path, Path]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise WorkflowError("invalid run_id")
    repo_root = resolve_repo_root(repo_root_value)
    workflows_dir = ensure_workflows_directory(repo_root)
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


def open_stable_lock(
    lock_path: Path, label: str = "state lock", *, allow_missing: bool = True
) -> int:
    exists = require_regular_path(lock_path, label, allow_missing=allow_missing)
    if not exists and not allow_missing:
        raise WorkflowError(f"{label} does not exist")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if exists:
        descriptor = open_existing_regular(lock_path, label, os.O_RDWR)
    else:
        try:
            descriptor = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | no_follow,
                0o600,
            )
        except FileExistsError:
            descriptor = open_existing_regular(lock_path, label, os.O_RDWR)
        try:
            verify_open_file(lock_path, descriptor, label)
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


def upgrade_state(value: Any) -> Any:
    """Fill the suspension fields and the lineage link into a prior-version
    ledger, in memory.

    Run and attempt records are validated against an exact field set, so a
    ledger written before the suspension model would otherwise stop loading the
    moment this helper is deployed — stranding every in-flight run. A
    prior-version ledger is upgraded here with the documented defaults and
    persists in the new shape on its next write; any other version is left for
    ``validate_state`` to reject (per D15).
    """
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != PRIOR_SCHEMA_VERSION
    ):
        return value
    issues = value.get("issues")
    if isinstance(issues, dict):
        for issue_value in issues.values():
            if not isinstance(issue_value, dict):
                continue
            attempts = issue_value.get("attempts")
            if not isinstance(attempts, list):
                continue
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                for field, default in SUSPENSION_DEFAULTS.items():
                    attempt.setdefault(field, default)
    value.setdefault("prior_run", None)
    value["schema_version"] = SCHEMA_VERSION
    return value


def read_locked_state(state_path: Path, run_id: str) -> dict[str, Any]:
    require_regular_path(state_path, "workflow state", allow_missing=False)
    try:
        descriptor = open_existing_regular(state_path, "workflow state", os.O_RDONLY)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            value = json.load(source)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid workflow state JSON: {error}") from error
    return validate_state(upgrade_state(value), run_id=run_id)


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


def phase_notes_maximum() -> int:
    _, policy_path = artifact_budget_paths()
    if policy_path is None:
        raise WorkflowError("artifact-budget policy is unavailable")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        maximum = policy["phase_reports"]["notes_max_characters"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise WorkflowError("artifact-budget policy is invalid") from error
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise WorkflowError("artifact-budget policy has an invalid notes limit")
    return maximum


def new_run_state(
    *,
    run_id: str,
    now: str,
    issues: dict[str, Any],
    prior_run: str | None = None,
) -> dict[str, Any]:
    """Create one run's durable state, linked to the run it succeeds.

    ``prior_run`` is the identity of the run this one continues — only the
    direct-owner ``new_run`` escape hatch has a predecessor, and recording it
    keeps an issue's history one readable chain instead of N unlinked run
    directories (per D5). The link always points at a lower direct sequence, so
    the chain cannot cycle.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "prior_run": prior_run,
        "issues": issues,
    }


def terminal_result(issue: int, state: str, notes: str) -> dict[str, Any]:
    if len(notes) > phase_notes_maximum():
        raise WorkflowError("generated terminal notes exceed the policy limit")
    return validate_ship_summary_value({
        "issue": issue,
        "state": state,
        "pr_url": None,
        "merge_sha": None,
        "issue_closed": False,
        "discussion_items": [],
        "detail_state": "none",
        "report_path": None,
        "notes": notes,
    })


def reconciled_result(issue: int, url: str, merge_sha: str) -> dict[str, Any]:
    """The terminal record a merged pull request writes into a stale ledger.

    Only what the forge itself observed is asserted: the issue is not claimed
    closed and no delivery detail is claimed present, because reconciliation
    saw a merge, not a report (per D3). That is also why this record is checked
    against the ledger's own result schema rather than the ship-summary
    boundary — the boundary is the contract for an owner's report, where a
    ``merged`` row means the owner also closed the issue and cleaned up.
    """
    return validate_result({
        "issue": issue,
        "state": "merged",
        "pr_url": url,
        "merge_sha": merge_sha,
        "issue_closed": False,
        "discussion_items": [],
        "detail_state": "none",
        "report_path": None,
        "notes": "reconciled from forge observation",
    }, expected_issue=issue)


def reconcile_merged_attempt(
    ledger_issue: dict[str, Any],
    attempt: dict[str, Any],
    *,
    forge: dict[str, Any],
    now: str,
) -> None:
    """Close out an attempt the forge has already merged.

    The ledger, not the forge, is what the next owner reads, so a merged pull
    request has to land in it before ownership is granted again — otherwise the
    stale record is rediscovered by hand, run after run. The record is marked
    ``superseded``: it was written by the lifecycle from an observation, not
    reported by an owner (per D3, D11).
    """
    result = reconciled_result(
        attempt["issue"], forge["url"], forge["merge_sha"]
    )
    attempt["state"] = "merged"
    attempt["blocked_on"] = None
    attempt["result"] = result
    attempt["finished_at"] = finish_time(attempt, now)
    attempt["result_source"] = "superseded"
    ledger_issue["outcome"] = copy.deepcopy(result)


def retain_worktree(notes: str, worktree: str, report_path: str | None = None) -> str:
    if worktree in notes:
        return notes
    suffix = f"worktree: {worktree}"
    maximum = phase_notes_maximum()
    if len(suffix) > maximum:
        raise WorkflowError("worktree path is too long for terminal notes")
    if not notes:
        return suffix
    separator = "; "
    if report_path is not None:
        combined = f"{notes}{separator}{suffix}"
        if len(combined) > maximum:
            raise WorkflowError("terminal notes cannot retain both detail and worktree paths")
        return combined
    prefix = notes[: maximum - len(separator) - len(suffix)].rstrip()
    return f"{prefix}{separator}{suffix}" if prefix else suffix


def finish_time(attempt: dict[str, Any], now: str) -> str:
    """Clamp a terminal finish instant to at least the attempt's own start.

    The terminal-writer policy receives an injected time which may precede the
    attempt it is closing. Clamping keeps the record truthful — the attempt ended
    no earlier than it began — and preserves the ``finished_at >= started_at``
    invariant for every later read of the run.
    """
    started_at = parse_utc(attempt["started_at"], "attempt start time")
    return now if parse_utc(now, "finish time") >= started_at else attempt["started_at"]


def stop_attempt(
    attempt: dict[str, Any], *, reason: str, now: str, source: str
) -> dict[str, Any]:
    """Stamp a terminal stopped record.

    ``source`` says who ended the attempt and must be a member of
    ``RESULT_SOURCES``; ``now`` is the already-formatted RFC3339 UTC instant at
    which the record was written. No writer passes ``expiry`` any more — an
    expired deadline suspends instead (per D2) — so a live ``expiry`` record only
    reaches this ledger from a pre-suspension run, where it stays at or after
    the attempt budget's ``deadline_at`` (per D15).
    """
    result = terminal_result(
        attempt["issue"], "stopped", f"{reason}; worktree: {attempt['worktree']}"
    )
    attempt["state"] = "stopped"
    attempt["result"] = result
    attempt["finished_at"] = finish_time(attempt, now)
    attempt["result_source"] = source
    attempt["blocked_on"] = None
    return result


def reentry_command(issue: int) -> str:
    """The single line that resumes one issue's run (per D14)."""
    return f"/from-issue {issue} --auto"


def suspend_attempt(attempt: dict[str, Any], *, blocked_on: str, now: str) -> bool:
    """Park an attempt at an environmental interruption without ending it.

    Quota walls, transport failures and human-only gates are not verdicts about
    the work, so they leave the attempt resumable: no result, no finish time, no
    result source, and no attempt consumed (per D2).

    Returns ``True`` when the attempt is now suspended. A suspension that would
    be the third consecutive one at the same recorded phase is a zombie loop, so
    the attempt is stopped with the synthetic ``stalled`` source instead and
    ``False`` is returned — the caller stashes that terminal record as the
    issue's outcome (per D8).
    """
    if blocked_on not in BLOCKED_ON_VALUES:
        raise WorkflowError("invalid suspension cause")
    phase = attempt["phase"]
    stalled_resumes = (
        attempt["stalled_resumes"] + 1 if attempt["suspend_phase"] == phase else 0
    )
    if stalled_resumes >= STALL_LIMIT:
        stop_attempt(
            attempt,
            reason="suspension stalled without phase progress",
            now=now,
            source="stalled",
        )
        return False
    attempt["state"] = "suspended"
    attempt["blocked_on"] = blocked_on
    attempt["suspend_phase"] = phase
    attempt["stalled_resumes"] = stalled_resumes
    return True


def attempt_deadline(now: str, attempt_budget_minutes: int) -> str:
    """The instant an attempt's wall-clock budget window closes."""
    try:
        deadline_value = parse_utc(now, "budget window start") + timedelta(
            minutes=attempt_budget_minutes
        )
    except OverflowError as error:
        raise WorkflowError("attempt deadline is out of range") from error
    return format_utc(deadline_value)


def resume_attempt(
    attempt: dict[str, Any], *, now: str, attempt_budget_minutes: int | None = None
) -> None:
    """Relaunch an attempt in place under its own identity.

    A resume appends a launch event, clears any suspension cause and flips the
    state back to ``active``. It consumes no attempt and moves no lineage, which
    is what makes it free to repeat (per D2, D5).

    ``attempt_budget_minutes`` re-bases the budget window, and the progress clock
    with it: a suspension resume passes the fresh full window D8 grants it, since
    an interruption may outlast the window the attempt started with. A resume
    inside the attempt's own live window — a handoff rollover, a dead-owner
    takeover — leaves it ``None`` and keeps the original deadline.

    ``suspend_phase`` and ``stalled_resumes`` deliberately survive a resume: they
    are the anti-zombie bound's memory across the suspend/resume cycle (per D8).
    """
    if attempt_budget_minutes is not None:
        attempt["deadline_at"] = attempt_deadline(now, attempt_budget_minutes)
        attempt["last_progress_at"] = now
    attempt["state"] = "active"
    attempt["blocked_on"] = None
    attempt["launch_kind"] = "resume"
    attempt["launches"].append({
        "kind": "resume",
        "owner": attempt["owner"],
        "worktree": attempt["worktree"],
        "at": now,
    })


def demote_expired_attempt(
    ledger_issue: dict[str, Any], attempt: dict[str, Any], *, now: str
) -> None:
    """Reap an attempt past its deadline into a resumable suspension.

    The reaper cannot know why the owner went silent, so the cause is ``unknown``
    and no issue outcome is written — an expired deadline bounds how long an
    owner may hold the issue, and says nothing about the work (per D2). Only the
    stall escalation inside ``suspend_attempt`` writes a terminal record, and
    that one is the issue's outcome (per D8).
    """
    if not suspend_attempt(attempt, blocked_on="unknown", now=now):
        ledger_issue["outcome"] = copy.deepcopy(attempt["result"])


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


def issue_branch_prefix(issue: int) -> str:
    """The stable head of one issue's branch name under ``branchNaming``.

    The pattern is ``issue-<num>-<slug>`` and the slug is the acquiring owner's
    to know, so the requirement names the prefix every candidate branch shares.
    """
    return f"issue-{issue}-"


def validate_forge_observation(value: Any) -> dict[str, Any]:
    """Check one issue branch's pull-request state as the owner observed it.

    A merge SHA is exactly what a merge produces, so it is required for
    ``merged`` and refused everywhere else; ``none`` means no pull request
    exists, which leaves nothing to carry a URL. Reconciliation writes this
    observation into the ledger permanently, so it is checked before it can.
    """
    observation = require_exact_fields(
        value, FORGE_OBSERVATION_FIELDS, "forge observation"
    )
    if (
        not isinstance(observation["state"], str)
        or observation["state"] not in FORGE_STATES
    ):
        raise WorkflowError("invalid forge state")
    for field in ("url", "merge_sha"):
        if observation[field] is not None and (
            not isinstance(observation[field], str) or not observation[field]
        ):
            raise WorkflowError(f"invalid forge {field}: expected string or null")
    if (observation["merge_sha"] is not None) != (observation["state"] == "merged"):
        raise WorkflowError("only a merged pull request carries a merge sha")
    if observation["merge_sha"] is not None and not MERGE_SHA_PATTERN.fullmatch(
        observation["merge_sha"]
    ):
        raise WorkflowError("invalid forge merge sha")
    if observation["state"] == "none" and observation["url"] is not None:
        raise WorkflowError("an absent pull request carries no url")
    if observation["state"] == "merged" and observation["url"] is None:
        raise WorkflowError("a merged pull request requires its url")
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


def load_json_request(path_value: str, label: str) -> Any:
    path = Path(path_value)
    if not path.is_absolute():
        raise WorkflowError("request file path must be absolute")
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid {label} JSON: {error}") from error
    except (OSError, UnicodeError) as error:
        raise WorkflowError(f"cannot read {label} file: {error}") from error
    return value


def load_control_request(path_value: str) -> dict[str, Any]:
    return validate_control_request(load_json_request(path_value, "control request"))


def validate_direct_owner_request(value: Any) -> dict[str, Any]:
    request = require_exact_fields(
        value, DIRECT_OWNER_REQUEST_FIELDS, "direct owner request"
    )
    if (
        type(request["interface_version"]) is not int
        or request["interface_version"] != DIRECT_OWNER_INTERFACE_VERSION
    ):
        raise WorkflowError("unsupported direct owner interface version")
    issue = require_plain_int(request["issue"], "direct owner issue", minimum=1)
    if not RUN_ID_PATTERN.fullmatch(f"direct-{issue}-000001"):
        raise WorkflowError("direct owner issue exceeds the run ID length limit")
    require_plain_int(
        request["attempt_budget_minutes"],
        "attempt_budget_minutes",
        minimum=1,
    )
    if not isinstance(request["now"], str):
        raise WorkflowError("invalid direct owner now: expected an RFC3339 UTC timestamp")
    request["now"] = format_utc(parse_utc(request["now"], "direct owner now"))
    for field in ("new_run", "owner_unavailable"):
        if type(request[field]) is not bool:
            raise WorkflowError(f"invalid {field}: expected boolean")
    if request["new_run"] and request["owner_unavailable"]:
        raise WorkflowError("new_run and owner_unavailable cannot both be true")
    if request["tracker"] is not None:
        tracker = validate_tracker_observation(request["tracker"])
        if tracker["issue"] != issue:
            raise WorkflowError("tracker observation does not match requested issue")
    if request["worktree"] is not None:
        worktree = validate_worktree_observation(request["worktree"])
        if worktree["issue"] != issue:
            raise WorkflowError("worktree observation does not match requested issue")
    if request["forge"] is not None:
        request["forge"] = validate_forge_observation(request["forge"])
    return request


def load_direct_owner_request(path_value: str) -> dict[str, Any]:
    return validate_direct_owner_request(
        load_json_request(path_value, "direct owner request")
    )


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


def reject_reserved_direct_run_id(run_id: str) -> None:
    if is_reserved_direct_run_id(run_id):
        raise WorkflowError("direct run identities are reserved for direct-owner")


def command_init_run(args: argparse.Namespace) -> int:
    reject_reserved_direct_run_id(args.run_id)
    now = format_utc(parse_utc(args.now, "--now"))

    def initialize(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        if state is not None:
            return state, False
        state = new_run_state(run_id=args.run_id, now=now, issues={})
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
        **SUSPENSION_DEFAULTS,
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
        "blocked_on": None if latest is None else latest["blocked_on"],
        "blockers": blockers,
        "result": result,
    }


def _apply_one_issue_policy(
    *,
    ledger_issue: dict[str, Any] | None,
    tracker: dict[str, Any] | None,
    worktree: dict[str, Any] | None,
    now: str,
    attempt_budget_minutes: int,
    current_owner_unavailable: bool,
    dispatch_permitted: bool,
    run_dir: Path,
    retained_worktree: str | None = None,
    human_directed: bool = False,
    forge: dict[str, Any] | None = None,
    require_forge: bool = False,
) -> dict[str, Any]:
    """Derive and apply the shared lifecycle policy for exactly one issue.

    ``require_forge`` says the caller must observe the issue branch's pull
    request before it may take or keep ownership, and ``forge`` carries that
    observation once it has. Only the acquiring direct owner is asked for it —
    it is the one that reads the forge anyway (per D3).

    Every caller drives an environmentally suspended attempt back to work
    through the recorded-worktree ladder: a quota wall, a transport failure or a
    silent owner is an interruption the retry itself survives, so re-entry alone
    clears it (per D2, D9). ``human_directed`` says a person asked for this
    re-entry, which is the only thing that clears a `human_gate`/`external`
    suspension — the orchestrated sweep leaves those parked and reports them.
    """
    if ledger_issue is not None:
        issue = ledger_issue["issue"]
    elif tracker is not None:
        issue = tracker["issue"]
    elif worktree is not None:
        issue = worktree["issue"]
    else:
        match = DIRECT_RUN_ID_PATTERN.fullmatch(run_dir.name)
        if match is None:
            raise WorkflowError("cannot derive issue identity for one-issue policy")
        issue = int(match.group(1))

    if tracker is not None and tracker["issue"] != issue:
        raise WorkflowError("tracker observation does not match ledger issue")
    if worktree is not None and worktree["issue"] != issue:
        raise WorkflowError("worktree observation does not match ledger issue")

    attempts = [] if ledger_issue is None else ledger_issue["attempts"]
    latest = attempts[-1] if attempts else None
    recorded_path = retained_worktree if latest is None else latest["worktree"]

    def validate_recorded_worktree() -> None:
        if worktree is None or worktree["recorded"] is None:
            return
        if recorded_path is None:
            raise WorkflowError("recorded worktree has no ledger attempt")
        if worktree["recorded"]["path"] != recorded_path:
            raise WorkflowError("recorded worktree path does not match ledger")

    def decision(
        operation: str, *, changed: bool = False,
        requirements: list[dict[str, Any]] | None = None,
        uses_candidate: bool = False, desired: str | None = None,
        attempt: dict[str, Any] | None = None, **projection: Any,
    ) -> dict[str, Any]:
        return {
            "operation": operation, "changed": changed,
            "issue_state": ledger_issue,
            "attempt": latest if attempt is None else attempt,
            "requirements": [] if requirements is None else requirements,
            "uses_candidate": uses_candidate,
            "desired": operation if desired is None else desired,
            **projection,
        }

    now_value = parse_utc(now, "policy now")
    expired = bool(
        latest is not None
        and latest["state"] in {"active", "handed_off"}
        and now_value >= parse_utc(latest["deadline_at"], "attempt deadline")
    )
    active_unexpired = bool(
        latest is not None and latest["state"] == "active" and not expired
    )
    handed_off = bool(
        latest is not None and latest["state"] == "handed_off" and not expired
    )
    suspended = bool(
        latest is not None
        and latest["state"] == "suspended"
        and (human_directed or latest["blocked_on"] in AUTO_RESUMABLE_BLOCKED_ON)
    )
    retryable = bool(
        latest is not None
        and (
            expired
            or (
                latest["state"] == "failed"
                and latest["result_source"] == "owner"
            )
            or (
                latest["state"] == "stopped"
                and latest["result_source"] == "expiry"
            )
        )
    )

    def forge_requirement() -> list[dict[str, Any]] | None:
        """The observation the caller still owes before it may take the issue."""
        if not require_forge or forge is not None:
            return None
        return [{"kind": "forge_pr", "path": issue_branch_prefix(issue)}]

    if current_owner_unavailable and not active_unexpired:
        raise WorkflowError("owner_unavailable is not applicable")

    if latest is not None and not (
        active_unexpired or handed_off or suspended or retryable
    ):
        return decision("terminal", expired=False)

    if forge is not None and forge["state"] == "merged" and latest is not None:
        # Reconciliation precedes ownership: whatever this request would have
        # earned, a merged pull request has already ended the work (per D3).
        assert ledger_issue is not None
        reconcile_merged_attempt(ledger_issue, latest, forge=forge, now=now)
        return decision("reconcile", changed=True, expired=False)

    if active_unexpired and not current_owner_unavailable:
        return decision("idle", expired=False)

    if active_unexpired or handed_off or suspended:
        assert latest is not None
        if not dispatch_permitted:
            return decision("idle", desired="resume", expired=False)
        if handed_off:
            validate_handoff_path(run_dir, latest["handoff_path"])
        unobserved_forge = forge_requirement()
        if unobserved_forge is not None:
            return decision(
                "observe", desired="resume", requirements=unobserved_forge,
                expired=False,
            )
        validate_recorded_worktree()
        recorded = None if worktree is None else worktree["recorded"]
        # A pause taken at Phase 0 predates the worktree: the attempt reserved a
        # path it never created, so "absent" is the reservation intact, not a
        # mismatch. That is true of any run id — an orchestrated Phase-0 handoff
        # would otherwise strand for want of a worktree it never had (per D7).
        absent_phase_zero_pause = bool(
            (handed_off or suspended)
            and latest["phase"] == 0
            and recorded is not None
            and recorded["state"] == "absent"
        )
        if (
            recorded is None
            or (
                recorded["state"] != "matching_issue_branch"
                and not absent_phase_zero_pause
            )
        ):
            return decision(
                "observe", desired="resume", requirements=[
                    {"kind": "recorded_worktree", "path": latest["worktree"]}
                ],
                expired=False,
            )
        resume_attempt(
            latest, now=now,
            attempt_budget_minutes=attempt_budget_minutes if suspended else None,
        )
        return decision("resume", changed=True, expired=False)

    needs_new_work = latest is None or retryable
    if needs_new_work and tracker is None:
        return decision(
            "observe", requirements=[{"kind": "tracker"}],
            desired="retry" if retryable else "spawn", expired=expired,
        )

    assert tracker is not None
    blockers = control_blockers(tracker)
    if tracker["state"] == "closed" or tracker["decision_blockers"] or tracker["open_blockers"]:
        changed = False
        if expired:
            assert latest is not None and ledger_issue is not None
            demote_expired_attempt(ledger_issue, latest, now=now)
            changed = True
        return decision(
            "terminal", changed=changed, expired=expired,
            tracker_reason=(
                "closed" if tracker["state"] == "closed"
                else "fogged" if tracker["decision_blockers"] else "blocked"
            ),
            blockers=blockers,
        )

    unobserved_forge = forge_requirement()
    if unobserved_forge is not None:
        return decision(
            "observe", requirements=unobserved_forge,
            desired="retry" if retryable else "spawn", expired=expired,
        )

    if retryable and latest is not None and latest["attempt"] >= 2:
        validate_recorded_worktree()
        if not dispatch_permitted:
            return decision("idle", desired="refuse", expired=expired)
        if expired:
            assert ledger_issue is not None
            demote_expired_attempt(ledger_issue, latest, now=now)
        worktrees = ", ".join(
            attempt["worktree"] for attempt in ledger_issue["attempts"][:2]
        )
        result = terminal_result(
            issue, "failed",
            f"Fresh retry refused after attempts 1 and 2; worktrees: {worktrees}",
        )
        latest["state"] = "failed"
        latest["blocked_on"] = None
        latest["result"] = result
        latest["finished_at"] = finish_time(latest, now)
        latest["result_source"] = "refused"
        ledger_issue["outcome"] = copy.deepcopy(result)
        return decision("refuse", changed=True, expired=expired)

    if not dispatch_permitted:
        if expired:
            assert latest is not None and ledger_issue is not None
            demote_expired_attempt(ledger_issue, latest, now=now)
            return decision(
                "idle", changed=True, desired="retry" if retryable else "spawn",
                expired=True,
            )
        return decision(
            "idle", desired="retry" if retryable else "spawn", expired=False,
        )

    selected_path: str | None = None
    uses_candidate = False
    if latest is None and retained_worktree is not None:
        validate_recorded_worktree()
        recorded = None if worktree is None else worktree["recorded"]
        if recorded is None:
            return decision(
                "observe", desired="spawn", requirements=[
                    {"kind": "recorded_worktree", "path": retained_worktree}
                ],
                expired=False,
            )
        if recorded["state"] == "matching_issue_branch":
            selected_path = retained_worktree
        elif worktree is not None and worktree["candidate"] is not None:
            selected_path = worktree["candidate"]["path"]
            uses_candidate = True
        else:
            return decision(
                "observe", desired="spawn",
                requirements=[{"kind": "candidate_worktree"}], expired=False,
            )
    elif latest is None:
        validate_recorded_worktree()
        candidate = None if worktree is None else worktree["candidate"]
        if candidate is None:
            return decision(
                "observe", desired="spawn",
                requirements=[{"kind": "candidate_worktree"}], expired=False,
            )
        selected_path = candidate["path"]
        uses_candidate = True
    else:
        validate_recorded_worktree()
        recorded = None if worktree is None else worktree["recorded"]
        candidate = None if worktree is None else worktree["candidate"]
        if recorded is None and candidate is None:
            return decision(
                "observe", desired="retry", requirements=[
                    {"kind": "recorded_worktree", "path": latest["worktree"]}
                ],
                expired=expired,
            )
        if recorded is not None and recorded["state"] == "matching_issue_branch":
            selected_path = latest["worktree"]
        elif candidate is not None:
            selected_path = candidate["path"]
            uses_candidate = True
        else:
            return decision(
                "observe", desired="retry",
                requirements=[{"kind": "candidate_worktree"}], expired=expired,
            )

    desired = "retry" if retryable else "spawn"
    if expired and latest is not None:
        assert ledger_issue is not None
        demote_expired_attempt(ledger_issue, latest, now=now)
    attempt_number = 2 if retryable else 1
    attempt = new_control_attempt(
        issue=issue, attempt_number=attempt_number, worktree=selected_path,
        now=now, deadline_at=attempt_deadline(now, attempt_budget_minutes),
    )
    if ledger_issue is None:
        ledger_issue = {"issue": issue, "attempts": [attempt], "outcome": None}
    elif retryable:
        ledger_issue["attempts"].append(attempt)
        ledger_issue["outcome"] = None
    else:
        ledger_issue["attempts"].append(attempt)
    return decision(
        desired, changed=True, attempt=attempt, uses_candidate=uses_candidate,
        path=selected_path, expired=expired,
    )


def command_control(args: argparse.Namespace) -> int:
    reject_reserved_direct_run_id(args.run_id)
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
                unavailable.add((
                    observation["issue"], observation["attempt"],
                    observation["launch"],
                ))

        def owner_is_unavailable(issue_state: dict[str, Any] | None) -> bool:
            if issue_state is None or not issue_state["attempts"]:
                return False
            latest = issue_state["attempts"][-1]
            identity = (latest["issue"], latest["attempt"], len(latest["launches"]))
            return latest["state"] == "active" and identity in unavailable

        for issue, observation in worktree_by_issue.items():
            recorded = observation["recorded"]
            if recorded is None:
                continue
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or not issue_state["attempts"]:
                raise WorkflowError("recorded worktree has no ledger attempt")
            if recorded["path"] != issue_state["attempts"][-1]["worktree"]:
                raise WorkflowError("recorded worktree path does not match ledger")

        analysis: dict[int, dict[str, Any]] = {}
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            analysis[issue] = _apply_one_issue_policy(
                ledger_issue=copy.deepcopy(issue_state),
                tracker=tracker_by_issue[issue],
                worktree=worktree_by_issue.get(issue),
                now=now,
                attempt_budget_minutes=request["attempt_budget_minutes"],
                current_owner_unavailable=owner_is_unavailable(issue_state),
                dispatch_permitted=False,
                run_dir=run_dir,
            )

        occupied = 0
        for issue_state in state["issues"].values():
            if not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            identity = (latest["issue"], latest["attempt"], len(latest["launches"]))
            if (
                latest["state"] == "active"
                and now_value < parse_utc(latest["deadline_at"], "attempt deadline")
                and identity not in unavailable
            ):
                occupied += 1
        capacity = max(0, request["max_parallel"] - occupied)

        planned: dict[int, dict[str, Any]] = {}
        proposal_order: list[int] = []

        def apply_policy(issue: int, dispatch_permitted: bool) -> dict[str, Any]:
            issue_state = state["issues"].get(str(issue))
            result = _apply_one_issue_policy(
                ledger_issue=copy.deepcopy(issue_state),
                tracker=tracker_by_issue[issue],
                worktree=worktree_by_issue.get(issue),
                now=now,
                attempt_budget_minutes=request["attempt_budget_minutes"],
                current_owner_unavailable=owner_is_unavailable(issue_state),
                dispatch_permitted=dispatch_permitted,
                run_dir=run_dir,
            )
            planned[issue] = result
            return result

        for issue in request["issues"]:
            if capacity <= 0 or analysis[issue]["desired"] != "resume":
                continue
            observation = worktree_by_issue.get(issue)
            if observation is None or observation["recorded"] is None:
                # The sweep resumes handoffs and suspensions that needed no
                # observation while they sat parked, so an issue the caller said
                # nothing about is a round it still owes: the summary reports the
                # pause and its worktree, and the next sweep resumes it. A
                # worktree observed as absent or mismatched stays a refusal (per
                # D9).
                continue
            result = apply_policy(issue, True)
            if result["operation"] == "observe":
                raise WorkflowError(
                    "resume control action requires a matching recorded worktree observation"
                )
            proposal_order.append(issue)
            capacity -= 1

        for issue in request["issues"]:
            desired = analysis[issue]["desired"]
            if desired == "refuse":
                apply_policy(issue, True)
                proposal_order.append(issue)
            elif desired == "retry":
                if capacity > 0:
                    result = apply_policy(issue, True)
                    if result["operation"] == "observe":
                        raise WorkflowError(
                            "retry control action requires a verified worktree observation"
                        )
                    proposal_order.append(issue)
                    capacity -= 1
                elif analysis[issue]["expired"]:
                    apply_policy(issue, False)
            elif analysis[issue]["expired"]:
                apply_policy(issue, False)

        for issue in request["issues"]:
            if capacity <= 0 or analysis[issue]["desired"] != "spawn":
                continue
            result = apply_policy(issue, True)
            if result["operation"] == "observe":
                raise WorkflowError(
                    "fresh control action requires an absent candidate worktree"
                )
            proposal_order.append(issue)
            capacity -= 1

        dispatch_results = [
            planned[issue] for issue in proposal_order
            if planned[issue]["operation"] in CONTROL_DISPATCH_KINDS
        ]
        selected_paths: dict[str, int] = {}
        durable_paths: dict[str, set[int]] = {}
        for issue_state in state["issues"].values():
            for attempt in issue_state["attempts"]:
                key = canonical_worktree_path(attempt["worktree"])
                durable_paths.setdefault(key, set()).add(attempt["issue"])
        for result in dispatch_results:
            if not result["uses_candidate"]:
                continue
            attempt = result["attempt"]
            issue = attempt["issue"]
            key = canonical_worktree_path(attempt["worktree"])
            if key in selected_paths:
                raise WorkflowError("candidate worktree path is shared by accepted actions")
            if any(other_issue != issue for other_issue in durable_paths.get(key, set())):
                raise WorkflowError("candidate worktree path aliases another issue")
            selected_paths[key] = issue

        actionless_replay = not dispatch_results
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            observation = worktree_by_issue.get(issue)
            candidate = None if observation is None else observation["candidate"]
            if candidate is None:
                continue
            result = planned.get(issue)
            if (
                result is not None
                and result["operation"] == "retry"
                and result["uses_candidate"]
                and result["attempt"]["worktree"] == candidate["path"]
                and candidate["path"] != latest["worktree"]
            ):
                continue
            identity = (issue, latest["attempt"], len(latest["launches"]))
            replay = (
                actionless_replay
                and not analysis[issue]["expired"]
                and (result is None or not result["changed"])
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

        for issue, result in planned.items():
            if result["changed"]:
                state["issues"][str(issue)] = result["issue_state"]

        deltas: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        for issue in request["issues"]:
            result = planned.get(issue)
            if (
                analysis[issue]["expired"]
                and result is not None
                and result["changed"]
                and result["operation"] != "refuse"
            ):
                number = analysis[issue]["attempt"]["attempt"]
                deltas.append({
                    "issue": issue,
                    "attempt": number,
                    "kind": "expired",
                    "state": state["issues"][str(issue)]["attempts"][number - 1][
                        "state"
                    ],
                })

        for issue in proposal_order:
            result = planned[issue]
            operation = result["operation"]
            attempt = result["attempt"]
            if operation == "refuse":
                deltas.append({
                    "issue": issue, "attempt": attempt["attempt"],
                    "kind": "retry_refused", "state": "failed",
                })
                continue
            delta_kind = {
                "spawn": "spawned", "resume": "resumed", "retry": "retried",
            }[operation]
            deltas.append({
                "issue": issue, "attempt": attempt["attempt"],
                "kind": delta_kind, "state": "active",
            })
            actions.append({
                "id": f"{issue}:{attempt['attempt']}:{len(attempt['launches'])}",
                "kind": operation,
                "issue": issue,
                "attempt": attempt["attempt"],
                "owner": attempt["owner"],
                "worktree": attempt["worktree"],
                "handoff_path": attempt["handoff_path"],
                "deadline_at": attempt["deadline_at"],
            })

        changed = any(result["changed"] for result in planned.values())
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
            if issue_state is None or not issue_state["attempts"]:
                continue
            latest = issue_state["attempts"][-1]
            if latest["state"] in {"active", "handed_off"}:
                deadlines.append(latest["deadline_at"])
        next_deadline = (
            min(deadlines, key=lambda value: parse_utc(value))
            if deadlines else None
        )

        # A wait must name the instant it ends. With no deadline armed there is
        # nothing left for this sweep to wake up for, so control renders the
        # summaries and returns to the caller instead of parking forever on a
        # notification that may never arrive (per D9, D12).
        if next_deadline is None:
            actions.append({"id": "finalize", "kind": "finalize"})
        else:
            actions.append({
                "id": f"wait:{next_deadline}", "kind": "wait",
                "wake_on": ["owner_notification", "tracker_change", "deadline"],
                "deadline_at": next_deadline,
            })
        return {
            "interface_version": CONTROL_INTERFACE_VERSION,
            "run_id": args.run_id,
            "now": now,
            "summaries": summaries,
            "deltas": deltas,
            "actions": actions,
            "next_deadline": next_deadline,
        }, changed

    response = transact(args.repo_root, args.run_id, control)
    print_json(response)
    return 0


def direct_run_is_terminal(issue_state: dict[str, Any]) -> bool:
    if not issue_state["attempts"]:
        return False
    latest = issue_state["attempts"][-1]
    if latest["state"] in {"active", "handed_off", "suspended"}:
        return False
    if (
        latest["state"] == "failed" and latest["result_source"] == "owner"
    ) or (
        latest["state"] == "stopped" and latest["result_source"] == "expiry"
    ):
        return False
    return True


def direct_observe(
    issue: int, run_id: str | None, requirements: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "interface_version": DIRECT_OWNER_INTERFACE_VERSION,
        "kind": "observe",
        "issue": issue,
        "run_id": run_id,
        "requirements": requirements,
    }


def direct_terminal(
    *, issue: int, run_id: str | None, source: str, reason: str,
    blockers: list[dict[str, Any]], result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replay one issue's terminal record to a direct owner.

    The envelope carries the re-entry line so the caller never composes it: a
    terminal replay is exactly where a human decides whether to re-enter, and
    the one command that does it is the same one everywhere (per D14).
    """
    return {
        "interface_version": DIRECT_OWNER_INTERFACE_VERSION,
        "kind": "terminal",
        "issue": issue,
        "run_id": run_id,
        "source": source,
        "reason": reason,
        "blockers": blockers,
        "result": copy.deepcopy(result),
        "reentry": reentry_command(issue),
    }


def direct_owner_response(
    repo_root: Path, run_id: str, attempt: dict[str, Any], operation: str
) -> dict[str, Any]:
    launch_kind = "resume" if operation == "resume" else operation
    return {
        "interface_version": DIRECT_OWNER_INTERFACE_VERSION,
        "kind": "owner",
        "ledger_repo_root": str(repo_root),
        "run_id": run_id,
        "issue": attempt["issue"],
        "attempt": attempt["attempt"],
        "owner": attempt["owner"],
        "action_id": (
            f"{attempt['issue']}:{attempt['attempt']}:{len(attempt['launches'])}"
        ),
        "launch_kind": launch_kind,
        "worktree": attempt["worktree"],
        "handoff_path": attempt["handoff_path"],
        "deadline_at": attempt["deadline_at"],
    }


def command_direct_owner(args: argparse.Namespace) -> int:
    request = load_direct_owner_request(args.request_file)
    issue = request["issue"]
    if not Path(args.repo_root).is_absolute():
        raise WorkflowError("repository root path must be absolute")
    repo_root = resolve_repo_root(args.repo_root)
    workflows_dir = ensure_workflows_directory(repo_root)
    issue_lock_path = workflows_dir / f".direct-{issue}.lock"
    issue_lock_descriptor = open_stable_lock(
        issue_lock_path, "direct issue lock", allow_missing=True
    )

    response: dict[str, Any]
    with os.fdopen(issue_lock_descriptor, "r+b") as issue_lock:
        fcntl.flock(issue_lock.fileno(), fcntl.LOCK_EX)
        with ExitStack() as retained_locks:
            prefix = f"direct-{issue}-"
            retained: list[tuple[int, str, Path, Path, dict[str, Any]]] = []
            claimed: list[tuple[int, str, Path]] = []
            for entry in os.scandir(workflows_dir):
                if not entry.name.startswith(prefix):
                    continue
                suffix = entry.name[len(prefix):]
                if len(suffix) != 6 or not suffix.isascii() or not suffix.isdecimal():
                    raise WorkflowError("malformed direct run namespace entry")
                sequence = int(suffix)
                if sequence < 1:
                    raise WorkflowError("malformed direct run namespace entry")
                run_id = entry.name
                run_dir = workflows_dir / run_id
                run_status = path_status(run_dir)
                if (
                    run_status is None
                    or stat.S_ISLNK(run_status.st_mode)
                    or not stat.S_ISDIR(run_status.st_mode)
                ):
                    raise WorkflowError(
                        "direct run entry must be a non-symlink directory"
                    )
                claimed.append((sequence, run_id, run_dir))

            for sequence, run_id, run_dir in sorted(claimed):
                lock_path = run_dir / "state.lock"
                state_path = run_dir / "state.json"
                require_regular_path(lock_path, "state lock", allow_missing=False)
                require_regular_path(state_path, "workflow state", allow_missing=False)
                lock_descriptor = open_stable_lock(
                    lock_path, "state lock", allow_missing=False
                )
                lock = retained_locks.enter_context(
                    os.fdopen(lock_descriptor, "r+b")
                )
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                state = read_locked_state(state_path, run_id)
                if set(state["issues"]) != {str(issue)}:
                    raise WorkflowError(
                        "direct run state must contain exactly the requested issue"
                    )
                retained.append(
                    (sequence, run_id, run_dir, state_path, state)
                )
            nonterminal = [
                item for item in retained
                if not direct_run_is_terminal(item[4]["issues"][str(issue)])
            ]
            if len(nonterminal) > 1:
                raise WorkflowError("multiple nonterminal direct runs are corrupt")
            if nonterminal and any(
                item[0] > nonterminal[0][0]
                and direct_run_is_terminal(item[4]["issues"][str(issue)])
                for item in retained
            ):
                raise WorkflowError("nonterminal direct run is below a newer terminal run")

            greatest = retained[-1] if retained else None
            selected = nonterminal[0] if nonterminal else greatest
            selected_is_terminal = bool(
                selected is not None
                and direct_run_is_terminal(selected[4]["issues"][str(issue)])
            )

            selected_attempts = (
                [] if selected is None
                else selected[4]["issues"][str(issue)]["attempts"]
            )
            if (
                request["new_run"]
                and selected_attempts
                and selected_attempts[-1]["state"] == "suspended"
            ):
                # A suspension is resumed in place and consumes no attempt, so
                # it must never become an escape hatch into run fan-out: the
                # re-entry command already reaches the work (per D5, D13).
                raise WorkflowError(
                    "new_run is not applicable: suspended attempt is resumable"
                )

            if request["new_run"]:
                if not retained or not selected_is_terminal or nonterminal:
                    raise WorkflowError("new_run is not applicable")
            elif request["owner_unavailable"] and (
                selected is None or selected_is_terminal
            ):
                raise WorkflowError("owner_unavailable is not applicable")

            if selected_is_terminal and not request["new_run"]:
                assert selected is not None
                issue_state = selected[4]["issues"][str(issue)]
                latest = issue_state["attempts"][-1]
                response = direct_terminal(
                    issue=issue, run_id=selected[1], source="lifecycle",
                    reason=latest["result"]["state"], blockers=[],
                    result=issue_state["outcome"],
                )
            else:
                retained_worktree = None
                prior_run = None
                if request["new_run"]:
                    assert greatest is not None
                    if greatest[0] >= 999999:
                        raise WorkflowError("direct run sequence exhausted")
                    run_sequence = greatest[0] + 1
                    terminal_issue = greatest[4]["issues"][str(issue)]
                    retained_worktree = terminal_issue["attempts"][-1]["worktree"]
                    prior_run = greatest[1]
                    run_id = f"direct-{issue}-{run_sequence:06d}"
                    run_dir = workflows_dir / run_id
                    state_path = run_dir / "state.json"
                    state = None
                    issue_state = None
                elif selected is None:
                    if retained:
                        raise WorkflowError("invalid direct run history")
                    run_id = f"direct-{issue}-000001"
                    run_dir = workflows_dir / run_id
                    state_path = run_dir / "state.json"
                    state = None
                    issue_state = None
                else:
                    _, run_id, run_dir, state_path, current_state = selected
                    state = copy.deepcopy(current_state)
                    issue_state = state["issues"][str(issue)]

                if issue_state is not None and issue_state["attempts"]:
                    latest = issue_state["attempts"][-1]
                    if (
                        latest["state"] == "active"
                        and parse_utc(request["now"], "direct owner now")
                        < parse_utc(latest["deadline_at"], "attempt deadline")
                        and not request["owner_unavailable"]
                    ):
                        raise WorkflowError("direct run has an active owner")
                    if (
                        parse_utc(request["now"], "direct owner now")
                        < parse_utc(state["updated_at"], "run update time")
                    ):
                        raise WorkflowError("direct owner time must not move backward")

                policy = _apply_one_issue_policy(
                    ledger_issue=issue_state,
                    tracker=request["tracker"],
                    worktree=request["worktree"],
                    now=request["now"],
                    attempt_budget_minutes=request["attempt_budget_minutes"],
                    current_owner_unavailable=request["owner_unavailable"],
                    dispatch_permitted=True,
                    run_dir=run_dir,
                    retained_worktree=retained_worktree,
                    human_directed=True,
                    forge=request["forge"],
                    require_forge=True,
                )
                operation = policy["operation"]
                if operation == "idle":
                    raise WorkflowError("direct run has an active owner")
                if operation == "observe":
                    observed_run_id = None
                    if selected is not None and not request["new_run"]:
                        observed_run_id = run_id
                    elif policy["requirements"] != [{"kind": "tracker"}]:
                        observed_run_id = run_id
                    response = direct_observe(
                        issue, observed_run_id, policy["requirements"]
                    )
                elif operation == "terminal" and "tracker_reason" in policy:
                    if policy["changed"]:
                        assert state is not None
                        state["issues"][str(issue)] = policy["issue_state"]
                        state["updated_at"] = request["now"]
                        validate_state(state, run_id=run_id)
                        atomic_write_state(run_dir, state_path, state)
                    response = direct_terminal(
                        issue=issue,
                        run_id=(run_id if state is not None else None),
                        source="tracker", reason=policy["tracker_reason"],
                        blockers=policy["blockers"], result=None,
                    )
                elif operation == "reconcile":
                    assert state is not None
                    state["issues"][str(issue)] = policy["issue_state"]
                    state["updated_at"] = request["now"]
                    validate_state(state, run_id=run_id)
                    atomic_write_state(run_dir, state_path, state)
                    response = direct_terminal(
                        issue=issue, run_id=run_id, source="lifecycle",
                        reason="merged", blockers=[],
                        result=policy["issue_state"]["outcome"],
                    )
                elif operation in {"spawn", "resume", "retry", "refuse"}:
                    if state is None:
                        ensure_gitignore(workflows_dir)
                        try:
                            run_dir.mkdir()
                        except FileExistsError as error:
                            raise WorkflowError(
                                "direct run directory appeared during allocation"
                            ) from error
                        new_lock_descriptor = open_stable_lock(
                            run_dir / "state.lock", "state lock", allow_missing=True
                        )
                        new_lock = retained_locks.enter_context(
                            os.fdopen(new_lock_descriptor, "r+b")
                        )
                        fcntl.flock(new_lock.fileno(), fcntl.LOCK_EX)
                        state = new_run_state(
                            run_id=run_id, now=request["now"],
                            issues={str(issue): policy["issue_state"]},
                            prior_run=prior_run,
                        )
                    else:
                        state["issues"][str(issue)] = policy["issue_state"]
                        state["updated_at"] = request["now"]
                    validate_state(state, run_id=run_id)
                    atomic_write_state(run_dir, state_path, state)
                    if operation == "refuse":
                        response = direct_terminal(
                            issue=issue, run_id=run_id, source="lifecycle",
                            reason="failed", blockers=[],
                            result=policy["issue_state"]["outcome"],
                        )
                    else:
                        response = direct_owner_response(
                            repo_root, run_id, policy["attempt"], operation
                        )
                else:
                    raise WorkflowError("invalid one-issue policy operation")

    print_json(response)
    return 0


def load_result_file(path_value: str, issue: int) -> dict[str, Any]:
    value = artifact_budget_validate(
        "validate-report", Path(path_value), boundary="ship-summary"
    )
    return validate_result(value, expected_issue=issue)


def validate_retained_detail(worktree: str, report_path: str) -> None:
    root = Path(worktree).resolve(strict=True)
    candidate = root / report_path
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as error:
        raise WorkflowError("unpublished detail is not beneath the recorded worktree") from error
    canonical = artifact_budget_validate("validate-detail-input", candidate)
    if not canonical.get("findings"):
        raise WorkflowError("unpublished detail must retain non-empty findings")


def validate_durable_detail(repo_root: str, report_path: str) -> None:
    root = Path(repo_root).resolve(strict=True)
    candidate = root / report_path
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as error:
        raise WorkflowError("durable detail is not beneath the repository root") from error
    argv, policy = artifact_budget_paths()
    argv.extend((
        "check", "--kind", "review-package", "--root", str(candidate),
        "--format", "json",
    ))
    if policy is not None:
        argv.extend(("--policy", str(policy)))
    completed = subprocess.run(argv, capture_output=True, check=False)
    if completed.returncode != 0:
        raise WorkflowError("durable detail is not a checker-valid review package")
    try:
        canonical = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkflowError("artifact-budget check returned invalid canonical JSON") from error
    if (not isinstance(canonical, dict)
            or canonical.get("kind") != "review-package"
            or canonical.get("status") != "within_budget"):
        raise WorkflowError("artifact-budget check returned an invalid review result")


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
    action = select_phase_action(run_id=args.run_id, **phase_inputs)
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


def command_suspend(args: argparse.Namespace) -> int:
    """Record an owner's graceful exit at an environmental interruption.

    The owner names the cause it can see (``unknown`` stays reserved for the
    reaper, which cannot); the envelope carries back the re-entry line that
    resumes the run, so callers never compose it themselves (per D2, D14).
    """
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)

    def suspend(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
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
            raise WorkflowError("only an active attempt can suspend")
        if now_value < parse_utc(attempt["last_progress_at"], "attempt progress time"):
            raise WorkflowError("suspend time must not move backward")
        suspended = suspend_attempt(attempt, blocked_on=args.blocked_on, now=now)
        state["updated_at"] = now
        if not suspended:
            issue_state["outcome"] = copy.deepcopy(attempt["result"])
            return attempt, True
        return {
            "kind": "suspended",
            "issue": attempt["issue"],
            "attempt": attempt["attempt"],
            "blocked_on": attempt["blocked_on"],
            "stalled_resumes": attempt["stalled_resumes"],
            "reentry": reentry_command(attempt["issue"]),
        }, True

    print_json(transact(args.repo_root, args.run_id, suspend))
    return 0


def command_finish(args: argparse.Namespace) -> int:
    """Record an owner's reported terminal result for one attempt.

    A finish at or after the attempt budget's ``deadline_at`` records the reported
    result rather than a synthetic expiry: the wall clock bounds how long an owner
    may keep working, not whether the work it finished is real. A *synthetic*
    record on the issue's latest attempt — one the lifecycle wrote about the
    environment (``expiry``, ``stalled``), not about the work — is therefore
    provisional and is replaced wholesale by the owner's own report, whatever it
    says. An ``owner``, ``refused`` or ``superseded`` record is a verdict and is
    never overwritten, which is where write-once means something (per D3, D11).
    Legacy ``expiry`` records only reach this ledger from a pre-suspension run
    (per D2, D15).
    """
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)
    result = load_result_file(args.result_file, args.issue)
    if result["detail_state"] == "present":
        assert isinstance(result["report_path"], str)
        validate_durable_detail(args.repo_root, result["report_path"])

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
        if result["detail_state"] == "unpublished":
            assert isinstance(result["report_path"], str)
            validate_retained_detail(attempt["worktree"], result["report_path"])
        if result["state"] in {"stopped", "failed"}:
            result["notes"] = retain_worktree(
                result["notes"], attempt["worktree"], result["report_path"]
            )
            normalized_result = validate_result(
                validate_ship_summary_value(result), expected_issue=args.issue
            )
            result.clear()
            result.update(normalized_result)
        if now_value < parse_utc(attempt["last_progress_at"], "attempt progress time"):
            raise WorkflowError("finish time must not move backward")
        existing = attempt["result"]
        outcome = issue_state["outcome"]
        if existing == result and outcome == result:
            return result, False
        if (
            args.attempt == len(issue_state["attempts"])
            and attempt["result_source"] in SYNTHETIC_RESULT_SOURCES
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

    direct_owner = subparsers.add_parser("direct-owner")
    direct_owner.add_argument("--repo-root", required=True)
    direct_owner.add_argument("--request-file", required=True)
    direct_owner.set_defaults(handler=command_direct_owner)

    finish = subparsers.add_parser("finish")
    add_run_arguments(finish)
    finish.add_argument("--issue", required=True, type=positive_int)
    finish.add_argument("--attempt", required=True, type=positive_int)
    finish.add_argument("--result-file", required=True)
    finish.set_defaults(handler=command_finish)

    suspend = subparsers.add_parser("suspend")
    add_run_arguments(suspend)
    suspend.add_argument("--issue", required=True, type=positive_int)
    suspend.add_argument("--attempt", required=True, type=positive_int)
    suspend.add_argument(
        "--blocked-on", required=True, choices=sorted(OWNER_BLOCKED_ON_VALUES)
    )
    suspend.set_defaults(handler=command_suspend)

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
