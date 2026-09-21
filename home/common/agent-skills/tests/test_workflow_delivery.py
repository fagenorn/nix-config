from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

from ._delivery_model_fixtures import (
    cleanup_contract_and_delivery, contract_and_delivery_for_stage, custody,
    observation, rebind_contract, seal, selection, stage_scope,
)

SCRIPTS = Path(__file__).parents[1] / "scripts"
ENTRY = SCRIPTS / "workflow_delivery.py"
NOW = "2026-09-21T00:00:00Z"


def runtime(name):
    spec = importlib.util.spec_from_file_location(name, ENTRY)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {ENTRY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.DeliveryRuntime(notes_max_characters=10_000)


def remainder_issue(delivery):
    record = {"remainder": 1, "contract_digest": delivery["contract_digest"],
        "source_attempt": 1, "prior_remainder": None, "pending_stage_ids": [],
        "owner": "151:r1", "worktree": "/worktree", "state": "suspended",
        "launches": [{"kind": "fresh", "owner": "151:r1",
                      "worktree": "/worktree", "at": NOW}],
        "deadline_at": "2026-09-21T03:00:00Z", "progress_token": "token",
        "blocked_on": "external", "suspend_phase": 0, "stalled_resumes": 0,
        "result": None, "result_source": None, "recovery": None,
        "finished_at": None}
    return {"issue": 151, "attempts": [], "outcome": None,
            "delivery": copy.deepcopy(delivery), "delivery_remainders": [record]}


def direct_values(contract, facts=(), scope=None):
    return {"delivery_contract": contract, "authorization_intents": [],
        "authority_observations": [], "reevaluation_evidence": [],
        "delivery_observations": list(facts), "requested_scope": scope,
        "recovery": None}


class WorkflowDeliveryRuntimeTest(unittest.TestCase):
    def test_remainder_reentry_uses_ready_stage_worktree_requirement(self):
        active = runtime("workflow_delivery_reentry_requirement_test")
        _, delivery = cleanup_contract_and_delivery(active.model)
        common = {"now": "2026-09-21T00:01:00Z", "owner_unavailable": False,
            "dispatch_permitted": True,
            "remainder_deadline": "2026-09-21T03:01:00Z"}
        for stage, recorded in (("close", None),
                ("worktree", {"path": "/worktree", "state": "absent"})):
            result = active.remainder_policy(remainder_issue(delivery),
                tracker_halted=True, recorded_worktree=recorded,
                preview={"next_stage_id": stage}, **common)
            self.assertEqual((result["operation"], result["attempt"]["state"],
                len(result["attempt"]["launches"])), ("resume", "active", 2))
        state = remainder_issue(delivery); before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            active.remainder_policy(state, tracker_halted=False,
                recorded_worktree={"path": "/worktree", "state": "mismatch"},
                preview={"next_stage_id": "worktree"}, **common)
        self.assertEqual(state, before)

    def test_public_historical_merge_folds_facts_before_terminal_replay(self):
        active = runtime("workflow_delivery_historical_merge_test")
        contract, delivery, _ = contract_and_delivery_for_stage(active.model, "select")
        issue = {"issue": 151, "attempts": [{"attempt": 1, "state": "merged",
            "worktree": "/worktree", "launches": [{"kind": "fresh"}]}],
            "outcome": None, "delivery": delivery, "delivery_remainders": []}
        selected = selection(active.model, active.model.canonical_digest(contract))
        request = direct_values(contract, [observation(active.model, contract,
            "selected_output", {"selected_output": selected})])
        policy = active.delivery_policy(issue, issue=151, request=request,
            source_kind="direct", now="2026-09-21T00:00:02Z",
            dispatch_permitted=True, remainder_deadline="2026-09-21T03:00:02Z",
            owner_unavailable=False, tracker_halted=False,
            recorded_worktree={"path": "/worktree", "state": "matching_issue_branch"})
        self.assertEqual((policy["operation"], issue["attempts"][0]["state"],
            issue["delivery_remainders"][0]["owner"],
            policy["reduction"]["pending_stage_ids"][0]),
            ("resume", "merged", "151:r1", "publish"))

    def test_cleanup_facts_bind_exact_recorded_worktree(self):
        active = runtime("workflow_delivery_worktree_binding_test")
        contract, delivery = cleanup_contract_and_delivery(active.model)
        worktree = "/owned/worktree"
        next(s for s in contract["stages"] if s["kind"] == "remove_worktree" \
            )["target_ref"]["value"] = worktree
        delivery = rebind_contract(active.model, contract, delivery)
        issue = {"issue": 151, "attempts": [{"attempt": 1,
            "launches": [{"kind": "fresh"}], "state": "active",
            "worktree": worktree}], "delivery_remainders": [], "delivery": delivery}
        report = {"custody": custody(),
            "contract_digest": active.model.canonical_digest(contract),
            "authority_observations": [], "reevaluation_evidence": [],
            "requested_scope": None}

        def absent(path, identity):
            return observation(active.model, contract, "worktree_absent", {
                "path": path, "recorded_worktree_identity": identity,
                "probe_mode": "no_follow", "absent": True})

        def apply(candidate, source, facts, scope=None):
            if source == "checkpoint":
                return active.prepare_report_transition(candidate, {
                    **report, "delivery_observations": facts}, source_kind=source,
                    at_time=NOW)
            request = direct_values(contract, facts, scope)
            if source == "control":
                request = {"delivery_contracts": {"151": contract},
                    **{key: {"151": request[value]} for key, value in (
                        ("authorization_intents", "authorization_intents"),
                        ("authority_observations", "authority_observations"),
                        ("reevaluation_evidence", "reevaluation_evidence"),
                        ("delivery_observations", "delivery_observations"),
                        ("requested_scopes", "requested_scope"),
                        ("recoveries", "recovery"))}}
            return active.apply_transition(candidate, issue=151, request=request,
                source_kind=source, at_time=NOW)

        for source in ("direct", "control", "checkpoint"):
            for path, identity in (("/foreign", "/foreign"),
                                   (worktree, "foreign-identity")):
                candidate = copy.deepcopy(issue)
                with self.subTest(source=source, path=path, identity=identity), \
                        self.assertRaises(ValueError):
                    apply(candidate, source, [absent(path, identity)])
                self.assertEqual(candidate, issue)
            apply(copy.deepcopy(issue), source, [absent(worktree, worktree)])
        wrong = stage_scope(active.model, contract, "worktree")
        wrong["endpoint"]["value"] = "/foreign"; seal(active.model, wrong)
        candidate = copy.deepcopy(issue)
        with self.assertRaises(ValueError):
            apply(candidate, "direct", [], wrong)
        self.assertEqual(candidate, issue)


if __name__ == "__main__":
    unittest.main()
