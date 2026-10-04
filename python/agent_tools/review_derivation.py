"""Deterministic derivation of the retained review bundle into a fresh directory (issue 249; RP4, RP5, RP6, RP9, RP16).

`derive_bundle` reads three repositories and the issue-100 archive and writes
the five bundle files `review_witness` defines. It refuses a bad input or
output before it reads a Git object, requires the running `agent_tools` package
to be the tool commit's, derives the three fixture payloads with SOURCE's
derivers, builds the witness and the anchor over them, and runs
`validate_bundle`, the validation replay runs, before it publishes.

Every output byte is `canonical_bytes` of a value the pins, the repositories,
the archive and the budget authority determine: no path, clock, hostname,
locale or environment value is written, so two derivations are byte-identical.
The inputs are only read. Derivation takes no snapshot of them (RP6).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import PACKING_POLICY_SHA256, RECORD_POLICY_SHA256, GenerationError, _run_git
from agent_tools.review_budget import BudgetAuthority
from agent_tools.review_forecast import canonical_bytes, raw_digest
from agent_tools.review_issue100 import Issue100Pins, derive_100, verify_archive
from agent_tools.review_issue121 import Issue121Pins, derive_121
from agent_tools.review_task7 import Task7Pins, derive_task7
from agent_tools.review_witness import (ANCHOR_MAX_BYTES, ANCHOR_NAME, MEMBER_MAX_BYTES, PAYLOAD_NAMES, build_anchor,
                                        build_witness, tool_closure, validate_bundle, verify_running_closure)

_CODES = ("invalid_inputs", "output_exists", "output_aliases_input", "member_oversize")
_WITNESS, _ISSUE_100, _ISSUE_121, _ESTIMATE = PAYLOAD_NAMES


class DerivationError(Exception):
    """Derivation refuses its inputs, its output or a member's size; `code` names why."""

    def __init__(self, code: str):
        if code not in _CODES:
            raise ValueError(f"unknown derivation code {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DeriveInputs:
    issue_121_repo: Path
    issue_100_repo: Path
    archive_dir: Path
    tool_repo: Path
    tool_commit: str
    output_dir: Path


def _require(condition: object, code: str) -> None:
    if not condition:
        raise DerivationError(code)


def _refuse_inputs(inputs: DeriveInputs) -> None:
    """Refuse a bad input (`invalid_inputs`), then a bad output (`output_exists`, `output_aliases_input`).

    The tool commit is 40 lowercase hex, each of the four input paths is a directory and each of the three
    repositories names its common Git directory. The output does not exist, a dangling symlink counting as
    existing, and its parent is a directory. Its resolved parent joined with its name does not equal, lie
    inside or contain any input path or any of those common Git directories. Only `git rev-parse
    --git-common-dir` runs, so no Git object is read.
    """
    repos = (inputs.issue_121_repo, inputs.issue_100_repo, inputs.tool_repo)
    paths = (*repos, inputs.archive_dir)
    _require(re.fullmatch(r"[0-9a-f]{40}", inputs.tool_commit) and all(path.is_dir() for path in paths),
             "invalid_inputs")
    protected = [path.resolve() for path in paths]
    for repo in repos:
        try:
            common = _run_git(repo, "rev-parse", "--git-common-dir")
        except GenerationError as exc:
            raise DerivationError("invalid_inputs") from exc
        # Git prints the directory relative to the repository path unless it is absolute already.
        protected.append(Path(repo, common.rstrip("\n")).resolve())
    output = inputs.output_dir
    _require(not os.path.lexists(output) and output.parent.is_dir(), "output_exists")
    target = output.parent.resolve() / output.name
    _require(not any(target == path or path in target.parents or target in path.parents for path in protected),
             "output_aliases_input")


def _encoded(value: object, limit: int) -> bytes:
    """The canonical bytes of one bundle member; above `limit` bytes is `member_oversize`."""
    raw = canonical_bytes(value)
    _require(len(raw) <= limit, "member_oversize")
    return raw


def derive_bundle(inputs: DeriveInputs, *, task7_pins: Task7Pins, issue121_pins: Issue121Pins,
                  issue100_pins: Issue100Pins, authority: BudgetAuthority) -> dict:
    """Derive the bundle into `inputs.output_dir` and return `{anchor_sha256, members}`.

    `members` lists all five files in path order as `{path, bytes, raw_sha256}`, the digest bare 64-hex, and
    `anchor_sha256` is `telemetry_digest` of the anchor. In order:

    1. the inputs and the output are refused as `_refuse_inputs` describes;
    2. the tool commit's closure must be the running package (`WitnessError`, `tool_closure`);
    3. `derive_task7` runs on the issue-121 repository, so a table that cannot be derived is an
       `EstimateError` and no bundle (RP5); `derive_121` follows, then `derive_100` with the issue-100
       repository as both its issue and its live repository (RP4);
    4. each payload is encoded, and one above `MEMBER_MAX_BYTES` is `member_oversize`;
    5. the witness, held to the same bound, and then the anchor, held to `ANCHOR_MAX_BYTES` under the same
       code, are built over the five component groups, each assembled once (RP16);
    6. `validate_bundle` accepts the anchor and the four raw members;
    7. the files are written into one private scratch directory beside the output, which is renamed onto
       the output. A failure from there on removes the scratch, so it leaves neither output nor scratch.

    The SOURCE derivers' and the validators' own errors pass through unchanged.
    """
    _refuse_inputs(inputs)
    closure = tool_closure(inputs.tool_repo, inputs.tool_commit)
    verify_running_closure(closure)
    table = derive_task7(inputs.issue_121_repo, task7_pins)
    payloads = {_ESTIMATE: table,
                _ISSUE_121: derive_121(inputs.issue_121_repo, issue121_pins, task7_pins, authority),
                _ISSUE_100: derive_100(inputs.issue_100_repo, inputs.issue_100_repo, inputs.archive_dir,
                                       issue100_pins, authority.limits)}
    raw = {name: _encoded(payload, MEMBER_MAX_BYTES) for name, payload in payloads.items()}
    components = {
        "tool": {**closure, "artifact_policy_sha256": authority.policy_sha256,
                 "packing_policy_sha256": PACKING_POLICY_SHA256, "record_policy_sha256": RECORD_POLICY_SHA256},
        "issue_121": {"base": issue121_pins.base, "head": issue121_pins.head, "tree": task7_pins.prerequisite_tree,
                      "signer_sha256": raw_digest(issue121_pins.allowed_signer)},
        "issue_100": {name: getattr(issue100_pins, name) for name in ("base", "head", "live", "parent_edges_sha256")},
        "archive": verify_archive(inputs.archive_dir, inputs.issue_100_repo, issue100_pins),
        "estimate": {**{name: getattr(task7_pins, name) for name in (
            "prerequisite_commit", "prerequisite_tree", "plan_root_blob", "task7_blob", "model_version")},
            "table_sha256": telemetry_digest(table)}}
    raw[_WITNESS] = _encoded(build_witness(components, payloads, raw), MEMBER_MAX_BYTES)
    anchor = build_anchor(components, raw)
    files = {**raw, ANCHOR_NAME: _encoded(anchor, ANCHOR_MAX_BYTES)}
    validate_bundle(anchor, raw, task7_pins=task7_pins, issue121_pins=issue121_pins, issue100_pins=issue100_pins)
    scratch = Path(tempfile.mkdtemp(dir=inputs.output_dir.parent, prefix=".derive-"))
    try:
        for name, data in files.items():
            (scratch / name).write_bytes(data)
        os.rename(scratch, inputs.output_dir)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
    return {"anchor_sha256": telemetry_digest(anchor),
            "members": [{"path": name, "bytes": len(files[name]), "raw_sha256": hashlib.sha256(files[name]).hexdigest()}
                        for name in sorted(files)]}
