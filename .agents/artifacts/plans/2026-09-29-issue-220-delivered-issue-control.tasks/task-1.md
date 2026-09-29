# Task 1: Gate delivered issues out of control's launch lanes

Acceptance 1 of #220, test-first. Per D1, D2, D3, D9, D11, D12.

**Files:**
- Create: `home/common/agent-skills/tests/test_delivered_control.py`
- Modify: `justfile` (the `agent-workflow-tests` recipe)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_control` only)

**Interfaces:**
- Consumes: `BuilderHarness`, `load`, `ARTIFACT_BUDGET`, `MODEL`, `NOW`, `POLICY`, `SOURCES`
  from `home/common/agent-skills/tests/test_delivery_workflow.py` (all exist at base);
  `runtime.delivery_complete(issue_state) -> bool` (the `DeliveryRuntime` facade over
  `DeliveryProjection.delivery_complete`, exists at base).
- Produces (later tasks append to this file and rely on these names):
  - module constants `DELIVERED = 207`, `LIVE = 209`, `ISSUES`, `DISPATCH`, and `at(minute) -> str`;
  - `DeliveredControlTest(BuilderHarness, unittest.TestCase)` with helpers
    `boundary(name, raw) -> CompletedProcess`, `validated(name, value) -> bytes`,
    `request(minute, *, recorded, owners=(), contracts=False, closed=()) -> bytes`,
    `control(minute, **kwargs) -> dict`, `delivered_shape() -> dict` (returns 209's custody
    reference `209:1:1`), `records(issue) -> (attempts, delivery_remainders)`,
    `after_delivery(minute, live) -> CompletedProcess`, and the attributes `self.ledger`
    (the run's `state.json` path) and `self.run_args`.
  - In `command_control`: a local `delivered: frozenset[int]` and a local
    `delivered_verdict(issue: int) -> dict[str, Any]`.

**Invariants:**
- A requested issue whose persisted ledger satisfies `runtime.delivery_complete`, evaluated
  after the opening admission settle, never reaches `_apply_one_issue_policy` in `control`:
  not in the analysis pass and not through `apply_policy` (per D1, D2).
- Such an issue gets no action, no delta (no `expired`), no `max_parallel` charge, no admission
  claim and no `admission.waiting` entry, and its ledger records are unchanged by the sweep
  (per D1, D12).
- A recovery proof or a candidate worktree observation for a delivered issue neither raises
  nor is consumed (per D9, D12).
- `direct-owner` and `_apply_one_issue_policy` are not edited (per D1).
- Delivery folding (`runtime.control_transitions`), admission settlement and summary
  rendering still run for delivered issues, unchanged.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_delivered_control.py` with exactly this content.
The fixture is pinned per D11: it reproduces the rejected `207:1:2` resume at base.

