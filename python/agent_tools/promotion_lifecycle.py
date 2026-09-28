"""The promotion candidate lifecycle: the ordered classification and the gates (#127).

`advance` moves one candidate along the closed transition table (D7) and
returns a new document; it never prints, parses argv or writes a file (D2).
Every edge is keyed to one gate family, the families' gates run in the fixed
order of D29 and the first failure is the only refusal. Classification is
computed once, on the bind edge, by walking `CLASSIFICATION_RULES` (D6). A
cited bundle is re-read and re-verified through `agent_gate_bundle` at every
gate that relies on it, and its recorded state is never trusted (D8).
Deployment (`authorized -> promoted`) is verified in this repository only and
the module deletes, moves and rewrites nothing on disk (D9).
Candidates are not a `transaction_core` consumer (D22).
"""

import copy
import dataclasses
import hashlib
import os
from pathlib import Path

from agent_tools.agent_gate_bundle import (GATE_CONTRACT, GATE_VERSION,
                                           BundleIntegrityError, verify_bundle)
from agent_tools.promotion_schema import (CLASSIFICATION_RULES, PROJECT_ONLY_RESIDUE,
                                          Refusal, is_safe_relative_path, load_strict,
                                          symlinked_component, violation)

TRANSITIONS: dict[tuple[str, str], str] = {
    ("captured", "evaluating"): "bind",
    ("captured", "withdrawn"): "rationale",
    ("evaluating", "decision_ready"): "measure",
    ("evaluating", "rejected"): "rationale",
    ("evaluating", "withdrawn"): "rationale",
    ("decision_ready", "authorized"): "authorize",
    ("decision_ready", "evaluating"): "remeasure",
    ("decision_ready", "rejected"): "rationale",
    ("decision_ready", "withdrawn"): "rationale",
    ("authorized", "rejected"): "rationale",
    ("authorized", "promoted"): "promote",
    ("promoted", "superseded"): "supersede",
}
ARGUMENT_TARGETS = {"tracker_ref": ("evaluating",), "bundle": ("decision_ready",),
                    "authorized_by": ("authorized",), "rationale": ("rejected", "withdrawn"),
                    "superseded_by": ("superseded",)}
DUPLICATE_OF_PLATFORM = 1
NATIVE_EXTENSION_RULE = 6
ADMITTED = "admitted"
APPROVED = "approved"
# A re-verified state other than approved refuses; anything unlisted reads as unmeasured.
UNAPPROVED_CODES = {"unmeasured": "evidence_unmeasured", "rejected": "evidence_rejected"}


@dataclasses.dataclass(frozen=True)
class Arguments:
    tracker_ref: int | None = None
    bundle: str | None = None
    authorized_by: str | None = None
    rationale: str | None = None
    superseded_by: str | None = None


def _refuse(code: str, pointer: str, message: str) -> Refusal:
    return Refusal(code, [violation(pointer, message)])


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def anchor_line_present(root: Path, relative: str, anchor: str) -> bool:
    """Whether `root/relative` is a readable regular UTF-8 file with no symlinked
    component and a line equal to `anchor` once trailing whitespace is stripped.

    A whole-line match, never a substring (D23). Any `OSError` is `False`.
    """
    try:
        if not is_safe_relative_path(relative) or symlinked_component(root, relative):
            return False
        path = Path(root) / relative
        if not path.is_file() or path.is_symlink():
            return False
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        return False
    return any(line.rstrip() == anchor for line in text.splitlines())


def classify(candidate: dict, root: Path) -> dict:
    """The first rule of `CLASSIFICATION_RULES` the candidate matches (D6).

    Rule 1 reads the destination file; rules 2-7 compare the declared layer.
    Running off the end is an engine defect and raises `RuntimeError`.
    """
    destination = candidate["destination"]
    for rule, rule_id in CLASSIFICATION_RULES:
        if rule == DUPLICATE_OF_PLATFORM:
            matched = anchor_line_present(root, destination["path"], destination["anchor"])
        else:
            matched = destination["layer"] == rule_id
        if matched:
            return {"rule": rule, "rule_id": rule_id,
                    "declared_layer": destination["layer"],
                    "overridden_by_rule_1": rule == DUPLICATE_OF_PLATFORM}
    raise RuntimeError(f"no classification rule matched layer {destination['layer']!r}")


