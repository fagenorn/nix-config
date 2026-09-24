"""Pure delivery builder: contracts, intents, scopes, selections and evidence.

This private helper has no I/O, reads no clock and grants no authority.
workflow-state resolves project policy and hands it in; every sealed object
this module returns is validated again by DeliveryRuntime before it is printed.
Declared scopes (in the initial intent) and actual scopes (kind ``scope``) come
from the one ``_scope`` function, so exact matching can only disagree when the
inputs differ. Selections and observations take only what a probe returns;
every member the contract determines is filled from the contract, so an owner
never composes a digest.
"""

from __future__ import annotations

import copy
import hashlib
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
_SELECTION_INPUT = {"contract", "head", "tree", "acceptance_ref", "review_ref", "test_ref"}
_OBSERVATION_INPUT = {"contract", "observation_kind", "source_kind", "source_reference",
                      "observed_at", "evidence"}
_OBSERVATION_SOURCES = frozenset({"provider", "tracker", "repository", "filesystem",
                                  "human_completion"})
_AUTHORITY_INPUT = {"contract", "scope_id", "launch_id", "authority_kind", "verdict",
                    "reason_code", "observed_at", "evidence"}
_AUTHORITY_KINDS = frozenset({"native_guard", "host", "provider"})
_VERDICTS = frozenset({"allowed", "rejected", "unknown"})


def _refuse(reason: str) -> None:
    raise ValueError(reason)


