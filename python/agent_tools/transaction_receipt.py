"""Terminal receipts (#209 D1-D4, D6, D7, D10, D13, D20, D24, D25, D29).

`terminal_receipt` derives the closed `transaction-terminal-receipt/v1` a terminal seals,
purely from a document's immutable metadata and the events it covers: identity, the
`created` event's back-link, authority class and plan digests, the subject's digest, the
outcome, its `terminal_qualifier` (the `failure_disposed`'s for `failed`, else null),
`sealed_at`, the covered `revision` and a `history_digest` over those events, and a
per-outcome `outcome_proof`: `succeeded` cites the `proof_sealed`, `abandoned` the
`action_effects` snapshot, `rolled_back` the latest `recovery_started` and the
`recovery_settled`, and `failed` the `failure_disposed`. `postconditions` gives each
proof-plan unit, in plan order, its action's `status`, its latest `satisfied` inspection as
`observed` and whether an attempt was intended as `effected`. `stops` lists each
`stop_synthesized` in seq order with `superseded_by`, the seq of the first `owner_result`
that supersedes it. `owner_results` lists each `owner_result` in seq order with its result
only as `result_digest`. `evaluations` gives each plan obligation, in plan order, its
evaluation and reason at `sealed_at` and its latest `obligation_observed` as
`evidence_id`. `receipt_event_violation` is the walk's rule for the `receipt_sealed` event
that names the receipt, and `terminal_view` the snapshot's derived `terminal` view of it.

`ReceiptStore` keeps receipts beside the transaction directories, never inside one, so a
receipt outlives a collected ledger: `receipts/<hex>.json`, where `sha256:<hex>` is the
receipt's `telemetry_digest`, holding exactly its `serialize` bytes, mode `0444`. A file is
created once and never replaced, and `read` verifies the bytes, the digest and the schema on
every read. The store's seal order is: `append_events` stamps `receipt_sealed` with the
receipt's digest and the walk re-derives it; `seal` then writes the receipt, reads it back
and, for an `effects_unobservable` receipt, writes one `transaction-hazard-marker/v1` per
concurrency key at `hazards/<sha256 hex of the key>/<receipt hex>.json`; only then is
`state.json` written. Post-terminal observations are numbered files beside the receipt,
`observations/<receipt hex>/<n>.json`, that never touch it or a ledger (D12, D18). Every
listing re-validates each file it lists. It reads files but no lock or clock: the core
passes every `at`.
"""

import copy
import hashlib
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_disposition import (
    FAILURE_REASON, OBSERVABILITY_GROUNDS, action_effects)
from agent_tools.transaction_invocation import fold_actions, status
from agent_tools.transaction_proof import closed_result_violation, evaluate
from agent_tools.transaction_storage import (
    ReceiptInvalid, StateInvalid, fsync_directory, lstat_mode, parse_at, require_directory,
    serialize, strict_loads)

RECEIPT_SCHEMA = "transaction-terminal-receipt/v1"
HAZARD_SCHEMA = "transaction-hazard-marker/v1"
OBSERVATION_SCHEMA = "transaction-post-terminal-observation/v1"
RECEIPT_EVENT_KEYS = frozenset({"seq", "type", "at", "receipt_digest"})
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_HEX_NAME = re.compile(r"([0-9a-f]{64})\.json")
_NUMBER_NAME = re.compile(r"([1-9][0-9]*)\.json")
_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_RESULT_FIELDS = ("outcome", "reason", "reference")
_OBSERVATION_KEYS = frozenset({"schema", "receipt_digest", "n", "at", "contradicts_ground",
                               *_RESULT_FIELDS})


def receipt_invalid(where: str, detail: str) -> ReceiptInvalid:
    """The one construction path of `ReceiptInvalid`: `where`, then the rule broken."""
    return ReceiptInvalid(f"{where}: {detail}")


