"""The pure half of attempt custody (#338): the vocabulary, the subject and the settle planner.

Every rule here needs no file, lock, clock or environment variable. It holds the closed sets of
suspension causes and the stall bound (their one home; `workflow-state` imports them), the
fencing refusal reasons, the keys and the closed `attempt-custody/v1` subject a custody
transaction is created under, the pure 8 -> 9 migration plan, the readers that answer from a
custody transaction's events (a launch's fence, whether it was reaped, whether a result is
recorded), and `settle_plan`, which turns one ledger attempt, its custody `Transaction` and its
lease record into the ordered `Operation`s that bring the core to the spec's projection table.
`agent_tools.attempt_store` owns the effects: it applies a plan to `TransactionStore` under the
store lock, and `workflow-state` owns the ledgers and the clock.
"""

import datetime
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent_tools.attempt_identity import MigrationRefused
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_history import TERMINALS, Transaction
from agent_tools.transaction_storage import is_id

SUBJECT_SCHEMA = "attempt-custody/v1"
AUTHORITY_CLASS = "attempt-custody"
FENCING_REASONS = ("custody_misbound", "superseded_launch", "launch_identity_required",
                   "custody_unavailable")
# ``host_capacity`` is written only by control, from a ``launch_refused`` owner
# observation; it is auto-resumable, but its resume is gated until some other
# claim is released after the refused launch's own claim (per D7, D26).
# ``agent_dispatch`` is written only by an owner, through ``suspend``, when its
# own context cannot launch the agents a phase needs. It is not auto-resumable:
# the ledger cannot see how deep a relaunch would run, and blind resumes would
# spend ``STALL_LIMIT``, so only a human-directed re-entry clears it (per D6).
# ``deadline`` is an owner value: sdd's headroom rule writes it through
# ``suspend`` when too little time is left before the attempt's
# ``deadline_at`` for its next task. It is auto-resumable, like ``transport``,
# because a resume's fresh window is the remedy (per #281 D2).
BLOCKED_ON_VALUES = frozenset({
    "usage_limit", "transport", "human_gate", "external", "unknown", "host_capacity",
    "agent_dispatch", "deadline",
})
OWNER_BLOCKED_ON_VALUES = BLOCKED_ON_VALUES - {"unknown", "host_capacity"}
AUTO_RESUMABLE_BLOCKED_ON = frozenset(
    {"usage_limit", "transport", "unknown", "host_capacity", "deadline"})
STALL_LIMIT = 3
LIVE_STATES = ("active", "handed_off", "suspended")
OPERATIONS = ("create", "acquire", "release", "reap", "park", "unpark", "renew",
              "record_result", "seal")

_SUBJECT_KEYS = frozenset({"schema", "run", "issue", "attempt", "worktree", "prior",
                           "bound_launch"})
_VERDICT_STATES = ("stopped", "failed", "merged")
_SYNTHETIC_SOURCES = ("stalled", "expiry")
_SUSPENDED = "suspended:"
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def stall_count(*, phase: int, suspend_phase: int | None, stalled_resumes: int) -> int:
    """The resumes already spent at `phase` once one more suspension lands there:
    `stalled_resumes + 1` when the last suspension was at the same phase, else 0."""
    return stalled_resumes + 1 if suspend_phase == phase else 0


def stalled(count: int) -> bool:
    """Whether `count` has reached `STALL_LIMIT`, the zombie-loop bound."""
    return count >= STALL_LIMIT


def suspension_reason(blocked_on: str) -> str:
    """The parking reason `suspended:<blocked_on>`; ValueError outside `BLOCKED_ON_VALUES`."""
    if type(blocked_on) is not str or blocked_on not in BLOCKED_ON_VALUES:
        raise ValueError(f"blocked_on {blocked_on!r} is not one of {sorted(BLOCKED_ON_VALUES)}")
    return _SUSPENDED + blocked_on


def blocked_on_of(reason: str) -> str | None:
    """The cause a parking reason records: "unknown" for `expiry`, the cause of a
    `suspended:<cause>` reason in `BLOCKED_ON_VALUES`, else None."""
    if reason == "expiry":
        return "unknown"
    if type(reason) is str and reason.startswith(_SUSPENDED):
        cause = reason[len(_SUSPENDED):]
        if cause in BLOCKED_ON_VALUES:
            return cause
    return None


