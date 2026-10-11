"""The effectful half of the delivery transaction (#339 D2, D5-D7, D17).

Each installed delivery contract has one core transaction whose subject is the contract and
whose `event` evidence is every delivery object the ledger holds. `settle_delivery` creates
the transaction of each installed contract that has none and appends the entries each lacks;
`workflow-state` calls it from `commit_state` after `settle_custody` and before the ledger is
published, so a write cut in between leaves entries the ledger lacks, which no reader
consults. An entry a sealed transaction lacks is recorded as a supplement of its receipt. Once
the ledger is published `seal_delivery` seals the transaction of each delivered issue
`succeeded` on the contract's required postconditions, and returns the receipts the custody
seals cite. The module owns those core effects: the creation, the journal appends under a
short span of the executor `delivery_executor(issue)`, the supplements and the proof. It
reaches the core only through `agent_tools.attempt_store`'s `reading` and `writing` seams,
which own the store lock, the clock and the error mapping, and holds no other lock.
`agent_tools.attempt_delivery` holds the pure rules.
"""

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from agent_tools import attempt_custody as custody_rules
from agent_tools import attempt_delivery as delivery_rules
from agent_tools.attempt_store import (
    StoreRefused, helper_span, reach_proving, reading, run_handle, settle_sealed, supplement,
    writing)
from agent_tools.transaction_core import TransactionStore
from agent_tools.transaction_history import TERMINALS, Transaction


class _Pending(NamedTuple):
    """One installed contract: its `issue`, `delivery` object and the journal `entries` its
    transaction should hold."""

    issue: int
    delivery: Mapping
    entries: tuple[delivery_rules.JournalEntry, ...]

    def lacking(self, held: frozenset[str]) -> tuple[delivery_rules.JournalEntry, ...]:
        """The entries whose ids are not in `held`."""
        return tuple(entry for entry in self.entries if entry.evidence_id not in held)


def _probe(core: TransactionStore, issue: int, digest: str) -> Iterator[tuple[int, Transaction]]:
    """Probe `delivery_key(issue, digest, n)` for n = 1, 2, ... to the first unused ordinal:
    each existing transaction with its ordinal. A probed subject that is not the closed
    delivery subject is a `StoreRefused`."""
    ordinal = 0
    while True:
        ordinal += 1
        identity = core.lookup(delivery_rules.delivery_key(issue, digest, ordinal))
        if identity is None:
            return
        transaction = core.load(identity)
        violation = delivery_rules.delivery_subject_violation(transaction.subject)
        if violation is not None:
            raise StoreRefused(
                f"delivery projection mismatch: {transaction.transaction_id}: {violation}")
        yield ordinal, transaction


def delivery_of(core: TransactionStore, run: str, issue: int,
                digest: str) -> tuple[int, Transaction | None]:
    """The first ordinal of the probe whose transaction names `run`, with that transaction,
    or the first unused ordinal with None."""
    ordinal = 0
    for ordinal, transaction in _probe(core, issue, digest):
        if transaction.subject["run"] == run:
            return ordinal, transaction
    return ordinal + 1, None


def installing_runs(store: Path, issue: int, digest: str) -> list[str]:
    """The handles of the runs whose delivery transaction for `issue` carries the contract
    `digest`, in ordinal order, read without a lock.

    A store that does not exist, or a contract with no delivery transaction, answers an empty
    list. Only the transaction is consulted: a ledger a cut write has not yet published
    matches later, at the caller's check of the ledger itself. A transaction whose run
    transaction is not an attempt run is a `StoreRefused`.
    """
    runs: list[str] = []
    with reading(store, 0) as core:  # lookup and load read no clock
        if core is None:
            return runs
        for _, transaction in _probe(core, issue, digest):
            run = transaction.subject["run"]
            handle = run_handle(store, run)
            if handle is None:
                raise StoreRefused(f"delivery run {run} is not an attempt run transaction")
            runs.append(handle)
    return runs


