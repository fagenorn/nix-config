"""Contract tests for `engine check` (`agent_tools.delivery.engine`, #1508).

Runs the command as `python -m agent_tools.delivery.engine check` against the
shipped toy procedures and against one-mutation copies of them (agent-helpers
rule 5).
"""

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest import mock

from agent_tools.delivery import engine, engine_graders, engine_reply, procedure_check
from agent_tools.delivery.engine_graders import GRADERS
from agent_tools.delivery.procedure_check import CommandDeclaration, load_commands
from tests.guard_policy_world import install_platform_manifest_in_environ

setUpModule = install_platform_manifest_in_environ

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"
DELIVERY = REPO_ROOT / "python/agent_tools/delivery"


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def load(directory: Path, name: str) -> dict:
    return json.loads((Path(directory) / f"{name}.json").read_text(encoding="utf-8"))


def save(directory: Path, name: str, doc: dict) -> None:
    (Path(directory) / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def step(doc: dict, step_id: str) -> dict:
    return next(item for item in doc["steps"] if item["id"] == step_id)


def broken_copy(mutate: Callable[[Path], None]) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="engine-check-"))
    unittest.addModuleCleanup(shutil.rmtree, directory, ignore_errors=True)
    target = directory / "procedures"
    shutil.copytree(PROCEDURES, target)
    mutate(target)
    return target


def run_check(*args: str) -> tuple[int, str, str]:
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.engine", "check", *args],
        capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout, done.stderr