def _latest(covered: Sequence[Mapping], event_type: str) -> Mapping:
    return [event for event in covered if event["type"] == event_type][-1]


def _succeeded_proof(covered: Sequence[Mapping]) -> dict:
    """The `proof_sealed` that sealed the proof."""
    seal = _latest(covered, "proof_sealed")
    return {"proof_sealed_seq": seal["seq"], "proof_cutoff_at": seal["proof_cutoff_at"],
            "advisory_warnings": seal["advisory_warnings"]}


def _abandoned_proof(covered: Sequence[Mapping]) -> dict:
    """Every folded action's effect class, `action_effects` (D20)."""
    return {"effect_snapshot": action_effects(covered)}


def _rolled_back_proof(covered: Sequence[Mapping]) -> dict:
    """The latest `recovery_started`'s snapshot and selection, and the `recovery_settled`'s
    seq, restores and residue (D5)."""
    started, settled = _latest(covered, "recovery_started"), _latest(covered, "recovery_settled")
    return {"recovery_settled_seq": settled["seq"], "effect_snapshot": started["effect_snapshot"],
            "selected": started["selected"], "restored": settled["restored"],
            "residue": settled["residue"]}


def _failed_proof(covered: Sequence[Mapping]) -> dict:
    """The `failure_disposed`'s seq, ground, successor, snapshot and units (#209 D9, D10)."""
    disposed = _latest(covered, FAILURE_REASON)
    return {"disposition_seq": disposed["seq"], "ground": disposed["ground"],
            "ground_reference": disposed["reference"],
            "ground_occurred_at": disposed["occurred_at"], "successor": disposed["successor"],
            "successor_receipt": disposed["successor_receipt"],
            "effect_snapshot": disposed["effect_snapshot"], "units": disposed["units"]}


_OUTCOME_PROOFS: Mapping[str, Callable[[Sequence[Mapping]], dict]] = MappingProxyType({
    "succeeded": _succeeded_proof, "abandoned": _abandoned_proof,
    "rolled_back": _rolled_back_proof, "failed": _failed_proof})


def _qualifier(events: Sequence[Mapping], outcome: str) -> str | None:
    """The latest `failure_disposed`'s qualifier for `failed`, else None."""
    return _latest(events, FAILURE_REASON)["qualifier"] if outcome == "failed" else None


def _postconditions(plan: Mapping, covered: Sequence[Mapping]) -> list[dict]:
    """Each plan unit from its action's fold: `status` and `observed` None and `effected`
    false when the action has no event (D4, D20; #208 D19)."""
    actions = fold_actions(covered)
    entries = []
    for unit in plan["units"]:
        identity = unit["action_id"]
        fold = actions.get(identity)
        seen = [event for event in covered if event["type"] == "action_inspected"
                and event["action_id"] == identity and event["outcome"] == "satisfied"]
        entries.append({
            "unit": identity, "name": unit["name"], "phase": unit["phase"],
            "status": None if fold is None else status(fold),
            "observed": {key: seen[-1][key] for key in ("seq", "at", "reference", "fence")}
            if seen else None,
            "effected": fold is not None and fold.attempts > 0})
    return entries


def _stops(covered: Sequence[Mapping]) -> list[dict]:
    """Each `stop_synthesized`, linked to the first `owner_result` superseding it (D13)."""
    results = [event for event in covered if event["type"] == "owner_result"]
    return [{"seq": stop["seq"], "executor_id": stop["executor_id"], "fence": stop["fence"],
             "reason": stop["reason"],
             "superseded_by": next((result["seq"] for result in results
                                    if result["supersedes"] == stop["seq"]), None)}
            for stop in covered if stop["type"] == "stop_synthesized"]


def _owner_results(covered: Sequence[Mapping]) -> list[dict]:
    """Each `owner_result`, its body only as a digest (D3, D13)."""
    return [{"seq": result["seq"], "executor_id": result["executor_id"],
             "fence": result["fence"], "custody": result["custody"],
             "supersedes": result["supersedes"],
             "result_digest": telemetry_digest(result["result"])}
            for result in covered if result["type"] == "owner_result"]


