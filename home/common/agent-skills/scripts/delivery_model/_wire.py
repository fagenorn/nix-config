"""Strict workflow and delivery transport envelopes."""
from __future__ import annotations

import copy
from typing import Any

from ._canonical import (canonical_bytes, canonical_digest, _boolean, _digest,
    _integer, _members, _object, _reject, _sorted_unique, _string, _utc)
from ._objects import (_POSTCONDITIONS, _STAGE_ACTIONS, _authority, _consumption,
    _contract, _custody_issue, _delivery_observation, _intent, _reevaluation,
    _postcondition_observation_matches, _scope, _selected, _selection_for_stage,
    _stage_fact, _stage_observation_matches, validate_custody_ref)

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


def _local_requirements(values: list[Any], pending: list[str],
                        contract: dict[str, Any] | None = None) -> None:
    if pending:
        stage_requirement = [{"kind": "scope_tuple", "subject_id": pending[0],
                              "reason_code": "scope_tuple_required",
                              "detail_pointer": None}]
        if values == stage_requirement: return
        dependency_requirements = bool(values) and all(
            item["kind"] == "observation"
            and item["reason_code"] == "dependency_observation_required"
            and item["subject_id"] in pending and item["detail_pointer"] is None
            for item in values)
        if not dependency_requirements: _reject()
        if contract is not None:
            stage = next(item for item in contract["stages"] if item["id"] == pending[0])
            missing = sorted(item for item in stage["depends_on"] if item in pending)
            if [item["subject_id"] for item in values] != missing: _reject()
        return
    if any(item["kind"] != "observation"
           or item["reason_code"] != "postcondition_observation_required"
           or item["subject_id"] not in _POSTCONDITIONS
           or item["detail_pointer"] is not None for item in values): _reject()


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
    scope = value["requested_scope"]
    if scope is None:
        if value["authority_evaluation"] is not None: _reject()
        _local_requirements(value["requirements"], value["pending_stage_ids"], contract)
    else:
        _scope(scope)
        if not value["pending_stage_ids"]: _reject()
        target = scope["target"]
        if target["issue"] != issue or (target["project_id"], target["provider"], target["repository_id"], target["repository_slug"]) != tuple(contract["project"][key] for key in ("project_id", "provider", "repository_id", "repository_slug")): _reject()
    return contract


def _owner_action(value: Any, notes_max: int, *, control: bool = False) -> dict[str, Any]:
    base = {"id", "kind", "issue", "attempt", "owner", "worktree", "handoff_path", "deadline_at"} if control else {"interface_version", "kind", "ledger_repo_root", "run_id", "issue", "attempt", "owner", "action_id", "launch_kind", "worktree", "handoff_path", "deadline_at"}
    value = _object(value, base | {"custody", "contract", "contract_digest", "pending_stage_ids", "requirements", "authority_evaluation", "requested_scope"}, "owner action")
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
    value = _object(value, _members("interface_version kind ledger_repo_root run_id issue source_attempt owner custody worktree contract contract_digest pending_stage_ids deadline_at requirements authority_evaluation requested_scope")); _v2(value)
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
    _object(value, common | {"next_action", "requirements", "authority_evaluation", "requested_scope", "state", "blocked_on"}, "checkpoint response"); issue, custody = _response_common(value)
    if value["state"] not in {"active", "suspended"} or value["blocked_on"] not in {None, "human_gate", "external", "transport"}: _reject()
    _requirements(value["requirements"], sorted_values=True); _evaluation(value["authority_evaluation"], issue=issue, contract_digest=value["contract_digest"], custody=custody)
    if value["requested_scope"] is None:
        if value["authority_evaluation"] is not None: _reject()
        _local_requirements(value["requirements"], value["pending_stage_ids"])
    else:
        _scope(value["requested_scope"])
        if not value["pending_stage_ids"]: _reject()
        if value["requested_scope"]["target"]["issue"] != issue: _reject()
    if value["state"] == "active" and value["blocked_on"] is not None: _reject()
    if value["next_action"] is not None:
        if not isinstance(value["next_action"], dict): _reject()
        (_owner_action if value["next_action"].get("kind") == "owner" else _remainder)(value["next_action"], notes_max)
        if value["next_action"]["requested_scope"] != value["requested_scope"]: _reject()
        nested = value["next_action"]
        for name in ("issue", "custody", "contract_digest", "pending_stage_ids", "requirements", "authority_evaluation"):
            if nested[name] != value[name]: _reject()
        if nested["ledger_repo_root"] != value["ledger_repo_root"] or nested["run_id"] != value["run_id"] or nested["owner"] != value["owner"]: _reject()
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
    issues = set(); missing_contracts = set()
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
        if item["contract_digest"] is None:
            expected = {"kind": "delivery_contract", "subject_id": str(issue),
                        "reason_code": "delivery_contract_required", "detail_pointer": None}
            if item["custody"] is not None or item["pending_stage_ids"] or item["requirements"] != [expected]: _reject()
            missing_contracts.add(issue)
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
    if any(action.get("issue") in missing_contracts for action in value["actions"]): _reject()
    return value


