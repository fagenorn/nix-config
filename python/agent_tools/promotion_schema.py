"""The promotion documents' vocabularies, refusal shape and shape-only validator.

Three documents are tracked: the authored `promotion-candidate-draft`, the
`promotion-candidate` that carries the authored section verbatim plus a
lifecycle section, and the `promotion-evaluation` record (#127). This module
holds every closed vocabulary those documents name, the `Refusal` the command
reports, the strict loader, the path-safety predicate and the symlinked-component
walk (D15), and `validate_document`.

The validator judges shape only (D13): it closes every object's member set,
types every member, refuses a member named for a clock reading at any depth,
and never recomputes an id or ties the presence of `classification`, `evidence`
or `deployment` to `state`.
"""

import json
import re
from pathlib import Path, PurePosixPath

from agent_tools.agent_gate_bundle import GATE_CONTRACT, GATE_VERSION
from agent_tools.canonical import (reject_duplicate_keys, reject_nonfinite_literal,
                                   telemetry_digest)

COMMAND_NAME = "promotion"
SCHEMA_VERSION = 1
DRAFT_KIND, CANDIDATE_KIND, EVALUATION_KIND = ("promotion-candidate-draft",
    "promotion-candidate", "promotion-evaluation")
KINDS = (DRAFT_KIND, CANDIDATE_KIND, EVALUATION_KIND)
STATES = ("captured", "evaluating", "decision_ready", "authorized", "promoted",
          "rejected", "withdrawn", "superseded")
TERMINAL_STATES = ("rejected", "withdrawn", "superseded")
PROMOTED = "promoted"
LAYERS = ("project_local", "core_module", "standard_layer", "native_adapter",
          "native_extension", "out_of_scope_product")
AGENT_IDS = ("claude", "codex")
REMOVE_DISPOSITION = "remove"
PROJECT_ONLY_RESIDUE = "project_only_residue"
DISPOSITIONS = (REMOVE_DISPOSITION, PROJECT_ONLY_RESIDUE)
ADMISSION_GATE = "issue-64"
ADMISSION_DECISIONS = ("pending", "admitted", "refused")
BUNDLE_STATES = ("approved", "rejected", "unmeasured")
EVALUATION_OUTCOMES = ("empty", "found")
TRACKER_LABEL = "promotion-candidate"
KNOWLEDGE_RELATIVE = (".agents", "knowledge", "promotions")
DRAFTS_RELATIVE = KNOWLEDGE_RELATIVE + ("drafts",)
CANDIDATES_RELATIVE = KNOWLEDGE_RELATIVE + ("candidates",)
EVALUATIONS_RELATIVE = KNOWLEDGE_RELATIVE + ("evaluations",)
AUTHORED_MEMBERS = ("lesson", "destination", "corroboration", "local_duplicates",
                    "native_admission")
LOCAL_DUPLICATES_MEMBER = "local_duplicates"
DUPLICATE_MEMBERS = ("repository", "path", "sha256", "disposition")
DRAFT_MEMBERS = ("schema_version", "kind") + AUTHORED_MEMBERS
CANDIDATE_MEMBERS = (("schema_version", "kind", "candidate_id", "state")
                     + AUTHORED_MEMBERS
                     + ("classification", "evidence", "deployment", "tracker", "history"))
EVALUATION_MEMBERS = ("schema_version", "kind", "evaluation_id", "scope", "commands",
                      "candidates", "outcome")
FORBIDDEN_MEMBER_NAMES = ("created_at", "generated_at", "time", "timestamp")
CLASSIFICATION_RULES = ((1, "duplicate_of_platform"),) + tuple(
    (number, layer) for number, layer in enumerate(LAYERS, start=2))
GATE_CODES = ("transition_not_permitted", "tracker_ref_required", "rationale_required",
              "authorizer_required", "corroboration_insufficient", "evidence_unresolvable",
              "evidence_unmeasured", "evidence_rejected", "native_admission_pending",
              "destination_missing", "duplicate_present", "promotion_reconciliation_required")
