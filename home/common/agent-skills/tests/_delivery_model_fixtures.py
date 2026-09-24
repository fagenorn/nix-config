from __future__ import annotations

import copy

def seal(model, value, field="id"):
    value[field] = model.canonical_digest(value, omit_derived=field)
    return value


def custody(kind="implementation", ordinal=1, launch=1):
    if kind == "implementation":
        return {"kind": kind, "attempt": ordinal, "launch": launch,
                "action_id": f"151:{ordinal}:{launch}"}
    return {"kind": kind, "remainder": ordinal, "launch": launch,
            "action_id": f"151:r{ordinal}:{launch}"}


def suspended_remainder(delivery, *, now="2026-09-21T00:00:00Z"):
    record = {"remainder": 1, "source_attempt": 1,
        "owner": "151:r1", "worktree": "/worktree", "state": "suspended",
        "launches": [{"kind": "fresh", "owner": "151:r1",
                      "worktree": "/worktree", "at": now}],
        "deadline_at": "2026-09-21T03:00:00Z",
        "blocked_on": "external", "suspend_phase": 0, "stalled_resumes": 0,
        "result": None}
    return {"issue": 151, "attempts": [], "outcome": None,
            "delivery": copy.deepcopy(delivery), "delivery_remainders": [record]}


def direct_delivery_request(contract, facts=(), scope=None, intents=(), *,
                            new_run=False, now="2026-09-21T00:00:00Z"):
    return {"delivery_contract": contract, "authorization_intents": list(intents),
        "authority_observations": [], "reevaluation_evidence": [],
        "delivery_observations": list(facts), "requested_scope": scope,
        "recovery": None, "new_run": new_run, "now": now}


def control_delivery_request(value):
    names = ("authorization_intents", "authority_observations",
             "reevaluation_evidence", "delivery_observations")
    return {"delivery_contracts": {"151": value["delivery_contract"]},
        **{name: {"151": value[name]} for name in names},
        "requested_scopes": {"151": value["requested_scope"]},
        "recoveries": {"151": value["recovery"]}}


def issue_with_attempt(delivery, *, state="active", worktree="/worktree"):
    return {"issue": 151, "attempts": [{"attempt": 1, "state": state,
        "worktree": worktree, "launches": [{"kind": "fresh"}]}],
        "outcome": None, "delivery": copy.deepcopy(delivery),
        "delivery_remainders": []}


def next_launch(value):
    result = copy.deepcopy(value)
    result["launch"] += 1
    if result["kind"] == "implementation":
        result["action_id"] = f"151:{result['attempt']}:{result['launch']}"
    else:
        result["action_id"] = f"151:r{result['remainder']}:{result['launch']}"
    return result


def scope(model, *, audience="private", pr="17"):
    return seal(model, {
        "schema_version": 1, "kind": "scope-tuple", "id": "",
        "principal": {"kind": "agent", "stable_id": "worker-1"},
        "action": "merge_pull_request", "effect": "provider_write",
        "target": {
            "project_id": "sim-project", "provider": "github",
            "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
            "issue": 151, "branch": "feature", "base": "main",
            "pr_ref": {"kind": "literal", "value": pr},
            "output_ref": {"kind": "slot", "slot_id": "reviewed"},
        },
        "endpoint": {"kind": "literal", "value": "provider:merge"},
        "data": {"kind": "selected_output_slot", "slot_id": "reviewed",
                 "classification": "source", "audience": audience},
        "risk": "repository_write", "spend": {"kind": "none"},
    })


def intent(model, declared, *, predecessor=None, issued="2026-09-20T00:00:00Z",
           key="key-1", source="explicit_user"):
    return seal(model, {
        "schema_version": 1, "kind": "authorization-intent", "id": "",
        "predecessor_intent_id": predecessor,
        "source": {"kind": source, "reference": f"ref:{key}",
                   "evidence_digest": "sha256:" + "1" * 64},
        "issued_at": issued, "expires_at": None, "revocation_key": key,
        "scopes": [declared],
    })


