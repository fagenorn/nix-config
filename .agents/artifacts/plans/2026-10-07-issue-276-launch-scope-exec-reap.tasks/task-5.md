# Task 5: Adapter sweep in the stop pass, and CLAUDE.md

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. Edit one anchor in `SupersededOwnerStopPassContractsTest`, and append the class `LaunchScopeSweepContractsTest` immediately before `if __name__ == "__main__":`.

**Interfaces:**
- Consumes: `launch-scope reap --repo-root R --run-id I --sweep` from Task 3. It prints one canonical JSON report and exits 0 when it skipped nothing, 1 when it skipped a launch, and 2 on an error with empty stdout.
- Produces: nothing that a later task consumes.

**Invariants:**
- §2 of orchestrate-issues is not edited. `test_section_two_carries_no_stop_pass` stays green.
- The sweep runs once per stop pass, after the stops and before the response's first action. That covers `finalize` and the all-refused `delivery_contract`, because both already run the stop pass.
- A sweep that exits non-zero never blocks dispatch, and §5 lists only the last such sweep (D13).
- The pass still sends no observation and makes no control call. It now "writes nothing to the ledger" (D13).

- [ ] **Step 1: Write the failing test**

In `SupersededOwnerStopPassContractsTest.test_a_stop_failure_is_reported_and_never_blocks_dispatch`, replace the anchor `"sends no observation, makes no control call and writes nothing",` with `"sends no observation, makes no control call and writes nothing to the ledger",`. Then append before `if __name__ == "__main__":`:

```python
class LaunchScopeSweepContractsTest(unittest.TestCase):
    """#276: the stop pass ends with one sweep of the run's non-current launches."""

    SWEEP = "launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep"

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def test_the_stop_pass_ends_with_one_sweep_that_never_blocks(self):
        self.assert_ordered(
            normalized(ORCHESTRATE.read_text(encoding="utf-8")),
            "**Stop pass.**",
            "On `current: false`, stop that handle through the host's task-stop",
            "writes nothing to the ledger",
            f"After its stops, the pass ends by running `{self.SWEEP}` once",
            "A sweep that exits non-zero never blocks dispatch",
            "Only after the pass, execute the response's actions in returned order.",
            "## 5. Final report", "**Stop failures**",
            "the pass's last sweep when it exited non-zero, with its exit code and its "
            "`skipped` launches",
            "omit the list when there is none")

    def test_claude_md_describes_launch_scope(self):
        self.assert_ordered(
            normalized((REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")),
            "**Agent helper package.**", "`launch-scope` (#276)",
            "AGENT_LAUNCH_SCOPE=<run-id>/<action-id>/<nonce>",
            "`launch-scope reap --action-id`", "`reap --sweep`",
            "agent-launch/<run-id>/<action-id>/")
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k StopPass -k LaunchScopeSweep 2>&1 | tail -5`
Expected: FAIL. Both new tests fail, and so does the edited #275 anchor.

- [ ] **Step 3: Write the minimal implementation**

1. **orchestrate-issues §4 `**Stop pass.**`.** Replace "The pass sends no observation, makes no control call and writes nothing, so a later notification from a stopped handle still falls under §2 rule (b)." with "The pass sends no observation, makes no control call and writes nothing to the ledger, so a later notification from a stopped handle still falls under §2 rule (b). After its stops, the pass ends by running `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep` once, which kills every process that a `launch-scope exec` of a non-current launch of this run left behind. A sweep that exits non-zero never blocks dispatch: keep its exit code and its `skipped` launches for §5." The sentence "Only after the pass, …" stays where it is, after this text.
2. **orchestrate-issues §5 `**Stop failures**`.** Replace "with its `action_id` and the failure; omit the list when there is none." with "with its `action_id` and the failure, and the pass's last sweep when it exited non-zero, with its exit code and its `skipped` launches; omit the list when there is none."
3. **CLAUDE.md, the `**Agent helper package.**` paragraph.** Right after the sentence that ends "which is how sdd's final gate lets ship skip a rerun (#263).", insert: "`launch-scope` (#276) contains a lifecycle agent's long commands: `launch-scope exec` checks that the launch (or worker) is live, runs the command in a new session whose processes carry `AGENT_LAUNCH_SCOPE=<run-id>/<action-id>/<nonce>`, and kills whatever the command left behind when it returns, while `launch-scope reap --action-id` (an owner, before its exit write) and `reap --sweep` (the orchestrate-issues stop pass, for every non-current launch of the run) kill the marked processes, and the process groups those processes prove, recorded in a host-local registry under the ledger repository's git common dir at `agent-launch/<run-id>/<action-id>/`."
4. **instruction-load.json (D9).** Run `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "exceed ceiling|^(OK|FAILED)"`. Raise each named profile and host to the reported `<N>`, and append " Ceiling raised for #276: the stop pass ends with a launch-scope sweep, and §5 lists a failed sweep (#155 D10)." to that profile's `note`. Rerun until it prints `OK`. The likely profiles are `orchestration-dispatcher` and `orchestrated-issue-owner`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3`
Expected: `OK`, with `SupersededOwnerStopPassContractsTest` (all three tests), `LaunchScopeSweepContractsTest` and the live ceilings all green.
Run this gate, which compares §2 byte for byte with `HEAD`:

```bash
PYTHONPATH="$PWD/python" timeout 60 python3 -c 'import pathlib, subprocess; p = "home/common/claude-code/skills/orchestrate-issues/SKILL.md"; cut = lambda t: t[t.index("## 2. Bootstrap and observe"):t.index("## 3. Decide")]; old = subprocess.run(["git", "show", "HEAD:" + p], capture_output=True, text=True, check=True).stdout; raise SystemExit(0 if cut(old) == cut(pathlib.Path(p).read_text()) else 1)'
```

Expected: exit 0, because §2 is unchanged.

- [ ] **Step 5: Commit**

Use `launch-commit` when your prompt carries a `Lifecycle worker:` line.

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md CLAUDE.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(orchestrate-issues): end the stop pass with a launch-scope sweep; describe launch-scope (#276)"
```