TOOL_CODES = ("unreadable_input", "invalid_document", "output_exists",
              "output_outside_root", "contract_unresolvable", "internal_failure")
TITLE_MAX, TEXT_MAX, ANCHOR_MAX = 120, 1000, 200
CITATIONS_MAX, DUPLICATES_MAX, COMMANDS_MAX = 8, 16, 16
INTERNAL_FAILURE_MESSAGE = "the promotion module failed unexpectedly"

LESSON_MEMBERS = ("title", "statement", "source")
CITATION_MEMBERS = ("repository", "path", "revision", "anchor")
DESTINATION_MEMBERS = ("layer", "owner", "name", "path", "anchor")
CORROBORATION_MEMBERS = ("repositories", "platform_governance")
ADMISSION_MEMBERS = ("gate", "decision", "irreducible_scenario")
CLASSIFICATION_MEMBERS = ("rule", "rule_id", "declared_layer", "overridden_by_rule_1")
EVIDENCE_MEMBERS = ("bundle_path", "bundle_id", "state", "gate_contract", "gate_version")
DEPLOYMENT_MEMBERS = ("verified_repository", "removed", "retained", "deferred_repositories")
TRACKER_MEMBERS = ("ref", "label", "create_command")
HISTORY_MEMBERS = ("from", "to", "actor", "rationale")
SCOPE_MEMBERS = ("repository", "revision")
MEMBERS_BY_KIND = {DRAFT_KIND: DRAFT_MEMBERS, CANDIDATE_KIND: CANDIDATE_MEMBERS,
                   EVALUATION_KIND: EVALUATION_MEMBERS}
RULE_IDS = dict(CLASSIFICATION_RULES)
NAME_SEGMENT = r"[a-z0-9][a-z0-9_-]*"
AGENT_ALTERNATION = "|".join(AGENT_IDS)
NAME_PATTERNS = {
    "native_adapter": re.compile(rf"^adapter\.({AGENT_ALTERNATION})\.{NAME_SEGMENT}$"),
    "native_extension": re.compile(rf"^native\.({AGENT_ALTERNATION})\.{NAME_SEGMENT}$"),
}
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def violation(pointer: str, message: str) -> dict:
    """The one violation shape every refusal carries."""
    return {"pointer": pointer, "message": message}


class Refusal(Exception):
    """A refusal the command reports as one `error` object (D12).

    `exit_code` is 3 for a gate code and 2 for a tool code; any other code is a
    programming error and raises `ValueError`.
    """

    def __init__(self, code: str, violations: list[dict], candidate_id=None, state=None):
        if code in GATE_CODES:
            exit_code = 3
        elif code in TOOL_CODES:
            exit_code = 2
        else:
            raise ValueError(f"unknown refusal code {code!r}")
        super().__init__(code)
        self.code = code
        self.violations = list(violations)
        self.candidate_id = candidate_id
        self.state = state
        self.exit_code = exit_code