def selection(model, contract_digest, *, subject_kind="commit", subject_value=None):
    if subject_value is None:
        subject_value = ("sha256:" + "a" * 64) if subject_kind == "record" else "a" * 40
    return seal(model, {
        "schema_version": 1, "kind": "selected-output", "id": "",
        "contract_digest": contract_digest, "slot_id": "reviewed",
        "subject_kind": subject_kind, "subject_value": subject_value,
        "data_identity_digest": "sha256:" + "2" * 64,
        "repository_id": "sim-repo", "branch": "feature", "base": "main",
        "evidence_digest": "sha256:" + "3" * 64,
        "acceptance_evidence_ids": ["accept-1"],
        "review_evidence_ids": ["review-1"],
        "test_evidence_ids": ["test-1"],
    })


def contract_and_delivery(model):
    declared = scope(model)
    first = intent(model, declared)
    stage_specs = [
        ("select", "select_reviewed_output", "select_output", "ledger_write"),
        ("publish", "publish_branch", "push_branch", "repository_write"),
        ("open", "open_pr", "open_pull_request", "provider_write"),
        ("merge", "merge_pr", "merge_pull_request", "provider_write"),
    ]
    target_ref = {
        "kind": "slot", "slot_id": "reviewed", "subject_kind": "commit",
        "constraints": {
            "project_id": "sim-project", "provider": "github",
            "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
            "branch": "feature", "base": "main", "deliverable_class": "source",
            "data_ref": {"kind": "selected_output_slot", "slot_id": "reviewed",
                         "classification": "source", "audience": "private"},
        },
    }
    stages = []
    for index, (stage_id, kind, action, effect) in enumerate(stage_specs):
        stages.append({
            "id": stage_id, "kind": kind, "action": action, "effect": effect,
            "target_ref": copy.deepcopy(target_ref),
            "worktree_requirement": "matching_required",
            "depends_on": [] if index == 0 else [stages[index - 1]["id"]],
            "retryable": True,
        })
    contract = {
        "schema_version": 1, "kind": "delivery-contract",
        "project": {"project_id": "sim-project", "provider": "github",
                    "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo"},
        "issue": 151,
        "deliverable": {"id": "delivery-151", "summary": "Deliver model",
                        "obligations": {"implementation_delivered": "required",
                                        "pr_merged": "required",
                                        "tracker_closed": "not_applicable",
                                        "cleanup_complete": "not_applicable"}},
        "stages": stages, "initial_authorization_intent_id": first["id"],
        "initial_authorization_intent_digest": model.canonical_digest(first),
        "provenance": {"kind": "issue", "reference": "issue:151",
                       "digest": "sha256:" + "4" * 64,
                       "created_at": "2026-09-20T00:00:00Z"},
    }
    digest = model.canonical_digest(contract)
    facts = [seal(model, {"schema_version": 1, "kind": "delivery-stage-fact", "id": "",
                               "contract_digest": digest, "stage_id": item["id"],
                               "state": "pending", "observation_id": None}) for item in stages]
    delivery = {
        "contract": contract, "contract_digest": digest,
        "authorization_intents": [first],
        "authorization_chain_digest": model.canonical_digest({"intent_ids": [first["id"]]}),
        "authority_observations": [], "reevaluation_evidence": [],
        "authority_evaluation_consumptions": [], "delivery_observations": [],
        "selected_outputs": [], "stage_facts": facts,
        "postconditions": {
            "implementation_delivered": {"state": "pending", "observation_id": None},
            "pr_merged": {"state": "pending", "observation_id": None},
            "tracker_closed": {"state": "not_applicable", "observation_id": None},
            "cleanup_complete": {"state": "not_applicable", "observation_id": None},
        },
    }
    return contract, delivery


