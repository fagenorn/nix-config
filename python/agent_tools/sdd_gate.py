"""`sdd-gate`: gate an sdd task's evidence, then render its dispatch brief (issue 353).

    sdd-gate review PLAN_FILE --skill-dir DIR --task N [--standards PATH ...]
        [--repo-root R --run-id I --action-id A --worker-id W]
    sdd-gate record PLAN_FILE --task N
    sdd-gate next PLAN_FILE --skill-dir DIR [--standards PATH ...]
        [--completed N [--parked K]] [--task M [--context-file PATH]] [--delivery-base SHA]
        [--repo-root R --run-id I --action-id A]

`next` needs at least one of `--completed` and `--task`, and takes both in one
call.

`review` runs seven steps in order and stops at the first that fails:
`ledger`, `release-worker`, `review-package`, `validate-report`,
`budget-check`, `metrics-match`, `render-brief`. It reads the task's base from
the sdd ledger, releases the worker `--worker-id` names (the implementer that
just returned; reviewers are never registered) when a lifecycle identity is
given, builds (or reuses) the review package for `base..HEAD`, checks the
package against the budget authority and writes the rendered reviewer brief
into the plan's workspace.

`record` writes the ownership evidence of finished task N into the plan's
forecast blocks, from the ledger and Git, and commits nothing (the controller
commits the two files). It runs three steps: `ledger` (tasks 1..N-1 are
complete, N is dispatched and not complete, and an earlier recorded head for N
is HEAD or the commit recording it), `worktree` (no tracked change
but the plan root and task N's member, and the task's base is a proper ancestor
of its head with the forecast's evidence head behind the base) and `record`
(the task's commits left every forecast block alone; each file holds its HEAD
or computed bytes and takes the computed ones; the ledger gains `Task N: recorded (head H)` once). The ready
object is `command`, `outcome`, `task`, `head_sha`, `paths` (root, member) and
`changed`, false when the files already hold the computed bytes. Refusals carry
gate `null`.

`next` closes task N and/or opens task M. It runs up to thirteen steps in order
and stops at the first that fails (a ledger that cannot be read or appended to
refuses at the step that needs it, and the delivery gate line's write refuses
at `metrics-match` with gate `failed`, not listed as passed): `ledger`,
`evidence` (the recording commit of the completed task, or of task M-1 for a
fresh `--task M`, is the one commit over the recorded head and commits the
computed bytes, and it is HEAD or HEAD's first-parent ancestor through a
metadata tail: single-parent commits touching only the proposed boundary's
process package and leaving every forecast block byte-identical, as
`review_forecast` accepts; refuses `failed`), `ledger-complete` (with `--completed`),
`mark-progress` (under an identity), `review-package`, `validate-report`,
`budget-check`, `metrics-match` (the cumulative delivery package, delivery
base to HEAD), then, with a fresh `--task M`, `projection` (project the
delivery with tasks 1..M-1 complete over HEAD; `decompose_required` or
`failed` ends the call before any dispatch), and with `--task`, `task-brief`,
`prepare-brief`, `register-worker` (under an identity) and `write-brief`. A
step that does not apply does not run. It appends the ledger's delivery base,
completion, delivery gate, projection gate and dispatch lines, each once, and
writes the implementer brief into the plan's workspace.

Stdout is one compact JSON object and a newline: the ready object (exit 0) or
the refusal object (exit 3 when the package must be decomposed, exit 2 for
every other refusal). An invalid invocation prints `sdd-gate: invalid
invocation` on stderr, nothing on stdout, and exits 2.

Every step is safe to repeat: a package is never deleted or overwritten, an
existing one is reused only for the same range with its saved report beside it,
the brief is replaced atomically, and releasing a released worker changes
nothing. `next --task` registers a fresh worker on every call, so it refuses
while the worker its earlier brief of that task names is still live. The command never resolves the project, reads the environment only
through `Path.home()` and reads Git only from the current checkout.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.review_budget import BudgetAuthority, BudgetError, describe
from agent_tools.review_forecast import ForecastError, forecast_block, history_commit, process_paths
from agent_tools.review_gate import (
    GateError, capture, plan_relative, project_argv, save_result, summarize,
)
from agent_tools.review_record import RangeError, RecordError, paths, recorded
from agent_tools.sdd_brief import (
    IMPLEMENTER_TEMPLATE, IMPLEMENTER_TOKENS, REVIEWER_TEMPLATE, REVIEWER_TOKENS, BriefError,
    plan_section, render, select_standards, standards_value, task_row, worker_block,
)
from agent_tools.siblings import sibling_argv

INVALID = "sdd-gate: invalid invocation\n"
DETAIL_LIMIT = 300
TAIL_LIMIT = 120
HEADER = re.compile(r"# SDD ledger — plan: (.+)")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
TASK_NUMBER = re.compile(r"[1-9][0-9]*")
WORKER_LINE = "Lifecycle worker: "
GLOBAL_CONSTRAINTS = "## Global Constraints"
TEST_SEAMS = "## Test seams"
STATES = ("complete", "decompose_required")
PRODUCER_EXIT = {"complete": 0, "decompose_required": 3}
# The budget metrics, in the order a brief names them, and the token each fills.
METRIC_KEYS = ("root_bytes", "total_bytes", "file_count", "largest_member_bytes")
COMPLETE_LINE = re.compile(r"Task ([1-9][0-9]*): complete \(.*\)")
PROJECTION_LINE = re.compile(
    r"Projection gate: ([0-9a-f]{40})\.\.([0-9a-f]{40}) through ([0-9]+) "
    + " ".join(rf"{key}=([0-9]+)" for key in METRIC_KEYS))


class InvocationError(Exception):
    """The command line is not a valid `sdd-gate` invocation."""


class Refusal(Exception):
    """One step refused: its name, a one-line detail, the gate it maps to and its report.

    `gate` is `decompose_required` or `failed` for the package steps and `None`
    for the others; `report` is the validated report object exactly when
    `gate` is `decompose_required`.
    """

    def __init__(self, step: str, detail: str, *, gate: str | None = None,
                 report: dict | None = None) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail
        self.gate = gate
        self.report = report


@dataclass(frozen=True)
class Ledger:
    """An sdd ledger: its workspace, `progress.md`, the lines read and the checkout's top level."""

    workspace: Path
    path: Path
    lines: tuple[str, ...]
    top: Path


