"""`land_tally`: what a delivery's landing counted, read back from its engine ledger; nothing here writes.

`landing` imports this module and no `engine_*.py` module does, so it is outside the engine package's line cap.
A procedure cannot hold a count a visit bound cannot hold (a count a continue or a release resets, a wait budget,
a count that spans attempts), so each is read here from the ledger, as `deliver-standard.js` held it in memory.

The delivery's runs: the root run is `<runs root>/<the text after the last "/" of the holder>`; its runs are
the root, then every run its `call` events name, each followed by its own descendants, in `call` event order
(`engine_ledger.delivery_runs`, which the engine's reuse of a stored result walks too).
The attempt runs are those whose procedure is `ATTEMPT`; the current attempt is the last.

Rules, each with the program line it ports:

- `held(trans)`: an outcome in `HOLDS` takes the lock, one in `FREES` frees it.
- `pending_spent(trans)` (`deliver-standard.js:3609`, 3712): a pending read of a `CHECK_STEPS` step counts as a
  wait while the lock is held (never reset) and as a read before it otherwise (reset by any other outcome of a
  `CHECK_STEPS` step before the lock). Spent when the counter the last such pending incremented is
  `PENDING_WAITS` or more; none at all is not spent.
- `stale_eligible(trans)` (`deliver-standard.js:3612-3619`): only the poll after a rerun of the failed jobs may
  answer stale: the last `RERUN_FROM` rerun answered `unchanged` or `silent`, no `STALE` follows it, every
  `CHECK_STEPS` outcome after it but the last is pending and the last is red.
- `lock_answers(run_dir)`: each graded visit of a `LOCK_WAIT_STEPS` step in order; a `contended` one adds its
  stored `lock` answer to the open run of waits, a `held` one closes the run.
- `lock_budget(runs)` (`deliver-standard.js:3048-3059`): the waited seconds of every answer of every run (at
  least `LAND_WAIT_CALL_S` each) plus one more call fit `LAND_WAIT_MAX_S`, and in the last run the answers that
  ended neither first in line nor in a better place than the one before number `LAND_WAIT_RETRIES` or fewer.
- `locked_shas(run_dir)`: the `lock.lock_sha` of every result graded in `HOLDS`: the shas this landing held.
- `held_shas(holder)`: the union of `locked_shas` over every attempt run of the delivery: a continue after a stop
  that left the lock makes a new attempt that took none, and a release must still free the earlier one's.
- Per-delivery counts (`entered` over `attempts`): one red-check fix and one sync-review fix a delivery.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_tools.delivery import engine_ledger

ATTEMPT = "land-attempt"
CHECK_STEPS = ("gate", "retake", "policy")
LOCK_WAIT_STEPS = ("lock", "relock")
CI_FIX = "ci-fix"
SYNC_FIX = "merge-fix"
RERUN_FROM = "ci-fixed"
STALE = "stale"
COUNTED_STEPS = (ATTEMPT, *CHECK_STEPS, *LOCK_WAIT_STEPS, CI_FIX, SYNC_FIX, RERUN_FROM, STALE)
HOLDS = ("held", "retaken")
FREES = ("released", "contended")
PENDING_WAITS = 3
LAND_WAIT_RETRIES = 3
LAND_WAIT_MAX_S = 6 * 3600
LAND_WAIT_CALL_S = 3000


class TallyError(Exception):
    """A ledger that cannot be counted: `code` is `no_run`, `no_attempt` or `ledger_unreadable`."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _events(run_dir: Path) -> list[dict]:
    try:
        return engine_ledger.replay(Path(run_dir) / "events.jsonl")
    except engine_ledger.LedgerError as error:
        raise TallyError("ledger_unreadable", str(error)) from None


def delivery_runs(holder: str, root: Path | None = None) -> list[Path]:
    """The delivery's root run, then every run it called and their descendants, in `call` event order."""
    base = engine_ledger.runs_root() if root is None else Path(root)
    run_dir = base / holder.rsplit("/", 1)[-1]
    if not (run_dir / "run.json").is_file():
        raise TallyError("no_run", f"no run {run_dir.name} under the runs root")
    try:
        return engine_ledger.delivery_runs(run_dir)
    except engine_ledger.LedgerError as error:
        raise TallyError("ledger_unreadable", str(error)) from None


def _procedure(run_dir: Path) -> str:
    try:
        return engine_ledger.read_run(run_dir)["procedure"]
    except engine_ledger.LedgerError as error:
        raise TallyError("ledger_unreadable", str(error)) from None


def attempts(holder: str, root: Path | None = None) -> list[Path]:
    """The delivery's `ATTEMPT` runs, in `delivery_runs` order."""
    return [run for run in delivery_runs(holder, root) if _procedure(run) == ATTEMPT]


def current(holder: str, root: Path | None = None) -> Path:
    """The last attempt run of the delivery."""
    found = attempts(holder, root)
    if not found:
        raise TallyError("no_attempt", "the delivery has no land attempt run")
    return found[-1]


