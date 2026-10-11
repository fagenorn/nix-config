"""`sdd-gate`: gate an sdd task's evidence, then render its dispatch brief (issue 353).

    sdd-gate review PLAN_FILE --skill-dir DIR --task N [--standards PATH ...]
        [--repo-root R --run-id I --action-id A --worker-id W]
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

`next` closes task N and/or opens task M. It runs up to eleven steps in order
and stops at the first that fails (a ledger that cannot be read or appended to
refuses at the step that needs it, and the delivery gate line's write refuses
at `metrics-match` with gate `failed`, not listed as passed): `ledger`, `ledger-complete` (with
`--completed`), `mark-progress` (under an identity), `review-package`,
`validate-report`, `budget-check`, `metrics-match` (the cumulative delivery
package, delivery base to HEAD), then, with `--task`, `task-brief`,
`prepare-brief`, `register-worker` (under an identity) and `write-brief`. A
step that does not apply does not run. It appends the ledger's delivery base,
completion, delivery gate and dispatch lines, each once, and writes the
implementer brief into the plan's workspace.

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
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.review_budget import BudgetAuthority, BudgetError, describe
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


def pinned_head() -> str:
    """The full `git rev-parse HEAD` of the current checkout; refuses at `review-package`."""
    try:
        done = _run(["git", "rev-parse", "HEAD"])
    except OSError as error:
        raise Refusal("review-package", f"cannot run git: {error}", gate="failed") from None
    head = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or FULL_SHA.fullmatch(head) is None:
        raise Refusal("review-package", f"cannot read HEAD (exit {done.returncode}){_why(done)}",
                      gate="failed")
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


def _ledger_reads(ledger: Ledger, args: argparse.Namespace) -> tuple[
        str, bool, str | None, str | None]:
    """What step `ledger` reads: the delivery base, whether it is new, and the bases of the
    completed task and of the task to dispatch (`None` when not asked for or not recorded)."""
    recorded = recorded_sha(ledger, r"Delivery base: ([0-9a-f]{40})")
    if recorded is None and args.delivery_base is None:
        raise Refusal("ledger", f"{ledger.path} records no delivery base: pass --delivery-base")
    if recorded is not None and args.delivery_base not in (None, recorded):
        raise Refusal("ledger", f"{ledger.path} records delivery base {recorded[:7]}, "
                                f"not {args.delivery_base[:7]}")
    completed = task_base(ledger, args.completed) if args.completed else None
    dispatched = _dispatched(ledger, args.task) if args.task else None
    return recorded or args.delivery_base, recorded is None, completed, dispatched


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


def next_task(args: argparse.Namespace, done: list[str]) -> dict:
    """Run the `next` steps and return the ready object.

    Each step that passes is appended to `done`; the first that fails raises
    `Refusal` with its step name. The ledger gains its lines one write each, and
    only after step `ledger` has read everything it checks.
    """
    plan = Path(os.path.abspath(args.plan_file))
    entries = [Path(os.path.abspath(value)) for value in args.standards]
    ledger = open_ledger(plan)
    delivery_base, new_base, completed_base, dispatched = _ledger_reads(ledger, args)
    if new_base:
        with _ledger_io("ledger", ledger):
            append_line(ledger, f"Delivery base: {delivery_base}")
    done.append("ledger")

    head = pinned_head()
    if args.completed:
        done_line = f"Task {args.completed}: complete"
        with _ledger_io("ledger-complete", ledger):
            if not _ledger_has(ledger, lambda line: line.startswith(done_line)):
                ending = f"{args.parked} parked" if args.parked else "review clean"
                append_line(ledger,
                            f"{done_line} (commits {completed_base[:7]}..{head[:7]}, {ending})")
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

    out = {"command": "next", "outcome": "ready", "completed": args.completed, "task": None,
           "brief_path": None, "report_path": None, "base_sha": None, "worker_id": None,
           "mark_progress": progress,
           "delivery": {"base_sha": delivery_base, "head_sha": head,
                        "manifest_root": package.manifest_root, "metrics": package.metrics},
           "standards": []}
    if args.task:
        base = dispatched or head
        documents, worker_id = _dispatch(plan, ledger, args, entries, package, base,
                                         dispatched is None, done)
        out.update(task=args.task, base_sha=base, worker_id=worker_id,
                   brief_path=str(ledger.workspace / f"task-{args.task}-implementer-dispatch.md"),
                   report_path=str(ledger.workspace / f"task-{args.task}-report.md"),
                   standards=[str(document) for document in documents])
    return out


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
        _print({"review": review, "next": next_task}[args.command](args, done))
    except Refusal as refusal:
        _print(_refusal_object(args.command, refusal, done))
        return 3 if refusal.gate == "decompose_required" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
