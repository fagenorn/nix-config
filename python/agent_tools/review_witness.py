"""The retained bundle contract: tool closure, witness, anchor and bundle validation (issue 249; RP2, RP3, RP16).

A bundle is five canonical JSON files. Three are the fixture payloads (the
issue-100 payload, the issue-121 payload and the Task-7 estimate table), the
witness digests them, and the anchor hashes all four. Five provenance groups,
the components, appear identically in the witness and in the anchor.

The issue-100 and issue-121 files are the compact payloads, schema versions 2
and 4. The model of each, SOURCE's object, is what `expand_100` or `expand_121`
yields: the witness digests the models' tables, and `validate_bundle` returns
the models (issue 254).

Construction is acyclic: the witness reads the components and the fixtures, the
anchor reads the components and the four payloads, and no payload names the
anchor. The anchor's identity is `telemetry_digest(anchor)`, which the caller
supplies; nothing in a bundle is trusted before `authenticate` binds it to that
digest.

`validate_bundle` is the one full semantic validation. Derivation runs it
before it publishes and replay runs it before it classifies (RP2). It runs no
Git, so it checks what the pins and the tables determine (RP7): `tool.commit`,
`tool.files` and `archive.shards` are checked for their closed shape only, and
are authentic only under the caller's anchor digest or by derivation again.
"""
from __future__ import annotations

import hashlib
import importlib.resources
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import PACKING_POLICY_SHA256, RECORD_POLICY_SHA256, GenerationError, _run_git
from agent_tools.review_forecast import (ForecastError, canonical_bytes, full_commit, raw_digest, read_regular,
                                         strict_json)
from agent_tools.review_issue100 import expand_100, validate_100
from agent_tools.review_issue121 import expand_121, validate_121
from agent_tools.review_task7 import validate_task7

ANCHOR_NAME = "derivation-anchor.json"
# The four files the anchor hashes, in the order CORE's `retained-anchor/v2` loader requires.
PAYLOAD_NAMES = ("derivation-witness.json", "issue-100-derived.json", "issue-121.json", "task7-estimate.json")
ANCHOR_MAX_BYTES = 32768
MEMBER_MAX_BYTES = 1048576

_CODES = ("tool_closure", "anchor_unreadable", "anchor_shape", "anchor_digest", "expected_digest", "member_set",
          "member_digest", "member_noncanonical", "witness_shape", "component_mismatch", "table_mismatch",
          "policy_mismatch")
_WITNESS, _ISSUE_100, _ISSUE_121, _ESTIMATE = PAYLOAD_NAMES
_FIXTURES = PAYLOAD_NAMES[1:]
_GROUPS = ("tool", "issue_121", "issue_100", "archive", "estimate")
_ANCHOR_KIND = "review-feasibility-derivation-anchor"
_WITNESS_KIND = "review-feasibility-derivation-witness"
_ENCODING = "canonical-json-ascii-lf/v1"
_PACKAGE = "python/agent_tools/"
_MEMBER = ("path", "bytes", "raw_sha256")
# Every table the witness digests, by fixture in path order, read from the two retained models and the
# estimate table. A dotted name is that member's `records` list.
# A `records` list is a raw-record table, and its `record_table_policy` sits beside it.
_TABLES = ((_ISSUE_100, ("parent_edges", "edges", "contributions", "pending_overlaps", "criteria",
                         "tables.historical", "tables.fresh")),
           (_ISSUE_121, ("classes", "edges", "anchors", "records")),
           (_ESTIMATE, ("rows",)))
_ESTIMATE_PINS = ("prerequisite_commit", "prerequisite_tree", "plan_root_blob", "task7_blob", "model_version")


class WitnessError(Exception):
    """A bundle, or the tool closure behind it, is refused; `code` names why."""

    def __init__(self, code: str):
        if code not in _CODES:
            raise ValueError(f"unknown witness code {code!r}")
        self.code = code
        super().__init__(code)


def _require(condition: object, code: str) -> None:
    if not condition:
        raise WitnessError(code)


def _hex(value: object, size: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % size, value) is not None


def _digest(value: object) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and _hex(value[len("sha256:"):], 64)


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


