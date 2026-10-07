# Task 1: Stop pass in orchestrate-issues §4 and its stop-failure report

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§4 and §5 only)
- Modify: `home/common/agent-skills/instruction-load.json` (profile `orchestration-dispatcher` only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (new class only)

**Interfaces:**
- Consumes: the module's `ORCHESTRATE` path constant and `normalized()` helper (both already defined); the existing `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` command form, whose stdout carries `current: true` or `current: false`.
- Produces: the §4 anchor `**Stop pass.**`, the phrase `run the stop pass` in the `finalize` and all-refused `delivery_contract` clauses, and the §5 heading phrase `**Stop failures**`. Nothing else consumes them.

**Invariants:**
- The text from `## 2. Bootstrap and observe` up to `## 3. Decide` is byte-identical to base (AC3, per D5).
- In §4 the stop pass precedes the first dispatch prose (`For \`spawn\`, \`resume\`, and \`retry\`, project the action`), per D1.
- Only `current: false` stops a handle; an unknown answer never does (per D3).
- The pass sends no observation, makes no control call and writes nothing (per D4).
- The `orchestration-dispatcher` ceiling equals the edited SKILL.md's byte count (per D7).

- [ ] **Step 1: Write the failing test**

Append this class immediately before the `if __name__ == "__main__":` line:

```python
class SupersededOwnerStopPassContractsTest(unittest.TestCase):
    """#275: stop superseded owner handles before dispatch and at finalize."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def text(self):
        return normalized(ORCHESTRATE.read_text(encoding="utf-8"))

    def test_the_stop_pass_precedes_dispatch_and_runs_at_finalize(self):
        self.assert_ordered(
            self.text(), "## 4. Execute control actions",
            "**Stop pass.**",
            "carries a `spawn`, `resume`, `retry` or `delivery_remainder` action",
            "every owner handle this adapter process recorded beside an owner "
            "launch's `action_id` that has produced no final return",
            "`workflow-state check-launch --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>`",
            "On `current: false`, stop that handle through the host's task-stop",
            "Only after the pass, execute the response's actions in returned order.",
            "For `spawn`, `resume`, and `retry`, project the action",
            "Dispatch the owner in the background",
            "For `finalize`, first run the stop pass,",
            "the action ends the run as `finalize` does: run the stop pass,",
            "## 5. Final report")

    def test_a_stop_failure_is_reported_and_never_blocks_dispatch(self):
        self.assert_ordered(
            self.text(), "**Stop pass.**",
            "a missing or already exited handle counts as stopped",
            "is unknown, never `current: false`",
            "A stop failure never blocks dispatch",
            "sends no observation, makes no control call and writes nothing",
            "## 5. Final report",
            "**Stop failures**",
            "Do not perform a second ledger read")

    def test_section_two_carries_no_stop_pass(self):
        text = self.text()
        section = text[text.index("## 2. Bootstrap and observe"):text.index("## 3. Decide")]
        self.assertNotIn("stop pass", section.lower())
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SupersededOwnerStopPass`
Expected: FAIL — 2 failures (`**Stop pass.**` not found), `test_section_two_carries_no_stop_pass` passes.

- [ ] **Step 3: Write the minimal implementation**

In `SKILL.md` §4, insert this paragraph immediately after the closed-kinds paragraph (the one ending `fail loudly.`) and before `For \`spawn\`, \`resume\`, and \`retry\`, project the action`, hard-wrapped near 80 columns like its neighbours (per D1–D4):

> **Stop pass.** Before executing the first action of a response that carries a `spawn`, `resume`, `retry` or `delivery_remainder` action, stop the superseded owners. The candidates are every owner handle this adapter process recorded beside an owner launch's `action_id` that has produced no final return. An interim notification under §2 rule (a) is not a final return. The current wait handle and non-owner handles are never candidates, and a handle this response dispatches becomes one only once it is dispatched. For each candidate, run
> `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
> with the `action_id` recorded beside that handle. On `current: false`, stop that handle through the host's task-stop and mark it stopped; a missing or already exited handle counts as stopped. On `current: true`, leave it running. A `check-launch` that exits non-zero, or whose output cannot be parsed, is unknown, never `current: false`: leave the handle a candidate. A failed stop also leaves it a candidate, and the next pass tries both again. A stop failure never blocks dispatch: keep it for §5 and continue. The pass sends no observation, makes no control call and writes nothing, so a later notification from a stopped handle still falls under §2 rule (b). Only after the pass, execute the response's actions in returned order.

Put the `workflow-state check-launch …` command on its own line, as §2 rule (b) does, so it normalizes to the exact anchor.

Change the `finalize` clause's opening from `For \`finalize\`, first clear \`current_wait_id\`,` to `For \`finalize\`, first run the stop pass, then clear \`current_wait_id\`,`; the rest of that clause is unchanged.

In the `delivery_contract` clause, change `the action ends the run as \`finalize\` does: clear the wait state as for \`finalize\` and render §5 from this response.` to `the action ends the run as \`finalize\` does: run the stop pass, clear the wait state as for \`finalize\` and render §5 from this response.`

In §5, insert immediately before `Do not perform a second ledger read`, per D6:

> Below the table, under **Stop failures**, list each owner handle the final stop pass still left a candidate because its stop failed or its `check-launch` answer was unknown, with its `action_id` and the failure; omit the list when there is none. These are facts local to this adapter, not fields of the finalize summary.

Then run `wc -c < home/common/claude-code/skills/orchestrate-issues/SKILL.md`, set the `orchestration-dispatcher` profile's `ceiling_bytes.claude` to that number, and append to that profile's `note`: ` Ceiling raised for #275: §4's stop pass and §5's stop-failure list (#155 D10).` (per D7). No other profile changes.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SupersededOwnerStopPass -k InterimOwnerNotification -k LaunchFencedWorker`
Expected: PASS, 0 failures (the two #275 tests now pass; the rule (a)/(b)/(c) assertions stay green, AC3).

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: PASS (fails with an `exceed ceiling` message if the ceiling step was skipped).

Run: `git diff -U0 origin/main -- home/common/claude-code/skills/orchestrate-issues/SKILL.md | grep '^@@'`
Expected: no hunk starts inside §2 (every hunk's line number is past the `## 4. Execute control actions` heading, line 267 at base).

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(orchestrate-issues): stop superseded owner handles before dispatch (#275)"
```