@dataclass(frozen=True)
class Package:
    """A gated review package: the report's manifest path, its root and measured metrics."""

    manifest_root: str
    root: Path
    metrics: dict[str, int]
    authority: BudgetAuthority


@dataclass(frozen=True)
class Reads:
    """What step `ledger` of `next` reads: the delivery base and whether it is new, the base of the
    completed task and of the task to dispatch (`None` when not asked for or not recorded), the
    task whose recording step `evidence` checks (task, dispatched base, recorded head) and, for
    a re-dispatch, the projection the ledger already holds."""

    delivery_base: str
    new_base: bool
    completed_base: str | None
    dispatched: str | None
    evidence: tuple[int, str, str] | None
    projected: dict | None


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, check=False)


def _why(done: subprocess.CompletedProcess) -> str:
    """The tail of a failed child's stderr as `: <tail>` on one line, or `` when it said nothing."""
    tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-TAIL_LIMIT:]
    return f": {tail}" if tail else ""


def _strict_json(raw: bytes) -> object:
    """Parse `raw` as UTF-8 JSON, refusing duplicate keys and non-finite constants."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def _resolved(path: str, top: Path) -> str:
    """`os.path.realpath` of `path`, taken relative to `top` when it is not absolute."""
    return os.path.realpath(path if os.path.isabs(path) else top / path)


def open_ledger(plan: Path) -> Ledger:
    """Read the ledger of `plan`'s workspace and check that it is this plan's.

    The workspace is what `sdd-workspace <plan>` prints. The first ledger line
    must be `# SDD ledger — plan: <path>`, the path (relative to the checkout's
    top level when not absolute) naming `plan` by real path. Refuses with step
    `ledger` when the workspace cannot be resolved, the ledger cannot be read or
    another plan's header leads it.
    """
    try:
        found = _run(["sdd-workspace", str(plan)])
        shown = _run(["git", "rev-parse", "--show-toplevel"])
    except OSError as error:
        raise Refusal("ledger", f"cannot resolve the workspace: {error}") from None
    if found.returncode != 0 or not found.stdout.strip():
        raise Refusal("ledger", f"sdd-workspace failed (exit {found.returncode}){_why(found)}")
    if shown.returncode != 0 or not shown.stdout.strip():
        raise Refusal("ledger", f"git rev-parse failed (exit {shown.returncode}){_why(shown)}")
    workspace = Path(found.stdout.decode("utf-8", "replace").strip())
    top = Path(shown.stdout.decode("utf-8", "replace").strip())
    path = workspace / "progress.md"
    try:
        lines = tuple(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError) as error:
        raise Refusal("ledger", f"cannot read {path}: {error}") from None
    header = HEADER.fullmatch(lines[0]) if lines else None
    if header is None:
        raise Refusal("ledger", f"{path} does not start with an SDD ledger header")
    if _resolved(header.group(1), top) != os.path.realpath(plan):
        raise Refusal("ledger", f"{path} belongs to another plan: {header.group(1)}")
    return Ledger(workspace, path, lines, top)


def recorded_sha(ledger: Ledger, pattern: str) -> str | None:
    """The one distinct group-1 value among the ledger lines matching `pattern` in full.

    `None` when no line matches; refuses with step `ledger` when two different
    values are recorded.
    """
    found = {match.group(1) for line in ledger.lines
             if (match := re.fullmatch(pattern, line)) is not None}
    if len(found) > 1:
        raise Refusal("ledger", f"{ledger.path} records {len(found)} different values "
                                f"for {pattern}")
    return next(iter(found), None)


def _dispatched(ledger: Ledger, task: int) -> str | None:
    """The base commit the ledger's `dispatched` line records for `task`, if it has one."""
    return recorded_sha(ledger, rf"Task {task}: dispatched \(base ([0-9a-f]{{40}})\)")


def task_base(ledger: Ledger, task: int) -> str:
    """The base commit the ledger's `dispatched` line records for `task`; refuses without one."""
    base = _dispatched(ledger, task)
    if base is None:
        raise Refusal("ledger", f"{ledger.path} has no dispatched line for task {task}")
    return base


def append_line(ledger: Ledger, line: str) -> None:
    """Append `line` and a newline to the ledger, first ending a last line that lacks one."""
    with ledger.path.open("ab+") as handle:
        size = handle.seek(0, os.SEEK_END)
        lead = b""
        if size:
            handle.seek(size - 1)
            lead = b"" if handle.read(1) == b"\n" else b"\n"
        handle.write(lead + line.encode("utf-8") + b"\n")  # append mode: it lands at the end


def pinned_head(step: str = "review-package", gate: str | None = "failed") -> str:
    """The full `git rev-parse HEAD` of the current checkout; refuses at `step` (default
    `review-package`, gate `failed`)."""
    try:
        done = _run(["git", "rev-parse", "HEAD"])
    except OSError as error:
        raise Refusal(step, f"cannot run git: {error}", gate=gate) from None
    head = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or FULL_SHA.fullmatch(head) is None:
        raise Refusal(step, f"cannot read HEAD (exit {done.returncode}){_why(done)}", gate=gate)
    return head


