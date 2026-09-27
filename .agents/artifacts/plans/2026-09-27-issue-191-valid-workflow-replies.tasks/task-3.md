# Task 3: `suspend` replies with a closed v2 `suspended`, or the terminal replay at the stall bound

Per D6, D7, D9. Abbreviations: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `S/delivery_model/_wire.py`, `S/workflow-state.py`
- Test: `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py`,
  `T/test_workflow_state.py`

**Interfaces:**
- Consumes: `LifecycleHarness.validated_response(self, stdout: str) -> dict`
  from Task 1. It pipes `stdout` through the real `workflow-response` boundary,
  asserts exit 0 and byte-equal canonical output, and returns the decoded
  reply.
- Consumes: `DeliveryRuntime.custody_for_record(issue, kind, record) -> dict`,
  reached as `_delivery().custody_for_record`. It is the one custody renderer.
- Consumes: `direct_terminal(*, issue, run_id, source, reason, blockers, result) -> dict`
  in `S/workflow-state.py`, the existing `kind: terminal` envelope builder that
  `direct-owner`'s replay uses.
- Consumes: the `phase_gate` branch and fixture that Task 2 added (the fixture
  name set already includes `"phase_gate"`).
- Produces: the `suspended` wire kind, which `workflow-state suspend` prints on
  a granted suspension:
  `{"interface_version": 2, "kind": "suspended", "run_id": str, "issue": int, "custody": <implementation custody>, "blocked_on": "usage_limit"|"transport"|"human_gate"|"external", "reentry": str}`.
- Produces: at the stall bound, `suspend` prints
  `direct_terminal(issue=args.issue, run_id=args.run_id, source="lifecycle", reason=<the stopped result's state>, blockers=[], result=<the issue outcome>)`.
- Produces: `LifecycleHarness.suspend(...)` returns the decoded, validated reply
  when `ok=True`, and the `CompletedProcess` when `ok=False`.
- Produces: the fixture `workflow_responses(model)["suspended"]`.

**Invariants:**
- `suspend` persists exactly what it persists today, both for a granted
  suspension and at the stall bound.
- `stalled_resumes` and `attempt` leave the wire. They stay in the ledger (D6).
- For a direct run, the stall-bound reply equals the replay that the next
  `direct-owner` call returns for that issue.
- `_workflow_response` stays a closed dispatch whose fallthrough is `_reject()`.
  `blocked_on` is the owner-reachable literal set. `unknown` (the reaper) and
  `host_capacity` (control) are refused.

- [ ] **Step 1: Write the failing tests**

(a) In `T/_delivery_model_fixtures.py`, in `workflow_responses`'s returned
dict, insert this entry directly before the `"terminal"` entry:

```python
        "suspended": {"interface_version": 2, "kind": "suspended", "run_id": "run-1",
                      "issue": 151, "custody": active, "blocked_on": "usage_limit",
                      "reentry": "/from-issue 151 --auto"},
```

(b) In `T/test_delivery_model.py`, `test_workflow_response_validation_is_structural_only`,
add `"suspended"` to the expected fixture-name set, so its last line reads
`"host_route", "host_route_unsupported", "phase_gate", "suspended"})`. Insert
this method immediately before `def test_current_launch_and_null_contract_correlations_are_exact`:

```python
    def test_suspended_reply_is_closed_and_names_an_owner_cause(self):
        """#191 D6: a granted suspension replies with one closed v2 `suspended`."""
        suspended = workflow_responses(self.model)["suspended"]
        for cause in ("usage_limit", "transport", "human_gate", "external"):
            value = {**copy.deepcopy(suspended), "blocked_on": cause}
            with self.subTest(blocked_on=cause):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        missing = copy.deepcopy(suspended)
        del missing["reentry"]
        for name, bad in {
            "the unversioned reply": {"kind": "suspended", "issue": 151, "attempt": 1,
                                      "blocked_on": "usage_limit", "stalled_resumes": 0,
                                      "reentry": "/from-issue 151 --auto"},
            "extra member": {**copy.deepcopy(suspended), "stalled_resumes": 0},
            "missing member": missing,
            "interface 1": {**copy.deepcopy(suspended), "interface_version": 1},
            "remainder custody": {**copy.deepcopy(suspended), "custody": custody("remainder")},
            "another issue's custody": {**copy.deepcopy(suspended), "issue": 152},
            "the reaper's cause": {**copy.deepcopy(suspended), "blocked_on": "unknown"},
            "control's cause": {**copy.deepcopy(suspended), "blocked_on": "host_capacity"},
            "empty reentry": {**copy.deepcopy(suspended), "reentry": ""},
            "null run": {**copy.deepcopy(suspended), "run_id": None},
        }.items():
            with self.subTest(invalid=name):
                self.assert_invalid(bad, "workflow-response")
```