def _installed(state: dict) -> list[tuple[int, Mapping]]:
    """Each issue's delivery object that holds a contract, issues ascending."""
    delivered = ((int(key), state["issues"][key]["delivery"]) for key in state["issues"])
    return sorted(((issue, delivery) for issue, delivery in delivered
                   if delivery["contract"] is not None), key=lambda item: item[0])


def _create(core: TransactionStore, run: str, ordinal: int, pending: _Pending) -> Transaction:
    delivery = pending.delivery
    try:
        subject = delivery_rules.delivery_subject(
            run=run, issue=pending.issue, contract_digest=delivery["contract_digest"],
            contract=delivery["contract"])
    except ValueError as error:
        raise StoreRefused(f"delivery subject of issue {pending.issue}: {error}") from error
    return core.create(
        delivery_rules.delivery_key(pending.issue, delivery["contract_digest"], ordinal),
        subject, **delivery_rules.delivery_creation_arguments(subject))


def _held(core: TransactionStore, transaction: Transaction) -> frozenset[str]:
    """The journal ids `transaction` holds: its evidence and, once sealed, the supplements of
    its receipt."""
    supplements = () if transaction.terminal is None else core.post_terminal_observations(
        transaction.terminal["receipt_digest"])
    return delivery_rules.journaled(transaction, supplements)


def _span(core: TransactionStore, store: Path, transaction: Transaction, issue: int,
          now_ms: int) -> Any:
    """The custody the delivery helpers run under: the transaction's open span of this
    executor that has not lapsed, else a new one."""
    return helper_span(
        core, transaction, executor=delivery_rules.delivery_executor(issue),
        lease_key=delivery_rules.delivery_lease_key(transaction.subject["run"], issue),
        subject_path=str(store.parents[1]), now_ms=now_ms)


def _append(core: TransactionStore, store: Path, transaction: Transaction, issue: int,
            entries: tuple[delivery_rules.JournalEntry, ...], now_ms: int) -> None:
    """Record `entries` as `event` evidence under a span that is released in this call."""
    span = _span(core, store, transaction, issue, now_ms)
    for entry in entries:
        core.record_evidence(span, evidence_id=entry.evidence_id, form="event",
                             reference=entry.reference)
    core.release(span)


def settle_delivery(store: Path, state: dict, *, now_ms: int,
                    canonical_text: Callable[[Any], str]) -> None:
    """Create the delivery transaction of each installed contract of `state` that has
    none, and append the journal entries each transaction lacks; a sealed transaction takes
    each as a supplement of its receipt (#339 D6).

    The read phase takes no lock: with no contract, or no transaction missing and no entry
    lacking, nothing is created, not even the store. Otherwise the write phase runs under the
    store lock, issues ascending, and decides again from what the lock shows. Every core call
    reads the clock `now_ms`; `canonical_text` is the delivery model's canonical form of one
    delivery object. A delivery transaction in the store that is not the closed delivery
    subject is a `StoreRefused`.
    """
    run = state["transaction_id"]
    installed = _installed(state)
    if not installed:
        return
    with reading(store, now_ms) as core:
        pending = []
        for issue, delivery in installed:
            transaction = None if core is None else delivery_of(
                core, run, issue, delivery["contract_digest"])[1]
            work = _Pending(issue, delivery,
                            delivery_rules.journal_entries(delivery, canonical_text))
            if transaction is None or work.lacking(_held(core, transaction)):
                pending.append(work)
    if not pending:
        return
    with writing(store, now_ms) as core:
        for work in pending:
            ordinal, transaction = delivery_of(core, run, work.issue,
                                               work.delivery["contract_digest"])
            if transaction is None:
                transaction = _create(core, run, ordinal, work)
            lacking = work.lacking(_held(core, transaction))
            if lacking and transaction.state in TERMINALS:
                for entry in lacking:
                    supplement(core, transaction.terminal["receipt_digest"],
                               outcome="satisfied", reason=entry.evidence_id,
                               reference=entry.reference)
            elif lacking:
                _append(core, store, transaction, work.issue, lacking, now_ms)