def workflow_state(step: str, *argv: str) -> dict:
    """Run `workflow-state <argv>` by name and return its one JSON object.

    A non-zero exit, a command that cannot start or a reply that is not one JSON
    object refuses with `step`.
    """
    try:
        done = _run(["workflow-state", *argv])
    except OSError as error:
        raise Refusal(step, f"cannot run workflow-state: {error}") from None
    if done.returncode != 0:
        raise Refusal(step, f"workflow-state exit {done.returncode}{_why(done)}")
    try:
        reply = _strict_json(done.stdout)
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        raise Refusal(step, "workflow-state did not print one JSON object")
    return reply


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temporary file beside it and `os.replace`.

    The temporary file is removed when the write fails and the `OSError` is
    raised again.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _package_root(ledger: Ledger, base: str, head: str) -> Path:
    return ledger.workspace / f"review-{base[:7]}..{head[:7]}.json"


def _errno(error: OSError) -> str:
    return error.strerror or type(error).__name__


def _reuse_refusal(root: Path, cause: str) -> Refusal:
    return Refusal("review-package", f"cannot reuse {root.name}: {cause}", gate="failed")


def _producer_report(plan: Path, root: Path, saved: Path, base: str, head: str) -> tuple[
        bytes, int | None]:
    """The package report's bytes and the producer's exit (`None` when reused)."""
    if not (root.exists() or root.is_symlink()):
        try:
            done = _run([*sibling_argv("review_package"), str(plan), base, head])
        except OSError as error:
            raise Refusal("review-package", f"cannot run review-package: {error}",
                          gate="failed") from None
        if done.returncode not in (0, 3):
            raise Refusal("review-package",
                          f"review-package failed (exit {done.returncode}){_why(done)}",
                          gate="failed")
        return done.stdout, done.returncode
    try:
        manifest = _strict_json(root.read_bytes())
    except OSError as error:
        raise _reuse_refusal(root, f"cannot read the manifest ({_errno(error)})") from None
    except ValueError:
        raise _reuse_refusal(root, "the manifest is not strict JSON") from None
    if not isinstance(manifest, dict) or manifest.get("range") != {"base": base, "head": head}:
        raise _reuse_refusal(root, "the manifest's range is not this base and head")
    try:
        raw = saved.read_bytes()
    except OSError as error:
        raise _reuse_refusal(root, f"the saved report is unreadable ({_errno(error)})") from None
    return raw, None


def package_gate(plan: Path, ledger: Ledger, base: str, head: str, done: list[str]) -> Package:
    """Build or reuse the `base..head` package and gate it; append each passed step to `done`.

    Steps `review-package` (produce the package, or reuse the one for exactly this
    range whose saved report exists), `validate-report` (the authority validates
    the report, whose artifact path must be this package; a fresh report is saved
    beside the package; a `decompose_required` report refuses with that gate),
    `budget-check` (an independent check says `within_budget`) and
    `metrics-match` (its metrics equal the report's). Every refusal but
    `decompose_required` carries gate `failed`.
    """
    root = _package_root(ledger, base, head)
    saved = root.with_name(root.stem + ".report.json")
    raw, exit_code = _producer_report(plan, root, saved, base, head)
    done.append("review-package")

    try:
        authority = describe("review-package")
        validated = authority.validate_report(raw, "producer")
        report = _strict_json(validated)
    except (BudgetError, ValueError) as error:
        raise Refusal("validate-report", f"report refused: {error}", gate="failed") from None
    artifact = report.get("artifact") if isinstance(report, dict) else None
    state = report.get("state") if isinstance(report, dict) else None
    if state not in STATES or not isinstance(artifact, dict) \
            or not isinstance(artifact.get("path"), str):
        raise Refusal("validate-report", "report is not a complete or decompose_required "
                                         "package report", gate="failed")
    if _resolved(artifact["path"], ledger.top) != os.path.realpath(root):
        raise Refusal("validate-report", "report names another package root", gate="failed")
    if exit_code is not None:
        if exit_code != PRODUCER_EXIT[state]:
            raise Refusal("validate-report", f"producer exit {exit_code} does not fit state "
                                             f"{state}", gate="failed")
        try:
            write_atomic(saved, validated)
        except OSError as error:
            raise Refusal("validate-report", f"cannot save the report: {error}",
                          gate="failed") from None
    if state == "decompose_required":
        raise Refusal("validate-report", "the package must be decomposed",
                      gate="decompose_required", report=report)
    done.append("validate-report")

    try:
        check = authority.check("review-package", root)
    except BudgetError as error:
        raise Refusal("budget-check", f"budget check refused: {error}", gate="failed") from None
    if check.status != "within_budget":
        raise Refusal("budget-check", f"package is {check.status}", gate="failed")
    done.append("budget-check")

    if dict(check.metrics) != artifact.get("metrics"):
        raise Refusal("metrics-match", "the report's metrics differ from the independent check",
                      gate="failed")
    done.append("metrics-match")
    return Package(artifact["path"], root, dict(check.metrics), authority)


def _metric_values(prefix: str, metrics: Mapping[str, int]) -> dict[str, str]:
    return {f"[{prefix}{key.upper()}]": str(metrics[key]) for key in METRIC_KEYS}