def _evaluations(plan: Mapping, covered: Sequence[Mapping]) -> list[dict]:
    """Each plan obligation's evaluation at the last covered `at`, citing its latest
    `obligation_observed`, else None (D20)."""
    evaluations = evaluate(plan, covered, parse_at(covered[-1]["at"]))
    latest = {event["obligation_id"]: event["evidence_id"] for event in covered
              if event["type"] == "obligation_observed"}
    return [{"obligation_id": identity, "evaluation": evaluations[identity][0],
             "reason": evaluations[identity][1], "evidence_id": latest.get(identity)}
            for identity in (entry["obligation_id"] for entry in plan["obligations"])]


def terminal_receipt(document: Mapping, covered: Sequence[Mapping]) -> dict:
    """The receipt that seals `covered`, a detached copy (D3, D25, D29).

    `covered` is the enveloped events from `created` through the transition into a terminal,
    or through the terminal `lease_released` right after it; ending any other way, or in a
    terminal without an outcome proof, is a `ValueError`. Reads `document`'s
    `transaction_id`, `creation_key`, `subject`, `concurrency_keys` and `proof_plan` only,
    never its `events`, `state`, `parked_from`, `custody` or `revision`. `outcome` is the last
    transition's `to`, `terminal_qualifier` the latest `failure_disposed`'s `qualifier` for
    `failed` and null otherwise, `sealed_at` the last covered `at`, `revision` the covered
    count.
    """
    covered = list(covered)
    final = (covered[-2] if len(covered) > 1 and covered[-1]["type"] == "lease_released"
             and covered[-1]["reason"] == "terminal" else covered[-1] if covered else None)
    if final is None or final["type"] != "transitioned" or final["to"] not in _OUTCOME_PROOFS:
        raise ValueError("covered does not end in a sealable terminal transition")
    created = covered[0]
    return copy.deepcopy({
        "schema": RECEIPT_SCHEMA, "transaction_id": document["transaction_id"],
        "creation_key": document["creation_key"], "recovers": created["recovers"],
        "authority_class": created["authority_class"],
        "concurrency_keys": list(document["concurrency_keys"]),
        "subject_digest": telemetry_digest(document["subject"]),
        "proof_plan_digest": created["proof_plan_digest"],
        "recovery_plan_digest": created["recovery_plan_digest"], "outcome": final["to"],
        "terminal_qualifier": _qualifier(covered, final["to"]), "sealed_at": covered[-1]["at"],
        "revision": len(covered),
        "history_digest": telemetry_digest(covered),
        "outcome_proof": _OUTCOME_PROOFS[final["to"]](covered),
        "postconditions": _postconditions(document["proof_plan"], covered),
        "stops": _stops(covered), "owner_results": _owner_results(covered),
        "evaluations": _evaluations(document["proof_plan"], covered)})


def _is_at(value: Any) -> bool:
    """Whether `value` is a `YYYY-MM-DDTHH:MM:SS.mmmZ` stamp that `parse_at` accepts."""
    if type(value) is not str or _AT_PATTERN.fullmatch(value) is None:
        return False
    try:
        parse_at(value)
    except ValueError:
        return False
    return True


def _observation_violation(observation: Any, contradicts_ground: Any, at: Any,
                           receipt: Mapping) -> str | None:
    """How a post-terminal observation breaks its value rules against `receipt`, or None:
    the one validator of insertion and read (D12, D22, D31). The observation is the closed
    `closed_result_violation` object, `at` a core timestamp, `contradicts_ground` a bool,
    and true only on a `failed` receipt whose ground is an observability ground."""
    violation = closed_result_violation(observation, "observation")
    if violation is not None:
        return violation
    if not _is_at(at):
        return f"at {at!r} is not a core timestamp"
    if type(contradicts_ground) is not bool:
        return f"contradicts_ground {contradicts_ground!r} is not a bool"
    if contradicts_ground and (receipt["outcome"] != "failed" or receipt["outcome_proof"][
            "ground"] not in OBSERVABILITY_GROUNDS):
        return "contradicts_ground is legal only on a failed receipt with an observability ground"
    return None


