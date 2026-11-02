# Task 5: orchestrate-issues liveness rules and computed sleeps

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json` (only if the gate below fails)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`ORCHESTRATE_MACHINE_TEXT`, `CLAUDE_POLICY_ENTRIES`)
- Test: `home/common/agent-skills/tests/test_shell_example_contracts.py` (new `ObserverSleepExampleTest`)

**Interfaces:**
- Consumes: Task 1's `bindings.workflow.orchestration.stall_minutes`; Task 3's `workflow-state owner-liveness` argv and its reply members `verdict`, `since` and `wait_seconds`; Task 4's control wait member `wait_seconds`.
- Produces: the adapter text Task 6's replay follows: rule (a) arms a liveness check, a new rule (d) handles its wake, and §4 arms the wait observer as `sleep <wait_seconds>`.

**Invariants:**
- §1 maps `bindings.workflow.orchestration.stall_minutes` next to `attempt_budget_minutes`, and passes it only to `owner-liveness`. Absent or `null` means rules (a) and (d) arm nothing, and rule (a) is exactly today's rule. The control request does not change (D1).
- Rule (a) still sends no observation, runs no `check-launch`, writes nothing, stops nothing and relaunches nothing. With a bound set, it runs `owner-liveness` without `--since`, validates the reply, and stores its `since` as the handle's `liveness_since`, replacing an earlier one. It arms one observer on `live` only when the handle has none (D6, D7).
- Rule (d) is a fourth host-notification class. It ignores a wake whose owner handle has a final return or was stopped. Otherwise it runs `owner-liveness --since <liveness_since>`: `live` re-arms for `wait_seconds`; `not_current` and `past_deadline` do nothing; `stalled` stops the task, marks the handle stopped, and sends exactly one `unavailable` owner observation for that custody, even when the stop failed. That verdict stands in for rule (b)'s `check-launch`. An owner handle's final return or stop cancels its liveness observer, and a missing or already exited observer counts as cancelled (D8, D10).
- Rule (c) excludes liveness observer handles. Liveness state is process-local like the wait fields, and the restart sentence covers liveness observers (spec "Adapter behavior").
- §4 arms the wait observer as one background `sleep <wait_seconds>`. No sentence in the skill invokes `date` (D9, D13).
- Every observer is one background `sleep <wait_seconds>`: no loop and no repeated short sleep.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_skill_contracts.py`, add these items to `ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE]`:

```python
        "workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id> --stall-minutes <stall_minutes>",
        "workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id> --stall-minutes <stall_minutes> --since <liveness_since>",
        "`wait_seconds`", "`liveness_since`", "`stalled`", "`past_deadline`",
        "`not_current`",
```

and add `"bindings.workflow.orchestration.stall_minutes"` to `CLAUDE_POLICY_ENTRIES["orchestrate-issues/SKILL.md"]`.

In `test_shell_example_contracts.py`, append (the module already imports `re` and defines `_examples` and `SOURCE_TREES`):

