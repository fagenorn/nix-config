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
_SET_ARRAYS = {
    "authorization_intents", "authority_observations", "reevaluation_evidence",
    "authority_evaluation_consumptions", "delivery_observations", "selected_outputs",
    "review_evidence_ids", "acceptance_evidence_ids", "test_evidence_ids",
}


class DeliveryModelError(ValueError):
    """A delivery object is structurally or semantically invalid."""


def canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes:
    candidate = copy.deepcopy(value)
    if omit_derived is not None:
        if not isinstance(candidate, dict) or omit_derived not in candidate:
            raise DeliveryModelError(f"missing derived member: {omit_derived}")
        del candidate[omit_derived]
    try:
        return (json.dumps(candidate, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeliveryModelError("value is not canonical JSON") from error


def canonical_digest(value: object, *, omit_derived: str | None = None) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, omit_derived=omit_derived)).hexdigest()


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DeliveryModelError(f"invalid {label} keys")
    return value


def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise DeliveryModelError(f"invalid {label}")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DeliveryModelError(f"invalid {label}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise DeliveryModelError(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DeliveryModelError(f"invalid {label}")
    return value


def _utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise DeliveryModelError(f"invalid {label}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise DeliveryModelError(f"invalid {label}") from error
    return value


def _derived(value: dict[str, Any], label: str, field: str = "id") -> None:
    _digest(value[field], f"{label} {field}")
    if value[field] != canonical_digest(value, omit_derived=field):
        raise DeliveryModelError(f"invalid {label} {field}")


def _sorted_unique(values: Any, label: str, *, key=lambda item: item) -> list[Any]:
    if not isinstance(values, list):
        raise DeliveryModelError(f"invalid {label}")
    keys = [key(item) for item in values]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise DeliveryModelError(f"invalid {label} order")
    return values


def _ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        raise DeliveryModelError(f"invalid {label}")
    if value["kind"] == "none":
        return _object(value, {"kind"}, label)
    if value["kind"] == "literal":
        _object(value, {"kind", "value"}, label); _string(value["value"], label)
        return value
    raise DeliveryModelError(f"invalid {label} kind")


def _data_ref(value: Any, label: str, *, allow_slot: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        raise DeliveryModelError(f"invalid {label}")
    kind = value["kind"]
    if kind == "none":
        return _object(value, {"kind"}, label)
    if kind == "literal":
        _object(value, {"kind", "digest", "classification", "audience"}, label)
        _digest(value["digest"], f"{label} digest")
    elif kind == "selected_output_slot" and allow_slot:
        _object(value, {"kind", "slot_id", "classification", "audience"}, label)
        _string(value["slot_id"], f"{label} slot")
    else:
        raise DeliveryModelError(f"invalid {label} kind")
    _string(value["classification"], f"{label} classification")
    _string(value["audience"], f"{label} audience")
    return value


def _scope(value: Any) -> dict[str, Any]:
    keys = {"schema_version", "kind", "id", "principal", "action", "effect", "target",
            "endpoint", "data", "risk", "spend"}
    value = _object(value, keys, "scope tuple")
    if value["schema_version"] != 1 or value["kind"] != "scope-tuple":
        raise DeliveryModelError("invalid scope tuple version")
    principal = _object(value["principal"], {"kind", "stable_id"}, "principal")
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
        raise DeliveryModelError("invalid spend")
    if spend["kind"] == "none": _object(spend, {"kind"}, "spend")
    elif spend["kind"] == "ceiling":
        _object(spend, {"kind", "unit", "ceiling"}, "spend"); _string(spend["unit"], "spend unit"); _integer(spend["ceiling"], "spend ceiling")
    else: raise DeliveryModelError("invalid spend kind")
    _derived(value, "scope tuple")
    return value


def _slot_ref(value: Any, label: str, *, constraints: bool = True) -> dict[str, Any]:
    keys = {"kind", "slot_id"} if not constraints else {"kind", "slot_id", "subject_kind", "constraints"}
    value = _object(value, keys, label)
    if value["kind"] != "slot": raise DeliveryModelError(f"invalid {label} kind")
    _string(value["slot_id"], f"{label} slot")
    if constraints:
        if value["subject_kind"] not in {"commit", "tree", "record", "pull_request"}: raise DeliveryModelError("invalid slot subject")
        c = _object(value["constraints"], {"project_id", "provider", "repository_id", "repository_slug", "branch", "base", "deliverable_class", "data_ref"}, "slot constraints")
        for key in ("project_id", "provider", "repository_id", "repository_slug", "branch", "base", "deliverable_class"): _string(c[key], f"constraint {key}")
        _data_ref(c["data_ref"], "constraint data")
        if c["data_ref"].get("kind") == "selected_output_slot" and c["data_ref"]["slot_id"] != value["slot_id"]: raise DeliveryModelError("slot data mismatch")
    return value


def _intent(value: Any) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "predecessor_intent_id", "source", "issued_at", "expires_at", "revocation_key", "scopes"}, "authorization intent")
    if value["schema_version"] != 1 or value["kind"] != "authorization-intent": raise DeliveryModelError("invalid intent version")
    if value["predecessor_intent_id"] is not None: _digest(value["predecessor_intent_id"], "predecessor")
    source = _object(value["source"], {"kind", "reference", "evidence_digest"}, "intent source")
    if source["kind"] not in {"explicit_user", "standing_repository", "parent_handoff"}: raise DeliveryModelError("invalid intent source")
    _string(source["reference"], "intent reference"); _digest(source["evidence_digest"], "intent evidence")
    _utc(value["issued_at"], "issued_at")
    if value["expires_at"] is not None: _utc(value["expires_at"], "expires_at")
    _string(value["revocation_key"], "revocation key")
    _sorted_unique(value["scopes"], "intent scopes", key=lambda item: item.get("id", ""))
    if not value["scopes"]: raise DeliveryModelError("empty intent scopes")
    for item in value["scopes"]: _scope(item)
    _derived(value, "authorization intent")
    return value


def _selected(value: Any) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "contract_digest", "slot_id", "subject_kind", "subject_value", "data_identity_digest", "repository_id", "branch", "base", "evidence_digest", "review_evidence_ids"}, "selected output")
    if value["schema_version"] != 1 or value["kind"] != "selected-output": raise DeliveryModelError("invalid selected output")
    for key in ("contract_digest", "data_identity_digest", "evidence_digest"): _digest(value[key], key)
    for key in ("slot_id", "subject_kind", "subject_value", "repository_id", "branch", "base"): _string(value[key], key)
    _sorted_unique(value["review_evidence_ids"], "review evidence")
    for item in value["review_evidence_ids"]: _string(item, "review evidence id")
    _derived(value, "selected output")
    return value


