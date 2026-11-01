"""Bounded capture, summary derivation and confirmation of a review-feasibility projection (issue 227)."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from typing import Callable, Sequence

from agent_tools.review_actual import SHA_RE, _run_git
from agent_tools.review_budget import BudgetAuthority, describe
from agent_tools.review_forecast import ForecastError, canonical_bytes, strict_json
from agent_tools.review_projection import validate_result
from agent_tools.siblings import sibling_argv

SUMMARY_KEYS = ("artifact_policy_sha256", "base", "completed_through", "forecast_sha256", "head", "kind",
                "metrics", "packing_policy_sha256", "plan", "plan_package_sha256", "recommended_boundary",
                "schema_version", "state", "violations")
RECOMMENDATION_KEYS = ("id", "metrics", "prerequisite_commit", "tasks")
_COPIED = ("state", "base", "head", "completed_through", "metrics", "violations", "plan_package_sha256",
           "forecast_sha256", "packing_policy_sha256", "artifact_policy_sha256")
_STATES = {"complete": 0, "decompose_required": 3}
_STDERR_TAIL = 4096
_REASON_CHARS = 300
_PREFIX = "review-feasibility: "


class GateError(ForecastError):
    """A projection could not be captured, summarized or confirmed; the message is the one-line reason."""


@dataclass(frozen=True)
class Capture:
    exit: int
    raw: bytes
    result: dict


def project_argv(plan: Path, base: str, head: str, completed_through: int) -> list[str]:
    return [*sibling_argv("review_feasibility"), "project", "--plan", str(plan), "--base", base,
            "--head", head, "--completed-through", str(completed_through)]


def _drain(stream, tail: bytearray) -> None:
    while chunk := stream.read1(_STDERR_TAIL):
        tail += chunk
        del tail[:-_STDERR_TAIL]


def _reason(tail: bytes) -> str:
    lines = [line for line in tail.decode("utf-8", "replace").splitlines() if line.strip()]
    text = " ".join(lines[-1].split()).removeprefix(_PREFIX) if lines else ""
    return text[:_REASON_CHARS] or "projection failed"


def capture(argv: Sequence[str], *, cwd: Path, authority: BudgetAuthority) -> Capture:
    """Bounded stdout, drained stderr, exit in {0, 2, 3}, then `validate_result` with that exit."""
    bound = authority.report_wire_max_bytes
    try:
        child = subprocess.Popen(list(argv), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise GateError("cannot run review-feasibility project") from exc
    tail = bytearray()
    drain = threading.Thread(target=_drain, args=(child.stderr, tail), daemon=True)
    drain.start()
    try:
        raw = child.stdout.read(bound + 1)
        if len(raw) > bound:
            child.kill()
            raise GateError("projection result exceeds report wire bound")
        code = child.wait()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
        drain.join()
        child.stdout.close()
        child.stderr.close()
    if code == 2:
        raise GateError(_reason(bytes(tail)))
    if code not in (0, 3):
        raise GateError(f"projection exit {code} is not 0, 2 or 3")
    try:
        validated = validate_result(raw, code, authority)
    except ForecastError as exc:
        raise GateError(f"invalid projection result: {exc}") from exc
    return Capture(code, validated, strict_json(validated))


def summarize(capture: Capture, plan: str) -> dict:
    result = capture.result
    recommendation = result["recommended_boundary"]
    complete = result["state"] == "complete"
    if (capture.exit != _STATES.get(result["state"]) or complete != (result["violations"] == [])
            or (complete and recommendation is not None)):
        raise GateError("summary state disagrees with its exit")
    summary = {key: result[key] for key in _COPIED}
    summary.update(schema_version=1, kind="review-feasibility-summary", plan=plan,
                   recommended_boundary=None if recommendation is None
                   else {key: recommendation[key] for key in RECOMMENDATION_KEYS})
    return summary


def plan_relative(plan: Path) -> str:
    """The plan's path from its checkout's top level, as POSIX."""
    directory = plan.absolute().parent
    top = Path(os.path.realpath(_run_git(directory, "rev-parse", "--show-toplevel").strip()))
    try:
        return (Path(os.path.realpath(directory)) / plan.name).relative_to(top).as_posix()
    except ValueError as exc:
        raise GateError("plan is outside its checkout") from exc


def result_name(head: str, completed_through: int) -> str:
    return f"projection-{head[:7]}-{completed_through}.json"


def save_result(directory: Path, capture: Capture) -> Path:
    """Write the validated bytes atomically; the file is a cache of the projection, not its provenance."""
    target = directory / result_name(capture.result["head"], capture.result["completed_through"])
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=target.name + ".")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(capture.raw)
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        raise GateError("cannot save projection result") from exc
    return target


def gate(plan: Path, base: str, head: str, completed_through: int, *, argv: Sequence[str] | None = None,
         save_dir: Path | None = None) -> tuple[int, bytes]:
    plan = plan.absolute()
    captured = capture(argv or project_argv(plan, base, head, completed_through), cwd=plan.parent,
                       authority=describe("review-package"))
    if save_dir is not None:
        save_result(save_dir, captured)
    return captured.exit, canonical_bytes(summarize(captured, plan_relative(plan)))


def _valid(key: str, value: object) -> bool:
    if key == "completed_through":
        return type(value) is int and value >= 0
    if key == "head":
        return isinstance(value, str) and SHA_RE.fullmatch(value) is not None
    if key == "state":
        return value in _STATES
    return True


def _parse(raw: bytes) -> dict:
    try:
        value = strict_json(raw)
    except ForecastError as exc:
        raise GateError("invalid summary JSON") from exc
    if not isinstance(value, dict):
        raise GateError("invalid summary JSON")
    mismatched = sorted(set(value) ^ set(SUMMARY_KEYS))
    if mismatched:
        raise GateError(f"confirm: {mismatched[0]} disagrees")
    for key in SUMMARY_KEYS:
        if not _valid(key, value[key]):
            raise GateError(f"confirm: {key} disagrees")
    return value


def confirm(plan: Path, base: str, raw: bytes, *,
            argv: Callable[[str, str, int], Sequence[str]] | None = None) -> tuple[int, bytes]:
    """Recompute the summary from the plan and history; `argv(base, head, completed_through)` names the producer."""
    if len(raw) > describe("review-package").report_wire_max_bytes:
        raise GateError("summary exceeds report wire bound")
    value = _parse(raw)
    if value["plan"] != plan_relative(plan):
        raise GateError("confirm: plan disagrees")
    if value["base"] != base:
        raise GateError("confirm: base disagrees")
    head, ordinal = value["head"], value["completed_through"]
    code, recomputed = gate(plan, base, head, ordinal, argv=None if argv is None else argv(base, head, ordinal))
    if canonical_bytes(value) != recomputed:
        actual = strict_json(recomputed)
        raise GateError(f"confirm: {next(key for key in SUMMARY_KEYS if value[key] != actual[key])} disagrees")
    if code != _STATES[value["state"]]:
        raise GateError("confirm: state disagrees")
    return code, recomputed