(c) In `T/test_workflow_state.py`, `LifecycleHarness.suspend`: bind the
`self.run_cli(...)` result to `completed` and end with
`return self.validated_response(completed.stdout) if ok else completed`.
Insert this class immediately before `class ReconciledReplyBoundaryTest`,
which Task 1 added:

```python
class SuspendReplyTest(LifecycleHarness, unittest.TestCase):
    """#191 D6: `suspend` replies with `suspended`, or the replay at the stall bound."""

    def test_a_direct_stall_bound_suspend_replies_with_the_next_replay(self):
        owner = self.acquire_direct(issue=16)
        self.run_id = owner["run_id"]
        recorded = {"path": owner["worktree"], "state": "matching_issue_branch"}
        for index in range(3):
            parked = self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                                  now=f"2026-08-20T10:0{2 * index + 1}:00Z")
            self.assertEqual(parked["custody"]["action_id"], f"16:1:{index + 1}")
            resumed = self.direct_owner(
                issue=16, now=f"2026-08-20T10:0{2 * index + 2}:00Z",
                worktree=self.worktree_fact(16, recorded=recorded))
            self.assertEqual(resumed["launch_kind"], "resume")
        stalled = self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                               now="2026-08-20T10:08:00Z")
        replay = self.direct_owner_at_root(
            self.root, self.direct_request(issue=16, now="2026-08-20T10:09:00Z"))
        self.assertEqual(stalled, self.validated_response(replay.stdout))
        self.assertEqual((stalled["kind"], stalled["source"], stalled["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text())["issues"]["16"]
        self.assertEqual((persisted["attempts"][-1]["result_source"], persisted["outcome"]),
                         ("stalled", stalled["result"]))
```

`validated_response` asserts that each reply's bytes equal their canonical
form. Equal decoded values therefore mean byte-equal replies.

(d) Rewrite the four existing call sites, in three tests of
`WorkflowStateLifecycleTest`, that read the old `CompletedProcess`:

1. `test_suspend_subcommand_records_blocked_on_and_reentry`: bind
   `envelope = self.suspend(...)` and drop the `returncode` and `json.loads`
   lines. The expected dict becomes
   `{"interface_version": 2, "kind": "suspended", "run_id": self.run_id, "issue": 15, "custody": {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "15:1:1"}, "blocked_on": "usage_limit", "reentry": "/from-issue 15 --auto"}`.
   The ledger assertions that follow stay as they are.
2. `test_third_stalled_suspension_escalates_to_synthetic_stop`: in the loop,
   bind `envelope = self.suspend(...)`. Replace the two envelope assertions
   with `self.assertEqual((envelope["kind"], envelope["custody"]["launch"]), ("suspended", index + 1))`
   and `self.assertEqual(self.read_state()["issues"]["16"]["attempts"][-1]["stalled_resumes"], index)`.
   After the loop, `final = self.suspend(...)` stays. Replace
   `attempt = json.loads(final.stdout)` and the assertions after it with:
   ```python
        persisted = self.read_state()["issues"]["16"]
        attempt = persisted["attempts"][-1]
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "stalled")
        self.assertIsNone(attempt["blocked_on"])
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(persisted["outcome"], attempt["result"])
        self.assertEqual(final, {
            "interface_version": 2, "kind": "terminal", "issue": 16,
            "run_id": self.run_id, "source": "lifecycle", "reason": "stopped",
            "blockers": [], "result": attempt["result"],
            "reentry": "/from-issue 16 --auto",
        })
   ```