def requested_scope(model, declared, selected):
    value = copy.deepcopy(declared)
    value["target"]["output_ref"] = {"kind": "literal", "value": selected["subject_value"]}
    value["data"] = {"kind": "literal", "digest": selected["data_identity_digest"],
                     "classification": "source", "audience": "private"}
    return seal(model, value)


def stage_scope(model, contract, stage_id):
    """Build an actual proposed tuple from the contract stage, never an intent."""
    stage = next(item for item in contract["stages"] if item["id"] == stage_id)
    value = scope(model)
    value["action"], value["effect"] = stage["action"], stage["effect"]
    target = stage["target_ref"]
    if target["kind"] == "slot":
        constraints = target["constraints"]
        for key in ("project_id", "provider", "repository_id", "repository_slug", "branch", "base"):
            value["target"][key] = constraints[key]
        value["target"]["output_ref"] = {"kind": "slot", "slot_id": target["slot_id"]}
        value["data"] = copy.deepcopy(constraints["data_ref"])
    else:
        value["target"]["output_ref"] = {"kind": "none"}
        value["data"] = {"kind": "none"}
        if stage["kind"] == "close_tracker":
            value["target"]["issue"] = int(target["value"])
        elif stage["kind"] in {"delete_remote_branch", "delete_local_branch"}:
            value["target"]["branch"] = target["value"]
        elif stage["kind"] == "remove_worktree":
            value["endpoint"] = {"kind": "literal", "value": target["value"]}
    return seal(model, value)


def contract_and_delivery_for_stage(model, stage_id):
    contract, delivery = contract_and_delivery(model)
    proposed = stage_scope(model, contract, stage_id)
    first = copy.deepcopy(delivery["authorization_intents"][0])
    if proposed["id"] not in {item["id"] for item in first["scopes"]}:
        first["scopes"].append(proposed)
    first["scopes"].sort(key=lambda item: item["id"])
    seal(model, first)
    contract["initial_authorization_intent_id"] = first["id"]
    contract["initial_authorization_intent_digest"] = model.canonical_digest(first)
    digest = model.canonical_digest(contract)
    delivery["contract"] = copy.deepcopy(contract)
    delivery["contract_digest"] = digest
    delivery["authorization_intents"] = [first]
    delivery["authorization_chain_digest"] = model.canonical_digest({"intent_ids": [first["id"]]})
    for fact in delivery["stage_facts"]:
        fact["contract_digest"] = digest
        seal(model, fact)
    return contract, delivery, proposed


def authority(model, contract, declared, launch, verdict="rejected"):
    return seal(model, {
        "schema_version": 1, "kind": "authority-observation", "id": "",
        "contract_digest": model.canonical_digest(contract), "scope_id": declared["id"],
        "launch_id": launch["action_id"], "authority_kind": "host", "verdict": verdict,
        "reason_code": "host_result", "observed_at": "2026-09-20T01:00:00Z",
        "evidence_digest": "sha256:" + "5" * 64,
        "opaque_host_reference": None, "revocation_subject": None,
        "evaluation_use_key": None,
    })


def revocation(model, contract, intent_value, *, observed="2026-09-20T02:00:00Z",
               key=None):
    declared = intent_value["scopes"][0]
    return seal(model, {
        "schema_version": 1, "kind": "authority-observation", "id": "",
        "contract_digest": model.canonical_digest(contract), "scope_id": declared["id"],
        "launch_id": None, "authority_kind": "intent_revocation", "verdict": "revoked",
        "reason_code": "revoked", "observed_at": observed,
        "evidence_digest": "sha256:" + "8" * 64, "opaque_host_reference": None,
        "revocation_subject": {"intent_id": intent_value["id"],
                               "revocation_key": key or intent_value["revocation_key"]},
        "evaluation_use_key": None})


