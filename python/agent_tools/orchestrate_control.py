"""`orchestrate-control`: the control surface of the orchestrate-issues skill (issue 403).

    orchestrate-control start --repo-root R [N ... | --label L | --milestone M] [--run-id I]

`start` runs four steps in order and stops at the first that refuses:
`bindings` (resolve the project in process and read the orchestration, tracker
and worktree bindings), `route` (`workflow-state host-route --route claude-code`,
its reply validated), `issues` (the explicit numbers in the caller's order, or
the open issues a label or milestone sweep lists, ascending) and `bootstrap`
(`workflow-state init-run`: the run for the issue set, or with `--run-id` the
run that id names, which is re-entered and never created).

Stdout is one compact JSON object and a newline. Ready (exit 0):
`{"command":"start","outcome":"ready","session":{interface_version, run_id,
issues, human_directed, source}}`. A host without the route (exit 0):
`{"command":"start","outcome":"unsupported","route":<the validated host_route>}`,
with no run created. Refused (exit 2): `{command, outcome:"refused", step,
detail, completed_steps, response}`, `detail` being one line of at most 300
characters. An invalid invocation prints `orchestrate-control: invalid
invocation` on stderr, nothing on stdout, and exits 2.

The command resolves the project in process, runs `workflow-state`,
`artifact-budget` and the bound tracker CLI by name on `PATH`, removes every
name in the contract's `unset_before_invocation` from each tracker-CLI child's
environment, and writes no file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_tools import resolve_project
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

INVALID = "orchestrate-control: invalid invocation\n"
DETAIL_LIMIT = 300
TAIL_LIMIT = 120
ROUTE = "claude-code"
INTERFACE_VERSION = 1
LISTING_LIMIT = 1000
ISSUE_NUMBER = re.compile(r"[1-9][0-9]*")


class InvocationError(Exception):
    """The command line is not a valid `orchestrate-control` invocation."""


class Refusal(Exception):
    """One step refused: its name, a one-line detail and the response it carries, if any."""

    def __init__(self, step: str, detail: str, *, response: dict | None = None) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail
        self.response = response


@dataclass(frozen=True)
class Bindings:
    """The contract members the command reads, every one required and none defaulted."""

    project_root: str
    max_parallel: int
    attempt_budget_minutes: int
    tracker_kind: str
    tracker_cli: str
    repo_slug: str
    unset: tuple[str, ...]
    worktree_root: str
    worktree_prefix: str


def _member(snapshot: Mapping, *pointer: str) -> object:
    """The snapshot member at `pointer`, or a refusal at `bindings` naming it."""
    value: object = snapshot
    for key in pointer:
        if not isinstance(value, Mapping) or key not in value:
            raise Refusal("bindings", "missing binding /" + "/".join(pointer))
        value = value[key]
    return value


def _integer(snapshot: Mapping, *pointer: str) -> int:
    value = _member(snapshot, *pointer)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise Refusal("bindings", "missing binding /" + "/".join(pointer))
    return value


def _text(snapshot: Mapping, *pointer: str, empty: bool = False) -> str:
    value = _member(snapshot, *pointer)
    if not isinstance(value, str) or not (value or empty):
        raise Refusal("bindings", "missing binding /" + "/".join(pointer))
    return value


def load_bindings(repo_root: str) -> Bindings:
    """Resolve the project at `repo_root` and read the bindings this command needs."""
    try:
        snapshot = resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        raise Refusal("bindings", f"resolve-project refused: {error.code} "
                                  f"{error.repair_id}") from error
    project_root = _text(snapshot, "project", "root")
    unset = _member(snapshot, "bindings", "tracker", "credential_env", "unset_before_invocation")
    if not isinstance(unset, list) or not all(isinstance(name, str) for name in unset):
        raise Refusal("bindings", "missing binding /bindings/tracker/credential_env"
                                  "/unset_before_invocation")
    repo_slug = _text(snapshot, "bindings", "tracker", "repo_slug")
    owner, _, name = repo_slug.partition("/")
    if not owner or not name or "/" in name:
        raise Refusal("bindings", "missing binding /bindings/tracker/repo_slug")
    worktree_root = _text(snapshot, "bindings", "vcs", "worktree", "root")
    return Bindings(
        project_root=project_root,
        max_parallel=_integer(snapshot, "bindings", "workflow", "orchestration", "max_parallel"),
        attempt_budget_minutes=_integer(snapshot, "bindings", "workflow", "orchestration",
                                        "attempt_budget_minutes"),
        tracker_kind=_text(snapshot, "bindings", "tracker", "kind"),
        tracker_cli=_text(snapshot, "bindings", "tracker", "cli"),
        repo_slug=repo_slug,
        unset=tuple(unset),
        worktree_root=os.path.normpath(os.path.join(project_root, worktree_root)),
        worktree_prefix=_text(snapshot, "bindings", "vcs", "worktree", "prefix", empty=True))


def strict_json(raw: bytes) -> object:
    """Parse `raw` as UTF-8 JSON, refusing duplicate keys and non-finite constants."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def run_child(step: str, argv: Sequence[str], *, stdin: bytes | None = None,
              env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run `argv` capturing its output, with `stdin` as its input or no input at all."""
    options: dict = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        return subprocess.run(list(argv), capture_output=True, check=False, env=env, **options)
    except OSError as error:
        raise Refusal(step, f"cannot run {argv[0]}: {error}") from error


def why(done: subprocess.CompletedProcess) -> str:
    """The tail of a failed child's stderr as `: <tail>` on one line, or `` when it said nothing."""
    tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-TAIL_LIMIT:]
    return f": {tail}" if tail else ""