def _workflow_response(value: Any, notes_max: int) -> dict[str, Any]:
    if not isinstance(value, dict): _reject()
    if set(value) == {"action_id", "current", "current_action_id", "reason"}:
        _string(value["action_id"], "action id"); _boolean(value["current"], "current")
        if value["current_action_id"] is not None: _string(value["current_action_id"], "current action")
        if value["reason"] not in {"unknown_run", "unknown_issue", "unknown_attempt", "superseded_attempt", "inactive_attempt", "superseded_launch", "current"}: _reject()
        if value["current"] != (value["reason"] == "current") or (value["current"] and value["current_action_id"] != value["action_id"]): _reject()
        if value["reason"] in {"unknown_run", "unknown_issue"} and value["current_action_id"] is not None: _reject()
        if value["reason"] == "inactive_attempt" and value["current_action_id"] not in {None, value["action_id"]}: _reject()
        if value["reason"] in {"unknown_attempt", "superseded_attempt", "superseded_launch"} and value["current_action_id"] == value["action_id"]: _reject()
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
    keys = {"interface_version", "issue", "custody", "contract_digest", "delivery_observations", "authority_observations", "reevaluation_evidence", "requested_scope", "detail_state", "report_path", "notes"}
    value = _object(value, keys, "ship checkpoint")
    if type(value["interface_version"]) is not int or value["interface_version"] != 2: _reject()
    issue = _integer(value["issue"], "checkpoint issue", minimum=1); validate_custody_ref(value["custody"], issue=issue); _digest(value["contract_digest"], "checkpoint contract")
    _report_arrays(value, ("delivery_observations", "authority_observations", "reevaluation_evidence"), notes_max); _report_detail(value); _bounded_notes(value["notes"], notes_max)
    if value["requested_scope"] is not None:
        _scope(value["requested_scope"])
        if value["requested_scope"]["target"]["issue"] != issue: _reject()
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
    keys = {"interface_version", "state", "ledger_repo_root", "run_id", "owner", "owner_worktree", "custody", "issue_number", "branch", "worktree_path", "spec_artifact", "plan_artifact", "head_sha", "review_state", "auto", "report_path", "notes", "delivery_contract", "delivery_contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observation_ids", "reevaluation_evidence_ids", "authority_evaluation_consumption_ids", "pending_stage_ids", "selected_outputs", "requested_scope"}
    value = _object(value, keys, "ship handoff")
    if type(value["interface_version"]) is not int or value["interface_version"] != 2: _reject()
    issue = _integer(value["issue_number"], "handoff issue", minimum=1); validate_custody_ref(value["custody"], issue=issue)
    for name in ("state", "ledger_repo_root", "run_id", "owner", "owner_worktree", "branch", "worktree_path", "head_sha", "review_state"): _string(value[name], f"handoff {name}")
    _bounded_notes(value["notes"], notes_max); _boolean(value["auto"], "handoff auto")
    if value["report_path"] is not None: _string(value["report_path"], "handoff report path")
    _artifact(value["spec_artifact"], "spec artifact"); _artifact(value["plan_artifact"], "plan artifact")
    contract = _contract(value["delivery_contract"], notes_max); digest = canonical_digest(contract)
    if value["delivery_contract_digest"] != digest or contract["issue"] != issue: _reject()
    _digest(value["authorization_chain_digest"], "handoff chain")
    _sorted_unique(value["authorization_intents"], "handoff intents", key=lambda item: item.get("id", ""))
    for item in value["authorization_intents"]: _intent(item)
    _validate_intent_chain(contract, value["authorization_intents"], value["authorization_chain_digest"])
    branches = {stage["target_ref"]["constraints"]["branch"]
                for stage in contract["stages"] if stage["target_ref"].get("kind") == "slot"}
    if branches and value["branch"] not in branches: _reject()
    for name in ("authority_observation_ids", "reevaluation_evidence_ids", "authority_evaluation_consumption_ids"):
        _sorted_unique(value[name], f"handoff {name}")
        for item in value[name]: _digest(item, f"handoff {name} member")
    _pending(value["pending_stage_ids"], contract)
    if value["requested_scope"] is not None:
        _scope(value["requested_scope"])
        target, project = value["requested_scope"]["target"], contract["project"]
        if target["issue"] != issue or any(target[name] != project[name] for name in ("project_id", "provider", "repository_id", "repository_slug")): _reject()
    _sorted_unique(value["selected_outputs"], "handoff selections", key=lambda item: item.get("id", ""))
    for item in value["selected_outputs"]:
        _selected(item)
        if item["contract_digest"] != digest or not any(
                _selection_for_stage(contract, {"contract_digest": digest,
                    "selected_outputs": [item]}, stage) is not None
                for stage in contract["stages"] if stage["kind"] == "select_reviewed_output"):
            _reject()
    return value