def shared_values(plan: Path, ledger: Ledger, task: int, authority: BudgetAuthority,
                  documents: Sequence[Path]) -> dict[str, str]:
    """The values of the ten tokens both dispatch templates share, but `[GLOBAL_CONSTRAINTS]`.

    These are the task's brief and report files in the workspace, the plan's path
    and its measured size, the selected standards documents and the stacks
    directory. Raises `BriefError` when the plan is over budget and
    `BudgetError` when the authority refuses.
    """
    check = authority.check("implementation-plan", plan)
    if check.status != "within_budget":
        raise BriefError(f"the plan is {check.status}")
    return {
        "[BRIEF_FILE]": str(ledger.workspace / f"task-{task}-brief.md"),
        "[REPORT_FILE]": str(ledger.workspace / f"task-{task}-report.md"),
        "[PLAN_ROOT]": str(plan),
        **_metric_values("PLAN_", check.metrics),
        "[STANDARDS]": standards_value(documents),
        "[STACKS_DIR]": str(_global_standards() / "stacks"),
    }


def _global_standards() -> Path:
    return Path.home() / ".agents/standards"


def _touched(base: str, head: str) -> list[str]:
    """Paths changed between `base` and `head`; a rename counts as a deletion and an addition."""
    done = _run(["git", "diff", "--name-only", "--no-renames", "-z", base, head])
    if done.returncode != 0:
        raise BriefError(f"git diff failed (exit {done.returncode}){_why(done)}")
    return [name for name in done.stdout.decode("utf-8", "replace").split("\0") if name]


def _render_brief(plan: Path, ledger: Ledger, args: argparse.Namespace, base: str, head: str,
                  package: Package, entries: Sequence[Path]) -> tuple[Path, list[Path]]:
    documents = select_standards(_global_standards(), entries, _touched(base, head))
    values = shared_values(plan, ledger, args.task, package.authority, documents)
    template = (args.skill_dir / REVIEWER_TEMPLATE).read_text(encoding="utf-8")
    text = render(template, REVIEWER_TOKENS, {
        **values,
        "[GLOBAL_CONSTRAINTS]": plan_section(plan.read_text(encoding="utf-8"),
                                             GLOBAL_CONSTRAINTS),
        "[BASE_SHA]": base,
        "[HEAD_SHA]": head,
        "[MANIFEST_ROOT]": package.manifest_root,
        **_metric_values("", package.metrics),
    })
    brief = ledger.workspace / f"task-{args.task}-review-dispatch.md"
    write_atomic(brief, text.encode("utf-8"))
    return brief, documents


def review(args: argparse.Namespace, done: list[str]) -> dict:
    """Run the seven `review` steps and return the ready object.

    Each step that passes is appended to `done`; the first that fails raises
    `Refusal` with its step name, leaving `done` as the completed steps.
    """
    plan = Path(os.path.abspath(args.plan_file))
    entries = [Path(os.path.abspath(value)) for value in args.standards]
    ledger = open_ledger(plan)
    base = task_base(ledger, args.task)
    done.append("ledger")

    if args.worker_id is not None:
        workflow_state("release-worker", "release-worker", "--repo-root", args.repo_root,
                       "--run-id", args.run_id, "--worker-id", args.worker_id,
                       "--event", "returned")
        done.append("release-worker")

    head = pinned_head()
    package = package_gate(plan, ledger, base, head, done)

    try:
        brief, documents = _render_brief(plan, ledger, args, base, head, package, entries)
    except (BriefError, BudgetError, OSError, UnicodeDecodeError) as error:
        raise Refusal("render-brief", f"cannot render the brief: {error}") from None
    done.append("render-brief")
    return {"command": "review", "outcome": "ready", "task": args.task,
            "brief_path": str(brief), "base_sha": base, "head_sha": head,
            "manifest_root": package.manifest_root, "metrics": package.metrics,
            "standards": [str(document) for document in documents]}


@contextlib.contextmanager
def _ledger_io(step: str, ledger: Ledger, gate: str | None = None):
    """Refuse with `step` (and `gate`) when reading or appending to the ledger fails."""
    try:
        yield
    except (OSError, UnicodeDecodeError) as error:
        cause = _errno(error) if isinstance(error, OSError) else "not UTF-8"
        raise Refusal(step, f"cannot update {ledger.path.name}: {cause}", gate=gate) from None


def _ledger_has(ledger: Ledger, matches) -> bool:
    """Whether the ledger file, read now, holds a line `matches` accepts."""
    return any(matches(line) for line in ledger.path.read_text(encoding="utf-8").splitlines())


def _recorded_head(ledger: Ledger, task: int) -> str | None:
    """The head the ledger's `recorded` line names for `task`, if it has one."""
    return recorded_sha(ledger, rf"Task {task}: recorded \(head ([0-9a-f]{{40}})\)")


def _completed_tasks(ledger: Ledger) -> set[int]:
    return {int(match.group(1)) for line in ledger.lines
            if (match := COMPLETE_LINE.fullmatch(line)) is not None}


def _earlier_projection(ledger: Ledger, delivery_base: str, task: int, base: str) -> dict:
    """The projection a re-dispatch of `task` reuses: the ledger's line through `task - 1` whose
    head is the task's dispatch base."""
    for line in ledger.lines:
        match = PROJECTION_LINE.fullmatch(line)
        if match is not None and match.group(1) == delivery_base and match.group(2) == base \
                and int(match.group(3)) == task - 1:
            return {"completed_through": task - 1, "head_sha": base,
                    "metrics": dict(zip(METRIC_KEYS, map(int, match.groups()[3:])))}
    raise Refusal("ledger", f"{ledger.path} has no projection through task {task - 1} at the "
                            f"dispatch base {base[:7]}")


def _evidence_target(ledger: Ledger, task: int) -> tuple[int, str, str]:
    """The task, dispatched base and recorded head `evidence` checks for `task`."""
    head = _recorded_head(ledger, task)
    if head is None:
        raise Refusal("ledger", f"{ledger.path} has no recorded line for task {task}: run "
                                "`sdd-gate record` and commit it first")
    return task, task_base(ledger, task), head


