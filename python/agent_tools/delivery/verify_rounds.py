"""`verify-rounds`: what a delivery's verification rounds counted, read back from its engine ledger, its
contract and its worktree; nothing here writes.

    verify-rounds round --holder H --worktree-path P
    verify-rounds round-reviewed --holder H --worktree-path P
    verify-rounds fix-range --worktree-path P --head S
    verify-rounds retested --holder H --worktree-path P

No engine module imports this module, so it is outside the engine package's line cap. A procedure cannot hold
a count a continue resets, so each is read here from the ledger, as `deliver-standard.js` held it in memory.
A continue starts a new verify run, hence the fix count is over the delivery's verify runs, not the current one.

The verify runs are the runs of `land_tally.delivery_runs(holder)` whose procedure is `VERIFY`; the current
run is the last. Each command prints one compact JSON line; a failure prints `{"verdict": "error", "error":
<code>, "detail": <text>}` and exits 1, with `error` one of `usage`, `no_run`, `no_verify_run`,
`no_verification`, `ledger_unreadable` or `contract_refused`.

`round` rules, in order, each with the program line it ports:

- no verify run is `no_verify_run`; the latest result of `VERIFICATION_STEPS` of the current run is the
  verification read, and none is `no_verification`.
- a read at a head other than the commit the last `ws-check` of the run read (the reviewed fix) is `verify`: the
  full rerun is bound to the reviewed commit, so a commit made after the review never lands unreviewed.
- a read whose verdict is `passed` is `retest` with `start_head = untested_start(runs)` when that is not None
  and not the read's own head, else `passed` (`deliver-standard.js:2941-2946`, the retest after the loop).
- any other verdict than `failed` or `dirty` is `verify` (`deliver-standard.js:2937`).
- any `fail` result with `no_slot` true is `verify`, before the dirty problem is looked at, so slot exhaustion
  never reaches a fix (`deliver-standard.js:2912`).
- (`round-reviewed` only; `round` keeps the verdicts a run saved before this subcommand maps, so a continued
  older run still validates) a run whose latest narrowing graded `findings` (a fix review with a blocking finding)
  and that no later fix review has graded, whatever transitions a continue added since, is
  `fix` while fewer than `FIX_ROUNDS` `fix` entries are over the verify runs, with each blocking finding of the
  latest fix review added to `problems` as `{id: review, status: finding, summary, file, failing_input, kind,
  reran: false}`, else `review-spent`; this is answered before the unreviewed-head rule, because the fix moved
  the head the verification read; the project lead's order is at most two fix rounds.
- `FIX_ROUNDS` or more `fix` entries over the verify runs is `spent` (`deliver-standard.js:2912`, `vRounds < 2`).
- otherwise `fix`; `problems` is one entry per `fail` result (`reran` its `reran is True`), then the `?`
  problem when the tree is not `clean` (`DIRTY`) or the verdict is `dirty` on a clean tree (`MOVED`)
  (`deliver-standard.js:2709-2719`).
- `guards` are the declared ids whose `verification_conditions` entry sets `pre_commit: true`, else the ids
  `verified-tree run` runs, each `{id, argv, cwd}` of the contract resolved in the worktree, `cwd` absolute
  (`deliver-standard.js:1578-1587`, `PRE_COMMIT` and `PUSH_TESTS`).

`untested_start(runs)` (the program never marks a verify fix; `deliver-standard.js:922-934` marks the others): at
each `ws-check` result of a verify run, with the latest `fix` result graded before it, no start pending, no
non-blank `tests` in that fix and the `ws-check` commit blank or other than its `start_head`, the pending start
becomes the `ws-check` `start_head`: the verified head before the fix, never a sha the fix reply names. A fix
entered whose `ws-check` recorded no result (the run stopped first, or the fix agent never replied) counts as
recording no test, and its start is the latest verification head before it (a `ws-check` result with no
`start_head` falls back to the same head). A `retested` transition with outcome `done` clears it.

`fix-range` (`deliver-standard.js:2738-2744`): `commit` is the worktree's HEAD and the range is read by
`verified_tree.fix_range`; a range or head git cannot read answers `unread`, which disables narrowing.

`retested` (`deliver-standard.js:2942-2944`): `untested` unless the latest `retest` reply is `done`, names the
latest `round` result's head as its start and commit, the worktree's HEAD is that head and its `tests` hold a
non-blank string; then `dirty` unless the reply says `clean` and `git status --porcelain --untracked-files=all`
prints nothing (untracked files included whatever `status.showUntrackedFiles` says, so the reply's word is not
taken); else `done`.

`round` also answers `digest`, `verified_tree.results_digest` of the read's results: the narrowed `rerun` passes it
back, so only the results this round graded can be carried.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_tools.delivery import engine_ledger, land_tally
from agent_tools.delivery.land_tally import TallyError
from agent_tools.verification import verified_tree

VERIFY = "verify"
VERIFICATION_STEPS = ("checks", "rerun")
ROUND = "round"
ROUND_REVIEWED = "round-reviewed"
FIX = "fix"
WS_CHECK = "ws-check"
RETEST = "retest"
RETESTED = "retested"
REVIEWS = ("fix-review", "fix-review-again")
NARROWINGS = ("narrowing", "narrowing-again")
FIX_ROUNDS = 2
DIRTY = "the worktree has uncommitted changes, so the verified tree is not the pushed head"
MOVED = "the head moved while the verification ran, so no result speaks for one commit"
UNTESTED = "the fix report records no test command, so its commit is not pushed"
RETEST_DIRTY = "the retest left the worktree changed, so the tested contents are not the commit and it is not pushed"


def _events(run_dir: Path) -> list[dict]:
    try:
        return engine_ledger.replay(Path(run_dir) / "events.jsonl")
    except engine_ledger.LedgerError as error:
        raise TallyError("ledger_unreadable", str(error)) from None


def verify_runs(holder: str, root: Path | None = None) -> list[Path]:
    """The delivery's runs of the `VERIFY` procedure, in `delivery_runs` order; none is `no_verify_run`."""
    found = [run for run in land_tally.delivery_runs(holder, root) if land_tally._procedure(run) == VERIFY]
    if not found:
        raise TallyError("no_verify_run", "the delivery has no verify run")
    return found


