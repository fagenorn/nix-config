"""Pure delivery builder: contracts, initial intents and scopes from policy.

This private helper has no I/O, reads no clock and grants no authority.
workflow-state resolves project policy and hands it in; every sealed object
this module returns is validated again by DeliveryRuntime before it is printed.
Declared scopes (in the initial intent) and actual scopes (kind ``scope``) come
from the one ``_scope`` function, so exact matching can only disagree when the
inputs differ.
"""

from __future__ import annotations

import copy
import os.path
from pathlib import PurePosixPath
import re
from typing import Any

WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 1

_SLOT = "reviewed"
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SOURCE_KINDS = frozenset({"explicit_user", "standing_repository"})
_PLACEHOLDER = re.compile(r"(<num>|<slug>)")
_SLUG = "[a-z0-9][a-z0-9-]*"
_OBLIGATIONS = ("implementation_delivered", "pr_merged", "tracker_closed",
                "cleanup_complete")
_SLOT_STAGES = ("select_reviewed_output", "publish_branch", "open_pr", "merge_pr")
_PR_STAGES = frozenset({"open_pr", "merge_pr"})
_CONTRACT_INPUT = {"issue", "worktree", "source_kind", "source_reference", "now"}


def _refuse(reason: str) -> None:
    raise ValueError(reason)