```python
"""Control never launches a delivered issue and never commits a rejected reply (#220)."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest

from .test_delivery_workflow import (ARTIFACT_BUDGET, MODEL, NOW, POLICY, SOURCES,
                                     BuilderHarness, load)

DELIVERED, LIVE = 207, 209
ISSUES = (DELIVERED, LIVE)
PROPOSED = {"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"}
DISPATCH = {"spawn", "resume", "retry", "delivery_remainder"}


def at(minute):
    start = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DeliveredControlTest(BuilderHarness, unittest.TestCase):
    """The issue-207 shape of run-20260927-204-205-206-207-208-209 over the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_delivered_control", package=True)

    def boundary(self, name, raw):
        """Run the real artifact-budget validator; return the completed process."""
        return subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             name, "--input", "-", "--policy", str(POLICY)],
            input=raw if isinstance(raw, bytes) else json.dumps(raw).encode(),
            capture_output=True, check=False)

    def validated(self, name, value):
        checked = self.boundary(name, value)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return checked.stdout

    def setup_run(self):
        self.project()
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": 7},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")
        self.run_args = ("--repo-root", self.root, "--run-id", "delivered")
        self.ledger = self.root / ".superpowers/workflows/delivered/state.json"
        self.cli("init-run", *self.run_args, "--now", at(0))
        self.worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-shape")
                          for n in ISSUES}
        self.built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=self.worktrees[n], now=at(0),
            source_reference="invocation:/orchestrate-issues 207 209")) for n in ISSUES}

    def request(self, minute, *, recorded, owners=(), contracts=False, closed=()):
        """One control request over the issues ``recorded`` names, in its order.

        ``recorded`` maps each issue to its recorded worktree state, or to None
        for a spawn at the absent candidate path. Issues in ``closed`` are
        observed with a closed tracker, as the adapter sees a delivered issue.
        """
        issues = list(recorded)
        def fact(n):
            if recorded[n] is None:
                return {"issue": n, "recorded": None,
                        "candidate": {"path": self.worktrees[n], "state": "absent"}}
            return {"issue": n, "candidate": None,
                    "recorded": {"path": self.worktrees[n], "state": recorded[n]}}
        request = self.control_request(
            issues, now=at(minute),
            contracts={str(n): self.built[n]["contract"] if contracts else None
                       for n in issues},
            intents={str(n): [self.built[n]["initial_intent"]] if contracts else []
                     for n in issues},
            worktrees=[fact(n) for n in issues])
        request["owners"] = list(owners)
        for item in request["tracker"]:
            if item["issue"] in closed:
                item["state"] = "closed"
        return json.dumps(request).encode()

    def control(self, minute, **kwargs):
        completed = self.cli("control", *self.run_args, "--request-file", "-",
                             stdin=self.request(minute, **kwargs))
        return json.loads(self.validated("workflow-response", completed.stdout))

    def observed(self, contract, when, kind, **facts):
        return self.build("observation", {"contract": contract,
            "observation_kind": kind, "source_kind": SOURCES[kind],
            "source_reference": f"probe:{kind}", "observed_at": when,
            "evidence": f"{kind} evidence", **facts})

    def fail_after_selection(self, custody, when):
        """The implementation custody stops after selecting; remainder r1 takes over."""
        contract = self.built[DELIVERED]["contract"]
        digest = self.model.canonical_digest(contract)
        self.selection = self.build("selected-output", {"contract": contract,
            "head": "a" * 40, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{DELIVERED}.md",
            "review_ref": "clean", "test_ref": "checks"})
        self.selected = self.observed(contract, when, "selected_output",
                                      selection=self.selection)
        historical = {"issue": DELIVERED, "state": "failed", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "discussion_items": [],
            "detail_state": "none", "report_path": None, "notes": "failed after selection"}
        summary = {"interface_version": 2, "issue": DELIVERED, "state": "terminal_failed",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": digest, "delivery_observations": [self.selected],
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "failed after selection"}
        remainder = json.loads(self.cli("finish", *self.run_args, "--now", when,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.assertEqual(remainder["kind"], "delivery_remainder")
        return remainder

    def deliver(self, custody, when):
        """Remainder custody walks every remaining stage and finishes delivery_complete."""
        issue, contract = DELIVERED, self.built[DELIVERED]["contract"]
        digest = self.model.canonical_digest(contract)
        url = f"https://github.com/fagenorn/nix-config/pull/{issue}"
        head, merge_sha = "a" * 40, "b" * 40
        observed = lambda kind, **facts: self.observed(contract, when, kind, **facts)
        facts = {
            "select_reviewed_output": [],
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
                self.cli("checkpoint-delivery", *self.run_args, "--now", when,
                    "--checkpoint-file", "-", stdin=self.validated("ship-checkpoint", {
                        "interface_version": 2, "issue": issue, "custody": custody,
                        "contract_digest": digest,
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
            observed("implementation_delivered", selection=self.selection,
                     merge_sha=merge_sha, integrated_ref="refs/heads/main",
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
        finished = json.loads(self.cli("finish", *self.run_args, "--now", when,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.assertEqual(finished["kind"], "delivery_complete")

    def delivered_shape(self):
        """Drive 207 to delivery through r1 after four launches, then spawn 209.

        Attempt 1 of 207 is spawned at minute 0 and resumed after each expiry at
        minutes 31, 62 and 93 (launches 2 to 4). It fails after selection at 94,
        minting r1 with deadline minute 274, and r1 finishes delivery_complete at
        95. 209 spawns at 250, with 207 observed closed and its worktree absent, so
        209's launch 1 is live until minute 280, past r1's deadline. Returns
        209's custody.
        """
        self.setup_run()
        spawned = self.control(0, recorded={DELIVERED: None}, contracts=True)
        launched = [a["custody"] for a in spawned["actions"] if a["kind"] in DISPATCH]
        for minute in (31, 62, 93):
            response = self.control(minute, recorded={DELIVERED: "matching_issue_branch"})
            launched = [a["custody"] for a in response["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([c["action_id"] for c in launched], [f"{DELIVERED}:1:4"])
        remainder = self.fail_after_selection(launched[0], at(94))
        self.assertEqual((remainder["custody"]["action_id"], remainder["deadline_at"]),
                         (f"{DELIVERED}:r1:1", at(274)))
        self.deliver(remainder["custody"], at(95))
        spawned = self.control(250, recorded={DELIVERED: "absent", LIVE: None},
                               contracts=True, closed={DELIVERED})
        live = [a["custody"] for a in spawned["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([c["action_id"] for c in live], [f"{LIVE}:1:1"])
        return live[0]

    def records(self, issue):
        """The ledger's attempts and remainders for ``issue``, as stored."""
        stored = json.loads(self.ledger.read_text(encoding="utf-8"))["issues"][str(issue)]
        return stored["attempts"], stored["delivery_remainders"]

    def after_delivery(self, minute, live):
        """The sweep that follows delivery: 209's owner is reported unavailable."""
        return self.cli("control", *self.run_args, "--request-file", "-", ok=False,
            stdin=self.request(minute, recorded={DELIVERED: "absent",
                                                 LIVE: "matching_issue_branch"},
                               closed={DELIVERED},
                               owners=[{"event_id": "209-unavailable", "issue": LIVE,
                                        "custody": live, "state": "unavailable"}]))

    def test_a_delivered_issue_is_never_relaunched(self):
        """Acceptance 1: past r1's deadline, control plans nothing for delivered 207.

        At the base commit the reaper suspends the still-active r1 and the resume
        lane relaunches it as `207:1:2` with null custody, which the boundary
        rejects after the ledger has committed the launch.
        """
        live = self.delivered_shape()
        before = self.records(DELIVERED)
        completed = self.after_delivery(275, live)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        checked = self.boundary("workflow-response", completed.stdout)
        self.assertEqual((checked.returncode, checked.stderr), (0, b""))
        self.assertEqual(checked.stdout, completed.stdout)
        response = json.loads(completed.stdout)
        dispatched = [a for a in response["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([(a["issue"], a["custody"]["action_id"]) for a in dispatched],
                         [(LIVE, f"{LIVE}:1:2")])
        self.assertEqual([d for d in response["deltas"] if d["issue"] == DELIVERED], [])
        self.assertEqual(self.records(DELIVERED), before)


if __name__ == "__main__":
    unittest.main()
```

