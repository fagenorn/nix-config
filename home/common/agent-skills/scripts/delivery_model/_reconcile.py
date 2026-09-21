"""Pure scope matching and delivery reconciliation."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from ._canonical import (canonical_bytes, canonical_digest, _boolean, _members,
    _object, _reject, _sorted_unique, _utc)
from ._objects import (_POSTCONDITIONS, _STAGE_ACTIONS, _authority, _contract,
    _delivery_observation, _intent, _postcondition_observation_matches,
    _reevaluation, _scope, _selected, _stage_observation_matches,
    validate_custody_ref)
from ._wire import validate_delivery_object

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
    validate_delivery_object(next_delivery, expected_kind="delivery", notes_max_characters=1_000_000)
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
                matches = [item for item in next_delivery["delivery_observations"]
                           if item["observation_kind"] == name
                           and _postcondition_observation_matches(c, next_delivery, name, item)]
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