3. `test_prior_schema_ledger_upgrades_on_load`: call `self.suspend(...)`
   without binding it, and delete `self.assertEqual(completed.returncode, 0, completed.stderr)`.
   The helper now asserts success.

Call sites with `ok=False` keep the `CompletedProcess` and are unchanged. That
includes `test_suspend_rejects_a_nonactive_attempt_and_the_reserved_cause` and
`T/test_host_admission.py`'s `host_capacity` refusal. Every other call ignores
the return value.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `FAILED`. The `suspended` fixture and the four accepted causes are refused.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k SuspendReplyTest -k test_suspend_subcommand -k test_third_stalled 2>&1 | grep -E '^(FAIL|ERROR):|AssertionError|^Ran |^OK|^FAILED'`
Expected: `FAILED`, with `Tuples differ: (2, 'artifact-budget: invalid report\n') != (0, '')`.

- [ ] **Step 3: Implement**

1. `S/delivery_model/_wire.py`, `_workflow_response`: insert a `suspended`
   branch immediately before the `delivery_remainder` line. It checks, in
   order:
   - the exact member set via
     `_object(value, _members("interface_version kind run_id issue custody blocked_on reentry"))`;
   - `_v2(value)`, and `_string(value["run_id"], "suspended run")`;
   - `issue = _integer(value["issue"], "suspended issue", minimum=1)`;
   - `_reject()` unless
     `validate_custody_ref(value["custody"], issue=issue)["kind"] == "implementation"`;
   - `_reject()` unless `value["blocked_on"]` is in
     `{"usage_limit", "transport", "human_gate", "external"}`. This literal set
     follows the checkpoint branch's precedent;
   - `_string(value["reentry"], "reentry")`.

   It then returns `value`.
2. `S/workflow-state.py`, `command_suspend`: bind `runtime = _delivery()` after
   `now = format_utc(now_value)`. In the closure, keep every check, the
   `suspend_attempt` call, `state["updated_at"] = now` and, at the bound,
   `issue_state["outcome"] = copy.deepcopy(attempt["result"])`. Then:
   - at the bound, return `direct_terminal(issue=args.issue, run_id=args.run_id, source="lifecycle", reason=attempt["result"]["state"], blockers=[], result=issue_state["outcome"])`
     with `True`. These are the stored fields `direct-owner`'s replay reads, so
     the two replies are equal by construction;
   - otherwise, return
     `{"interface_version": 2, "kind": "suspended", "run_id": args.run_id, "issue": args.issue, "custody": runtime.custody_for_record(args.issue, "implementation", attempt), "blocked_on": attempt["blocked_on"], "reentry": reentry_command(args.issue)}`
     with `True`.

   The docstring's "the envelope carries back the re-entry line" stays true.

- [ ] **Step 4: Verify**

Summarize every run with the Step 2 `grep -E` filter.

1. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py` → `OK`.
2. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_host_admission.py` → `OK`. This takes about 12 minutes, so run it once. Every `suspend()` call is now a boundary regression.
3. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py` → `OK`. These call `suspend` through the CLI without reading its reply.
4. No rewritten test still reads a process result or a removed member. This
   fails at the start, naming all three tests:

```bash
python3 - <<'EOF'
import ast
path = "home/common/agent-skills/tests/test_workflow_state.py"
source = open(path, encoding="utf-8").read()
names = {"test_suspend_subcommand_records_blocked_on_and_reentry",
         "test_third_stalled_suspension_escalates_to_synthetic_stop",
         "test_prior_schema_ledger_upgrades_on_load"}
found = [node for node in ast.walk(ast.parse(source))
         if isinstance(node, ast.FunctionDef) and node.name in names]
assert len(found) == 3, [node.name for node in found]
stale = [node.name for node in found
         if any(token in ast.get_source_segment(source, node)
                for token in (".stdout", ".returncode", 'envelope["stalled_resumes"]'))]
raise SystemExit(f"stale suspend readers: {stale}" if stale else 0)
EOF
```

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/_delivery_model_fixtures.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(agent-skills): reply to suspend with a closed suspended or its terminal replay (#191)"
```