def load_strict(text: str) -> object:
    """`json.loads` refusing duplicate keys and non-finite literals; `ValueError`."""
    return json.loads(text, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def is_safe_relative_path(value: object) -> bool:
    """A non-empty `str`, not absolute, with no `..` part (D15)."""
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def symlinked_component(root: Path, relative: str) -> Path | None:
    """The first component of `relative` under `root` that is a symlink.

    `root` itself is never tested. `None` when no component is linked, or when
    a component is absent (nothing beneath it can be linked).
    """
    current = Path(root)
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            return current
        if not current.exists():
            return None
    return None


def authored_section(document: dict) -> dict:
    """The five authored members, which are all `candidate_id` covers (D13)."""
    return {member: document[member] for member in AUTHORED_MEMBERS}


def candidate_id_of(document: dict) -> str:
    """`telemetry_digest` of the authored section."""
    return telemetry_digest(authored_section(document))


def _citation_text(citation: dict, pinned: bool) -> str:
    """`<repository> <path>[@<revision|unpinned>]#<anchor>` for the issue body."""
    revision = f"@{citation['revision'] or 'unpinned'}" if pinned else ""
    return f"{citation['repository']} {citation['path']}{revision}#{citation['anchor']}"


def create_command(repo_slug: str, document_path: str, draft: dict,
                   candidate_id: str) -> list[str]:
    """The labelled `gh issue create` argv `capture` prints as data (D1).

    The body is bounded fields and links, never the statement (#68, D30).
    """
    lesson, destination = draft["lesson"], draft["destination"]
    corroboration = draft["corroboration"]
    lines = [f"candidate: {candidate_id}",
             f"document: {document_path}",
             f"source: {_citation_text(lesson['source'], pinned=True)}",
             f"destination: {destination['layer']} {destination['owner']}/"
             f"{destination['name']} {destination['path']}#{destination['anchor']}"]
    lines += [f"corroboration: {_citation_text(item, pinned=False)}"
              for item in corroboration["repositories"]]
    if corroboration["platform_governance"] is not None:
        lines.append("platform_governance: provided")
    return ["gh", "issue", "create", "--repo", repo_slug, "--label", TRACKER_LABEL,
            "--title", "promotion: " + lesson["title"], "--body", "\n".join(lines)]


def mint_candidate(draft: dict, repo_slug: str, document_path: str) -> dict:
    """The `captured` candidate: the authored section verbatim plus a fresh lifecycle."""
    candidate_id = candidate_id_of(draft)
    return {"schema_version": SCHEMA_VERSION, "kind": CANDIDATE_KIND,
            "candidate_id": candidate_id, "state": "captured", **authored_section(draft),
            "classification": None, "evidence": None, "deployment": None,
            "tracker": {"ref": None, "label": TRACKER_LABEL,
                        "create_command": create_command(repo_slug, document_path, draft,
                                                         candidate_id)},
            "history": [{"from": None, "to": "captured", "actor": None, "rationale": None}]}


def mint_evaluation(repository: str, revision: str | None, commands: list[str],
                    candidates: list[str]) -> dict:
    """The evaluation record; `commands` are kept verbatim and never run (D19).

    `evaluation_id` digests the document without itself (D13).
    """
    body = {"schema_version": SCHEMA_VERSION, "kind": EVALUATION_KIND,
            "scope": {"repository": repository, "revision": revision},
            "commands": list(commands), "candidates": list(candidates),
            "outcome": "found" if candidates else "empty"}
    return {**body, "evaluation_id": telemetry_digest(body)}


# Each checker appends violations and reports whether the value passed, so a
# caller can stop descending into a member it already refused.


def _child(pointer: str, name) -> str:
    """`pointer` extended by one JSON-pointer reference token."""
    token = str(name).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{token}"


def _forbidden_names(value: object, pointer: str, out: list) -> None:
    if isinstance(value, dict):
        for key, member in value.items():
            child = _child(pointer, key)
            if key in FORBIDDEN_MEMBER_NAMES:
                out.append(violation(child, "no member may be named for a clock reading"))
            _forbidden_names(member, child, out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _forbidden_names(item, _child(pointer, index), out)


def _members(value: object, pointer: str, expected: tuple, out: list) -> bool:
    if not isinstance(value, dict):
        out.append(violation(pointer, "must be an object"))
        return False
    for name in expected:
        if name not in value:
            out.append(violation(_child(pointer, name), "is a required member"))
    for name in value:
        if name not in expected:
            out.append(violation(_child(pointer, name), "is not a member of this object"))
    return True


def _text(value: object, pointer: str, out: list, limit: int | None = None) -> bool:
    if isinstance(value, str) and value and (limit is None or len(value) <= limit):
        return True
    bound = "" if limit is None else f" of at most {limit} characters"
    out.append(violation(pointer, f"must be a non-empty string{bound}"))
    return False


def _optional_text(value: object, pointer: str, out: list, limit: int | None = None) -> bool:
    return value is None or _text(value, pointer, out, limit)


def _one_of(value: object, pointer: str, allowed: tuple, out: list) -> bool:
    if isinstance(value, str) and value in allowed:
        return True
    out.append(violation(pointer, "must be one of: " + ", ".join(allowed)))
    return False


def _exact_int(value: object, pointer: str, expected: int, out: list) -> bool:
    if type(value) is int and value == expected:
        return True
    out.append(violation(pointer, f"must be the integer {expected}"))
    return False


def _pattern(value: object, pointer: str, pattern, message: str, out: list,
             nullable: bool = False) -> bool:
    if (nullable and value is None) or (isinstance(value, str) and pattern.fullmatch(value)):
        return True
    out.append(violation(pointer, ("must be null or " if nullable else "must be ") + message))
    return False


def _revision(value: object, pointer: str, out: list) -> bool:
    return _pattern(value, pointer, REVISION, "40 lowercase hex digits", out, nullable=True)


def _digest_id(value: object, pointer: str, out: list) -> bool:
    return _pattern(value, pointer, DIGEST_ID, "'sha256:' and 64 lowercase hex digits", out)


def _path(value: object, pointer: str, out: list) -> bool:
    if is_safe_relative_path(value):
        return True
    out.append(violation(pointer, "must be a safe repository-relative path"))
    return False


def _list(value: object, pointer: str, out: list, minimum: int = 0,
          maximum: int | None = None) -> bool:
    if not isinstance(value, list):
        out.append(violation(pointer, "must be a list"))
        return False
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        bound = f"at least {minimum}" if maximum is None else f"{minimum} to {maximum}"
        out.append(violation(pointer, f"must hold {bound} entries"))
    return True


def _citation(value: object, pointer: str, out: list) -> None:
    if not _members(value, pointer, CITATION_MEMBERS, out):
        return
    _text(value.get("repository"), _child(pointer, "repository"), out)
    _path(value.get("path"), _child(pointer, "path"), out)
    _revision(value.get("revision"), _child(pointer, "revision"), out)
    _text(value.get("anchor"), _child(pointer, "anchor"), out, ANCHOR_MAX)


def _lesson(value: object, out: list) -> None:
    if not _members(value, "/lesson", LESSON_MEMBERS, out):
        return
    _text(value.get("title"), "/lesson/title", out, TITLE_MAX)
    _text(value.get("statement"), "/lesson/statement", out, TEXT_MAX)
    _citation(value.get("source"), "/lesson/source", out)


def _destination(value: object, out: list) -> object:
    """Returns the declared layer when it is one, else `None`."""
    if not _members(value, "/destination", DESTINATION_MEMBERS, out):
        return None
    layer = value.get("layer")
    known = _one_of(layer, "/destination/layer", LAYERS, out)
    _text(value.get("owner"), "/destination/owner", out)
    name = value.get("name")
    if _text(name, "/destination/name", out) and known and layer in NAME_PATTERNS:
        pattern = NAME_PATTERNS[layer]
        if not pattern.fullmatch(name):
            out.append(violation("/destination/name", f"must match {pattern.pattern}"))
    _path(value.get("path"), "/destination/path", out)
    _text(value.get("anchor"), "/destination/anchor", out, ANCHOR_MAX)
    return layer if known else None


def _corroboration(value: object, out: list) -> None:
    if not _members(value, "/corroboration", CORROBORATION_MEMBERS, out):
        return
    repositories = value.get("repositories")
    if _list(repositories, "/corroboration/repositories", out, maximum=CITATIONS_MAX):
        for index, item in enumerate(repositories):
            _citation(item, f"/corroboration/repositories/{index}", out)
    _optional_text(value.get("platform_governance"), "/corroboration/platform_governance",
                   out, TEXT_MAX)


def _local_duplicates(value: object, out: list) -> None:
    pointer = "/" + LOCAL_DUPLICATES_MEMBER
    if not _list(value, pointer, out, maximum=DUPLICATES_MAX):
        return
    for index, item in enumerate(value):
        entry = f"{pointer}/{index}"
        if not _members(item, entry, DUPLICATE_MEMBERS, out):
            continue
        _text(item.get("repository"), f"{entry}/repository", out)
        _path(item.get("path"), f"{entry}/path", out)
        _pattern(item.get("sha256"), f"{entry}/sha256", SHA256, "64 lowercase hex digits",
                 out, nullable=True)
        _one_of(item.get("disposition"), f"{entry}/disposition", DISPOSITIONS, out)


def _native_admission(value: object, layer: object, out: list) -> None:
    if value is None:
        if layer == "native_extension":
            out.append(violation("/native_admission",
                                 "is required for the native_extension layer"))
        return
    if not _members(value, "/native_admission", ADMISSION_MEMBERS, out):
        return
    _one_of(value.get("gate"), "/native_admission/gate", (ADMISSION_GATE,), out)
    _one_of(value.get("decision"), "/native_admission/decision", ADMISSION_DECISIONS, out)
    _text(value.get("irreducible_scenario"), "/native_admission/irreducible_scenario",
          out, TEXT_MAX)


def _authored(document: dict, out: list) -> None:
    _lesson(document.get("lesson"), out)
    layer = _destination(document.get("destination"), out)
    _corroboration(document.get("corroboration"), out)
    _local_duplicates(document.get(LOCAL_DUPLICATES_MEMBER), out)
    if "native_admission" in document:
        _native_admission(document["native_admission"], layer, out)


def _classification(value: object, out: list) -> None:
    if not _members(value, "/classification", CLASSIFICATION_MEMBERS, out):
        return
    rule = value.get("rule")
    if type(rule) is int and rule in RULE_IDS:
        if value.get("rule_id") != RULE_IDS[rule]:
            out.append(violation("/classification/rule_id",
                                 f"must be {RULE_IDS[rule]} for rule {rule}"))
    else:
        out.append(violation("/classification/rule",
                             f"must be an integer from 1 to {len(CLASSIFICATION_RULES)}"))
        _one_of(value.get("rule_id"), "/classification/rule_id", tuple(RULE_IDS.values()),
                out)
    _one_of(value.get("declared_layer"), "/classification/declared_layer", LAYERS, out)
    if not isinstance(value.get("overridden_by_rule_1"), bool):
        out.append(violation("/classification/overridden_by_rule_1", "must be a boolean"))


def _evidence(value: object, out: list) -> None:
    if not _members(value, "/evidence", EVIDENCE_MEMBERS, out):
        return
    _path(value.get("bundle_path"), "/evidence/bundle_path", out)
    _digest_id(value.get("bundle_id"), "/evidence/bundle_id", out)
    _one_of(value.get("state"), "/evidence/state", BUNDLE_STATES, out)
    _one_of(value.get("gate_contract"), "/evidence/gate_contract", (GATE_CONTRACT,), out)
    _exact_int(value.get("gate_version"), "/evidence/gate_version", GATE_VERSION, out)


def _deployment(value: object, out: list) -> None:
    if not _members(value, "/deployment", DEPLOYMENT_MEMBERS, out):
        return
    _text(value.get("verified_repository"), "/deployment/verified_repository", out)
    for member in ("removed", "retained"):
        paths = value.get(member)
        if _list(paths, f"/deployment/{member}", out):
            for index, item in enumerate(paths):
                _path(item, f"/deployment/{member}/{index}", out)
    deferred = value.get("deferred_repositories")
    if _list(deferred, "/deployment/deferred_repositories", out):
        for index, item in enumerate(deferred):
            _text(item, f"/deployment/deferred_repositories/{index}", out)


def _tracker(value: object, out: list) -> None:
    if not _members(value, "/tracker", TRACKER_MEMBERS, out):
        return
    ref = value.get("ref")
    if ref is not None and not (type(ref) is int and ref >= 1):
        out.append(violation("/tracker/ref", "must be null or an integer of at least 1"))
    _one_of(value.get("label"), "/tracker/label", (TRACKER_LABEL,), out)
    command = value.get("create_command")
    if _list(command, "/tracker/create_command", out, minimum=1):
        for index, item in enumerate(command):
            _text(item, f"/tracker/create_command/{index}", out)


def _history(value: object, out: list) -> None:
    if not _list(value, "/history", out, minimum=1):
        return
    for index, item in enumerate(value):
        entry = f"/history/{index}"
        if not _members(item, entry, HISTORY_MEMBERS, out):
            continue
        if item.get("from") is not None:
            _one_of(item.get("from"), f"{entry}/from", STATES, out)
        _one_of(item.get("to"), f"{entry}/to", STATES, out)
        _optional_text(item.get("actor"), f"{entry}/actor", out)
        _optional_text(item.get("rationale"), f"{entry}/rationale", out)


def _optional_section(document: dict, member: str, check, out: list) -> None:
    """Presence is never tied to `state` (D13): `null` is always accepted."""
    if document.get(member) is not None:
        check(document[member], out)


def _draft(document: dict, out: list) -> None:
    _authored(document, out)


def _candidate(document: dict, out: list) -> None:
    _digest_id(document.get("candidate_id"), "/candidate_id", out)
    _one_of(document.get("state"), "/state", STATES, out)
    _authored(document, out)
    _optional_section(document, "classification", _classification, out)
    _optional_section(document, "evidence", _evidence, out)
    _optional_section(document, "deployment", _deployment, out)
    _tracker(document.get("tracker"), out)
    _history(document.get("history"), out)


def _evaluation(document: dict, out: list) -> None:
    _digest_id(document.get("evaluation_id"), "/evaluation_id", out)
    scope = document.get("scope")
    if _members(scope, "/scope", SCOPE_MEMBERS, out):
        _text(scope.get("repository"), "/scope/repository", out)
        _revision(scope.get("revision"), "/scope/revision", out)
    commands = document.get("commands")
    if _list(commands, "/commands", out, minimum=1, maximum=COMMANDS_MAX):
        for index, item in enumerate(commands):
            _text(item, f"/commands/{index}", out, TEXT_MAX)
    candidates = document.get("candidates")
    listed = _list(candidates, "/candidates", out)
    if listed:
        for index, item in enumerate(candidates):
            _digest_id(item, f"/candidates/{index}", out)
    outcome = document.get("outcome")
    if _one_of(outcome, "/outcome", EVALUATION_OUTCOMES, out) and listed:
        expected = "found" if candidates else "empty"
        if outcome != expected:
            out.append(violation("/outcome",
                                 f"must be {expected} for {len(candidates)} candidates"))


VALIDATORS = {DRAFT_KIND: _draft, CANDIDATE_KIND: _candidate, EVALUATION_KIND: _evaluation}


def validate_document(document: object) -> list[dict]:
    """The violations of `document`, sorted by `(pointer, message)` and
    de-duplicated; `[]` means valid. Shape only: no id is recomputed (D13).
    """
    out: list[dict] = []
    _forbidden_names(document, "", out)
    if not isinstance(document, dict):
        out.append(violation("", "must be an object"))
    else:
        _exact_int(document.get("schema_version"), "/schema_version", SCHEMA_VERSION, out)
        kind = document.get("kind")
        if _one_of(kind, "/kind", KINDS, out):
            _members(document, "", MEMBERS_BY_KIND[kind], out)
            VALIDATORS[kind](document, out)
    unique = {(item["pointer"], item["message"]) for item in out}
    return [violation(pointer, message) for pointer, message in sorted(unique)]