def at_ms(stamp: str) -> int:
    """An RFC 3339 UTC `...Z` ledger timestamp as epoch milliseconds; ValueError otherwise."""
    if type(stamp) is not str or not stamp.endswith("Z"):
        raise ValueError(f"{stamp!r} is not an RFC 3339 UTC timestamp ending in Z")
    parsed = datetime.datetime.fromisoformat(stamp[:-1] + "+00:00")
    return (parsed - _EPOCH) // datetime.timedelta(milliseconds=1)


def worktree_key(worktree: str) -> str:
    """The one concurrency key of a custody transaction: `attempt-worktree:<worktree>`."""
    return f"attempt-worktree:{worktree}"


def creation_key(run: str, issue: int, attempt: int) -> str:
    """The creation key `attempt-custody/v1:<run>:<issue>:<attempt>` of an attempt's transaction."""
    return f"{SUBJECT_SCHEMA}:{run}:{issue}:{attempt}"


def launch_id(issue: int, attempt: int, launch: int) -> str:
    """The launch's action id `<issue>:<attempt>:<launch>`, also its span's `executor_id`."""
    return f"{issue}:{attempt}:{launch}"


def _is_ordinal(value: object) -> bool:
    return type(value) is int and value >= 1


def subject_violation(value: object) -> str | None:
    """Why `value` is not the closed attempt-custody/v1 subject, else None."""
    if not isinstance(value, Mapping) or set(value) != _SUBJECT_KEYS:
        return f"subject is not the closed {SUBJECT_SCHEMA} object"
    if value["schema"] != SUBJECT_SCHEMA:
        return f"subject schema is not {SUBJECT_SCHEMA}"
    if not is_id(value["run"]):
        return "subject run is not a transaction id"
    for name in ("issue", "attempt"):
        if not _is_ordinal(value[name]):
            return f"subject {name} is not an integer of at least 1"
    worktree = value["worktree"]
    if type(worktree) is not str or not os.path.isabs(worktree) \
            or worktree != os.path.normpath(worktree):
        return "subject worktree is not a normalized absolute path"
    if value["prior"] is not None and not is_id(value["prior"]):
        return "subject prior is not null or a transaction id"
    if value["bound_launch"] is not None and not _is_ordinal(value["bound_launch"]):
        return "subject bound_launch is not null or an integer of at least 1"
    return None


def subject(*, run: str, issue: int, attempt: int, worktree: str, prior: str | None,
            bound_launch: int | None) -> dict:
    """The closed subject of an attempt's custody transaction; ValueError carries the
    text of `subject_violation`."""
    built = {"schema": SUBJECT_SCHEMA, "run": run, "issue": issue, "attempt": attempt,
             "worktree": worktree, "prior": prior, "bound_launch": bound_launch}
    violation = subject_violation(built)
    if violation is not None:
        raise ValueError(violation)
    return built


def creation_arguments(subject: Mapping) -> dict:
    """The keyword arguments of `TransactionStore.create` for a custody transaction: one
    concurrency key, the inert proof and recovery declarations, the authority class."""
    return {"concurrency_keys": [worktree_key(subject["worktree"])],
            "proof": {"units": [], "obligations": [], "collectors": {}},
            "recovery": {"effects": {}, "units": []},
            "authority_class": AUTHORITY_CLASS}


def plan_custody_migration(document: Mapping) -> dict[tuple[int, int], int]:
    """The pure 8 -> 9 plan: `(issue, attempt ordinal) -> launch count` for each issue whose
    latest attempt is live; a live worktree that is not absolute is `invalid_state`."""
    plan = {}
    for key, issue_state in document["issues"].items():
        attempts = issue_state["attempts"]
        if not attempts or attempts[-1]["state"] not in LIVE_STATES:
            continue
        latest = attempts[-1]
        worktree = latest["worktree"]
        if type(worktree) is not str or not os.path.isabs(worktree):
            raise MigrationRefused(
                "invalid_state",
                f"issue {key} attempt {latest['attempt']}: worktree {worktree!r} is not an "
                f"absolute path")
        plan[(int(key), latest["attempt"])] = len(latest["launches"])
    return plan


