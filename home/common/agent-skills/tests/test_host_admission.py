"""Host agent-slot admission (#150): declaration, host-route, claims, control admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from .test_workflow_state import DEFAULT_NOW, SCRIPT, LifecycleHarness, load_source_module

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
POLICY = REPO / "home/common/agent-skills/artifact-budget-policy.json"
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"
ALTERNATIVE = "/from-issue <issue> --auto"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


def install_declaration(home, value):
    """Write `value` (JSON, or a str verbatim) as HOME's declaration; None removes it."""
    target = Path(home) / ".agents/share/host-declaration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if value is not None:
        target.write_text(value if isinstance(value, str) else json.dumps(value),
                          encoding="utf-8")
    return target


def boundary(case, raw):
    """Pipe raw bytes through the workflow-response boundary; return the parsed value."""
    checked = subprocess.run(
        [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
         "workflow-response", "--input", "-", "--policy", str(POLICY)],
        input=raw, capture_output=True, check=False)
    case.assertEqual((checked.returncode, checked.stdout), (0, raw), checked.stderr)
    return json.loads(raw)


class HostRouteTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def host_route(self, route):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), "host-route", "--route", route],
            capture_output=True, check=False, env={**os.environ, "HOME": str(self.home)})

    def answer(self, route):
        completed = self.host_route(route)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return boundary(self, completed.stdout)

    @staticmethod
    def unsupported(route, reason):
        return {"interface_version": 1, "kind": "host_route", "route": route,
                "support": "unsupported", "agent_slots": None,
                "reason_code": reason, "alternative": ALTERNATIVE}

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "codex": {"support": "unsupported"}}))
        install_declaration(self.home, committed)
        self.assertEqual(self.answer("claude-code"), {
            "interface_version": 1, "kind": "host_route", "route": "claude-code",
            "support": "supported", "agent_slots": 7, "reason_code": None,
            "alternative": None})
        self.assertEqual(self.answer("codex"),
                         self.unsupported("codex", "declared_unsupported"))

    def test_every_reason_code_is_a_typed_answer(self):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 4}}))
        self.assertEqual(self.answer("claude-code")["agent_slots"], 4)
        self.assertEqual(self.answer("gemini"),
                         self.unsupported("gemini", "route_undeclared"))
        install_declaration(self.home, None)
        self.assertEqual(self.answer("claude-code"),
                         self.unsupported("claude-code", "declaration_missing"))

    def test_invalid_declarations_answer_declaration_invalid(self):
        supported = {"support": "supported", "agent_slots": 7}
        for label, value in (
                ("below the floor", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": 3}})),
                ("boolean slots", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": True}})),
                ("host metric", {**declaration(**{"claude-code": supported}), "cpu": 8}),
                ("route member", declaration(**{"claude-code": {**supported, "memory": 1}})),
                ("unsupported with slots", declaration(codex={
                    "support": "unsupported", "agent_slots": 4})),
                ("reserved direct", declaration(direct=supported)),
                ("bad route name", declaration(**{"Claude Code": supported})),
                ("no routes", declaration()),
                ("schema two", {"schema_version": 2, "routes": {"claude-code": supported}}),
                ("duplicate key", '{"schema_version": 1, "schema_version": 1, "routes": '
                                  '{"claude-code": {"support": "supported", "agent_slots": 7}}}'),
                ("not json", "{"),
                ("integer past the conversion limit", '{"schema_version": ' + "1" * 5000
                                                      + ', "routes": {}}'),
                ("nesting past the recursion limit", "[" * 100000 + "]" * 100000)):
            with self.subTest(label):
                install_declaration(self.home, value)
                self.assertEqual(self.answer("claude-code"),
                                 self.unsupported("claude-code", "declaration_invalid"))

    def test_usage_errors_exit_two_and_nothing_is_written(self):
        install_declaration(self.home, json.loads(
            COMMITTED_DECLARATION.read_text(encoding="utf-8")))
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        for route in ("direct", "Claude Code", ""):
            with self.subTest(route=route):
                completed = self.host_route(route)
                self.assertEqual((completed.returncode, completed.stdout), (2, b""))
        self.answer("claude-code")
        self.assertEqual(
            sorted(path.relative_to(self.home) for path in self.home.rglob("*")), before)


OWNER_ROLES = {"owner": 1, "worker": 1, "reviewer": 1}


def claim(holder, roles, at, released=None):
    """One claim record; `released` is (released_at, event, seq) or None."""
    released_at, event, seq = released or (None, None, None)
    return {"holder": holder, "roles": dict(roles), "acquired_at": at,
            "released_at": released_at, "release_event": event, "release_seq": seq}


class ClaimLedgerTest(LifecycleHarness, unittest.TestCase):
    """D5, D11, D19: schema 4 records claims; the commit boundary releases them."""

    LATER = "2026-08-13T20:30:00Z"

    def admitted(self):
        """A v4 run: contractless issue 14 active, its launch and the controller claimed."""
        self.init_run()
        workflow = load_source_module(SCRIPT, "host_admission_ledger")
        state = self.read_state()
        attempt = workflow.new_control_attempt(
            issue=14, attempt_number=1, worktree=str(self.root / "wt-14"),
            now=DEFAULT_NOW, deadline_at="2026-08-13T23:00:00Z")
        state["issues"]["14"] = {"issue": 14, "attempts": [attempt], "outcome": None,
                                 "delivery": self.empty_delivery(),
                                 "delivery_remainders": []}
        state["admission"] = {"route": "claude-code", "releases": 0, "claims": [
            claim("controller", {"controller": 1}, DEFAULT_NOW),
            claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)]}
        self.write_state(state)
        return state

    def released(self, holder):
        item = {c["holder"]: c for c in self.read_state()["admission"]["claims"]}[holder]
        return item["released_at"], item["release_event"], item["release_seq"]

    def finish_14(self, now, *, ok=True):
        result = self.root / "result.json"
        result.write_text(json.dumps(self.merged_result(14)), encoding="utf-8")
        return self.run_cli("finish", "--repo-root", self.root, "--run-id", self.run_id,
                            "--issue", 14, "--attempt", 1, "--result-file", result,
                            "--now", now, ok=ok)

    def test_finish_releases_the_claim_in_its_own_write(self):
        self.admitted()
        self.finish_14(self.LATER)
        state = self.read_state()
        self.assertEqual(state["issues"]["14"]["attempts"][0]["state"], "merged")
        self.assertEqual(state["updated_at"], self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "finished", 1))
        self.assertEqual((state["admission"]["releases"], self.released("controller")),
                         (1, (None, None, None)))

    def test_suspend_releases_suspended(self):
        self.admitted()
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit", now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "suspended", 1))

    def test_handoff_releases_handed_off(self):
        self.admitted()
        self.progress(turn_count=118, context_tokens=20000,
                      handoff_path=self.write_handoff(14), now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "handed_off", 1))

    def test_a_refused_write_leaves_record_and_claim_unchanged(self):
        self.admitted()
        before = self.state_path.read_bytes()
        refused = self.finish_14("2026-08-13T19:00:00Z", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_state_validation_closes_the_admission_block(self):
        valid = self.admitted()
        check = ("check-launch", "--repo-root", self.root, "--run-id", self.run_id,
                 "--action-id", "14:1:1")
        self.assertEqual(self.run_cli(*check).returncode, 0)
        owner = claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)
        block = lambda claims, releases=0, route="claude-code": {
            "route": route, "releases": releases, "claims": claims}
        for label, admission in (
                ("stale holder", block([claim("14:1:9", OWNER_ROLES, DEFAULT_NOW)])),
                ("two controllers", block([claim("controller", {"controller": 1},
                                                 DEFAULT_NOW)] * 2)),
                ("duplicate holder", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                  (DEFAULT_NOW, "suspended", 1)), owner], 1)),
                ("partial release", block([{**owner, "released_at": DEFAULT_NOW,
                                            "release_seq": 1}], 1)),
                ("counter mismatch", block([owner], 2)),
                ("wrong roles", block([claim("14:1:1", {"controller": 1}, DEFAULT_NOW)])),
                ("owner finalized", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                 (DEFAULT_NOW, "finalized", 1))], 1)),
                ("direct with claims", block([owner], route="direct")),
                ("extra member", {**block([]), "slots": 4})):
            with self.subTest(label):
                self.write_state({**valid, "admission": admission})
                self.assertEqual(self.run_cli(*check, ok=False).returncode, 2)

    def test_schema_three_reads_migrate_to_a_null_admission(self):
        self.admitted()
        self.write_state(self._as_legacy(self.read_state(), 3))
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"], "current")
        self.init_run()  # a locked read persists the migration
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["admission"]), (4, None))

    def test_direct_runs_carry_no_admission(self):
        self.acquire_direct()
        state = json.loads(self.direct_state_path("direct-73-000001").read_text())
        self.assertIsNone(state["admission"])



