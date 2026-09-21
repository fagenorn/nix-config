"""Pure canonical delivery contracts, authority matching, and reduction."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import re
from typing import Any

MODEL_INTERFACE_VERSION = 1

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_STAGE_ACTIONS = {
    "select_reviewed_output": ("select_output", "ledger_write", "selected_output"),
    "deliver_repository_record": ("write_record", "repository_write", "repository_record_proposed"),
    "publish_branch": ("push_branch", "repository_write", "branch_published"),
    "open_pr": ("open_pull_request", "provider_write", "pr_opened"),
    "merge_pr": ("merge_pull_request", "provider_write", "pr_merged"),
    "close_tracker": ("close_issue", "tracker_write", "tracker_closed"),
    "delete_remote_branch": ("delete_remote_branch", "repository_write", "remote_branch_absent"),
    "remove_worktree": ("remove_worktree", "filesystem_write", "worktree_absent"),
    "delete_local_branch": ("delete_local_branch", "repository_write", "local_branch_absent"),
}
_POSTCONDITIONS = ("implementation_delivered", "pr_merged", "tracker_closed", "cleanup_complete")
class DeliveryModelError(ValueError):
    """A delivery object is structurally or semantically invalid."""


def _reject(message: str = "invalid") -> None:
    raise DeliveryModelError(message)


def canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes:
    candidate = copy.deepcopy(value)
    if omit_derived is not None:
        if not isinstance(candidate, dict) or omit_derived not in candidate:
            _reject(f"missing derived member: {omit_derived}")
        del candidate[omit_derived]
    try:
        return (json.dumps(candidate, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeliveryModelError("value is not canonical JSON") from error


def canonical_digest(value: object, *, omit_derived: str | None = None) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, omit_derived=omit_derived)).hexdigest()


def _members(value: str) -> set[str]:
    return set(value.split())


def _object(value: Any, keys: set[str], label: str = "object") -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _reject(f"invalid {label} keys")
    return value


def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _reject(f"invalid {label}")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _reject(f"invalid {label}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        _reject(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _reject(f"invalid {label}")
    return value


def _utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        _reject(f"invalid {label}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise DeliveryModelError(f"invalid {label}") from error
    return value


def _derived(value: dict[str, Any], label: str, field: str = "id") -> None:
    _digest(value[field], f"{label} {field}")
    if value[field] != canonical_digest(value, omit_derived=field):
        _reject(f"invalid {label} {field}")


def _sorted_unique(values: Any, label: str, *, key=lambda item: item) -> list[Any]:
    if not isinstance(values, list):
        _reject(f"invalid {label}")
    keys = [key(item) for item in values]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _reject(f"invalid {label} order")
    return values


def _ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        _reject(f"invalid {label}")
    if value["kind"] == "none":
        return _object(value, _members("kind"), label)
    if value["kind"] == "literal":
        _object(value, _members("kind value"), label); _string(value["value"], label)
        return value
    _reject(f"invalid {label} kind")


def _data_ref(value: Any, label: str, *, allow_slot: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        _reject(f"invalid {label}")
    kind = value["kind"]
    if kind == "none":
        return _object(value, _members("kind"), label)
    if kind == "literal":
        _object(value, _members("kind digest classification audience"), label)
        _digest(value["digest"], f"{label} digest")
    elif kind == "selected_output_slot" and allow_slot:
        _object(value, _members("kind slot_id classification audience"), label)
        _string(value["slot_id"], f"{label} slot")
    else:
        _reject(f"invalid {label} kind")
    _string(value["classification"], f"{label} classification")
    _string(value["audience"], f"{label} audience")
    return value


def _scope(value: Any) -> dict[str, Any]:
    keys = {"schema_version", "kind", "id", "principal", "action", "effect", "target",
            "endpoint", "data", "risk", "spend"}
    value = _object(value, keys, "scope tuple")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "scope-tuple":
        _reject()
    principal = _object(value["principal"], _members("kind stable_id"))
    _string(principal["kind"], "principal kind"); _string(principal["stable_id"], "principal id")
    _string(value["action"], "scope action"); _string(value["effect"], "scope effect")
    target = _object(value["target"], {"project_id", "provider", "repository_id", "repository_slug",
        "issue", "branch", "base", "pr_ref", "output_ref"}, "scope target")
    for key in ("project_id", "provider", "repository_id", "repository_slug", "branch", "base"):
        _string(target[key], f"target {key}")
    _integer(target["issue"], "target issue", minimum=1)
    _ref(target["pr_ref"], "pr ref"); _ref(target["output_ref"], "output ref") if target["output_ref"].get("kind") != "slot" else _slot_ref(target["output_ref"], "output ref", constraints=False)
    _ref(value["endpoint"], "endpoint")
    _data_ref(value["data"], "scope data")
    _string(value["risk"], "risk")
    spend = value["spend"]
    if not isinstance(spend, dict) or "kind" not in spend:
        _reject()
    if spend["kind"] == "none": _object(spend, _members("kind"))
    elif spend["kind"] == "ceiling":
        _object(spend, _members("kind unit ceiling")); _string(spend["unit"], "spend unit"); _integer(spend["ceiling"], "spend ceiling")
    else: _reject()
    _derived(value, "scope tuple")
    return value


def _slot_ref(value: Any, label: str, *, constraints: bool = True) -> dict[str, Any]:
    keys = {"kind", "slot_id"} if not constraints else {"kind", "slot_id", "subject_kind", "constraints"}
    value = _object(value, keys, label)
    if value["kind"] != "slot": _reject(f"invalid {label} kind")
    _string(value["slot_id"], f"{label} slot")
    if constraints:
        if value["subject_kind"] not in {"commit", "tree", "record", "pull_request"}: _reject()
        c = _object(value["constraints"], _members("project_id provider repository_id repository_slug branch base deliverable_class data_ref"))
        for key in ("project_id", "provider", "repository_id", "repository_slug", "branch", "base", "deliverable_class"): _string(c[key], f"constraint {key}")
        _data_ref(c["data_ref"], "constraint data")
        if c["data_ref"].get("kind") == "selected_output_slot" and c["data_ref"]["slot_id"] != value["slot_id"]: _reject()
    return value


def _intent(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id predecessor_intent_id source issued_at expires_at revocation_key scopes"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "authorization-intent": _reject()
    if value["predecessor_intent_id"] is not None: _digest(value["predecessor_intent_id"], "predecessor")
    source = _object(value["source"], _members("kind reference evidence_digest"))
    if source["kind"] not in {"explicit_user", "standing_repository", "parent_handoff"}: _reject()
    _string(source["reference"], "intent reference"); _digest(source["evidence_digest"], "intent evidence")
    _utc(value["issued_at"], "issued_at")
    if value["expires_at"] is not None: _utc(value["expires_at"], "expires_at")
    _string(value["revocation_key"], "revocation key")
    _sorted_unique(value["scopes"], "intent scopes", key=lambda item: item.get("id", ""))
    if not value["scopes"]: _reject()
    for item in value["scopes"]: _scope(item)
    _derived(value, "authorization intent")
    return value


def _selected(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest slot_id subject_kind subject_value data_identity_digest repository_id branch base evidence_digest review_evidence_ids"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "selected-output": _reject()
    for key in ("contract_digest", "data_identity_digest", "evidence_digest"): _digest(value[key], key)
    for key in ("slot_id", "subject_kind", "subject_value", "repository_id", "branch", "base"): _string(value[key], key)
    _sorted_unique(value["review_evidence_ids"], "review evidence")
    for item in value["review_evidence_ids"]: _string(item, "review evidence id")
    _derived(value, "selected output")
    return value


def _contract(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind project issue deliverable stages initial_authorization_intent_id initial_authorization_intent_digest provenance"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "delivery-contract": _reject()
    project = _object(value["project"], _members("project_id provider repository_id repository_slug"))
    for item in project.values(): _string(item, "project value")
    _integer(value["issue"], "contract issue", minimum=1)
    delivery = _object(value["deliverable"], _members("id summary obligations"))
    _string(delivery["id"], "deliverable id"); _string(delivery["summary"], "summary")
    if len(delivery["summary"]) > notes_max: _reject()
    obligations = _object(delivery["obligations"], set(_POSTCONDITIONS), "obligations")
    if any(item not in {"required", "not_applicable"} for item in obligations.values()): _reject()
    if not isinstance(value["stages"], list) or not value["stages"]: _reject()
    ids = []
    for stage in value["stages"]:
        stage = _object(stage, _members("id kind action effect target_ref worktree_requirement depends_on retryable"))
        _string(stage["id"], "stage id")
        if stage["id"] in ids: _reject()
        if stage["kind"] not in _STAGE_ACTIONS: _reject()
        action, effect, _ = _STAGE_ACTIONS[stage["kind"]]
        if (stage["action"], stage["effect"]) != (action, effect): _reject()
        if stage["target_ref"].get("kind") == "slot": _slot_ref(stage["target_ref"], "target ref")
        else: _ref(stage["target_ref"], "target ref")
        if stage["worktree_requirement"] not in {"matching_required", "cleanup_target", "not_required"}: _reject()
        _sorted_unique(stage["depends_on"], "dependencies")
        if any(dep not in ids for dep in stage["depends_on"]): _reject()
        _boolean(stage["retryable"], "retryable"); ids.append(stage["id"])
    _digest(value["initial_authorization_intent_id"], "initial intent id"); _digest(value["initial_authorization_intent_digest"], "initial intent digest")
    provenance = _object(value["provenance"], _members("kind reference digest created_at"))
    _string(provenance["kind"], "provenance kind"); _string(provenance["reference"], "provenance reference"); _digest(provenance["digest"], "provenance digest"); _utc(provenance["created_at"], "provenance time")
    return value


def validate_custody_ref(value: object, *, issue: int) -> dict[str, object]:
    candidate = copy.deepcopy(value)
    _integer(issue, "custody issue", minimum=1)
    if not isinstance(candidate, dict) or candidate.get("kind") not in {"implementation", "remainder"}: _reject()
    if candidate["kind"] == "implementation":
        _object(candidate, _members("kind attempt launch action_id"))
        ordinal = _integer(candidate["attempt"], "attempt", minimum=1); expected = f"{issue}:{ordinal}:{_integer(candidate['launch'], 'launch', minimum=1)}"
    else:
        _object(candidate, _members("kind remainder launch action_id"))
        ordinal = _integer(candidate["remainder"], "remainder", minimum=1); expected = f"{issue}:r{ordinal}:{_integer(candidate['launch'], 'launch', minimum=1)}"
    if candidate["action_id"] != expected: _reject()
    return candidate


def _custody_issue(value: Any) -> int:
    if not isinstance(value, dict) or not isinstance(value.get("action_id"), str):
        _reject()
    prefix = value["action_id"].split(":", 1)[0]
    if not prefix.isdigit() or prefix.startswith("0"):
        _reject()
    return _integer(int(prefix), "custody issue", minimum=1)


def _authority(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest scope_id launch_id authority_kind verdict reason_code observed_at evidence_digest opaque_host_reference revocation_subject evaluation_use_key"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "authority-observation": _reject()
    _digest(value["contract_digest"], "authority contract"); _digest(value["scope_id"], "authority scope")
    if value["authority_kind"] not in {"intent_revocation", "native_guard", "host", "provider"}: _reject()
    if value["verdict"] not in {"allowed", "rejected", "unknown", "revoked"}: _reject()
    if value["authority_kind"] == "intent_revocation":
        if value["launch_id"] is not None or value["verdict"] != "revoked": _reject()
        subject = _object(value["revocation_subject"], _members("intent_id revocation_key")); _digest(subject["intent_id"], "revoked intent"); _string(subject["revocation_key"], "revocation key")
    else:
        _string(value["launch_id"], "authority launch")
        if value["revocation_subject"] is not None: _reject()
    _string(value["reason_code"], "authority reason"); _utc(value["observed_at"], "authority time"); _digest(value["evidence_digest"], "authority evidence")
    if value["opaque_host_reference"] is not None: _string(value["opaque_host_reference"], "host reference")
    if value["evaluation_use_key"] is not None: _digest(value["evaluation_use_key"], "evaluation use key")
    if value["authority_kind"] == "intent_revocation" and value["evaluation_use_key"] is not None: _reject()
    _derived(value, "authority observation"); return value


def _reevaluation(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest scope_id rejected_observation_id source_kind reason_code observed_at evidence_digest"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "reevaluation-evidence" or value["source_kind"] not in {"host", "provider"}: _reject()
    for key in ("contract_digest", "scope_id", "rejected_observation_id", "evidence_digest"): _digest(value[key], key)
    _string(value["reason_code"], "reevaluation reason"); _utc(value["observed_at"], "reevaluation time"); _derived(value, "reevaluation evidence"); return value


def _consumption(value: Any, issue: int) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id use_key contract_digest scope_id rejected_observation_id basis custody consumed_at"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "authority-evaluation-consumption": _reject()
    basis = _object(value["basis"], _members("kind id"))
    if basis["kind"] not in {"successor_intent", "reevaluation_evidence"}: _reject()
    for key in ("id", "contract_digest", "scope_id", "rejected_observation_id"): _digest(value[key], key)
    validate_custody_ref(value["custody"], issue=issue); _utc(value["consumed_at"], "consumed_at")
    expected = canonical_digest({"contract_digest": value["contract_digest"], "scope_id": value["scope_id"], "rejected_observation_id": value["rejected_observation_id"], "basis": basis})
    if value["use_key"] != expected: _reject()
    _derived(value, "evaluation consumption"); return value


def _stage_fact(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest stage_id state observation_id"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "delivery-stage-fact": _reject()
    _digest(value["contract_digest"], "fact contract"); _string(value["stage_id"], "fact stage")
    if value["state"] not in {"pending", "observed", "not_applicable"}: _reject()
    if (value["state"] == "observed") != (value["observation_id"] is not None): _reject()
    if value["observation_id"] is not None: _digest(value["observation_id"], "fact observation")
    _derived(value, "stage fact"); return value


def _delivery_observation(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest project observation_kind subject source observed_at evidence_digest"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "delivery-observation": _reject()
    _digest(value["contract_digest"], "observation contract")
    project = _object(value["project"], _members("project_id provider repository_id repository_slug"))
    for item in project.values(): _string(item, "observation project value")
    if value["observation_kind"] not in {item[2] for item in _STAGE_ACTIONS.values()} | set(_POSTCONDITIONS): _reject()
    if not isinstance(value["subject"], dict) or not value["subject"]: _reject()
    source = _object(value["source"], _members("kind reference"))
    if source["kind"] not in {"provider", "tracker", "repository", "filesystem", "human_completion"}: _reject()
    _string(source["reference"], "observation reference"); _utc(value["observed_at"], "observation time"); _digest(value["evidence_digest"], "observation evidence")
    subject, kind = value["subject"], value["observation_kind"]
    if kind == "selected_output": _selected(_object(subject, _members("selected_output"))["selected_output"])
    elif kind == "branch_published":
        _object(subject, _members("repository_id branch selected_head"))
        for item in subject.values(): _string(item, "branch subject")
    elif kind in {"pr_opened", "pr_merged"}:
        fields = "provider_repository_id pr_number pr_url expected_head base" + (" merge_sha merged" if kind == "pr_merged" else "")
        _object(subject, _members(fields)); _integer(subject["pr_number"], "pr number", minimum=1)
        for name in ("provider_repository_id", "pr_url", "expected_head", "base"): _string(subject[name], name)
        if kind == "pr_merged": _string(subject["merge_sha"], "merge sha"); _boolean(subject["merged"], "merged")
    elif kind == "repository_record_proposed":
        _object(subject, _members("repository_id selected_record_digest branch live_pr_head review_evidence_ids")); _digest(subject["selected_record_digest"], "record digest"); _sorted_unique(subject["review_evidence_ids"], "record reviews")
    elif kind == "tracker_closed":
        _object(subject, _members("tracker_repository_id issue state close_reason observation_identity")); _integer(subject["issue"], "tracker issue", minimum=1)
        if subject["state"] != "closed": _reject()
    elif kind in {"remote_branch_absent", "local_branch_absent"}:
        _object(subject, _members("repository_id branch absent")); _boolean(subject["absent"], "absent")
        if not subject["absent"]: _reject()
    elif kind == "worktree_absent":
        _object(subject, _members("path recorded_worktree_identity probe_mode absent")); _boolean(subject["absent"], "absent")
        if subject["probe_mode"] != "no_follow" or not subject["absent"]: _reject()
    _derived(value, "delivery observation"); return value


def _v2(value: dict[str, Any]) -> None:
    if type(value["interface_version"]) is not int or value["interface_version"] != 2: _reject()


def _requirements(values: Any, *, sorted_values: bool) -> list[Any]:
    if not isinstance(values, list): _reject()
    if sorted_values: _sorted_unique(values, "requirements", key=lambda item: canonical_bytes(item))
    for item in values:
        if not isinstance(item, dict) or "kind" not in item: _reject()
        if item["kind"] in {"delivery_contract", "scope_tuple", "observation", "worktree_fact"}:
            _object(item, _members("kind subject_id reason_code detail_pointer"))
            _string(item["subject_id"], "requirement subject"); _string(item["reason_code"], "requirement reason")
            if item["detail_pointer"] is not None: _string(item["detail_pointer"], "requirement detail")
        elif item["kind"] in {"tracker", "candidate_worktree"}: _object(item, _members("kind"))
        elif item["kind"] in {"recorded_worktree", "forge_pr"}: _object(item, _members("kind path")); _string(item["path"], "requirement path")
        else: _reject()
    return values


def _pending(values: Any, contract: dict[str, Any] | None) -> list[Any]:
    if not isinstance(values, list) or len(values) != len(set(values)) or any(not isinstance(item, str) or not item for item in values): _reject()
    if contract is not None:
        order = [item["id"] for item in contract["stages"]]
        if any(item not in order for item in values) or values != [item for item in order if item in values]: _reject()
    return values


def _evaluation(value: Any, *, issue: int, contract_digest: str, custody: dict[str, Any]) -> None:
    if value is None: return
    value = _object(value, _members("kind contract_digest scope_id custody rejected_observation_id basis_kind basis_id use_key"))
    if value["kind"] != "native_authority_evaluation" or value["contract_digest"] != contract_digest or value["custody"] != custody or value["basis_kind"] not in {"successor_intent", "reevaluation_evidence"}: _reject()
    validate_custody_ref(value["custody"], issue=issue)
    for name in ("contract_digest", "scope_id", "rejected_observation_id", "basis_id", "use_key"): _digest(value[name], name)


def _delivery_block(value: dict[str, Any], *, issue: int, notes_max: int) -> dict[str, Any]:
    contract = _contract(value["contract"], notes_max); digest = canonical_digest(contract)
    if contract["issue"] != issue or value["contract_digest"] != digest: _reject()
    _pending(value["pending_stage_ids"], contract); _requirements(value["requirements"], sorted_values=True)
    _evaluation(value["authority_evaluation"], issue=issue, contract_digest=digest, custody=value["custody"])
    return contract


def _owner_action(value: Any, notes_max: int, *, control: bool = False) -> dict[str, Any]:
    base = {"id", "kind", "issue", "attempt", "owner", "worktree", "handoff_path", "deadline_at"} if control else {"interface_version", "kind", "ledger_repo_root", "run_id", "issue", "attempt", "owner", "action_id", "launch_kind", "worktree", "handoff_path", "deadline_at"}
    value = _object(value, base | {"custody", "contract", "contract_digest", "pending_stage_ids", "requirements", "authority_evaluation"}, "owner action")
    if not control: _v2(value)
    if value["kind"] not in ({"spawn", "resume", "retry"} if control else {"owner"}): _reject()
    issue = _integer(value["issue"], "owner issue", minimum=1); attempt = _integer(value["attempt"], "owner attempt", minimum=1); custody = validate_custody_ref(value["custody"], issue=issue)
    if custody["kind"] != "implementation" or custody["attempt"] != attempt: _reject()
    if control and value["id"] != custody["action_id"]: _reject()
    if not control and (value["action_id"] != custody["action_id"] or value["launch_kind"] not in {"spawn", "resume", "retry"}): _reject()
    for name in (("owner", "worktree", "handoff_path", "deadline_at") if control else ("ledger_repo_root", "run_id", "owner", "worktree", "handoff_path", "deadline_at")): _string(value[name], name)
    _utc(value["deadline_at"], "owner deadline"); _delivery_block(value, issue=issue, notes_max=notes_max)
    return value


def _remainder(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, _members("interface_version kind ledger_repo_root run_id issue source_attempt owner custody worktree contract contract_digest pending_stage_ids deadline_at requirements authority_evaluation")); _v2(value)
    if value["kind"] != "delivery_remainder": _reject()
    issue = _integer(value["issue"], "remainder issue", minimum=1); _integer(value["source_attempt"], "source attempt", minimum=1)
    custody = validate_custody_ref(value["custody"], issue=issue)
    if custody["kind"] != "remainder": _reject()
    for name in ("ledger_repo_root", "run_id", "owner", "worktree", "deadline_at"): _string(value[name], name)
    _utc(value["deadline_at"], "remainder deadline"); _delivery_block(value, issue=issue, notes_max=notes_max); return value


def _blockers(values: Any) -> None:
    if not isinstance(values, list): _reject()
    _sorted_unique(values, "blockers", key=lambda item: (item.get("kind", ""), item.get("issue", 0)))
    for item in values:
        item = _object(item, _members("kind issue url"))
        if item["kind"] not in {"issue", "decision"}: _reject()
        _integer(item["issue"], "blocker issue", minimum=1)
        if item["url"] is not None: _string(item["url"], "blocker url")


def _response_common(value: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    _v2(value); issue = _integer(value["issue"], "response issue", minimum=1); custody = validate_custody_ref(value["custody"], issue=issue)
    for name in ("ledger_repo_root", "run_id", "owner"): _string(value[name], name)
    _digest(value["contract_digest"], "response contract"); _sorted_unique(value["accepted_observation_ids"], "accepted observations")
    for item in value["accepted_observation_ids"]: _digest(item, "accepted observation")
    _pending(value["pending_stage_ids"], None); return issue, custody


def _checkpoint_response(value: Any, notes_max: int) -> dict[str, Any]:
    common = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue", "owner", "custody", "contract_digest", "accepted_observation_ids", "pending_stage_ids"}
    if value.get("kind") == "delivery_stalled":
        _object(value, common | {"state", "stalled_resumes", "result_source", "reason_code"}, "stalled response"); _response_common(value)
        if (value["state"], value["stalled_resumes"], value["result_source"], value["reason_code"]) != ("terminal_failed", 3, "stalled", "suspension_stalled_without_progress"): _reject()
        return value
    _object(value, common | {"next_action", "requirements", "authority_evaluation", "state", "blocked_on"}, "checkpoint response"); issue, custody = _response_common(value)
    if value["state"] not in {"active", "suspended"} or value["blocked_on"] not in {None, "human_gate", "external", "transport"}: _reject()
    _requirements(value["requirements"], sorted_values=True); _evaluation(value["authority_evaluation"], issue=issue, contract_digest=value["contract_digest"], custody=custody)
    if value["state"] == "active" and value["blocked_on"] is not None: _reject()
    if value["next_action"] is not None:
        if not isinstance(value["next_action"], dict): _reject()
        (_owner_action if value["next_action"].get("kind") == "owner" else _remainder)(value["next_action"], notes_max)
    return value


def _finish_response(value: Any) -> dict[str, Any]:
    common = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue", "owner", "custody", "contract_digest", "accepted_observation_ids", "pending_stage_ids", "state"}
    failed = value.get("kind") == "terminal_failed"
    _object(value, common | ({"result_source", "reason_code"} if failed else set()), "finish response"); _response_common(value)
    if failed:
        if (value["state"], value["result_source"], value["reason_code"]) != ("terminal_failed", "owner", "owner_reported_failure"): _reject()
    elif value["state"] != "delivery_complete" or value["pending_stage_ids"]: _reject()
    return value


def _control_response(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, _members("interface_version run_id now summaries deltas actions next_deadline")); _v2(value); _string(value["run_id"], "control run"); _utc(value["now"], "control now")
    if value["next_deadline"] is not None: _utc(value["next_deadline"], "next deadline")
    if not all(isinstance(value[name], list) for name in ("summaries", "deltas", "actions")): _reject()
    issues = set()
    for item in value["summaries"]:
        item = _object(item, _members("issue state custody owner worktree deadline_at blocked_on blockers result contract_digest pending_stage_ids requirements"))
        issue = _integer(item["issue"], "summary issue", minimum=1)
        if issue in issues or item["state"] not in {"queued", "blocked", "fogged", "active", "handed_off", "suspended", "merged", "stopped", "failed", "closed"}: _reject()
        issues.add(issue)
        if item["custody"] is not None: validate_custody_ref(item["custody"], issue=issue)
        for name in ("owner", "worktree", "deadline_at", "blocked_on", "contract_digest"):
            if item[name] is not None: (_digest if name == "contract_digest" else _string)(item[name], name)
        if item["result"] is not None and not isinstance(item["result"], dict): _reject()
        _blockers(item["blockers"]); _pending(item["pending_stage_ids"], None); _requirements(item["requirements"], sorted_values=True)
        if item["contract_digest"] is None and (item["pending_stage_ids"] or any(req["kind"] != "delivery_contract" for req in item["requirements"])): _reject()
    for item in value["deltas"]:
        item = _object(item, _members("issue custody kind state")); issue = _integer(item["issue"], "delta issue", minimum=1)
        if item["custody"] is not None: validate_custody_ref(item["custody"], issue=issue)
        if item["kind"] not in {"expired", "spawned", "resumed", "retried", "retry_refused"}: _reject()
        _string(item["state"], "delta state")
    for item in value["actions"]:
        if not isinstance(item, dict) or "kind" not in item: _reject()
        if item["kind"] in {"spawn", "resume", "retry"}: _owner_action(item, notes_max, control=True)
        elif item["kind"] == "wait":
            _object(item, _members("id kind wake_on deadline_at")); _string(item["id"], "wait id"); _utc(item["deadline_at"], "wait deadline"); _sorted_unique(item["wake_on"], "wake events")
            if any(event not in {"owner_notification", "tracker_change", "deadline"} for event in item["wake_on"]): _reject()
        elif item["kind"] == "finalize": _object(item, _members("id kind")); _string(item["id"], "finalize id")
        elif item["kind"] == "delivery_remainder": _remainder(item, notes_max)
        else: _reject()
    return value


def _workflow_response(value: Any, notes_max: int) -> dict[str, Any]:
    if not isinstance(value, dict): _reject()
    if set(value) == {"action_id", "current", "current_action_id", "reason"}:
        _string(value["action_id"], "action id"); _boolean(value["current"], "current")
        if value["current_action_id"] is not None: _string(value["current_action_id"], "current action")
        if value["reason"] not in {"unknown_run", "unknown_issue", "unknown_attempt", "superseded_attempt", "inactive_attempt", "superseded_launch", "current"}: _reject()
        if value["current"] != (value["reason"] == "current") or (value["current"] and value["current_action_id"] != value["action_id"]): _reject()
        return value
    if value.get("kind") == "workflow_bootstrap":
        _object(value, _members("interface_version kind run_id requirements")); _v2(value); _string(value["run_id"], "run id")
        _sorted_unique(value["requirements"], "bootstrap requirements", key=lambda item: (item.get("issue", 0), item.get("custody", {}).get("action_id", "")))
        for item in value["requirements"]:
            item = _object(item, _members("issue owner custody recorded_worktree")); issue = _integer(item["issue"], "requirement issue", minimum=1); _string(item["owner"], "requirement owner"); validate_custody_ref(item["custody"], issue=issue); _string(item["recorded_worktree"], "recorded worktree")
        return value
    if value.get("kind") == "observe":
        _object(value, _members("interface_version kind issue run_id requirements")); _v2(value); _integer(value["issue"], "observe issue", minimum=1)
        if value["run_id"] is not None: _string(value["run_id"], "observe run")
        _requirements(value["requirements"], sorted_values=False); return value
    if value.get("kind") == "owner": return _owner_action(value, notes_max)
    if value.get("kind") == "terminal":
        _object(value, _members("interface_version kind issue run_id source reason blockers result reentry")); _v2(value); _integer(value["issue"], "terminal issue", minimum=1)
        for name in ("source", "reason", "reentry"): _string(value[name], name)
        if value["run_id"] is not None: _string(value["run_id"], "terminal run")
        if value["result"] is not None and not isinstance(value["result"], dict): _reject()
        _blockers(value["blockers"]); return value
    if value.get("kind") == "delivery_remainder": return _remainder(value, notes_max)
    if value.get("kind") in {"delivery_checkpointed", "delivery_stalled"}: return _checkpoint_response(value, notes_max)
    if value.get("kind") in {"delivery_complete", "terminal_failed"}: return _finish_response(value)
    if "kind" not in value: return _control_response(value, notes_max)
    _reject()


def _bounded_notes(value: Any, notes_max: int) -> str:
    value = _string(value, "notes", nonempty=False)
    if len(value) > notes_max: _reject()
    return value


def _report_detail(value: dict[str, Any]) -> None:
    if value["detail_state"] not in {"none", "present", "unpublished"}: _reject()
    if value["report_path"] is not None: _string(value["report_path"], "report path")
    if value["detail_state"] == "present" and value["report_path"] is None: _reject()


def _report_arrays(value: dict[str, Any], names: tuple[str, ...], notes_max: int) -> None:
    validators = {"delivery_observations": lambda item: _delivery_observation(item, notes_max), "authority_observations": _authority, "reevaluation_evidence": _reevaluation}
    for name in names:
        _sorted_unique(value[name], name, key=lambda item: item.get("id", ""))
        for item in value[name]: validators[name](item)


def _ship_checkpoint(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"interface_version", "issue", "custody", "contract_digest", "delivery_observations", "authority_observations", "reevaluation_evidence", "detail_state", "report_path", "notes"}
    value = _object(value, keys, "ship checkpoint")
    if type(value["interface_version"]) is not int or value["interface_version"] != 2: _reject()
    issue = _integer(value["issue"], "checkpoint issue", minimum=1); validate_custody_ref(value["custody"], issue=issue); _digest(value["contract_digest"], "checkpoint contract")
    _report_arrays(value, ("delivery_observations", "authority_observations", "reevaluation_evidence"), notes_max); _report_detail(value); _bounded_notes(value["notes"], notes_max)
    return value


def _ship_summary(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"interface_version", "issue", "state", "custody", "historical_owner_result", "delivery_contract_digest", "delivery_observations", "authority_observations", "reevaluation_evidence", "detail_state", "report_path", "notes"}
    value = _object(value, keys, "ship summary")
    if type(value["interface_version"]) is not int or value["interface_version"] != 2 or value["state"] not in {"delivery_complete", "terminal_failed"}: _reject()
    issue = _integer(value["issue"], "summary issue", minimum=1); validate_custody_ref(value["custody"], issue=issue); _digest(value["delivery_contract_digest"], "summary contract")
    if value["historical_owner_result"] is not None and not isinstance(value["historical_owner_result"], dict): _reject()
    _report_arrays(value, ("delivery_observations", "authority_observations", "reevaluation_evidence"), notes_max); _report_detail(value); _bounded_notes(value["notes"], notes_max)
    return value


def _artifact(value: Any, label: str) -> dict[str, Any]:
    value = _object(value, _members("budget_status kind metrics path"), label)
    if value["budget_status"] not in {"within_budget", "over_budget"}: _reject(f"invalid {label} budget")
    _string(value["kind"], f"{label} kind"); _string(value["path"], f"{label} path")
    metrics = _object(value["metrics"], _members("root_bytes total_bytes file_count largest_member_bytes"), f"{label} metrics")
    for name, metric in metrics.items(): _integer(metric, f"{label} {name}")
    return value


def _ship_handoff(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"interface_version", "state", "ledger_repo_root", "run_id", "owner", "owner_worktree", "custody", "issue_number", "branch", "worktree_path", "spec_artifact", "plan_artifact", "head_sha", "review_state", "auto", "report_path", "notes", "delivery_contract", "delivery_contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observation_ids", "reevaluation_evidence_ids", "authority_evaluation_consumption_ids", "pending_stage_ids", "selected_outputs"}
    value = _object(value, keys, "ship handoff")
    if type(value["interface_version"]) is not int or value["interface_version"] != 2: _reject()
    issue = _integer(value["issue_number"], "handoff issue", minimum=1); validate_custody_ref(value["custody"], issue=issue)
    for name in ("state", "ledger_repo_root", "run_id", "owner", "owner_worktree", "branch", "worktree_path", "head_sha", "review_state"): _string(value[name], f"handoff {name}")
    _bounded_notes(value["notes"], notes_max); _boolean(value["auto"], "handoff auto")
    if value["report_path"] is not None: _string(value["report_path"], "handoff report path")
    _artifact(value["spec_artifact"], "spec artifact"); _artifact(value["plan_artifact"], "plan artifact")
    contract = _contract(value["delivery_contract"], notes_max); digest = canonical_digest(contract)
    if value["delivery_contract_digest"] != digest: _reject()
    _digest(value["authorization_chain_digest"], "handoff chain")
    _sorted_unique(value["authorization_intents"], "handoff intents", key=lambda item: item.get("id", ""))
    for item in value["authorization_intents"]: _intent(item)
    for name in ("authority_observation_ids", "reevaluation_evidence_ids", "authority_evaluation_consumption_ids", "pending_stage_ids"):
        _sorted_unique(value[name], f"handoff {name}")
        for item in value[name]: _string(item, f"handoff {name} member")
    _sorted_unique(value["selected_outputs"], "handoff selections", key=lambda item: item.get("id", ""))
    for item in value["selected_outputs"]: _selected(item)
    return value


def _delivery(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"contract", "contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observations", "reevaluation_evidence", "authority_evaluation_consumptions", "delivery_observations", "selected_outputs", "stage_facts", "postconditions"}
    value = _object(value, keys, "delivery")
    contract = _contract(value["contract"], notes_max); digest = canonical_digest(contract)
    if value["contract_digest"] != digest: _reject()
    _sorted_unique(value["authorization_intents"], "authorization intents", key=lambda item: item.get("id", ""))
    intents = []
    for item in value["authorization_intents"]:
        _intent(item); intents.append(item)
    if not intents: _reject()
    by_id = {item["id"]: item for item in intents}
    roots = [item for item in intents if item["predecessor_intent_id"] is None]
    if len(roots) != 1 or roots[0]["id"] != contract["initial_authorization_intent_id"]: _reject()
    children: dict[str, list[str]] = {}
    for item in intents:
        predecessor = item["predecessor_intent_id"]
        if predecessor is not None and predecessor not in by_id: _reject()
        if predecessor is not None: children.setdefault(predecessor, []).append(item["id"])
    if any(len(items) != 1 for items in children.values()): _reject()
    reached = {roots[0]["id"]}; current = roots[0]["id"]
    while current in children:
        current = children[current][0]
        if current in reached: _reject()
        reached.add(current)
    if reached != set(by_id): _reject()
    expected_chain = canonical_digest({"intent_ids": [item["id"] for item in intents]})
    if value["authorization_chain_digest"] != expected_chain: _reject()
    _digest(value["authorization_chain_digest"], "intent chain digest")
    validators = (("authority_observations", _authority), ("reevaluation_evidence", _reevaluation), ("delivery_observations", lambda item: _delivery_observation(item, notes_max)), ("selected_outputs", _selected))
    bodies: dict[str, bytes] = {}
    for name, validator in validators:
        _sorted_unique(value[name], name, key=lambda item: item.get("id", ""))
        for item in value[name]:
            validator(item); body = canonical_bytes(item)
            if item["id"] in bodies and bodies[item["id"]] != body: _reject()
            bodies[item["id"]] = body
    delivery_by_id = {item["id"]: item for item in value["delivery_observations"]}
    _sorted_unique(value["authority_evaluation_consumptions"], "consumptions", key=lambda item: item.get("id", ""))
    uses = set()
    for item in value["authority_evaluation_consumptions"]:
        _consumption(item, contract["issue"])
        if item["use_key"] in uses: _reject()
        uses.add(item["use_key"])
    if not isinstance(value["stage_facts"], list) or [x.get("stage_id") for x in value["stage_facts"]] != [x["id"] for x in contract["stages"]]: _reject()
    stages_by_id = {item["id"]: item for item in contract["stages"]}
    for fact in value["stage_facts"]:
        _stage_fact(fact)
        if fact["state"] == "observed":
            observed = delivery_by_id.get(fact["observation_id"])
            if observed is None or observed["observation_kind"] != _STAGE_ACTIONS[stages_by_id[fact["stage_id"]]["kind"]][2]: _reject()
    postconditions = _object(value["postconditions"], set(_POSTCONDITIONS), "postconditions")
    for key, state in postconditions.items():
        state = _object(state, _members("state observation_id"), f"postcondition {key}")
        if state["state"] not in {"pending", "observed", "not_applicable"}: _reject()
        if (state["state"] == "observed") != (state["observation_id"] is not None): _reject()
        if state["state"] == "observed" and (state["observation_id"] not in delivery_by_id or delivery_by_id[state["observation_id"]]["observation_kind"] != key): _reject()
    return value


def validate_delivery_object(value: object, *, expected_kind: str | None = None, notes_max_characters: int) -> dict[str, object]:
    _integer(notes_max_characters, "notes maximum", minimum=1)
    candidate = copy.deepcopy(value)
    if expected_kind == "workflow-response": _workflow_response(candidate, notes_max_characters)
    elif expected_kind == "ship-checkpoint": _ship_checkpoint(candidate, notes_max_characters)
    elif expected_kind == "ship-handoff": _ship_handoff(candidate, notes_max_characters)
    elif expected_kind == "ship-summary": _ship_summary(candidate, notes_max_characters)
    elif expected_kind == "delivery" or (expected_kind is None and isinstance(candidate, dict) and set(candidate) == {"contract", "contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observations", "reevaluation_evidence", "authority_evaluation_consumptions", "delivery_observations", "selected_outputs", "stage_facts", "postconditions"}): _delivery(candidate, notes_max_characters)
    else:
        if not isinstance(candidate, dict): _reject()
        kind = candidate.get("kind")
        if expected_kind is not None and kind != expected_kind: _reject()
        dispatch = {"scope-tuple": _scope, "authorization-intent": _intent, "selected-output": _selected, "delivery-contract": lambda item: _contract(item, notes_max_characters), "authority-observation": _authority, "reevaluation-evidence": _reevaluation, "authority-evaluation-consumption": lambda item: _consumption(item, _custody_issue(item["custody"])), "delivery-observation": lambda item: _delivery_observation(item, notes_max_characters), "delivery-stage-fact": _stage_fact}
        if kind not in dispatch: _reject()
        dispatch[kind](candidate)
    return candidate


def _time(value: str) -> datetime:
    _utc(value, "time"); return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def _scope_mismatch(declared: dict[str, Any], requested: dict[str, Any], selected: list[dict[str, Any]]) -> str | None:
    for key in ("principal", "action", "effect", "endpoint", "risk"):
        if requested[key] != declared[key]: return "scope_target_mismatch"
    dt, rt = declared["target"], requested["target"]
    for key in ("project_id", "provider", "repository_id", "repository_slug", "issue", "branch", "base", "pr_ref"):
        if rt[key] != dt[key]: return "scope_target_mismatch"
    output = dt["output_ref"]
    if output["kind"] == "none":
        if rt["output_ref"] != output: return "scope_target_mismatch"
    elif output["kind"] == "literal":
        if rt["output_ref"] != output: return "scope_target_mismatch"
    elif output["kind"] == "slot":
        if rt["output_ref"] != output:
            matching = [item for item in selected if item["slot_id"] == output["slot_id"]]
            if len(matching) != 1 or rt["output_ref"] != {"kind": "literal", "value": matching[0]["subject_value"]}: return "scope_target_mismatch"
    dd, rd = declared["data"], requested["data"]
    if dd["kind"] == "selected_output_slot":
        if rd != dd:
            matching = [item for item in selected if item["slot_id"] == dd["slot_id"]]
            expected = None if len(matching) != 1 else {"kind": "literal", "digest": matching[0]["data_identity_digest"], "classification": dd["classification"], "audience": dd["audience"]}
            if rd != expected: return "scope_data_mismatch"
    elif rd != dd: return "scope_data_mismatch"
    ds, rs = declared["spend"], requested["spend"]
    if ds["kind"] == "none" and rs != ds: return "scope_spend_mismatch"
    if ds["kind"] == "ceiling" and (rs.get("kind") != "ceiling" or rs.get("unit") != ds["unit"] or type(rs.get("ceiling")) is not int or rs["ceiling"] > ds["ceiling"]): return "scope_spend_mismatch"
    return None


def match_scope(contract: object, intent: object, requested: object, *, selected_outputs: list[object], at_time: str, revocation_observations: list[object]) -> dict[str, object]:
    c = validate_delivery_object(contract, expected_kind="delivery-contract", notes_max_characters=1_000_000)
    i = validate_delivery_object(intent, expected_kind="authorization-intent", notes_max_characters=1_000_000)
    r = validate_delivery_object(requested, expected_kind="scope-tuple", notes_max_characters=1_000_000)
    selections = [validate_delivery_object(item, expected_kind="selected-output", notes_max_characters=1_000_000) for item in copy.deepcopy(selected_outputs)]
    revocations = [validate_delivery_object(item, expected_kind="authority-observation", notes_max_characters=1_000_000) for item in copy.deepcopy(revocation_observations)]
    if c["initial_authorization_intent_digest"] != canonical_digest(i) and i["predecessor_intent_id"] is None: return {"matched": False, "scope_id": None, "reason_code": "contract_mismatch"}
    now = _time(at_time)
    if now < _time(i["issued_at"]) or (i["expires_at"] is not None and now > _time(i["expires_at"])): return {"matched": False, "scope_id": None, "reason_code": "intent_expired"}
    if any(item["authority_kind"] == "intent_revocation" and item["revocation_subject"] == {"intent_id": i["id"], "revocation_key": i["revocation_key"]} for item in revocations): return {"matched": False, "scope_id": None, "reason_code": "intent_revoked"}
    for declared in i["scopes"]:
        slot_ref = declared["target"]["output_ref"]
        if slot_ref["kind"] == "slot" and r["target"]["output_ref"] != slot_ref:
            contract_slots = [stage["target_ref"] for stage in c["stages"] if stage["target_ref"].get("kind") == "slot" and stage["target_ref"]["slot_id"] == slot_ref["slot_id"]]
            bound = [item for item in selections if item["slot_id"] == slot_ref["slot_id"]]
            if not contract_slots or len(bound) != 1 or any(item != contract_slots[0] for item in contract_slots[1:]):
                return {"matched": False, "scope_id": None, "reason_code": "slot_constraint_mismatch"}
            constraints, selected = contract_slots[0]["constraints"], bound[0]
            expected = (canonical_digest(c), contract_slots[0]["subject_kind"], constraints["repository_id"], constraints["branch"], constraints["base"])
            actual = (selected["contract_digest"], selected["subject_kind"], selected["repository_id"], selected["branch"], selected["base"])
            if actual != expected:
                return {"matched": False, "scope_id": None, "reason_code": "slot_constraint_mismatch"}
        reason = _scope_mismatch(declared, r, selections)
        if reason is None: return {"matched": True, "scope_id": declared["id"], "reason_code": "matched"}
    reason = _scope_mismatch(i["scopes"][0], r, selections)
    return {"matched": False, "scope_id": None, "reason_code": reason or "scope_tuple_required"}


def _merge_by_id(existing: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = {item["id"]: copy.deepcopy(item) for item in existing}
    for item in candidates:
        if item["id"] in result and canonical_bytes(result[item["id"]]) != canonical_bytes(item): _reject()
        result[item["id"]] = copy.deepcopy(item)
    return sorted(result.values(), key=lambda item: item["id"])


def _stage_observation_matches(contract: dict[str, Any], delivery: dict[str, Any], stage: dict[str, Any], item: dict[str, Any]) -> bool:
    if item["observation_kind"] != _STAGE_ACTIONS[stage["kind"]][2]: return False
    subject = item["subject"]
    selected = delivery["selected_outputs"]
    heads = {entry["subject_value"] for entry in selected}
    if stage["kind"] == "select_reviewed_output": return subject.get("selected_output") in selected
    if stage["kind"] == "publish_branch":
        return set(subject) == {"repository_id", "branch", "selected_head"} and subject["repository_id"] == contract["project"]["repository_id"] and subject["selected_head"] in heads
    if stage["kind"] in {"open_pr", "merge_pr"}:
        required = {"provider_repository_id", "pr_number", "pr_url", "expected_head", "base"}
        if stage["kind"] == "merge_pr": required |= {"merge_sha", "merged"}
        if set(subject) != required or type(subject["pr_number"]) is not int or subject["pr_number"] < 1: return False
        prs = {scope["target"]["pr_ref"]["value"] for intent in delivery["authorization_intents"] for scope in intent["scopes"] if scope["target"]["pr_ref"]["kind"] == "literal"}
        valid = subject["provider_repository_id"] == contract["project"]["repository_id"] and str(subject["pr_number"]) in prs and subject["expected_head"] in heads
        valid = valid and any(ref.get("kind") == "slot" and ref["constraints"]["base"] == subject["base"] for ref in [stage["target_ref"]])
        if stage["kind"] == "merge_pr":
            valid = valid and subject["merged"] is True and any(obs["observation_kind"] == "pr_opened" and obs["subject"].get("pr_number") == subject["pr_number"] and obs["subject"].get("expected_head") == subject["expected_head"] and obs["subject"].get("base") == subject["base"] for obs in delivery["delivery_observations"])
        return valid
    return True


def reduce_delivery(contract: object, delivery: object, *, evaluation: object) -> dict[str, object]:
    c = validate_delivery_object(contract, expected_kind="delivery-contract", notes_max_characters=1_000_000)
    d = validate_delivery_object(delivery, expected_kind="delivery", notes_max_characters=1_000_000)
    if canonical_digest(c) != d["contract_digest"]: _reject()
    e = copy.deepcopy(evaluation)
    _object(e, _members("at_time custody current_launch requested_scope source_kind authorization_intents authority_observations reevaluation_evidence delivery_observations"))
    _utc(e["at_time"], "evaluation time")
    if e["source_kind"] not in {"control", "direct", "checkpoint", "summary"}: _reject()
    if e["custody"] is None:
        if e["current_launch"] is not None: _reject()
    else:
        validate_custody_ref(e["custody"], issue=c["issue"]); _boolean(e["current_launch"], "current launch")
    if e["requested_scope"] is not None: _scope(e["requested_scope"])
    if e["source_kind"] in {"checkpoint", "summary"} and e["authorization_intents"]: _reject()
    for name in ("authorization_intents", "authority_observations", "reevaluation_evidence", "delivery_observations"):
        _sorted_unique(e[name], f"evaluation {name}", key=lambda item: item.get("id", ""))
    for item in e["authorization_intents"]: _intent(item)
    for item in e["authority_observations"]:
        _authority(item)
        if item["contract_digest"] != d["contract_digest"]: _reject()
        if e["source_kind"] in {"checkpoint", "summary"} and item["authority_kind"] != "intent_revocation" and (e["custody"] is None or item["launch_id"] != e["custody"]["action_id"]): _reject()
    for item in e["reevaluation_evidence"]:
        _reevaluation(item)
        if item["contract_digest"] != d["contract_digest"]: _reject()
    for item in e["delivery_observations"]:
        _delivery_observation(item, 1_000_000)
        if item["contract_digest"] != d["contract_digest"] or item["project"] != c["project"]: _reject()
    next_delivery = copy.deepcopy(d)
    next_delivery["authorization_intents"] = _merge_by_id(d["authorization_intents"], e["authorization_intents"])
    next_delivery["authorization_chain_digest"] = canonical_digest({"intent_ids": [item["id"] for item in next_delivery["authorization_intents"]]})
    next_delivery["authority_observations"] = _merge_by_id(d["authority_observations"], e["authority_observations"])
    next_delivery["reevaluation_evidence"] = _merge_by_id(d["reevaluation_evidence"], e["reevaluation_evidence"])
    next_delivery["delivery_observations"] = _merge_by_id(d["delivery_observations"], e["delivery_observations"])
    for item in next_delivery["delivery_observations"]:
        if item["observation_kind"] == "selected_output":
            selected = item["subject"]["selected_output"]
            next_delivery["selected_outputs"] = _merge_by_id(next_delivery["selected_outputs"], [selected])
    stage_observation: dict[str, dict[str, Any]] = {}
    for stage in c["stages"]:
        expected = _STAGE_ACTIONS[stage["kind"]][2]
        matches = [item for item in next_delivery["delivery_observations"] if item["observation_kind"] == expected and _stage_observation_matches(c, next_delivery, stage, item)]
        if len({canonical_bytes(item["subject"]) for item in matches}) > 1: _reject()
        if matches: stage_observation[stage["id"]] = max(matches, key=lambda item: (item["observed_at"], item["id"]))
    facts = []
    for stage in c["stages"]:
        observed = stage_observation.get(stage["id"])
        state = "observed" if observed else "pending"
        facts.append({"schema_version": 1, "kind": "delivery-stage-fact", "id": "", "contract_digest": d["contract_digest"], "stage_id": stage["id"], "state": state, "observation_id": observed["id"] if observed else None})
        facts[-1]["id"] = canonical_digest(facts[-1], omit_derived="id")
    next_delivery["stage_facts"] = facts
    post = {name: {"state": "pending", "observation_id": None} for name in _POSTCONDITIONS}
    for name in _POSTCONDITIONS:
        if c["deliverable"]["obligations"][name] == "not_applicable": post[name] = {"state": "not_applicable", "observation_id": None}
        else:
            if name == "pr_merged":
                matches = [stage_observation[stage["id"]] for stage in c["stages"] if stage["kind"] == "merge_pr" and stage["id"] in stage_observation]
            else:
                matches = [item for item in next_delivery["delivery_observations"] if item["observation_kind"] == name]
            if len({canonical_bytes(item["subject"]) for item in matches}) > 1: _reject()
            if matches:
                chosen = max(matches, key=lambda item: (item["observed_at"], item["id"]))
                post[name] = {"state": "observed", "observation_id": chosen["id"]}
    next_delivery["postconditions"] = post
    observed_ids = {fact["stage_id"] for fact in facts if fact["state"] != "pending"}
    pending = [stage["id"] for stage in c["stages"] if stage["id"] not in observed_ids]
    next_stage = None
    requirements: list[dict[str, Any]] = []
    for stage in c["stages"]:
        if stage["id"] in observed_ids: continue
        missing = [dep for dep in stage["depends_on"] if dep not in observed_ids]
        if missing:
            requirements = [{"kind": "observation", "subject_id": dep, "reason_code": "dependency_observation_required", "detail_pointer": None} for dep in missing]
        else: next_stage = stage["id"]
        break
    blocking = None
    authority_evaluation = None
    requested = e["requested_scope"]
    if requested is not None:
        if e["custody"] is None or e["current_launch"] is not True:
            requirements = [{"kind": "observation", "subject_id": requested["id"], "reason_code": "current_launch_required", "detail_pointer": None}]
        else:
            intent_matches = [(item, match_scope(c, item, requested, selected_outputs=next_delivery["selected_outputs"], at_time=e["at_time"], revocation_observations=next_delivery["authority_observations"])) for item in next_delivery["authorization_intents"]]
            covering = [(item, match) for item, match in intent_matches if match["matched"]]
            if not covering:
                requirements = [{"kind": "scope_tuple", "subject_id": requested["id"], "reason_code": "authorization_intent_required", "detail_pointer": None}]
                blocking = {"blocked_on": "human_gate", "reason_code": "authorization_intent_required", "subject_id": requested["id"]}
                covering = []
            scope_id = covering[-1][1]["scope_id"] if covering else requested["id"]
            rejections = [item for item in next_delivery["authority_observations"] if item["scope_id"] == scope_id and item["verdict"] == "rejected"]
            allowed = [item for item in next_delivery["authority_observations"] if item["scope_id"] == scope_id and item["verdict"] == "allowed"]
            if covering and rejections:
                rejection = sorted(rejections, key=lambda item: item["observed_at"])[-1]
                fresh_allowed = [item for item in allowed if item["launch_id"] == e["custody"]["action_id"] and any(item["evaluation_use_key"] == use["use_key"] and use["rejected_observation_id"] == rejection["id"] and use["contract_digest"] == item["contract_digest"] and use["scope_id"] == item["scope_id"] and use["custody"] == e["custody"] and _time(item["observed_at"]) >= _time(use["consumed_at"]) for use in next_delivery["authority_evaluation_consumptions"])]
                if fresh_allowed and any(_time(item["observed_at"]) >= max(_time(allow["observed_at"]) for allow in fresh_allowed) for item in rejections): fresh_allowed = []
                if fresh_allowed:
                    rejection = None
                basis = None
                for item in e["authorization_intents"] if rejection is not None else []:
                    match = match_scope(c, item, requested, selected_outputs=next_delivery["selected_outputs"], at_time=e["at_time"], revocation_observations=next_delivery["authority_observations"])
                    if match["matched"] and _time(item["issued_at"]) > _time(rejection["observed_at"]): basis = {"kind": "successor_intent", "id": item["id"]}; break
                if basis is None and rejection is not None:
                    for item in e["reevaluation_evidence"]:
                        if item["rejected_observation_id"] == rejection["id"] and item["scope_id"] == scope_id: basis = {"kind": "reevaluation_evidence", "id": item["id"]}; break
                if rejection is None:
                    pass
                elif basis is None:
                    blocking = {"blocked_on": "human_gate", "reason_code": "host_rejected", "subject_id": rejection["id"]}
                else:
                    use_key = canonical_digest({"contract_digest": d["contract_digest"], "scope_id": scope_id, "rejected_observation_id": rejection["id"], "basis": basis})
                    if any(item["use_key"] == use_key for item in next_delivery["authority_evaluation_consumptions"]):
                        blocking = {"blocked_on": "human_gate", "reason_code": "reevaluation_consumed", "subject_id": use_key}
                    else:
                        consumption = {"schema_version": 1, "kind": "authority-evaluation-consumption", "id": "", "use_key": use_key, "contract_digest": d["contract_digest"], "scope_id": scope_id, "rejected_observation_id": rejection["id"], "basis": basis, "custody": copy.deepcopy(e["custody"]), "consumed_at": e["at_time"]}
                        consumption["id"] = canonical_digest(consumption, omit_derived="id")
                        next_delivery["authority_evaluation_consumptions"] = sorted(next_delivery["authority_evaluation_consumptions"] + [consumption], key=lambda item: item["id"])
                        authority_evaluation = {"kind": "native_authority_evaluation", "contract_digest": d["contract_digest"], "scope_id": scope_id, "custody": copy.deepcopy(e["custody"]), "rejected_observation_id": rejection["id"], "basis_kind": basis["kind"], "basis_id": basis["id"], "use_key": use_key}
            elif covering and allowed and not any(item["launch_id"] == e["custody"]["action_id"] for item in allowed):
                requirements = [{"kind": "observation", "subject_id": scope_id, "reason_code": "authority_launch_mismatch", "detail_pointer": None}]
            elif covering and not allowed:
                requirements = [{"kind": "observation", "subject_id": scope_id, "reason_code": "native_evaluation_required", "detail_pointer": None}]
    completion = "delivery_complete" if all(item["state"] in {"observed", "not_applicable"} for item in post.values()) else "pending"
    result = {"next_delivery": next_delivery, "pending_stage_ids": pending, "next_stage_id": next_stage,
              "requirements": sorted(requirements, key=lambda item: (item["kind"], item["subject_id"], item["reason_code"])),
              "completion_state": completion, "blocking": blocking, "authority_evaluation": authority_evaluation}
    validate_delivery_object(next_delivery, expected_kind="delivery", notes_max_characters=1_000_000)
    return result