def reevaluation(model, contract, denial):
    return seal(model, {
        "schema_version": 1, "kind": "reevaluation-evidence", "id": "",
        "contract_digest": model.canonical_digest(contract), "scope_id": denial["scope_id"],
        "rejected_observation_id": denial["id"], "source_kind": "host",
        "reason_code": "material_change", "observed_at": "2026-09-20T02:00:00Z",
        "evidence_digest": "sha256:" + "6" * 64,
    })


def evaluation(**changes):
    value = {"at_time": "2026-09-21T00:00:00Z", "custody": None,
             "current_launch": None, "requested_scope": None, "source_kind": "direct",
             "authorization_intents": [], "authority_observations": [],
             "reevaluation_evidence": [], "delivery_observations": []}
    value.update(changes)
    return value


def native_evaluation(contract_digest, active, scope_id):
    return {
        "kind": "native_authority_evaluation", "contract_digest": contract_digest,
        "scope_id": scope_id, "custody": copy.deepcopy(active),
        "rejected_observation_id": "sha256:" + "9" * 64,
        "basis_kind": "reevaluation_evidence", "basis_id": "sha256:" + "8" * 64,
        "use_key": "sha256:" + "7" * 64,
    }


def stage_state(result, stage_id):
    return next(fact["state"] for fact in result["next_delivery"]["stage_facts"]
                if fact["stage_id"] == stage_id)


def post_state(result, name):
    return result["next_delivery"]["postconditions"][name]["state"]


def workflow_responses(model):
    contract, _ = contract_and_delivery(model); digest = model.canonical_digest(contract)
    active = custody(); pending = [stage["id"] for stage in contract["stages"]]
    block = {"custody": active, "contract": contract, "contract_digest": digest,
             "pending_stage_ids": pending, "requirements": [{"kind": "scope_tuple", "subject_id": "select", "reason_code": "scope_tuple_required", "detail_pointer": None}], "authority_evaluation": None,
             "requested_scope": None}
    owner = {"interface_version": 2, "kind": "owner", "ledger_repo_root": "/repo",
             "run_id": "run-1", "issue": 151, "attempt": 1, "owner": "151:1",
             "action_id": "151:1:1", "launch_kind": "spawn", "worktree": "/worktree",
             "handoff_path": "/handoff", "deadline_at": "2026-09-21T01:00:00Z", **block}
    control_owner = {"id": "151:1:1", "kind": "spawn", "issue": 151, "attempt": 1,
                     "owner": "151:1", "worktree": "/worktree", "handoff_path": "/handoff",
                     "deadline_at": "2026-09-21T01:00:00Z", **block}
    remainder_custody = {"kind": "remainder", "remainder": 1, "launch": 1,
                         "action_id": "151:r1:1"}
    remainder = {"interface_version": 2, "kind": "delivery_remainder",
                 "ledger_repo_root": "/repo", "run_id": "run-1", "issue": 151,
                 "source_attempt": 1, "owner": "151:r1", "custody": remainder_custody,
                 "worktree": "/worktree", "contract": contract, "contract_digest": digest,
                 "pending_stage_ids": pending, "deadline_at": "2026-09-21T01:00:00Z",
                 "requirements": [{"kind": "scope_tuple", "subject_id": "select", "reason_code": "scope_tuple_required", "detail_pointer": None}], "authority_evaluation": None, "requested_scope": None}
    common = {"interface_version": 2, "ledger_repo_root": "/repo", "run_id": "run-1",
              "issue": 151, "owner": "151:1", "custody": active,
              "contract_digest": digest, "accepted_observation_ids": [],
              "pending_stage_ids": pending}
    return {
        "host_route": {"interface_version": 1, "kind": "host_route", "route": "claude-code",
                       "support": "supported", "agent_slots": 7, "reason_code": None,
                       "alternative": None},
        "host_route_unsupported": {"interface_version": 1, "kind": "host_route",
                                   "route": "codex", "support": "unsupported",
                                   "agent_slots": None, "reason_code": "declared_unsupported",
                                   "alternative": "/from-issue <issue> --auto"},
        "current": {"action_id": "151:1:1", "current": True,
                    "current_action_id": "151:1:1", "reason": "current"},
        "bootstrap": {"interface_version": 2, "kind": "workflow_bootstrap",
                      "run_id": "run-1", "requirements": []},
        "control": {"interface_version": 3, "run_id": "run-1", "now": "2026-09-21T00:00:00Z",
                    "summaries": [{"issue": 151, "state": "active", "custody": active,
                        "owner": "151:1", "worktree": "/worktree", "deadline_at": "2026-09-21T01:00:00Z",
                        "blocked_on": None, "blockers": [], "result": None,
                        "contract_digest": digest, "pending_stage_ids": pending, "requirements": []}],
                    "deltas": [{"issue": 151, "custody": active, "kind": "spawned", "state": "active"}],
                    "actions": [control_owner], "next_deadline": "2026-09-21T01:00:00Z",
                    "admission": {"route": "claude-code", "declared_slots": 7, "reserved": {
                        "controller": 1, "owner": 1, "worker": 1, "reviewer": 1},
                        "available": 3, "waiting": []}},
        "observe": {"interface_version": 2, "kind": "observe", "issue": 151,
                    "run_id": "run-1", "requirements": [{"kind": "tracker"}]},
        "owner": owner,
        "terminal": {"interface_version": 2, "kind": "terminal", "issue": 151,
                     "run_id": "run-1", "source": "ledger", "reason": "closed",
                     "blockers": [], "result": None, "reentry": "resume"},
        "remainder": remainder,
        "checkpointed": {**common, "kind": "delivery_checkpointed", "next_action": None,
                         "requirements": [{"kind": "scope_tuple", "subject_id": "select", "reason_code": "scope_tuple_required", "detail_pointer": None}], "authority_evaluation": None, "requested_scope": None, "state": "active", "blocked_on": None},
        "stalled": {**common, "kind": "delivery_stalled", "state": "terminal_failed",
                    "stalled_resumes": 3, "result_source": "stalled",
                    "reason_code": "suspension_stalled_without_progress"},
        "complete": {**common, "kind": "delivery_complete", "pending_stage_ids": [],
                     "state": "delivery_complete"},
        "failed": {**common, "kind": "terminal_failed", "state": "terminal_failed",
                   "result_source": "owner", "reason_code": "owner_reported_failure"},
    }