def validate_bytes(step: str, raw: bytes) -> bytes:
    """`raw` as the artifact-budget authority validates it at the `workflow-response` boundary."""
    done = run_child(step, ["artifact-budget", "validate-report", "--boundary",
                            "workflow-response", "--input", "-"], stdin=raw)
    if done.returncode != 0:
        raise Refusal(step, f"validate-report refused (exit {done.returncode}){why(done)}")
    return done.stdout


def workflow_response(step: str, *argv: str, stdin: bytes | None = None) -> dict:
    """The validated JSON object `workflow-state <argv>` printed; no field is read before it
    has passed `validate-report` (D13)."""
    done = run_child(step, ["workflow-state", *argv], stdin=stdin)
    if done.returncode != 0:
        raise Refusal(step, f"workflow-state exit {done.returncode}{why(done)}")
    try:
        reply = strict_json(validate_bytes(step, done.stdout))
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        raise Refusal(step, "validate-report did not print one JSON object")
    return reply


def tracker_env(bindings: Bindings) -> dict[str, str]:
    """This process's environment less every name the contract says to unset for the tracker."""
    return {key: value for key, value in os.environ.items() if key not in bindings.unset}


def require_github(step: str, bindings: Bindings) -> None:
    if bindings.tracker_kind != "github":
        raise Refusal(step, f"tracker kind {bindings.tracker_kind} is not supported")


def sweep(bindings: Bindings, flag: str, value: str) -> list[int]:
    """The open issues `flag value` selects (`--label` or `--milestone`), ascending."""
    require_github("issues", bindings)
    cli = bindings.tracker_cli
    done = run_child("issues", [cli, "issue", "list", "--repo", bindings.repo_slug, "--state",
                                "open", flag, value, "--json", "number", "--limit",
                                str(LISTING_LIMIT)], env=tracker_env(bindings))
    if done.returncode != 0:
        raise Refusal("issues", f"{cli} exit {done.returncode}{why(done)}")
    try:
        listing = strict_json(done.stdout)
    except ValueError:
        listing = None
    if not (isinstance(listing, list) and all(
            isinstance(row, dict) and isinstance(row.get("number"), int)
            and not isinstance(row["number"], bool) and row["number"] >= 1 for row in listing)):
        raise Refusal("issues", f"{cli} did not list issue numbers")
    if len(listing) >= LISTING_LIMIT:
        raise Refusal("issues", f"the listing reached its {LISTING_LIMIT}-issue limit")
    return sorted({row["number"] for row in listing})