def corroboration_satisfied(candidate: dict) -> bool:
    """Two citations from distinct repositories with a path and an anchor, or a
    platform-governance proof."""
    corroboration = candidate["corroboration"]
    if corroboration["platform_governance"]:
        return True
    repositories = {item["repository"] for item in corroboration["repositories"]
                    if item["path"] and item["anchor"]}
    return len(repositories) >= 2


def resolve_bundle(root: Path, relative: str | None) -> tuple[str, str]:
    """`(bundle_id, state)` of the verified bundle at `root/relative`.

    The path resolves against `root`, never the working directory. Any path,
    read, parse or integrity failure refuses `evidence_unresolvable`.
    """
    pointer = "/evidence/bundle_path"
    if relative is None:
        raise _refuse("evidence_unresolvable", pointer, "no --bundle was given")
    unsafe = _refuse("evidence_unresolvable", pointer,
                     "must be a safe path under project.root with no symlinked component")
    if not is_safe_relative_path(relative):
        raise unsafe
    path = Path(root) / relative
    try:
        if symlinked_component(root, relative):
            raise unsafe
        if not path.is_file() or path.is_symlink():
            raise _refuse("evidence_unresolvable", pointer, "is not a regular file")
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        raise _refuse("evidence_unresolvable", pointer, "the bundle cannot be read")
    try:
        document = load_strict(text)
    except ValueError:
        raise _refuse("evidence_unresolvable", pointer, "the bundle is not strict JSON")
    try:
        state = verify_bundle(document)
    except BundleIntegrityError:
        raise _refuse("evidence_unresolvable", pointer, "the bundle does not verify")
    return document["bundle_id"], state


def authorization_gates(candidate: dict, root: Path) -> None:
    """The `authorized` gates in D29 order (amended by D33), minus the authorizer.

    Corroboration, a recorded classification, the recorded bundle re-verified
    under the same `bundle_id`, its re-verified state `approved`, and for rule 6
    an admitted native admission.
    """
    if not corroboration_satisfied(candidate):
        raise _refuse("corroboration_insufficient", "/corroboration",
                      "needs two distinct repositories or a platform_governance proof")
    classification = candidate["classification"]
    if classification is None:
        raise _refuse("transition_not_permitted", "/classification",
                      "a candidate with no classification cannot be authorized")
    evidence = candidate["evidence"]
    if evidence is None:
        raise _refuse("evidence_unresolvable", "/evidence", "no bundle is recorded")
    bundle_id, state = resolve_bundle(root, evidence["bundle_path"])
    if bundle_id != evidence["bundle_id"]:
        raise _refuse("evidence_unresolvable", "/evidence/bundle_id",
                      "the bundle at bundle_path is not the recorded bundle")
    if state != APPROVED:
        raise _refuse(UNAPPROVED_CODES.get(state, "evidence_unmeasured"), "/evidence/state",
                      f"the re-verified bundle is {state}, not {APPROVED}")
    admission = candidate["native_admission"]
    if classification["rule"] == NATIVE_EXTENSION_RULE and (
            admission is None or admission["decision"] != ADMITTED):
        raise _refuse("native_admission_pending", "/native_admission/decision",
                      f"a native extension must be {ADMITTED} by #64's gate")


def _reconcile(index: int, message: str) -> Refusal:
    return _refuse("promotion_reconciliation_required",
                   f"/local_duplicates/{index}/path", message)


def _require_absent(root: Path, index: int, entry: dict) -> None:
    """Return when `entry`'s path is absent in `root`; otherwise refuse.

    Absent means no symlinked component and nothing at the path. A regular file
    whose bytes match a non-null `sha256` is `duplicate_present`; anything else
    (other bytes, a null digest, a directory, a symlink, an unreadable file)
    needs reconciliation.
    """
    relative = entry["path"]
    if not is_safe_relative_path(relative):
        raise _reconcile(index, "is not a safe path under project.root")
    path = Path(root) / relative
    try:
        if symlinked_component(root, relative) is not None:
            raise _reconcile(index, "has a symlinked component")
        if not os.path.lexists(path):
            return
        if not path.is_file() or path.is_symlink():
            raise _reconcile(index, "is present but is not a regular file")
        if entry["sha256"] is None:
            raise _reconcile(index, "is present and its recorded sha256 is null")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise _reconcile(index, "cannot be inspected")
    if digest == entry["sha256"]:
        raise _refuse("duplicate_present", f"/local_duplicates/{index}/path",
                      "the declared duplicate is still on disk, unchanged")
    raise _reconcile(index, "is present with bytes other than the recorded sha256")