def _ledger_reads(ledger: Ledger, args: argparse.Namespace) -> Reads:
    recorded = recorded_sha(ledger, r"Delivery base: ([0-9a-f]{40})")
    if recorded is None and args.delivery_base is None:
        raise Refusal("ledger", f"{ledger.path} records no delivery base: pass --delivery-base")
    if recorded is not None and args.delivery_base not in (None, recorded):
        raise Refusal("ledger", f"{ledger.path} records delivery base {recorded[:7]}, "
                                f"not {args.delivery_base[:7]}")
    delivery_base = recorded or args.delivery_base
    completed = task_base(ledger, args.completed) if args.completed else None
    dispatched = _dispatched(ledger, args.task) if args.task else None
    evidence = _evidence_target(ledger, args.completed) if args.completed else None
    projected = None
    if args.task:
        closed = _completed_tasks(ledger) | ({args.completed} if args.completed else set())
        if closed != set(range(1, args.task)):
            raise Refusal("ledger", f"{ledger.path} does not record exactly tasks "
                                    f"1..{args.task - 1} complete before task {args.task}")
        if dispatched is not None:
            projected = _earlier_projection(ledger, delivery_base, args.task, dispatched)
        elif evidence is None and args.task > 1:
            evidence = _evidence_target(ledger, args.task - 1)
    return Reads(delivery_base, recorded is None, completed, dispatched, evidence, projected)


def _mark_progress(args: argparse.Namespace) -> str:
    """The `mark-progress` outcome under an identity (`refused` on any failure), else `skipped`."""
    if args.repo_root is None:
        return "skipped"
    try:
        done = _run(["workflow-state", "mark-progress", "--repo-root", args.repo_root,
                     "--run-id", args.run_id, "--action-id", args.action_id])
        reply = _strict_json(done.stdout) if done.returncode == 0 else None
    except (OSError, ValueError):
        return "refused"
    outcome = reply.get("outcome") if isinstance(reply, dict) else None
    return outcome if isinstance(outcome, str) else "refused"


def _write_refusal(error: OSError, args: argparse.Namespace, worker_id: str | None) -> Refusal:
    """The `write-brief` refusal, after releasing the worker this call registered (D15)."""
    detail = f"cannot write the brief: {_errno(error)}"
    if worker_id is None:
        return Refusal("write-brief", detail)
    command = ["workflow-state", "release-worker", "--repo-root", args.repo_root, "--run-id",
               args.run_id, "--worker-id", worker_id, "--event", "stopped"]
    try:
        released = _run(command).returncode == 0
    except OSError:
        released = False
    if released:
        return Refusal("write-brief", detail)
    return Refusal("write-brief", f"{detail}; worker {worker_id} is still registered: run "
                                  f"`{shlex.join(command)}` before calling next again")


def _refuse_live_predecessor(brief: Path, args: argparse.Namespace) -> None:
    """Refuse at `register-worker` while a worker an earlier dispatch of this task named in
    its brief is still live: registering over it would leave it unreleased."""
    try:
        lines = brief.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return  # no earlier brief of this task to read
    for line in lines:
        if not line.startswith(WORKER_LINE):
            continue
        try:
            flags = shlex.split(line[len(WORKER_LINE):])
            earlier = flags[flags.index("--worker-id") + 1]
        except (ValueError, IndexError):
            continue
        try:
            checked = _run(["workflow-state", "check-worker", "--repo-root", args.repo_root,
                            "--run-id", args.run_id, "--worker-id", earlier])
            reply = _strict_json(checked.stdout) if checked.returncode == 0 else None
        except (OSError, ValueError):
            continue
        if isinstance(reply, dict) and reply.get("live") is True:
            raise Refusal("register-worker", f"worker {earlier} from an earlier dispatch of task "
                                             f"{args.task} is still registered: release it "
                                             "before calling next again")


def _dispatch(plan: Path, ledger: Ledger, args: argparse.Namespace, entries: Sequence[Path],
              package: Package, base: str, record: bool, done: list[str]) -> tuple[
        list[Path], str | None]:
    """Steps `task-brief` to `write-brief`: the task's standards and the worker id.

    `base` is the task's base; `record` says the ledger does not hold it yet.
    """
    task = args.task
    try:
        made = _run(["task-brief", str(plan), str(task)])
    except OSError as error:
        raise Refusal("task-brief", f"cannot run task-brief: {error}") from None
    if made.returncode != 0:
        raise Refusal("task-brief", f"task-brief exit {made.returncode}{_why(made)}")
    done.append("task-brief")

    try:
        if record:
            append_line(ledger, f"Task {task}: dispatched (base {base})")
        plan_text = plan.read_text(encoding="utf-8")
        row = task_row(plan_text, task)
        documents = select_standards(_global_standards(), entries, list(row.paths))
        context = args.context_file.read_bytes().decode("utf-8").rstrip("\n") \
            if args.context_file else ""
        values = {
            **shared_values(plan, ledger, task, package.authority, documents),
            "[TASK_NUMBER]": str(task), "[TASK_NAME]": row.title, "[CONTEXT]": context,
            "[GLOBAL_CONSTRAINTS]": plan_section(plan_text, GLOBAL_CONSTRAINTS),
            "[TEST_SEAMS]": plan_section(plan_text, TEST_SEAMS), "[LIFECYCLE_WORKER]": "",
        }
        template = (args.skill_dir / IMPLEMENTER_TEMPLATE).read_text(encoding="utf-8")
        render(template, IMPLEMENTER_TOKENS, values)  # proves it renders before any worker exists
    except (BriefError, BudgetError, OSError, UnicodeDecodeError) as error:
        raise Refusal("prepare-brief", f"cannot prepare the brief: {error}") from None
    done.append("prepare-brief")

    worker_id = None
    brief = ledger.workspace / f"task-{task}-implementer-dispatch.md"
    if args.repo_root is not None:
        _refuse_live_predecessor(brief, args)
        reply = workflow_state("register-worker", "register-worker", "--repo-root", args.repo_root,
                               "--run-id", args.run_id, "--action-id", args.action_id)
        worker_id = reply.get("worker_id")
        if not isinstance(worker_id, str):
            raise Refusal("register-worker", "workflow-state did not name the worker")
        done.append("register-worker")
        values["[LIFECYCLE_WORKER]"] = worker_block(args.repo_root, args.run_id, worker_id)
    text = render(template, IMPLEMENTER_TOKENS, values)
    try:
        write_atomic(brief, text.encode("utf-8"))
    except OSError as error:
        raise _write_refusal(error, args, worker_id) from None
    return documents, worker_id


