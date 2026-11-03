"""The pure half of delivery custody (#339): the delivery transaction and remainder custody.

Every rule here needs no file, lock, clock or environment variable, and nothing from the skill
scripts is imported: the delivery model lives there, so a caller passes its canonical-text
function in where a rule needs the canonical form of a delivery object (#339 D14). The module
holds the keys and the closed `attempt-delivery/v1` subject of a delivery transaction (one per
installed contract), the proof plan compiled from the contract's required postconditions, the
journal that carries the ledger's delivery objects as `event` evidence, the `(postcondition,
observation)` pairs a sealing collects, and the closed `remainder-custody/v1` subject of a
delivery remainder, which `agent_tools.attempt_custody`'s settle planner plans through the same
rows as an attempt. `agent_tools.attempt_custody` is imported here, never the reverse.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from agent_tools import attempt_custody as custody_rules
from agent_tools.transaction_storage import is_id

DELIVERY_SCHEMA = "attempt-delivery/v1"
DELIVERY_AUTHORITY_CLASS = "attempt-delivery"
REMAINDER_SCHEMA = "remainder-custody/v1"
# The delivery model's postconditions, in its order (`delivery_model._objects`).
POSTCONDITIONS = ("implementation_delivered", "pr_merged", "tracker_closed", "cleanup_complete")
# The ledger's lists of delivery objects the journal carries, in the order it appends them.
# `stage_facts` and `postconditions` are derived from these by the delivery model, so they are
# not journaled.
JOURNAL_KINDS = ("authorization_intents", "authority_observations", "reevaluation_evidence",
                 "authority_evaluation_consumptions", "delivery_observations",
                 "selected_outputs")
COLLECTOR = "delivery"
COLLECTION_LATENCY_MS = 30_000
OBSERVED = "observed"
RECEIPT_EVIDENCE = "delivery-receipt"
# The window of the span a helper takes for a delivery write or a seal.
HELPER_TTL_MS = 60_000

_DELIVERY_KEYS = frozenset({"schema", "run", "issue", "contract_digest", "contract"})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MARKS = ("required", "not_applicable")


class JournalEntry(NamedTuple):
    """One delivery object as an `event` evidence entry: `evidence_id` is `<kind>:<object
    id>` and `reference` the object's canonical text."""

    evidence_id: str
    reference: str


def delivery_key(issue: int, contract_digest: str, ordinal: int) -> str:
    """The creation key `attempt-delivery/v1:<issue>:<contract digest>:<ordinal>`."""
    return f"{DELIVERY_SCHEMA}:{issue}:{contract_digest}:{ordinal}"


def delivery_lease_key(run: str, issue: int) -> str:
    """The one concurrency key of a delivery transaction: `attempt-delivery:<run>:<issue>`."""
    return f"{DELIVERY_AUTHORITY_CLASS}:{run}:{issue}"


def delivery_executor(issue: int) -> str:
    """The executor of the span a helper takes on an issue's delivery transaction."""
    return f"delivery:{issue}"


def _contract_violation(contract: object, issue: object) -> str | None:
    if not isinstance(contract, Mapping) or contract.get("issue") != issue:
        return "subject contract does not name the subject's issue"
    deliverable = contract.get("deliverable")
    marks = deliverable.get("obligations") if isinstance(deliverable, Mapping) else None
    if not isinstance(marks, Mapping) or set(marks) != set(POSTCONDITIONS) \
            or any(mark not in _MARKS for mark in marks.values()):
        return "subject contract does not mark each postcondition required or not_applicable"
    return None


def delivery_subject_violation(value: object) -> str | None:
    """Why `value` is not the closed attempt-delivery/v1 subject, else None."""
    if not isinstance(value, Mapping) or set(value) != _DELIVERY_KEYS:
        return f"subject is not the closed {DELIVERY_SCHEMA} object"
    if value["schema"] != DELIVERY_SCHEMA:
        return f"subject schema is not {DELIVERY_SCHEMA}"
    if not is_id(value["run"]):
        return "subject run is not a transaction id"
    if not custody_rules.is_ordinal(value["issue"]):
        return "subject issue is not an integer of at least 1"
    if type(value["contract_digest"]) is not str or _DIGEST.fullmatch(
            value["contract_digest"]) is None:
        return "subject contract_digest is not a sha256 digest"
    return _contract_violation(value["contract"], value["issue"])


def delivery_subject(*, run: str, issue: int, contract_digest: str, contract: Mapping) -> dict:
    """The closed subject of an issue's delivery transaction; ValueError carries the text of
    `delivery_subject_violation`."""
    built = {"schema": DELIVERY_SCHEMA, "run": run, "issue": issue,
             "contract_digest": contract_digest, "contract": contract}
    violation = delivery_subject_violation(built)
    if violation is not None:
        raise ValueError(violation)
    return built


