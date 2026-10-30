"""The pure half of attempt custody (#338, #339): the vocabulary, the subject and the settle planner.

Every rule here needs no file, lock, clock or environment variable. It holds the closed sets of
suspension causes and the stall bound (their one home; `workflow-state` imports them), the
fencing refusal reasons, the keys and the closed `attempt-custody/v1` subject a custody
transaction is created under, the pure 8 -> 9 migration plan, the readers that answer from a
custody transaction's events (a launch's fence, whether it was reaped, whether a result is
recorded), the readers that answer a launch's admission claim from the same events, and
`settle_plan`, which turns one ledger attempt (or delivery remainder), its custody `Transaction`
and its lease record into the ordered `Operation`s that bring the core to the spec's projection
table.
`agent_tools.attempt_store` owns the effects: it applies a plan to `TransactionStore` under the
store lock, and `workflow-state` owns the ledgers and the clock.
"""

import datetime
import json
import os
from collections.abc import Mapping, Sequence
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
# claim is released after the refused launch's own claim (per #150 D7, D26).
# ``agent_dispatch`` is written only by an owner, through ``suspend``, when its
# own context cannot launch the agents a phase needs. It is not auto-resumable:
# the ledger cannot see how deep a relaunch would run, and blind resumes would
# spend ``STALL_LIMIT``, so only a human-directed re-entry clears it (per #198 D6).
# ``deadline`` is an owner value: sdd's headroom rule writes it through
# ``suspend`` when too little time is left before the attempt's
# ``deadline_at`` for its next task. It is auto-resumable, like ``transport``,
# because a resume's fresh window is the remedy (per #281 D2).
BLOCKED_ON_VALUES = frozenset({
    "usage_limit", "transport", "human_gate", "external", "unknown", "host_capacity",
    "agent_dispatch", "deadline",
})
OWNER_BLOCKED_ON_VALUES = BLOCKED_ON_VALUES - {"unknown", "host_capacity"}
# ``owner_unavailable`` is the one cause only a delivery remainder takes: control writes it when
# the host reports the remainder's owner gone (#339 D15, D24). It is not an attempt cause, so the
# vocabularies that `suspend` and attempt validation read keep their members.
REMAINDER_BLOCKED_ON_VALUES = frozenset({"owner_unavailable"})
SUSPENSION_CAUSES = BLOCKED_ON_VALUES | REMAINDER_BLOCKED_ON_VALUES
AUTO_RESUMABLE_BLOCKED_ON = frozenset(
    {"usage_limit", "transport", "unknown", "host_capacity", "deadline"})
# A suspension cause only a person clears: an attempt or a delivery remainder parked on one
# resumes only on a human-directed re-entry (issue 458 D3).
HUMAN_GATED_BLOCKED_ON = BLOCKED_ON_VALUES - AUTO_RESUMABLE_BLOCKED_ON
STALL_LIMIT = 3
LIVE_STATES = ("active", "handed_off", "suspended")
# The unparking reason of a `host_capacity` suspension a later release woke, and the reason of
# the seal over a delivered issue (#339 D4, D5).
CAPACITY_RELEASED = "capacity_released"
DELIVERED = "delivered"
# The reason of a supplement over an `abandoned` receipt whose record a reconcile found merged
# (#339 D6), and the reserved reason with which the core parks a proof that cannot converge
# (D27).
RECONCILED_MERGE = "reconciled_merge"
UNCONVERGED = "proof_did_not_converge"
# The core states a `succeeded` seal passes through, in order; a delivered record may be found
# in any of them by a seal that was cut partway (#339 D19b).
FORWARD_STATES = ("awaiting_verification", "ready", "publishing", "published", "proving")
OPERATIONS = ("create", "acquire", "release", "reap", "park", "unpark", "renew",
              "record_result", "seal", "claim", "seal_succeeded", "supplement")