def _committed(path: PurePosixPath, commit: str) -> bytes | None:
    """The bytes of `path` committed at `commit`, or `None` when it has none."""
    done = _run(["git", "cat-file", "blob", f"{commit}:{path}"])
    return done.stdout if done.returncode == 0 else None


def _verify_recording(ledger: Ledger, plan: Path, target: tuple[int, str, str], commit: str) -> None:
    """Raise `RecordError` unless `commit` is the one commit that records the target task over its
    recorded head: its single parent, changing only the plan root and the task's member and
    committing exactly the bytes `recorded` computes."""
    task, base, recorded_head = target
    try:
        if history_commit(ledger.top, commit).parents != (recorded_head,):
            raise RecordError(f"{commit[:7]} is not the one commit recording task {task} over "
                              f"{recorded_head[:7]}")
        files = paths(ledger.top, plan, task)
        if not set(_touched(recorded_head, commit)) <= {str(path) for path in files}:
            raise RecordError(f"the commit recording task {task} changes more than its plan files")
        for path, data in zip(files, recorded(ledger.top, plan, task, base, recorded_head)):
            if _committed(path, commit) != data:
                raise RecordError(f"{path} at {commit[:7]} is not task {task}'s computed record")
    except (BriefError, ForecastError) as error:
        raise RecordError(str(error)) from None


DELIVERY_HEADING = "## Review feasibility delivery"
TASK_HEADING = "## Review feasibility task"


def _recording_commit(ledger: Ledger, target: tuple[int, str, str], head: str) -> tuple[str, list[str]]:
    """The candidate recording commit for the target task and the metadata tail over it.

    Walks `head` back along single-parent commits to the first whose one parent is the recorded
    head. The tail is every commit walked past, oldest first. Raises `RecordError` when the
    recorded head is not a proper ancestor of `head` or the walk meets a merge or a root.
    """
    task, _, recorded_head = target
    refused = RecordError(f"{head[:7]} is not the one commit recording task {task} over "
                          f"{recorded_head[:7]}, nor a metadata tail over it")
    if head == recorded_head or _run(["git", "merge-base", "--is-ancestor", recorded_head,
                                      head]).returncode != 0:
        raise refused
    tail: list[str] = []
    commit = head
    while True:
        parents = history_commit(ledger.top, commit).parents
        if parents == (recorded_head,):
            return commit, tail[::-1]
        if len(parents) != 1:
            raise RecordError(f"{commit[:7]} in the metadata tail over task {task}'s recording "
                              "is not a single-parent commit")
        tail.append(commit)
        commit = parents[0]


def _forecast_blocks(ledger: Ledger, plan: Path, commit: str) -> tuple[set[str], dict[str, dict]]:
    """The proposed boundary's process paths at `commit` and each path's forecast block."""
    root, _ = paths(ledger.top, plan, 1)
    raw = _committed(root, commit)
    if raw is None:
        raise RecordError(f"{root} is not committed at {commit[:7]}")
    delivery = forecast_block(raw, DELIVERY_HEADING)
    try:
        proposed = [boundary for boundary in delivery["boundaries"]
                    if boundary["id"] == delivery["proposed_boundary"]]
        package = proposed[0]["process_package"] if len(proposed) == 1 else None
        allowed = set(process_paths(package)) if isinstance(package, dict) else None
        spec = package["spec"] if allowed is not None else None
    except (KeyError, TypeError):
        allowed = spec = None
    if allowed is None or str(root) not in allowed:
        raise RecordError(f"{root} at {commit[:7]} declares no proposed process package")
    blocks = {}
    for path in sorted(allowed - {spec}):
        data = _committed(PurePosixPath(path), commit)
        if data is None:
            raise RecordError(f"{path} is not committed at {commit[:7]}")
        blocks[path] = forecast_block(data, DELIVERY_HEADING if path == str(root) else TASK_HEADING)
    return allowed, blocks


def _verify_tail(ledger: Ledger, plan: Path, task: int, recording: str, tail: Sequence[str]) -> None:
    """Raise `RecordError` unless each tail commit touches only process paths and leaves every
    forecast block as the recording commit holds it."""
    allowed, blocks = _forecast_blocks(ledger, plan, recording)
    previous = recording
    for commit in tail:
        stray = sorted(set(_touched(previous, commit)) - allowed)
        if stray:
            raise RecordError(f"{commit[:7]} over task {task}'s recording changes {stray[0]}, "
                              "outside the process package")
        if _forecast_blocks(ledger, plan, commit) != (allowed, blocks):
            raise RecordError(f"{commit[:7]} over task {task}'s recording changes a forecast block")
        previous = commit


