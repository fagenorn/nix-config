"""The effectful half of the delivery transaction (#339 D2, D7, D17).

Each installed delivery contract has one core transaction whose subject is the contract and
whose `event` evidence is every delivery object the ledger holds. `settle_delivery` creates
the transaction of each installed contract that has none and appends the entries each lacks;
`workflow-state` calls it from `commit_state` after `settle_custody` and before the ledger is
published, so a write cut in between leaves entries the ledger lacks, which no reader
consults. The module owns those two core effects: the creation, and the journal appends under
a short span of the executor `delivery_executor(issue)`. It reaches the core only through
`agent_tools.attempt_store`'s `reading` and `writing` seams, which own the store lock, the
clock and the error mapping, and holds no other lock. A terminal transaction is left alone.
`agent_tools.attempt_delivery` holds the pure rules.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from agent_tools import attempt_custody as custody_rules
from agent_tools import attempt_delivery as delivery_rules
from agent_tools.attempt_store import StoreRefused, reading, run_handle, writing
from agent_tools.transaction_core import TransactionStore
from agent_tools.transaction_history import TERMINALS, Transaction


class _Pending(NamedTuple):
    """One installed contract: its `issue`, `delivery` object and the journal `entries` its
    transaction should hold."""

    issue: int
    delivery: Mapping
    entries: tuple[delivery_rules.JournalEntry, ...]

    def lacking(self, transaction: Transaction | None) -> tuple[delivery_rules.JournalEntry, ...]:
        """The entries `transaction` does not hold; a terminal transaction lacks none here."""
        if transaction is not None and transaction.state in TERMINALS:
            return ()
        held = () if transaction is None else delivery_rules.journaled(transaction)
        return tuple(entry for entry in self.entries if entry.evidence_id not in held)


def delivery_of(core: TransactionStore, run: str, issue: int,
                digest: str) -> tuple[int, Transaction | None]:
    """Probe `delivery_key(issue, digest, n)` for n = 1, 2, ...: the first ordinal whose
    transaction names `run`, with that transaction, or the first unused ordinal with None.
    A probed subject that is not the closed delivery subject is a `StoreRefused`."""
    ordinal = 0
    while True:
        ordinal += 1
        identity = core.lookup(delivery_rules.delivery_key(issue, digest, ordinal))
        if identity is None:
            return ordinal, None
        transaction = core.load(identity)
        violation = delivery_rules.delivery_subject_violation(transaction.subject)
        if violation is not None:
            raise StoreRefused(
                f"delivery projection mismatch: {transaction.transaction_id}: {violation}")
        if transaction.subject["run"] == run:
            return ordinal, transaction


def installing_runs(store: Path, issue: int, digest: str) -> list[str]:
    """The handles of the runs whose delivery transaction for `issue` carries the contract
    `digest`, in ordinal order, read without a lock.

    Probes `delivery_key(issue, digest, n)` from 1 to the first miss, so a store that does
    not exist, or a contract with no delivery transaction, answers an empty list. Only the
    transaction is consulted: a ledger a cut write has not yet published matches later, at
    the caller's check of the ledger itself. A transaction that is not the closed delivery
    subject, or whose run transaction is not an attempt run, is a `StoreRefused`.
    """
    runs: list[str] = []
    with reading(store, 0) as core:  # lookup and load read no clock
        if core is None:
            return runs
        ordinal = 0
        while True:
            ordinal += 1
            identity = core.lookup(delivery_rules.delivery_key(issue, digest, ordinal))
            if identity is None:
                return runs
            transaction = core.load(identity)
            violation = delivery_rules.delivery_subject_violation(transaction.subject)
            if violation is not None:
                raise StoreRefused(
                    f"delivery projection mismatch: {transaction.transaction_id}: {violation}")
            run = transaction.subject["run"]
            handle = run_handle(store, run)
            if handle is None:
                raise StoreRefused(f"delivery run {run} is not an attempt run transaction")
            runs.append(handle)


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


def _span(core: TransactionStore, store: Path, transaction: Transaction, issue: int,
          now_ms: int) -> Any:
    """The custody the journal appends run under: the transaction's open span of this
    executor that has not lapsed, else a new one. Over a lapsed span `acquire` is called
    directly, and the core records the lapse."""
    executor, span = delivery_rules.delivery_executor(issue), transaction.custody
    if span is not None and span.executor_id == executor:
        lease = core.inspect_lease(
            delivery_rules.delivery_lease_key(transaction.subject["run"], issue))
        if not custody_rules.span_lapsed(span, lease, now_ms):
            return span
    return core.acquire(
        transaction.transaction_id, executor_id=executor, subject_path=str(store.parents[1]),
        ttl_ms=delivery_rules.HELPER_TTL_MS).custody


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
    none, and append the journal entries each transaction lacks.

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
            if transaction is None or work.lacking(transaction):
                pending.append(work)
    if not pending:
        return
    with writing(store, now_ms) as core:
        for work in pending:
            ordinal, transaction = delivery_of(core, run, work.issue,
                                               work.delivery["contract_digest"])
            if transaction is None:
                transaction = _create(core, run, ordinal, work)
            lacking = work.lacking(transaction)
            if lacking:
                _append(core, store, transaction, work.issue, lacking, now_ms)