def _tested(reply: Mapping) -> bool:
    tests = reply.get("tests")
    return isinstance(tests, list) and any(isinstance(test, str) and test.strip() for test in tests)


def untested_start(runs: Sequence[Path]) -> str | None:
    """The verified head before the earliest fix no `retested` done has covered and that recorded no test.

    A fix whose `ws-check` never recorded its result (the run stopped first, or the fix agent never replied) is
    read from the latest verification head before it, and a reply-less fix counts as recording no test."""
    pending: str | None = None
    head: str | None = None
    for run in runs:
        fix: dict | None = None
        anchor: str | None = None
        unchecked = False
        for event in _events(run):
            step = event.get("step")
            if event["event"] == "step_entered" and step == FIX:
                fix, anchor, unchecked = {}, head, True
            elif event["event"] == "transition_taken" and step == RETESTED and event["outcome"] == "done":
                pending = None
            elif event["event"] == "outcome_graded" and step in VERIFICATION_STEPS:
                seen = land_tally.stored(run, step, event["visit"]).get("head")
                head = seen if isinstance(seen, str) and seen else head
            elif event["event"] == "outcome_graded" and step == FIX:
                fix = land_tally.stored(run, FIX, event["visit"])
            elif event["event"] == "outcome_graded" and step == WS_CHECK and fix is not None:
                check = land_tally.stored(run, WS_CHECK, event["visit"])
                start, commit = check.get("start_head") or anchor, check.get("commit")
                unchecked = False
                if (pending is None and not _tested(fix) and isinstance(start, str) and start
                        and (not commit or commit != start)):
                    pending = start
        if unchecked and pending is None and fix is not None and not _tested(fix) and anchor:
            pending = anchor
    return pending


def _unreviewed(run: Path) -> bool:
    """Whether the latest verification of the run is at a head other than the fix `ws-check` last read."""
    reviewed: str | None = None
    moved = False
    for event in _events(run):
        step = event.get("step")
        if event["event"] != "outcome_graded":
            continue
        if step == WS_CHECK:
            commit = land_tally.stored(run, WS_CHECK, event["visit"]).get("commit")
            reviewed = commit if isinstance(commit, str) and commit else None
        elif step in VERIFICATION_STEPS and reviewed is not None:
            head = land_tally.stored(run, step, event["visit"]).get("head")
            moved = isinstance(head, str) and head != reviewed
    return moved


def _problems(read: Mapping) -> list[dict]:
    results = [r for r in read.get("results") or [] if isinstance(r, dict)]
    problems = [{"id": r.get("id", "?"), "status": "fail", "summary": r.get("summary", ""),
                 "reran": r.get("reran") is True} for r in results if r.get("status") == "fail"]
    if read.get("verdict") in ("failed", "dirty"):
        if read.get("clean") is not True:
            problems.append({"id": "?", "status": "dirty", "summary": DIRTY, "reran": False})
        elif read.get("verdict") == "dirty":
            problems.append({"id": "?", "status": "dirty", "summary": MOVED, "reran": False})
    return problems


def _findings(run: Path) -> list[dict] | None:
    """The blocking findings of the fix review that a narrowing took to `round` and no later review has
    graded: a continue's preflight and checks between them never hide the finding. None when there are none."""
    outstanding = False
    for event in _events(run):
        if event["event"] == "transition_taken" and event["step"] in NARROWINGS:
            outstanding = event["outcome"] == "findings"
        elif event["event"] == "outcome_graded" and event["step"] in REVIEWS:
            outstanding = False
    if not outstanding:
        return None
    review = land_tally.latest_result(run, REVIEWS) or {}
    found = review.get("findings")
    return [{"id": "review", "status": "finding", "summary": f.get("summary", ""), "file": f.get("file", ""),
             "failing_input": f.get("failing_input", ""), "kind": f.get("kind", ""), "reran": False}
            for f in found if isinstance(f, dict) and f.get("severity") != "minor"] if isinstance(found, list) else []