def _check_evidence(ledger: Ledger, plan: Path, target: tuple[int, str, str], head: str) -> None:
    """Step `evidence`: `head` is the commit that records the target task, or a metadata tail
    over it (#565)."""
    try:
        recording, tail = _recording_commit(ledger, target, head)
        _verify_recording(ledger, plan, target, recording)
        if tail:
            _verify_tail(ledger, plan, target[0], recording, tail)
    except (BriefError, ForecastError) as error:
        raise Refusal("evidence", str(error), gate="failed") from None
    except RecordError as error:
        raise Refusal("evidence", str(error), gate="failed") from None


def _project(plan: Path, ledger: Ledger, delivery_base: str, head: str, through: int,
             package: Package) -> dict:
    """Step `projection`: project the delivery with tasks 1..`through` complete over `head`.

    The validated result is saved in the workspace before it is acted on. A projection that must be
    decomposed refuses with `decompose_required` and the canonical summary; one that cannot be
    produced refuses with `failed`. A passing one appends its ledger line once.
    """
    try:
        captured = capture(project_argv(plan, delivery_base, head, through), cwd=ledger.top,
                           authority=package.authority)
        result = captured.result
        if (result["base"], result["head"], result["completed_through"]) != (
                delivery_base, head, through):
            raise GateError("projection result is for another range")
        save_result(ledger.workspace, captured)
        if captured.exit == 3:
            raise Refusal("projection", "the projection must be decomposed",
                          gate="decompose_required",
                          report=summarize(captured, plan_relative(plan)))
    except GateError as error:
        raise Refusal("projection", str(error), gate="failed") from None
    metrics = {key: result["metrics"][key] for key in METRIC_KEYS}
    line = f"Projection gate: {delivery_base}..{head} through {through} " + " ".join(
        f"{key}={metrics[key]}" for key in METRIC_KEYS)
    with _ledger_io("projection", ledger, "failed"):
        if not _ledger_has(ledger, line.__eq__):
            append_line(ledger, line)
    return {"completed_through": through, "head_sha": head, "metrics": metrics}


def next_task(args: argparse.Namespace, done: list[str]) -> dict:
    """Run the `next` steps and return the ready object.

    Each step that passes is appended to `done`; the first that fails raises
    `Refusal` with its step name. The ledger gains its lines one write each, and
    only after step `ledger` has read everything it checks.
    """
    plan = Path(os.path.abspath(args.plan_file))
    entries = [Path(os.path.abspath(value)) for value in args.standards]
    ledger = open_ledger(plan)
    reads = _ledger_reads(ledger, args)
    delivery_base, dispatched = reads.delivery_base, reads.dispatched
    if reads.new_base:
        with _ledger_io("ledger", ledger):
            append_line(ledger, f"Delivery base: {delivery_base}")
    done.append("ledger")

    head = pinned_head()
    if reads.evidence is not None:
        _check_evidence(ledger, plan, reads.evidence, head)
        done.append("evidence")

    if args.completed:
        done_line = f"Task {args.completed}: complete"
        with _ledger_io("ledger-complete", ledger):
            if not _ledger_has(ledger, lambda line: line.startswith(done_line)):
                ending = f"{args.parked} parked" if args.parked else "review clean"
                append_line(ledger, f"{done_line} (commits {reads.completed_base[:7]}.."
                                    f"{reads.evidence[2][:7]}, {ending})")
        done.append("ledger-complete")

    progress = _mark_progress(args)
    if args.repo_root is not None:
        done.append("mark-progress")

    package = package_gate(plan, ledger, delivery_base, head, done)
    gate = f"Delivery gate: {delivery_base}..{head} " + " ".join(
        f"{key}={package.metrics[key]}" for key in METRIC_KEYS)
    try:
        with _ledger_io("metrics-match", ledger, "failed"):
            if not _ledger_has(ledger, gate.__eq__):
                append_line(ledger, gate)
    except Refusal:
        done.pop()  # the gate's result was not recorded, so `metrics-match` has not passed
        raise

    projection = reads.projected
    if args.task and dispatched is None:
        projection = _project(plan, ledger, delivery_base, head, args.task - 1, package)
        done.append("projection")

    out = {"command": "next", "outcome": "ready", "completed": args.completed, "task": None,
           "brief_path": None, "report_path": None, "base_sha": None, "worker_id": None,
           "mark_progress": progress,
           "delivery": {"base_sha": delivery_base, "head_sha": head,
                        "manifest_root": package.manifest_root, "metrics": package.metrics},
           "projection": projection, "standards": []}
    if args.task:
        base = dispatched or head
        documents, worker_id = _dispatch(plan, ledger, args, entries, package, base,
                                         dispatched is None, done)
        out.update(task=args.task, base_sha=base, worker_id=worker_id,
                   brief_path=str(ledger.workspace / f"task-{args.task}-implementer-dispatch.md"),
                   report_path=str(ledger.workspace / f"task-{args.task}-report.md"),
                   standards=[str(document) for document in documents])
    return out


def _dirty_paths() -> set[str]:
    """The tracked paths whose worktree or index state differs from `HEAD`."""
    done = _run(["git", "status", "--porcelain", "--untracked-files=no", "--no-renames", "-z"])
    if done.returncode != 0:
        raise Refusal("worktree", f"git status failed (exit {done.returncode}){_why(done)}")
    return {entry[3:] for entry in done.stdout.decode("utf-8", "replace").split("\0") if entry}


def _record_head(ledger: Ledger, plan: Path, task: int, base: str, current: str) -> str:
    """`H`: `HEAD`, or the head an earlier `recorded` line names when `HEAD` is that head or the
    commit that records it (anything else refuses at `ledger`)."""
    earlier = _recorded_head(ledger, task)
    if earlier is None or earlier == current:
        return earlier or current
    try:
        _verify_recording(ledger, plan, (task, base, earlier), current)
    except RecordError as error:
        raise Refusal("ledger", f"task {task} was recorded at {earlier[:7]}, which HEAD neither "
                                f"is nor records: {error}") from None
    return earlier