_CLAIM_KEYS = frozenset({"roles", "route"})
_VERDICT_STATES = ("stopped", "failed", "merged")
_SYNTHETIC_SOURCES = ("stalled", "expiry")
_SUSPENDED = "suspended:"
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def holds_issue(issue_state: Mapping) -> bool:
    """Whether a run still holds an issue: its latest attempt or latest delivery remainder is
    in `LIVE_STATES` (issue 475 D7). The direct-owner refusal also requires that the issue's
    delivery is not complete; this predicate alone does not (D12)."""
    return any(records and records[-1]["state"] in LIVE_STATES
               for records in (issue_state["attempts"], issue_state["delivery_remainders"]))


def stall_count(*, phase: int, suspend_phase: int | None, stalled_resumes: int) -> int:
    """The resumes already spent at `phase` once one more suspension lands there:
    `stalled_resumes + 1` when the last suspension was at the same phase, else 0."""
    return stalled_resumes + 1 if suspend_phase == phase else 0


def stalled(count: int) -> bool:
    """Whether `count` has reached `STALL_LIMIT`, the zombie-loop bound."""
    return count >= STALL_LIMIT


def suspension_reason(blocked_on: str) -> str:
    """The parking reason `suspended:<blocked_on>`; ValueError outside `SUSPENSION_CAUSES`."""
    if type(blocked_on) is not str or blocked_on not in SUSPENSION_CAUSES:
        raise ValueError(f"blocked_on {blocked_on!r} is not one of {sorted(SUSPENSION_CAUSES)}")
    return _SUSPENDED + blocked_on


def blocked_on_of(reason: str) -> str | None:
    """The cause a parking reason records: "unknown" for `expiry`, the cause of a
    `suspended:<cause>` reason in `SUSPENSION_CAUSES`, else None."""
    if reason == "expiry":
        return "unknown"
    if type(reason) is str and reason.startswith(_SUSPENDED):
        cause = reason[len(_SUSPENDED):]
        if cause in SUSPENSION_CAUSES:
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


def is_ordinal(value: object) -> bool:
    """Whether `value` is an integer (not a bool) of at least 1."""
    return type(value) is int and value >= 1


def custody_subject_violation(value: object, *, schema: str, ordinal: str) -> str | None:
    """Why `value` is not the closed custody subject of `schema`, whose record is numbered by
    the member `ordinal` (`attempt` or `remainder`), else None."""
    keys = {"schema", "run", "issue", ordinal, "worktree", "prior", "bound_launch"}
    if not isinstance(value, Mapping) or set(value) != keys:
        return f"subject is not the closed {schema} object"
    if value["schema"] != schema:
        return f"subject schema is not {schema}"
    if not is_id(value["run"]):
        return "subject run is not a transaction id"
    for name in ("issue", ordinal):
        if not is_ordinal(value[name]):
            return f"subject {name} is not an integer of at least 1"
    worktree = value["worktree"]
    if type(worktree) is not str or not os.path.isabs(worktree) \
            or worktree != os.path.normpath(worktree):
        return "subject worktree is not a normalized absolute path"
    if value["prior"] is not None and not is_id(value["prior"]):
        return "subject prior is not null or a transaction id"
    if value["bound_launch"] is not None and not is_ordinal(value["bound_launch"]):
        return "subject bound_launch is not null or an integer of at least 1"
    return None


def subject_violation(value: object) -> str | None:
    """Why `value` is not the closed attempt-custody/v1 subject, else None."""
    return custody_subject_violation(value, schema=SUBJECT_SCHEMA, ordinal="attempt")


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


def claim_reference(roles: Mapping, route: str) -> str:
    """The reference of an admission-claim entry: the sorted, compact JSON of the claim's
    `roles` and `route`."""
    return json.dumps({"roles": dict(roles), "route": route}, sort_keys=True,
                      separators=(",", ":"))


def claim_roles(reference: str) -> dict:
    """The role counts a claim entry's `reference` records; ValueError when `reference` is
    not the JSON `claim_reference` writes, with `roles` a mapping of names to integers."""
    try:
        value = json.loads(reference)
    except (TypeError, ValueError) as error:
        raise ValueError(f"claim reference is not JSON: {error}") from error
    if not isinstance(value, dict) or set(value) != _CLAIM_KEYS \
            or not isinstance(value["roles"], dict) \
            or any(type(role) is not str or type(count) is not int
                   for role, count in value["roles"].items()):
        raise ValueError("claim reference is not an object of roles and a route")
    return value["roles"]