def _contract(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "project", "issue", "deliverable", "stages", "initial_authorization_intent_id", "initial_authorization_intent_digest", "provenance"}, "delivery contract")
    if value["schema_version"] != 1 or value["kind"] != "delivery-contract": raise DeliveryModelError("invalid contract")
    project = _object(value["project"], {"project_id", "provider", "repository_id", "repository_slug"}, "project")
    for item in project.values(): _string(item, "project value")
    _integer(value["issue"], "contract issue", minimum=1)
    delivery = _object(value["deliverable"], {"id", "summary", "obligations"}, "deliverable")
    _string(delivery["id"], "deliverable id"); _string(delivery["summary"], "summary")
    if len(delivery["summary"]) > notes_max: raise DeliveryModelError("summary too long")
    obligations = _object(delivery["obligations"], set(_POSTCONDITIONS), "obligations")
    if any(item not in {"required", "not_applicable"} for item in obligations.values()): raise DeliveryModelError("invalid obligation")
    if not isinstance(value["stages"], list) or not value["stages"]: raise DeliveryModelError("invalid stages")
    ids = []
    for stage in value["stages"]:
        stage = _object(stage, {"id", "kind", "action", "effect", "target_ref", "worktree_requirement", "depends_on", "retryable"}, "stage")
        _string(stage["id"], "stage id")
        if stage["id"] in ids: raise DeliveryModelError("duplicate stage")
        if stage["kind"] not in _STAGE_ACTIONS: raise DeliveryModelError("invalid stage kind")
        action, effect, _ = _STAGE_ACTIONS[stage["kind"]]
        if (stage["action"], stage["effect"]) != (action, effect): raise DeliveryModelError("stage action mismatch")
        if stage["target_ref"].get("kind") == "slot": _slot_ref(stage["target_ref"], "target ref")
        else: _ref(stage["target_ref"], "target ref")
        if stage["worktree_requirement"] not in {"matching_required", "cleanup_target", "not_required"}: raise DeliveryModelError("invalid worktree requirement")
        _sorted_unique(stage["depends_on"], "dependencies")
        if any(dep not in ids for dep in stage["depends_on"]): raise DeliveryModelError("forward dependency")
        _boolean(stage["retryable"], "retryable"); ids.append(stage["id"])
    _digest(value["initial_authorization_intent_id"], "initial intent id"); _digest(value["initial_authorization_intent_digest"], "initial intent digest")
    provenance = _object(value["provenance"], {"kind", "reference", "digest", "created_at"}, "provenance")
    _string(provenance["kind"], "provenance kind"); _string(provenance["reference"], "provenance reference"); _digest(provenance["digest"], "provenance digest"); _utc(provenance["created_at"], "provenance time")
    return value


