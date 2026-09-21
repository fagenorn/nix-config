"""Closed delivery contract and evidence object grammar."""
from __future__ import annotations

import copy
from typing import Any

from ._canonical import (canonical_bytes, canonical_digest, _boolean, _data_ref,
    _derived, _digest, _integer, _members, _object, _ref, _reject, _sorted_unique,
    _string, _utc)

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


def _recovery_proof(value: Any, kind: str) -> dict[str, Any]:
    common = _members("kind source_kind reference observed_at evidence_digest")
    extra = (_members("effect_attempted classification") if kind == "effect_failure"
             else _members("absent probe_succeeded"))
    value = _object(value, common | extra, f"{kind} proof")
    if value["kind"] != kind or value["source_kind"] not in {
        "provider", "host", "tracker", "repository", "filesystem"
    }: _reject()
    _string(value["reference"], f"{kind} reference")
    _utc(value["observed_at"], f"{kind} observed_at")
    _digest(value["evidence_digest"], f"{kind} evidence")
    if kind == "effect_failure":
        if value["effect_attempted"] is not True or value["classification"] != "transient": _reject()
    elif value["absent"] is not True or value["probe_succeeded"] is not True: _reject()
    return value


def _recovery(value: Any) -> dict[str, Any]:
    value = _object(value, _members("schema_version kind id contract_digest stage_id requested_scope failure effect_absence basis"), "delivery recovery")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "delivery-recovery": _reject()
    _digest(value["contract_digest"], "recovery contract")
    _string(value["stage_id"], "recovery stage")
    scope = _scope(value["requested_scope"])
    _recovery_proof(value["failure"], "effect_failure")
    _recovery_proof(value["effect_absence"], "effect_absence")
    basis = value["basis"]
    if not isinstance(basis, dict) or "kind" not in basis: _reject()
    if basis["kind"] == "changed_relevant_evidence":
        basis = _object(basis, _members("kind scope_id source_kind reference observed_at evidence_digest"), "recovery basis")
        _digest(basis["scope_id"], "recovery basis scope")
        _recovery_proof({"kind": "effect_absence", "absent": True,
            "probe_succeeded": True, **{name: basis[name] for name in
            ("source_kind", "reference", "observed_at", "evidence_digest")}},
            "effect_absence")
        if basis["scope_id"] != scope["id"]: _reject()
    elif basis["kind"] in {"new_authorization", "human_transient_retry"}:
        basis = _object(basis, _members("kind id"), "recovery basis")
        _digest(basis["id"], "recovery basis id")
    else: _reject()
    _derived(value, "delivery recovery")
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
    value = _object(value, _members("schema_version kind id contract_digest slot_id subject_kind subject_value data_identity_digest repository_id branch base evidence_digest acceptance_evidence_ids review_evidence_ids test_evidence_ids"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "selected-output": _reject()
    for key in ("contract_digest", "data_identity_digest", "evidence_digest"): _digest(value[key], key)
    for key in ("slot_id", "subject_kind", "subject_value", "repository_id", "branch", "base"): _string(value[key], key)
    for name in ("acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids"):
        _sorted_unique(value[name], name)
        if not value[name]: _reject()
        for item in value[name]: _string(item, name)
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
    stages = {stage["id"]: stage for stage in value["stages"]}

    def precedes(stage: dict[str, Any], required_kind: str, *, slot: str | None = None,
                 stage_id: str | None = None) -> bool:
        pending = list(stage["depends_on"]); seen = set()
        while pending:
            dependency = pending.pop()
            if dependency in seen: continue
            seen.add(dependency); candidate = stages[dependency]
            if candidate["kind"] == required_kind and (stage_id is None or candidate["id"] == stage_id):
                target = candidate["target_ref"]
                if slot is None or (target.get("kind") == "slot" and target["slot_id"] == slot):
                    return True
            pending.extend(candidate["depends_on"])
        return False

    for stage in value["stages"]:
        target = stage["target_ref"]
        slot = target.get("slot_id") if target.get("kind") == "slot" else None
        if slot is not None and stage["kind"] != "select_reviewed_output" and not precedes(
                stage, "select_reviewed_output", slot=slot):
            _reject("slot use must follow selection")
        if stage["kind"] == "open_pr":
            publication = ("deliver_repository_record"
                           if target.get("subject_kind") == "record" else "publish_branch")
            if not precedes(stage, publication, slot=slot):
                _reject("PR opening must follow publication")
        if stage["kind"] == "merge_pr" and not (
                precedes(stage, "select_reviewed_output", slot=slot)
                and precedes(stage, "open_pr", slot=slot)):
            _reject("merge must follow selection and open PR")
    cleanup_kinds = {"delete_remote_branch", "remove_worktree", "delete_local_branch"}
    non_cleanup = [stage for stage in value["stages"] if stage["kind"] not in cleanup_kinds]
    if non_cleanup:
        last_effect = non_cleanup[-1]
        for stage in value["stages"]:
            if stage["kind"] in cleanup_kinds and not precedes(
                    stage, last_effect["kind"], slot=None, stage_id=last_effect["id"]):
                _reject("cleanup must follow the last declared non-cleanup effect")
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
        _object(subject, _members("repository_id selected_record_digest branch live_pr_head review_evidence_ids")); _string(subject["repository_id"], "record repository"); _digest(subject["selected_record_digest"], "record digest"); _string(subject["branch"], "record branch"); _string(subject["live_pr_head"], "record PR head"); _sorted_unique(subject["review_evidence_ids"], "record reviews")
        if not subject["review_evidence_ids"]: _reject()
        for item in subject["review_evidence_ids"]: _string(item, "record review")
    elif kind == "tracker_closed":
        _object(subject, _members("tracker_repository_id issue state close_reason observation_identity")); _integer(subject["issue"], "tracker issue", minimum=1)
        _string(subject["tracker_repository_id"], "tracker repository")
        if subject["state"] != "closed": _reject()
        if subject["close_reason"] is not None: _string(subject["close_reason"], "close reason")
        _string(subject["observation_identity"], "tracker observation identity")
    elif kind in {"remote_branch_absent", "local_branch_absent"}:
        _object(subject, _members("repository_id branch absent")); _string(subject["repository_id"], "branch repository"); _string(subject["branch"], "absent branch"); _boolean(subject["absent"], "absent")
        if not subject["absent"]: _reject()
    elif kind == "worktree_absent":
        _object(subject, _members("path recorded_worktree_identity probe_mode absent")); _string(subject["path"], "worktree path"); _string(subject["recorded_worktree_identity"], "worktree identity"); _boolean(subject["absent"], "absent")
        if subject["probe_mode"] != "no_follow" or not subject["absent"]: _reject()
    elif kind == "implementation_delivered":
        _object(subject, _members("selected_subject integration_subject presence merge_observation_id acceptance_evidence_ids review_evidence_ids test_evidence_ids"))
        for name in ("selected_subject", "integration_subject"):
            item = _object(subject[name], _members("kind value"), name)
            if item["kind"] not in {"commit", "tree", "record"}: _reject()
            _string(item["value"], f"{name} value")
        if subject["selected_subject"]["kind"] != subject["integration_subject"]["kind"]: _reject()
        presence = _object(subject["presence"], _members("kind repository_id selected_value integration_value integrated_ref succeeded"), "delivery presence")
        expected_presence = "record_presence" if subject["selected_subject"]["kind"] == "record" else "reachability"
        if presence["kind"] != expected_presence: _reject()
        for name in ("repository_id", "selected_value", "integration_value", "integrated_ref"): _string(presence[name], f"presence {name}")
        if (presence["selected_value"], presence["integration_value"]) != (subject["selected_subject"]["value"], subject["integration_subject"]["value"]): _reject()
        if _boolean(presence["succeeded"], "presence succeeded") is not True: _reject()
        if subject["merge_observation_id"] is not None: _digest(subject["merge_observation_id"], "merge observation")
        for name in ("acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids"):
            _sorted_unique(subject[name], name)
            if not subject[name]: _reject()
            for item in subject[name]: _string(item, name)
    elif kind == "cleanup_complete":
        _object(subject, _members("remote_branch_observation_ids local_branch_observation_ids worktree_observation_ids durable_detail"))
        for name in ("remote_branch_observation_ids", "local_branch_observation_ids", "worktree_observation_ids"):
            _sorted_unique(subject[name], name)
            for item in subject[name]: _digest(item, name)
        detail = _object(subject["durable_detail"], _members("detail_pointer read_evidence_digest succeeded"), "durable detail")
        _string(detail["detail_pointer"], "detail pointer"); _digest(detail["read_evidence_digest"], "detail evidence")
        if _boolean(detail["succeeded"], "detail succeeded") is not True: _reject()
    _derived(value, "delivery observation"); return value


def _selection_for_stage(contract: dict[str, Any], delivery: dict[str, Any],
                         stage: dict[str, Any]) -> dict[str, Any] | None:
    target = stage["target_ref"]
    if target.get("kind") != "slot": return None
    constraints = target["constraints"]
    matches = [item for item in delivery["selected_outputs"]
               if item["contract_digest"] == delivery["contract_digest"]
               and item["slot_id"] == target["slot_id"]
               and item["subject_kind"] == target["subject_kind"]
               and item["repository_id"] == constraints["repository_id"]
               and item["branch"] == constraints["branch"]
               and item["base"] == constraints["base"]]
    if len(matches) > 1: _reject("conflicting selected outputs")
    return matches[0] if matches else None


def _stage_scope_matches(contract: dict[str, Any], delivery: dict[str, Any],
                         stage: dict[str, Any], requested: dict[str, Any]) -> None:
    """Reject a proposed actual scope that is not this contract's ready stage."""
    _scope(requested)
    project = contract["project"]
    target = requested["target"]
    if (target["project_id"], target["provider"], target["repository_id"],
            target["repository_slug"], target["issue"]) != (
            project["project_id"], project["provider"], project["repository_id"],
            project["repository_slug"], contract["issue"]): _reject()
    if (requested["action"], requested["effect"]) != (stage["action"], stage["effect"]): _reject()
    stage_target = stage["target_ref"]
    if stage_target.get("kind") == "slot":
        constraints = stage_target["constraints"]
        if any(target[key] != constraints[key] for key in ("branch", "base")): _reject()
        declared_data = constraints["data_ref"]
        selected = _selection_for_stage(contract, delivery, stage)
        output, data = target["output_ref"], requested["data"]
        if selected is None:
            if output != {"kind": "slot", "slot_id": stage_target["slot_id"]} or data != declared_data: _reject()
        else:
            if declared_data["kind"] == "selected_output_slot":
                expected = {"kind": "literal", "digest": selected["data_identity_digest"],
                            "classification": declared_data["classification"],
                            "audience": declared_data["audience"]}
            elif declared_data["kind"] == "none":
                expected = {"kind": "none"}
            else:
                _reject()
            if not ((output == {"kind": "slot", "slot_id": stage_target["slot_id"]} and data == declared_data)
                    or (output == {"kind": "literal", "value": selected["subject_value"]} and data == expected)):
                _reject()
    else:
        literal = stage_target["value"]
        if stage["kind"] == "close_tracker":
            if str(target["issue"]) != literal: _reject()
        elif stage["kind"] in {"delete_remote_branch", "delete_local_branch"}:
            if target["branch"] != literal: _reject()
        elif stage["kind"] == "remove_worktree":
            if requested["endpoint"] != {"kind": "literal", "value": literal}: _reject()
        else: _reject()


def _pr_numbers(contract: dict[str, Any], delivery: dict[str, Any],
                stage: dict[str, Any], selected: dict[str, Any]) -> set[int]:
    values: set[int] = set()
    for intent in delivery["authorization_intents"]:
        for declared in intent["scopes"]:
            target = declared["target"]
            if declared["action"] not in {"open_pull_request", "merge_pull_request"}: continue
            if (target["project_id"], target["provider"], target["repository_id"],
                    target["repository_slug"], target["issue"], target["branch"],
                    target["base"]) != (
                    contract["project"]["project_id"], contract["project"]["provider"],
                    contract["project"]["repository_id"], contract["project"]["repository_slug"],
                    contract["issue"], selected["branch"], selected["base"]): continue
            output = target["output_ref"]
            if output not in ({"kind": "slot", "slot_id": selected["slot_id"]},
                              {"kind": "literal", "value": selected["subject_value"]}): continue
            ref = target["pr_ref"]
            if ref["kind"] == "literal" and ref["value"].isdigit(): values.add(int(ref["value"]))
    return values


def _selected_head(delivery: dict[str, Any], selected: dict[str, Any]) -> str | None:
    if selected["subject_kind"] != "record": return selected["subject_value"]
    proposals = [item["subject"] for item in delivery["delivery_observations"]
                 if item["observation_kind"] == "repository_record_proposed"
                 and item["subject"]["selected_record_digest"] == selected["subject_value"]
                 and item["subject"]["repository_id"] == selected["repository_id"]
                 and item["subject"]["branch"] == selected["branch"]]
    heads = {item["live_pr_head"] for item in proposals}
    if len(heads) > 1: _reject("conflicting record proposal heads")
    return next(iter(heads)) if heads else None


def _stage_observation_matches(contract: dict[str, Any], delivery: dict[str, Any],
                               stage: dict[str, Any], item: dict[str, Any]) -> bool:
    subject = item["subject"]; selected = _selection_for_stage(contract, delivery, stage)
    repo = contract["project"]["repository_id"]
    if stage["kind"] == "select_reviewed_output":
        candidate = subject["selected_output"]
        return selected is not None and candidate["id"] == selected["id"]
    if stage["kind"] == "deliver_repository_record":
        return selected is not None and selected["subject_kind"] == "record" \
            and subject["repository_id"] == repo \
            and subject["selected_record_digest"] == selected["subject_value"] \
            and subject["branch"] == selected["branch"] \
            and set(selected["review_evidence_ids"]) <= set(subject["review_evidence_ids"])
    if stage["kind"] == "publish_branch":
        return selected is not None and subject == {"repository_id": repo,
            "branch": selected["branch"], "selected_head": selected["subject_value"]}
    if stage["kind"] in {"open_pr", "merge_pr"}:
        expected_head = None if selected is None else _selected_head(delivery, selected)
        valid = selected is not None and subject["provider_repository_id"] == repo \
            and expected_head is not None and subject["expected_head"] == expected_head \
            and subject["base"] == selected["base"]
        numbers = set() if selected is None else _pr_numbers(contract, delivery, stage, selected)
        valid = valid and subject["pr_number"] in numbers
        if stage["kind"] == "merge_pr":
            valid = valid and subject["merged"] is True and any(
                observation["observation_kind"] == "pr_opened"
                and observation["subject"].get("pr_number") == subject["pr_number"]
                and observation["subject"].get("expected_head") == subject["expected_head"]
                and observation["subject"].get("base") == subject["base"]
                and any(open_stage["kind"] == "open_pr"
                        and _stage_observation_matches(
                            contract, delivery, open_stage, observation)
                        for open_stage in contract["stages"])
                for observation in delivery["delivery_observations"])
        return valid
    target = stage["target_ref"].get("value")
    if stage["kind"] == "close_tracker":
        return subject["tracker_repository_id"] == repo and subject["issue"] == contract["issue"] and subject["state"] == "closed"
    if stage["kind"] in {"delete_remote_branch", "delete_local_branch"}:
        return subject["repository_id"] == repo and subject["branch"] == target and subject["absent"] is True
    if stage["kind"] == "remove_worktree":
        return subject["path"] == target and subject["probe_mode"] == "no_follow" and subject["absent"] is True
    return False


def _postcondition_observation_matches(contract: dict[str, Any], delivery: dict[str, Any],
                                       kind: str, item: dict[str, Any]) -> bool:
    subject = item["subject"]
    if kind == "tracker_closed":
        return subject["tracker_repository_id"] == contract["project"]["repository_id"] \
            and subject["issue"] == contract["issue"] and subject["state"] == "closed"
    if kind == "implementation_delivered":
        selected = [candidate for candidate in delivery["selected_outputs"]
                    if candidate["contract_digest"] == delivery["contract_digest"]
                    and candidate["subject_kind"] == subject["selected_subject"]["kind"]
                    and candidate["subject_value"] == subject["selected_subject"]["value"]
                    and candidate["repository_id"] == subject["presence"]["repository_id"]]
        if len(selected) != 1: return False
        for name in ("acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids"):
            if not set(selected[0][name]) <= set(subject[name]): return False
        if selected[0]["subject_kind"] == "record" \
                and subject["integration_subject"]["value"] != selected[0]["subject_value"]:
            return False
        merge_id = subject["merge_observation_id"]
        if any(stage["kind"] == "merge_pr" for stage in contract["stages"]):
            if merge_id is None: return False
            merge = next((candidate for candidate in delivery["delivery_observations"]
                          if candidate["id"] == merge_id and candidate["observation_kind"] == "pr_merged"), None)
            if merge is None: return False
            applicable = [stage for stage in contract["stages"]
                          if stage["kind"] == "merge_pr"
                          and _stage_observation_matches(contract, delivery, stage, merge)]
            if len(applicable) != 1: return False
            if selected[0]["subject_kind"] == "record":
                if merge["subject"]["expected_head"] != _selected_head(delivery, selected[0]): return False
            elif merge["subject"]["merge_sha"] != subject["integration_subject"]["value"]: return False
        elif merge_id is not None: return False
        return subject["presence"]["succeeded"] is True
    if kind == "cleanup_complete":
        classes = {"remote_branch_observation_ids": ("delete_remote_branch", "remote_branch_absent"),
                   "local_branch_observation_ids": ("delete_local_branch", "local_branch_absent"),
                   "worktree_observation_ids": ("remove_worktree", "worktree_absent")}
        observations = {candidate["id"]: candidate for candidate in delivery["delivery_observations"]}
        for field, (stage_kind, observation_kind) in classes.items():
            stages = [stage for stage in contract["stages"] if stage["kind"] == stage_kind]
            references = subject[field]
            if bool(stages) != bool(references) or len(references) != len(stages): return False
            remaining = list(stages)
            for reference in references:
                observation = observations.get(reference)
                if observation is None or observation["observation_kind"] != observation_kind: return False
                match = next((stage for stage in remaining
                              if _stage_observation_matches(contract, delivery, stage, observation)), None)
                if match is None: return False
                remaining.remove(match)
        return subject["durable_detail"]["succeeded"] is True
    return False
