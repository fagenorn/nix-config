"""`engine`: run the delivery engine's commands (#1508).

`engine check [--procedures <dir>]` reads the procedure files of a directory
(default: the package's `procedures` directory) and prints one line of compact
sorted-key JSON to stdout, starting no process and opening no socket:

- exit 0: `{"procedures": [<names>], "verdict": "ok"}`;
- exit 1: `{"breaches": [{"cap", "size", "thing", "unit"}, ...], "refusals":
  [{"defect", "detail", "procedure", "step"}, ...], "verdict": "refused"}`,
  refusals ordered by procedure name, phase, then step position, and both
  members always present;
- exit 2, stdout empty and one stderr line: a usage error, `--procedures` not a
  directory, a directory with no procedure file, or an invalid
  `command_verdicts.json`.

The procedure format and every refusal code are `procedure_check`'s contract.
In a directory an onboarded project owns, the command ids checked are the
platform's plus the project's, the ones `engine deliver` accepts; elsewhere
they are the platform's.
The check also lists in `breaches` each cap of `engine_caps` the core, the
engine package, a procedure, the graders or a prompt file exceeds; nothing
changes a cap.

`engine status <issue> [--project <slug>]` reads the newest run of the issue
under `~/.agents/state/engine/runs/` (the run directory `engine_ledger`
describes) and prints one line of compact sorted-key JSON, the state one fold
derives from the run's `events.jsonl`. It writes nothing and creates no
directory:

- exit 0: the folded state (`engine_ledger.RunState.as_json()`);
- exit 1: `{"issue": <n>, "run": null}`, no run of that issue (and project);
- exit 2, stdout empty and one stderr line: a usage error, an issue that is not
  an integer of 1 or more, runs of several projects with no `--project`, an
  unreadable `run.json`, or an event file the ledger refuses.

`engine deliver <issue> [--procedures <dir>]` runs `<dir>/deliver.json` (a
procedure of `command` and `decide` steps; default: the package's `procedures`
directory) for the issue, in the project the current directory belongs to, to
`done` or a stop, and prints one line of compact sorted-key JSON when it ends
(`engine_shell` is the contract):

- exit 0: `{"detail", "end": "done", "need": null, "run"}`;
- exit 3: `{"detail", "end": <stop name>, "need": <stop need>, "run"}`;
- exit 4: `{"detail", "end": null, "need": null, "process": {"pid", "started"},
  "run"}`, another deliver of the issue holds its run's lock; nothing is written;
- exit 1, stdout empty and one stderr line: a fault during the run;
- exit 2, stdout empty and one stderr line: a usage error, or a refusal before
  any run exists, which creates no run directory.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import sys
from pathlib import Path

from agent_tools.delivery import (
    engine_caps,
    engine_graders,
    engine_ledger,
    engine_shell,
    procedure_check,
)

ENGINE_DIR = Path(importlib.resources.files("agent_tools.delivery"))
PROCEDURES_DIR = Path(__file__).with_name("procedures")


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


class UsageError(Exception):
    pass


def _issue_number(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        raise UsageError(f"issue is not an integer: {text}") from None
    if number < 1:
        raise UsageError(f"issue must be 1 or more: {text}")
    return number


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="engine", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser(
        "check", help="refuse a malformed procedure by step and defect")
    check_parser.add_argument("--procedures", type=Path, default=PROCEDURES_DIR)
    status_parser = commands.add_parser(
        "status", help="print the state a run's recorded events fold to")
    status_parser.add_argument("issue", type=_issue_number)
    status_parser.add_argument("--project")
    deliver_parser = commands.add_parser(
        "deliver", help="run a procedure of command steps to done or a stop")
    deliver_parser.add_argument("issue", type=_issue_number)
    deliver_parser.add_argument("--procedures", type=Path, default=PROCEDURES_DIR)
    return parser


def _usage(message: str) -> int:
    sys.stderr.write("engine: " + " ".join(message.split()) + "\n")
    return 2


def _status(issue: int, project: str | None) -> int:
    try:
        run_dir = engine_ledger.find_run(engine_ledger.runs_root(), issue, project)
        if run_dir is None:
            sys.stdout.write(compact({"issue": issue, "run": None}))
            return 1
        state = engine_ledger.fold(
            engine_ledger.read_run(run_dir),
            engine_ledger.replay(run_dir / "events.jsonl"),
            engine_ledger.process_alive)
    except (engine_ledger.LedgerError, OSError, KeyError) as error:
        return _usage(str(error))
    sys.stdout.write(compact(state.as_json()))
    return 0


def _deliver(issue: int, procedures: Path) -> int:
    try:
        code, line = engine_shell.deliver(issue, procedures)
    except engine_shell.Refused as error:
        return _usage(str(error))
    except engine_shell.Fault as error:
        sys.stderr.write("engine: " + " ".join(str(error).split()) + "\n")
        return engine_shell.EXIT_FAULT
    sys.stdout.write(compact(line))
    return code


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        return _usage(str(error))
    if args.command == "status":
        return _status(args.issue, args.project)
    if args.command == "deliver":
        return _deliver(args.issue, args.procedures)
    if not args.procedures.is_dir():
        return _usage(f"--procedures is not a directory: {args.procedures}")
    try:
        commands = engine_shell.check_declarations()
        result = procedure_check.check_directory(args.procedures, commands)
        breaches = engine_caps.breaches(ENGINE_DIR, args.procedures, engine_graders.GRADERS)
    except (procedure_check.DeclarationError, engine_shell.Refused, ValueError) as error:
        return _usage(str(error))
    if result.refusals or breaches:
        sys.stdout.write(compact({"breaches": [b.as_json() for b in breaches],
                                  "refusals": [r.as_json() for r in result.refusals],
                                  "verdict": "refused"}))
        return 1
    sys.stdout.write(compact({"procedures": list(result.procedures), "verdict": "ok"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
