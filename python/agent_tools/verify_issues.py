"""Trusted block and marker selection for the verify-pending run (issue 630).

An issue's held verification is the newest `verify` block posted by a trusted author (P3): a
comment whose association is in `TRUSTED`, that is not itself a marker and whose body carries a
`verify` fence. Unfenced JSON is never a block, an unparsable newest block never falls back to
an older one, and the newest block is chosen by comment id, not by time.

The run's markers are the markers after that block by a trusted author, `end` markers included,
and the trusted `window-open` and `end` markers before it: a window belongs to a merge and an
event, not to a block, so a replacement block inherits it. Every other author's marker is invisible.

A result's identity is its block version and check index; the `ac` field is never part of it (P15).
A block version is the block comment's id and a digest of the block's content (`block_key`), so
editing or reordering the checks of a comment keeps the id but starts a new version: a marker
written for an earlier version names another `block` and is never read back as this one's.

This module runs no process, reads no clock and touches no file.
"""
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from agent_tools import forge_markers, verify_block

TRUSTED = ("OWNER", "MEMBER")
RESULT, RUN, WINDOW, DUE, FOLLOWUP, CLOSED, FOLLOWUP_OF = (
    "verify-result", "verify-run", "window-open", "verify-due",
    "verify-followup", "verify-closed", "verify-followup-of")


@dataclass(frozen=True)
class Comment:
    id: int
    association: str
    body: str
    created_at: str


@dataclass(frozen=True)
class Held:
    block_id: int
    block: object | None
    errors: list[dict]
    markers: list[forge_markers.Marker]
    key: str = ""


def block_key(block_id: int, block: object | None) -> str:
    """The version of a block: `<comment id>.<digest of its canonical JSON>`, the bare id when unparsed."""
    if block is None:
        return str(block_id)
    text = json.dumps(block, sort_keys=True, separators=(",", ":"))
    return f"{block_id}.{hashlib.sha256(text.encode()).hexdigest()[:16]}"


def comment_id(value: object) -> int:
    """A comment id from GraphQL's `fullDatabaseId`: a BigInt, so a string of ASCII digits.

    `databaseId` is a 32-bit Int that the forge cannot fill for this repository's comment ids
    (about 6.7e9), so it is never read; anything but decimal digits is `payload_invalid`."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise forge_markers.ForgeError("payload_invalid", f"comment fullDatabaseId {value!r}")
    return int(value)


def comments_from_graphql(nodes: list) -> list[Comment]:
    """The comments of GraphQL nodes, ascending id; ForgeError `payload_invalid` for a bad node."""
    comments = []
    for node in nodes:
        if not isinstance(node, dict):
            raise forge_markers.ForgeError("payload_invalid", f"comment node {node!r} is not an object")
        cid = comment_id(node.get("fullDatabaseId"))
        for key in ("authorAssociation", "body", "createdAt"):
            if not isinstance(node.get(key), str):
                raise forge_markers.ForgeError("payload_invalid", f"comment {cid} has no string {key}")
        comments.append(Comment(cid, node["authorAssociation"], node["body"], node["createdAt"]))
    return sorted(comments, key=lambda c: c.id)


def _as_marker(comment: Comment) -> forge_markers.Marker | None:
    return forge_markers.parse({"id": comment.id, "body": comment.body, "updated_at": comment.created_at})


def _is_block(comment: Comment) -> bool:
    return (comment.association in TRUSTED and _as_marker(comment) is None
            and verify_block.FENCE.search(comment.body.replace("\r\n", "\n")) is not None)


def select(comments: list[Comment]) -> Held | None:
    """The newest trusted block with the trusted markers after it, or None when there is no block."""
    blocks = [c for c in comments if _is_block(c)]
    if not blocks:
        return None
    newest = max(blocks, key=lambda c: c.id)
    block, errors = verify_block.parse_block(newest.body)
    found = [_as_marker(c) for c in comments if c.association in TRUSTED]
    markers = visible([m for m in found if m is not None], newest.id)
    return Held(newest.id, block, errors, markers, block_key(newest.id, block))


def visible(markers: list[forge_markers.Marker], block_id: int) -> list[forge_markers.Marker]:
    """The trusted `markers` a run reads for the block comment `block_id`, ascending id: those
    after it, and the window and `end` markers before it. The caller passes trusted markers only."""
    found = [m for m in markers if m.comment_id != block_id and (
        m.comment_id > block_id or m.kind in (WINDOW, forge_markers.END_KIND))]
    return sorted(found, key=lambda m: m.comment_id)


def latest_result(markers: list[forge_markers.Marker], key: str, check: int) -> forge_markers.Marker | None:
    """The newest live result of the check of block version `key`, whatever its `ac` field says."""
    found = [m for m in markers if m.kind == RESULT and m.fields.get("block") == key
             and m.fields.get("check") == str(check) and forge_markers.is_live(m, markers)]
    return max(found, key=lambda m: m.comment_id, default=None)


def live_one(markers: list[forge_markers.Marker], kind: str, match: Mapping[str, str]) -> forge_markers.Marker | None:
    """The winning live marker of `kind` matching `match`, or None."""
    contested = forge_markers.contest(markers, kind, match)
    return contested[0] if contested else None