def receipt_event_violation(event: dict, events_before: Sequence[Mapping],
                            document: dict) -> str | None:
    """How a `receipt_sealed` the walk admitted after a terminal breaks its rule, or None
    (D7, D24): its `at` must be the terminal transition's, and its `receipt_digest` the
    `telemetry_digest` of `terminal_receipt(document, events_before)`."""
    terminal = _latest(events_before, "transitioned")
    if event["at"] != terminal["at"]:
        return "receipt_sealed at is not the terminal transition's at"
    if event["receipt_digest"] != telemetry_digest(terminal_receipt(document, events_before)):
        return "receipt_sealed receipt_digest is not the digest of the terminal receipt"
    return None


def terminal_view(document: dict) -> Mapping | None:
    """None unless the last event is `receipt_sealed`; else a read-only
    `{receipt_digest, outcome, terminal_qualifier}`, the receipt's qualifier, derived and
    never stored."""
    events = document["events"]
    if events[-1]["type"] != "receipt_sealed":
        return None
    return MappingProxyType({"receipt_digest": events[-1]["receipt_digest"],
                             "outcome": document["state"],
                             "terminal_qualifier": _qualifier(events, document["state"])})


class ReceiptStore:
    """The permanent receipt files under the store `root` (D6, D20).

    Every failure, an `OSError` or a refused path included, is `ReceiptInvalid` naming the
    file's path.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, digest: Any) -> Path:
        if type(digest) is not str or _DIGEST_PATTERN.fullmatch(digest) is None:
            raise receipt_invalid(repr(digest), "is not a sha256:<64 lowercase hex> digest")
        return self.root / "receipts" / (digest.removeprefix("sha256:") + ".json")

    def seal(self, receipt: dict, digest: str) -> None:
        """Write `receipt` at the name `digest` gives, then read it back (D2, D29).

        Refused unless `digest` is the receipt's `telemetry_digest`; an existing file is
        accepted only when it holds the same bytes, so a retried seal is idempotent. An
        `effects_unobservable` receipt then gets one hazard marker per concurrency key, each
        created the same way (D6, D12, D22).
        """
        if type(digest) is not str or telemetry_digest(receipt) != digest:
            raise receipt_invalid(repr(digest), "is not the digest of the receipt to seal")
        path = self._path(digest)
        content = serialize(receipt)
        self._create_once(path, content.encode("ascii"))
        if serialize(dict(self.read(digest))) != content:
            raise receipt_invalid(str(path), "does not read back as the sealed receipt")
        if receipt["terminal_qualifier"] == "effects_unobservable":
            for key in receipt["concurrency_keys"]:
                marker = {"schema": HAZARD_SCHEMA, "key": key, "receipt_digest": digest}
                self._create_once(self._hazards(key) / path.name,
                                  serialize(marker).encode("ascii"))

    def read(self, digest: Any) -> Mapping[str, Any]:
        """The receipt `digest` names, a read-only view over its strict parse (D7, D20).

        Refused for a malformed digest, a missing, non-directory or unreadable `receipts`
        directory, a missing, non-regular or unparseable file, bytes other than `serialize`
        of the parse, a parse whose digest is not `digest`, or another schema.
        """
        path = self._path(digest)
        try:
            require_directory(path.parent, missing_ok=False)
        except (OSError, StateInvalid) as error:
            raise receipt_invalid(str(path), f"receipts directory refused ({error})") from error
        raw = self._bytes(path)
        try:
            receipt = strict_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise receipt_invalid(str(path), f"not strict JSON ({error})") from error
        if type(receipt) is not dict or serialize(receipt).encode("ascii") != raw:
            raise receipt_invalid(str(path), "bytes are not the serialized receipt")
        if telemetry_digest(receipt) != digest:
            raise receipt_invalid(str(path), "content is not the receipt its name digests")
        if receipt.get("schema") != RECEIPT_SCHEMA:
            raise receipt_invalid(str(path), f"schema is not {RECEIPT_SCHEMA}")
        return MappingProxyType(receipt)

    def _hazards(self, key: str) -> Path:
        return self.root / "hazards" / hashlib.sha256(key.encode("utf-8")).hexdigest()

    def hazard_markers(self, key: str) -> tuple[str, ...]:
        """The sorted receipt digests marked under `key`, or `()` when none are (D12, D22).

        Each marker is re-validated: its `serialize` bytes, the closed keys, the schema,
        `key`, and a `receipt_digest` its file name gives. It reads no receipt.
        """
        digests = []
        for path, match in self._listing(self._hazards(key), _HEX_NAME):
            marker = self._document(path)
            expected = {"schema": HAZARD_SCHEMA, "key": key,
                        "receipt_digest": "sha256:" + match.group(1)}
            if marker != expected:
                raise receipt_invalid(str(path), f"is not the {HAZARD_SCHEMA} marker it names")
            digests.append(expected["receipt_digest"])
        return tuple(sorted(digests))

    def record_observation(self, receipt_digest: Any, observation: Any,
                           contradicts_ground: Any, at: str) -> Mapping[str, Any]:
        """Append the next numbered observation of the receipt `receipt_digest` names, a
        read-only view of its record (D12, D18, D22, D26).

        The receipt is read first; an observation `_observation_violation` refuses is
        `StateInvalid` before any write. The record copies the observation's three fields.
        `n` starts one past the files present and moves on at each collision, so no file is
        replaced. It never touches the receipt, a ledger or a lease.
        """
        receipt = self.read(receipt_digest)
        violation = _observation_violation(observation, contradicts_ground, at, receipt)
        if violation is not None:
            raise StateInvalid(f"{receipt['transaction_id']}: record_post_terminal: {violation}")
        directory = self._observations(receipt_digest)
        n = len(self._listing(directory, _NUMBER_NAME)) + 1
        while True:
            record = {"schema": OBSERVATION_SCHEMA, "receipt_digest": receipt_digest, "n": n,
                      "at": at, "contradicts_ground": contradicts_ground,
                      **{name: observation[name] for name in _RESULT_FIELDS}}
            try:
                self._create_once(directory / f"{n}.json", serialize(record).encode("ascii"),
                                  exclusive=True)
            except FileExistsError:
                n += 1
                continue
            return MappingProxyType(record)

    def observations(self, receipt_digest: Any) -> tuple[Mapping[str, Any], ...]:
        """The receipt's observations ordered by `n`, each a read-only view (D12, D22, D31).

        The receipt is read first. Each file is re-validated: its `serialize` bytes, the
        closed keys, the schema, `receipt_digest`, an `n` its name gives, and every value
        rule `record_observation` enforces.
        """
        receipt = self.read(receipt_digest)
        records = []
        for path, match in self._listing(self._observations(receipt_digest), _NUMBER_NAME):
            record = self._document(path)
            if set(record) != _OBSERVATION_KEYS or record["schema"] != OBSERVATION_SCHEMA:
                raise receipt_invalid(str(path), f"is not a closed {OBSERVATION_SCHEMA} record")
            if record["receipt_digest"] != receipt_digest:
                raise receipt_invalid(str(path), "names another receipt")
            if type(record["n"]) is not int or record["n"] != int(match.group(1)):
                raise receipt_invalid(str(path), "n is not its file name")
            violation = _observation_violation(
                {name: record[name] for name in _RESULT_FIELDS}, record["contradicts_ground"],
                record["at"], receipt)
            if violation is not None:
                raise receipt_invalid(str(path), violation)
            records.append(record)
        return tuple(MappingProxyType(record) for record in
                     sorted(records, key=lambda record: record["n"]))

    def _observations(self, receipt_digest: str) -> Path:
        return self.root / "observations" / receipt_digest.removeprefix("sha256:")

    def _listing(self, directory: Path, name: re.Pattern) -> list[tuple[Path, re.Match]]:
        """Each file in `directory` and its `name` match, `[]` when `directory` is missing.

        `directory` and its parent below the root must be real directories; the create
        helper's temporary siblings (a leading `.`) are skipped, any other unmatched name
        is refused.
        """
        try:
            for level in (directory.parent, directory):
                if not require_directory(level, missing_ok=True):
                    return []
            entries = sorted(os.listdir(directory))
        except (OSError, StateInvalid) as error:
            raise receipt_invalid(str(directory), f"cannot be listed ({error})") from error
        listed = []
        for entry in entries:
            match = name.fullmatch(entry)
            if match is None and not entry.startswith("."):
                raise receipt_invalid(str(directory / entry), "is not a file this store names")
            if match is not None:
                listed.append((directory / entry, match))
        return listed

    def _document(self, path: Path) -> dict:
        """The strict parse of one listed file whose bytes are its `serialize` bytes."""
        raw = self._bytes(path)
        try:
            document = strict_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise receipt_invalid(str(path), f"not strict JSON ({error})") from error
        if type(document) is not dict or serialize(document).encode("ascii") != raw:
            raise receipt_invalid(str(path), "bytes are not a serialized object")
        return document

    @staticmethod
    def _bytes(path: Path) -> bytes:
        """The bytes of one regular, non-symlinked file."""
        try:
            mode = lstat_mode(path)
            if mode is None:
                raise receipt_invalid(str(path), "file is missing")
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise receipt_invalid(str(path), "not a regular file")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with open(descriptor, "rb") as handle:
                return handle.read()
        except OSError as error:
            raise receipt_invalid(str(path), f"unreadable ({error.strerror})") from error

    def _directory(self, directory: Path) -> None:
        """Create each missing level of `directory` below the root and fsync every level's
        parent; a level that is a symlink or not a directory is refused.

        The parent is fsynced whether or not this call made the level: a writer that died
        between `mkdir` and its fsync, or a concurrent first writer still inside that
        window, leaves an entry this caller must not assume durable before it seals.
        """
        parent = self.root
        for part in directory.relative_to(self.root).parts:
            level = parent / part
            if not require_directory(level, missing_ok=True):
                try:
                    level.mkdir()
                except FileExistsError:  # a concurrent first writer made it
                    pass
                require_directory(level, missing_ok=False)
            fsync_directory(parent)
            parent = level

    def _create_once(self, path: Path, content: bytes, *, exclusive: bool = False) -> None:
        """Create `path` holding `content`, mode `0444`, never replacing a file (D6, D20).

        A temporary sibling opened `O_CREAT | O_EXCL | O_NOFOLLOW` is written and fsynced,
        hard-linked to `path` and always unlinked, then the directory is fsynced. When
        `path` exists its bytes must be `content`, or, when `exclusive`, the collision is a
        `FileExistsError` to the caller.
        """
        try:
            self._directory(path.parent)
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 0o444)
            try:
                with open(descriptor, "wb") as output:
                    os.fchmod(output.fileno(), 0o444)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if exclusive:
                        raise
                    if self._bytes(path) != content:
                        raise receipt_invalid(str(path), "already holds other bytes") from None
            finally:
                temporary.unlink(missing_ok=True)
            fsync_directory(path.parent)
        except ReceiptInvalid:
            raise
        except (OSError, StateInvalid) as error:
            if exclusive and isinstance(error, FileExistsError):
                raise
            raise receipt_invalid(str(path), f"cannot be written ({error})") from error