def table_rows() -> list[str]:
    return re.findall(r'^\s+"([a-z0-9-]+)" = "[a-z_.]+";$',
                      (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8"), re.M)


def editing(name: str, change: Callable[[dict], None]) -> Callable[[Path], None]:
    def mutate(directory: Path) -> None:
        doc = load(directory, name)
        change(doc)
        save(directory, name, doc)
    return mutate


@dataclass(frozen=True)
class Case:
    name: str
    mutate: Callable[[Path], None]
    expected: list[tuple[str, str | None, str]]


def _set(target: Callable[[dict], dict], key: str, value: object) -> Callable[[dict], None]:
    def change(toy: dict) -> None:
        target(toy)[key] = value
    return change


def _repeat_scope(toy: dict) -> None:
    toy["steps"].append(copy.deepcopy(step(toy, "scope")))


def _add_version(toy: dict) -> None:
    toy["version"] = 1


def _unknown_need(toy: dict) -> None:
    toy["stops"]["needs-owner"]["need"] = "someday"


def _write_broken_child(directory: Path) -> None:
    (directory / "toy-child.json").write_text("{", encoding="utf-8")


def _reroute_tally(toy: dict) -> None:
    step(toy, "tally")["on"]["revise"] = "redraft"


def _reenter_nowhere(toy: dict) -> None:
    toy["stops"]["needs-owner"]["reenter"] = "nope"


def _stop_reenters_a_repair_step_that_returns_to_scope(toy: dict) -> None:
    toy["stops"]["needs-owner"]["reenter"] = "repair"
    toy["steps"].append({"id": "repair", "stage": "setup", "kind": "command",
                         "command": "diff-scope", "holds": "run", "in": ["run.range"],
                         "on": {"ok": "scope", "failed": "done"}})


def _exhausted_scope_hands_over_to_the_repair_a_stop_enters(toy: dict) -> None:
    toy["stops"]["needs-owner"]["reenter"] = "repair"
    toy["steps"].append({"id": "repair", "stage": "setup", "kind": "command",
                         "command": "diff-scope", "holds": "run", "in": ["run.range"],
                         "max_visits": 2,
                         "on": {"ok": "scope", "failed": "done", "refused": "done", "exhausted": "done"}})
    step(toy, "scope")["on"]["exhausted"] = "repair"
    step(toy, "children")["on"]["exhausted"] = "done"


def _undeclared_command(toy: dict) -> None:
    step(toy, "scope")["command"] = next(
        key for key, declaration in sorted(procedure_check.load_commands().items())
        if declaration is None)


def _editing_draft_reply(change: Callable[[dict], None]) -> Callable[[Path], None]:
    def mutate(directory: Path) -> None:
        path = directory / "toy-draft.reply.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        change(schema)
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return mutate


def _drop_outcome_enum(schema: dict) -> None:
    del schema["properties"]["status"]["enum"]


def _outcome_not_required(schema: dict) -> None:
    schema["required"].remove("status")


def _add_orphan(toy: dict) -> None:
    toy["steps"].append({"id": "orphan", "stage": "building", "kind": "command",
                         "command": "diff-scope", "holds": "run",
                         "in": ["draft.summary"],
                         "on": {"ok": "done", "failed": "done", "refused": "done"}})


def _claim_reaches_done_only_through_exhausted(child: dict) -> None:
    claim = step(child, "claim")
    claim["on"] = {outcome: "child-stop" for outcome in claim["on"]}
    claim["on"]["exhausted"] = "done"


def _add_enum_outcome(schema: dict) -> None:
    schema["properties"]["status"]["enum"].append("abandoned")


def _without(target: Callable[[dict], dict], key: str) -> Callable[[dict], None]:
    def change(toy: dict) -> None:
        del target(toy)[key]
    return change


def _drop_on(step_id: str, outcome: str) -> Callable[[dict], None]:
    def change(toy: dict) -> None:
        step(toy, step_id)["on"].pop(outcome, None)
    return change


def _no_reply_reply_value(schema: dict) -> None:
    schema["properties"]["status"]["enum"].append("no-reply")


def _pass_set_with_no_reply(toy: dict) -> None:
    step(toy, "review")["members"][0]["pass"].append("no-reply")


def _unbound_the_loop(toy: dict) -> None:
    for step_id in ("draft", "review", "tally"):
        del step(toy, step_id)["max_visits"]


def _pass_set_with_maybe(toy: dict) -> None:
    step(toy, "review")["members"][0]["pass"] = ["approve", "maybe"]


def _append_in(step_id: str, path: str) -> Callable[[dict], None]:
    def change(toy: dict) -> None:
        step(toy, step_id)["in"].append(path)
    return change


def _drop_holder_input(toy: dict) -> None:
    toy["inputs"].remove("holder")


def _items_not_required(schema: dict) -> None:
    schema["required"].remove("items")


def _append_to_review_prompt(directory: Path) -> None:
    with (directory / "toy-review.md").open("a", encoding="utf-8") as prompt:
        prompt.write("\n{{draft.items}}\n")


def _link_outside(name: str) -> Callable[[Path], None]:
    """Replace one file of the procedure directory with a symlink to a copy outside it."""
    def mutate(directory: Path) -> None:
        outside = directory.parent / f"outside-{name}"
        outside.write_bytes((directory / name).read_bytes())
        (directory / name).unlink()
        (directory / name).symlink_to(outside)
    return mutate


def _write_bytes(name: str, data: bytes) -> Callable[[Path], None]:
    def mutate(directory: Path) -> None:
        (directory / name).write_bytes(data)
    return mutate


def _two_exhausted_steps_hand_over(child: dict) -> None:
    child["steps"] = [
        {"id": own, "stage": "building", "kind": "command", "command": "diff-scope",
         "holds": "run", "in": ["run.item"], "max_visits": 1,
         "on": {"ok": own, "failed": "done", "refused": "done", "exhausted": other}}
        for own, other in (("a", "b"), ("b", "a"))]
    for stop in child["stops"].values():
        stop["reenter"] = "a"


def _exhausted_and_ordinary_edges_loop(child: dict) -> None:
    def make(own: str, ok: str, exhausted: str | None, bound: bool) -> dict:
        on = {"ok": ok, "failed": "done", "refused": "done"}
        if exhausted is not None:
            on["exhausted"] = exhausted
        item = {"id": own, "stage": "building", "kind": "command", "command": "diff-scope",
                "holds": "run", "in": ["run.item"], "on": on}
        if bound:
            item["max_visits"] = 1
        return item
    child["steps"] = [make("a", "a", "b", True), make("b", "b", "c", True), make("c", "a", None, False)]
    for stop in child["stops"].values():
        stop["reenter"] = "a"


def _no_claim_lost_stop(toy: dict) -> None:
    del toy["stops"]["claim-lost"]
    step(toy, "children")["on"]["claim-lost"] = "needs-owner"


def _recovery(child: dict) -> None:
    child["steps"].append(
        {"id": "recover", "stage": "building", "kind": "command", "command": "diff-scope",
         "holds": "run", "in": ["run.item"],
         "on": {"ok": "done", "failed": "child-stop", "refused": "child-stop"}})
    child["stops"]["claim-lost"]["reenter"] = "recover"


def _recovery_without_a_mutating_step(child: dict) -> None:
    _recovery(child)
    del step(child, "claim")["mutates"]
    del step(child, "claim")["check"]


def _recovery_without_a_keep_alive(child: dict) -> None:
    _recovery(child)
    del child["keep_alive"]


def _recovery_reading(path: str) -> Callable[[dict], None]:
    """toy-child as a -> b (mutates) -> done, whose `claim-lost` re-enters `r`, a step reading `path`."""
    def edit(child: dict) -> None:
        def command(name: str, reads: str, on: dict, **more: object) -> dict:
            return {"id": name, "stage": "building", "kind": "command", "command": "diff-scope",
                    "holds": "run", "in": [reads], "on": on, **more}
        done = {"ok": "done", "failed": "child-stop", "refused": "child-stop"}
        child["steps"] = [command("a", "run.item", {"ok": "b", "failed": "child-stop", "refused": "child-stop"}),
                          command("b", "run.item", done, mutates=True,
                                                  check={"command": "diff-scope"}), command("r", path, done)]
        child["stops"]["child-stop"]["reenter"] = "a"
        child["stops"]["claim-lost"]["reenter"] = "r"
    return edit


def _first_step_recovery_reading(path: str) -> Callable[[dict], None]:
    def edit(child: dict) -> None:
        _recovery(child)
        step(child, "recover")["in"] = [path]
    return edit


def _no_reply_to_review(toy: dict) -> None:
    step(toy, "draft")["on"]["no-reply"] = "review"


def _exhausted_stop(toy: dict) -> None:
    toy["stops"]["exhausted"] = {"need": "retry", "reenter": "draft"}


def _quota_wait_stop(toy: dict) -> None:
    toy["stops"]["quota-wait"] = {"need": "retry", "reenter": "draft"}


def _entry_id_with_newline(toy: dict) -> None:
    step(toy, "scope")["id"] = "scope\n"


def _exhausted_reply_value(schema: dict) -> None:
    schema["properties"]["status"]["enum"].append("exhausted")


def _each_over(path: str) -> Callable[[dict], None]:
    def change(toy: dict) -> None:
        children = step(toy, "children")
        children["in"] = [path]
        children["each"] = path
    return change


def _drop_first_pass_set(toy: dict) -> None:
    del step(toy, "review")["members"][0]["pass"]


def _no_reply_reaches_the_reviewers(toy: dict) -> None:
    step(toy, "draft")["on"]["no-reply"] = "review"


def _summary_with_min_length(schema: dict) -> None:
    schema["properties"]["summary"] = {"type": "string", "minLength": 1}


def _out_of_bounds_stop(toy: dict) -> None:
    toy["stops"]["out-of-bounds"] = {"need": "retry", "reenter": "draft"}


def _out_of_bounds_reply_value(schema: dict) -> None:
    schema["properties"]["status"]["enum"].append("out-of-bounds")


def _bound_route_to_review(toy: dict) -> None:
    step(toy, "draft")["on"]["out-of-bounds"] = "review"


def _exhausted_route_to_children(toy: dict) -> None:
    step(toy, "draft")["on"]["exhausted"] = "children"


def _bound_retries_and_exhausted_route_to_children(toy: dict) -> None:
    _exhausted_route_to_children(toy)
    step(toy, "draft")["on"]["out-of-bounds"] = "draft"


CASES = [
    Case("undefined_step_field",
         editing("toy", _set(lambda toy: step(toy, "draft"), "timeout", 5)),
         [("toy", "draft", "undefined_field")]),
    Case("version_member_in_header", editing("toy", _add_version),
         [("toy", None, "undefined_field")]),
    Case("stage_outside_the_list",
         editing("toy", _set(lambda toy: step(toy, "draft"), "stage", "testing")),
         [("toy", "draft", "unknown_stage")]),
    Case("repeated_step_id", editing("toy", _repeat_scope),
         [("toy", "scope", "duplicate_step")]),
    Case("zero_max_visits",
         editing("toy", _set(lambda toy: step(toy, "draft"), "max_visits", 0)),
         [("toy", "draft", "invalid_field")]),
    Case("unsupported_format", editing("toy", _set(lambda toy: toy, "format", 2)),
         [("toy", None, "invalid_field")]),
    Case("unknown_need", editing("toy", _unknown_need),
         [("toy", None, "invalid_field")]),
    Case("group_member_with_on",
         editing("toy", _set(lambda toy: step(toy, "review-a"), "on", {"approve": "tally"})),
         [("toy", "review-a", "invalid_field")]),
    Case("unreadable_child", _write_broken_child,
         [("toy-child", None, "unreadable_procedure")]),
    Case("keep_alive_reads_a_step_result",
         editing("toy", _set(lambda toy: toy["keep_alive"], "in", ["draft.summary"])),
         [("toy", None, "invalid_field")]),
    Case("transition_to_a_missing_step", editing("toy", _reroute_tally),
         [("toy", "tally", "unknown_target")]),
    Case("stop_reenters_a_missing_step", editing("toy", _reenter_nowhere),
         [("toy", None, "unknown_target")]),
    Case("unknown_command_id",
         editing("toy", _set(lambda toy: step(toy, "scope"), "command", "nope")),
         [("toy", "scope", "unknown_command")]),
    Case("unknown_keep_alive",
         editing("toy", _set(lambda toy: toy["keep_alive"], "command", "nope")),
         [("toy", None, "unknown_command")]),
    Case("keep_alive_without_a_claim_lost_stop", editing("toy", _no_claim_lost_stop),
         [("toy", None, "missing_claim_lost")]),
    Case("claim_lost_recovery_without_a_mutating_step",
         editing("toy-child", _recovery_without_a_mutating_step),
         [("toy-child", "recover", "unreachable_step")]),
    Case("claim_lost_recovery_without_a_keep_alive",
         editing("toy-child", _recovery_without_a_keep_alive),
         [("toy-child", "recover", "unreachable_step")]),
    Case("claim_lost_recovery_reads_the_result_of_the_step_it_guards",
         editing("toy-child", _recovery_reading("b.anything")),
         [("toy-child", "r", "unproduced_input")]),
    Case("claim_lost_recovery_reads_the_result_of_the_first_step_it_guards",
         editing("toy-child", _first_step_recovery_reading("claim.verdict")),
         [("toy-child", "recover", "unproduced_input")]),
    Case("subcommand_on_a_plain_command",
         editing("toy", _set(lambda toy: step(toy, "scope"), "subcommand", "run")),
         [("toy", "scope", "unknown_command")]),
    Case("command_without_declared_verdicts", editing("toy", _undeclared_command),
         [("toy", "scope", "undeclared_verdicts")]),
    Case("subcommand_without_declared_verdicts",
         editing("toy-child", _set(lambda toy: step(toy, "claim"), "subcommand", "release")),
         [("toy-child", "claim", "undeclared_verdicts")]),
    Case("unknown_role",
         editing("toy", _set(lambda toy: step(toy, "review-b"), "role", "auditor")),
         [("toy", "review-b", "unknown_role")]),
    Case("missing_prompt_file",
         editing("toy", _set(lambda toy: step(toy, "draft"), "prompt", "toy-nope.md")),
         [("toy", "draft", "missing_prompt")]),
    Case("missing_reply_schema",
         editing("toy", _set(lambda toy: step(toy, "draft"), "reply", "toy-nope.reply.json")),
         [("toy", "draft", "missing_reply")]),
    Case("reply_without_outcome_enum", _editing_draft_reply(_drop_outcome_enum),
         [("toy", "draft", "invalid_reply")]),
    Case("reply_outcome_not_required", _editing_draft_reply(_outcome_not_required),
         [("toy", "draft", "invalid_reply")]),
    Case("unknown_grader",
         editing("toy", _set(lambda toy: step(toy, "tally"), "grader", "nope")),
         [("toy", "tally", "unknown_grader")]),
    Case("missing_child_procedure",
         editing("toy", _set(lambda toy: step(toy, "children"), "procedure", "toy-nope")),
         [("toy", "children", "missing_procedure")]),
    Case("unreachable_step", editing("toy", _add_orphan),
         [("toy", "orphan", "unreachable_step")]),
    Case("unreachable_done",
         editing("toy", _set(lambda toy: step(toy, "children")["on"], "done", "needs-owner")),
         [("toy", None, "unreachable_done")]),
    Case("done_only_through_an_impossible_exhausted",
         editing("toy-child", _claim_reaches_done_only_through_exhausted),
         [("toy-child", None, "unreachable_done")]),
    Case("reply_enum_outcome_unmapped", _editing_draft_reply(_add_enum_outcome),
         [("toy", "draft", "unmapped_outcome")]),
    Case("command_verdict_unmapped",
         editing("toy-child", _without(lambda toy: step(toy, "claim")["on"], "stale")),
         [("toy-child", "claim", "unmapped_outcome")]),
    Case("grader_outcome_unmapped",
         editing("toy", _without(lambda toy: step(toy, "tally")["on"], "revise")),
         [("toy", "tally", "unmapped_outcome")]),
    Case("exhausted_unmapped_on_a_cycle",
         editing("toy", _without(lambda toy: step(toy, "review")["on"], "exhausted")),
         [("toy", "review", "unmapped_outcome")]),
    Case("exhausted_unmapped_on_a_cycle_a_stop_closes",
         editing("toy", _stop_reenters_a_repair_step_that_returns_to_scope),
         [("toy", "scope", "unmapped_outcome"), ("toy", "repair", "unmapped_outcome"),
          ("toy", "children", "unmapped_outcome")]),
    Case("exhausted_target_reenters_a_loop_a_stop_closes",
         editing("toy", _exhausted_scope_hands_over_to_the_repair_a_stop_enters),
         [("toy", "scope", "unbounded_cycle")]),
    Case("group_blocked_unmapped",
         editing("toy", _without(lambda toy: step(toy, "review")["on"], "blocked")),
         [("toy", "review", "unmapped_outcome")]),
    Case("child_stop_unmapped",
         editing("toy", _without(lambda toy: step(toy, "children")["on"], "child-stop")),
         [("toy", "children", "unmapped_outcome")]),
    Case("cycle_without_a_bound", editing("toy", _unbound_the_loop),
         [("toy", "draft", "unbounded_cycle")]),
    Case("exhausted_reenters_its_loop",
         editing("toy", _set(lambda toy: step(toy, "draft")["on"], "exhausted", "review")),
         [("toy", "draft", "unbounded_cycle")]),
    Case("outcome_the_step_cannot_produce",
         editing("toy", _set(lambda toy: step(toy, "draft")["on"], "maybe", "review")),
         [("toy", "draft", "unknown_outcome")]),
    Case("pass_set_outcome_the_member_cannot_produce", editing("toy", _pass_set_with_maybe),
         [("toy", "review", "unknown_outcome")]),
    Case("input_not_produced_on_every_route",
         editing("toy", _set(lambda toy: step(toy, "scope")["on"], "failed", "children")),
         [("toy", "children", "unmapped_outcome"), ("toy", "children", "unproduced_input")]),
    Case("input_produced_only_later",
         editing("toy", _set(lambda toy: step(toy, "scope"), "in", ["run.range", "draft.summary"])),
         [("toy", "scope", "unproduced_input")]),
    Case("undeclared_run_input", editing("toy", _append_in("children", "run.ticket")),
         [("toy", "children", "unproduced_input")]),
    Case("keep_alive_reads_an_undeclared_input", editing("toy", _drop_holder_input),
         [("toy", None, "unproduced_input")]),
    Case("member_the_schema_lacks", editing("toy", _append_in("children", "draft.nope")),
         [("toy", "children", "unknown_member")]),
    Case("consumed_member_not_required", _editing_draft_reply(_items_not_required),
         [("toy", "children", "unknown_member")]),
    Case("placeholder_outside_in", _append_to_review_prompt,
         [("toy", "review-a", "unknown_placeholder")]),
    Case("prompt_symlinked_outside_the_directory", _link_outside("toy-draft.md"),
         [("toy", "draft", "missing_prompt")]),
    Case("reply_symlinked_outside_the_directory", _link_outside("toy-draft.reply.json"),
         [("toy", "draft", "missing_reply")]),
    Case("procedure_symlinked_outside_the_directory", _link_outside("toy-child.json"),
         [("toy-child", None, "unreadable_procedure")]),
    Case("prompt_that_is_not_utf8", _write_bytes("toy-draft.md", b"\xff\xfe"),
         [("toy", "draft", "missing_prompt")]),
    Case("procedure_nested_too_deeply", _write_bytes("toy-child.json", b"[" * 2000 + b"]" * 2000),
         [("toy-child", None, "unreadable_procedure")]),
    Case("exhausted_steps_hand_over_to_each_other",
         editing("toy-child", _two_exhausted_steps_hand_over),
         [("toy-child", "a", "unbounded_cycle")]),
    Case("exhausted_and_ordinary_edges_loop_for_ever",
         editing("toy-child", _exhausted_and_ordinary_edges_loop),
         [("toy-child", "a", "unbounded_cycle")]),
    Case("step_id_with_a_trailing_newline", editing("toy", _entry_id_with_newline),
         [("toy", "scope\n", "invalid_field")]),
    Case("stop_named_exhausted", editing("toy", _exhausted_stop),
         [("toy", None, "invalid_field")]),
    Case("stop_named_quota_wait", editing("toy", _quota_wait_stop),
         [("toy", None, "invalid_field")]),
    Case("no_reply_to_a_reader_of_the_reply", editing("toy", _no_reply_to_review),
         [("toy", "children", "unproduced_input"), ("toy", "review-a", "unproduced_input"),
          ("toy", "review-b", "unproduced_input")]),
    Case("reply_enum_value_named_exhausted", _editing_draft_reply(_exhausted_reply_value),
         [("toy", "draft", "invalid_reply")]),
    Case("each_over_a_string", editing("toy", _each_over("draft.summary")),
         [("toy", "children", "each_not_a_list")]),
    Case("each_over_a_run_input", editing("toy", _each_over("run.issue")),
         [("toy", "children", "each_not_a_list")]),
    Case("each_over_a_decide_verdict", editing("toy", _each_over("tally.verdict")),
         [("toy", "children", "each_not_a_list")]),
    Case("each_over_a_command_string", editing("toy", _each_over("scope.range")),
         [("toy", "children", "each_not_a_list")]),
    Case("each_over_a_missing_member", editing("toy", _each_over("draft.missing")),
         [("toy", "children", "unknown_member")]),
    Case("group_pass_unmapped",
         editing("toy", _without(lambda toy: step(toy, "review")["on"], "pass")),
         [("toy", "review", "unmapped_outcome")]),
    Case("call_done_unmapped",
         editing("toy", _set(lambda toy: step(toy, "children"), "on", {"child-stop": "done"})),
         [("toy", "children", "unmapped_outcome")]),
    Case("group_member_without_a_pass_set", editing("toy", _drop_first_pass_set),
         [("toy", "review", "invalid_field")]),
    Case("parallel_below_one",
         editing("toy", _set(lambda toy: step(toy, "children"), "parallel", 0)),
         [("toy", "children", "invalid_field")]),
    Case("step_without_holds",
         editing("toy", _without(lambda toy: step(toy, "scope"), "holds")),
         [("toy", "scope", "invalid_field")]),
    Case("holds_outside_the_three_values",
         editing("toy", _set(lambda toy: step(toy, "scope"), "holds", "forever")),
         [("toy", "scope", "invalid_field")]),
    Case("group_member_without_holds",
         editing("toy", _without(lambda toy: step(toy, "review-a"), "holds")),
         [("toy", "review-a", "invalid_field")]),
    Case("mutating_command_without_check",
         editing("toy-child", _without(lambda toy: step(toy, "claim"), "check")),
         [("toy-child", "claim", "invalid_field")]),
    Case("check_on_a_step_that_does_not_mutate",
         editing("toy", _set(lambda toy: step(toy, "scope"), "check", {"command": "diff-scope"})),
         [("toy", "scope", "invalid_field")]),
    Case("check_that_is_not_an_object",
         editing("toy-child", _set(lambda toy: step(toy, "claim"), "check", "forge-claim")),
         [("toy-child", "claim", "invalid_field")]),
    Case("check_with_an_undefined_member",
         editing("toy-child", _set(lambda toy: step(toy, "claim")["check"], "timeout", 5)),
         [("toy-child", "claim", "undefined_field")]),
    Case("check_with_an_unknown_command",
         editing("toy-child", _set(lambda toy: step(toy, "claim")["check"], "command", "nope")),
         [("toy-child", "claim", "unknown_command")]),
    Case("agent_step_without_no_reply", editing("toy", _drop_on("draft", "no-reply")),
         [("toy", "draft", "unmapped_outcome")]),
    Case("reply_enum_value_named_no_reply", _editing_draft_reply(_no_reply_reply_value),
         [("toy", "draft", "invalid_reply")]),
    Case("pass_set_naming_no_reply", editing("toy", _pass_set_with_no_reply),
         [("toy", "review", "unknown_outcome")]),
    Case("no_reply_edge_to_steps_reading_the_empty_result",
         editing("toy", _no_reply_reaches_the_reviewers),
         [("toy", "review-a", "unproduced_input"), ("toy", "review-b", "unproduced_input"),
          ("toy", "children", "unproduced_input")]),
    Case("reply_schema_outside_the_subset",
         _editing_draft_reply(_summary_with_min_length),
         [("toy", "draft", "unsupported_reply")]),
    Case("agent_step_without_out_of_bounds",
         editing("toy", _without(lambda toy: step(toy, "draft")["on"], "out-of-bounds")),
         [("toy", "draft", "unmapped_outcome")]),
    Case("reply_enum_value_named_out_of_bounds", _editing_draft_reply(_out_of_bounds_reply_value),
         [("toy", "draft", "invalid_reply")]),
    Case("stop_named_out_of_bounds", editing("toy", _out_of_bounds_stop),
         [("toy", None, "invalid_field")]),
    Case("bound_route_reaches_a_reply_reader", editing("toy", _bound_route_to_review),
         [("toy", "review-a", "unproduced_input"), ("toy", "review-b", "unproduced_input"),
          ("toy", "children", "unproduced_input")]),
    Case("exhausted_route_after_a_retried_bound_reaches_a_reply_reader",
         editing("toy", _bound_retries_and_exhausted_route_to_children),
         [("toy", "children", "unproduced_input")]),
    Case("step_overrides_a_bound",
         editing("toy", _set(lambda toy: step(toy, "draft"), "max_turns", 5)),
         [("toy", "draft", "undefined_field")]),
]

SIDE_EFFECT_SCRIPT = r"""
import contextlib, io, json, os, socket, subprocess, sys
from unittest import mock

assert not any(m == "agent_tools" or m.startswith("agent_tools.") for m in sys.modules)
targets = {
    "Popen": (subprocess, "Popen"),
    "posix_spawn": (os, "posix_spawn"),
    "posix_spawnp": (os, "posix_spawnp"),
    "fork": (os, "fork"),
    "system": (os, "system"),
    "socket": (socket, "socket"),
}
mocks = {}
for name, (owner, attribute) in targets.items():
    mocks[name] = mock.patch.object(owner, attribute, side_effect=AssertionError("side effect")).start()

import agent_tools.delivery.engine as engine

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    first = engine.main(["check"])
    second = engine.main(["check", "--procedures", sys.argv[1]])
sys.__stdout__.write(json.dumps({"called": sorted(n for n, m in mocks.items() if m.called),
                                 "codes": [first, second]}) + "\n")
"""


class ToyProcedureTest(unittest.TestCase):
    def test_engine_check_passes_the_shipped_toy(self):
        code, out, err = run_check()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, compact({"procedures": ["toy", "toy-child"], "verdict": "ok"}))

    def test_a_command_step_may_map_out_of_bounds(self):
        def map_bound(toy: dict) -> None:
            step(toy, "scope")["on"]["out-of-bounds"] = "needs-owner"
        code, out, _ = run_check("--procedures", str(broken_copy(editing("toy", map_bound))))
        self.assertEqual((code, out), (0, compact({"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_an_exhausted_retry_loop_may_feed_a_reader_of_its_reply(self):
        code, out, _ = run_check("--procedures", str(broken_copy(editing("toy", _exhausted_route_to_children))))
        self.assertEqual((code, out), (0, compact({"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_a_decide_step_cannot_map_out_of_bounds(self):
        def map_bound(toy: dict) -> None:
            step(toy, "tally")["on"]["out-of-bounds"] = "needs-owner"
        code, out, _ = run_check("--procedures", str(broken_copy(editing("toy", map_bound))))
        self.assertEqual(code, 1)
        self.assertEqual(
            [(r["procedure"], r["step"], r["defect"]) for r in json.loads(out)["refusals"]],
            [("toy", "tally", "unknown_outcome")])

    def test_a_procedure_with_no_keep_alive_passes_the_check(self):
        def drop_keep_alive(directory: Path) -> None:
            for name in ("toy", "toy-child"):
                doc = load(directory, name)
                del doc["keep_alive"]
                save(directory, name, doc)
        code, out, _ = run_check("--procedures", str(broken_copy(drop_keep_alive)))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_a_procedure_with_no_keep_alive_needs_no_claim_lost_stop(self):
        def drop_keep_alive_and_claim_lost(directory: Path) -> None:
            toy, child = load(directory, "toy"), load(directory, "toy-child")
            del toy["keep_alive"], child["keep_alive"], child["stops"]["claim-lost"]
            del step(toy, "children")["on"]["claim-lost"]
            save(directory, "toy", toy)
            save(directory, "toy-child", child)
        code, out, _ = run_check("--procedures", str(broken_copy(drop_keep_alive_and_claim_lost)))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_the_toy_has_all_five_kinds_a_stop_and_a_bounded_loop(self):
        toy = load(PROCEDURES, "toy")
        self.assertEqual({item["kind"] for item in toy["steps"]},
                         {"command", "agent", "decide", "group", "call"})
        self.assertTrue(toy["stops"])
        self.assertEqual(step(toy, "draft")["on"]["drafted"], "review")
        self.assertEqual(step(toy, "review")["on"]["pass"], "tally")
        self.assertEqual(step(toy, "tally")["on"]["revise"], "draft")
        for step_id in ("draft", "review", "tally"):
            item = step(toy, step_id)
            self.assertIs(type(item["max_visits"]), int)
            self.assertGreaterEqual(item["max_visits"], 1)
            self.assertIn(item["on"]["exhausted"], toy["stops"])

    def test_the_toy_maps_no_reply_to_the_retry_stop_step_failed(self):
        toy = load(PROCEDURES, "toy")
        self.assertEqual(step(toy, "draft")["on"]["no-reply"], "step-failed")
        self.assertEqual(toy["stops"]["step-failed"]["need"], "retry")

    def test_every_stage_is_accepted(self):
        stages = ("setup", "planning", "plan review", "building", "final review",
                  "verifying", "awaiting look", "landing", "closing out", "done")
        for stage in stages:
            with self.subTest(stage=stage):
                directory = broken_copy(
                    editing("toy", _set(lambda toy: step(toy, "draft"), "stage", stage)))
                code, out, _ = run_check("--procedures", str(directory))
                self.assertEqual((code, out), (0, compact(
                    {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_each_holds_value_is_accepted(self):
        for value in ("run", "head", "live"):
            with self.subTest(value=value):
                directory = broken_copy(
                    editing("toy", _set(lambda toy: step(toy, "scope"), "holds", value)))
                code, out, _ = run_check("--procedures", str(directory))
                self.assertEqual((code, out), (0, compact(
                    {"procedures": ["toy", "toy-child"], "verdict": "ok"})))


class NoReplyOutcomeTest(unittest.TestCase):
    def test_an_agent_step_may_map_no_reply_and_a_command_step_may_not(self):
        with self.subTest("agent step"):
            directory = broken_copy(editing(
                "toy", _set(lambda toy: step(toy, "draft")["on"], "no-reply", "needs-owner")))
            code, out, _ = run_check("--procedures", str(directory))
            self.assertEqual((code, out), (0, compact(
                {"procedures": ["toy", "toy-child"], "verdict": "ok"})))
        with self.subTest("command step"):
            directory = broken_copy(editing(
                "toy", _set(lambda toy: step(toy, "scope")["on"], "no-reply", "needs-owner")))
            code, out, _ = run_check("--procedures", str(directory))
            document = json.loads(out)
            self.assertEqual(code, 1)
            self.assertEqual([(r["procedure"], r["step"], r["defect"])
                              for r in document["refusals"]],
                             [("toy", "scope", "unknown_outcome")])


class RefusedOutcomeTest(unittest.TestCase):
    def test_a_command_step_that_does_not_map_refused_is_refused_and_one_that_maps_it_is_accepted(self):
        missing = broken_copy(editing("toy", lambda doc: step(doc, "scope")["on"].pop("refused", None)))
        restored = broken_copy(editing(
            "toy", lambda doc: step(doc, "scope")["on"].update(refused="needs-owner")))
        code, out, _ = run_check("--procedures", str(missing))
        code2, out2, _ = run_check("--procedures", str(restored))
        self.assertEqual(code, 1, out)
        refusals = json.loads(out)["refusals"]
        self.assertEqual(len(refusals), 1, out)
        self.assertEqual((refusals[0]["defect"], refusals[0]["procedure"], refusals[0]["step"]),
                         ("unmapped_outcome", "toy", "scope"))
        self.assertIn("'refused'", refusals[0]["detail"])
        self.assertEqual(code2, 0, out2)
        self.assertNotIn("unknown_outcome", out2)

    def test_a_group_member_that_passes_on_refused_is_refused(self):
        def with_probe(passes: list[str]) -> Path:
            def change(doc: dict) -> None:
                probe = {key: value for key, value in step(doc, "scope").items() if key != "on"}
                probe["id"] = "probe"
                group = next(item for item in doc["steps"] if item["kind"] == "group")
                doc["steps"].insert(doc["steps"].index(group), probe)
                group["members"].append({"step": "probe", "pass": passes})
            return broken_copy(editing("toy", change))

        code, out, _ = run_check("--procedures", str(with_probe(["ok", "refused"])))
        self.assertEqual(code, 1, out)
        refusals = json.loads(out)["refusals"]
        self.assertEqual(len(refusals), 1, out)
        self.assertEqual((refusals[0]["defect"], refusals[0]["procedure"], refusals[0]["step"]),
                         ("unknown_outcome", "toy", "review"))
        self.assertIn("'refused'", refusals[0]["detail"])
        self.assertIn("'probe'", refusals[0]["detail"])
        code2, out2, _ = run_check("--procedures", str(with_probe(["ok"])))
        self.assertEqual(code2, 0, out2)


class RefusalTableTest(unittest.TestCase):
    def test_each_case_is_refused_by_step_and_defect(self):
        for case in CASES:
            with self.subTest(case.name):
                code, out, _ = run_check("--procedures", str(broken_copy(case.mutate)))
                document = json.loads(out)
                self.assertEqual(code, 1)
                self.assertEqual(document["verdict"], "refused")
                for refusal in document["refusals"]:
                    self.assertEqual(sorted(refusal), ["defect", "detail", "procedure", "step"])
                    self.assertIsInstance(refusal["detail"], str)
                    self.assertTrue(refusal["detail"])
                self.assertEqual(
                    sorted((r["procedure"], r["step"] or "", r["defect"])
                           for r in document["refusals"]),
                    sorted((p, s or "", d) for p, s, d in case.expected))

    def test_every_defect_has_a_table_case(self):
        self.assertEqual({d for c in CASES for _, _, d in c.expected},
                         set(procedure_check.DEFECTS))


class RefusalDetailTest(unittest.TestCase):
    def test_a_schema_outside_the_subset_names_the_schema_and_the_construct(self):
        directory = broken_copy(_editing_draft_reply(_summary_with_min_length))
        code, out, _ = run_check("--procedures", str(directory))
        refusals = json.loads(out)["refusals"]
        self.assertEqual(code, 1)
        self.assertEqual(len(refusals), 1)
        self.assertIn("toy-draft.reply.json", refusals[0]["detail"])
        self.assertIn("minLength", refusals[0]["detail"])


def _object(**properties: object) -> dict:
    return {"type": "object", "properties": properties, "additionalProperties": False}


class ReplySubsetTest(unittest.TestCase):
    def test_the_subset_schemas_pass(self):
        for path in sorted(PROCEDURES.glob("*.reply.json")):
            with self.subTest(path.name):
                self.assertIsNone(engine_reply.schema_problem(
                    json.loads(path.read_text(encoding="utf-8"))))
        schema = {"type": "object",
                  "properties": {"n": {"type": "integer"}, "ok": {"type": "boolean"},
                                 "tags": {"type": "array",
                                          "items": {"enum": ["a", "b"], "type": "string"}},
                                 "inner": {"type": "object", "properties": {},
                                           "additionalProperties": False}},
                  "required": ["n"], "additionalProperties": False}
        self.assertIsNone(engine_reply.schema_problem(schema))

    def test_each_construct_outside_the_subset_is_named(self):
        rows = [
            ({"type": "number"}, "number"),
            ({"type": ["string", "null"]}, "type"),
            ({"const": "x"}, "const"),
            ({"oneOf": [{"type": "string"}]}, "oneOf"),
            ({"$ref": "#/x"}, "$ref"),
            ({"type": "string", "description": "d"}, "description"),
            ({"type": "string", "pattern": "a"}, "pattern"),
            ({"enum": [1, 2]}, "enum"),
            ({"enum": []}, "enum"),
            ({"enum": ["a", "a"]}, "enum"),
            ({"type": "array"}, "items"),
            ({"type": "object", "properties": {}}, "additionalProperties"),
        ]
        for node, word in rows:
            with self.subTest(node=node):
                problem = engine_reply.schema_problem(_object(p=node))
                self.assertIsNotNone(problem)
                self.assertIn(word, problem)
        open_root = {"type": "object", "properties": {}, "additionalProperties": True}
        self.assertIn("additionalProperties", engine_reply.schema_problem(open_root))
        absent = {"type": "object", "properties": {}, "required": ["absent"],
                  "additionalProperties": False}
        self.assertIn("absent", engine_reply.schema_problem(absent))
        self.assertIn("not an object", engine_reply.schema_problem([]))

    def test_a_phrase_names_where_the_construct_is(self):
        self.assertEqual(
            engine_reply.schema_problem(_object(summary={"type": "string", "minLength": 1})),
            "the keyword 'minLength' at reply.properties.summary")
        self.assertEqual(
            engine_reply.schema_problem(_object(n={"type": "number"})),
            "the type 'number' at reply.properties.n")
        self.assertEqual(
            engine_reply.schema_problem({"type": "object", "properties": {}}),
            "an object with no additionalProperties false at reply")
        self.assertEqual(
            engine_reply.schema_problem(_object(a={"type": "array", "items": {"type": "number"}})),
            "the type 'number' at reply.properties.a.items")

    def test_the_root_must_be_an_object_node(self):
        for node in ({"type": "string"}, {"enum": ["a"]},
                     {"type": "array", "items": {"type": "string"}}):
            with self.subTest(node=node):
                problem = engine_reply.schema_problem(node)
                self.assertIsNotNone(problem)
                self.assertIn("root", problem)
                self.assertIsNone(engine_reply.schema_problem(_object(p=node)))


class ReplyValidatorTest(unittest.TestCase):
    def test_a_reply_is_checked_against_exactly_the_subset(self):
        draft = json.loads((PROCEDURES / "toy-draft.reply.json").read_text(encoding="utf-8"))
        good = {"status": "drafted", "summary": "s", "items": ["a"]}
        self.assertIsNone(engine_reply.reply_problem(draft, good))
        bad = {
            "extra member": {"status": "drafted", "summary": "s", "items": [], "extra": 1},
            "outside the enum": {**good, "status": "maybe"},
            "wrong type": {**good, "summary": 3},
            "wrong item type": {**good, "items": [1]},
            "missing member": {"summary": "s", "items": []},
        }
        for name, reply in bad.items():
            with self.subTest(name):
                self.assertIsNotNone(engine_reply.reply_problem(draft, reply))
        integer = _object(n={"type": "integer"})
        self.assertIsNotNone(engine_reply.reply_problem(integer, {"n": True}))
        self.assertIsNone(engine_reply.reply_problem(integer, {"n": 2}))
        self.assertIsNone(engine_reply.reply_problem(integer, {"n": 2.0}))
        self.assertIsNotNone(engine_reply.reply_problem(integer, {"n": 2.5}))
        self.assertIsNotNone(engine_reply.reply_problem(integer, {"n": float("inf")}))
        self.assertIsNotNone(engine_reply.reply_problem(integer, {"n": False}))
        self.assertIsNotNone(engine_reply.reply_problem({"type": "number"}, 1))
        self.assertIsNotNone(engine_reply.reply_problem({"type": "string"}, "x"))
        self.assertIsNone(engine_reply.reply_problem(_object(s={"type": "string"}), {"s": "x"}))


class GraphTest(unittest.TestCase):
    def test_a_no_reply_edge_that_runs_the_producer_again_leaves_its_readers_unflagged(self):
        directory = broken_copy(editing("toy", _set(
            lambda toy: step(toy, "draft")["on"], "no-reply", "needs-owner")))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_a_step_reached_only_through_claim_lost_is_reachable(self):
        directory = broken_copy(editing("toy-child", _recovery))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_a_claim_lost_recovery_may_read_what_ran_before_the_guarded_step(self):
        directory = broken_copy(editing("toy-child", _recovery_reading("a.anything")))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_exhausted_may_be_mapped_off_a_cycle(self):
        directory = broken_copy(editing(
            "toy-child", _set(lambda child: step(child, "claim")["on"], "exhausted", "child-stop")))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))


class DataFlowTest(unittest.TestCase):
    def test_a_member_reads_what_precedes_its_group(self):
        directory = broken_copy(editing(
            "toy", _set(lambda toy: step(toy, "review-a"), "in", ["draft.summary", "run.issue"])))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_an_each_over_the_list_a_platform_command_publishes_is_accepted(self):
        directory = broken_copy(editing("toy", _each_over("scope.files")))
        code, out, _ = run_check("--procedures", str(directory))
        self.assertEqual((code, out), (0, compact(
            {"procedures": ["toy", "toy-child"], "verdict": "ok"})))

    def test_a_no_reply_route_bypasses_its_step_whatever_order_the_steps_are_listed_in(self):
        def agent(step_id: str, on: dict, reads: tuple[str, ...] = ()) -> dict:
            return {"id": step_id, "kind": "agent", "on": on, "in": list(reads)}

        steps = {
            "a": agent("a", {"ok": "s1"}),
            "s1": agent("s1", {"ok": "s2", "no-reply": "s2"}),
            "s2": agent("s2", {"ok": "done", "no-reply": "r"}),
            "r": agent("r", {"ok": "done"}, ("s1.x",)),
        }
        for order in (("a", "s1", "s2", "r"), ("a", "s2", "s1", "r")):
            with self.subTest(order=order):
                procedure = {"steps": [steps[name] for name in order], "stops": {}, "inputs": []}
                graph = procedure_check.result_flow_graph(procedure)
                dominating = procedure_check.dominators(graph, procedure_check.START)["r"]
                self.assertNotIn("s1(result)", dominating)

    @staticmethod
    def _dominating(procedure: dict, reader: str) -> frozenset[str]:
        graph = procedure_check.result_flow_graph(procedure)
        return procedure_check.dominators(graph, procedure_check.START)[reader]

    def test_a_no_reply_route_into_a_mutating_step_can_still_lose_its_claim(self):
        def agent(step_id: str, on: dict, reads: tuple[str, ...] = ()) -> dict:
            return {"id": step_id, "kind": "agent", "on": on, "in": list(reads)}

        procedure = {
            "inputs": [], "keep_alive": {"command": "k", "in": []},
            "stops": {"claim-lost": {"need": "retry", "reenter": "r"}},
            "steps": [agent("s", {"ok": "m", "no-reply": "m"}),
                      {"id": "m", "kind": "command", "mutates": True, "on": {"ok": "done"}, "in": []},
                      agent("r", {"ok": "done"}, ("s.x",))]}
        graph = procedure_check.result_flow_graph(procedure)
        self.assertIn(procedure_check.CLAIM_LOST, graph["s"])
        self.assertNotIn("s(result)", self._dominating(procedure, "r"))

    def test_a_step_that_reaches_no_mutating_step_has_no_claim_lost_edge(self):
        def agent(step_id: str, on: dict, reads: tuple[str, ...] = ()) -> dict:
            return {"id": step_id, "kind": "agent", "on": on, "in": list(reads)}

        procedure = {
            "inputs": [], "keep_alive": {"command": "k", "in": []},
            "stops": {"claim-lost": {"need": "retry", "reenter": "r"}},
            "steps": [agent("s", {"ok": "done", "no-reply": "m"}),
                      {"id": "m", "kind": "command", "mutates": True, "on": {"ok": "done"}, "in": []},
                      agent("r", {"ok": "done"}, ("s.x",))]}
        graph = procedure_check.result_flow_graph(procedure)
        self.assertNotIn(procedure_check.CLAIM_LOST, graph["s(result)"])
        self.assertIn(procedure_check.CLAIM_LOST, graph["s"])

    def test_an_exhausted_entry_after_a_no_reply_does_not_credit_the_reply(self):
        def agent(step_id: str, on: dict, reads: tuple[str, ...] = (), **more) -> dict:
            return {"id": step_id, "kind": "agent", "on": on, "in": list(reads), **more}

        procedure = {
            "inputs": [], "stops": {},
            "steps": [agent("a", {"ok": "done", "no-reply": "a", "exhausted": "reader"}, max_visits=1),
                      agent("reader", {"ok": "done"}, ("a.x",))]}
        self.assertNotIn("a(result)", self._dominating(procedure, "reader"))

    def test_an_exhausted_target_that_is_itself_a_no_reply_step_is_split_too(self):
        def agent(step_id: str, on: dict, reads: tuple[str, ...] = (), **more) -> dict:
            return {"id": step_id, "kind": "agent", "on": on, "in": list(reads), **more}

        procedure = {
            "inputs": [], "stops": {},
            "steps": [agent("a", {"ok": "p", "no-reply": "a", "exhausted": "s2"}, max_visits=1),
                      agent("p", {"ok": "s2"}),
                      agent("s2", {"ok": "done", "no-reply": "t"}),
                      agent("t", {"ok": "done"}, ("p.x",))]}
        self.assertNotIn("p", self._dominating(procedure, "t"))


class RoleTest(unittest.TestCase):
    def test_each_role_has_its_agent_file(self):
        for name in procedure_check.ROLES:
            with self.subTest(name=name):
                self.assertTrue(
                    (REPO_ROOT / "home/common/claude-code/agents" / f"{name}.md").is_file())


class NoSideEffectTest(unittest.TestCase):
    def test_check_starts_no_process_and_opens_no_socket(self):
        broken = broken_copy(editing("toy", _repeat_scope))
        done = subprocess.run([sys.executable, "-c", SIDE_EFFECT_SCRIPT, str(broken)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"called": [], "codes": [0, 1]})

    def test_the_check_modules_import_no_process_or_socket_module(self):
        for name in ("engine.py", "procedure_check.py", "engine_graders.py", "engine_caps.py",
                     "engine_reply.py"):
            tree = ast.parse((DELIVERY / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                for module in imported:
                    self.assertNotIn(module.split(".")[0], ("subprocess", "socket"), name)


class UsageTest(unittest.TestCase):
    def test_a_missing_directory_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_check("--procedures", f"{tmp}/absent")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_a_directory_without_procedures_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_check("--procedures", tmp)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_a_bad_argument_returns_2_with_one_stderr_line(self):
        for argv in (["check", "--bogus"], [], ["check", "--procedures"]):
            with self.subTest(argv=argv):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = engine.main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_an_invalid_declarations_file_is_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(procedure_check, "load_commands",
                               side_effect=procedure_check.DeclarationError("bad")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = engine.main(["check"])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(len(err.getvalue().splitlines()), 1)


class DeclarationTest(unittest.TestCase):
    def test_the_declarations_name_every_command_table_row(self):
        self.assertIn("engine", table_rows())
        self.assertEqual(set(load_commands()), set(table_rows()))

    def test_the_toy_commands_declare_their_verdicts(self):
        commands = load_commands()
        self.assertEqual(commands["forge-claim"], CommandDeclaration(None, {
            "acquire": ("acquired", "already_held", "held_by", "lost_to", "error"),
            "renew": ("renewed", "not_held", "error"),
            "status": ("free", "held_by", "stale", "error")}))
        self.assertEqual(commands["diff-scope"].outcomes(None), ("ok", "failed"))
        self.assertIsNone(commands["diff-scope"].outcomes("x"))
        self.assertEqual(commands["forge-claim"].outcomes("acquire"),
                         ("acquired", "already_held", "held_by", "lost_to", "error"))
        self.assertEqual(commands["look-approval"].outcomes("marked"),
                         ("marked", "unmarked", "error"))
        self.assertEqual(commands["resolve-project"].outcomes("resolve"), ("ok", "failed"))
        self.assertIsNone(commands["engine"])

    def test_a_malformed_declaration_is_refused(self):
        bad = ['{"x": {"verdicts": [], "subcommands": {"a": []}}}',
               '{"x": {"verdicts": ["a", "a"]}}',
               '{"x": {"subcommands": {}}}',
               '{"x": {"argv": ["a"]}}',
               '{"x": {"verdicts": ["ok", "exhausted"]}}',
               '{"x": {"subcommands": {"a": ["exhausted"]}}}',
               '{"x": {"verdicts": ["ok", "out-of-bounds"]}}',
               '{"x": {"subcommands": {"a": ["out-of-bounds"]}}}',
               '{"X": null}']
        with tempfile.TemporaryDirectory() as tmp:
            for index, text in enumerate(bad):
                with self.subTest(text):
                    path = Path(tmp) / f"declarations-{index}.json"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(procedure_check.DeclarationError):
                        load_commands(path)


class GraderTest(unittest.TestCase):
    GRADER_CASES = [
        ("toy-tally", {"review-a.verdict": "approve", "review-b.verdict": "approve"}, "accept"),
        ("toy-tally", {"review-a.verdict": "approve", "review-b.verdict": "revise"}, "revise"),
    ]

    def test_each_grader_case_grades_its_outcome(self):
        for name, results, expected in self.GRADER_CASES:
            with self.subTest(name=name, results=results):
                self.assertEqual(GRADERS[name].grade(results), expected)

    def test_every_declared_grader_outcome_is_produced(self):
        for name in GRADERS:
            with self.subTest(name=name):
                self.assertEqual({e for n, _, e in self.GRADER_CASES if n == name},
                                 set(GRADERS[name].outcomes))


if __name__ == "__main__":
    unittest.main()