def verify_deployment(candidate: dict, root: Path, here: str) -> dict:
    """The `deployment` section for `candidate` in repository `here`, or a Refusal.

    Walks `local_duplicates` in order (D9): `project_only_residue` is retained,
    a foreign repository is deferred (first occurrence only), a local path must
    be absent. The first refusal wins. Nothing on disk is changed.
    """
    removed, retained, deferred = [], [], []
    for index, entry in enumerate(candidate["local_duplicates"]):
        if entry["disposition"] == PROJECT_ONLY_RESIDUE:
            retained.append(entry["path"])
        elif entry["repository"] != here:
            if entry["repository"] not in deferred:
                deferred.append(entry["repository"])
        else:
            _require_absent(root, index, entry)
            removed.append(entry["path"])
    return {"verified_repository": here, "removed": removed, "retained": retained,
            "deferred_repositories": deferred}


def _bind(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    if arguments.tracker_ref is None:
        raise _refuse("tracker_ref_required", "/tracker/ref",
                      "binding to evaluating needs --tracker-ref")
    result["tracker"]["ref"] = arguments.tracker_ref
    result["classification"] = classify(result, root)


def _rationale(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    if _blank(arguments.rationale):
        raise _refuse("rationale_required", "/history", "this edge needs --rationale")


def _measure(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    if not corroboration_satisfied(result):
        raise _refuse("corroboration_insufficient", "/corroboration",
                      "needs two distinct repositories or a platform_governance proof")
    bundle_id, state = resolve_bundle(root, arguments.bundle)
    result["evidence"] = {"bundle_path": arguments.bundle, "bundle_id": bundle_id,
                          "state": state, "gate_contract": GATE_CONTRACT,
                          "gate_version": GATE_VERSION}


def _authorize(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    authorization_gates(result, root)
    if _blank(arguments.authorized_by):
        raise _refuse("authorizer_required", "/history", "authorizing needs --authorized-by")


def _remeasure(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    result["evidence"] = None


def _promote(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    authorization_gates(result, root)
    destination = result["destination"]
    if not anchor_line_present(root, destination["path"], destination["anchor"]):
        raise _refuse("destination_missing", "/destination/path",
                      "the destination has no line equal to the anchor")
    result["deployment"] = verify_deployment(result, root, here)


def _supersede(result: dict, root: Path, here: str, arguments: Arguments) -> None:
    """Shape is checked by the CLI's argparse type (D32); nothing else changes."""


GATES = {"bind": _bind, "rationale": _rationale, "measure": _measure,
         "authorize": _authorize, "remeasure": _remeasure, "promote": _promote,
         "supersede": _supersede}
RATIONALES = {"rationale": lambda arguments: arguments.rationale,
              "supersede": lambda arguments: f"superseded by {arguments.superseded_by}"}


def advance(candidate: dict, target: str, root: Path, here: str, arguments: Arguments) -> dict:
    """A deep copy of `candidate` moved to `target` with one history entry appended.

    `candidate` is never mutated. Every refusal carries the candidate's current
    `candidate_id` and `state`.
    """
    current = candidate["state"]
    try:
        family = TRANSITIONS.get((current, target))
        if family is None:
            raise _refuse("transition_not_permitted", "/state",
                          f"{current} has no edge to {target}")
        result = copy.deepcopy(candidate)
        GATES[family](result, Path(root), here, arguments)
    except Refusal as refusal:
        refusal.candidate_id = candidate["candidate_id"]
        refusal.state = current
        raise
    result["state"] = target
    result["history"].append({
        "from": current, "to": target,
        "actor": arguments.authorized_by if family == "authorize" else None,
        "rationale": RATIONALES.get(family, lambda arguments: None)(arguments)})
    return result