def _issues(args: argparse.Namespace, bindings: Bindings) -> tuple[list[int], bool, dict]:
    """The session's issue numbers, whether a human named them, and where they came from."""
    if args.numbers:
        issues = list(args.numbers)
        for number in issues:
            if issues.count(number) > 1:
                raise Refusal("issues", f"duplicate issue number {number}")
        reference = "invocation:/orchestrate-issues " + " ".join(map(str, issues))
        return issues, True, {"kind": "explicit_user", "reference": reference}
    flag, value = ("--label", args.label) if args.label is not None else \
        ("--milestone", args.milestone)
    issues = sweep(bindings, flag, value)
    if not issues:
        raise Refusal("issues", "the issue set is empty")
    return issues, False, {"kind": "standing_repository",
                           "reference": f"sweep:{flag.removeprefix('--')}:{value}"}


def _bootstrap(args: argparse.Namespace, issues: list[int]) -> str:
    """The run id `init-run` answers for the run `--run-id` names or the issue set."""
    handle = ["--run-id", args.run_id] if args.run_id else \
        ["--issue-set", "-".join(map(str, issues))]
    reply = workflow_response("bootstrap", "init-run", "--repo-root", args.repo_root, *handle)
    if reply.get("kind") != "workflow_bootstrap" \
            or (args.run_id and reply.get("run_id") != args.run_id):
        raise Refusal("bootstrap", "init-run did not answer the requested run")
    return reply["run_id"]


def start(args: argparse.Namespace, done: list[str]) -> dict:
    """Open an orchestrate-issues session; `done` collects the steps that finished."""
    bindings = load_bindings(args.repo_root)
    done.append("bindings")
    route = workflow_response("route", "host-route", "--route", ROUTE)
    if route.get("support") == "unsupported":
        return {"command": "start", "outcome": "unsupported", "route": route}
    if route.get("support") != "supported":
        raise Refusal("route", "host-route did not report a support value")
    done.append("route")
    issues, human_directed, source = _issues(args, bindings)
    done.append("issues")
    run_id = _bootstrap(args, issues)
    done.append("bootstrap")
    return {"command": "start", "outcome": "ready",
            "session": {"interface_version": INTERFACE_VERSION, "run_id": run_id,
                        "issues": issues, "human_directed": human_directed, "source": source}}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


def _issue_number(value: str) -> int:
    if ISSUE_NUMBER.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("not an issue number")
    return int(value)


def _parser() -> _Parser:
    parser = _Parser(prog="orchestrate-control",
                     description="The control surface of the orchestrate-issues skill.")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start", help="open a session and its run")
    start_parser.add_argument("--repo-root", required=True)
    start_parser.add_argument("numbers", nargs="*", type=_issue_number, metavar="N")
    sweeps = start_parser.add_mutually_exclusive_group()
    sweeps.add_argument("--label")
    sweeps.add_argument("--milestone")
    start_parser.add_argument("--run-id")
    return parser


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    args = _parser().parse_args(argv)
    given = [bool(args.numbers), args.label is not None, args.milestone is not None]
    if not os.path.isabs(args.repo_root) or sum(given) != 1:
        raise InvocationError("start takes an absolute --repo-root and exactly one of "
                              "numbers, --label and --milestone")
    return args


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
        _print({"start": start}[args.command](args, done))
    except Refusal as refusal:
        _print({"command": args.command, "outcome": "refused", "step": refusal.step,
                "detail": " ".join(refusal.detail.split())[:DETAIL_LIMIT],
                "completed_steps": list(done), "response": refusal.response})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
