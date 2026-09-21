"""Pure interface-2 workflow state and response projection.

This private helper has no I/O and grants no authority. DeliveryRuntime supplies
already-validated delivery reductions; this module correlates custody records,
validates owner/worktree request observations, and constructs response values.
"""

from __future__ import annotations

import copy
from typing import Any

WORKFLOW_DELIVERY_WIRE_INTERFACE_VERSION = 1
_LIVE_STATES = {"active", "handed_off", "suspended"}


class DeliveryProjection:
    """Project validated workflow state into closed interface-2 values."""

    @staticmethod
    def custody_for_record(issue: int, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        ordinal_name = "attempt" if kind == "implementation" else "remainder"
        ordinal = record[ordinal_name]
        middle = str(ordinal) if kind == "implementation" else f"r{ordinal}"
        return {"kind": kind, ordinal_name: ordinal, "launch": len(record["launches"]),
                "action_id": f"{issue}:{middle}:{len(record['launches'])}"}

    @staticmethod
    def delivery_complete(issue_state: dict[str, Any]) -> bool:
        delivery = issue_state.get("delivery")
        return (isinstance(delivery, dict) and delivery.get("contract") is not None
                and bool(delivery.get("postconditions"))
                and all(item["state"] in {"observed", "not_applicable"}
                        for item in delivery["postconditions"].values()))

    def current_custody(self, issue: int, issue_state: dict[str, Any]
                        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if self.delivery_complete(issue_state):
            return None, None
        live = [(kind, record)
                for kind, records in (("implementation", issue_state["attempts"]),
                                      ("remainder", issue_state["delivery_remainders"]))
                for record in records if record["state"] in _LIVE_STATES]
        if len(live) > 1:
            raise ValueError("multiple nonterminal custody records")
        if not live:
            return None, None
        kind, record = live[0]
        return self.custody_for_record(issue, kind, record), record

    @staticmethod
    def _worktree(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"issue", "recorded", "candidate"}:
            raise ValueError("invalid worktree observation")
        if type(value["issue"]) is not int or value["issue"] < 1:
            raise ValueError("invalid worktree issue")
        for name, states in (("recorded", {"matching_issue_branch", "absent", "mismatch"}),
                             ("candidate", {"available", "absent"})):
            item = value[name]
            if item is None:
                continue
            if not isinstance(item, dict) or set(item) != {"path", "state"}:
                raise ValueError(f"invalid {name} fields")
            if not isinstance(item["path"], str) or not item["path"].startswith("/"):
                raise ValueError(f"invalid {name} path")
            if item["state"] not in states:
                raise ValueError(f"invalid {name} state")
        return value

    @staticmethod
    def _owner(value: object, issues: set[int], model: object) -> tuple[str, tuple[Any, ...]]:
        if not isinstance(value, dict) or set(value) != {"event_id", "issue", "custody", "state"}:
            raise ValueError("invalid owner observation fields")
        if not isinstance(value["event_id"], str) or not value["event_id"]:
            raise ValueError("invalid owner event_id")
        issue = value["issue"]
        if type(issue) is not int or issue < 1:
            raise ValueError("invalid owner issue")
        if value["state"] != "unavailable":
            raise ValueError("invalid owner state")
        if issue not in issues:
            raise ValueError("owner observation outside requested issues")
        try:
            custody = model.validate_custody_ref(value["custody"], issue=issue)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid owner custody") from error
        ordinal = custody.get("attempt", custody.get("remainder"))
        return value["event_id"], (issue, custody["kind"], ordinal, custody["launch"])

    def validate_control_observations(self, request: dict[str, Any], issues: set[int],
                                      model: object) -> None:
        owners = request["owners"]
        if not isinstance(owners, list):
            raise ValueError("invalid owner observations")
        identities = [self._owner(item, issues, model) for item in owners]
        if len({item[0] for item in identities}) != len(identities):
            raise ValueError("duplicate owner event_id")
        if len({item[1] for item in identities}) != len(identities):
            raise ValueError("duplicate owner observation")
        worktrees = request["worktrees"]
        if not isinstance(worktrees, list):
            raise ValueError("invalid worktree observations")
        worktree_issues = [self._worktree(item)["issue"] for item in worktrees]
        if len(set(worktree_issues)) != len(worktree_issues):
            raise ValueError("duplicate worktree observation")
        if not set(worktree_issues) <= issues:
            raise ValueError("worktree observation outside requested issues")

    def validate_direct_observations(self, request: dict[str, Any], issue: int) -> None:
        item = request["worktree"]
        if item is not None and self._worktree(item)["issue"] != issue:
            raise ValueError("worktree observation does not match requested issue")

    @staticmethod
    def response_block(issue_state: dict[str, Any], reduction: dict[str, Any]) -> dict[str, Any]:
        delivery = issue_state["delivery"]
        return {"contract": copy.deepcopy(delivery["contract"]),
                "contract_digest": delivery["contract_digest"],
                "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
                "requirements": copy.deepcopy(reduction["requirements"]),
                "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
                "requested_scope": copy.deepcopy(reduction["requested_scope"])}

    def bootstrap(self, state: dict[str, Any]) -> dict[str, Any]:
        requirements = []
        for issue_key in sorted(state["issues"], key=int):
            issue_state = state["issues"][issue_key]
            if self.delivery_complete(issue_state):
                continue
            records = ([("implementation", item) for item in issue_state["attempts"]]
                       + [("remainder", item) for item in issue_state["delivery_remainders"]])
            if not records:
                continue
            live = [(kind, item) for kind, item in records if item["state"] in _LIVE_STATES]
            if len(live) > 1:
                raise ValueError("multiple nonterminal custody records")
            kind, record = (live[0] if live else records[-1]
                            if issue_state["delivery_remainders"]
                            else ("implementation", issue_state["attempts"][-1]))
            requirements.append({"issue": int(issue_key), "owner": record["owner"],
                "custody": self.custody_for_record(int(issue_key), kind, record),
                "recorded_worktree": record["worktree"]})
        return {"interface_version": 2, "kind": "workflow_bootstrap",
                "run_id": state["run_id"], "requirements": requirements}

    def remainder_response(self, *, ledger_repo_root: str, run_id: str,
                           issue_state: dict[str, Any], remainder: dict[str, Any],
                           reduction: dict[str, Any]) -> dict[str, Any]:
        return {"interface_version": 2, "kind": "delivery_remainder",
            "ledger_repo_root": ledger_repo_root, "run_id": run_id,
            "issue": issue_state["issue"], "source_attempt": remainder["source_attempt"],
            "owner": remainder["owner"],
            "custody": self.custody_for_record(issue_state["issue"], "remainder", remainder),
            "worktree": remainder["worktree"],
            "contract": copy.deepcopy(issue_state["delivery"]["contract"]),
            "contract_digest": issue_state["delivery"]["contract_digest"],
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "deadline_at": remainder["deadline_at"],
            "requirements": copy.deepcopy(reduction["requirements"]),
            "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
            "requested_scope": copy.deepcopy(reduction["requested_scope"])}

    @staticmethod
    def create_first_remainder(
        issue_state: dict[str, Any], record: dict[str, Any],
        reduction: dict[str, Any], *, now: str, deadline: str,
        progress_token: str,
    ) -> dict[str, Any]:
        owner = f"{issue_state['issue']}:r1"
        remainder = {
            "remainder": 1,
            "contract_digest": issue_state["delivery"]["contract_digest"],
            "source_attempt": record.get("attempt", record.get("source_attempt")),
            "prior_remainder": None,
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"]),
            "owner": owner, "worktree": record["worktree"], "state": "active",
            "launches": [{"kind": "fresh", "owner": owner,
                          "worktree": record["worktree"], "at": now}],
            "deadline_at": deadline, "progress_token": progress_token,
            "blocked_on": None, "suspend_phase": None, "stalled_resumes": 0,
            "result": None, "result_source": None, "recovery": None,
            "finished_at": None,
        }
        issue_state["delivery_remainders"].append(remainder)
        return remainder

    @staticmethod
    def suspend_expired_remainder(
        issue_state: dict[str, Any], remainder: dict[str, Any], now: str,
    ) -> None:
        remainder["state"], remainder["blocked_on"] = "suspended", "unknown"
        remainder["stalled_resumes"] = (
            remainder["stalled_resumes"] + 1
            if remainder["suspend_phase"] is not None else 0)
        remainder["suspend_phase"] = 0
        if remainder["stalled_resumes"] < 3:
            return
        remainder["state"], remainder["blocked_on"] = "failed", None
        remainder["result"] = {
            "issue": issue_state["issue"], "state": "failed",
            "pr_url": None, "merge_sha": None, "issue_closed": False,
            "discussion_items": [], "detail_state": "none",
            "report_path": None,
            "notes": "Delivery remainder stalled without progress.",
        }
        remainder["result_source"], remainder["finished_at"] = "stalled", now

    @staticmethod
    def remainder_worktree_requirements(
        contract: dict[str, Any], stage_id: str | None,
        recorded: dict[str, Any] | None, path: str,
    ) -> list[dict[str, Any]]:
        stage = (None if stage_id is None else next(
            item for item in contract["stages"] if item["id"] == stage_id))
        requirement = "not_required" if stage is None else stage["worktree_requirement"]
        state = None if recorded is None else recorded.get("state")
        if recorded is not None and recorded.get("path") != path:
            raise ValueError("recorded worktree path does not match remainder")
        if state == "mismatch":
            raise ValueError("recorded worktree does not match remainder")
        missing = (requirement == "matching_required" and state != "matching_issue_branch") \
            or (requirement == "cleanup_target"
                and state not in {"matching_issue_branch", "absent"})
        if requirement not in {"matching_required", "cleanup_target", "not_required"}:
            raise ValueError("invalid remainder worktree requirement")
        return [{"kind": "recorded_worktree", "path": path}] if missing else []

    @staticmethod
    def report_response(*, ledger_repo_root: str, run_id: str, issue: int,
                        record: dict[str, Any], report: dict[str, Any],
                        delivery: dict[str, Any], reduction: dict[str, Any],
                        accepted: list[str]) -> dict[str, Any]:
        return {"interface_version": 2, "ledger_repo_root": ledger_repo_root,
            "run_id": run_id, "issue": issue, "owner": record["owner"],
            "custody": copy.deepcopy(report["custody"]),
            "contract_digest": delivery["contract_digest"],
            "accepted_observation_ids": accepted,
            "pending_stage_ids": copy.deepcopy(reduction["pending_stage_ids"])}

    @staticmethod
    def checkpoint_response(common: dict[str, Any], reduction: dict[str, Any], *,
                            stalled: bool, blocking: dict[str, Any] | None,
                            next_action: dict[str, Any] | None) -> dict[str, Any]:
        if stalled:
            return {**common, "kind": "delivery_stalled", "state": "terminal_failed",
                    "stalled_resumes": 3, "result_source": "stalled",
                    "reason_code": "suspension_stalled_without_progress"}
        return {**common, "kind": "delivery_checkpointed", "next_action": next_action,
            "requirements": copy.deepcopy(reduction["requirements"]),
            "authority_evaluation": copy.deepcopy(reduction["authority_evaluation"]),
            "requested_scope": copy.deepcopy(reduction["requested_scope"]),
            "state": "suspended" if blocking is not None else "active",
            "blocked_on": None if blocking is None else blocking["blocked_on"]}

    def owner_response(self, *, ledger_repo_root: str, run_id: str,
                       issue_state: dict[str, Any], attempt: dict[str, Any],
                       launch_kind: str, reduction: dict[str, Any]) -> dict[str, Any]:
        custody = self.custody_for_record(attempt["issue"], "implementation", attempt)
        return {"interface_version": 2, "kind": "owner",
            "ledger_repo_root": ledger_repo_root, "run_id": run_id,
            "issue": attempt["issue"], "attempt": attempt["attempt"],
            "owner": attempt["owner"], "action_id": custody["action_id"],
            "launch_kind": "resume" if launch_kind == "resume" else launch_kind,
            "worktree": attempt["worktree"], "handoff_path": attempt["handoff_path"],
            "deadline_at": attempt["deadline_at"], "custody": custody,
            **self.response_block(issue_state, reduction)}

    @staticmethod
    def direct_terminal(*, issue: int, run_id: str, reason: str,
                        result: dict[str, Any] | None, reentry: str) -> dict[str, Any]:
        return {"interface_version": 2, "kind": "terminal", "issue": issue,
                "run_id": run_id, "source": "lifecycle", "reason": reason,
                "blockers": [], "result": copy.deepcopy(result), "reentry": reentry}

    def control_summary(self, *, issue: int, tracker: dict[str, Any],
                        issue_state: dict[str, Any] | None,
                        reduction: dict[str, Any] | None,
                        blockers: list[dict[str, Any]],
                        result_fields: tuple[str, ...]) -> dict[str, Any]:
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
        return {"issue": issue, "state": state_name, "custody": custody,
            "owner": None if latest is None else latest["owner"],
            "worktree": None if latest is None else latest["worktree"],
            "deadline_at": None if latest is None else latest["deadline_at"],
            "blocked_on": None if latest is None else latest["blocked_on"],
            "blockers": blockers, "result": result,
            "contract_digest": None if delivery is None else delivery["contract_digest"],
            "pending_stage_ids": [] if reduction is None else copy.deepcopy(reduction["pending_stage_ids"]),
            "requirements": (missing if delivery is None or delivery["contract"] is None
                             else ([] if reduction is None else copy.deepcopy(reduction["requirements"])))}

    @staticmethod
    def contractless_control(request: dict[str, Any], run_id: str) -> dict[str, Any]:
        summaries = []
        for issue in request["issues"]:
            requirement = {"kind": "delivery_contract", "subject_id": str(issue),
                           "reason_code": "delivery_contract_required", "detail_pointer": None}
            summaries.append({"issue": issue, "state": "queued", "custody": None,
                "owner": None, "worktree": None, "deadline_at": None,
                "blocked_on": None, "blockers": [], "result": None,
                "contract_digest": None, "pending_stage_ids": [],
                "requirements": [requirement]})
        return {"interface_version": 2, "run_id": run_id, "now": request["now"],
                "summaries": summaries, "deltas": [],
                "actions": [{"id": "finalize", "kind": "finalize"}],
                "next_deadline": None}

    def decorate_control(self, state: dict[str, Any], deltas: list[dict[str, Any]],
                         actions: list[dict[str, Any]], reductions: dict[int, dict[str, Any]],
                         dispatch_kinds: frozenset[str], *, ledger_repo_root: str) -> None:
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
                action.clear()
                action.update(self.remainder_response(
                    ledger_repo_root=ledger_repo_root, run_id=state["run_id"],
                    issue_state=issue_state, remainder=record,
                    reduction=reductions[issue_state["issue"]]))
                continue
            action["custody"] = custody
            action.update(self.response_block(issue_state, reductions[action["issue"]]))