```python
ORCHESTRATE_SKILL = SOURCE_TREES["claude-only"] / "orchestrate-issues/SKILL.md"
# A `date` invocation: at a line start or after a shell operator, `$(` or a
# backtick, followed by an option, a closing backtick or parenthesis, or the end.
DATE_INVOCATION = re.compile(r"(?:^|[;&|(`]|\$\()\s*date(?:\s+[-+]|\s*[`)]|\s*$)", re.M)


class ObserverSleepExampleTest(unittest.TestCase):
    """#310 D9, D13: observers sleep for a helper-computed time; no skill text runs `date`."""

    def test_the_date_pattern_finds_invocations_and_spares_prose(self):
        for text in ("date -j -f %s 1", "x=$(date -u +%s)", "`date`", "sleep 1; date -d now",
                     "  date +%s"):
            with self.subTest(text=text):
                self.assertIsNotNone(DATE_INVOCATION.search(text))
        for text in ("update the date arithmetic", "a deadline date", "`deadline_at`",
                     "validate -- date-time", "candidate"):
            with self.subTest(text=text):
                self.assertIsNone(DATE_INVOCATION.search(text))

    def test_the_skill_runs_no_date(self):
        self.assertIsNone(DATE_INVOCATION.search(ORCHESTRATE_SKILL.read_text(encoding="utf-8")))

    def test_the_observer_example_sleeps_for_wait_seconds(self):
        examples = [payload[0].text for _, kind, payload
                    in _examples(ORCHESTRATE_SKILL.read_text(encoding="utf-8"))
                    if kind == "call"]
        self.assertIn("sleep <wait_seconds>", examples)
```

`SOURCE_TREES["claude-only"]` is `home/common/claude-code/skills` (`skill_tree_support.py`). The dispatch prompt's no-wait-loops clause also holds the spans `sleep` and `sleep N`, so the test asserts membership only.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_orchestrate_documents_carry_their_machine_text -k test_claude_source_phase_entries`
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py -k ObserverSleepExample`
Expected: FAIL on the new argv, key and binding pins, and on `test_the_observer_example_sleeps_for_wait_seconds`. `test_the_date_pattern_finds_invocations_and_spares_prose` and `test_the_skill_runs_no_date` pass already; the first proves the second can fail.

- [ ] **Step 3: Edit the skill**

In `home/common/claude-code/skills/orchestrate-issues/SKILL.md`:

1. §1, after the bullet that maps `attempt_budget_minutes` and `max_parallel` to the request, add:

   ```markdown
   - Retained `bindings.workflow.orchestration.stall_minutes`, when present and non-null, is
     `stall_minutes`, the owner stall bound of §2 rules (a) and (d); pass it only to
     `owner-liveness`. Absent or null, those rules arm no liveness check.
   ```

2. §2 rule (a): keep its first sentence as it is, then append to the same list item:

   ````markdown
     When `stall_minutes` is set, also run the first call below for that launch's `action_id`,
     and keep the validated reply's `since` as the handle's `liveness_since`, replacing any
     earlier one. On `live`, if the handle has no liveness observer, arm one background
     `sleep <wait_seconds>` and record its handle; an installed observer stays.

     ```text
     workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --stall-minutes <stall_minutes> | artifact-budget validate-report --boundary workflow-response --input -
     workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --stall-minutes <stall_minutes> --since <liveness_since> | artifact-budget validate-report --boundary workflow-response --input -
     ```
   ````

   The fence is indented two spaces, inside the list item.

3. §2 rule (c): change "The handle is neither an owner launch's nor the current wait handle" to "The handle is neither an owner launch's, a liveness observer's, nor the current wait handle".

4. §2, after rule (c), add:

   ```markdown
   - (d) **Liveness wake.** The handle is a liveness observer's. Ignore it when its owner handle
     has a final return or was stopped. Otherwise run the second call above and act on its
     `verdict`: `live` arms a new observer for `wait_seconds`; `not_current` and `past_deadline`
     do nothing; `stalled` stops the owner's task through the host's task-stop, marks the handle
     stopped and sends exactly one `unavailable` owner observation for that custody in the next
     control call, even when the stop failed, and that verdict stands in for rule (b)'s
     `check-launch`. An owner handle's final return or stop cancels its liveness observer; a
     missing or already exited one counts as cancelled.
   ```

5. §2's restart paragraph: change "the host reaps or cancels inherited detached wait observers before any rearm from a returned wait ID; the wait fields below cannot adopt their handles." to "the host reaps or cancels inherited detached wait and liveness observers before any rearm; the wait and liveness fields are process-local and cannot adopt their handles."

6. §4: replace the sentence "Arm the one-shot observer for the returned wake conditions and its `deadline_at`; every wait carries one (" with "Arm the observer as one background `sleep <wait_seconds>`; every wait carries one (", keeping the rest of that paragraph unchanged.

Do not edit the owner dispatch prompt block (the `orchestration-issue-owner` region). The `orchestrated-issue-owner` instruction profile measures it.

- [ ] **Step 4: Verify, and raise the ceiling only if needed**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py`
Expected: PASS, including `SourceTreeSweepTest` (the new argv lines are sanctioned lifecycle calls, like the `host-route` example) and `VocabularyGuardTest`.

Run: `just agent-instruction-budget`
Expected: the `orchestration-dispatcher` profile fails, because its Claude ceiling (25605 bytes) equals the file's size at the base. Then, in `instruction-load.json`, set that profile's `ceiling_bytes.claude` to the new byte size of `orchestrate-issues/SKILL.md` (`wc -c`), and append to its `note`: ` Ceiling raised for #310: §2's liveness check after an interim notification and its wake rule (#155 D10).` Change no other profile. Then:

Run: `just agent-instruction-budget --raise-label` and `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: PASS. If the plain gate passed without a raise, skip this edit.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/tests/test_shell_example_contracts.py
git commit -m "feat(orchestrate-issues): liveness check after an interim notification (#310)"
```
