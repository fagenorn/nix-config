"""Deterministic replay of the measured two-owner, limited-slot shape (#150 D12, D23).

A simulated adapter follows orchestrate-issues to the letter: one `orchestrate-control start`,
then one `orchestrate-control step` per event, run from source in the hermetic world of
`tests/orchestrate_world.py` over the real workflow-state (#404 D6). The host is a fixture,
not a live Claude host (D14).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests.orchestrate_world import OrchestrateWorld

from .test_delivery_workflow import ARTIFACT_BUDGET, MODEL, NOW, POLICY, SOURCES, load

BASELINE = Path(__file__).with_name("fixtures") / "admission-replay" / "baseline.json"
ISSUES = (12, 14)
OWNER_MINUTES = 60
PROPOSED = {"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"}
DISPATCH = {"spawn", "resume", "retry", "delivery_remainder"}
# The stall bound D1 chose for bindings.workflow.orchestration.stall_minutes (#310 D1, D15).
STALL_MINUTES = 90


def at(minute):
    start = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def attempt_budget_180(contract):
    """The fixture contract's attempt budget, which the stall test's deadline reads."""
    contract["bindings"]["workflow"]["orchestration"]["attempt_budget_minutes"] = 180


def custody_of(response, action_id):
    """The custody of the action whose `custody.action_id` is a dispatch's `action_id` (D2)."""
    (custody,) = [action["custody"] for action in response["actions"]
                  if (action.get("custody") or {}).get("action_id") == action_id]
    return custody


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


class AdmissionReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_admission_replay", package=True)

    def setUp(self):
        self.world = OrchestrateWorld(self, mutate=attempt_budget_180)
        self.root = self.world.root

    def clock(self, minute):
        """Pin the ledger clock of every later `step` and direct workflow-state call (D6)."""
        self.world.env["WORKFLOW_STATE_TEST_CLOCK"] = at(minute)

    def cli(self, *argv, stdin=None):
        """A direct workflow-state call, as the skill or an owner makes it."""
        done = self.world.ws(*argv, stdin=stdin)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        return done

    def build(self, kind, value):
        return json.loads(self.cli("build-delivery", "--repo-root", self.root, "--kind", kind,
                                   "--input", "-", stdin=json.dumps(value).encode()).stdout)

    def validated(self, boundary, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        checked = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=raw, capture_output=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return checked.stdout

    def declare(self, slots):
        (self.world.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": slots},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")

    def start(self):
        """`orchestrate-control start` for the replay's issues at minute 0: its one object."""
        self.clock(0)
        return self.world.start(*map(str, ISSUES))

    def open_run(self):
        """A ready session for the replay's issues, with `self.run_id` set to its run."""
        started = self.start()
        self.assertEqual(started["outcome"], "ready", started)
        self.run_id = started["session"]["run_id"]
        return started["session"]

    def step(self, minute, session, carried, owners=(), *, first_sweep=False):
        """One `orchestrate-control step` at `minute`; its ready report's `contracts_due` and
        `refused_contracts` replace `carried`, to be passed back on the next call (D2)."""
        self.clock(minute)
        done, report = self.world.step(
            session, first_sweep=first_sweep, owners=owners,
            contracts_due=carried["contracts_due"],
            refused_contracts=carried["refused_contracts"])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(report["outcome"], "ready", report)
        carried.update(contracts_due=report["contracts_due"],
                       refused_contracts=report["refused_contracts"])
        return report

    def add_worktree(self, entry):
        """The fixture host's checkout of a spawned owner's worktree on its issue branch."""
        self.world.add_worktree(entry["worktree"], f"issue-{entry['issue']}-orchestrated")

    def remove_worktree(self, entry):
        """The owner's delivery cleanup: its worktree and local branch are gone."""
        self.world.git("worktree", "remove", entry["worktree"])
        self.world.git("branch", "-D", f"issue-{entry['issue']}-orchestrated")

    def complete_delivery(self, entry, run, when):
        """One owner's merged finish at `when`: DeliveryLoopTest.deliver's sequence per issue.

        The owner decodes its own `owner_object`, as every owner does on receipt."""
        owner = json.loads(entry["owner_object"])
        issue, contract, custody = owner["issue"], owner["contract"], owner["custody"]
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
        self.declare(slots)
        session = self.open_run()
        run = ("--repo-root", self.root, "--run-id", self.run_id)
        host = SimulatedHost(refuse)
        tally = dict.fromkeys(("controller_turns", "wait_producing_responses",
                               "owner_dispatches", "delivered_events", "refusal_turns",
                               "control_calls"), 0)
        carried = {"contracts_due": [], "refused_contracts": []}
        events, reports = [], []

        def turn(minute, owners=()):
            """One `step` and its launches; the report's refused launches ride one more `step`
            once it has executed (D12)."""
            report = self.step(minute, session, carried, owners, first_sweep=not reports)
            reports.append(report)
            tally["controller_turns"] += 1
            tally["control_calls"] += report["control_calls"]
            response, refused = report["response"], []
            for entry in report["dispatches"]:
                tally["owner_dispatches"] += 1
                custody = custody_of(response, entry["action_id"])
                if host.launch(entry["action_id"], minute):
                    if entry["launch_kind"] == "spawn":
                        self.add_worktree(entry)
                    events.append((minute + OWNER_MINUTES, entry))
                else:
                    refused.append({"event_id": f"refused-{entry['action_id']}",
                                    "issue": entry["issue"], "custody": custody,
                                    "state": "launch_refused"})
            tally["wait_producing_responses"] += sum(
                1 for action in response["actions"] if action["kind"] == "wait")
            if refused:
                tally["refusal_turns"] += 1
                return turn(minute, refused)
            return report

        last = turn(0)
        clock, first_merged = 0, None
        while last["response"]["actions"][-1]["kind"] != "finalize":
            self.assertTrue(events, "a wait with no pending host event would need polling")
            events.sort(key=lambda event: event[0])
            clock, entry = events.pop(0)
            tally["delivered_events"] += 1
            self.clock(clock)
            self.complete_delivery(entry, run, at(clock))
            self.remove_worktree(entry)
            first_merged = clock if first_merged is None else first_merged
            last = turn(clock)
        self.assertEqual(tally["controller_turns"],
                         1 + tally["delivered_events"] + tally["refusal_turns"])
        # Every control round went through `step`: the world logged no other control call.
        self.assertEqual(len(self.world.calls("workflow-state", "control")),
                         tally["control_calls"])
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
                }, reports[0]["response"], last["response"]

    def baseline(self, name):
        return json.loads(BASELINE.read_text(encoding="utf-8"))[name]

    def state_path(self):
        return self.root / ".superpowers/workflows" / self.run_id / "state.json"

    def claims(self):
        return {c["holder"]: c for c in
                json.loads(self.state_path().read_text())["admission"]["claims"]}

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
        self.declare(3)
        started = self.start()
        self.assertEqual((started["outcome"], started["route"]["support"],
                          started["route"]["reason_code"]),
                         ("unsupported", "unsupported", "declaration_invalid"))
        self.assertEqual(list((self.root / ".superpowers/workflows").glob("*")), [])
        # A run a valid declaration opens, so the declaration is the only reason the
        # control call can refuse (D32).
        self.declare(4)
        session = self.open_run()
        before = self.state_path().read_bytes()
        self.declare(3)
        done, refused = self.world.step(session, first_sweep=True)
        self.assertEqual((done.returncode, refused["outcome"], refused["step"]),
                         (2, "refused", "control"))
        self.assertIn("declaration_invalid", refused["detail"])
        self.assertEqual(self.state_path().read_bytes(), before)
        self.declare(4)
        admitted = self.step(0, session, {"contracts_due": [], "refused_contracts": []},
                             first_sweep=True)
        self.assertEqual([a["kind"] for a in admitted["response"]["actions"]],
                         ["spawn", "wait"])

    def test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone(self):
        """#310 AC1: rule (a) arms a liveness check and rule (d) frees a stalled owner."""
        self.declare(7)
        session = self.open_run()
        run = ("--repo-root", self.root, "--run-id", self.run_id)
        carried = {"contracts_due": [], "refused_contracts": []}
        first = self.step(0, session, carried, first_sweep=True)
        custody = {}
        for entry in first["dispatches"]:
            custody[entry["issue"]] = custody_of(first["response"], entry["action_id"])
            self.add_worktree(entry)
        self.assertEqual(sorted(custody), list(ISSUES))
        deadline = {a["issue"]: a["deadline_at"] for a in first["response"]["actions"]
                    if a["kind"] in DISPATCH}
        self.assertEqual(deadline[12], at(180))

        def liveness(minute, action_id, since=None):
            argv = ["owner-liveness", *run, "--action-id", action_id,
                    "--stall-minutes", str(STALL_MINUTES)]
            if since is not None:
                argv += ["--since", since]
            self.clock(minute)
            return json.loads(self.validated("workflow-response", self.cli(*argv).stdout))

        # Rule (a): both owners notify interim at minute 5; each arms one observer.
        since, observers, stopped, observations = {}, {}, set(), []
        for issue in ISSUES:
            reply = liveness(5, custody[issue]["action_id"])
            self.assertEqual((reply["verdict"], reply["since"], reply["wait_seconds"]),
                             ("live", at(5), STALL_MINUTES * 60))
            since[issue] = reply["since"]
            observers[issue] = 5 + reply["wait_seconds"] // 60
        # B's owner records progress: a registered worker on its launch at minute 30.
        self.clock(30)
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
                response = self.step(minute, session, carried, [event])["response"]
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
