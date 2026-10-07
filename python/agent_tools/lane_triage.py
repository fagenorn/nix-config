"""`lane-triage`: the deterministic light-lane verdict over an owner's triage record (#279).

It reads `bindings.workflow.light_lane` through `resolve_project.resolve`, prints
`{hits, lane, mode}` and writes no file.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys

from agent_tools import resolve_project
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

SIGNALS = ("contract_change", "concurrency_or_persistence",
           "open_design_questions", "criteria_shape")
VALUES = ("no", "hit", "doubt")
HIT_ORDER = SIGNALS + ("risk_path",)
SIGNAL_MEMBERS = ("value", "evidence")
TOP_MEMBERS = ("signals", "paths")


class TriageRefusal(Exception):
    """One refusal: a closed code and its detail (`None` when it has none)."""

    def __init__(self, code: str, detail: object) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def invalid(pointer: str, message: str) -> TriageRefusal:
    return TriageRefusal("invalid_input", {"pointer": pointer, "message": message})


def check_members(value: dict, expected: tuple[str, ...], pointer: str) -> None:
    for name in expected:
        if name not in value:
            raise invalid(f"{pointer}/{name}", "required member is absent")
    for key in sorted(set(value) - set(expected)):
        raise invalid(f"{pointer}/{key}", "member is not part of this schema")


def validate_record(value: object) -> None:
    """Raise `TriageRefusal` at the first violation of the triage record schema."""
    if not isinstance(value, dict):
        raise invalid("", "must be an object")
    check_members(value, TOP_MEMBERS, "")
    signals = value["signals"]
    if not isinstance(signals, dict):
        raise invalid("/signals", "must be an object")
    check_members(signals, SIGNALS, "/signals")
    for name in SIGNALS:
        pointer = f"/signals/{name}"
        signal = signals[name]
        if not isinstance(signal, dict):
            raise invalid(pointer, "must be an object")
        check_members(signal, SIGNAL_MEMBERS, pointer)
        if not isinstance(signal["value"], str) or signal["value"] not in VALUES:
            raise invalid(f"{pointer}/value", "must be one of " + ", ".join(VALUES))
        evidence = signal["evidence"]
        if not isinstance(evidence, str) or not evidence \
                or "\n" in evidence or "\r" in evidence:
            raise invalid(f"{pointer}/evidence",
                          "must be a non-empty string with no line break")
    paths = value["paths"]
    if not isinstance(paths, list) or not paths:
        raise invalid("/paths", "must be a non-empty list")
    for index, path in enumerate(paths):
        if not resolve_project.is_safe_relative_path(path):
            raise invalid(f"/paths/{index}", "must be a non-empty repository-relative "
                                             "path with no '..' segment")
        if not is_canonical_path(path):
            raise invalid(f"/paths/{index}", "must be spelled canonically: '/'-separated, "
                                             "with no backslash, no empty or '.' segment "
                                             "and no trailing '/'")


def is_canonical_path(path: str) -> bool:
    """The one spelling `risk_paths` globs are matched against, as recorded (D11)."""
    return "\\" not in path and all(segment not in ("", ".") for segment in path.split("/"))


def load_record(text: str) -> dict:
    """Strictly parse and validate a triage record."""
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except ValueError as error:
        raise invalid("", f"not strict JSON: {error}") from None
    validate_record(value)
    return value


def light_lane_policy(repo_root: str) -> dict:
    """The authored `light_lane` object of the project at `repo_root`."""
    try:
        snapshot = resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        detail = {"code": error.code, "repair_id": error.repair_id,
                  "violations": error.violations}
        if error.reason_code is not None:
            detail["reason_code"] = error.reason_code
        raise TriageRefusal("resolver_refused", detail) from None
    light_lane = snapshot["bindings"]["workflow"].get("light_lane")
    if light_lane is None:
        raise TriageRefusal("light_lane_unsupported", None)
    return light_lane


def evaluate(record: dict, light_lane: dict) -> dict:
    """The verdict: `light` exactly when no signal and no risk path hits."""
    hit = {name for name in SIGNALS if record["signals"][name]["value"] != "no"}
    if any(fnmatch.fnmatchcase(path, glob)
           for path in record["paths"] for glob in light_lane["risk_paths"]):
        hit.add("risk_path")
    hits = [name for name in HIT_ORDER if name in hit]
    return {"hits": hits, "lane": "full" if hits else "light", "mode": light_lane["mode"]}


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lane-triage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = commands.add_parser(
        "evaluate", help="print the lane verdict for a triage record read from stdin")
    evaluate_parser.add_argument("--repo-root", required=True)
    evaluate_parser.add_argument("--input", required=True, choices=["-"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = sys.stdin.read()
    try:
        light_lane = light_lane_policy(args.repo_root)
        verdict = evaluate(load_record(text), light_lane)
    except TriageRefusal as refusal:
        sys.stderr.write(compact({"error": {"code": refusal.code, "detail": refusal.detail}}))
        return 2
    sys.stdout.write(compact(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