def _validate_intent_chain(contract: dict[str, Any], intents: list[dict[str, Any]],
                           chain_digest: str) -> None:
    if not intents: _reject()
    by_id = {item["id"]: item for item in intents}
    roots = [item for item in intents if item["predecessor_intent_id"] is None]
    if len(roots) != 1 or roots[0]["id"] != contract["initial_authorization_intent_id"] \
            or canonical_digest(roots[0]) != contract["initial_authorization_intent_digest"]:
        _reject()
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
    if chain_digest != canonical_digest({"intent_ids": [item["id"] for item in intents]}): _reject()
    project = contract["project"]
    for item in intents:
        for declared in item["scopes"]:
            target = declared["target"]
            if (target["project_id"], target["provider"], target["repository_id"],
                    target["repository_slug"], target["issue"]) != (
                    project["project_id"], project["provider"], project["repository_id"],
                    project["repository_slug"], contract["issue"]): _reject()


def _delivery(value: Any, notes_max: int) -> dict[str, Any]:
    keys = {"contract", "contract_digest", "authorization_intents", "authorization_chain_digest", "authority_observations", "reevaluation_evidence", "authority_evaluation_consumptions", "delivery_observations", "selected_outputs", "stage_facts", "postconditions"}
    value = _object(value, keys, "delivery")
    contract = _contract(value["contract"], notes_max); digest = canonical_digest(contract)
    if value["contract_digest"] != digest: _reject()
    _sorted_unique(value["authorization_intents"], "authorization intents", key=lambda item: item.get("id", ""))
    intents = []
    for item in value["authorization_intents"]:
        _intent(item); intents.append(item)
    _validate_intent_chain(contract, intents, value["authorization_chain_digest"])
    _digest(value["authorization_chain_digest"], "intent chain digest")
    validators = (("authority_observations", _authority), ("reevaluation_evidence", _reevaluation), ("delivery_observations", lambda item: _delivery_observation(item, notes_max)), ("selected_outputs", _selected))
    bodies: dict[str, bytes] = {}
    for name, validator in validators:
        _sorted_unique(value[name], name, key=lambda item: item.get("id", ""))
        for item in value[name]:
            validator(item); body = canonical_bytes(item)
            if item["id"] in bodies and bodies[item["id"]] != body: _reject()
            bodies[item["id"]] = body
    for item in intents:
        body = canonical_bytes(item)
        if item["id"] in bodies and bodies[item["id"]] != body: _reject()
        bodies[item["id"]] = body
    scope_ids = {scope["id"] for intent in intents for scope in intent["scopes"]}
    intent_by_id = {intent["id"]: intent for intent in intents}
    intents_by_scope = {
        scope_id: [intent for intent in intents
                   if scope_id in {scope["id"] for scope in intent["scopes"]}]
        for scope_id in scope_ids
    }

    def scope_exists_at(scope_id: str, observed_at: str) -> bool:
        return any(intent["issued_at"] <= observed_at
                   for intent in intents_by_scope.get(scope_id, []))

    authority_by_id = {item["id"]: item for item in value["authority_observations"]}
    reevaluation_by_id = {item["id"]: item for item in value["reevaluation_evidence"]}
    for item in value["authority_observations"]:
        if item["contract_digest"] != digest or item["scope_id"] not in scope_ids: _reject()
        if item["authority_kind"] == "intent_revocation":
            revoked = intent_by_id.get(item["revocation_subject"]["intent_id"])
            if revoked is None or revoked["revocation_key"] != item["revocation_subject"]["revocation_key"] \
                    or item["scope_id"] not in {scope["id"] for scope in revoked["scopes"]} \
                    or item["observed_at"] < revoked["issued_at"]: _reject()
        elif not scope_exists_at(item["scope_id"], item["observed_at"]):
            _reject()
    for item in value["reevaluation_evidence"]:
        rejection = authority_by_id.get(item["rejected_observation_id"])
        if item["contract_digest"] != digest \
                or item["scope_id"] not in scope_ids \
                or rejection is None or rejection["verdict"] != "rejected" \
                or rejection["scope_id"] != item["scope_id"] \
                or item["observed_at"] < rejection["observed_at"] \
                or not scope_exists_at(item["scope_id"], item["observed_at"]): _reject()
    for item in value["delivery_observations"]:
        if item["contract_digest"] != digest or item["project"] != contract["project"]: _reject()
    for item in value["selected_outputs"]:
        if item["contract_digest"] != digest or not any(
                _selection_for_stage(contract, value, stage) is not None
                and _selection_for_stage(contract, value, stage)["id"] == item["id"]
                for stage in contract["stages"] if stage["kind"] == "select_reviewed_output"):
            _reject()
    delivery_by_id = {item["id"]: item for item in value["delivery_observations"]}
    _sorted_unique(value["authority_evaluation_consumptions"], "consumptions", key=lambda item: item.get("id", ""))
    uses = set()
    for item in value["authority_evaluation_consumptions"]:
        _consumption(item, contract["issue"])
        body = canonical_bytes(item)
        if item["id"] in bodies and bodies[item["id"]] != body: _reject()
        bodies[item["id"]] = body
        if item["use_key"] in uses: _reject()
        rejection = authority_by_id.get(item["rejected_observation_id"])
        basis = (intent_by_id if item["basis"]["kind"] == "successor_intent" else reevaluation_by_id).get(item["basis"]["id"])
        if item["contract_digest"] != digest \
                or item["scope_id"] not in scope_ids \
                or rejection is None or rejection["verdict"] != "rejected" \
                or rejection["scope_id"] != item["scope_id"] or basis is None \
                or item["consumed_at"] < rejection["observed_at"]: _reject()
        if item["basis"]["kind"] == "successor_intent" and (
                basis["predecessor_intent_id"] is None
                or item["scope_id"] not in {scope["id"] for scope in basis["scopes"]}
                or basis["issued_at"] <= rejection["observed_at"]
                or item["consumed_at"] < basis["issued_at"]): _reject()
        if item["basis"]["kind"] == "reevaluation_evidence" and (
                basis["rejected_observation_id"] != item["rejected_observation_id"]
                or basis["scope_id"] != item["scope_id"]
                or item["consumed_at"] < basis["observed_at"]): _reject()
        uses.add(item["use_key"])
    consumption_by_key = {item["use_key"]: item for item in value["authority_evaluation_consumptions"]}
    for item in value["authority_observations"]:
        if item["evaluation_use_key"] is None: continue
        consumption = consumption_by_key.get(item["evaluation_use_key"])
        if consumption is None or consumption["contract_digest"] != item["contract_digest"] \
                or consumption["scope_id"] != item["scope_id"] \
                or consumption["custody"]["action_id"] != item["launch_id"] \
                or item["observed_at"] < consumption["consumed_at"]: _reject()
    if not isinstance(value["stage_facts"], list) or [x.get("stage_id") for x in value["stage_facts"]] != [x["id"] for x in contract["stages"]]: _reject()
    stages_by_id = {item["id"]: item for item in contract["stages"]}
    for fact in value["stage_facts"]:
        _stage_fact(fact)
        if fact["contract_digest"] != digest: _reject()
        if fact["state"] == "observed":
            observed = delivery_by_id.get(fact["observation_id"])
            stage = stages_by_id[fact["stage_id"]]
            if observed is None or observed["observation_kind"] != _STAGE_ACTIONS[stage["kind"]][2] \
                    or not _stage_observation_matches(contract, value, stage, observed): _reject()
    postconditions = _object(value["postconditions"], set(_POSTCONDITIONS), "postconditions")
    for key, state in postconditions.items():
        state = _object(state, _members("state observation_id"), f"postcondition {key}")
        if state["state"] not in {"pending", "observed", "not_applicable"}: _reject()
        if (state["state"] == "observed") != (state["observation_id"] is not None): _reject()
        if state["state"] == "observed":
            observed = delivery_by_id.get(state["observation_id"])
            if observed is None or observed["observation_kind"] != key: _reject()
            if key == "pr_merged":
                if not any(stage["kind"] == "merge_pr" and _stage_observation_matches(
                        contract, value, stage, observed) for stage in contract["stages"]): _reject()
            elif not _postcondition_observation_matches(contract, value, key, observed): _reject()
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