def validate_custody_ref(value: object, *, issue: int) -> dict[str, object]:
    candidate = copy.deepcopy(value)
    _integer(issue, "custody issue", minimum=1)
    if not isinstance(candidate, dict) or candidate.get("kind") not in {"implementation", "remainder"}: raise DeliveryModelError("invalid custody")
    if candidate["kind"] == "implementation":
        _object(candidate, {"kind", "attempt", "launch", "action_id"}, "implementation custody")
        ordinal = _integer(candidate["attempt"], "attempt", minimum=1); expected = f"{issue}:{ordinal}:{_integer(candidate['launch'], 'launch', minimum=1)}"
    else:
        _object(candidate, {"kind", "remainder", "launch", "action_id"}, "remainder custody")
        ordinal = _integer(candidate["remainder"], "remainder", minimum=1); expected = f"{issue}:r{ordinal}:{_integer(candidate['launch'], 'launch', minimum=1)}"
    if candidate["action_id"] != expected: raise DeliveryModelError("custody action mismatch")
    return candidate


def _custody_issue(value: Any) -> int:
    if not isinstance(value, dict) or not isinstance(value.get("action_id"), str):
        raise DeliveryModelError("invalid custody")
    prefix = value["action_id"].split(":", 1)[0]
    if not prefix.isdigit() or prefix.startswith("0"):
        raise DeliveryModelError("invalid custody issue")
    return _integer(int(prefix), "custody issue", minimum=1)


def _authority(value: Any) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "contract_digest", "scope_id", "launch_id", "authority_kind", "verdict", "reason_code", "observed_at", "evidence_digest", "opaque_host_reference", "revocation_subject"}, "authority observation")
    if value["schema_version"] != 1 or value["kind"] != "authority-observation": raise DeliveryModelError("invalid authority observation")
    _digest(value["contract_digest"], "authority contract"); _digest(value["scope_id"], "authority scope")
    if value["authority_kind"] not in {"intent_revocation", "native_guard", "host", "provider"}: raise DeliveryModelError("invalid authority kind")
    if value["verdict"] not in {"allowed", "rejected", "unknown", "revoked"}: raise DeliveryModelError("invalid authority verdict")
    if value["authority_kind"] == "intent_revocation":
        if value["launch_id"] is not None or value["verdict"] != "revoked": raise DeliveryModelError("invalid revocation launch")
        subject = _object(value["revocation_subject"], {"intent_id", "revocation_key"}, "revocation subject"); _digest(subject["intent_id"], "revoked intent"); _string(subject["revocation_key"], "revocation key")
    else:
        _string(value["launch_id"], "authority launch")
        if value["revocation_subject"] is not None: raise DeliveryModelError("unexpected revocation subject")
    _string(value["reason_code"], "authority reason"); _utc(value["observed_at"], "authority time"); _digest(value["evidence_digest"], "authority evidence")
    if value["opaque_host_reference"] is not None: _string(value["opaque_host_reference"], "host reference")
    _derived(value, "authority observation"); return value