def with_host_rejection(model, contract, delivery, active):
    result = copy.deepcopy(delivery)
    denial = authority(model, contract, result["authorization_intents"][-1]["scopes"][0], active)
    result["authority_observations"] = [denial]
    return result, denial


def observation(model, contract, kind, subject):
    return seal(model, {
        "schema_version": 1, "kind": "delivery-observation", "id": "",
        "contract_digest": model.canonical_digest(contract),
        "project": copy.deepcopy(contract["project"]), "observation_kind": kind,
        "subject": copy.deepcopy(subject),
        "source": {"kind": "provider", "reference": f"sim:{kind}"},
        "observed_at": "2026-09-20T03:00:00Z",
        "evidence_digest": "sha256:" + "7" * 64,
    })


def pr_subject(kind, *, head="a" * 40, pr=17, repository="sim-repo",
               base="main", merged=True):
    value = {"provider_repository_id": repository, "pr_number": pr,
             "pr_url": f"https://sim.invalid/pr/{pr}", "expected_head": head,
             "base": base}
    if kind == "pr_merged": value.update(merge_sha="b" * 40, merged=merged)
    return value


def with_observed(model, contract, delivery, stage_ids):
    result = copy.deepcopy(delivery)
    mapping = {
        "select": ("selected_output", {"selected_output": selection(model, model.canonical_digest(contract))}),
        "publish": ("branch_published", {"repository_id": "sim-repo", "branch": "feature", "selected_head": "a" * 40}),
        "open": ("pr_opened", pr_subject("pr_opened")),
        "merge": ("pr_merged", pr_subject("pr_merged")),
    }
    for stage_id in stage_ids:
        kind, subject = mapping[stage_id]
        item = observation(model, contract, kind, subject)
        result["delivery_observations"].append(item)
    result["delivery_observations"].sort(key=lambda item: item["id"])
    return result