def _plain(value: Any) -> Any:
    """`value` with every mapping a dict and every sequence a list, recursively."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def launch_fence(transaction: Transaction, executor_id: str) -> dict | None:
    """The fence, as plain dicts, of the latest `lease_acquired` or `lease_reacquired` event
    carrying `executor_id`; None when that executor never held a span."""
    fence = None
    for event in transaction.events:
        if event["type"] in ("lease_acquired", "lease_reacquired") \
                and event["executor_id"] == executor_id:
            fence = _plain(event["fence"])
    return fence


def reaped(transaction: Transaction, executor_id: str) -> bool:
    """Whether a `stop_synthesized` event carries the fence of `executor_id`'s latest span."""
    fence = launch_fence(transaction, executor_id)
    return fence is not None and any(
        event["type"] == "stop_synthesized" and _plain(event["fence"]) == fence
        for event in transaction.events)


def result_recorded(transaction: Transaction, executor_id: str, digest: str) -> bool:
    """Whether an `owner_result` on the fence of `executor_id`'s latest span carries a
    `result` whose `telemetry_digest` is `digest`."""
    fence = launch_fence(transaction, executor_id)
    return fence is not None and any(
        event["type"] == "owner_result" and _plain(event["fence"]) == fence
        and telemetry_digest(_plain(event["result"])) == digest
        for event in transaction.events)


def merge_recorded(issue_state: Mapping, attempt: Mapping) -> bool:
    """Whether a merge is on record: the attempt's result is `merged` or names a
    `merge_sha`, or the issue's delivery has observed `pr_merged`."""
    result = attempt.get("result") or {}
    if result.get("state") == "merged" or result.get("merge_sha") is not None:
        return True
    postconditions = (issue_state.get("delivery") or {}).get("postconditions") or {}
    return (postconditions.get("pr_merged") or {}).get("state") == "observed"


def span_lapsed(custody: Any, lease: Mapping | None, now_ms: int) -> bool:
    """Whether the custody's span has lapsed at `now_ms`: true unless `lease` still names the
    custody's epoch and instance and `now_ms < expires_at`. This is the core's own lapse
    comparison for the one key a custody transaction has."""
    holder = None if lease is None else lease["holder"]
    if holder is None:
        return True
    return any(lease["epoch"] != entry["epoch"] or holder["instance"] != entry["instance"]
               or now_ms >= holder["expires_at"] for entry in custody.fence.values())


@dataclass(frozen=True)
class Operation:
    """One core operation of a settle plan; `kind` is one of `OPERATIONS`.

    `acquire` and `record_result` carry `executor_id`; `acquire` and `renew` carry `ttl_ms`;
    `reap`, `park`, `unpark` and `seal` carry `reason`; every other field is None.
    """

    kind: str
    executor_id: str | None = None
    ttl_ms: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in OPERATIONS:
            raise ValueError(f"operation {self.kind!r} is not one of {OPERATIONS}")


class ProjectionMismatch(ValueError):
    """The ledger attempt and its custody transaction are a combination the projection
    tables do not produce."""


class _Settling:
    """The two facts a plan tracks while it emits operations: the transaction's open span
    (`holder`, the executor that holds it, and whether it has `lapsed`) and whether the
    transaction is `parked`. Each emitting method updates them as the core would."""

    def __init__(self, *, holder: str | None, lapsed: bool, parked: bool, current: str) -> None:
        self.holder, self.lapsed, self.parked, self.current = holder, lapsed, parked, current
        self.operations: list[Operation] = []

    def create(self) -> None:
        self.operations.append(Operation("create"))

    def acquire(self, ttl_ms: int) -> None:
        self.operations.append(Operation("acquire", executor_id=self.current, ttl_ms=ttl_ms))
        self.holder, self.lapsed = self.current, False

    def release(self) -> None:
        self.operations.append(Operation("release"))
        self.holder = None

    def reap(self, reason: str) -> None:
        self.operations.append(Operation("reap", reason=reason))
        self.holder, self.lapsed, self.parked = None, False, True

    def park(self, reason: str) -> None:
        self.operations.append(Operation("park", reason=reason))
        self.parked = True

    def unpark(self) -> None:
        self.operations.append(Operation("unpark", reason="resumed"))
        self.parked = False

    def close(self, reason: str) -> None:
        """No span: nothing. A lapsed span is reaped (which parks); a live one is released."""
        if self.holder is None:
            return
        if self.lapsed:
            self.reap(reason)
        else:
            self.release()

    def park_with(self, parking_reason: str, reap_reason: str) -> None:
        """A lapsed span is reaped and nothing else; otherwise park unless parked, then
        release a live span."""
        if self.holder is not None and self.lapsed:
            self.reap(reap_reason)
            return
        if not self.parked:
            self.park(parking_reason)
        if self.holder is not None:
            self.release()