def _closed(value: object, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _rows(value: object, keys: tuple[str, ...]) -> bool:
    return isinstance(value, list) and all(_closed(row, keys) for row in value)


def _same(left: object, right: object) -> bool:
    """Canonical equality, so `True` never stands in for `1`."""
    return canonical_bytes(left) == canonical_bytes(right)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _members(raw: Mapping[str, bytes], names: tuple[str, ...]) -> list[dict]:
    return [{"path": name, "bytes": len(raw[name]), "raw_sha256": _sha(raw[name])} for name in names]


def tool_closure(tool_repo: Path, tool_commit: str) -> dict:
    """`{commit, files}`: every blob under `python/agent_tools/` at the full, original-history-authenticated
    `tool_commit`, as `{path, blob, raw_sha256}` rows sorted by `path`.

    `path` is relative to the package directory, which is read from the commit's root tree wherever in the
    worktree `tool_repo` points. An unauthenticated commit, an entry that is not a regular blob, a name that
    is not UTF-8, a failed Git read and a commit without the package are `tool_closure`.
    """
    files = []
    try:
        full_commit(tool_repo, tool_commit)
        listing = _run_git(tool_repo, "ls-tree", "-r", "-z", "--full-tree", tool_commit, "--", _PACKAGE, binary=True)
        for entry in listing.split(b"\0")[:-1]:
            metadata, path = entry.split(b"\t", 1)
            mode, _, blob = metadata.decode("ascii").split()
            _require(mode in ("100644", "100755"), "tool_closure")
            files.append({"path": path.decode("utf-8")[len(_PACKAGE):], "blob": blob,
                          "raw_sha256": _sha(_run_git(tool_repo, "cat-file", "blob", blob, binary=True))})
    except (ForecastError, GenerationError, UnicodeDecodeError) as exc:
        raise WitnessError("tool_closure") from exc
    _require(files, "tool_closure")
    return {"commit": tool_commit, "files": sorted(files, key=lambda row: row["path"])}


def verify_running_closure(closure: dict) -> None:
    """Refuse, as `tool_closure`, unless the running `agent_tools` package is exactly the closure's files.

    The package is read as the import system's own resource tree, so no module is loaded by path. Only
    `__pycache__` directories are skipped: an extra, missing or differing file refuses, which covers a dirty
    source tree and a stale build alike.
    """
    running, pending = {}, [("", importlib.resources.files("agent_tools"))]
    while pending:
        prefix, directory = pending.pop()
        for entry in directory.iterdir():
            if not entry.is_dir():
                running[prefix + entry.name] = _sha(entry.read_bytes())
            elif entry.name != "__pycache__":
                pending.append((f"{prefix}{entry.name}/", entry))
    _require(running == {row["path"]: row["raw_sha256"] for row in closure["files"]}, "tool_closure")


def _tables(models: Mapping[str, object]) -> tuple[list[dict], dict]:
    """The witness's `tables` and `table_policies`, read from `models` (see `build_witness`); a fixture
    without one of its tables is `table_mismatch`."""
    tables, policies = [], {}
    for fixture, names in _TABLES:
        for name in names:
            holder, key = models[fixture], name
            if "." in name:
                outer, inner = name.split(".")
                holder, key = holder.get(outer) if isinstance(holder, dict) else None, "records"
                holder = holder.get(inner) if isinstance(holder, dict) else None
            rows = holder.get(key) if isinstance(holder, dict) else None
            _require(isinstance(rows, list), "table_mismatch")
            tables.append({"fixture": fixture, "table": name, "rows": len(rows), "sha256": telemetry_digest(rows)})
            if key == "records":
                policies[f"{fixture}#{name}"] = holder.get("record_table_policy")
    return tables, policies


def build_witness(components: dict, models: Mapping[str, dict], raw: Mapping[str, bytes]) -> dict:
    """The version-2 witness over the components and the three fixtures. `models` holds what the tables
    digest, by fixture name: the two retained models and the estimate table. `raw` holds the bundle files'
    bytes. The witness holds no anchor identity and no digest of itself."""
    tables, policies = _tables(models)
    return {"schema_version": 2, "kind": _WITNESS_KIND, "components": {group: components[group] for group in _GROUPS},
            "fixtures": _members(raw, _FIXTURES), "tables": tables, "table_policies": policies}


def build_anchor(components: dict, raw: Mapping[str, bytes]) -> dict:
    """The `retained-anchor/v2` anchor over the components and the four payloads' raw bytes."""
    return {"schema_version": 2, "kind": _ANCHOR_KIND, **{group: components[group] for group in _GROUPS},
            "payload": {"encoding": _ENCODING, "members": _members(raw, PAYLOAD_NAMES)}}


def _anchor(raw: bytes) -> dict:
    """The decoded anchor; `anchor_shape` unless it is the closed, canonical version-2 envelope. Bytes
    nested too deeply to decode are `anchor_shape` too."""
    try:
        anchor = strict_json(raw)
    except (ForecastError, RecursionError) as exc:
        raise WitnessError("anchor_shape") from exc
    _require(_closed(anchor, ("schema_version", "kind", *_GROUPS, "payload"))
             and type(anchor["schema_version"]) is int and anchor["schema_version"] == 2
             and anchor["kind"] == _ANCHOR_KIND and canonical_bytes(anchor) == raw
             and all(isinstance(anchor[group], dict) for group in _GROUPS)
             and _closed(anchor["payload"], ("encoding", "members")), "anchor_shape")
    payload = anchor["payload"]
    _require(payload["encoding"] == _ENCODING and _rows(payload["members"], _MEMBER)
             and [member["path"] for member in payload["members"]] == list(PAYLOAD_NAMES)
             and all(_count(member["bytes"]) and _hex(member["raw_sha256"], 64) for member in payload["members"]),
             "anchor_shape")
    return anchor


def authenticate(bundle_dir: Path, expected_anchor_sha256: str) -> tuple[dict, dict[str, bytes]]:
    """The anchor under the caller's digest and the four payloads' raw bytes under the anchor.

    The anchor is read below `ANCHOR_MAX_BYTES`, strictly decoded, required to be the closed canonical
    envelope and compared with `expected_anchor_sha256`. A failed read is `anchor_unreadable`: a missing or
    symlinked directory or anchor, or an anchor that is oversized or not a regular file. The directory then
    holds exactly the five names, each a regular file and not a symlink, and each payload is read up to its
    declared size (at most `MEMBER_MAX_BYTES`) with its length and SHA-256 matching the anchor. No payload is
    decoded here.
    """
    _require(_digest(expected_anchor_sha256), "expected_digest")
    bundle_dir = Path(bundle_dir)
    try:
        data = read_regular(bundle_dir, ANCHOR_NAME, ANCHOR_MAX_BYTES)
    except (ForecastError, OSError) as exc:
        raise WitnessError("anchor_unreadable") from exc
    anchor = _anchor(data)
    _require(telemetry_digest(anchor) == expected_anchor_sha256, "anchor_digest")
    names = {ANCHOR_NAME, *PAYLOAD_NAMES}
    _require(set(os.listdir(bundle_dir)) == names
             and all(stat.S_ISREG(os.lstat(bundle_dir / name).st_mode) for name in names), "member_set")
    raw = {}
    for member in anchor["payload"]["members"]:
        _require(member["bytes"] <= MEMBER_MAX_BYTES, "member_digest")
        try:
            data = read_regular(bundle_dir, member["path"], member["bytes"])
        except ForecastError as exc:
            raise WitnessError("member_digest") from exc
        _require(len(data) == member["bytes"] and _sha(data) == member["raw_sha256"], "member_digest")
        raw[member["path"]] = data
    return anchor, raw


def _components(components: dict, table: object, task7_pins, issue121_pins, issue100_pins) -> None:
    """The five groups against the pins and CORE's policy constants: `component_mismatch`."""
    pinned = {
        "issue_121": {"base": issue121_pins.base, "head": issue121_pins.head, "tree": task7_pins.prerequisite_tree,
                      "signer_sha256": raw_digest(issue121_pins.allowed_signer)},
        "issue_100": {name: getattr(issue100_pins, name) for name in ("base", "head", "live", "parent_edges_sha256")},
        "estimate": {**{name: getattr(task7_pins, name) for name in _ESTIMATE_PINS},
                     "table_sha256": telemetry_digest(table)}}
    tool, archive = components["tool"], components["archive"]
    _require(all(_same(components[group], members) for group, members in pinned.items())
             and _closed(tool, ("commit", "files", "artifact_policy_sha256", "packing_policy_sha256",
                                "record_policy_sha256"))
             and _hex(tool["commit"], 40) and _digest(tool["artifact_policy_sha256"])
             and tool["packing_policy_sha256"] == PACKING_POLICY_SHA256
             and tool["record_policy_sha256"] == RECORD_POLICY_SHA256
             and _closed(archive, ("producer_sha256", "manifest_sha256", "shards"))
             and archive["producer_sha256"] == issue100_pins.producer_sha256
             and archive["manifest_sha256"] == issue100_pins.manifest_sha256, "component_mismatch")
    files, shards = tool["files"], archive["shards"]
    _require(_rows(files, ("path", "blob", "raw_sha256")) and files
             and all(isinstance(row["path"], str) and _hex(row["blob"], 40) and _hex(row["raw_sha256"], 64)
                     for row in files)
             and all(before["path"] < after["path"] for before, after in zip(files, files[1:]))
             and _rows(shards, ("path", "bytes", "sha256"))
             and all(isinstance(row["path"], str) and _count(row["bytes"]) and _hex(row["sha256"], 64)
                     for row in shards), "component_mismatch")


def validate_bundle(anchor: dict, raw: Mapping[str, bytes], *, task7_pins, issue121_pins,
                    issue100_pins) -> dict[str, dict]:
    """The four members by name, the two retained ones as their models, after the one full semantic
    validation of a bundle.

    `anchor` is an authenticated or freshly built anchor and `raw` its four payloads' bytes. In order:
    each payload strictly decodes to its own canonical bytes (`member_noncanonical`); the witness is the
    closed version-2 object whose fixtures are the anchor's (`witness_shape`), whose components are the
    anchor's (`component_mismatch`) and whose table rows, digests and policies are those of the two retained
    payloads' expansions and the estimate table (`table_mismatch`, or an expansion's own refusal, which
    passes through); the components match the pins and policy constants (`component_mismatch`); the
    three SOURCE validators accept the fixtures, their own errors passing through unchanged; every
    measured issue-121 outcome carries the tool group's artifact policy (`policy_mismatch`); and the
    outcomes the pinned head determines carry the pinned tree (`component_mismatch`, RP16): a measured
    aggregate's and a measured `tasks-7-8`'s `result_tree`, and the `tasks-7-8` prerequisite's `tree`.
    """
    payloads = {}
    for name in PAYLOAD_NAMES:
        try:
            payloads[name] = strict_json(raw[name])
        except ForecastError as exc:
            raise WitnessError("member_noncanonical") from exc
        _require(canonical_bytes(payloads[name]) == raw[name], "member_noncanonical")
    witness, components = payloads[_WITNESS], {group: anchor[group] for group in _GROUPS}
    _require(_closed(witness, ("schema_version", "kind", "components", "fixtures", "tables", "table_policies"))
             and type(witness["schema_version"]) is int and witness["schema_version"] == 2
             and witness["kind"] == _WITNESS_KIND, "witness_shape")
    _require(_same(witness["components"], components), "component_mismatch")
    _require(_same(witness["fixtures"], [m for m in anchor["payload"]["members"] if m["path"] != _WITNESS]),
             "witness_shape")
    models = {**payloads, _ISSUE_100: expand_100(payloads[_ISSUE_100]),
              _ISSUE_121: expand_121(payloads[_ISSUE_121])}
    _require(_same([witness["tables"], witness["table_policies"]], list(_tables(models))), "table_mismatch")
    table = payloads[_ESTIMATE]
    _components(components, table, task7_pins, issue121_pins, issue100_pins)
    validate_task7(table, task7_pins)
    issue121 = models[_ISSUE_121] = validate_121(payloads[_ISSUE_121], issue121_pins, table)
    models[_ISSUE_100] = validate_100(payloads[_ISSUE_100], issue100_pins)
    outcomes = [issue121["aggregate"]["actual"], issue121["aggregate"]["projected"], *issue121["boundaries"]]
    _require(all(row["measurement"]["artifact_policy_sha256"] == components["tool"]["artifact_policy_sha256"]
                 for row in outcomes if row["state"] == "measured"), "policy_mismatch")
    tree, (actual, projected, _, _, future) = components["issue_121"]["tree"], outcomes
    _require(future["prerequisite"]["tree"] == tree
             and all(row["result_tree"] == tree for row in (actual, projected, future) if row["state"] == "measured"),
             "component_mismatch")
    return models