def rebind_contract(model, contract, delivery):
    result = copy.deepcopy(delivery)
    result["contract"] = copy.deepcopy(contract)
    result["contract_digest"] = model.canonical_digest(contract)
    result["stage_facts"] = [seal(model, {
        "schema_version": 1, "kind": "delivery-stage-fact", "id": "",
        "contract_digest": result["contract_digest"], "stage_id": stage["id"],
        "state": "pending", "observation_id": None,
    }) for stage in contract["stages"]]
    return result


def cleanup_contract_and_delivery(model):
    contract, delivery = contract_and_delivery(model)
    stages = (
        ("close", "close_tracker", "close_issue", "tracker_write", "151", "not_required"),
        ("remote", "delete_remote_branch", "delete_remote_branch", "repository_write", "feature", "cleanup_target"),
        ("worktree", "remove_worktree", "remove_worktree", "filesystem_write", "/worktree", "cleanup_target"),
        ("local", "delete_local_branch", "delete_local_branch", "repository_write", "feature", "cleanup_target"),
    )
    dependency = "merge"
    for stage_id, kind, action, effect, target, requirement in stages:
        contract["stages"].append({
            "id": stage_id, "kind": kind, "action": action, "effect": effect,
            "target_ref": {"kind": "literal", "value": target},
            "worktree_requirement": requirement, "depends_on": [dependency],
            "retryable": True,
        })
        dependency = stage_id
    contract["deliverable"]["obligations"].update(
        tracker_closed="required", cleanup_complete="required")
    delivery = rebind_contract(model, contract, delivery)
    delivery["postconditions"]["tracker_closed"] = {"state": "pending", "observation_id": None}
    delivery["postconditions"]["cleanup_complete"] = {"state": "pending", "observation_id": None}
    return contract, delivery


def record_case(model, *, with_merge, integrated=None):
    contract, delivery = contract_and_delivery(model)
    for stage in contract["stages"]:
        stage["target_ref"]["subject_kind"] = "record"
    record_stage = {
        "id": "record", "kind": "deliver_repository_record", "action": "write_record",
        "effect": "repository_write", "target_ref": copy.deepcopy(contract["stages"][0]["target_ref"]),
        "worktree_requirement": "matching_required", "depends_on": ["select"], "retryable": True}
    stages = [contract["stages"][0], record_stage]
    if with_merge:
        opened = copy.deepcopy(contract["stages"][2]); opened["depends_on"] = ["record"]
        merged = copy.deepcopy(contract["stages"][3]); merged["depends_on"] = ["open"]
        stages += [opened, merged]
    else:
        contract["deliverable"]["obligations"]["pr_merged"] = "not_applicable"
    contract["stages"] = stages
    delivery = rebind_contract(model, contract, delivery)
    if not with_merge:
        delivery["postconditions"]["pr_merged"] = {"state": "not_applicable", "observation_id": None}
    chosen = selection(model, delivery["contract_digest"], subject_kind="record")
    value = chosen["subject_value"]; integrated = integrated or value
    items = {
        "selected": observation(model, contract, "selected_output", {"selected_output": chosen}),
        "record": observation(model, contract, "repository_record_proposed", {
            "repository_id": "sim-repo", "selected_record_digest": value,
            "branch": "feature", "live_pr_head": "c" * 40,
            "review_evidence_ids": ["review-1"]}),
    }
    if with_merge:
        items["open"] = observation(model, contract, "pr_opened", {
            "provider_repository_id": "sim-repo", "pr_number": 17,
            "pr_url": "https://sim.invalid/pr/17", "expected_head": "c" * 40, "base": "main"})
        items["merge"] = observation(model, contract, "pr_merged", {
            **items["open"]["subject"], "merge_sha": "b" * 40, "merged": True})
    items["delivered"] = observation(model, contract, "implementation_delivered", {
        "selected_subject": {"kind": "record", "value": value},
        "integration_subject": {"kind": "record", "value": integrated},
        "presence": {"kind": "record_presence", "repository_id": "sim-repo",
                     "selected_value": value, "integration_value": integrated,
                     "integrated_ref": "refs/heads/main", "succeeded": True},
        "merge_observation_id": items["merge"]["id"] if with_merge else None,
        "acceptance_evidence_ids": ["accept-1"], "review_evidence_ids": ["review-1"],
        "test_evidence_ids": ["test-1"]})
    delivery["delivery_observations"] = sorted(items.values(), key=lambda item: item["id"])
    return contract, delivery, items


