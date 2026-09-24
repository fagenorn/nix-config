"""Private delivery admission and transition boundary for workflow-state."""

from __future__ import annotations

import copy
from datetime import datetime
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any


WORKFLOW_DELIVERY_INTERFACE_VERSION = 1


class DeliveryRuntime:
    def __init__(self, *, notes_max_characters: int) -> None:
        if type(notes_max_characters) is not int or notes_max_characters < 1:
            raise ValueError("invalid delivery notes limit")
        self._notes_max = notes_max_characters
        self._model = self._load_model()
        self._builder = self._load_builder(self._model, notes_max_characters)
        self._projection = self._load_projection()

    @staticmethod
    def _load_model() -> object:
        entry = Path(__file__).with_name("delivery_model") / "__init__.py"
        if not entry.is_file():
            raise ValueError("delivery model is unavailable")
        name = "_workflow_delivery_model"
        spec = importlib.util.spec_from_file_location(
            name, entry, submodule_search_locations=[str(entry.parent)]
        )
        if spec is None or spec.loader is None:
            raise ValueError("delivery model is unavailable")
        for key in tuple(sys.modules):
            if key == name or key.startswith(name + "."):
                sys.modules.pop(key, None)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            if type(getattr(module, "MODEL_INTERFACE_VERSION", None)) is not int or module.MODEL_INTERFACE_VERSION != 1:
                raise ValueError("unsupported delivery model interface")
            return module
        except Exception:
            for key in tuple(sys.modules):
                if key == name or key.startswith(name + "."):
                    sys.modules.pop(key, None)
            raise

    @staticmethod
    def _load_projection() -> object:
        entry = Path(__file__).with_name("workflow_delivery_wire.py")
        if not entry.is_file():
            raise ValueError("workflow delivery projection is unavailable")
        name = "_workflow_delivery_wire"
        spec = importlib.util.spec_from_file_location(name, entry)
        if spec is None or spec.loader is None:
            raise ValueError("workflow delivery projection is unavailable")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            if getattr(module, "WORKFLOW_DELIVERY_WIRE_INTERFACE_VERSION", None) != 1:
                raise ValueError("unsupported workflow delivery projection interface")
            return module.DeliveryProjection()
        except Exception:
            sys.modules.pop(name, None)
            raise

    @staticmethod
    def _load_builder(model: object, notes_max: int) -> object:
        entry = Path(__file__).with_name("workflow_delivery_build.py")
        if not entry.is_file():
            raise ValueError("workflow delivery builder is unavailable")
        name = "_workflow_delivery_build"
        spec = importlib.util.spec_from_file_location(name, entry)
        if spec is None or spec.loader is None:
            raise ValueError("workflow delivery builder is unavailable")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            if getattr(module, "WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION", None) != 1:
                raise ValueError("unsupported workflow delivery builder interface")
            return module.DeliveryBuilder(model, notes_max_characters=notes_max)
        except Exception:
            sys.modules.pop(name, None)
            raise

    _BUILD_OUTPUT_KINDS = {"initial-intent": "authorization-intent", "scope": "scope-tuple",
                           "selected-output": "selected-output",
                           "observation": "delivery-observation",
                           "authority-observation": "authority-observation"}

    def build_delivery(self, kind: str, value: object, *, policy: dict[str, Any] | None
                       ) -> object:
        """Build one sealed delivery value and validate every object it carries."""
        result = self._builder.build(kind, value, policy=policy)
        if kind == "contract":
            if not isinstance(result, dict) or set(result) != {"contract", "initial_intent"}:
                raise ValueError("builder returned an invalid contract result")
            self.validate(result["contract"], "delivery-contract")
            self.validate(result["initial_intent"], "authorization-intent")
        elif kind == "authorization-chain":
            if not isinstance(result, dict) or set(result) != {"authorization_chain_digest"} \
                    or not isinstance(result["authorization_chain_digest"], str) \
                    or not result["authorization_chain_digest"].startswith("sha256:"):
                raise ValueError("builder returned an invalid authorization chain")
        elif kind in self._BUILD_OUTPUT_KINDS:
            self.validate(result, self._BUILD_OUTPUT_KINDS[kind])
        else:
            raise ValueError(f"unknown builder kind: {kind!r}")
        return result

    @property
    def model(self) -> object:
        """The private model dependency used by workflow-state validators."""
        return self._model

    def validate_issue_state(
        self, issue_value: dict[str, Any], *, issue: int,
        attempts: list[dict[str, Any]], updated_at: str,
    ) -> list[dict[str, Any]]:
        self.validate_issue_delivery(
            issue_value, issue=issue, attempts=attempts, updated_at=updated_at)
        records = (attempts, issue_value["delivery_remainders"])
        live = sum(record["state"] in {"active", "handed_off", "suspended"}
                   for values in records for record in values)
        if live > 1:
            raise ValueError("multiple nonterminal custody records")
        return [record["result"] for record in issue_value["delivery_remainders"]
                if record["result"] is not None]

    def validate_control_observations(
        self, request: dict[str, Any], issues: set[int],
    ) -> None:
        self._projection.validate_control_observations(request, issues, self._model)

    def validate_control_inputs(
        self, request: dict[str, Any], issues: set[int], tracker_issues: set[int],
    ) -> tuple[dict[str, Any], dict[int, Any]]:
        self.validate_control_observations(request, issues)
        forge = self.validate_issue_map(request["forge"], issues, "forge")
        contracts = self.validate_control_delivery(request, issues, tracker_issues)
        return forge, contracts

    def validate_direct_observations(self, request: dict[str, Any], issue: int) -> None:
        self._projection.validate_direct_observations(request, issue)

    def validate_direct_inputs(
        self, request: dict[str, Any], issue: int,
    ) -> dict[int, Any]:
        self.validate_direct_observations(request, issue)
        return self.validate_direct_delivery(request, issue)

    def validate_control_custody(
        self, state: dict[str, Any], request: dict[str, Any],
    ) -> set[tuple[int, str, int, int]]:
        unavailable: set[tuple[int, str, int, int]] = set()
        for observation in request["owners"]:
            issue_state = state["issues"].get(str(observation["issue"]))
            if issue_state is None:
                raise ValueError("unknown owner observation identity")
            custody = observation["custody"]
            records = (issue_state["attempts"] if custody["kind"] == "implementation"
                       else issue_state["delivery_remainders"])
            ordinal = custody.get("attempt", custody.get("remainder"))
            if ordinal > len(records) or custody["launch"] > len(records[ordinal - 1]["launches"]):
                raise ValueError("unknown owner observation identity")
            if ordinal == len(records) and custody["launch"] == len(records[-1]["launches"]):
                unavailable.add((observation["issue"], custody["kind"], ordinal,
                                 custody["launch"]))
        for observation in request["worktrees"]:
            recorded = observation["recorded"]
            if recorded is None:
                continue
            issue = observation["issue"]
            issue_state = state["issues"].get(str(issue))
            if issue_state is None:
                raise ValueError("recorded worktree has no ledger custody")
            _, current = self.current_custody(issue, issue_state)
            if current is None:
                records = issue_state["delivery_remainders"] or issue_state["attempts"]
                current = records[-1] if records else None
            if current is None or recorded["path"] != current["worktree"]:
                raise ValueError("recorded worktree path does not match ledger")
        return unavailable

    def owner_is_unavailable(
        self, issue_state: dict[str, Any] | None,
        unavailable: set[tuple[int, str, int, int]],
    ) -> bool:
        if issue_state is None:
            return False
        custody, record = self.current_custody(issue_state["issue"], issue_state)
        if custody is None or record is None:
            return False
        ordinal = custody.get("attempt", custody.get("remainder"))
        identity = (issue_state["issue"], custody["kind"], ordinal, custody["launch"])
        return record["state"] == "active" and identity in unavailable

    def delivery_policy(
        self, issue_state: dict[str, Any] | None, *, issue: int,
        request: dict[str, Any], source_kind: str, now: str,
        dispatch_permitted: bool, remainder_deadline: str,
        owner_unavailable: bool, tracker_halted: bool,
        recorded_worktree: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            recovery = self.recovery_policy(
                issue_state, issue=issue, request=request, source_kind=source_kind,
                now=now, dispatch_permitted=dispatch_permitted,
                remainder_deadline=remainder_deadline)
        except (TypeError, ValueError) as error:
            raise ValueError("delivery recovery refused") from error
        if recovery is not None:
            return recovery
        # Direct's historical remainder, and control's once a merged forge has
        # been reconciled and dispatch is permitted (per D13, D30).
        if (issue_state is not None
                and (source_kind == "direct"
                     or (source_kind == "control" and dispatch_permitted))
                and not issue_state["delivery_remainders"]
                and issue_state["attempts"]
                and issue_state["attempts"][-1]["state"]
                in {"merged", "completed", "stopped", "failed"}
                and self.historical_requested(
                    issue_state, **self.historical_request(request, issue,
                                                           source_kind=source_kind))):
            before = copy.deepcopy(issue_state["delivery"])
            reduction = self.apply_transition(
                issue_state, issue=issue, request=request,
                source_kind=source_kind, at_time=now)
            record = issue_state["attempts"][-1]
            remainder = self._create_first_remainder(
                issue_state, record, reduction, now=now,
                remainder_deadline=remainder_deadline)
            if remainder is not None:
                return {"operation": "resume", "changed": True,
                    "issue_state": issue_state,
                    "attempt": self._remainder_facade(issue_state, remainder),
                    "requirements": copy.deepcopy(reduction["requirements"]),
                    "uses_candidate": False, "desired": "resume",
                    "custody_kind": "remainder", "expired": False,
                    "reduction": reduction}
            return {"operation": "terminal",
                "changed": issue_state["delivery"] != before,
                "issue_state": issue_state, "attempt": record,
                "requirements": copy.deepcopy(reduction["requirements"]),
                "uses_candidate": False, "desired": "terminal",
                "expired": False, "reduction": reduction}
        if (issue_state is None or not issue_state["delivery_remainders"]
                or issue_state["delivery_remainders"][-1]["state"]
                not in {"active", "suspended"}):
            return None
        try:
            return self.remainder_policy(
                issue_state, now=now, owner_unavailable=owner_unavailable,
                dispatch_permitted=dispatch_permitted, tracker_halted=tracker_halted,
                recorded_worktree=recorded_worktree,
                remainder_deadline=remainder_deadline, issue=issue,
                request=request, source_kind=source_kind)
        except (TypeError, ValueError) as error:
            raise ValueError("remainder policy refused") from error

    def apply_direct_delivery(
        self, state: dict[str, Any], *, issue: int, request: dict[str, Any],
        policy: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        issue_state = state["issues"][str(issue)]
        before = copy.deepcopy(issue_state["delivery"])
        reduction = policy.get("reduction")
        if reduction is None:
            reduction = self.apply_transition(
                issue_state, issue=issue, request=request,
                source_kind="direct", at_time=request["now"])
        changed = policy["changed"] or issue_state["delivery"] != before
        if changed:
            state["updated_at"] = request["now"]
        return changed, reduction

    def complete_direct_policy(
        self, state: dict[str, Any], *, issue: int, request: dict[str, Any],
        policy: dict[str, Any], ledger_repo_root: str, run_id: str, reentry: str,
    ) -> tuple[bool, dict[str, Any]]:
        changed, reduction = self.apply_direct_delivery(
            state, issue=issue, request=request, policy=policy)
        issue_state = state["issues"][str(issue)]
        if policy["operation"] == "refuse":
            response = self._projection.direct_terminal(
                issue=issue, run_id=run_id, reason="failed",
                result=issue_state["outcome"], reentry=reentry)
        elif policy.get("custody_kind") == "remainder":
            response = self.remainder_response(
                ledger_repo_root=ledger_repo_root, run_id=run_id,
                issue_state=issue_state,
                remainder=issue_state["delivery_remainders"][-1],
                reduction=reduction)
        else:
            response = self.owner_response(
                ledger_repo_root=ledger_repo_root, run_id=run_id,
                issue_state=issue_state, attempt=policy["attempt"],
                launch_kind=policy["operation"], reduction=reduction)
        return changed, response

    def migrate_1_to_2(self, value: object) -> object:
        candidate = self.migrate(value, migration_contracts={})
        if isinstance(value, dict) and value.get("schema_version") == 1:
            candidate["schema_version"] = 2
            candidate.pop("admission", None)
            for issue in candidate.get("issues", {}).values():
                issue.pop("delivery", None)
                issue.pop("delivery_remainders", None)
        return candidate

    def validate(self, value: object, kind: str) -> dict[str, Any]:
        return self._model.validate_delivery_object(
            value, expected_kind=kind, notes_max_characters=self._notes_max
        )

    def custody_for_record(self, issue: int, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        return self._projection.custody_for_record(issue, kind, record)


    def current_custody(self, issue: int, issue_state: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        return self._projection.current_custody(issue, issue_state)


    def delivery_complete(self, issue_state: dict[str, Any]) -> bool:
        return self._projection.delivery_complete(issue_state)

    def historical_requested(
        self, issue_state: dict[str, Any], *, forge: object, contract: object,
        new_run: object,
    ) -> bool:
        return self._projection.historical_requested(
            issue_state, forge=forge, contract=contract, new_run=new_run)

    @staticmethod
    def historical_request(
        request: dict[str, Any], issue: int, *, source_kind: str,
    ) -> dict[str, Any]:
        """The historical predicate's inputs from a direct or control request shape."""
        if source_kind == "control":
            key = str(issue)
            return {"forge": request["forge"][key],
                    "contract": request["delivery_contracts"][key], "new_run": False}
        return {"forge": request.get("forge"), "contract": request["delivery_contract"],
                "new_run": request.get("new_run")}


    def remainder_policy(
        self, issue_state: dict[str, Any] | None, *, now: str,
        owner_unavailable: bool, dispatch_permitted: bool,
        tracker_halted: bool, recorded_worktree: dict[str, Any] | None,
        remainder_deadline: str, preview: dict[str, Any] | None = None,
        issue: int | None = None, request: dict[str, Any] | None = None,
        source_kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Resume the current delivery remainder without spending an attempt."""
        if issue_state is None or not issue_state["delivery_remainders"]:
            return None
        remainder = issue_state["delivery_remainders"][-1]
        if remainder["state"] not in {"active", "suspended"}:
            return None
        elapsed = self._time(now) >= self._time(remainder["deadline_at"])
        reaped = remainder["state"] == "active" and elapsed
        if reaped:
            self._projection.suspend_expired_remainder(
                issue_state, remainder, now)

        def result(operation: str, *, changed: bool = False,
                   requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            facade = self._remainder_facade(issue_state, remainder)
            return {"operation": operation, "changed": changed,
                    "issue_state": issue_state, "attempt": facade,
                    "requirements": [] if requirements is None else requirements,
                    "uses_candidate": False, "desired": "resume",
                    "custody_kind": "remainder", "expired": reaped,
                    "reduction": None}

        if remainder["state"] == "failed":
            if preview is None:
                preview = {"next_stage_id": None}
            return result("terminal", changed=True)
        if preview is None:
            if issue is None or request is None or source_kind is None:
                raise ValueError("remainder preview inputs are required")
            preview_state = copy.deepcopy(issue_state)
            candidate = copy.deepcopy(request)
            if source_kind == "control": candidate["requested_scopes"][str(issue)] = None
            else: candidate["requested_scope"] = None
            preview = self.apply_transition(
                preview_state, issue=issue, request=candidate,
                source_kind=source_kind, at_time=now)
        if owner_unavailable and remainder["state"] != "active":
            raise ValueError("owner_unavailable is not applicable")
        if remainder["state"] == "active" and not owner_unavailable:
            return result("idle")
        _ = tracker_halted
        if not dispatch_permitted:
            return result("idle", changed=reaped)
        requirements = self._projection.remainder_worktree_requirements(
            issue_state["delivery"]["contract"], preview["next_stage_id"],
            recorded_worktree, remainder["worktree"])
        if requirements:
            return result("observe", changed=reaped, requirements=requirements)
        if elapsed:
            remainder["deadline_at"] = remainder_deadline
        remainder["launches"].append({"kind": "resume", "owner": remainder["owner"],
            "worktree": remainder["worktree"], "at": now})
        remainder["state"], remainder["blocked_on"] = "active", None
        return result("resume", changed=True)

    def recovery_policy(
        self, issue_state: dict[str, Any] | None, *, issue: int,
        request: dict[str, Any],
        source_kind: str, now: str, dispatch_permitted: bool,
        remainder_deadline: str,
    ) -> dict[str, Any] | None:
        """Validate an explicit D21 proof and allocate only remainder two."""
        if issue_state is None:
            if self.request_values(request, issue,
                                   control=source_kind == "control").get("recovery") is not None:
                raise ValueError("recovery has no retained delivery")
            return None
        if issue_state["issue"] != issue:
            raise ValueError("recovery issue mismatch")
        values = self.request_values(request, issue, control=source_kind == "control")
        recovery = values["recovery"]
        remainders = issue_state["delivery_remainders"]
        if recovery is None:
            if len(remainders) == 1 and remainders[0]["state"] in {"failed", "stopped"}:
                record = remainders[0]
                return {"operation": "terminal", "changed": False,
                        "issue_state": issue_state,
                        "attempt": self._remainder_facade(issue_state, record),
                        "requirements": [], "uses_candidate": False,
                        "desired": "terminal", "custody_kind": "remainder",
                        "expired": False}
            return None
        recovery = self.validate_recovery(
            recovery, issue=issue, contract=values["contract"])
        assert recovery is not None
        if len(remainders) == 2:
            existing = remainders[1]
            if existing["recovery"] != recovery:
                raise ValueError("recovery proof was already consumed")
            reduction = self.transition(
                issue_state["delivery"], contract=values["contract"], at_time=now,
                custody=None, current_launch=None, requested_scope=None,
                source_kind=source_kind, authorization_intents=[],
                authority_observations=[], reevaluation_evidence=[],
                delivery_observations=[])
            operation = ("recover" if existing["state"] in
                         {"active", "handed_off", "suspended"} else "terminal")
            return {"operation": operation,
                    "changed": False, "issue_state": issue_state,
                    "attempt": self._remainder_facade(issue_state, existing),
                    "requirements": copy.deepcopy(reduction["requirements"]),
                    "uses_candidate": False, "desired": operation,
                    "custody_kind": "remainder", "expired": False,
                    "reduction": reduction}
        if len(remainders) != 1:
            raise ValueError("recovery requires exactly one prior remainder")
        prior = remainders[0]
        authentic = ((prior["state"] == "failed" and prior["result_source"] == "owner")
                     or (prior["state"] == "failed" and prior["result_source"] == "stalled"))
        if not authentic or prior["finished_at"] is None:
            raise ValueError("recovery requires a terminal failed first remainder")
        if self.current_custody(issue, issue_state) != (None, None):
            raise ValueError("recovery cannot replace active custody")

        null_request = copy.deepcopy(request)
        if source_kind == "control":
            null_request["requested_scopes"][str(issue)] = None
        else:
            null_request["requested_scope"] = None
        reduction = self.apply_transition(
            issue_state, issue=issue, request=null_request,
            source_kind=source_kind, at_time=now)
        stage_id = reduction["next_stage_id"]
        if stage_id is None or recovery["stage_id"] != stage_id:
            raise ValueError("recovery does not name the ready stage")
        contract = issue_state["delivery"]["contract"]
        stage = next(item for item in contract["stages"] if item["id"] == stage_id)
        if not stage["retryable"]:
            raise ValueError("recovery stage is not retryable")
        self._validate_recorded_worktree(
            prior, issue_state["delivery"], [], recovery["requested_scope"])
        scope_probe = self.transition(
            issue_state["delivery"], contract=contract, at_time=now,
            custody=None, current_launch=None,
            requested_scope=recovery["requested_scope"], source_kind=source_kind,
            authorization_intents=[], authority_observations=[],
            reevaluation_evidence=[], delivery_observations=[])
        if scope_probe["next_stage_id"] != stage_id:
            raise ValueError("recovery scope does not match the ready stage")

        intents = issue_state["delivery"]["authorization_intents"]
        observations = issue_state["delivery"]["authority_observations"]
        matches = [(intent, self._model.match_scope(
            contract, intent, recovery["requested_scope"],
            selected_outputs=issue_state["delivery"]["selected_outputs"],
            at_time=now, revocation_observations=observations)) for intent in intents]
        covering = [(intent, match) for intent, match in matches if match["matched"]]
        if not covering:
            raise ValueError("recovery scope has no current authorization")
        declared_ids = {match["scope_id"] for _, match in covering}
        scope_ids = declared_ids | {recovery["requested_scope"]["id"]}
        verdicts = [item for item in observations
                    if item["authority_kind"] != "intent_revocation"
                    and item["scope_id"] in scope_ids]
        latest_by_scope = {}
        for item in verdicts:
            key = item["scope_id"]
            current = latest_by_scope.get(key)
            if current is None or (item["observed_at"], item["id"]) > \
                    (current["observed_at"], current["id"]):
                latest_by_scope[key] = item
        if any(item["verdict"] in {"rejected", "unknown"}
               for item in latest_by_scope.values()):
            raise ValueError("recovery is blocked by unresolved authority")

        failure = recovery["failure"]
        absence = recovery["effect_absence"]
        launched = self._time(prior["launches"][-1]["at"])
        failed_at = self._time(failure["observed_at"])
        finished = self._time(prior["finished_at"])
        absent_at = self._time(absence["observed_at"])
        current = self._time(now)
        if not (launched <= failed_at <= finished <= absent_at <= current):
            raise ValueError("invalid recovery proof chronology")
        basis = recovery["basis"]
        if basis["kind"] == "changed_relevant_evidence":
            if not (failed_at < self._time(basis["observed_at"]) <= current):
                raise ValueError("recovery evidence is not newer than failure")
        else:
            candidates = [intent for intent, match in covering
                          if intent["id"] == basis["id"]]
            if (len(candidates) != 1
                    or self._time(candidates[0]["issued_at"]) <= failed_at):
                raise ValueError("recovery authorization is not newer than failure")
            if (basis["kind"] == "human_transient_retry"
                    and candidates[0]["source"]["kind"] != "explicit_user"):
                raise ValueError("human retry requires explicit user intent")
        if not dispatch_permitted:
            return {"operation": "idle", "changed": True,
                    "issue_state": issue_state,
                    "attempt": self._remainder_facade(issue_state, prior),
                    "requirements": [], "uses_candidate": False,
                    "desired": "recover", "custody_kind": "remainder",
                    "expired": False, "reduction": reduction}

        progress = self._model.canonical_digest({
            "pending": reduction["pending_stage_ids"],
            "postconditions": issue_state["delivery"]["postconditions"],
        })
        owner = f"{issue}:r2"
        remainder = {
            "remainder": 2, "contract_digest": recovery["contract_digest"],
            "source_attempt": prior["source_attempt"], "prior_remainder": 1,
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "owner": owner, "worktree": prior["worktree"], "state": "active",
            "launches": [{"kind": "fresh", "owner": owner,
                          "worktree": prior["worktree"], "at": now}],
            "deadline_at": remainder_deadline, "progress_token": progress,
            "blocked_on": None, "suspend_phase": None, "stalled_resumes": 0,
            "result": None, "result_source": None,
            "recovery": copy.deepcopy(recovery), "finished_at": None,
        }
        issue_state["delivery_remainders"].append(remainder)
        return {"operation": "recover", "changed": True,
                "issue_state": issue_state,
                "attempt": self._remainder_facade(issue_state, remainder),
                "requirements": copy.deepcopy(reduction["requirements"]),
                "uses_candidate": False, "desired": "recover",
                "custody_kind": "remainder", "expired": False,
                "reduction": reduction}

    def _remainder_facade(
        self, issue_state: dict[str, Any], remainder: dict[str, Any]
    ) -> dict[str, Any]:
        return self._projection.remainder_facade(issue_state, remainder)

    def occupied_count(
        self, state: dict[str, Any], *, at_time: str,
        unavailable: set[tuple[int, str, int, int]],
    ) -> int:
        count = 0
        for issue_state in state["issues"].values():
            custody, record = self.current_custody(issue_state["issue"], issue_state)
            if custody is None or record is None or record["state"] != "active":
                continue
            ordinal = custody.get("attempt", custody.get("remainder"))
            identity = (issue_state["issue"], custody["kind"], ordinal, custody["launch"])
            if self._time(at_time) < self._time(record["deadline_at"]) and identity not in unavailable:
                count += 1
        return count

    def next_deadline(self, state: dict[str, Any], issues: list[int]) -> str | None:
        values = []
        for issue in issues:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None:
                continue
            _, record = self.current_custody(issue, issue_state)
            if record is not None and record["state"] in {"active", "handed_off"}:
                values.append(record["deadline_at"])
        return min(values, key=self._time) if values else None

    def request_values(
        self, request: dict[str, Any], issue: int, *, control: bool
    ) -> dict[str, Any]:
        return self._projection.request_values(
            request, issue, control=control)

    @staticmethod
    def effective_contract(
        issue_state: dict[str, Any] | None, supplied: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """The contract that governs one issue: the installed one, else the supplied one.

        A null request contract means "none supplied", never "none governs": an
        installed contract keeps governing, and a supplied one must equal it (D10).
        """
        installed = None if issue_state is None else issue_state["delivery"]["contract"]
        if installed is None:
            return supplied
        if supplied is not None and supplied != installed:
            raise ValueError("delivery contract is immutable")
        return installed

    def apply_transition(
        self, issue_state: dict[str, Any], *, issue: int,
        request: dict[str, Any], source_kind: str, at_time: str,
    ) -> dict[str, Any]:
        values = self.request_values(request, issue, control=source_kind == "control")
        contract = self.effective_contract(issue_state, values["contract"])
        if contract is None:
            raise ValueError("delivery contract is required")
        custody, record = self.current_custody(issue, issue_state)
        binding_record = record
        if binding_record is None:
            retained = issue_state["delivery_remainders"] or issue_state["attempts"]
            binding_record = retained[-1] if retained else None
        self._validate_recorded_worktree(
            binding_record, issue_state["delivery"],
            values["delivery_observations"], values["requested_scope"])
        reduced = self.transition(
            issue_state["delivery"], contract=contract, at_time=at_time,
            custody=custody,
            current_launch=(record["state"] == "active" if record is not None else None),
            requested_scope=values["requested_scope"], source_kind=source_kind,
            authorization_intents=values["authorization_intents"],
            authority_observations=values["authority_observations"],
            reevaluation_evidence=values["reevaluation_evidence"],
            delivery_observations=values["delivery_observations"],
        )
        issue_state["delivery"] = reduced["next_delivery"]
        return reduced

    def response_block(self, issue_state: dict[str, Any], reduction: dict[str, Any]) -> dict[str, Any]:
        return self._projection.response_block(issue_state, reduction)


    def bootstrap(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._projection.bootstrap(state)


    def record_for_custody(
        self, issue_state: dict[str, Any], custody: dict[str, Any]
    ) -> dict[str, Any]:
        records = (issue_state["attempts"] if custody["kind"] == "implementation"
                   else issue_state["delivery_remainders"])
        ordinal = custody.get("attempt", custody.get("remainder"))
        if not records or ordinal != len(records):
            raise ValueError("custody is not current")
        record = records[ordinal - 1]
        expected = self.custody_for_record(issue_state["issue"], custody["kind"], record)
        if expected != custody or record["state"] != "active":
            raise ValueError("custody is not current")
        return record

    def prepare_report_transition(
        self, issue_state: dict[str, Any], report: dict[str, Any], *,
        source_kind: str, at_time: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        custody = report["custody"]
        record = self.record_for_custody(issue_state, custody)
        delivery = issue_state["delivery"]
        report_digest = report.get("contract_digest", report.get("delivery_contract_digest"))
        if delivery["contract_digest"] != report_digest:
            raise ValueError(f"{source_kind} contract mismatch")
        requested_scope = report.get("requested_scope") if source_kind == "checkpoint" else None
        reduced = self.apply_transition(
            issue_state, issue=issue_state["issue"], source_kind=source_kind,
            at_time=at_time,
            request={
                "delivery_contract": delivery["contract"],
                "authorization_intents": [],
                "authority_observations": report["authority_observations"],
                "reevaluation_evidence": report["reevaluation_evidence"],
                "delivery_observations": report["delivery_observations"],
                "requested_scope": requested_scope,
            },
        )
        accepted = sorted({item["id"] for name in
                           ("authority_observations", "reevaluation_evidence",
                            "delivery_observations") for item in report[name]})
        return record, reduced, accepted

    @staticmethod
    def _validate_recorded_worktree(
        record: dict[str, Any] | None, delivery: dict[str, Any],
        candidate_observations: list[dict[str, Any]],
        requested_scope: dict[str, Any] | None,
    ) -> None:
        """Bind worktree cleanup facts/actions to the custody record under lock."""
        observations = [
            item for item in (
                delivery["delivery_observations"] + candidate_observations
            ) if item["observation_kind"] == "worktree_absent"
        ]
        requests_cleanup = (
            requested_scope is not None
            and requested_scope["action"] == "remove_worktree"
        )
        if not observations and not requests_cleanup:
            return
        if record is None:
            raise ValueError("cleanup has no recorded custody worktree")
        stages = [stage for stage in delivery["contract"]["stages"]
                  if stage["kind"] == "remove_worktree"]
        if len(stages) != 1 or stages[0]["target_ref"] != {
            "kind": "literal", "value": record["worktree"]
        }:
            raise ValueError("cleanup worktree does not match recorded custody")
        if requests_cleanup and requested_scope["endpoint"] != {
            "kind": "literal", "value": record["worktree"]
        }:
            raise ValueError("cleanup scope does not match recorded custody")
        for item in observations:
            subject = item["subject"]
            if (subject["path"] != record["worktree"]
                    or subject["recorded_worktree_identity"] != record["worktree"]
                    or subject["probe_mode"] != "no_follow"
                    or subject["absent"] is not True):
                raise ValueError("cleanup observation does not match recorded custody")

    def remainder_response(self, **values: Any) -> dict[str, Any]:
        return self._projection.remainder_response(**values)


    def report_response(self, **values: Any) -> dict[str, Any]:
        return self._projection.report_response(**values)


    def checkpoint_response(self, common: dict[str, Any], reduction: dict[str, Any], **values: Any) -> dict[str, Any]:
        return self._projection.checkpoint_response(common, reduction, **values)


    def checkpoint_begin(
        self, issue_state: dict[str, Any], report: dict[str, Any], *, now: str
    ) -> dict[str, Any]:
        before = copy.deepcopy(issue_state["delivery"])
        record, reduction, accepted = self.prepare_report_transition(
            issue_state, report, source_kind="checkpoint", at_time=now)
        blocking = reduction["blocking"]
        stalled = False
        if report["custody"]["kind"] == "remainder":
            token = self._model.canonical_digest({
                "pending": reduction["pending_stage_ids"],
                "postconditions": issue_state["delivery"]["postconditions"],
            })
            if blocking is None:
                if record["progress_token"] != token:
                    record["stalled_resumes"] = 0
                record["suspend_phase"] = None
            else:
                record["stalled_resumes"] = (
                    record["stalled_resumes"] + 1
                    if record["suspend_phase"] is not None
                    and record["progress_token"] == token else 0)
                record["suspend_phase"] = 0
            record["progress_token"] = token
            if blocking is not None:
                stalled = record["stalled_resumes"] >= 3
                record["state"] = "failed" if stalled else "suspended"
                record["blocked_on"] = None if stalled else blocking["blocked_on"]
                if stalled:
                    record["result"] = {
                        "issue": issue_state["issue"], "state": "failed",
                        "pr_url": None, "merge_sha": None, "issue_closed": False,
                        "discussion_items": [], "detail_state": "none",
                        "report_path": None,
                        "notes": "Delivery remainder stalled without progress.",
                    }
                    record["result_source"] = "stalled"
                    record["finished_at"] = now
        return {"before": before, "record": record, "reduction": reduction,
                "accepted": accepted, "blocking": blocking, "stalled": stalled}

    def checkpoint_state(
        self, state: dict[str, Any], report: dict[str, Any], *, now: str,
        suspend_attempt: Any, ledger_repo_root: str, run_id: str,
    ) -> tuple[dict[str, Any], bool]:
        issue_state = state["issues"].get(str(report["issue"]))
        if issue_state is None:
            raise ValueError("unknown checkpoint issue")
        context = self.checkpoint_begin(issue_state, report, now=now)
        stalled = context["stalled"]
        if (context["blocking"] is not None
                and report["custody"]["kind"] == "implementation"):
            stalled = not suspend_attempt(
                context["record"], blocked_on=context["blocking"]["blocked_on"], now=now)
            if stalled:
                issue_state["outcome"] = copy.deepcopy(context["record"]["result"])
        state["updated_at"] = now
        return self.complete_checkpoint(
            context, ledger_repo_root=ledger_repo_root, run_id=run_id,
            issue_state=issue_state, report=report, stalled=stalled)

    def complete_checkpoint(
        self, context: dict[str, Any], *, ledger_repo_root: str, run_id: str,
        issue_state: dict[str, Any], report: dict[str, Any], stalled: bool,
    ) -> tuple[dict[str, Any], bool]:
        reduction, record = context["reduction"], context["record"]
        blocking = context["blocking"]
        common = self.report_response(
            ledger_repo_root=ledger_repo_root, run_id=run_id,
            issue=issue_state["issue"], record=record, report=report,
            delivery=issue_state["delivery"], reduction=reduction,
            accepted=context["accepted"])
        next_action = None
        if (not stalled and blocking is None
                and reduction["next_stage_id"] is not None):
            if report["custody"]["kind"] == "implementation":
                next_action = self.owner_response(
                    ledger_repo_root=ledger_repo_root, run_id=run_id,
                    issue_state=issue_state, attempt=record,
                    launch_kind="resume", reduction=reduction)
            else:
                next_action = self.remainder_response(
                    ledger_repo_root=ledger_repo_root, run_id=run_id,
                    issue_state=issue_state, remainder=record, reduction=reduction)
        response = self.checkpoint_response(
            common, reduction, stalled=stalled, blocking=blocking,
            next_action=next_action)
        changed = issue_state["delivery"] != context["before"] or blocking is not None
        return response, changed

    def finish_outcome(
        self, issue_state: dict[str, Any], record: dict[str, Any],
        report: dict[str, Any], reduction: dict[str, Any], common: dict[str, Any],
        *, now: str, remainder_deadline: str, ledger_repo_root: str, run_id: str,
    ) -> dict[str, Any]:
        if report["state"] == "delivery_complete":
            if reduction["completion_state"] != "delivery_complete":
                raise ValueError("delivery summary is incomplete")
            historical = report["historical_owner_result"]
            if historical is not None and report["custody"]["kind"] == "implementation":
                record.update(state=historical["state"], result=copy.deepcopy(historical),
                              finished_at=now, result_source="owner")
                issue_state["outcome"] = copy.deepcopy(historical)
            return {**common, "kind": "delivery_complete",
                    "pending_stage_ids": [], "state": "delivery_complete"}

        historical = report["historical_owner_result"]
        if historical is None:
            raise ValueError("failed summary requires historical owner result")
        record.update(state=historical["state"], result=copy.deepcopy(historical),
                      result_source="owner")
        if report["custody"]["kind"] == "implementation":
            record["finished_at"] = now
            issue_state["outcome"] = copy.deepcopy(historical)
        else:
            record["finished_at"] = now
        terminal = {**common, "kind": "terminal_failed", "state": "terminal_failed",
                    "result_source": "owner", "reason_code": "owner_reported_failure"}
        if not self._selection_observed(issue_state["delivery"]):
            # Before selection a failure belongs to the implementation retry
            # lane: a remainder here would be the one nonterminal custody and
            # block the retry (per D14).
            return terminal
        remainder = self._create_first_remainder(
            issue_state, record, reduction, now=now,
            remainder_deadline=remainder_deadline)
        if remainder is None:
            return terminal
        return self.remainder_response(
            ledger_repo_root=ledger_repo_root, run_id=run_id,
            issue_state=issue_state, remainder=remainder, reduction=reduction)

    @staticmethod
    def _selection_observed(delivery: dict[str, Any]) -> bool:
        selection = {stage["id"] for stage in delivery["contract"]["stages"]
                     if stage["kind"] == "select_reviewed_output"}
        return all(fact["state"] == "observed" for fact in delivery["stage_facts"]
                   if fact["stage_id"] in selection)

    def _create_first_remainder(
        self, issue_state: dict[str, Any], record: dict[str, Any],
        reduction: dict[str, Any], *, now: str, remainder_deadline: str,
    ) -> dict[str, Any] | None:
        if (not reduction["pending_stage_ids"] and not reduction["requirements"]
                or issue_state["delivery_remainders"]):
            return None
        contract = issue_state["delivery"]["contract"]
        next_stage = reduction["next_stage_id"]
        if next_stage is not None and not next(
            stage["retryable"] for stage in contract["stages"]
            if stage["id"] == next_stage):
            return None
        progress_token = self._model.canonical_digest({
            "pending": reduction["pending_stage_ids"],
            "postconditions": issue_state["delivery"]["postconditions"],
        })
        return self._projection.create_first_remainder(
            issue_state, record, reduction, now=now,
            deadline=remainder_deadline, progress_token=progress_token)

    def finish_state(
        self, state: dict[str, Any], report: dict[str, Any], *, now: str,
        remainder_deadline: str, ledger_repo_root: str, run_id: str,
    ) -> dict[str, Any]:
        issue = report["issue"]
        issue_state = state["issues"].get(str(issue))
        if issue_state is None:
            raise ValueError("unknown summary issue")
        record, reduction, accepted = self.prepare_report_transition(
            issue_state, report, source_kind="summary", at_time=now)
        common = self.report_response(
            ledger_repo_root=ledger_repo_root, run_id=run_id, issue=issue,
            record=record, report=report, delivery=issue_state["delivery"],
            reduction=reduction, accepted=accepted)
        response = self.finish_outcome(
            issue_state, record, report, reduction, common, now=now,
            remainder_deadline=remainder_deadline,
            ledger_repo_root=ledger_repo_root, run_id=run_id)
        state["updated_at"] = now
        return response

    def owner_response(self, **values: Any) -> dict[str, Any]:
        return self._projection.owner_response(**values)


    def control_summary(self, **values: Any) -> dict[str, Any]:
        return self._projection.control_summary(**values)


    def control_transitions(
        self, state: dict[str, Any], request: dict[str, Any], installing: set[int],
    ) -> tuple[dict[int, dict[str, Any]], bool]:
        """Fold delivery only where a contract governs or is being installed (D10)."""
        reductions = {}
        changed = False
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None or (issue_state["delivery"]["contract"] is None
                                       and issue not in installing):
                continue
            before = copy.deepcopy(issue_state["delivery"])
            reductions[issue] = self.apply_transition(
                issue_state, issue=issue, request=request,
                source_kind="control", at_time=request["now"])
            changed |= issue_state["delivery"] != before
        return reductions, changed

    def decorate_control(self, state: dict[str, Any], deltas: list[dict[str, Any]], actions: list[dict[str, Any]], reductions: dict[int, dict[str, Any]], dispatch_kinds: frozenset[str], *, ledger_repo_root: str) -> None:
        self._projection.decorate_control(state, deltas, actions, reductions, dispatch_kinds, ledger_repo_root=ledger_repo_root)


    @staticmethod
    def _time(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("invalid delivery time")
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        return parsed

    @staticmethod
    def _integer(value: object, *, minimum: int = 0) -> int:
        if type(value) is not int or value < minimum:
            raise ValueError("invalid delivery integer")
        return value

    def validate_recovery(
        self, value: object, *, issue: int, contract: object,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if contract is None:
            raise ValueError("recovery requires a delivery contract")
        value = self.validate(value, "delivery-recovery")
        scope = value["requested_scope"]
        if scope["target"]["issue"] != issue:
            raise ValueError("recovery scope issue mismatch")
        contract_value = self.validate(contract, "delivery-contract")
        digest = self._model.canonical_digest(contract_value)
        if value["contract_digest"] != digest:
            raise ValueError("recovery contract mismatch")
        return value

    def validate_delivery_inputs(
        self, *, issue: int, contract: object, intents: object,
        authority: object, reevaluation: object, observations: object,
        requested_scope: object,
    ) -> dict[str, Any] | None:
        arrays = (
            (intents, "authorization-intent"),
            (authority, "authority-observation"),
            (reevaluation, "reevaluation-evidence"),
            (observations, "delivery-observation"),
        )
        for values, kind in arrays:
            if not isinstance(values, list):
                raise ValueError("invalid delivery facts")
            ids = [self.validate(item, kind)["id"] for item in values]
            if ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError("delivery facts must be sorted and unique")
        if requested_scope is not None:
            self.validate(requested_scope, "scope-tuple")
        if contract is None:
            if any(values for values, _ in arrays) or requested_scope is not None:
                raise ValueError("delivery facts require a contract")
            return None
        contract = self.validate(contract, "delivery-contract")
        if contract["issue"] != issue:
            raise ValueError("delivery contract issue mismatch")
        digest, project = self._model.canonical_digest(contract), contract["project"]
        for item in intents:
            for declared in item["scopes"]:
                target = declared["target"]
                if target["issue"] != issue or any(
                    target[name] != project[name] for name in
                    ("project_id", "provider", "repository_id", "repository_slug")
                ):
                    raise ValueError("authorization target mismatch")
        for values in (authority, reevaluation, observations):
            for item in values:
                if item["contract_digest"] != digest:
                    raise ValueError("delivery fact contract mismatch")
                if item.get("project") is not None and item["project"] != project:
                    raise ValueError("delivery fact project mismatch")
        if requested_scope is not None:
            target = requested_scope["target"]
            if target["issue"] != issue or any(
                target[name] != project[name] for name in
                ("project_id", "provider", "repository_id", "repository_slug")
            ):
                raise ValueError("requested scope target mismatch")
        return copy.deepcopy(contract)

    @staticmethod
    def validate_issue_map(value: object, issues: set[int], label: str) -> dict[str, Any]:
        expected = {str(issue) for issue in issues}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError(f"{label} keys must exactly match requested issues")
        return value

    def validate_control_delivery(
        self, request: dict[str, Any], issues: set[int], tracker_issues: set[int]
    ) -> dict[int, Any]:
        contracts = self.validate_issue_map(request["delivery_contracts"], issues,
                                    "delivery contracts")
        if tracker_issues != issues:
            raise ValueError("tracker observations must match requested issues")
        names = ("authorization_intents", "authority_observations",
                 "reevaluation_evidence", "delivery_observations", "requested_scopes",
                 "recoveries")
        maps = {name: self.validate_issue_map(request[name], issues, name) for name in names}
        result = {}
        for issue in issues:
            key = str(issue)
            result[issue] = self.validate_delivery_inputs(
                issue=issue, contract=contracts[key], intents=maps["authorization_intents"][key],
                authority=maps["authority_observations"][key],
                reevaluation=maps["reevaluation_evidence"][key],
                observations=maps["delivery_observations"][key],
                requested_scope=maps["requested_scopes"][key])
            self.validate_recovery(maps["recoveries"][key], issue=issue,
                                   contract=contracts[key])
            if maps["recoveries"][key] is not None \
                    and maps["requested_scopes"][key] is not None:
                raise ValueError("recovery request scope must be null")
        return copy.deepcopy(result)

    def validate_direct_delivery(
        self, request: dict[str, Any], issue: int
    ) -> dict[int, Any]:
        contract = self.validate_delivery_inputs(
            issue=issue, contract=request["delivery_contract"],
            intents=request["authorization_intents"],
            authority=request["authority_observations"],
            reevaluation=request["reevaluation_evidence"],
            observations=request["delivery_observations"],
            requested_scope=request["requested_scope"])
        self.validate_recovery(request["recovery"], issue=issue,
                               contract=request["delivery_contract"])
        if request["recovery"] is not None and request["requested_scope"] is not None:
            raise ValueError("recovery request scope must be null")
        return {issue: copy.deepcopy(contract)}

    def validate_issue_delivery(
        self, issue_value: dict[str, Any], *, issue: int,
        attempts: list[dict[str, Any]], updated_at: str,
    ) -> None:
        remainders = issue_value.get("delivery_remainders")
        if not isinstance(remainders, list) or len(remainders) > 2:
            raise ValueError("invalid delivery remainders")
        delivery = issue_value.get("delivery")
        if not isinstance(delivery, dict) or set(delivery) != set(self.empty_delivery()):
            raise ValueError("invalid delivery schema")
        if delivery["contract"] is None:
            if delivery != self.empty_delivery() or remainders:
                raise ValueError("invalid absent delivery sentinel")
            return
        self.validate(delivery, "delivery")
        digest = self._model.canonical_digest(delivery["contract"])
        if delivery["contract"]["issue"] != issue or delivery["contract_digest"] != digest:
            raise ValueError("delivery contract mismatch")
        order = [stage["id"] for stage in delivery["contract"]["stages"]]
        updated = self._time(updated_at)
        for index, value in enumerate(remainders, start=1):
            required = {
                "remainder", "contract_digest", "source_attempt", "prior_remainder",
                "pending_stage_ids", "owner", "worktree", "state", "launches",
                "deadline_at", "progress_token", "blocked_on", "suspend_phase",
                "stalled_resumes", "result", "result_source", "recovery",
                "finished_at",
            }
            if not isinstance(value, dict) or set(value) != required:
                raise ValueError("invalid delivery remainder")
            if self._integer(value["remainder"], minimum=1) != index:
                raise ValueError("invalid remainder ordinal")
            if value["contract_digest"] != digest:
                raise ValueError("remainder contract mismatch")
            source = self._integer(value["source_attempt"], minimum=1)
            if source > len(attempts) or value["prior_remainder"] != (None if index == 1 else index - 1):
                raise ValueError("invalid remainder lineage")
            pending = value["pending_stage_ids"]
            if (not isinstance(pending, list) or pending != [x for x in order if x in pending]
                    or len(pending) != len(set(pending))):
                raise ValueError("invalid remainder pending stages")
            if not isinstance(value["owner"], str) or not value["owner"]:
                raise ValueError("invalid remainder owner")
            if not isinstance(value["worktree"], str) or not value["worktree"].startswith("/"):
                raise ValueError("invalid remainder worktree")
            if value["state"] not in {"active", "handed_off", "suspended", "stopped", "failed", "merged"}:
                raise ValueError("invalid remainder state")
            launches = value["launches"]
            if not isinstance(launches, list) or not launches:
                raise ValueError("invalid remainder launches")
            deadline = self._time(value["deadline_at"])
            for launch_index, launch in enumerate(launches):
                if (not isinstance(launch, dict)
                        or set(launch) != {"kind", "owner", "worktree", "at"}
                        or launch["kind"] != ("fresh" if launch_index == 0 else "resume")
                        or launch["owner"] != value["owner"]
                        or launch["worktree"] != value["worktree"]
                        or self._time(launch["at"]) > min(updated, deadline)):
                    raise ValueError("invalid remainder launch")
            if not isinstance(value["progress_token"], str) or not value["progress_token"]:
                raise ValueError("invalid remainder progress token")
            if value["blocked_on"] not in {None, "human_gate", "external", "transport", "owner_unavailable", "unknown"}:
                raise ValueError("invalid remainder blocker")
            if value["suspend_phase"] is not None:
                self._integer(value["suspend_phase"])
            if self._integer(value["stalled_resumes"]) > 3:
                raise ValueError("invalid remainder stall count")
            if (value["result"] is None) != (value["result_source"] is None):
                raise ValueError("invalid remainder result")
            nonterminal = value["state"] in {"active", "handed_off", "suspended"}
            if nonterminal != (value["result"] is None):
                raise ValueError("invalid remainder terminal state")
            if nonterminal != (value["finished_at"] is None):
                raise ValueError("invalid remainder finish time")
            if value["finished_at"] is not None:
                finished = self._time(value["finished_at"])
                if finished < self._time(launches[-1]["at"]) or finished > updated:
                    raise ValueError("invalid remainder finish time")
            if index == 1:
                if value["recovery"] is not None:
                    raise ValueError("first remainder cannot carry recovery")
            elif self.validate_recovery(value["recovery"], issue=issue,
                                        contract=delivery["contract"]) is None:
                raise ValueError("second remainder requires recovery")
            if value["state"] == "suspended":
                if value["blocked_on"] is None:
                    raise ValueError("suspended remainder requires blocker")
            elif value["blocked_on"] is not None:
                raise ValueError("only suspended remainder carries blocker")
            custody = {"kind": "remainder", "remainder": index,
                       "launch": len(launches),
                       "action_id": f"{issue}:r{index}:{len(launches)}"}
            self._model.validate_custody_ref(custody, issue=issue)

    def empty_delivery(self) -> dict[str, Any]:
        return {
            "contract": None,
            "contract_digest": None,
            "authorization_intents": [],
            "authorization_chain_digest": None,
            "authority_observations": [],
            "reevaluation_evidence": [],
            "authority_evaluation_consumptions": [],
            "delivery_observations": [],
            "selected_outputs": [],
            "stage_facts": [],
            "postconditions": {},
        }

    def migrate(self, value: object, *, migration_contracts: dict[int, object]) -> object:
        """Compose schema 1→2→3→4 on a detached copy without persisting."""
        if not isinstance(migration_contracts, dict):
            raise ValueError("invalid migration contracts")
        for issue, contract in migration_contracts.items():
            self._integer(issue, minimum=1)
            if contract is not None:
                checked = self.validate(contract, "delivery-contract")
                if checked["issue"] != issue:
                    raise ValueError("migration contract issue mismatch")
        candidate = copy.deepcopy(value)
        seen: set[int] = set()
        while isinstance(candidate, dict) and candidate.get("schema_version") != 4:
            version = candidate.get("schema_version")
            if type(version) is not int or version in seen or version not in {1, 2, 3}:
                raise ValueError("unsupported workflow state schema version")
            seen.add(version)
            issues = candidate.get("issues")
            if not isinstance(issues, dict):
                raise ValueError("invalid workflow issues")
            if version in {1, 2} and any(
                    not isinstance(issue, dict)
                    or set(issue) != {"issue", "attempts", "outcome"}
                    for issue in issues.values()):
                raise ValueError("invalid legacy issue schema")
            if version == 3:
                # Schema 4 adds the run's admission block; a schema-3 document
                # that already carries one is a hybrid, never a migration input.
                if "admission" in candidate:
                    raise ValueError("invalid schema-three admission")
                candidate["admission"] = None
                candidate["schema_version"] = 4
            elif version == 1:
                for issue in issues.values():
                    if isinstance(issue, dict) and isinstance(issue.get("attempts"), list):
                        for attempt in issue["attempts"]:
                            if isinstance(attempt, dict):
                                if any(name in attempt for name in
                                       ("blocked_on", "suspend_phase", "stalled_resumes")):
                                    raise ValueError("invalid schema-one attempt")
                                attempt.setdefault("blocked_on", None)
                                attempt.setdefault("suspend_phase", None)
                                attempt.setdefault("stalled_resumes", 0)
                candidate.setdefault("prior_run", None)
                candidate["schema_version"] = 2
            else:
                for issue in issues.values():
                    if isinstance(issue, dict):
                        issue.setdefault("delivery", self.empty_delivery())
                        issue.setdefault("delivery_remainders", [])
                candidate["schema_version"] = 3
        return candidate

    def _initial_delivery(
        self, contract: dict[str, Any], intents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        contract = copy.deepcopy(self.validate(contract, "delivery-contract"))
        intents = [copy.deepcopy(self.validate(item, "authorization-intent")) for item in intents]
        if not intents:
            raise ValueError("delivery contract requires its initial intent")
        if intents[0]["id"] != contract["initial_authorization_intent_id"]:
            raise ValueError("initial authorization intent mismatch")
        if self._model.canonical_digest(intents[0]) != contract["initial_authorization_intent_digest"]:
            raise ValueError("initial authorization intent digest mismatch")
        digest = self._model.canonical_digest(contract)
        facts = []
        for stage in contract["stages"]:
            fact = {
                "schema_version": 1,
                "kind": "delivery-stage-fact",
                "id": "",
                "contract_digest": digest,
                "stage_id": stage["id"],
                "state": "pending",
                "observation_id": None,
            }
            fact["id"] = self._model.canonical_digest(fact, omit_derived="id")
            facts.append(fact)
        postconditions = {
            name: {
                "state": "pending" if applicability == "required" else "not_applicable",
                "observation_id": None,
            }
            for name, applicability in contract["deliverable"]["obligations"].items()
        }
        delivery = {
            "contract": contract,
            "contract_digest": digest,
            "authorization_intents": intents,
            "authorization_chain_digest": self._model.canonical_digest(
                {"intent_ids": [item["id"] for item in intents]}
            ),
            "authority_observations": [],
            "reevaluation_evidence": [],
            "authority_evaluation_consumptions": [],
            "delivery_observations": [],
            "selected_outputs": [],
            "stage_facts": facts,
            "postconditions": postconditions,
        }
        return copy.deepcopy(self.validate(delivery, "delivery"))

    def transition(
        self,
        delivery: dict[str, Any],
        *,
        contract: dict[str, Any],
        at_time: str,
        custody: dict[str, Any] | None,
        current_launch: bool | None,
        requested_scope: dict[str, Any] | None,
        source_kind: str,
        authorization_intents: list[dict[str, Any]],
        authority_observations: list[dict[str, Any]],
        reevaluation_evidence: list[dict[str, Any]],
        delivery_observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return the model's complete detached persistable transition."""
        candidate = copy.deepcopy(delivery)
        if candidate == self.empty_delivery():
            candidate = self._initial_delivery(contract, authorization_intents)
            new_intents: list[dict[str, Any]] = []
        else:
            if candidate.get("contract") != contract:
                raise ValueError("delivery contract is immutable")
            new_intents = authorization_intents
        result = self._model.reduce_delivery(
            contract,
            candidate,
            evaluation={
                "at_time": at_time,
                "custody": copy.deepcopy(custody),
                "current_launch": current_launch,
                "requested_scope": copy.deepcopy(requested_scope),
                "source_kind": source_kind,
                "authorization_intents": copy.deepcopy(new_intents),
                "authority_observations": copy.deepcopy(authority_observations),
                "reevaluation_evidence": copy.deepcopy(reevaluation_evidence),
                "delivery_observations": copy.deepcopy(delivery_observations),
            },
        )
        result = copy.deepcopy(result)
        self.validate(result["next_delivery"], "delivery")
        return result


__all__ = ("WORKFLOW_DELIVERY_INTERFACE_VERSION", "DeliveryRuntime")