T0 = "2026-08-13T20:00:00Z"
ZERO = {"controller": 0, "owner": 0, "worker": 0, "reviewer": 0}


class AdmissionSweeps(LifecycleHarness):
    """Interface-3 sweeps over issues 12 and 14 (and 15) with a per-test declaration."""

    def slots(self, count):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": count},
            "codex": {"support": "unsupported"}}))

    def sweep(self, now, issues=(12, 14), *, recorded=(), unobserved=(), forge=None,
              owners=None, ok=True, **fields):
        def fact(n):
            path = str(self.root / f"wt-{n}")
            if n in recorded:
                return self.worktree_fact(n, recorded={"path": path,
                                                       "state": "matching_issue_branch"})
            return self.worktree_fact(n, candidate={"path": path, "state": "absent"})
        request = self.control_request(
            now=now, issues=list(issues), tracker=[self.tracker_fact(n) for n in issues],
            worktrees=[fact(n) for n in issues if n not in unobserved], owners=owners,
            **fields)
        request["forge"].update(forge or {})
        completed = self.control_raw(request=request, ok=ok, legacy=False)
        if not ok:
            return completed
        return boundary(self, completed.stdout.encode())

    def claims(self):
        return {c["holder"]: c for c in self.read_state()["admission"]["claims"]}

    def kinds(self, response):
        return [(a["kind"], a.get("issue")) for a in response["actions"]]