def renewal_case(model, allow_at, revoke_at=None):
    contract, delivery, declared = contract_and_delivery_for_stage(model, "select")
    first = delivery["authorization_intents"][0]
    first["expires_at"] = "2026-09-20T02:00:00Z"; seal(model, first)
    contract["initial_authorization_intent_id"] = first["id"]
    contract["initial_authorization_intent_digest"] = model.canonical_digest(first)
    delivery["authorization_chain_digest"] = model.canonical_digest({"intent_ids": [first["id"]]})
    delivery = rebind_contract(model, contract, delivery)
    successor = intent(model, declared, predecessor=first["id"],
                       issued="2026-09-20T03:00:00Z", key="renewal")
    allowed = authority(model, contract, declared, custody(), verdict="allowed")
    allowed["observed_at"] = allow_at; seal(model, allowed)
    observations = [allowed]
    if revoke_at is not None:
        observations.append(revocation(model, contract, first, observed=revoke_at))
    observations.sort(key=lambda item: item["id"])
    result = model.reduce_delivery(contract, delivery, evaluation=evaluation(
        at_time="2026-09-20T04:00:00Z", custody=custody(), current_launch=True,
        requested_scope=declared, authorization_intents=[successor],
        authority_observations=observations))
    return result, allowed


def ship_handoff(model, contract, delivery):
    artifact = {"budget_status": "within_budget", "kind": "design-spec",
                "metrics": {"root_bytes": 1, "total_bytes": 1, "file_count": 1,
                            "largest_member_bytes": 0},
                "path": ".claude/specs/sim.md"}
    return {"interface_version": 2, "state": "complete", "ledger_repo_root": "/repo",
            "run_id": "run-1", "owner": "151:1", "owner_worktree": "/worktree",
            "custody": custody(), "issue_number": 151, "branch": "feature",
            "worktree_path": "/worktree", "spec_artifact": artifact,
            "plan_artifact": {**artifact, "kind": "implementation-plan",
                              "path": ".claude/plans/sim.md"},
            "head_sha": "a" * 40, "review_state": "clean", "auto": True,
            "report_path": None, "notes": "simulated", "delivery_contract": contract,
            "delivery_contract_digest": model.canonical_digest(contract),
            "authorization_intents": delivery["authorization_intents"],
            "authorization_chain_digest": delivery["authorization_chain_digest"],
            "authority_observation_ids": [], "reevaluation_evidence_ids": [],
            "authority_evaluation_consumption_ids": [],
            "pending_stage_ids": [stage["id"] for stage in contract["stages"]],
            "selected_outputs": delivery["selected_outputs"], "requested_scope": None}


def ship_checkpoint(model, contract, requested=None):
    return {
        "interface_version": 2, "issue": contract["issue"], "custody": custody(),
        "contract_digest": model.canonical_digest(contract),
        "delivery_observations": [], "authority_observations": [],
        "reevaluation_evidence": [], "requested_scope": copy.deepcopy(requested),
        "detail_state": "none", "report_path": None, "notes": "simulated",
    }
