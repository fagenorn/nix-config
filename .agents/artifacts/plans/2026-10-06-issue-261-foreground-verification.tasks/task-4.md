# Task 4: The dispatcher's interim owner case and final verification

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (`## 2. Bootstrap and observe`, the task-handle classification list)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 2's edit to the owner-launch blockquote of the same file (leave it alone); Task 3's owner paragraph, which is why an owner can legitimately be live after an interim notice.
- Produces: the dispatcher's lettered cases (a) interim owner notification, (b) owner return without a terminal write, (c) non-owner hand-back (per D9).

**Invariants:**
- The interim case is first, and for it the dispatcher sends no observation, runs no `check-launch`, writes nothing, stops no task and relaunches nothing (per D6).
- Cases (b) and (c) keep their current text apart from their letters.
- A wake of the current wait handle stays outside every case.

- [ ] **Step 1: Write the failing test and move the #222 anchors**

In `LaunchFencedWorkerContractsTest.test_the_dispatcher_handles_both_cases_without_judgment`, change the anchors `"a wake of the current wait handle is neither case"` → `"a wake of the current wait handle is none of these cases"`, `"(a) **Owner return without a terminal write.**"` → `"(b) **Owner return without a terminal write.**"` and `"(b) **Non-owner hand-back.**"` → `"(c) **Non-owner hand-back.**"` (per D9). Then append this class after `InterimChildResultContractsTest` (or after `ProgressMarkerContractsTest` if that class is absent):

```python
class InterimOwnerNotificationContractsTest(unittest.TestCase):
    """#261: the dispatcher does not observe an interim owner notification."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def test_an_interim_owner_notification_is_the_first_case(self):
        self.assert_ordered(
            normalized(ORCHESTRATE.read_text(encoding="utf-8")),
            "## 2. Bootstrap and observe",
            "a wake of the current wait handle is none of these cases",
            "(a) **Interim owner notification.**",
            "The handle is an owner launch's, and the host marks the notification interim",
            "The owner is still running, so send no observation, run no "
            "`check-launch`, write nothing, stop no task and relaunch nothing",
            "the same handle notifies again with the owner's real return.",
            "(b) **Owner return without a terminal write.**",
            "(c) **Non-owner hand-back.**",
            "## 3. Decide")
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k dispatcher -k interim_owner 2>&1 | tail -6`
Expected: FAIL — `none of these cases` not found in both tests.

- [ ] **Step 3: Implement**

In `orchestrate-issues/SKILL.md` `## 2. Bootstrap and observe`:
- `handle is neither case and keeps its wait-ID handling below:` becomes `handle is none of these cases and keeps its wait-ID handling below:`.
- Insert as the first list item, before the owner-return case (per D6):

```markdown
- (a) **Interim owner notification.** The handle is an owner launch's, and the
  host marks the notification interim: the owner stopped with background work
  of its own still running, or its result may be interim. The owner is still
  running, so send no observation, run no `check-launch`, write nothing, stop
  no task and relaunch nothing; the same handle notifies again with the
  owner's real return.
```

- Relabel `- (a) **Owner return without a terminal write.**` to `- (b) …` and `- (b) **Non-owner hand-back.**` to `- (c) …`; their bodies are unchanged.

Then run `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E '^profile|exceed' | head -20`; for each `profile <id> on <host>: hot <N> bytes exceed ceiling <M>` line set that ceiling to `<N>` and append once to that profile's `note`: `Ceiling raised for #261: §2's interim owner notification case (#155 D10).`

- [ ] **Step 4: Verify the task**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -4`
Expected: `OK` (installed-tree tests skipped).

- [ ] **Step 5: Commit**

Stage exactly the files listed above, then
`launch-commit <Lifecycle worker values> -- -m "feat(orchestrate-issues): leave an interim owner notification unobserved (#261)" -m "<trailers>"`.

- [ ] **Step 6: Full verification of the branch**

Each command runs in the foreground with Bash timeout 1800000 (above the expected duration) when the session runs under the raised `BASH_MAX_TIMEOUT_MS` (per D12), otherwise the pre-#261 host maximum 600000, its output in a log that ends with an `exit=` line. If the host moves one to the background, wait for that `exit=` line within the same turn; never end the turn while it runs.

```bash
log="${TMPDIR:-/tmp}/awt-261.log"
{ just agent-workflow-tests; echo "exit=$?"; } > "$log" 2>&1
grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED|^exit=' "$log" | tail -8
blog="${TMPDIR:-/tmp}/build-261.log"
{ just build; echo "exit=$?"; } > "$blog" 2>&1
tail -3 "$blog"
```

Expected: the test log ends `OK` (skips allowed) then `exit=0`; the build log ends `exit=0`. Any `FAIL:`/`ERROR:` line, or a nonzero `exit=`, means the branch is incomplete: fix in the task that owns the failing file and re-run. Remove both logs afterwards. This step changes no file and needs no commit.