class ControlAdmissionTest(AdmissionSweeps, unittest.TestCase):
    """D4, D6, D11, D20, D21: control admits whole role sets and reports capacity."""

    def test_four_slots_admit_one_owner_and_seven_admit_both(self):
        self.slots(4)
        self.init_run()
        first = self.sweep(T0)
        self.assertEqual(self.kinds(first), [("spawn", 12), ("wait", None)])
        self.assertEqual(first["admission"], {"route": "claude-code", "declared_slots": 4,
            "reserved": {"controller": 1, "owner": 1, "worker": 1, "reviewer": 1},
            "available": 0, "waiting": [14]})
        waiting = next(s for s in first["summaries"] if s["issue"] == 14)
        self.assertEqual((waiting["state"], waiting["requirements"]), ("queued", [{
            "kind": "delivery_contract", "subject_id": "14",
            "reason_code": "delivery_contract_required", "detail_pointer": None}]))
        self.assertEqual(sorted(self.claims()), ["12:1:1", "controller"])
        woken = self.sweep("2026-08-13T20:10:00Z", recorded=(12,))  # a tracker wake
        self.assertEqual((self.kinds(woken), woken["admission"]["waiting"]),
                         ([("wait", None)], [14]))
        self.run_id = "issue-14-seven"
        self.slots(7)
        self.init_run()
        both = self.sweep(T0)
        self.assertEqual(self.kinds(both), [("spawn", 12), ("spawn", 14), ("wait", None)])
        self.assertEqual((both["admission"]["available"], both["admission"]["waiting"]),
                         (0, []))

    def test_a_released_claim_admits_the_waiting_owner(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0)
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:05:00Z")
        # 12's worktree goes unobserved, so its resume is a round still owed.
        after = self.sweep("2026-08-13T20:06:00Z", unobserved=(12,))
        self.assertEqual(self.kinds(after), [("spawn", 14), ("wait", None)])
        claims = self.claims()
        self.assertEqual((claims["12:1:1"]["release_event"], claims["12:1:1"]["release_seq"]),
                         ("suspended", 1))
        self.assertIsNone(claims["14:1:1"]["released_at"])
        self.assertEqual(after["admission"]["waiting"], [])

    def test_an_unavailable_owner_is_released_and_taken_over_subject_to_admission(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0)
        dead = self.owner_fact(event_id="12-dead", issue=12, attempt=1, launch=1)
        after = self.sweep("2026-08-13T20:05:00Z", recorded=(12,), owners=[dead])
        self.assertEqual(self.kinds(after), [("resume", 12), ("wait", None)])
        claims = self.claims()
        self.assertEqual(claims["12:1:1"]["release_event"], "owner_unavailable")
        self.assertIsNone(claims["12:1:2"]["released_at"])
        self.assertEqual(after["admission"]["waiting"], [14])

    def test_a_reap_suspends_and_a_reap_resumed_in_one_sweep_supersedes(self):
        for label, recorded, event in (("reaped", (), "suspended"),
                                       ("resumed", (12,), "superseded")):
            with self.subTest(label):
                self.run_id = f"reap-{label}"
                self.slots(4)
                self.init_run()
                self.sweep(T0, issues=(12,))
                self.sweep("2026-08-13T20:31:00Z", issues=(12,), recorded=recorded,
                           unobserved=() if recorded else (12,))
                self.assertEqual(self.claims()["12:1:1"]["release_event"], event)

    def test_forge_reconciliation_releases_finished(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0, issues=(12,))
        merged = {"state": "merged", "merge_sha": "c" * 40,
                  "url": "https://github.com/fagenorn/nix-config/pull/12"}
        self.sweep("2026-08-13T20:31:00Z", issues=(12,), recorded=(12,),
                   forge={"12": merged})
        self.assertEqual(self.claims()["12:1:1"]["release_event"], "finished")

    def test_finalize_releases_the_controller_and_replays_byte_stable(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0, issues=(12,))
        self.suspend(issue=12, attempt=1, blocked_on="human_gate",
                     now="2026-08-13T20:05:00Z")
        final = self.sweep("2026-08-13T20:06:00Z", issues=(12,), unobserved=(12,))
        self.assertEqual(final["actions"][-1]["kind"], "finalize")
        self.assertEqual(self.claims()["controller"]["release_event"], "finalized")
        self.assertEqual(final["admission"]["reserved"], ZERO)
        before = self.state_path.read_bytes()
        self.sweep("2026-08-13T20:07:00Z", issues=(12,), unobserved=(12,))
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_route_binding_is_immutable_and_unsupported_routes_write_nothing(self):
        self.slots(4)
        self.init_run()
        before = self.state_path.read_bytes()
        for label, route, issues, parallel in (
                ("declared unsupported", "codex", (12, 14), 2),
                ("undeclared", "gemini", (12, 14), 2),
                ("direct over two issues", "direct", (12, 14), 1),
                ("direct above one", "direct", (12,), 2)):
            with self.subTest(label):
                refused = self.sweep(T0, issues=issues, ok=False, host_route=route,
                                     max_parallel=parallel)
                self.assertEqual((refused.returncode, self.state_path.read_bytes()),
                                 (2, before))
        install_declaration(self.home, None)
        refused = self.sweep(T0, ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))
        self.slots(4)
        self.sweep(T0)
        bound = self.state_path.read_bytes()
        refused = self.sweep("2026-08-13T20:01:00Z", issues=(12,), recorded=(12,),
                             ok=False, host_route="direct", max_parallel=1)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, bound))

    def test_the_direct_route_reads_no_declaration_and_records_no_claims(self):
        install_declaration(self.home, None)
        self.init_run()
        response = self.sweep(T0, issues=(12,), host_route="direct", max_parallel=1)
        self.assertEqual(self.kinds(response), [("spawn", 12), ("wait", None)])
        self.assertEqual(response["admission"], {"route": "direct", "declared_slots": None,
            "reserved": ZERO, "available": None, "waiting": []})
        self.assertEqual(self.read_state()["admission"],
                         {"route": "direct", "releases": 0, "claims": []})

    def test_migrated_live_custody_is_adopted_and_new_admission_waits(self):
        self.init_run()  # the harness declaration: 64 slots
        self.sweep(T0)
        self.write_state(self._as_legacy(self.read_state(), 3))
        self.slots(4)
        response = self.sweep("2026-08-13T20:05:00Z", issues=(12, 14, 15),
                              recorded=(12, 14), max_parallel=3)
        self.assertEqual(sorted(self.claims()), ["12:1:1", "14:1:1", "controller"])
        self.assertEqual(response["admission"]["reserved"],
                         {"controller": 1, "owner": 2, "worker": 2, "reviewer": 2})
        self.assertEqual((response["admission"]["available"],
                          response["admission"]["waiting"]), (0, [15]))