def _guards(worktree: str) -> list[dict]:
    root = Path(worktree)
    try:
        snapshot = verified_tree._resolved(root)
    except verified_tree.VerifiedTreeError as error:
        raise TallyError("contract_refused", str(error)) from None
    policy = verified_tree._policy(snapshot)
    conditions = policy["conditions"]
    ids = [i for i in policy["verification"]
           if isinstance(conditions.get(i), dict) and conditions[i].get("pre_commit") is True]
    commands = snapshot["bindings"]["commands"]
    return [{"id": i, "argv": commands[i]["argv"], "cwd": commands[i]["cwd"]}
            for i in ids or verified_tree._run_ids(policy)]


def answer(holder: str, worktree: str, root: Path | None = None, reviewed: bool = False) -> dict:
    """The round's `{verdict, head, clean, results, problems, start_head, guards}`; `reviewed` (the
    `round-reviewed` subcommand) also reads a fix review's outstanding findings."""
    runs = verify_runs(holder, root)
    read = land_tally.latest_result(runs[-1], VERIFICATION_STEPS)
    if read is None:
        raise TallyError("no_verification", "the current verify run has no verification result")
    guards = _guards(worktree)
    problems = _problems(read)
    results = read.get("results") if isinstance(read.get("results"), list) else []
    start = ""
    verdict = read.get("verdict")
    findings = _findings(runs[-1]) if reviewed else None
    if findings is not None:
        verdict = "review-spent" if land_tally.entered(runs, FIX) >= FIX_ROUNDS else "fix"
        problems += findings
    elif _unreviewed(runs[-1]):
        verdict = "verify"
    elif verdict == "passed":
        found = untested_start(runs)
        verdict, start = ("passed", "") if found is None or found == read.get("head") else ("retest", found)
    elif verdict not in ("failed", "dirty") or any(
            isinstance(r, dict) and r.get("status") == "fail" and r.get("no_slot") for r in results):
        verdict = "verify"
    elif land_tally.entered(runs, FIX) >= FIX_ROUNDS:
        verdict = "spent"
    else:
        verdict = "fix"
    return {"verdict": verdict, "head": read.get("head", ""), "clean": read.get("clean"), "results": results,
            "digest": verified_tree.results_digest(results), "problems": problems, "start_head": start,
            "guards": guards}


def fix_range(worktree: str, start_head: str) -> dict:
    """The live head and the fix range `start_head`..HEAD; `unread` when git cannot read them."""
    root = Path(worktree)
    try:
        commit = verified_tree._git(["rev-parse", "HEAD"], root)
        read = verified_tree.fix_range(root, start_head, commit)
    except verified_tree.VerifiedTreeError as error:
        return {"verdict": "unread", "start_head": start_head, "commit": "", "whitespace_only": False,
                "changed_paths": [], "detail": str(error)}
    return {"verdict": "read", "start_head": start_head, "commit": commit,
            "whitespace_only": read["whitespace_only"], "changed_paths": read["changed_paths"]}


def retested(holder: str, worktree: str, root: Path | None = None) -> dict:
    """`done`, `untested` or `dirty` for the latest retest against the latest round's head."""
    current = verify_runs(holder, root)[-1]
    reply = land_tally.latest_result(current, (RETEST,))
    latest = land_tally.latest_result(current, (ROUND,))
    head = latest.get("head") if isinstance(latest, dict) else None
    try:
        live = verified_tree._git(["rev-parse", "HEAD"], Path(worktree))
    except verified_tree.VerifiedTreeError:
        live = None
    if not (isinstance(reply, dict) and isinstance(head, str) and head and reply.get("status") == "done"
            and reply.get("start_head") == head and reply.get("commit") == head and live == head
            and _tested(reply)):
        return {"verdict": "untested", "detail": UNTESTED}
    try:
        changed = verified_tree._git(["status", "--porcelain", "--untracked-files=all"], Path(worktree))
    except verified_tree.VerifiedTreeError:
        changed = "?"
    if reply.get("clean") is not True or changed:
        return {"verdict": "dirty", "detail": RETEST_DIRTY}
    return {"verdict": "done", "detail": ""}


def emit(value: Mapping) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _failure(code: str, detail: str) -> int:
    emit({"verdict": "error", "error": code, "detail": detail})
    return 1


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        _failure("usage", message)
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="verify-rounds")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for name, flags in (("round", ("holder", "worktree-path")), (ROUND_REVIEWED, ("holder", "worktree-path")),
                        ("fix-range", ("worktree-path", "head")),
                        (RETESTED, ("holder", "worktree-path"))):
        command = commands.add_parser(name)
        for flag in flags:
            command.add_argument(f"--{flag}", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "fix-range":
            emit(fix_range(args.worktree_path, args.head))
        elif args.command in ("round", ROUND_REVIEWED):
            emit(answer(args.holder, args.worktree_path, reviewed=args.command == ROUND_REVIEWED))
        else:
            emit(retested(args.holder, args.worktree_path))
    except TallyError as error:
        return _failure(error.code, error.detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