def record(args: argparse.Namespace, done: list[str]) -> dict:
    """Run the three `record` steps and return the ready object.

    `ledger` (this plan's ledger holds tasks 1..N-1 complete and N dispatched, not complete),
    `worktree` (no tracked change but the plan root and the task's member, and the task's commits
    are a range over the forecast's evidence head) and `record` (the task's commits left every
    forecast block alone; each file holds its `HEAD` or computed bytes, never an edit of its own;
    the two files take the computed bytes and the ledger the `recorded` line). Nothing is committed.
    """
    plan = Path(os.path.abspath(args.plan_file))
    task = args.task
    ledger = open_ledger(plan)
    closed = _completed_tasks(ledger)
    if task in closed or not set(range(1, task)) <= closed:
        raise Refusal("ledger", f"{ledger.path} must record tasks 1..{task - 1} complete and "
                                f"task {task} not complete")
    base = task_base(ledger, task)
    head = _record_head(ledger, plan, task, base, pinned_head("ledger", None))
    done.append("ledger")

    files = [ledger.top / path for path in paths(ledger.top, plan, task)]
    stray = _dirty_paths() - {str(path.relative_to(ledger.top)) for path in files}
    if stray:
        raise Refusal("worktree", f"uncommitted change outside the plan record: {min(stray)}")
    try:
        computed = recorded(ledger.top, plan, task, base, head)
    except RecordError as error:
        if not isinstance(error, RangeError):
            done.append("worktree")
        raise Refusal("worktree" if isinstance(error, RangeError) else "record", str(error)) from None
    done.append("worktree")

    stale = [(path, data) for path, data in zip(files, computed) if _read(path) != data]
    for path, _ in stale:
        relative = PurePosixPath(path.relative_to(ledger.top).as_posix())
        if _read(path) != _committed(relative, "HEAD"):
            raise Refusal("record", f"{relative} holds an uncommitted edit the record would discard")
    try:
        for path, data in stale:
            write_atomic(path, data)
        if _recorded_head(ledger, task) is None:
            append_line(ledger, f"Task {task}: recorded (head {head})")
    except OSError as error:
        raise Refusal("record", f"cannot write the record: {_errno(error)}") from None
    done.append("record")
    return {"command": "record", "outcome": "ready", "task": task, "head_sha": head,
            "paths": [str(path) for path in files], "changed": bool(stale)}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


def _task(value: str) -> int:
    if TASK_NUMBER.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("not a task number")
    return int(value)


def _full_sha(value: str) -> str:
    if FULL_SHA.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("not a full lowercase commit id")
    return value


def _parser() -> _Parser:
    parser = _Parser(prog="sdd-gate", description="Gate an sdd task's evidence and render "
                                                  "its dispatch brief.")
    commands = parser.add_subparsers(dest="command", required=True)
    review_parser = commands.add_parser("review", help="gate a task's review package and "
                                                       "render the reviewer brief")
    review_parser.add_argument("plan_file", metavar="PLAN_FILE")
    review_parser.add_argument("--skill-dir", required=True, type=Path)
    review_parser.add_argument("--task", required=True, type=_task)
    review_parser.add_argument("--standards", action="append", default=[])
    for flag in ("--repo-root", "--run-id", "--action-id", "--worker-id"):
        review_parser.add_argument(flag)

    record_parser = commands.add_parser("record", help="record a finished task's commits in the "
                                                       "plan's forecast")
    record_parser.add_argument("plan_file", metavar="PLAN_FILE")
    record_parser.add_argument("--task", required=True, type=_task)

    next_parser = commands.add_parser("next", help="close a task, open the next and render "
                                                   "the implementer brief")
    next_parser.add_argument("plan_file", metavar="PLAN_FILE")
    next_parser.add_argument("--skill-dir", required=True, type=Path)
    next_parser.add_argument("--standards", action="append", default=[])
    next_parser.add_argument("--completed", type=_task)
    next_parser.add_argument("--parked", type=_task)
    next_parser.add_argument("--task", type=_task)
    next_parser.add_argument("--context-file", type=Path)
    next_parser.add_argument("--delivery-base", type=_full_sha)
    for flag in ("--repo-root", "--run-id", "--action-id"):
        next_parser.add_argument(flag)
    return parser


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    args = _parser().parse_args(argv)
    if args.command == "record":
        return args
    identity = (args.repo_root, args.run_id, args.action_id)
    if any(value is not None for value in identity) and any(value is None for value in identity):
        raise InvocationError("a lifecycle identity is all three flags or none")
    if args.command == "review":
        if (args.worker_id is not None) != (args.repo_root is not None):
            raise InvocationError("--worker-id goes with a lifecycle identity")
    elif (args.completed is None and args.task is None) \
            or (args.parked is not None and args.completed is None) \
            or (args.context_file is not None and args.task is None):
        raise InvocationError("next takes --completed and/or --task, --parked with "
                              "--completed and --context-file with --task")
    return args


def _refusal_object(command: str, refusal: Refusal, done: Sequence[str]) -> dict:
    return {"command": command, "outcome": "refused", "step": refusal.step,
            "gate": refusal.gate, "detail": " ".join(refusal.detail.split())[:DETAIL_LIMIT],
            "report": refusal.report, "completed_steps": list(done)}


def _print(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, run the subcommand, print its one JSON object and return the exit code."""
    try:
        args = _parse(argv)
    except InvocationError:
        sys.stderr.write(INVALID)
        return 2
    done: list[str] = []
    try:
        _print({"review": review, "record": record, "next": next_task}[args.command](args, done))
    except Refusal as refusal:
        _print(_refusal_object(args.command, refusal, done))
        return 3 if refusal.gate == "decompose_required" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