class _Observed:
    """The observer `collect_obligation` calls: it reads nothing but the observation id the
    ledger bound to each required postcondition."""

    def __init__(self, observations: Mapping[str, str]) -> None:
        self._observations = observations

    def observe(self, request: Mapping[str, Any]) -> dict[str, str]:
        return {"outcome": "satisfied", "reason": delivery_rules.OBSERVED,
                "reference": self._observations[request["obligation_id"]]}


def _sealing(core: TransactionStore, state: dict,
             delivered: frozenset[int]) -> Iterator[tuple[int, Mapping, Transaction]]:
    """Each delivered issue's delivery object and its transaction in this run, issues
    ascending; an issue whose transaction does not exist yet is left out."""
    run = state["transaction_id"]
    for issue, delivery in _installed(state):
        if issue in delivered:
            transaction = delivery_of(core, run, issue, delivery["contract_digest"])[1]
            if transaction is not None:
                yield issue, delivery, transaction


def _open(transaction: Transaction) -> bool:
    """Whether a proof is still to be settled: not sealed, and not parked unconverged (D27)."""
    return transaction.state not in TERMINALS and not custody_rules.unconverged(transaction)


def delivery_pending(store: Path, state: dict, delivered: frozenset[int]) -> bool:
    """Whether some delivered issue's delivery transaction has a proof left to settle, read
    without a lock. One the core parked unconverged is not pending (#339 D27)."""
    with reading(store, 0) as core:  # lookup and load read no clock
        return core is not None and any(
            _open(transaction) for _, _, transaction in _sealing(core, state, delivered))


def unconverged_deliveries(store: Path, state: dict, delivered: frozenset[int]) -> frozenset[int]:
    """The issues of `delivered` whose delivery transaction the core parked unconverged (D27),
    read without a lock: the issues whose custody seals are not pending."""
    with reading(store, 0) as core:
        return frozenset() if core is None else frozenset(
            issue for issue, _, transaction in _sealing(core, state, delivered)
            if custody_rules.unconverged(transaction))


def _seal(core: TransactionStore, store: Path, transaction: Transaction, issue: int,
          delivery: Mapping, now_ms: int) -> Transaction:
    """Prove one delivery transaction (#339 D5, D19): its forward states, then each required
    obligation whose latest observation is not an admissible `satisfied`, then the cohort and
    the settlement, in the core's order, all under one span."""
    span = _span(core, store, transaction, issue, now_ms)
    transaction = reach_proving(core, transaction, span)
    observer = _Observed(dict(delivery_rules.collections(delivery)))
    for entry in transaction.proof["obligations"]:
        if not (entry["latest_outcome"] == "satisfied" and entry["latest_admissible"]):
            core.collect_obligation(span, obligation_id=entry["obligation_id"],
                                    observer=observer)
    return settle_sealed(core, span)


def seal_delivery(store: Path, state: dict, *, now_ms: int,
                  delivered: frozenset[int]) -> dict[int, str]:
    """Seal the delivery transaction of each delivered issue `succeeded` on the contract's
    required postconditions, after the ledger is published (#339 D5).

    The read phase takes no lock and, with nothing to prove, returns what it found. Otherwise
    the write phase proves each transaction that is still open, issues ascending, a seal a
    cut write left half done resuming from the state it reached. It returns the receipt
    digest of every delivered issue whose transaction is `succeeded`, which the custody seals
    cite; a proof the core parked unconverged yields none (D27).
    """
    receipts: dict[int, str] = {}
    work = []
    with reading(store, now_ms) as core:
        if core is None:
            return receipts
        for issue, delivery, transaction in _sealing(core, state, delivered):
            if transaction.state == "succeeded":
                receipts[issue] = transaction.terminal["receipt_digest"]
            elif _open(transaction):
                work.append((issue, delivery))
    if not work:
        return receipts
    with writing(store, now_ms) as core:
        run = state["transaction_id"]
        for issue, delivery in work:
            transaction = delivery_of(core, run, issue, delivery["contract_digest"])[1]
            if _open(transaction):
                transaction = _seal(core, store, transaction, issue, delivery, now_ms)
            if transaction.state == "succeeded":
                receipts[issue] = transaction.terminal["receipt_digest"]
    return receipts
