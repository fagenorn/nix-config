# Task 6: Deterministic admission replay and baseline

**Files:**
- Create: `home/common/agent-skills/tests/test_admission_replay.py`
- Create: `home/common/agent-skills/tests/fixtures/admission-replay/baseline.json`
- Modify: `justfile` (`agent-workflow-tests` gains `test_admission_replay.py`)

**Interfaces:**
- Consumes (Tasks 1–5): `workflow-state host-route`, `init-run`, `control` (interface 3, `admission` report), `checkpoint-delivery`, `finish --summary-file -`; `BuilderHarness` (`project`, `cli`, `build`, `contract_input`, `control_request(..., host_route="claude-code")`, `self.home`, `self.root`) and `ARTIFACT_BUDGET`, `MODEL`, `NOW`, `POLICY`, `SOURCES`, `load` from `T/test_delivery_workflow.py`.
- Produces: the replay (seam S2) and its committed baseline — nothing later tasks call.

**Invariants:**
- The adapter follows orchestrate-issues exactly: one `host-route` answer first, one control call at start and one per delivered host event, owners launched only from returned dispatch actions, contracts sent only while the run is new or a summary carries `delivery_contract_required`, and no call without an event: `controller_turns == 1 + delivered_events` (per D6, D12, D21).
- Time is whole simulated minutes from `NOW`; each owner runs 60 minutes (two tasks, each a 20-minute worker then a distinct 10-minute reviewer, so exactly one support agent is busy), then finishes `merged` with its delivery complete (per D23).
- The simulated host refuses any owner launch that would exceed its declared agents (controller 1 + each live owner + each live support agent, counting the new owner and its first support agent) and any scripted launch, counting refusals. Each owner's worker and reviewer steps are distinct support agents, and the replay asserts the host never exceeds its declared agents at any minute, so the reviewer-never-waits evidence is measured rather than assumed (per D27). It is a fixture, not a live Claude host (per D14).
- Metrics (per D12): `controller_turns`; `wait_producing_responses`; `owner_dispatches`; `host_refusals`; `time_to_first_useful_result` (minutes to the first merged finish); `makespan` (the minute of the finalizing control call); `worker_utilization` = `[busy support slot-minutes, Σ over makespan minutes of (declared − controller − live owners)]`. No percentage or target field exists.
- The baseline is the committed exact-match fixture. It starts as the spec's prediction; when the implementation measures something else, commit the measured values and state each deviation and its cause in the task report — never change runtime behavior to meet the prediction (per D12).

- [ ] **Step 1: Write the failing test and the baseline**

`T/fixtures/admission-replay/baseline.json`:

```json
{
  "measured": {"controller_turns": 3, "declared_slots": 4, "host_refusals": 0, "makespan": 120, "max_parallel": 2, "owner_dispatches": 2, "time_to_first_useful_result": 60, "wait_producing_responses": 2, "worker_utilization": [120, 240]},
  "scripted_refusal": {"controller_turns": 3, "declared_slots": 4, "host_refusals": 1, "makespan": 60, "max_parallel": 2, "owner_dispatches": 2, "time_to_first_useful_result": 60, "wait_producing_responses": 2, "worker_utilization": [60, 120]},
  "seven_slots": {"controller_turns": 3, "declared_slots": 7, "host_refusals": 0, "makespan": 60, "max_parallel": 2, "owner_dispatches": 2, "time_to_first_useful_result": 60, "wait_producing_responses": 2, "worker_utilization": [120, 240]}
}
```

`T/test_admission_replay.py`:

```python
"""Deterministic replay of the measured two-owner, limited-slot shape (#150 D12, D23).

A simulated adapter follows orchestrate-issues to the letter over the real
workflow-state CLI; the host is a fixture, not a live Claude host (D14).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest

from .test_delivery_workflow import (ARTIFACT_BUDGET, MODEL, NOW, POLICY, SOURCES,
                                     BuilderHarness, load)

BASELINE = Path(__file__).with_name("fixtures") / "admission-replay" / "baseline.json"
ISSUES = (12, 14)
OWNER_MINUTES = 60
PROPOSED = {"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"}
DISPATCH = {"spawn", "resume", "retry", "delivery_remainder"}


def at(minute):
    start = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


TASK_STEPS = (("worker", 20), ("reviewer", 10), ("worker", 20), ("reviewer", 10))


class SimulatedHost:
    """A fixture host where the controller, each owner and each support agent is one agent.

    An owner runs its two tasks in order, each a worker then a distinct reviewer, so
    exactly one of its support agents is live at any minute of its run (D12, D14).
    """

    def __init__(self, capacity, refuse=()):
        self.capacity, self.refuse, self.refusals = capacity, set(refuse), 0
        self.owners = {}  # launch action id -> (start, end)
        self.support = []  # (launch action id, role, start, end), one entry per agent

    def live(self, minute):
        return sum(1 for start, end in self.owners.values() if start <= minute < end)

    def agents(self, minute):
        busy = sum(1 for _, _, start, end in self.support if start <= minute < end)
        return 1 + self.live(minute) + busy

    def launch(self, action_id, minute):
        # The owner and its first support agent must both fit.
        if action_id in self.refuse or self.agents(minute) + 2 > self.capacity:
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
        host = SimulatedHost(slots, refuse)
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
        refused = self.cli("control", *run, "--request-file", "-", ok=False, stdin=json.dumps(
            self.control_request(list(ISSUES), now=at(0))).encode())
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -15`
Expected at the Task-5 head: PASS, or a metric mismatch naming the differing member. At the base commit every case fails (`host-route` does not exist). The replay is evidence over Tasks 1–5, so a failure other than a baseline value mismatch is a defect in those tasks: report it as a blocker rather than editing runtime code here.

- [ ] **Step 3: Settle the baseline**

If only baseline values differ, write the measured metrics into `baseline.json`, re-run, and list every deviation from the prediction with its cause in the task report (per D12). Add `home/common/agent-skills/tests/test_admission_replay.py \` to `agent-workflow-tests` after `test_host_admission.py`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -3`
Expected: `OK`, 4 tests.

Run: `grep -c test_admission_replay.py justfile`
Expected: `1` (`0` at the base commit).

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_admission_replay.py \
  home/common/agent-skills/tests/fixtures/admission-replay/baseline.json justfile
git commit -m "test(workflow-state): replay two owners on four slots and record the baseline (#150)"
```