def _reevaluation(value: Any) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "contract_digest", "scope_id", "rejected_observation_id", "source_kind", "reason_code", "observed_at", "evidence_digest"}, "reevaluation evidence")
    if value["schema_version"] != 1 or value["kind"] != "reevaluation-evidence" or value["source_kind"] not in {"host", "provider"}: raise DeliveryModelError("invalid reevaluation")
    for key in ("contract_digest", "scope_id", "rejected_observation_id", "evidence_digest"): _digest(value[key], key)
    _string(value["reason_code"], "reevaluation reason"); _utc(value["observed_at"], "reevaluation time"); _derived(value, "reevaluation evidence"); return value


def _consumption(value: Any, issue: int) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "use_key", "contract_digest", "scope_id", "rejected_observation_id", "basis", "custody", "consumed_at"}, "evaluation consumption")
    if value["schema_version"] != 1 or value["kind"] != "authority-evaluation-consumption": raise DeliveryModelError("invalid consumption")
    basis = _object(value["basis"], {"kind", "id"}, "consumption basis")
    if basis["kind"] not in {"successor_intent", "reevaluation_evidence"}: raise DeliveryModelError("invalid consumption basis")
    for key in ("id", "contract_digest", "scope_id", "rejected_observation_id"): _digest(value[key], key)
    validate_custody_ref(value["custody"], issue=issue); _utc(value["consumed_at"], "consumed_at")
    expected = canonical_digest({"contract_digest": value["contract_digest"], "scope_id": value["scope_id"], "rejected_observation_id": value["rejected_observation_id"], "basis": basis})
    if value["use_key"] != expected: raise DeliveryModelError("invalid use key")
    _derived(value, "evaluation consumption"); return value


def _stage_fact(value: Any) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "contract_digest", "stage_id", "state", "observation_id"}, "stage fact")
    if value["schema_version"] != 1 or value["kind"] != "delivery-stage-fact": raise DeliveryModelError("invalid stage fact")
    _digest(value["contract_digest"], "fact contract"); _string(value["stage_id"], "fact stage")
    if value["state"] not in {"pending", "observed", "not_applicable"}: raise DeliveryModelError("invalid fact state")
    if (value["state"] == "observed") != (value["observation_id"] is not None): raise DeliveryModelError("fact observation mismatch")
    if value["observation_id"] is not None: _digest(value["observation_id"], "fact observation")
    _derived(value, "stage fact"); return value


def _delivery_observation(value: Any, notes_max: int) -> dict[str, Any]:
    value = _object(value, {"schema_version", "kind", "id", "contract_digest", "project", "observation_kind", "subject", "source", "observed_at", "evidence_digest"}, "delivery observation")
    if value["schema_version"] != 1 or value["kind"] != "delivery-observation": raise DeliveryModelError("invalid delivery observation")
    _digest(value["contract_digest"], "observation contract")
    project = _object(value["project"], {"project_id", "provider", "repository_id", "repository_slug"}, "observation project")
    for item in project.values(): _string(item, "observation project value")
    if value["observation_kind"] not in {item[2] for item in _STAGE_ACTIONS.values()} | set(_POSTCONDITIONS): raise DeliveryModelError("invalid observation kind")
    if not isinstance(value["subject"], dict) or not value["subject"]: raise DeliveryModelError("invalid observation subject")
    source = _object(value["source"], {"kind", "reference"}, "observation source")
    if source["kind"] not in {"provider", "tracker", "repository", "filesystem", "human_completion"}: raise DeliveryModelError("invalid observation source")
    _string(source["reference"], "observation reference"); _utc(value["observed_at"], "observation time"); _digest(value["evidence_digest"], "observation evidence")
    if value["observation_kind"] == "selected_output": _selected(_object(value["subject"], {"selected_output"}, "selected output subject")["selected_output"])
    _derived(value, "delivery observation"); return value