def transitions(run_dir: Path) -> list[tuple[str, str]]:
    """`(step, outcome)` of every transition the run took, in ledger order."""
    return [(event["step"], event["outcome"]) for event in _events(run_dir)
            if event["event"] == "transition_taken"]


def held(trans: Sequence[tuple[str, str]]) -> bool:
    """Whether the transitions leave the land lock held."""
    holding = False
    for _, outcome in trans:
        if outcome in HOLDS:
            holding = True
        elif outcome in FREES:
            holding = False
    return holding


def pending_spent(trans: Sequence[tuple[str, str]]) -> bool:
    """Whether the last pending read of a check step used up its `PENDING_WAITS`."""
    waits = pends = 0
    spent = False
    holding = False
    for step, outcome in trans:
        if step in CHECK_STEPS:
            if outcome == "pending":
                if holding:
                    waits += 1
                    spent = waits >= PENDING_WAITS
                else:
                    pends += 1
                    spent = pends >= PENDING_WAITS
            elif not holding:
                pends = 0
        if outcome in HOLDS:
            holding = True
        elif outcome in FREES:
            holding = False
    return spent


def stale_eligible(trans: Sequence[tuple[str, str]]) -> bool:
    """Whether the read now is the first poll after a rerun, and it is red."""
    reruns = [index for index, (step, outcome) in enumerate(trans)
              if step == RERUN_FROM and outcome in ("unchanged", "silent")]
    if not reruns:
        return False
    after = trans[reruns[-1] + 1:]
    if any(step == STALE for step, _ in after):
        return False
    polls = [outcome for step, outcome in after if step in CHECK_STEPS]
    return bool(polls) and polls[-1] == "red" and all(outcome == "pending" for outcome in polls[:-1])


def entered(runs: Sequence[Path], step: str) -> int:
    """The `step_entered` events of `step` over the runs."""
    return sum(1 for run in runs for event in _events(run)
               if event["event"] == "step_entered" and event["step"] == step)


def stored(run_dir: Path, step: str, visit: int) -> dict:
    path = Path(run_dir) / "results" / f"{step}.{visit}.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise TallyError("ledger_unreadable", f"cannot read {path.name}: {error}") from None
    return loaded if isinstance(loaded, dict) else {}


def _graded(run_dir: Path) -> list[tuple[str, int, str]]:
    return [(event["step"], event["visit"], event["outcome"]) for event in _events(run_dir)
            if event["event"] == "outcome_graded"]


def lock_answers(run_dir: Path) -> list[list[dict]]:
    """The contended lock answers of the run, in runs of waits each ended by a hold; the last is current."""
    runs: list[list[dict]] = [[]]
    for step, visit, outcome in _graded(run_dir):
        if step not in LOCK_WAIT_STEPS:
            continue
        if outcome == "contended":
            lock = stored(run_dir, step, visit).get("lock")
            runs[-1].append(lock if isinstance(lock, dict) else {})
        elif outcome == "held" and runs[-1]:
            runs.append([])
    return runs


def _waited(lock: Mapping) -> int:
    waited = lock.get("waited_s")
    return waited if isinstance(waited, int) and not isinstance(waited, bool) and waited >= 0 else 0


def _position(lock: Mapping) -> int | None:
    position = lock.get("position")
    return position if (isinstance(position, int) and not isinstance(position, bool)
                        and position >= 1) else None


def lock_budget(runs: Sequence[Sequence[Mapping]]) -> bool:
    """Whether another lock wait fits the budget (`waitBudget` of the program)."""
    total = sum(max(_waited(lock), LAND_WAIT_CALL_S) for run in runs for lock in run if lock)
    spent = 0
    place: int | None = None
    for lock in runs[-1] if runs else ():
        at = _position(lock)
        if not (at == 1 or (at is not None and place is not None and at < place)):
            spent += 1
        place = at
    return spent <= LAND_WAIT_RETRIES and total + LAND_WAIT_CALL_S <= LAND_WAIT_MAX_S


def locked_shas(run_dir: Path) -> set[str]:
    """The `lock.lock_sha` of every result of the run graded in `HOLDS`."""
    shas: set[str] = set()
    for step, visit, outcome in _graded(run_dir):
        if outcome in HOLDS:
            lock = stored(run_dir, step, visit).get("lock")
            sha = lock.get("lock_sha") if isinstance(lock, dict) else None
            if isinstance(sha, str):
                shas.add(sha)
    return shas


def held_shas(holder: str, root: Path | None = None) -> set[str]:
    """The union of `locked_shas` over every attempt run of the delivery (a release frees any of them)."""
    return {sha for run in attempts(holder, root) for sha in locked_shas(run)}


def latest_result(run_dir: Path, steps: Sequence[str]) -> dict | None:
    """The stored result of the latest graded visit among `steps`; None when none was graded."""
    graded = [(step, visit) for step, visit, _ in _graded(run_dir) if step in steps]
    return stored(run_dir, *graded[-1]) if graded else None