def _closed(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _refuse("builder input keys: expected exactly " + ", ".join(sorted(keys)))
    return value


def _policy_member(policy: object, path: str, kind: type) -> Any:
    value = policy
    for name in path.split("."):
        if not isinstance(value, dict) or name not in value:
            _refuse(f"policy member missing: {path}")
        value = value[name]
    if type(value) is not kind:
        _refuse(f"policy member mistyped: {path}")
    return value


class DeliveryBuilder:
    """Derive sealed delivery objects from resolved policy and invocation facts."""

    def __init__(self, model: object, *, notes_max_characters: int) -> None:
        self._model = model
        self._notes_max = notes_max_characters
        self._actions = model.STAGE_ACTIONS

    def build(self, kind: str, value: object, *, policy: dict | None) -> object:
        if kind == "contract":
            return self._build_contract(value, policy)
        if kind == "initial-intent":
            contract = self._checked_contract(_closed(value, {"contract"})["contract"])
            return self._intent(contract)
        if kind == "scope":
            value = _closed(value, {"contract", "stage_id"})
            if not isinstance(value["stage_id"], str):
                _refuse("builder input keys: stage_id must be a string")
            contract = self._checked_contract(value["contract"])
            stage = next((item for item in contract["stages"]
                          if item["id"] == value["stage_id"]), None)
            if stage is None:
                _refuse(f"unknown stage: {value['stage_id']!r}")
            return self._scope(contract, stage)
        _refuse(f"unknown builder kind: {kind!r}")

    def _seal(self, value: dict[str, Any]) -> dict[str, Any]:
        value["id"] = ""
        value["id"] = self._model.canonical_digest(value, omit_derived="id")
        return value

    def _build_contract(self, value: object, policy: object) -> dict[str, Any]:
        value = _closed(value, _CONTRACT_INPUT)
        issue, worktree = value["issue"], value["worktree"]
        if (type(issue) is not int or issue < 1 or not isinstance(worktree, str)
                or not isinstance(value["source_kind"], str)
                or not isinstance(value["source_reference"], str)
                or not value["source_reference"] or not isinstance(value["now"], str)
                or _UTC.fullmatch(value["now"]) is None):
            _refuse("builder input keys: mistyped contract input")
        if value["source_kind"] not in _SOURCE_KINDS:
            _refuse(f"source kind {value['source_kind']!r} cannot source an initial intent")
        if not os.path.isabs(worktree) or os.path.normpath(worktree) != worktree:
            _refuse("worktree must be absolute and normalized")
        facts = {
            "project_id": _policy_member(policy, "project.id", str),
            "tracker_kind": _policy_member(policy, "bindings.tracker.kind", str),
            "repository_slug": _policy_member(policy, "bindings.tracker.repo_slug", str),
            "branch_pattern": _policy_member(policy, "bindings.vcs.branch_pattern", str),
            "worktree_prefix": _policy_member(policy, "bindings.vcs.worktree.prefix", str),
            "integration_branch": _policy_member(
                policy, "bindings.vcs.integration_branch", str),
            "delete_branch": _policy_member(policy, "bindings.vcs.merge.delete_branch", bool),
        }
        if facts["tracker_kind"] != "github":
            _refuse(f"tracker kind {facts['tracker_kind']!r} is unsupported")
        branch = PurePosixPath(worktree).name
        pattern = "".join(
            str(issue) if part == "<num>" else _SLUG if part == "<slug>" else re.escape(part)
            for part in _PLACEHOLDER.split(facts["branch_pattern"]))
        if re.fullmatch(f"(?:{re.escape(facts['worktree_prefix'])})?{pattern}", branch) is None:
            _refuse(f"worktree name {branch!r} does not match the issue branch pattern")
        slug = facts["repository_slug"]
        project = {"project_id": facts["project_id"], "provider": facts["tracker_kind"],
                   "repository_id": slug, "repository_slug": slug}
        slot = {"kind": "slot", "slot_id": _SLOT, "subject_kind": "commit",
                "constraints": {**project, "branch": branch,
                                "base": facts["integration_branch"],
                                "deliverable_class": "source",
                                "data_ref": {"kind": "selected_output_slot", "slot_id": _SLOT,
                                             "classification": "source",
                                             "audience": self._model.canonical_digest(
                                                 {"repository": slug})}}}
        plan = [(kind, slot, "matching_required") for kind in _SLOT_STAGES]
        plan.append(("close_tracker", {"kind": "literal", "value": str(issue)},
                     "not_required"))
        if facts["delete_branch"]:
            plan.append(("delete_remote_branch", {"kind": "literal", "value": branch},
                         "not_required"))
        plan.append(("remove_worktree", {"kind": "literal", "value": worktree},
                     "cleanup_target"))
        plan.append(("delete_local_branch", {"kind": "literal", "value": branch},
                     "cleanup_target"))
        stages, previous = [], []
        for kind, target, requirement in plan:
            action, effect, _ = self._actions[kind]
            stages.append({"id": kind, "kind": kind, "action": action, "effect": effect,
                           "target_ref": copy.deepcopy(target),
                           "worktree_requirement": requirement,
                           "depends_on": previous, "retryable": True})
            previous = [kind]
        source = {"kind": value["source_kind"], "reference": value["source_reference"]}
        contract = {
            "schema_version": 1, "kind": "delivery-contract", "project": project,
            "issue": issue,
            "deliverable": {"id": f"issue-{issue}", "summary": f"Deliver {slug}#{issue}",
                            "obligations": {name: "required" for name in _OBLIGATIONS}},
            "stages": stages,
            "initial_authorization_intent_id": None,
            "initial_authorization_intent_digest": None,
            "provenance": {**source, "digest": self._model.canonical_digest({
                "policy": {name: facts[name] for name in (
                    "project_id", "tracker_kind", "repository_slug", "branch_pattern",
                    "worktree_prefix", "integration_branch", "delete_branch")},
                "issue": issue, "worktree": worktree, "source": source}),
                "created_at": value["now"]},
        }
        intent = self._intent(contract)
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = self._model.canonical_digest(intent)
        return {"contract": contract, "initial_intent": intent}

    def _checked_contract(self, value: object) -> dict[str, Any]:
        """Validate a supplied contract and require its recorded intent to regenerate."""
        try:
            contract = self._model.validate_delivery_object(
                value, expected_kind="delivery-contract",
                notes_max_characters=self._notes_max)
        except ValueError as error:
            _refuse(f"contract is invalid: {error}")
        if contract["provenance"]["kind"] not in _SOURCE_KINDS:
            _refuse("source kind of the contract cannot source an initial intent")
        intent = self._intent(contract)
        if (intent["id"], self._model.canonical_digest(intent)) != (
                contract["initial_authorization_intent_id"],
                contract["initial_authorization_intent_digest"]):
            _refuse("derived intent does not match the contract's initial intent")
        return contract

    def _intent(self, contract: dict[str, Any]) -> dict[str, Any]:
        project, issue, _, _, _ = self._contract_facts(contract)
        provenance = contract["provenance"]
        scopes = sorted((self._scope(contract, stage) for stage in contract["stages"]),
                        key=lambda item: item["id"])
        return self._seal({
            "schema_version": 1, "kind": "authorization-intent",
            "predecessor_intent_id": None,
            "source": {"kind": provenance["kind"], "reference": provenance["reference"],
                       "evidence_digest": provenance["digest"]},
            "issued_at": provenance["created_at"], "expires_at": None,
            "revocation_key": f"{project['project_id']}#{issue}@{provenance['created_at']}",
            "scopes": scopes,
        })

    @staticmethod
    def _contract_facts(contract: dict[str, Any]) -> tuple[dict[str, Any], int, str, str, str]:
        slot = next((stage["target_ref"] for stage in contract["stages"]
                     if stage["target_ref"].get("kind") == "slot"), None)
        worktree = next((stage["target_ref"].get("value") for stage in contract["stages"]
                         if stage["kind"] == "remove_worktree"
                         and stage["target_ref"].get("kind") == "literal"), None)
        if slot is None or worktree is None:
            _refuse("derived intent cannot be regenerated: the contract has no "
                    "reviewed slot or worktree stage")
        constraints = slot["constraints"]
        return (copy.deepcopy(contract["project"]), contract["issue"],
                constraints["branch"], constraints["base"], worktree)

    def _scope(self, contract: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
        project, issue, branch, base, worktree = self._contract_facts(contract)
        action, effect, _ = self._actions[stage["kind"]]
        target_ref = stage["target_ref"]
        if target_ref.get("kind") == "slot":
            output_ref = {"kind": "slot", "slot_id": target_ref["slot_id"]}
            data = copy.deepcopy(target_ref["constraints"]["data_ref"])
        else:
            output_ref, data = {"kind": "none"}, {"kind": "none"}
        pr_ref = (copy.deepcopy(output_ref)
                  if stage["kind"] in _PR_STAGES and output_ref["kind"] == "slot"
                  else {"kind": "none"})
        endpoint = ({"kind": "literal", "value": worktree}
                    if stage["kind"] == "remove_worktree" else {"kind": "none"})
        return self._seal({
            "schema_version": 1, "kind": "scope-tuple",
            "principal": {"kind": "issue_owner",
                          "stable_id": f"{project['project_id']}#{issue}"},
            "action": action, "effect": effect,
            "target": {**project, "issue": issue, "branch": branch, "base": base,
                       "pr_ref": pr_ref, "output_ref": output_ref},
            "endpoint": endpoint, "data": data, "risk": effect, "spend": {"kind": "none"},
        })
