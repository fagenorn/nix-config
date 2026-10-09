"""Deterministic replay of the measured two-owner, limited-slot shape (#150 D12, D23).

A simulated adapter follows orchestrate-issues to the letter over the real
workflow-state CLI; the host is a fixture, not a live Claude host (D14).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from .test_delivery_workflow import (ARTIFACT_BUDGET, MODEL, NOW, POLICY, SOURCES,
                                     BuilderHarness, load)

BASELINE = Path(__file__).with_name("fixtures") / "admission-replay" / "baseline.json"
ISSUES = (12, 14)
OWNER_MINUTES = 60
PROPOSED = {"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"}
DISPATCH = {"spawn", "resume", "retry", "delivery_remainder"}
# The stall bound D1 chose for bindings.workflow.orchestration.stall_minutes (#310 D1, D15).
STALL_MINUTES = 90
STALL_ISSUES_SOURCE = "invocation:/orchestrate-issues 12 14"


def at(minute):
    start = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


TASK_STEPS = (("worker", 20), ("reviewer", 10), ("worker", 20), ("reviewer", 10))


class SimulatedHost:
    """A fixture host where the controller, each owner and each support agent is one agent.

    An owner runs its two tasks in order, each a worker then a distinct reviewer, so
    exactly one of its support agents is live at any minute of its run (D12, D14).
    It refuses only scripted launches and accepts every other one, so an over-admission
    surfaces in the replay's per-minute budget check rather than as a refusal (D32).
    """

    def __init__(self, refuse=()):
        self.refuse, self.refusals = set(refuse), 0
        self.owners = {}  # launch action id -> (start, end)
        self.support = []  # (launch action id, role, start, end), one entry per agent

    def live(self, minute):
        return sum(1 for start, end in self.owners.values() if start <= minute < end)

    def agents(self, minute):
        busy = sum(1 for _, _, start, end in self.support if start <= minute < end)
        return 1 + self.live(minute) + busy

    def launch(self, action_id, minute):
        if action_id in self.refuse:
            self.refuse.discard(action_id)
            self.refusals += 1
            return False
        self.owners[action_id] = (minute, minute + OWNER_MINUTES)
        start = minute
        for role, length in TASK_STEPS:
            self.support.append((action_id, role, start, start + length))
            start += length
        return True


class AdmissionReplayTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_admission_replay", package=True)

    def validated(self, boundary, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        checked = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=raw, capture_output=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return checked.stdout

    def declare(self, slots):
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": slots},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")

    def complete_delivery(self, action, built, run, when):
        """One owner's merged finish at `when`: DeliveryLoopTest.deliver's sequence per issue."""
        issue, contract, custody = action["issue"], built["contract"], action["custody"]
        digest = self.model.canonical_digest(contract)
        url = f"https://github.com/fagenorn/nix-config/pull/{issue}"
        head, merge_sha = "a" * 40, "b" * 40

        def observed(kind, **facts):
            return self.build("observation", {"contract": contract,
                "observation_kind": kind, "source_kind": SOURCES[kind],
                "source_reference": f"probe:{kind}", "observed_at": when,
                "evidence": f"{kind} evidence", **facts})

        selection = self.build("selected-output", {"contract": contract, "head": head,
            "tree": "c" * 40, "acceptance_ref": f".claude/specs/issue-{issue}.md",
            "review_ref": "clean", "test_ref": "checks"})
        facts = {
            "select_reviewed_output": [observed("selected_output", selection=selection)],
            "publish_branch": [observed("branch_published", head=head)],
            "open_pr": [observed("pr_opened", pr_number=issue, pr_url=url, head=head)],
            "merge_pr": [observed("pr_merged", pr_number=issue, pr_url=url, head=head,
                                  merge_sha=merge_sha)],
            "close_tracker": [observed("tracker_closed", close_reason="completed",
                                       observation_identity=f"github:issue:{issue}:closed")],
            "delete_remote_branch": [observed("remote_branch_absent")],
            "remove_worktree": [observed("worktree_absent")],
            "delete_local_branch": [observed("local_branch_absent")]}
        pending, authority = [], []
        for stage in contract["stages"]:
            if stage["id"] in PROPOSED:
                scope = self.build("scope", {"contract": contract, "stage_id": stage["id"]})
                self.cli("checkpoint-delivery", *run, "--now", when, "--checkpoint-file", "-",
                    stdin=self.validated("ship-checkpoint", {"interface_version": 2,
                        "issue": issue, "custody": custody, "contract_digest": digest,
                        "delivery_observations": sorted(pending, key=lambda i: i["id"]),
                        "authority_observations": authority, "reevaluation_evidence": [],
                        "requested_scope": scope, "detail_state": "none",
                        "report_path": None, "notes": ""}))
                pending, authority = [], [self.build("authority-observation", {
                    "contract": contract, "scope_id": scope["id"],
                    "launch_id": custody["action_id"], "authority_kind": "native_guard",
                    "verdict": "allowed", "reason_code": "guard_allowed",
                    "observed_at": when, "evidence": stage["id"]})]
            pending += facts[stage["id"]]
        by_kind = {i["observation_kind"]: i["id"] for items in facts.values() for i in items}
        completing = pending + [
            observed("implementation_delivered", selection=selection, merge_sha=merge_sha,
                     integrated_ref="refs/heads/main",
                     merge_observation_id=by_kind["pr_merged"]),
            observed("cleanup_complete",
                     remote_branch_observation_ids=[by_kind["remote_branch_absent"]],
                     local_branch_observation_ids=[by_kind["local_branch_absent"]],
                     worktree_observation_ids=[by_kind["worktree_absent"]],
                     detail_pointer=f".superpowers/issue-delivery/{issue}/detail.json",
                     read_evidence="detail read")]
        historical = {"issue": issue, "state": "merged", "pr_url": url,
            "merge_sha": merge_sha, "issue_closed": True, "discussion_items": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        summary = {"interface_version": 2, "issue": issue, "state": "delivery_complete",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": digest,
            "delivery_observations": sorted(completing, key=lambda i: i["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        finished = json.loads(self.cli("finish", *run, "--now", when, "--summary-file",
            "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.assertEqual(finished["kind"], "delivery_complete")

    def replay(self, slots, *, refuse=()):
        """Return (metrics, first control response, last control response)."""
        self.project()
        self.declare(slots)
        route = json.loads(self.validated("workflow-response", self.cli(
            "host-route", "--route", "claude-code").stdout))
        if route["support"] != "supported":
            return route, None, None
        run = ("--repo-root", self.root, "--run-id", "replay")
        self.cli("init-run", *run, "--now", at(0))
        worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-replay")
                     for n in ISSUES}
        built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=worktrees[n], now=at(0),
            source_reference="invocation:/orchestrate-issues 12 14")) for n in ISSUES}
        host = SimulatedHost(refuse)
        tally = dict.fromkeys(("controller_turns", "wait_producing_responses",
                               "owner_dispatches", "delivered_events"), 0)
        dispatched, finished, events = {}, set(), []
        ask = set(ISSUES)  # this invocation created the run

        def control(minute, owners=()):
            nonlocal ask
            def fact(n):
                if n not in dispatched:
                    return {"issue": n, "recorded": None,
                            "candidate": {"path": worktrees[n], "state": "absent"}}
                return {"issue": n, "candidate": None, "recorded": {"path": worktrees[n],
                        "state": "absent" if n in finished else "matching_issue_branch"}}
            request = self.control_request(list(ISSUES), now=at(minute),
                contracts={str(n): built[n]["contract"] if n in ask else None
                           for n in ISSUES},
                intents={str(n): [built[n]["initial_intent"]] if n in ask else []
                         for n in ISSUES},
                worktrees=[fact(n) for n in ISSUES])
            request.update(attempt_budget_minutes=180, owners=list(owners))
            response = json.loads(self.validated("workflow-response", self.cli(
                "control", *run, "--request-file", "-",
                stdin=json.dumps(request).encode()).stdout))
            tally["controller_turns"] += 1
            ask = {s["issue"] for s in response["summaries"]
                   if any(r.get("reason_code") == "delivery_contract_required"
                          for r in s["requirements"])}
            for action in response["actions"]:
                if action["kind"] in DISPATCH:
                    tally["owner_dispatches"] += 1
                    dispatched[action["issue"]] = action
                    launched = host.launch(action["custody"]["action_id"], minute)
                    events.append((minute + OWNER_MINUTES if launched else minute,
                                   "exit" if launched else "refused", action))
                elif action["kind"] == "wait":
                    tally["wait_producing_responses"] += 1
            return response

        first = last = control(0)
        clock, first_merged = 0, None
        while last["actions"][-1]["kind"] != "finalize":
            self.assertTrue(events, "a wait with no pending host event would need polling")
            events.sort(key=lambda event: event[0])
            clock, kind, action = events.pop(0)
            tally["delivered_events"] += 1
            if kind == "exit":
                self.complete_delivery(action, built[action["issue"]], run, at(clock))
                finished.add(action["issue"])
                first_merged = clock if first_merged is None else first_merged
                last = control(clock)
            else:
                last = control(clock, [{"event_id": f"refused-{action['custody']['action_id']}",
                    "issue": action["issue"], "custody": action["custody"],
                    "state": "launch_refused"}])
        self.assertEqual(tally["controller_turns"], 1 + tally["delivered_events"])
        # Every admitted owner's worker and reviewer ran as its own agent, and none
        # would have waited for a slot: the fixture host never exceeds its budget.
        self.assertTrue(all(host.agents(minute) <= slots for minute in range(clock)),
                        "an admitted owner's worker or reviewer would have waited for a slot")
        return {"declared_slots": slots, "max_parallel": 2,
                "controller_turns": tally["controller_turns"],
                "wait_producing_responses": tally["wait_producing_responses"],
                "owner_dispatches": tally["owner_dispatches"],
                "host_refusals": host.refusals,
                "time_to_first_useful_result": first_merged, "makespan": clock,
                "worker_utilization": [
                    sum(max(0, min(end, clock) - start) for _, _, start, end in host.support),
                    sum(slots - 1 - host.live(minute) for minute in range(clock))],
                }, first, last

    def baseline(self, name):
        return json.loads(BASELINE.read_text(encoding="utf-8"))[name]

    def claims(self):
        state = self.root / ".superpowers/workflows/replay/state.json"
        return {c["holder"]: c for c in json.loads(state.read_text())["admission"]["claims"]}

    def test_the_measured_shape_admits_one_owner_at_a_time(self):
        metrics, first, _ = self.replay(4)
        self.assertEqual(metrics, self.baseline("measured"))
        self.assertEqual([(a["kind"], a.get("issue")) for a in first["actions"]],
                         [("spawn", 12), ("wait", None)])
        self.assertEqual(first["admission"]["waiting"], [14])
        claims = self.claims()
        self.assertEqual((claims["12:1:1"]["release_event"], claims["12:1:1"]["released_at"]),
                         ("finished", at(60)))
        self.assertEqual(claims["14:1:1"]["acquired_at"], at(60))

    def test_seven_slots_admit_both_so_the_fixture_is_no_hidden_clamp(self):
        metrics, first, _ = self.replay(7)
        self.assertEqual(metrics, self.baseline("seven_slots"))
        self.assertEqual([a["kind"] for a in first["actions"]], ["spawn", "spawn", "wait"])

    def test_a_scripted_refusal_is_bounded(self):
        metrics, _, last = self.replay(4, refuse={"14:1:1"})
        self.assertEqual(metrics, self.baseline("scripted_refusal"))
        self.assertFalse(any(a.get("issue") == 14 for a in last["actions"]))
        self.assertEqual(last["admission"]["waiting"], [14])

    def test_a_three_slot_declaration_is_refused_before_any_ledger_write(self):
        route, _, _ = self.replay(3)
        self.assertEqual((route["support"], route["reason_code"]),
                         ("unsupported", "declaration_invalid"))
        run = ("--repo-root", self.root, "--run-id", "refused")
        self.cli("init-run", *run, "--now", at(0))
        state = self.root / ".superpowers/workflows/refused/state.json"
        before = state.read_bytes()
        # A fresh request a valid declaration admits, so the declaration is the only
        # reason the control call can refuse (D32).
        worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-refused")
                     for n in ISSUES}
        built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=worktrees[n], now=at(0),
            source_reference="invocation:/orchestrate-issues 12 14")) for n in ISSUES}
        request = json.dumps(self.control_request(list(ISSUES), now=at(0),
            contracts={str(n): built[n]["contract"] for n in ISSUES},
            intents={str(n): [built[n]["initial_intent"]] for n in ISSUES},
            worktrees=[{"issue": n, "recorded": None,
                        "candidate": {"path": worktrees[n], "state": "absent"}}
                       for n in ISSUES])).encode()
        refused = self.cli("control", *run, "--request-file", "-", ok=False, stdin=request)
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
        self.assertIn(b"declaration_invalid", refused.stderr)
        self.declare(4)
        admitted = json.loads(self.cli("control", *run, "--request-file", "-",
                                       stdin=request).stdout)
        self.assertEqual([a["kind"] for a in admitted["actions"]], ["spawn", "wait"])

    def test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone(self):
        """#310 AC1: rule (a) arms a liveness check and rule (d) frees a stalled owner."""
        self.project()
        self.declare(7)
        run = ("--repo-root", self.root, "--run-id", "replay")
        self.cli("init-run", *run, "--now", at(0))
        worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-stall")
                     for n in ISSUES}
        built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=worktrees[n], now=at(0),
            source_reference=STALL_ISSUES_SOURCE)) for n in ISSUES}

        def control(minute, owners=(), *, first=False):
            def fact(n):
                if first:
                    return {"issue": n, "recorded": None,
                            "candidate": {"path": worktrees[n], "state": "absent"}}
                return {"issue": n, "candidate": None, "recorded": {
                    "path": worktrees[n], "state": "matching_issue_branch"}}
            request = self.control_request(list(ISSUES), now=at(minute),
                contracts={str(n): built[n]["contract"] if first else None for n in ISSUES},
                intents={str(n): [built[n]["initial_intent"]] if first else []
                         for n in ISSUES},
                worktrees=[fact(n) for n in ISSUES])
            request.update(attempt_budget_minutes=180, owners=list(owners))
            return json.loads(self.validated("workflow-response", self.cli(
                "control", *run, "--request-file", "-",
                stdin=json.dumps(request).encode()).stdout))

        def liveness(minute, action_id, since=None):
            argv = ["owner-liveness", *run, "--action-id", action_id,
                    "--stall-minutes", str(STALL_MINUTES)]
            if since is not None:
                argv += ["--since", since]
            with mock.patch.dict(os.environ, {"WORKFLOW_STATE_TEST_CLOCK": at(minute)}):
                return json.loads(self.validated("workflow-response", self.cli(*argv).stdout))

        first = control(0, first=True)
        custody = {a["issue"]: a["custody"] for a in first["actions"] if a["kind"] in DISPATCH}
        self.assertEqual(sorted(custody), list(ISSUES))
        deadline = {a["issue"]: a["deadline_at"] for a in first["actions"]
                    if a["kind"] in DISPATCH}
        self.assertEqual(deadline[12], at(180))

        # Rule (a): both owners notify interim at minute 5; each arms one observer.
        since, observers, stopped, observations = {}, {}, set(), []
        for issue in ISSUES:
            reply = liveness(5, custody[issue]["action_id"])
            self.assertEqual((reply["verdict"], reply["since"], reply["wait_seconds"]),
                             ("live", at(5), STALL_MINUTES * 60))
            since[issue] = reply["since"]
            observers[issue] = 5 + reply["wait_seconds"] // 60
        # B's owner records progress: a registered worker on its launch at minute 30.
        self.cli("register-worker", *run, "--now", at(30), "--action-id",
                 custody[14]["action_id"])

        # Rule (d): each observer wakes once, in time order (A first at a tie).
        wakes = sorted((minute, issue) for issue, minute in observers.items())
        self.assertEqual(wakes, [(95, 12), (95, 14)])
        for minute, issue in wakes:
            reply = liveness(minute, custody[issue]["action_id"], since=since[issue])
            if reply["verdict"] == "stalled":
                stopped.add(issue)  # the host's task-stop, then one observation
                event = {"event_id": f"{issue}-stalled", "issue": issue,
                         "custody": custody[issue], "state": "unavailable"}
                observations.append(event)
                response = control(minute, [event])
                relaunched = [a for a in response["actions"]
                              if a["kind"] in {"resume", "retry"} and a["issue"] == issue]
                self.assertEqual(len(relaunched), 1)
                self.assertNotEqual(relaunched[0]["custody"]["action_id"],
                                    custody[issue]["action_id"])
            else:
                self.assertEqual(reply["verdict"], "live")
                observers[issue] = minute + reply["wait_seconds"] // 60
                self.assertEqual((reply["progress_at"], reply["stall_at"],
                                  reply["wait_seconds"]), (at(30), at(120), 1500))

        self.assertEqual(stopped, {12})
        self.assertEqual([event["issue"] for event in observations], [12])

        # PR310-04: "exactly once" survives a stale liveness wake and a late
        # return from the stopped owner after its replacement was dispatched.
        # The stale wake is answered `not_current` (no observation, per rule (a));
        # the late return falls under rule (b), whose `check-launch` reads
        # `current: false`, so it sends nothing either.
        stale = liveness(100, custody[12]["action_id"], since=since[12])
        self.assertEqual(stale["verdict"], "not_current")
        late = json.loads(self.cli("check-launch", *run, "--action-id",
                                   custody[12]["action_id"]).stdout)
        self.assertIs(late["current"], False)
        self.assertEqual([event["issue"] for event in observations], [12])
        claims = self.claims()
        self.assertEqual((claims["12:1:1"]["release_event"], claims["12:1:1"]["released_at"]),
                         ("owner_unavailable", at(95)))
        self.assertLess(at(95), deadline[12])
        self.assertIsNone(claims["14:1:1"]["released_at"])


if __name__ == "__main__":
    unittest.main()