def claim_id(executor_id: str, epoch: int) -> str:
    """The evidence id of the claim a span records: `admission-claim:<executor id>:<epoch>`.
    The epoch is part of it because a launch can reacquire and evidence ids are single-use."""
    return f"admission-claim:{executor_id}:{epoch}"


def span_epoch(custody: Any) -> int:
    """The epoch of the span `custody` holds (the greatest across its fenced keys)."""
    return max(entry["epoch"] for entry in custody.fence.values())


def claimed(transaction: Transaction, executor_id: str) -> str | None:
    """The reference of the claim entry recorded under the fence of `executor_id`'s latest
    span, else None: a claim recorded under an earlier span of the launch does not count."""
    fence = launch_fence(transaction, executor_id)
    if fence is None:
        return None
    wanted = claim_id(executor_id, max(entry["epoch"] for entry in fence.values()))
    for event in transaction.events:
        if event["type"] == "evidence_recorded" and event["evidence_id"] == wanted \
                and _plain(event["fence"]) == fence:
            return event["reference"]
    return None


def held_claim(admission: Mapping | None, holder: str) -> str | None:
    """The claim reference of the unreleased claim the `admission` block holds for `holder`,
    else None (also for no block)."""
    if admission is None:
        return None
    for claim in admission["claims"]:
        if claim["holder"] == holder and claim["released_at"] is None:
            return claim_reference(claim["roles"], admission["route"])
    return None


def owner_gone(admission: Mapping | None, holder: str) -> bool:
    """Whether the `admission` block shows `holder`'s claim released as `owner_unavailable`."""
    return admission is not None and any(
        claim["holder"] == holder and claim["release_event"] == "owner_unavailable"
        for claim in admission["claims"])


def gate_open(claims: Sequence[Mapping], holder: str) -> bool:
    """Whether the `host_capacity` gate of `holder`'s refused launch is open: `claims` holds a
    `launch_refused` claim naming `holder`, and some claim released by any other event has a
    greater `release_seq`. Another launch's refusal frees no capacity, so two refused owners
    never wake each other."""
    refused = next((claim for claim in claims if claim["holder"] == holder
                    and claim["release_event"] == "launch_refused"), None)
    return refused is not None and any(
        claim["release_event"] not in (None, "launch_refused")
        and claim["release_seq"] > refused["release_seq"] for claim in claims)


def seal_executor(launch: str) -> str:
    """The executor of the span a `succeeded` seal takes over a record: the record's launch
    id with its launch number replaced by `seal`."""
    return launch.rpartition(":")[0] + ":seal"


def merge_recorded(issue_state: Mapping, attempt: Mapping) -> bool:
    """Whether a merge is on record: the attempt's result is `merged` or names a
    `merge_sha`, or the issue's delivery has observed `pr_merged`."""
    result = attempt.get("result") or {}
    if result.get("state") == "merged" or result.get("merge_sha") is not None:
        return True
    postconditions = (issue_state.get("delivery") or {}).get("postconditions") or {}
    return (postconditions.get("pr_merged") or {}).get("state") == "observed"


