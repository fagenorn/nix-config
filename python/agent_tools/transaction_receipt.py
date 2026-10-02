"""Terminal receipts (#209 D1-D3, D6, D7, D20, D24, D25, D29).

`terminal_receipt` derives the closed `transaction-terminal-receipt/v1` a terminal seals,
purely from a document's immutable metadata and the events it covers: identity, the
`created` event's back-link, authority class and plan digests, the subject's digest, the
outcome, `sealed_at`, the covered `revision` and a `history_digest` over those events, and
a per-outcome `outcome_proof`. `receipt_event_violation` is the walk's rule for the
`receipt_sealed` event that names the receipt, and `terminal_view` the snapshot's derived
`terminal` view of it.

`ReceiptStore` keeps receipts beside the transaction directories, never inside one, so a
receipt outlives a collected ledger: `receipts/<hex>.json`, where `sha256:<hex>` is the
receipt's `telemetry_digest`, holding exactly its `serialize` bytes, mode `0444`. A file is
created once and never replaced, and `read` verifies the bytes, the digest and the schema on
every read. The store's seal order is: `append_events` stamps `receipt_sealed` with the
receipt's digest and the walk re-derives it; `seal` then writes the receipt and reads it
back, and only then is `state.json` written. It reads files but no lock or clock: the
core passes every `at`.
"""

import copy
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_invocation import fold_actions
from agent_tools.transaction_recovery import effect_class
from agent_tools.transaction_storage import (
    ReceiptInvalid, StateInvalid, fsync_directory, lstat_mode, require_directory, serialize,
    strict_loads)

RECEIPT_SCHEMA = "transaction-terminal-receipt/v1"
RECEIPT_EVENT_KEYS = frozenset({"seq", "type", "at", "receipt_digest"})
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


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
    """Every folded action's effect class, by action id in declaration order (D20)."""
    return {"effect_snapshot": {identity: effect_class(entry)
                                for identity, entry in fold_actions(covered).items()}}


def _rolled_back_proof(covered: Sequence[Mapping]) -> dict:
    """The latest `recovery_started`'s snapshot and selection, and the `recovery_settled`'s
    seq, restores and residue (D5)."""
    started, settled = _latest(covered, "recovery_started"), _latest(covered, "recovery_settled")
    return {"recovery_settled_seq": settled["seq"], "effect_snapshot": started["effect_snapshot"],
            "selected": started["selected"], "restored": settled["restored"],
            "residue": settled["residue"]}


_OUTCOME_PROOFS: Mapping[str, Callable[[Sequence[Mapping]], dict]] = MappingProxyType({
    "succeeded": _succeeded_proof, "abandoned": _abandoned_proof,
    "rolled_back": _rolled_back_proof})


def terminal_receipt(document: Mapping, covered: Sequence[Mapping]) -> dict:
    """The receipt that seals `covered`, a detached copy (D3, D25, D29).

    `covered` is the enveloped events from `created` through the transition into a terminal,
    or through the terminal `lease_released` right after it; ending any other way, or in a
    terminal without an outcome proof, is a `ValueError`. Reads `document`'s
    `transaction_id`, `creation_key`, `subject` and `concurrency_keys` only, never its
    `events`, `state`, `parked_from`, `custody` or `revision`. `outcome` is the last
    transition's `to`, `sealed_at` the last covered `at`, `revision` the covered count.
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
        "terminal_qualifier": None, "sealed_at": covered[-1]["at"], "revision": len(covered),
        "history_digest": telemetry_digest(covered),
        "outcome_proof": _OUTCOME_PROOFS[final["to"]](covered)})


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
    `{receipt_digest, outcome, terminal_qualifier}`, derived and never stored."""
    last = document["events"][-1]
    if last["type"] != "receipt_sealed":
        return None
    return MappingProxyType({"receipt_digest": last["receipt_digest"],
                             "outcome": document["state"], "terminal_qualifier": None})


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
        accepted only when it holds the same bytes, so a retried seal is idempotent.
        """
        if type(digest) is not str or telemetry_digest(receipt) != digest:
            raise receipt_invalid(repr(digest), "is not the digest of the receipt to seal")
        path = self._path(digest)
        content = serialize(receipt)
        self._create_once(path, content.encode("ascii"))
        if serialize(dict(self.read(digest))) != content:
            raise receipt_invalid(str(path), "does not read back as the sealed receipt")

    def read(self, digest: Any) -> Mapping[str, Any]:
        """The receipt `digest` names, a read-only view over its strict parse (D7, D20).

        Refused for a malformed digest, a missing, non-regular or unparseable file, bytes
        other than `serialize` of the parse, a parse whose digest is not `digest`, or
        another schema.
        """
        path = self._path(digest)
        try:
            require_directory(path.parent, missing_ok=False)
        except StateInvalid as error:
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
        """Create each missing level of `directory` below the root, fsyncing its parent; a
        level that is a symlink or not a directory is refused."""
        parent = self.root
        for part in directory.relative_to(self.root).parts:
            level = parent / part
            if not require_directory(level, missing_ok=True):
                level.mkdir()
                require_directory(level, missing_ok=False)
                fsync_directory(parent)
            parent = level

    def _create_once(self, path: Path, content: bytes) -> None:
        """Create `path` holding `content`, mode `0444`, never replacing a file (D6, D20).

        A temporary sibling opened `O_CREAT | O_EXCL | O_NOFOLLOW` is written and fsynced,
        hard-linked to `path` and always unlinked, then the directory is fsynced. When
        `path` exists its bytes must be `content`.
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
                    if self._bytes(path) != content:
                        raise receipt_invalid(str(path), "already holds other bytes") from None
            finally:
                temporary.unlink(missing_ok=True)
            fsync_directory(path.parent)
        except ReceiptInvalid:
            raise
        except (OSError, StateInvalid) as error:
            raise receipt_invalid(str(path), f"cannot be written ({error})") from error