def required_postconditions(contract: Mapping) -> tuple[str, ...]:
    """The postconditions `contract` marks `required`, in `POSTCONDITIONS` order."""
    marks = contract["deliverable"]["obligations"]
    return tuple(name for name in POSTCONDITIONS if marks[name] == "required")


def proof_declaration(contract: Mapping) -> dict:
    """The proof plan of a delivery transaction: one deterministic collector and, per required
    postcondition, one required `event` obligation named for it. A contract that requires
    none gets the inert declaration. Applicability is declared here, never inferred later."""
    required = required_postconditions(contract)
    if not required:
        return {"units": [], "obligations": [], "collectors": {}}
    return {
        "units": [],
        "collectors": {COLLECTOR: {"basis": "deterministic",
                                   "max_collection_latency_ms": COLLECTION_LATENCY_MS,
                                   "predicates": list(required)}},
        "obligations": [{"id": name, "semantic": "readiness", "form": "event",
                         "predicate": name, "collector": COLLECTOR, "required": True,
                         "deps": [], "parameters": {}} for name in required]}


def delivery_creation_arguments(subject: Mapping) -> dict:
    """The keyword arguments of `TransactionStore.create` for a delivery transaction: its one
    concurrency key, the proof declaration its contract compiles to, the empty recovery plan
    and the authority class."""
    return {"concurrency_keys": [delivery_lease_key(subject["run"], subject["issue"])],
            "proof": proof_declaration(subject["contract"]),
            "recovery": {"effects": {}, "units": []},
            "authority_class": DELIVERY_AUTHORITY_CLASS}


def journal_entries(delivery: Mapping,
                    canonical_text: Callable[[Any], str]) -> tuple[JournalEntry, ...]:
    """Every delivery object of the ledger as a journal entry: kind by kind in
    `JOURNAL_KINDS` order, each list in stored order. `canonical_text` is the delivery
    model's own canonical form of one object."""
    return tuple(JournalEntry(f"{kind}:{item['id']}", canonical_text(item))
                 for kind in JOURNAL_KINDS for item in delivery[kind])


def journaled(transaction: Any, supplements: Iterable[Mapping] = ()) -> frozenset[str]:
    """The journal ids a delivery transaction already holds: its evidence entries and, for
    objects that arrived after its seal, the `reason` of each post-terminal supplement."""
    return frozenset(entry["evidence_id"] for entry in transaction.evidence) \
        | frozenset(entry["reason"] for entry in supplements)


def collections(delivery: Mapping) -> tuple[tuple[str, str], ...]:
    """The `(postcondition, observation id)` pair of each postcondition the delivery's
    contract requires, in `POSTCONDITIONS` order; ValueError when one is not `observed`."""
    pairs = []
    for name in required_postconditions(delivery["contract"]):
        postcondition = delivery["postconditions"][name]
        if postcondition["state"] != OBSERVED:
            raise ValueError(f"postcondition {name} is {postcondition['state']}, not observed")
        pairs.append((name, postcondition["observation_id"]))
    return tuple(pairs)


def remainder_key(run: str, issue: int, remainder: int) -> str:
    """The creation key `attempt-custody/v1:<run>:<issue>:r<remainder>` of a remainder's
    custody transaction."""
    return f"{custody_rules.SUBJECT_SCHEMA}:{run}:{issue}:r{remainder}"


def remainder_launch_id(issue: int, remainder: int, launch: int) -> str:
    """The launch's action id `<issue>:r<remainder>:<launch>`, also its span's `executor_id`."""
    return f"{issue}:r{remainder}:{launch}"


def remainder_subject_violation(value: object) -> str | None:
    """Why `value` is not the closed remainder-custody/v1 subject, else None."""
    return custody_rules.custody_subject_violation(
        value, schema=REMAINDER_SCHEMA, ordinal="remainder")


def remainder_subject(*, run: str, issue: int, remainder: int, worktree: str,
                      prior: str | None, bound_launch: int | None) -> dict:
    """The closed subject of a remainder's custody transaction; ValueError carries the text
    of `remainder_subject_violation`. It is created with
    `attempt_custody.creation_arguments`."""
    built = {"schema": REMAINDER_SCHEMA, "run": run, "issue": issue, "remainder": remainder,
             "worktree": worktree, "prior": prior, "bound_launch": bound_launch}
    violation = remainder_subject_violation(built)
    if violation is not None:
        raise ValueError(violation)
    return built


def plan_remainder_migration(document: Mapping) -> dict[tuple[int, int], int]:
    """The pure bind plan: `(issue, remainder ordinal) -> launch count` for each delivery
    remainder whose state is live."""
    return {(int(key), record["remainder"]): len(record["launches"])
            for key, issue_state in document["issues"].items()
            for record in issue_state["delivery_remainders"]
            if record["state"] in custody_rules.LIVE_STATES}