def _workflow_response(value: Any, notes_max: int) -> dict[str, Any]:
    if not isinstance(value, dict): raise DeliveryModelError("invalid workflow response")
    if set(value) == {"action_id", "current", "current_action_id", "reason"}:
        _string(value["action_id"], "action id"); _boolean(value["current"], "current")
        if value["current_action_id"] is not None: _string(value["current_action_id"], "current action")
        _string(value["reason"], "current reason"); return value
    if value.get("kind") == "workflow_bootstrap":
        _object(value, {"interface_version", "kind", "run_id", "requirements"}, "bootstrap response")
        if value["interface_version"] != 2: raise DeliveryModelError("invalid bootstrap version")
        _string(value["run_id"], "run id")
        _sorted_unique(value["requirements"], "bootstrap requirements", key=lambda item: (item.get("issue", 0), item.get("custody", {}).get("action_id", "")))
        for item in value["requirements"]:
            item = _object(item, {"issue", "owner", "custody", "recorded_worktree"}, "bootstrap requirement")
            issue = _integer(item["issue"], "requirement issue", minimum=1); _string(item["owner"], "requirement owner"); validate_custody_ref(item["custody"], issue=issue); _string(item["recorded_worktree"], "recorded worktree")
        return value
    if value.get("kind") in {"delivery_checkpointed", "delivery_stalled"}:
        common = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue", "owner", "custody", "contract_digest", "accepted_observation_ids", "pending_stage_ids"}
        if value["kind"] == "delivery_checkpointed":
            _object(value, common | {"next_action", "requirements", "authority_evaluation", "state", "blocked_on"}, "checkpoint response")
            if value["state"] not in {"active", "suspended"}: raise DeliveryModelError("invalid checkpoint state")
        else:
            _object(value, common | {"state", "stalled_resumes", "result_source", "reason_code"}, "stalled response")
            if (value["state"], value["stalled_resumes"], value["result_source"], value["reason_code"]) != ("terminal_failed", 3, "stalled", "suspension_stalled_without_progress"): raise DeliveryModelError("invalid stalled response")
        issue = _integer(value["issue"], "response issue", minimum=1); validate_custody_ref(value["custody"], issue=issue); return value
    if value.get("interface_version") == 2 and isinstance(value.get("kind"), str):
        return value
    raise DeliveryModelError("unknown workflow response")


def _delivery(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"contract", "contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observations", "reevaluation_evidence", "authority_evaluation_consumptions", "delivery_observations", "selected_outputs", "stage_facts", "postconditions"}
    value = _object(value, keys, "delivery")
    contract = _contract(value["contract"], notes_max); digest = canonical_digest(contract)
    if value["contract_digest"] != digest: raise DeliveryModelError("delivery contract mismatch")
    _sorted_unique(value["authorization_intents"], "authorization intents", key=lambda item: item.get("id", ""))
    intents = []
    for item in value["authorization_intents"]:
        _intent(item); intents.append(item)
    if not intents: raise DeliveryModelError("initial intent mismatch")
    by_id = {item["id"]: item for item in intents}
    roots = [item for item in intents if item["predecessor_intent_id"] is None]
    if len(roots) != 1 or roots[0]["id"] != contract["initial_authorization_intent_id"]: raise DeliveryModelError("initial intent mismatch")
    for item in intents:
        predecessor = item["predecessor_intent_id"]
        if predecessor is not None and predecessor not in by_id: raise DeliveryModelError("broken intent chain")
    expected_chain = canonical_digest({"intent_ids": [item["id"] for item in intents]})
    if value["authorization_chain_digest"] != expected_chain: raise DeliveryModelError("intent chain digest")
    _digest(value["authorization_chain_digest"], "intent chain digest")
    validators = (("authority_observations", _authority), ("reevaluation_evidence", _reevaluation), ("delivery_observations", lambda item: _delivery_observation(item, notes_max)), ("selected_outputs", _selected))
    bodies: dict[str, bytes] = {}
    for name, validator in validators:
        _sorted_unique(value[name], name, key=lambda item: item.get("id", ""))
        for item in value[name]:
            validator(item); body = canonical_bytes(item)
            if item["id"] in bodies and bodies[item["id"]] != body: raise DeliveryModelError("conflicting observation identity")
            bodies[item["id"]] = body
    _sorted_unique(value["authority_evaluation_consumptions"], "consumptions", key=lambda item: item.get("id", ""))
    uses = set()
    for item in value["authority_evaluation_consumptions"]:
        _consumption(item, contract["issue"])
        if item["use_key"] in uses: raise DeliveryModelError("duplicate consumption use key")
        uses.add(item["use_key"])
    if not isinstance(value["stage_facts"], list) or [x.get("stage_id") for x in value["stage_facts"]] != [x["id"] for x in contract["stages"]]: raise DeliveryModelError("stage fact order")
    for fact in value["stage_facts"]: _stage_fact(fact)
    postconditions = _object(value["postconditions"], set(_POSTCONDITIONS), "postconditions")
    for key, state in postconditions.items():
        state = _object(state, {"state", "observation_id"}, f"postcondition {key}")
        if state["state"] not in {"pending", "observed", "not_applicable"}: raise DeliveryModelError("invalid postcondition")
        if (state["state"] == "observed") != (state["observation_id"] is not None): raise DeliveryModelError("postcondition observation mismatch")
    return value


