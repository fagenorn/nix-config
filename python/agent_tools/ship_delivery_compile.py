"""Compile factual shipping recipes using the canonical delivery boundaries.

No effect is executed or ledger changed here. Seals, scopes and wire validation
remain owned by workflow-state and artifact-budget respectively.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal


class DeliveryInputError(ValueError):
    """A recipe, context or canonical dependency refused the construction."""


def load_json(raw: str) -> Any:
    return json.loads(raw, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def closed(value: Any, required: set[str], optional: set[str] | None = None,
           *, label: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - (optional or set())):
        raise DeliveryInputError(
            f"{label}: required keys {', '.join(sorted(required))}; "
            f"optional keys {', '.join(sorted(optional or set()))}")
    return value


def array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DeliveryInputError(f"{label} must be an array")
    return value


class DeliveryCommands:
    """Existing executable boundaries, also usable by importers of the compiler."""

    def call(self, argv: list[str], value: Any = None) -> Any:
        try:
            result = subprocess.run(argv, input=None if value is None else json.dumps(value),
                                    text=True, capture_output=True, check=False, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise DeliveryInputError(f"{argv[0]} timed out: {error}") from error
        if result.returncode:
            raise DeliveryInputError(
                f"{argv[0]} exited {result.returncode}: {result.stderr.rstrip()}")
        try:
            return load_json(result.stdout)
        except ValueError as error:
            raise DeliveryInputError(f"{argv[0]} returned invalid JSON: {error}") from error

    def validate(self, boundary: str, value: Any) -> Any:
        return self.call(["artifact-budget", "validate-report", "--boundary", boundary,
                          "--input", "-"], value)

    def build(self, root: str, kind: str, value: Any) -> Any:
        return self.call(["workflow-state", "build-delivery", "--repo-root", root,
                          "--kind", kind, "--input", "-"], value)


class DeliveryCompiler:
    """One invocation's validated identity, sealed builder results and local refs."""

    def __init__(self, context: Any, prior: list[Any], commands: DeliveryCommands):
        self.commands = commands
        if not isinstance(context, dict) or context.get("interface_version") != 2:
            raise DeliveryInputError("context must use interface_version 2")
        if isinstance(context, dict) and context.get("kind") == "delivery_remainder":
            context = commands.validate("workflow-response", context)
            contract, digest = context["contract"], context["contract_digest"]
        else:
            context = commands.validate("ship-handoff", context)
            if context["state"] != "complete":
                raise DeliveryInputError("handoff must be complete")
            contract, digest = context["delivery_contract"], context["delivery_contract_digest"]
        self.context, self.contract, self.digest = context, contract, digest
        self.issue, self.custody = contract["issue"], context["custody"]
        self.root = context["ledger_repo_root"]
        self.selection: Any = None
        self.references: dict[str, dict[str, Any]] = {}
        for payload in prior:
            if not isinstance(payload, dict):
                raise DeliveryInputError("prior payload must be an object")
            if payload.get("interface_version") != 2:
                raise DeliveryInputError("prior payload must use interface_version 2")
            boundary = "ship-checkpoint" if "requested_scope" in payload else "ship-summary"
            payload = commands.validate(boundary, payload)
            digest_key = "contract_digest" if boundary == "ship-checkpoint" else "delivery_contract_digest"
            if (payload["issue"], payload[digest_key]) != (self.issue, self.digest):
                raise DeliveryInputError("prior payload belongs to another issue or contract")
            for observation in payload["delivery_observations"]:
                self.remember(observation)

    def build(self, kind: str, **facts: Any) -> Any:
        return self.commands.build(self.root, kind, {"contract": self.contract, **facts})

    def scope(self, stage: Any) -> Any:
        if not isinstance(stage, str) or not stage:
            raise DeliveryInputError("stage must be a non-empty string")
        return self.build("scope", stage_id=stage)

    def current_selection(self) -> Any:
        if self.selection is None:
            self.selection = self.build("current-selection")
        return self.selection

    def remember(self, observation: dict[str, Any]) -> None:
        if (observation["contract_digest"] != self.digest
                or observation["project"] != self.contract["project"]):
            raise DeliveryInputError("prior observation belongs to another contract")
        kind = observation["observation_kind"]
        self.references.setdefault(kind, {})[observation["id"]] = observation

    def observation_id(self, reference: Any) -> str:
        if not isinstance(reference, str) or not reference.startswith("$"):
            raise DeliveryInputError("observation references must be $<observation_kind>")
        matches = self.references.get(reference[1:], {})
        if len(matches) != 1:
            raise DeliveryInputError(f"{reference}: expected one observation, found {len(matches)}")
        return next(iter(matches))

    def observation(self, recipe: Any, observed_at: str) -> dict[str, Any]:
        recipe = closed(recipe, {"kind", "source_kind", "source_reference", "evidence", "facts"},
                        label="observation")
        if not isinstance(recipe["facts"], dict):
            raise DeliveryInputError("observation facts must be an object")
        facts = dict(recipe["facts"])
        if "selection" in facts:
            if facts["selection"] != "$selection":
                raise DeliveryInputError("selection reference must be $selection")
            facts["selection"] = self.current_selection()
        if "merge_observation_id" in facts:
            facts["merge_observation_id"] = self.observation_id(facts["merge_observation_id"])
        for name in ("remote_branch_observation_ids", "local_branch_observation_ids",
                     "worktree_observation_ids"):
            if name in facts:
                facts[name] = [self.observation_id(item) for item in array(facts[name], name)]
        # A recipe cannot replace the compiler's context or provenance fields.
        reserved = {"kind", "self", "contract", "observation_kind", "source_kind", "source_reference",
                    "observed_at", "evidence"}
        if reserved & facts.keys():
            raise DeliveryInputError("observation facts contain reserved builder keys")
        result = self.build("observation", observation_kind=recipe["kind"],
                            source_kind=recipe["source_kind"],
                            source_reference=recipe["source_reference"],
                            evidence=recipe["evidence"], observed_at=observed_at, **facts)
        self.remember(result)
        return result

    def selections(self, recipes: Any, observed_at: str) -> list[Any]:
        observations = []
        for recipe in array(recipes, "selections"):
            recipe = closed(recipe, {"kind", "head", "tree", "review_ref", "test_ref",
                                     "source_kind", "source_reference", "evidence"},
                            {"acceptance_ref", "parents"}, label="selection")
            facts = {name: recipe[name] for name in ("head", "tree", "review_ref", "test_ref")}
            if recipe["kind"] == "initial":
                if "acceptance_ref" not in recipe or "parents" in recipe or self.selection is not None:
                    raise DeliveryInputError("initial selection needs acceptance_ref, no parents or prior link")
                self.selection = self.build("selected-output", **facts,
                                            acceptance_ref=recipe["acceptance_ref"])
            elif recipe["kind"] == "sync":
                if "parents" not in recipe or "acceptance_ref" in recipe:
                    raise DeliveryInputError("sync selection needs parents and no acceptance_ref")
                self.selection = self.build("sync-selection", **facts,
                    parents=recipe["parents"], prior_selection=self.current_selection())
            else:
                raise DeliveryInputError("selection kind must be initial or sync")
            observations.append(self.observation({
                "kind": "selected_output", "facts": {"selection": "$selection"},
                **{name: recipe[name] for name in ("source_kind", "source_reference", "evidence")}},
                observed_at))
        return observations

    def authority(self, recipe: Any, observed_at: str) -> Any:
        recipe = closed(recipe, {"stage_id", "authority_kind", "verdict", "reason_code", "evidence"},
                        label="authority")
        scope = self.scope(recipe["stage_id"])
        return self.build("authority-observation", scope_id=scope["id"],
            launch_id=self.custody["action_id"], observed_at=observed_at,
            **{name: recipe[name] for name in ("authority_kind", "verdict", "reason_code", "evidence")})

    def require_current(self) -> None:
        reply = self.commands.call(["workflow-state", "current-launch", "--repo-root", self.root,
            "--run-id", self.context["run_id"], "--action-id", self.custody["action_id"]])
        if (not isinstance(reply, dict)
                or set(reply) != {"action_id", "current", "current_action_id", "reason"}
                or reply["current"] is not True or reply["action_id"] != self.custody["action_id"]
                or reply["current_action_id"] != self.custody["action_id"]):
            raise DeliveryInputError(f"launch is not current: {json.dumps(reply, sort_keys=True)}")

    def compile(self, mode: str, recipe: Any) -> Any:
        optional = {"selections", "observations", "authority", "detail_state", "report_path", "notes"}
        required = {"observed_at", "requested_stage"} if mode == "checkpoint" else {
            "observed_at", "state", "result"}
        recipe = closed(recipe, required, optional, label=mode)
        if mode == "checkpoint" or recipe["state"] == "delivery_complete":
            self.require_current()
        observations = self.selections(recipe.get("selections", []), recipe["observed_at"])
        observations.extend(self.observation(item, recipe["observed_at"])
                            for item in array(recipe.get("observations", []), "observations"))
        authority = [self.authority(item, recipe["observed_at"])
                     for item in array(recipe.get("authority", []), "authority")]
        detail = {"detail_state": recipe.get("detail_state", "none"),
                  "report_path": recipe.get("report_path"), "notes": recipe.get("notes", "")}
        common = {"interface_version": 2, "issue": self.issue, "custody": self.custody,
                  "delivery_observations": sorted({item["id"]: item for item in observations}.values(),
                                                   key=lambda item: item["id"]),
                  "authority_observations": sorted({item["id"]: item for item in authority}.values(),
                                                    key=lambda item: item["id"]),
                  "reevaluation_evidence": [], **detail}
        if mode == "checkpoint":
            result = {**common, "contract_digest": self.digest, "requested_scope":
                      None if recipe["requested_stage"] is None else self.scope(recipe["requested_stage"])}
            return self.commands.validate("ship-checkpoint", result)
        legacy = closed(recipe["result"], {"state", "pr_url", "merge_sha", "issue_closed"}, label="result")
        if ((recipe["state"] == "delivery_complete" and legacy["state"] != "merged")
                or (recipe["state"] == "terminal_failed" and legacy["state"] not in ("stopped", "failed"))):
            raise DeliveryInputError("summary state disagrees with result state")
        result = {**common, "state": recipe["state"], "delivery_contract_digest": self.digest,
                  "historical_owner_result": {"issue": self.issue, **legacy,
                                              "discussion_items": [], **detail}}
        return self.commands.validate("ship-summary", result)


def compile_delivery(mode: str, context: Any, recipe: Any, *, prior: list[Any] | None = None,
                     commands: DeliveryCommands | None = None) -> Any:
    """Return only a validator-accepted payload; a caller still checkpoints/finishes it."""
    if mode not in {"checkpoint", "summary"}:
        raise DeliveryInputError("mode must be checkpoint or summary")
    return DeliveryCompiler(context, prior or [], commands or DeliveryCommands()).compile(mode, recipe)
