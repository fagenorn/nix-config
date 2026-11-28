"""Reading an outline run's store: the approved record, the setup snapshot, the built slices and the outline text.

The outline of a run exists only in the run store of its root run (D6). A command is handed `run.holder` and
`run.issue`; `root_run` finds the root run from them, and every other function reads that run's results. No
function reads the worktree or derives a branch: the store is the only source.

- `latest` is the result of the last `result_stored` event, in ledger order, of a step that passes a test. The
  step is looked up by id in the run's own copy of its procedure.
- `outline` is the outline members of the latest result of any step whose reply is `OUTLINE_REPLY`.
- `snapshot` is the setup facts the build reads, `SNAPSHOT`: the latest result of each named step, flattened.
- `approved` is the latest result of the note step that posted. It never reads a later outline reply, so the
  approved outline is the one the note stored.
- `built(run, digest)` maps a slice number to the `build` result of the latest `SLICE_PROCEDURE` run that ended
  `done` and whose `SLICE_READ` step was given the approved outline of `digest`, so a slice built under an earlier
  approved outline is never taken for one of this outline. The runs are those named by the `call` events of the
  `BUILD_PROCEDURE` children the root's own `call` events name; a later `call` event wins.
- `render` writes an outline as the text the design review reads and the forge comment carries.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_tools.delivery import engine_ledger, engine_resume

OUTLINE_REPLY = "outline.reply.json"
NOTE_SUBCOMMAND = "outline-note"
BUILD_PROCEDURE = "outline-build"
SLICE_PROCEDURE = "outline-slice"
SLICE_READ = "slice"
OUTLINE_MEMBERS = ("approach", "rejected", "slices", "criteria", "risks", "questions")
SNAPSHOT = (("start", ("details", "merged_refs")),
            ("plan-preflight", ("branch", "worktree_path", "integration_branch", "issue_text", "routed",
                                "route_detail")))


class RecordError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def root_run(holder: str, issue: int) -> Path:
    """The root run of `holder` (`<host>/<run id>`) for `issue`; `run_unknown` when it names no such run."""
    name = holder.partition("/")[2]
    if "/" not in holder or name in ("", ".", "..") or "/" in name:
        raise RecordError("run_unknown", f"{holder!r} does not name a run")
    run_dir = engine_ledger.runs_root() / name
    try:
        document = engine_ledger.read_run(run_dir)
    except engine_ledger.LedgerError as error:
        raise RecordError("run_unknown", f"no readable run {name}: {error}") from error
    if document["issue"] != issue:
        raise RecordError("run_unknown", f"run {name} is not a run of issue #{issue}")
    return run_dir


def procedure_steps(run_dir: Path) -> dict[str, dict]:
    """The steps of the run's own procedure copy by id, in procedure order."""
    procedure = engine_ledger.read_run(run_dir)["procedure"]
    try:
        document = json.loads((run_dir / "procedure" / f"{procedure}.json").read_text(encoding="utf-8"))
        return {step["id"]: step for step in document["steps"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RecordError("run_unknown", f"run {run_dir.name} holds no readable procedure {procedure}") from error


def latest(run_dir: Path, step: Callable[[Mapping], bool],
           result: Callable[[Mapping], bool] = lambda r: True) -> dict | None:
    """The result of the last `result_stored` event whose step passes `step` and whose result passes `result`."""
    run_dir = Path(run_dir)
    steps = procedure_steps(run_dir)
    found = None
    for event in engine_ledger.replay(run_dir / "events.jsonl"):
        if event["event"] != "result_stored" or event["step"] not in steps:
            continue
        if not step(steps[event["step"]]):
            continue
        try:
            stored = json.loads((run_dir / event["result"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RecordError("run_unknown", f"cannot read {event['result']} of run {run_dir.name}") from error
        if isinstance(stored, dict) and result(stored):
            found = stored
    return found


def _members(stored: Mapping, members: tuple[str, ...], what: str) -> dict:
    missing = [member for member in members if member not in stored]
    if missing:
        raise RecordError("plan_missing", f"the latest {what} lacks {', '.join(missing)}")
    return {member: stored[member] for member in members}


def outline(run_dir: Path) -> dict:
    stored = latest(run_dir, lambda step: step.get("reply") == OUTLINE_REPLY)
    if stored is None:
        raise RecordError("plan_missing", "the run has no outline reply")
    return _members(stored, OUTLINE_MEMBERS, "outline reply")


def snapshot(run_dir: Path) -> dict:
    facts: dict = {}
    for step_id, members in SNAPSHOT:
        stored = latest(run_dir, lambda step, step_id=step_id: step.get("id") == step_id)
        if stored is None:
            raise RecordError("plan_missing", f"the run has no result of step {step_id}")
        facts.update(_members(stored, members, f"{step_id} result"))
    return facts


def approved(run_dir: Path) -> dict:
    stored = latest(run_dir,
                    lambda step: step.get("kind") == "command" and step.get("subcommand") == NOTE_SUBCOMMAND,
                    lambda result: result.get("verdict") == "posted")
    if stored is None:
        raise RecordError("plan_missing", "the run has no posted outline note")
    return stored


def _called(run_dir: Path, procedure: str) -> list[Path]:
    """The child runs of `procedure` the run's `call` events name, in event order."""
    children = []
    for event in engine_ledger.replay(run_dir / "events.jsonl"):
        if event["event"] != "call":
            continue
        child = engine_ledger.runs_root() / event["child"]
        try:
            if engine_ledger.read_run(child)["procedure"] == procedure:
                children.append(child)
        except engine_ledger.LedgerError:
            continue
    return children


def built(run_dir: Path, digest: str) -> dict[int, dict]:
    slices: dict[int, dict] = {}
    for build_run in _called(Path(run_dir), BUILD_PROCEDURE):
        for child in _called(build_run, SLICE_PROCEDURE):
            if engine_resume.ended(child) != engine_resume.DONE:
                continue
            read = latest(child, lambda step: step.get("id") == SLICE_READ)
            stored = latest(child, lambda step: step.get("id") == "build")
            item = engine_ledger.read_run(child)["inputs"].get("item")
            if stored is not None and isinstance(item, int) and read is not None and read.get("digest") == digest:
                slices[item] = stored
    return slices


def render(issue: int, outline: Mapping) -> str:
    lines = [f"# Outline of issue #{issue}", "", "## Approach", outline["approach"], "",
             "## Rejected alternative", outline["rejected"], "", "## Slices"]
    for item in outline["slices"]:
        lines += [f"### Slice {item['n']}: {item['change']}", f"- Files: {', '.join(item['files'])}",
                  f"- Proving test: {item['test']}: {item['assertion']}"]
    lines += ["", "## Acceptance criteria"]
    lines += [f"- {c['id']} ({c['kind']}, slice {c['slice']}): {c['text']}" for c in outline["criteria"]]
    lines += ["", "## Risks"] + [f"- {risk}" for risk in outline["risks"] or ["none"]]
    lines += ["", "## Owner questions"] + [f"- {question}" for question in outline["questions"] or ["none"]]
    return "\n".join(lines) + "\n"