def validate_delivery_object(value: object, *, expected_kind: str | None = None, notes_max_characters: int) -> dict[str, object]:
    _integer(notes_max_characters, "notes maximum", minimum=1)
    candidate = copy.deepcopy(value)
    if expected_kind == "workflow-response": _workflow_response(candidate, notes_max_characters)
    elif expected_kind == "delivery" or (expected_kind is None and isinstance(candidate, dict) and set(candidate) == {"contract", "contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observations", "reevaluation_evidence", "authority_evaluation_consumptions", "delivery_observations", "selected_outputs", "stage_facts", "postconditions"}): _delivery(candidate, notes_max_characters)
    else:
        if not isinstance(candidate, dict): raise DeliveryModelError("delivery object must be an object")
        kind = candidate.get("kind")
        if expected_kind is not None and kind != expected_kind: raise DeliveryModelError("unexpected delivery object kind")
        dispatch = {"scope-tuple": _scope, "authorization-intent": _intent, "selected-output": _selected, "delivery-contract": lambda item: _contract(item, notes_max_characters), "authority-observation": _authority, "reevaluation-evidence": _reevaluation, "authority-evaluation-consumption": lambda item: _consumption(item, _custody_issue(item["custody"])), "delivery-observation": lambda item: _delivery_observation(item, notes_max_characters), "delivery-stage-fact": _stage_fact}
        if kind not in dispatch: raise DeliveryModelError("unknown delivery object kind")
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
    if output["kind"] == "literal":
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
        if item["id"] in result and canonical_bytes(result[item["id"]]) != canonical_bytes(item): raise DeliveryModelError("conflicting candidate identity")
        result[item["id"]] = copy.deepcopy(item)
    return sorted(result.values(), key=lambda item: item["id"])