def unconverged(transaction: Transaction) -> bool:
    """Whether the core parked `transaction` because its proof did not converge (#339 D27): it
    is `attention_required` and its last transition carries the reserved reason. Such a
    transaction is never resumed."""
    if transaction.state != "attention_required":
        return False
    last = next(event for event in reversed(transaction.events) if event["type"] == "transitioned")
    return last["reason"] == UNCONVERGED


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

    `acquire`, `record_result`, `claim` and `seal_succeeded` carry `executor_id`; `acquire` and
    `renew` carry `ttl_ms`; `reap`, `park`, `unpark`, `seal`, `seal_succeeded` and `supplement`
    carry `reason`; `claim` and `supplement` carry `reference`; every other field is None.
    """

    kind: str
    executor_id: str | None = None
    ttl_ms: int | None = None
    reason: str | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in OPERATIONS:
            raise ValueError(f"operation {self.kind!r} is not one of {OPERATIONS}")


class ProjectionMismatch(ValueError):
    """The ledger attempt and its custody transaction are a combination the projection
    tables do not produce."""


class _Settling:
    """The facts a plan tracks while it emits operations: the transaction's open span
    (`holder`, the executor that holds it, and whether it has `lapsed`), whether the
    transaction is `parked` and whether this plan has `acquired` a span. Each emitting method
    updates them as the core would."""

    def __init__(self, *, holder: str | None, lapsed: bool, parked: bool, current: str) -> None:
        self.holder, self.lapsed, self.parked, self.current = holder, lapsed, parked, current
        self.acquired = False
        self.operations: list[Operation] = []

    def create(self) -> None:
        self.operations.append(Operation("create"))

    def acquire(self, ttl_ms: int) -> None:
        self.operations.append(Operation("acquire", executor_id=self.current, ttl_ms=ttl_ms))
        self.holder, self.lapsed, self.acquired = self.current, False, True

    def release(self) -> None:
        self.operations.append(Operation("release"))
        self.holder = None

    def reap(self, reason: str) -> None:
        self.operations.append(Operation("reap", reason=reason))
        self.holder, self.lapsed, self.parked = None, False, True

    def park(self, reason: str) -> None:
        self.operations.append(Operation("park", reason=reason))
        self.parked = True

    def unpark(self, reason: str = "resumed") -> None:
        self.operations.append(Operation("unpark", reason=reason))
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
                report_digest: str | None = None, bound: bool = False,
                current: str | None = None, claim: str | None = None,
                owner_gone: bool = False, gate_open: bool = False,
                delivered: bool = False) -> tuple[Operation, ...]:
    """The ordered operations that bring a record's custody transaction to the projection
    table, for one ledger attempt (or delivery remainder) of `issue_state`.

    `transaction` is the record's custody snapshot or None; `lease` is the record
    `inspect_lease` returns for its worktree key; `latest` says the record is the last of its
    issue; `report_digest` is the digest of an owner report this write submits; `bound` says
    this write is the record's bind. `current` is the launch id of the record's current launch
    (default: the attempt's `launch_id`, a remainder passes its own). The plan tracks the open
    span and the parking separately and updates both as it emits, so a plan resumed after any
    of its operations emits only what is still missing. The five remaining keywords are the
    cutover's facts and default to the earlier plan:

    - `claim`: the admission-claim reference of an `active` launch; the plan ends with a
      `claim` operation when the launch holds an unlapsed span this plan acquired or that
      carries no claim.
    - `owner_gone`: the host reports the launch's owner unavailable; an `active` record's span
      is closed and never acquired.
    - `gate_open`: a release opened the `host_capacity` gate; a `host_capacity` suspension is
      woken with `capacity_released`.
    - `delivered`: the issue's delivery is complete; the record holds no launch span and the
      plan ends with `seal_succeeded`, or is empty over a sealed transaction or one the core
      parked unconverged (D27).

    A sealed `abandoned` transaction over a record a reconcile found `merged` plans one
    `supplement` of that merge (D6, D24g), delivered or not.

    Raises only `ProjectionMismatch`.
    """
    state = attempt["state"]
    if state not in LIVE_STATES + _VERDICT_STATES:
        raise ProjectionMismatch(f"attempt state {state!r} has no custody projection")
    if current is None:
        current = launch_id(attempt["issue"], attempt["attempt"], len(attempt["launches"]))
    if transaction is None:
        if not (bound or (latest and state in LIVE_STATES)):
            return ()
        settling = _Settling(holder=None, lapsed=False, parked=False, current=current)
        settling.create()
    else:
        if transaction.state in TERMINALS:
            if state in LIVE_STATES and not delivered:
                raise ProjectionMismatch(
                    f"{current}: the custody transaction is {transaction.state} but the "
                    f"attempt is {state}")
            if transaction.state == "abandoned" and state == "merged" \
                    and attempt["result_source"] == "superseded":
                return (Operation("supplement", reason=RECONCILED_MERGE,
                                  reference=telemetry_digest(attempt["result"])),)
            return ()
        if delivered and unconverged(transaction):
            return ()
        if delivered and transaction.state in FORWARD_STATES:
            return (_seal_succeeded(current),)
        if transaction.state not in ("created", "attention_required"):
            raise ProjectionMismatch(
                f"{current}: custody transaction state {transaction.state!r} is not one "
                f"attempt custody produces")
        span = transaction.custody
        settling = _Settling(
            holder=None if span is None else span.executor_id,
            lapsed=span is not None and span_lapsed(span, lease, now_ms),
            parked=transaction.state == "attention_required", current=current)
    if delivered:
        _plan_delivered(settling, attempt, transaction, report_digest)
    elif state == "active" and owner_gone:
        settling.close("expiry")
        if settling.parked:
            settling.unpark()
    elif state == "active":
        _plan_active(settling, attempt, lease, now_ms)
        if claim is not None and _wants_claim(settling, transaction):
            settling.operations.append(
                Operation("claim", executor_id=current, reference=claim))
    elif state == "handed_off":
        settling.close("expiry")
        if settling.parked:
            settling.unpark()
    elif state == "suspended":
        cause = attempt["blocked_on"]
        if type(cause) is not str or cause not in SUSPENSION_CAUSES:
            raise ProjectionMismatch(f"{current}: suspension cause {cause!r} is not known")
        reason = suspension_reason(cause)
        if cause == "host_capacity" and gate_open:
            if settling.holder is not None:
                settling.park_with(reason, reason)
            if settling.parked:
                settling.unpark(CAPACITY_RELEASED)
        else:
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


def _seal_succeeded(current: str) -> Operation:
    return Operation("seal_succeeded", executor_id=seal_executor(current), reason=DELIVERED)


def _wants_claim(settling: _Settling, transaction: Transaction | None) -> bool:
    """Whether the plan ends with the current launch holding an unlapsed span that has no
    claim yet: one this plan acquired, or one the store holds without a claim entry."""
    if settling.holder != settling.current or settling.lapsed:
        return False
    return settling.acquired or claimed(transaction, settling.current) is None


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


def _record_owner_result(settling: _Settling, attempt: Mapping,
                         transaction: Transaction | None, report_digest: str | None) -> None:
    """An owner report this write submits is recorded once, on the current launch's span."""
    current = settling.current
    if (attempt["result_source"] == "owner" and report_digest is not None
            and transaction is not None and launch_fence(transaction, current) is not None
            and not result_recorded(transaction, current, report_digest)):
        settling.operations.append(Operation("record_result", executor_id=current))


def _plan_verdict(settling: _Settling, issue_state: Mapping, attempt: Mapping,
                  transaction: Transaction | None, report_digest: str | None) -> None:
    if settling.holder is not None and settling.lapsed:
        settling.reap("expiry")
    _record_owner_result(settling, attempt, transaction, report_digest)
    if merge_recorded(issue_state, attempt):
        if settling.holder is not None:
            settling.release()
    else:
        settling.operations.append(
            Operation("seal", reason=f"{attempt['result_source']}:{attempt['state']}"))


def _plan_delivered(settling: _Settling, attempt: Mapping, transaction: Transaction | None,
                    report_digest: str | None) -> None:
    """A delivered issue's record gives up its launch span, then is sealed `succeeded`. The
    seal's own span, left open by a seal that was cut, is kept."""
    if settling.holder != seal_executor(settling.current):
        if settling.holder is not None and settling.lapsed:
            settling.reap("expiry")
        _record_owner_result(settling, attempt, transaction, report_digest)
        if settling.holder is not None:
            settling.release()
    settling.operations.append(_seal_succeeded(settling.current))