def settle_plan(issue_state: Mapping, attempt: Mapping, transaction: Transaction | None, *,
                lease: Mapping | None, now_ms: int, latest: bool,
                report_digest: str | None = None, bound: bool = False) -> tuple[Operation, ...]:
    """The ordered operations that bring `attempt`'s custody transaction to the projection
    table, for one ledger attempt of `issue_state`.

    `transaction` is the attempt's custody snapshot or None; `lease` is the record
    `inspect_lease` returns for its worktree key; `latest` says the attempt is its issue's
    last; `report_digest` is the digest of an owner report this write submits; `bound` says
    this write is the attempt's 8 -> 9 bind. The plan tracks the open span and the parking
    separately and updates both as it emits, so a plan resumed after any of its operations
    emits only what is still missing. Raises only `ProjectionMismatch`.
    """
    state = attempt["state"]
    if state not in LIVE_STATES + _VERDICT_STATES:
        raise ProjectionMismatch(f"attempt state {state!r} has no custody projection")
    current = launch_id(attempt["issue"], attempt["attempt"], len(attempt["launches"]))
    if transaction is None:
        if not (bound or (latest and state in LIVE_STATES)):
            return ()
        settling = _Settling(holder=None, lapsed=False, parked=False, current=current)
        settling.create()
    else:
        if transaction.state in TERMINALS:
            if state in LIVE_STATES:
                raise ProjectionMismatch(
                    f"{current}: the custody transaction is {transaction.state} but the "
                    f"attempt is {state}")
            return ()
        if transaction.state not in ("created", "attention_required"):
            raise ProjectionMismatch(
                f"{current}: custody transaction state {transaction.state!r} is not one "
                f"attempt custody produces")
        span = transaction.custody
        settling = _Settling(
            holder=None if span is None else span.executor_id,
            lapsed=span is not None and span_lapsed(span, lease, now_ms),
            parked=transaction.state == "attention_required", current=current)
    if state == "active":
        _plan_active(settling, attempt, lease, now_ms)
    elif state == "handed_off":
        settling.close("expiry")
        if settling.parked:
            settling.unpark()
    elif state == "suspended":
        cause = attempt["blocked_on"]
        if type(cause) is not str or cause not in BLOCKED_ON_VALUES:
            raise ProjectionMismatch(f"{current}: suspension cause {cause!r} is not known")
        reason = suspension_reason(cause)
        settling.park_with(reason, "expiry" if cause == "unknown" else reason)
    else:
        source = attempt["result_source"]
        if source in _SYNTHETIC_SOURCES:
            settling.park_with(source, source)
        elif source in ("owner", "refused", "superseded"):
            _plan_verdict(settling, issue_state, attempt, transaction, report_digest)
        else:
            raise ProjectionMismatch(f"{current}: result source {source!r} is not known")
    return tuple(settling.operations)


def _plan_active(settling: _Settling, attempt: Mapping, lease: Mapping | None,
                 now_ms: int) -> None:
    try:
        deadline = at_ms(attempt["deadline_at"])
    except (ValueError, TypeError, KeyError) as error:
        raise ProjectionMismatch(
            f"{settling.current}: deadline_at is not a UTC timestamp: {error}") from error
    ttl = deadline - now_ms
    if settling.holder == settling.current:
        if not settling.lapsed:
            if ttl > 0 and lease["holder"]["expires_at"] != deadline:
                settling.operations.append(Operation("renew", ttl_ms=ttl))
        elif ttl > 0:
            settling.acquire(ttl)
        elif settling.parked:
            settling.reap("expiry")
    else:
        settling.close("expiry")
        if ttl > 0:
            settling.acquire(ttl)
    if settling.parked:
        settling.unpark()


def _plan_verdict(settling: _Settling, issue_state: Mapping, attempt: Mapping,
                  transaction: Transaction | None, report_digest: str | None) -> None:
    if settling.holder is not None and settling.lapsed:
        settling.reap("expiry")
    current = settling.current
    if (attempt["result_source"] == "owner" and report_digest is not None
            and transaction is not None and launch_fence(transaction, current) is not None
            and not result_recorded(transaction, current, report_digest)):
        settling.operations.append(Operation("record_result", executor_id=current))
    if merge_recorded(issue_state, attempt):
        if settling.holder is not None:
            settling.release()
    else:
        settling.operations.append(
            Operation("seal", reason=f"{attempt['result_source']}:{attempt['state']}"))