def reduce_delivery(contract: object, delivery: object, *, evaluation: object) -> dict[str, object]:
    c = validate_delivery_object(contract, expected_kind="delivery-contract", notes_max_characters=1_000_000)
    d = validate_delivery_object(delivery, expected_kind="delivery", notes_max_characters=1_000_000)
    if canonical_digest(c) != d["contract_digest"]: raise DeliveryModelError("reducer contract mismatch")
    e = copy.deepcopy(evaluation)
    _object(e, {"at_time", "custody", "current_launch", "requested_scope", "source_kind", "authorization_intents", "authority_observations", "reevaluation_evidence", "delivery_observations"}, "evaluation")
    _utc(e["at_time"], "evaluation time")
    if e["source_kind"] not in {"control", "direct", "checkpoint", "summary"}: raise DeliveryModelError("invalid evaluation source")
    if e["custody"] is None:
        if e["current_launch"] is not None: raise DeliveryModelError("current launch without custody")
    else:
        validate_custody_ref(e["custody"], issue=c["issue"]); _boolean(e["current_launch"], "current launch")
    if e["requested_scope"] is not None: _scope(e["requested_scope"])
    if e["source_kind"] in {"checkpoint", "summary"} and e["authorization_intents"]: raise DeliveryModelError("owner report cannot append intent")
    for name in ("authorization_intents", "authority_observations", "reevaluation_evidence", "delivery_observations"):
        _sorted_unique(e[name], f"evaluation {name}", key=lambda item: item.get("id", ""))
    for item in e["authorization_intents"]: _intent(item)
    for item in e["authority_observations"]:
        _authority(item)
        if item["contract_digest"] != d["contract_digest"]: raise DeliveryModelError("authority contract mismatch")
        if e["source_kind"] in {"checkpoint", "summary"} and item["authority_kind"] != "intent_revocation" and (e["custody"] is None or item["launch_id"] != e["custody"]["action_id"]): raise DeliveryModelError("owner authority launch mismatch")
    for item in e["reevaluation_evidence"]:
        _reevaluation(item)
        if item["contract_digest"] != d["contract_digest"]: raise DeliveryModelError("reevaluation contract mismatch")
    for item in e["delivery_observations"]:
        _delivery_observation(item, 1_000_000)
        if item["contract_digest"] != d["contract_digest"] or item["project"] != c["project"]: raise DeliveryModelError("delivery observation contract mismatch")
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
        matches = [item for item in next_delivery["delivery_observations"] if item["observation_kind"] == expected]
        if matches: stage_observation[stage["id"]] = matches[-1]
    facts = []
    for stage in c["stages"]:
        observed = stage_observation.get(stage["id"])
        state = "observed" if observed else "pending"
        facts.append({"schema_version": 1, "kind": "delivery-stage-fact", "id": "", "contract_digest": d["contract_digest"], "stage_id": stage["id"], "state": state, "observation_id": observed["id"] if observed else None})
        facts[-1]["id"] = canonical_digest(facts[-1], omit_derived="id")
    next_delivery["stage_facts"] = facts
    post = copy.deepcopy(d["postconditions"])
    for name in _POSTCONDITIONS:
        if c["deliverable"]["obligations"][name] == "not_applicable": post[name] = {"state": "not_applicable", "observation_id": None}
        else:
            matches = [item for item in next_delivery["delivery_observations"] if item["observation_kind"] == name]
            if matches: post[name] = {"state": "observed", "observation_id": matches[-1]["id"]}
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
            scope_id = requested["id"]
            rejections = [item for item in next_delivery["authority_observations"] if item["scope_id"] == scope_id and item["verdict"] == "rejected"]
            allowed = [item for item in next_delivery["authority_observations"] if item["scope_id"] == scope_id and item["verdict"] == "allowed"]
            if rejections:
                rejection = sorted(rejections, key=lambda item: item["observed_at"])[-1]
                basis = None
                for item in e["authorization_intents"]:
                    match = match_scope(c, item, requested, selected_outputs=next_delivery["selected_outputs"], at_time=e["at_time"], revocation_observations=next_delivery["authority_observations"])
                    if match["matched"] and _time(item["issued_at"]) > _time(rejection["observed_at"]): basis = {"kind": "successor_intent", "id": item["id"]}; break
                if basis is None:
                    for item in e["reevaluation_evidence"]:
                        if item["rejected_observation_id"] == rejection["id"] and item["scope_id"] == scope_id: basis = {"kind": "reevaluation_evidence", "id": item["id"]}; break
                if basis is None:
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
            elif allowed and not any(item["launch_id"] == e["custody"]["action_id"] for item in allowed):
                requirements = [{"kind": "observation", "subject_id": scope_id, "reason_code": "authority_launch_mismatch", "detail_pointer": None}]
            elif not allowed:
                requirements = [{"kind": "observation", "subject_id": scope_id, "reason_code": "native_evaluation_required", "detail_pointer": None}]
    completion = "delivery_complete" if all(item["state"] in {"observed", "not_applicable"} for item in post.values()) else "pending"
    result = {"next_delivery": next_delivery, "pending_stage_ids": pending, "next_stage_id": next_stage,
              "requirements": sorted(requirements, key=lambda item: (item["kind"], item["subject_id"], item["reason_code"])),
              "completion_state": completion, "blocking": blocking, "authority_evaluation": authority_evaluation}
    validate_delivery_object(next_delivery, expected_kind="delivery", notes_max_characters=1_000_000)
    return result
