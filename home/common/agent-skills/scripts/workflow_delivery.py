"""Private delivery admission and transition boundary for workflow-state."""

from __future__ import annotations

import copy
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
from typing import Any


WORKFLOW_DELIVERY_INTERFACE_VERSION = 1


class DeliveryRuntime:
    """Load the lexical model and compute detached delivery transitions."""

    def __init__(self, *, notes_max_characters: int) -> None:
        if type(notes_max_characters) is not int or notes_max_characters < 1:
            raise ValueError("invalid delivery notes limit")
        self._notes_max = notes_max_characters
        self._model = self._load_model()

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

    @property
    def model(self) -> object:
        """The private model dependency used by workflow-state validators."""
        return self._model

    def validate(self, value: object, kind: str) -> dict[str, Any]:
        return self._model.validate_delivery_object(
            value, expected_kind=kind, notes_max_characters=self._notes_max
        )

    @staticmethod
    def custody_for_record(issue: int, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        ordinal_name = "attempt" if kind == "implementation" else "remainder"
        ordinal = record[ordinal_name]
        action_id = (f"{issue}:{ordinal}:{len(record['launches'])}"
                     if kind == "implementation" else
                     f"{issue}:r{ordinal}:{len(record['launches'])}")
        return {"kind": kind, ordinal_name: ordinal,
                "launch": len(record["launches"]), "action_id": action_id}

    def current_custody(
        self, issue: int, issue_state: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if self.delivery_complete(issue_state):
            return None, None
        live = [
            (kind, record)
            for kind, records in (("implementation", issue_state["attempts"]),
                                  ("remainder", issue_state["delivery_remainders"]))
            for record in records
            if record["state"] in {"active", "handed_off", "suspended"}
        ]
        if len(live) > 1:
            raise ValueError("multiple nonterminal custody records")
        if not live:
            return None, None
        kind, record = live[0]
        return self.custody_for_record(issue, kind, record), record

    @staticmethod
    def delivery_complete(issue_state: dict[str, Any]) -> bool:
        delivery = issue_state.get("delivery")
        return (isinstance(delivery, dict) and delivery.get("contract") is not None
                and bool(delivery.get("postconditions"))
                and all(item["state"] in {"observed", "not_applicable"}
                        for item in delivery["postconditions"].values()))

    def remainder_policy(
        self, issue_state: dict[str, Any] | None, *, now: str,
        owner_unavailable: bool, dispatch_permitted: bool,
        tracker_halted: bool, recorded_worktree: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Resume the current delivery remainder without spending an attempt."""
        if issue_state is None or not issue_state["delivery_remainders"]:
            return None
        remainder = issue_state["delivery_remainders"][-1]
        if remainder["state"] not in {"active", "suspended"}:
            return None
        expired = (remainder["state"] == "active"
                   and self._time(now) >= self._time(remainder["deadline_at"]))
        if expired:
            remainder["state"], remainder["blocked_on"] = "suspended", "unknown"

        def result(operation: str, *, changed: bool = False,
                   requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            facade = {"issue": issue_state["issue"],
                "attempt": remainder["source_attempt"], "state": remainder["state"],
                "owner": remainder["owner"], "worktree": remainder["worktree"],
                "handoff_path": None, "deadline_at": remainder["deadline_at"],
                "launches": remainder["launches"]}
            return {"operation": operation, "changed": changed,
                    "issue_state": issue_state, "attempt": facade,
                    "requirements": [] if requirements is None else requirements,
                    "uses_candidate": False, "desired": "resume",
                    "custody_kind": "remainder", "expired": False}

        if owner_unavailable and remainder["state"] != "active":
            raise ValueError("owner_unavailable is not applicable")
        if remainder["state"] == "active" and not owner_unavailable:
            return result("idle")
        if tracker_halted:
            return result("terminal", changed=expired)
        if not dispatch_permitted:
            return result("idle", changed=expired)
        if (recorded_worktree is None
                or recorded_worktree.get("path") != remainder["worktree"]
                or recorded_worktree.get("state") != "matching_issue_branch"):
            return result("observe", changed=expired, requirements=[
                {"kind": "recorded_worktree", "path": remainder["worktree"]}])
        remainder["launches"].append({"kind": "resume", "owner": remainder["owner"],
            "worktree": remainder["worktree"], "at": now})
        remainder["state"], remainder["blocked_on"] = "active", None
        return result("resume", changed=True)

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

    @staticmethod
    def request_values(
        request: dict[str, Any], issue: int, *, control: bool
    ) -> dict[str, Any]:
        if not control:
            names = ("delivery_contract", "authorization_intents",
                     "authority_observations", "reevaluation_evidence",
                     "delivery_observations", "requested_scope")
            values = {name: request[name] for name in names}
            values["contract"] = values.pop("delivery_contract")
            return values
        key = str(issue)
        return {
            "contract": request["delivery_contracts"][key],
            "authorization_intents": request["authorization_intents"][key],
            "authority_observations": request["authority_observations"][key],
            "reevaluation_evidence": request["reevaluation_evidence"][key],
            "delivery_observations": request["delivery_observations"][key],
            "requested_scope": request["requested_scopes"][key],
        }

    def apply_transition(
        self, issue_state: dict[str, Any], *, issue: int,
        request: dict[str, Any], source_kind: str, at_time: str,
    ) -> dict[str, Any]:
        values = self.request_values(request, issue, control=source_kind == "control")
        if values["contract"] is None:
            raise ValueError("delivery contract is required")
        custody, record = self.current_custody(issue, issue_state)
        reduced = self.transition(
            issue_state["delivery"], contract=values["contract"], at_time=at_time,
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

    @staticmethod
    def response_block(
        issue_state: dict[str, Any], reduction: dict[str, Any]
    ) -> dict[str, Any]:
        delivery = issue_state["delivery"]
        return {
            "contract": copy.deepcopy(delivery["contract"]),
            "contract_digest": delivery["contract_digest"],
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "requirements": copy.deepcopy(reduction["requirements"]),
            "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
            "requested_scope": copy.deepcopy(reduction["requested_scope"]),
        }

    def bootstrap(self, state: dict[str, Any]) -> dict[str, Any]:
        requirements = []
        for issue_key in sorted(state["issues"], key=int):
            issue_state = state["issues"][issue_key]
            if self.delivery_complete(issue_state):
                continue
            records = ([('implementation', item) for item in issue_state["attempts"]]
                       + [('remainder', item) for item in issue_state["delivery_remainders"]])
            if not records:
                continue
            live = [(kind, item) for kind, item in records
                    if item["state"] in {"active", "handed_off", "suspended"}]
            if len(live) > 1:
                raise ValueError("multiple nonterminal custody records")
            kind, record = (live[0] if live else
                            records[-1] if issue_state["delivery_remainders"] else
                            ("implementation", issue_state["attempts"][-1]))
            requirements.append({
                "issue": int(issue_key), "owner": record["owner"],
                "custody": self.custody_for_record(int(issue_key), kind, record),
                "recorded_worktree": record["worktree"],
            })
        return {"interface_version": 2, "kind": "workflow_bootstrap",
                "run_id": state["run_id"], "requirements": requirements}

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

    def remainder_response(
        self, *, ledger_repo_root: str, run_id: str,
        issue_state: dict[str, Any], remainder: dict[str, Any],
        reduction: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "interface_version": 2, "kind": "delivery_remainder",
            "ledger_repo_root": ledger_repo_root, "run_id": run_id,
            "issue": issue_state["issue"],
            "source_attempt": remainder["source_attempt"],
            "owner": remainder["owner"],
            "custody": self.custody_for_record(issue_state["issue"], "remainder", remainder),
            "worktree": remainder["worktree"],
            "contract": copy.deepcopy(issue_state["delivery"]["contract"]),
            "contract_digest": issue_state["delivery"]["contract_digest"],
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "deadline_at": remainder["deadline_at"],
            "requirements": copy.deepcopy(reduction["requirements"]),
            "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
            "requested_scope": copy.deepcopy(reduction["requested_scope"]),
        }

    @staticmethod
    def report_response(
        *, ledger_repo_root: str, run_id: str, issue: int,
        record: dict[str, Any], report: dict[str, Any], delivery: dict[str, Any],
        reduction: dict[str, Any], accepted: list[str],
    ) -> dict[str, Any]:
        return {
            "interface_version": 2, "ledger_repo_root": ledger_repo_root,
            "run_id": run_id, "issue": issue, "owner": record["owner"],
            "custody": copy.deepcopy(report["custody"]),
            "contract_digest": delivery["contract_digest"],
            "accepted_observation_ids": accepted,
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
        }

    @staticmethod
    def checkpoint_response(
        common: dict[str, Any], reduction: dict[str, Any], *,
        stalled: bool, blocking: dict[str, Any] | None,
        next_action: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if stalled:
            return {
                **common, "kind": "delivery_stalled", "state": "terminal_failed",
                "stalled_resumes": 3, "result_source": "stalled",
                "reason_code": "suspension_stalled_without_progress",
            }
        return {
            **common, "kind": "delivery_checkpointed", "next_action": next_action,
            "requirements": copy.deepcopy(reduction["requirements"]),
            "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
            "requested_scope": copy.deepcopy(reduction["requested_scope"]),
            "state": "suspended" if blocking is not None else "active",
            "blocked_on": None if blocking is None else blocking["blocked_on"],
        }

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
        return {"before": before, "record": record, "reduction": reduction,
                "accepted": accepted, "blocking": blocking, "stalled": stalled}

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
        terminal = {**common, "kind": "terminal_failed", "state": "terminal_failed",
                    "result_source": "owner", "reason_code": "owner_reported_failure"}
        if (not reduction["pending_stage_ids"] and not reduction["requirements"]
                or len(issue_state["delivery_remainders"]) >= 2):
            return terminal
        number = len(issue_state["delivery_remainders"]) + 1
        contract = issue_state["delivery"]["contract"]
        next_stage = reduction["next_stage_id"]
        if next_stage is not None and not next(
            stage["retryable"] for stage in contract["stages"]
            if stage["id"] == next_stage):
            return terminal
        progress_token = self._model.canonical_digest({
            "pending": reduction["pending_stage_ids"],
            "postconditions": issue_state["delivery"]["postconditions"],
        })
        if number == 2 and issue_state["delivery_remainders"][-1]["progress_token"] == progress_token:
            return terminal
        owner = f"{issue_state['issue']}:r{number}"
        remainder = {
            "remainder": number,
            "contract_digest": issue_state["delivery"]["contract_digest"],
            "source_attempt": (report["custody"].get("attempt")
                               or record["source_attempt"]),
            "prior_remainder": None if number == 1 else number - 1,
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "owner": owner, "worktree": record["worktree"], "state": "active",
            "launches": [{"kind": "fresh", "owner": owner,
                          "worktree": record["worktree"], "at": now}],
            "deadline_at": remainder_deadline,
            "progress_token": progress_token,
            "blocked_on": None, "suspend_phase": None, "stalled_resumes": 0,
            "result": None, "result_source": None,
        }
        issue_state["delivery_remainders"].append(remainder)
        return self.remainder_response(
            ledger_repo_root=ledger_repo_root, run_id=run_id,
            issue_state=issue_state, remainder=remainder, reduction=reduction)

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

    def owner_response(
        self, *, ledger_repo_root: str, run_id: str,
        issue_state: dict[str, Any], attempt: dict[str, Any],
        launch_kind: str, reduction: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "interface_version": 2, "kind": "owner",
            "ledger_repo_root": ledger_repo_root, "run_id": run_id,
            "issue": attempt["issue"], "attempt": attempt["attempt"],
            "owner": attempt["owner"],
            "action_id": self.custody_for_record(
                attempt["issue"], "implementation", attempt)["action_id"],
            "launch_kind": "resume" if launch_kind == "resume" else launch_kind,
            "worktree": attempt["worktree"], "handoff_path": attempt["handoff_path"],
            "deadline_at": attempt["deadline_at"],
            "custody": self.custody_for_record(attempt["issue"], "implementation", attempt),
            **self.response_block(issue_state, reduction),
        }

    def control_summary(
        self, *, issue: int, tracker: dict[str, Any],
        issue_state: dict[str, Any] | None, reduction: dict[str, Any] | None,
        blockers: list[dict[str, Any]], result_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        latest_kind = None
        latest = None
        if issue_state is not None:
            custody, live = self.current_custody(issue, issue_state)
            if live is not None:
                latest_kind, latest = custody["kind"], live
            elif not self.delivery_complete(issue_state) and issue_state["delivery_remainders"]:
                latest_kind, latest = "remainder", issue_state["delivery_remainders"][-1]
            elif not self.delivery_complete(issue_state) and issue_state["attempts"]:
                latest_kind, latest = "implementation", issue_state["attempts"][-1]
        if latest is None:
            state_name = ("closed" if tracker["state"] == "closed" else
                          "fogged" if tracker["decision_blockers"] else
                          "blocked" if tracker["open_blockers"] else "queued")
        else:
            state_name, blockers = latest["state"], []
        result = None if latest is None or latest["result"] is None else {
            field: copy.deepcopy(latest["result"][field]) for field in result_fields}
        custody = None if latest is None else self.custody_for_record(issue, latest_kind, latest)
        delivery = None if issue_state is None else issue_state["delivery"]
        missing = [{"kind": "delivery_contract", "subject_id": str(issue),
                    "reason_code": "delivery_contract_required", "detail_pointer": None}]
        return {
            "issue": issue, "state": state_name, "custody": custody,
            "owner": None if latest is None else latest["owner"],
            "worktree": None if latest is None else latest["worktree"],
            "deadline_at": None if latest is None else latest["deadline_at"],
            "blocked_on": None if latest is None else latest["blocked_on"],
            "blockers": blockers, "result": result,
            "contract_digest": None if delivery is None else delivery["contract_digest"],
            "pending_stage_ids": [] if reduction is None else copy.deepcopy(reduction["pending_stage_ids"]),
            "requirements": (missing if delivery is None or delivery["contract"] is None
                             else ([] if reduction is None else copy.deepcopy(reduction["requirements"]))),
        }

    @staticmethod
    def contractless_control(request: dict[str, Any], run_id: str) -> dict[str, Any]:
        summaries = []
        for issue in request["issues"]:
            requirement = {"kind": "delivery_contract", "subject_id": str(issue),
                           "reason_code": "delivery_contract_required",
                           "detail_pointer": None}
            summaries.append({
                "issue": issue, "state": "queued", "custody": None,
                "owner": None, "worktree": None, "deadline_at": None,
                "blocked_on": None, "blockers": [], "result": None,
                "contract_digest": None, "pending_stage_ids": [],
                "requirements": [requirement],
            })
        return {"interface_version": 2, "run_id": run_id, "now": request["now"],
                "summaries": summaries, "deltas": [],
                "actions": [{"id": "finalize", "kind": "finalize"}],
                "next_deadline": None}

    def control_transitions(
        self, state: dict[str, Any], request: dict[str, Any]
    ) -> tuple[dict[int, dict[str, Any]], bool]:
        reductions = {}
        changed = False
        for issue in request["issues"]:
            issue_state = state["issues"].get(str(issue))
            if issue_state is None:
                continue
            before = copy.deepcopy(issue_state["delivery"])
            reductions[issue] = self.apply_transition(
                issue_state, issue=issue, request=request,
                source_kind="control", at_time=request["now"])
            changed |= issue_state["delivery"] != before
        return reductions, changed

    def decorate_control(
        self, state: dict[str, Any], deltas: list[dict[str, Any]],
        actions: list[dict[str, Any]], reductions: dict[int, dict[str, Any]],
        dispatch_kinds: frozenset[str], *, ledger_repo_root: str,
    ) -> None:
        for delta in deltas:
            issue_state = state["issues"].get(str(delta["issue"]))
            custody, _ = ((None, None) if issue_state is None else
                          self.current_custody(delta["issue"], issue_state))
            if custody is None and issue_state is not None and delta.get("attempt"):
                custody = self.custody_for_record(
                    delta["issue"], "implementation",
                    issue_state["attempts"][delta["attempt"] - 1])
            delta.pop("attempt", None)
            delta["custody"] = custody
        for action in actions:
            if action["kind"] not in dispatch_kinds:
                continue
            issue_state = state["issues"][str(action["issue"])]
            custody, record = self.current_custody(action["issue"], issue_state)
            if custody is not None and custody["kind"] == "remainder":
                action.clear(); action.update(self.remainder_response(
                    ledger_repo_root=ledger_repo_root, run_id=state["run_id"],
                    issue_state=issue_state, remainder=record,
                    reduction=reductions[issue_state["issue"]]))
                continue
            action["custody"] = custody
            action.update(self.response_block(issue_state, reductions[action["issue"]]))

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
        if any(value is not None for value in contracts.values()) and tracker_issues != issues:
            raise ValueError("tracker observations must match requested issues")
        names = ("authorization_intents", "authority_observations",
                 "reevaluation_evidence", "delivery_observations", "requested_scopes")
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
                "stalled_resumes", "result", "result_source",
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
        """Compose schema 1→2→3 on a detached copy without persisting."""
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
        while isinstance(candidate, dict) and candidate.get("schema_version") != 3:
            version = candidate.get("schema_version")
            if type(version) is not int or version in seen or version not in {1, 2}:
                raise ValueError("unsupported workflow state schema version")
            seen.add(version)
            issues = candidate.get("issues")
            if not isinstance(issues, dict):
                raise ValueError("invalid workflow issues")
            if any(not isinstance(issue, dict)
                   or set(issue) != {"issue", "attempts", "outcome"}
                   for issue in issues.values()):
                raise ValueError("invalid legacy issue schema")
            if version == 1:
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