class LaunchRefusalTest(AdmissionSweeps, unittest.TestCase):
    """D7, D22: a refused launch parks under host_capacity until another release."""

    def refused(self, issue, launch=1):
        fact = self.owner_fact(event_id=f"refused-{issue}-{launch}", issue=issue,
                               attempt=1, launch=launch)
        return {**fact, "state": "launch_refused"}

    @staticmethod
    def summary(response, issue):
        return next(s for s in response["summaries"] if s["issue"] == issue)

    def admitted_pair(self):
        self.slots(7)
        self.init_run()
        self.sweep(T0)  # 12 and 14 spawned

    def test_a_refusal_parks_the_launch_until_another_claim_is_released(self):
        self.admitted_pair()
        parked = self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14),
                            owners=[self.refused(14)])
        self.assertEqual(self.kinds(parked), [("wait", None)])
        self.assertEqual((self.summary(parked, 14)["state"],
                          self.summary(parked, 14)["blocked_on"]),
                         ("suspended", "host_capacity"))
        self.assertEqual(parked["admission"]["waiting"], [14])
        refused = self.claims()["14:1:1"]
        self.assertEqual(refused["release_event"], "launch_refused")
        woken = self.sweep("2026-08-13T20:02:00Z", recorded=(12, 14))
        self.assertEqual((self.kinds(woken), woken["admission"]["waiting"]),
                         ([("wait", None)], [14]))
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:03:00Z")
        resumed = self.sweep("2026-08-13T20:04:00Z", recorded=(14,), unobserved=(12,))
        self.assertEqual(self.kinds(resumed), [("resume", 14), ("wait", None)])
        claims = self.claims()
        self.assertGreater(claims["12:1:1"]["release_seq"], refused["release_seq"])
        self.assertIsNone(claims["14:1:2"]["released_at"])

    def test_a_refusal_gated_finalize_resumes_on_the_next_invocation(self):
        self.admitted_pair()
        self.suspend(issue=12, attempt=1, blocked_on="human_gate",
                     now="2026-08-13T20:01:00Z")
        parked = self.sweep("2026-08-13T20:02:00Z", recorded=(14,), unobserved=(12,),
                            owners=[self.refused(14)])
        self.assertEqual((self.kinds(parked), parked["admission"]["waiting"]),
                         ([("finalize", None)], [14]))
        claims = self.claims()
        self.assertGreater(claims["controller"]["release_seq"],
                           claims["14:1:1"]["release_seq"])
        again = self.sweep("2026-08-13T20:03:00Z", recorded=(14,), unobserved=(12,))
        self.assertEqual(self.kinds(again), [("resume", 14), ("wait", None)])

    def test_the_anti_zombie_bound_ends_a_launch_that_keeps_being_refused(self):
        self.admitted_pair()
        self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14), owners=[self.refused(14)])
        state = self.read_state()
        state["issues"]["14"]["attempts"][0]["stalled_resumes"] = 2  # two resumes spent
        self.write_state(state)
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:02:00Z")
        self.sweep("2026-08-13T20:03:00Z", recorded=(14,), unobserved=(12,))  # 14:1:2
        final = self.sweep("2026-08-13T20:04:00Z", recorded=(14,), unobserved=(12,),
                           owners=[self.refused(14, launch=2)])
        self.assertEqual(self.summary(final, 14)["state"], "stopped")
        self.assertEqual(self.claims()["14:1:2"]["release_event"], "finished")
        self.assertFalse(any(a.get("issue") == 14 for a in final["actions"]))

    def test_inapplicable_refusals_write_nothing_and_stale_ones_are_ignored(self):
        self.admitted_pair()
        self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14), owners=[self.refused(14)])
        before = self.state_path.read_bytes()
        again = {**self.refused(14), "event_id": "refused-again"}
        rejected = self.sweep("2026-08-13T20:02:00Z", recorded=(12, 14), owners=[again],
                              ok=False)
        self.assertEqual((rejected.returncode, self.state_path.read_bytes()), (2, before))
        dead = self.owner_fact(event_id="12-dead", issue=12, attempt=1, launch=1)
        self.sweep("2026-08-13T20:03:00Z", recorded=(12, 14), owners=[dead])  # 12:1:2
        stale = self.sweep("2026-08-13T20:04:00Z", recorded=(12, 14),
                           owners=[self.refused(12)])
        self.assertEqual(self.summary(stale, 12)["state"], "active")
        self.assertIsNone(self.claims()["12:1:2"]["released_at"])

    def test_direct_runs_and_owners_cannot_report_host_capacity(self):
        install_declaration(self.home, None)
        self.init_run()
        self.sweep(T0, issues=(12,), host_route="direct", max_parallel=1)
        before = self.state_path.read_bytes()
        refused = self.sweep("2026-08-13T20:01:00Z", issues=(12,), recorded=(12,),
                             host_route="direct", max_parallel=1,
                             owners=[self.refused(12)], ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))
        usage = self.suspend(issue=12, attempt=1, blocked_on="host_capacity",
                             now="2026-08-13T20:02:00Z", ok=False)
        self.assertEqual((usage.returncode, self.state_path.read_bytes()), (2, before))


if __name__ == "__main__":
    unittest.main()