def _closed(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _refuse("builder input keys: expected exactly " + ", ".join(sorted(keys)))
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        _refuse(f"builder input keys: {name} must be a non-empty string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        _refuse(f"builder input keys: {name} must be a positive integer")
    return value


def _texts(value: object, name: str) -> list[str]:
    if not isinstance(value, list):
        _refuse(f"builder input keys: {name} must be a list of strings")
    return sorted(_text(item, name) for item in value)


def _utc(value: object, name: str) -> str:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        _refuse(f"builder input keys: {name} must be a UTC timestamp")
    return value


def _evidence_digest(value: object, name: str) -> str:
    return "sha256:" + hashlib.sha256(_text(value, name).encode("utf-8")).hexdigest()


# The observed facts per observation kind: each kind's fact checkers, and the subject
# built from the contract context (repository, issue, branch, base, worktree) and
# those checked facts. A selection fact is checked by the builder itself.
def _pr_subject(context: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    return {"provider_repository_id": context["repository_id"],
            "pr_number": facts["pr_number"], "pr_url": facts["pr_url"],
            "expected_head": facts["head"], "base": context["base"]}


def _absent_branch(context: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    return {"repository_id": context["repository_id"], "branch": context["branch"],
            "absent": True}


def _delivered(context: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    selection = facts["selection"]
    return {
        "selected_subject": {"kind": selection["subject_kind"],
                             "value": selection["subject_value"]},
        "integration_subject": {"kind": selection["subject_kind"],
                                "value": facts["merge_sha"]},
        "presence": {"kind": "reachability", "repository_id": context["repository_id"],
                     "selected_value": selection["subject_value"],
                     "integration_value": facts["merge_sha"],
                     "integrated_ref": facts["integrated_ref"], "succeeded": True},
        "merge_observation_id": facts["merge_observation_id"],
        **{name: list(selection[name]) for name in (
            "acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids")},
    }


def _cleaned(context: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    return {**{name: facts[name] for name in (
                "remote_branch_observation_ids", "local_branch_observation_ids",
                "worktree_observation_ids")},
            "durable_detail": {"detail_pointer": facts["detail_pointer"],
                               "read_evidence_digest": facts["read_evidence"],
                               "succeeded": True}}


_OBSERVATIONS: dict[str, tuple[dict[str, Any], Any]] = {
    "selected_output": ({"selection": None},
                        lambda context, facts: {"selected_output": facts["selection"]}),
    "branch_published": ({"head": _text}, lambda context, facts: {
        "repository_id": context["repository_id"], "branch": context["branch"],
        "selected_head": facts["head"]}),
    "pr_opened": ({"pr_number": _positive, "pr_url": _text, "head": _text}, _pr_subject),
    "pr_merged": ({"pr_number": _positive, "pr_url": _text, "head": _text,
                   "merge_sha": _text},
                  lambda context, facts: {**_pr_subject(context, facts),
                                          "merge_sha": facts["merge_sha"], "merged": True}),
    "tracker_closed": ({"close_reason": _optional_text, "observation_identity": _text},
                       lambda context, facts: {
                           "tracker_repository_id": context["repository_id"],
                           "issue": context["issue"], "state": "closed",
                           "close_reason": facts["close_reason"],
                           "observation_identity": facts["observation_identity"]}),
    "remote_branch_absent": ({}, _absent_branch),
    "local_branch_absent": ({}, _absent_branch),
    "worktree_absent": ({}, lambda context, facts: {
        "path": context["worktree"], "recorded_worktree_identity": context["worktree"],
        "probe_mode": "no_follow", "absent": True}),
    "implementation_delivered": ({"selection": None, "merge_sha": _text,
                                  "integrated_ref": _text, "merge_observation_id": _text},
                                 _delivered),
    "cleanup_complete": ({"remote_branch_observation_ids": _texts,
                          "local_branch_observation_ids": _texts,
                          "worktree_observation_ids": _texts, "detail_pointer": _text,
                          "read_evidence": _evidence_digest}, _cleaned),
}


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
        observable = {item[2] for item in self._actions.values()} | set(_OBLIGATIONS)
        if not set(_OBSERVATIONS) <= observable:
            raise ValueError("builder observation kinds exceed the model's")
        self._observations = {kind: _OBSERVATIONS[kind] for kind in sorted(observable)
                              if kind in _OBSERVATIONS}

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
        if kind == "selected-output":
            return self._selection(value)
        if kind == "observation":
            return self._observation(value)
        if kind == "authority-observation":
            return self._authority(value)
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

    def _selection(self, value: object) -> dict[str, Any]:
        value = _closed(value, _SELECTION_INPUT)
        refs = {name: _text(value[name], name) for name in (
            "head", "tree", "acceptance_ref", "review_ref", "test_ref")}
        contract = self._checked_contract(value["contract"])
        _, _, branch, base, _ = self._contract_facts(contract)
        head = refs["head"]
        return self._seal({
            "schema_version": 1, "kind": "selected-output",
            "contract_digest": self._model.canonical_digest(contract),
            "slot_id": _SLOT, "subject_kind": "commit", "subject_value": head,
            "data_identity_digest": self._model.canonical_digest(
                {"kind": "git-tree", "value": refs["tree"]}),
            "repository_id": contract["project"]["repository_id"],
            "branch": branch, "base": base,
            "evidence_digest": self._model.canonical_digest({name: refs[name] for name in (
                "head", "acceptance_ref", "review_ref", "test_ref")}),
            "acceptance_evidence_ids": [f"acceptance:{refs['acceptance_ref']}@{head}"],
            "review_evidence_ids": [f"review:{refs['review_ref']}@{head}"],
            "test_evidence_ids": [f"test:{refs['test_ref']}@{head}"],
        })

    def _observation(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("observation_kind"), str):
            _refuse("builder input keys: observation_kind must be a string")
        kind = value["observation_kind"]
        if kind not in self._observations:
            _refuse(f"unsupported observation kind: {kind!r}")
        checkers, subject = self._observations[kind]
        value = _closed(value, _OBSERVATION_INPUT | set(checkers))
        if _text(value["source_kind"], "source_kind") not in _OBSERVATION_SOURCES:
            _refuse(f"source kind {value['source_kind']!r} cannot source an observation")
        reference = _text(value["source_reference"], "source_reference")
        observed_at = _utc(value["observed_at"], "observed_at")
        evidence = _evidence_digest(value["evidence"], "evidence")
        contract = self._checked_contract(value["contract"])
        digest = self._model.canonical_digest(contract)
        facts = {name: (self._contract_selection(value[name], digest) if check is None
                        else check(value[name], name))
                 for name, check in checkers.items()}
        project, issue, branch, base, worktree = self._contract_facts(contract)
        context = {"repository_id": project["repository_id"], "issue": issue,
                   "branch": branch, "base": base, "worktree": worktree}
        return self._seal({
            "schema_version": 1, "kind": "delivery-observation", "contract_digest": digest,
            "project": project, "observation_kind": kind,
            "subject": subject(context, facts),
            "source": {"kind": value["source_kind"], "reference": reference},
            "observed_at": observed_at, "evidence_digest": evidence,
        })

    def _contract_selection(self, value: object, contract_digest: str) -> dict[str, Any]:
        try:
            selection = self._model.validate_delivery_object(
                value, expected_kind="selected-output", notes_max_characters=self._notes_max)
        except ValueError as error:
            _refuse(f"selection is invalid: {error}")
        if selection["contract_digest"] != contract_digest:
            _refuse("selection contract digest does not match the contract")
        return selection

    def _authority(self, value: object) -> dict[str, Any]:
        value = _closed(value, _AUTHORITY_INPUT)
        if _text(value["authority_kind"], "authority_kind") not in _AUTHORITY_KINDS:
            _refuse(f"unsupported authority kind: {value['authority_kind']!r}")
        if _text(value["verdict"], "verdict") not in _VERDICTS:
            _refuse(f"unsupported verdict: {value['verdict']!r}")
        launch = _text(value["launch_id"], "launch_id")
        reason = _text(value["reason_code"], "reason_code")
        observed_at = _utc(value["observed_at"], "observed_at")
        evidence = _evidence_digest(value["evidence"], "evidence")
        contract = self._checked_contract(value["contract"])
        scopes = {self._scope(contract, stage)["id"] for stage in contract["stages"]}
        if _text(value["scope_id"], "scope_id") not in scopes:
            _refuse(f"unknown scope: {value['scope_id']!r} is not a stage scope of the contract")
        return self._seal({
            "schema_version": 1, "kind": "authority-observation",
            "contract_digest": self._model.canonical_digest(contract),
            "scope_id": value["scope_id"], "launch_id": launch,
            "authority_kind": value["authority_kind"], "verdict": value["verdict"],
            "reason_code": reason, "observed_at": observed_at, "evidence_digest": evidence,
            "opaque_host_reference": None, "revocation_subject": None,
            "evaluation_use_key": None,
        })

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