Register it in the `justfile`'s `agent-workflow-tests` recipe: add the line
`    home/common/agent-skills/tests/test_delivered_control.py \` directly after
`    home/common/agent-skills/tests/test_delivery_workflow.py \`.

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py 2>&1 | tail -8`
Expected: FAIL in `test_a_delivered_issue_is_never_relaunched` at the boundary assertion,
`(2, b'artifact-budget: invalid report\n') != (0, b'')`. Control exits 0 but its reply
carries a `resume` for 207 with id `207:1:2` and null custody, which the boundary rejects.
Any other failure (a harness step asserting, a CLI exit) means the fixture drifted from the
base commit: stop and report it, do not adjust the fixture to pass.

- [ ] **Step 3: Write the minimal implementation**

All edits are inside `command_control`'s inner `control(state)` in
`home/common/agent-skills/scripts/workflow-state.py`.

1. Immediately after the opening `if not direct:` block that calls `settle_admission` and
   releases `owner_unavailable` claims, and before `analysis: dict[int, dict[str, Any]] = {}`,
   add:

```python
        # A delivered issue has nothing left to launch: its persisted ledger is
        # delivery-complete after the opening settle, so no lane plans it and the
        # one-issue policy never runs for it here (#220 D1, D2, D9).
        delivered = frozenset(
            issue for issue in request["issues"]
            if str(issue) in state["issues"]
            and runtime.delivery_complete(state["issues"][str(issue)]))

        def delivered_verdict(issue: int) -> dict[str, Any]:
            """The fixed verdict for a delivered issue: terminal, unchanged, no dispatch."""
            issue_state = state["issues"][str(issue)]
            return {"operation": "terminal", "changed": False,
                    "issue_state": copy.deepcopy(issue_state),
                    "attempt": issue_state["attempts"][-1] if issue_state["attempts"] else None,
                    "requirements": [], "uses_candidate": False, "desired": "terminal",
                    "expired": False}
```

   The verdict carries every key control reads from a policy result (`operation`, `changed`,
   `issue_state`, `attempt`, `requirements`, `uses_candidate`, `desired`, `expired`) and no
   `custody_kind`.
2. In the analysis loop, first statement of the loop body:
   `if issue in delivered: analysis[issue] = delivered_verdict(issue); continue` (written as
   an `if` block).
3. In `apply_policy`, first statement: `if issue in delivered:` set
   `planned[issue] = delivered_verdict(issue)` and return it. This is the single entry every
   dispatch lane goes through (per D1).
4. In the remainder-1 lane's skip condition (the `if (issue_state is None or ... ): continue`
   block before `slot_withheld`), add `or issue in delivered` right after
   `issue_state is None`, so a delivered issue is never counted in `waiting` (per D12).
5. In the candidate-worktree replay loop (the one that begins
   `actionless_replay = not dispatch_results`), extend the first skip to
   `if issue_state is None or not issue_state["attempts"] or issue in delivered: continue`.
   Without it a delivered remainder issue observed with a candidate raises
   `current control action requires a recorded worktree observation`, because the verdict no
   longer carries `custody_kind` `remainder` (per D9, D12).

No other lane needs an edit: with `desired` `terminal` and `expired` False, the recover,
resume, refuse/retry, expired-reap and spawn lanes skip the issue.

- [ ] **Step 4: Verify**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py 2>&1 | tail -3`
Expected: `OK`, 1 test.

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -3`
Expected: `OK` (the remainder, recovery and replay tests stay green).

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && if ! grep -q 'tests/test_delivered_control.py' justfile; then exit 1; fi && git diff --quiet 3081d23 -- home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow_delivery_wire.py && echo scoped`
Expected: `scoped` (registered, and the delivery runtime files are untouched by this task).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_delivered_control.py justfile \
  home/common/agent-skills/scripts/workflow-state.py
git commit -m "fix(issue-220): never plan a launch for a delivered issue in control"
```

The message ends with the two trailer lines from the plan's Global Constraints.
