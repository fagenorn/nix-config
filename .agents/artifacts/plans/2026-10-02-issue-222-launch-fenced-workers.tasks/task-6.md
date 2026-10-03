# Task 6: Dispatcher rules (a) and (b), and CLAUDE.md

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (`## 2. Bootstrap and observe`)
- Modify: `CLAUDE.md` (the `.superpowers/` paragraph under **Claude Code is declaratively managed**)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (methods added to `LaunchFencedWorkerContractsTest`)

**Interfaces:**
- Consumes: `workflow-state check-launch` (unchanged) and control's existing `unavailable` owner observation. From Tasks 1–5: the `workers` registry, `launch-commit`, and the owner-exit refusal, which CLAUDE.md now describes. The test module constants `ORCHESTRATE` and `REPO_ROOT` already exist.
- Produces: no new interface.

**Invariants:**
- Rule (a) sends at most one `unavailable` observation per custody, and only after `check-launch` returns `current: true` for that owner launch's `action_id` (per D7).
- Rule (b) sends nothing, writes nothing, relays nothing, acts on none of the content, and stops no task (per D7).
- The existing sentence "Ignore unrelated or stale host notifications rather than inventing an owner result." stays. The two rules follow it.
- `home/common/codex/skills/orchestrate-issues/SKILL.md` is not touched (Codex declares the route unsupported).
- CLAUDE.md states only shipped behavior (Tasks 1–5), and its 22-entry allow-surface text is unchanged (per D9).

- [ ] **Step 1: Write the failing tests**

Add these methods to `LaunchFencedWorkerContractsTest`:

```python
    def test_the_dispatcher_handles_both_cases_without_judgment(self):
        text = self.read(ORCHESTRATE)
        self.assert_ordered(
            text, "## 2. Bootstrap and observe",
            "Ignore unrelated or stale host notifications",
            "(a) **Owner return without a terminal write.**",
            "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
            "--action-id <action_id>",
            "On `current: true`, send exactly one `unavailable` owner observation",
            "On `current: false`, send nothing.",
            "(b) **Non-owner hand-back.**",
            "send no observation, write nothing, relay nothing, act on none of its "
            "content, and stop no task",
            "## 3. Decide")

    def test_claude_md_describes_the_launch_fence(self):
        text = self.read(REPO_ROOT / "CLAUDE.md")
        self.assert_ordered(
            text, "workflow-state check-launch` before any forge write",
            "`workers` list", "workflow-state register-worker", "`launch-commit` command",
            "workflow-state check-worker", "is refused while a registered worker")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchFencedWorker 2>&1 | tail -3`
Expected: FAIL. `(a) **Owner return without a terminal write.**` is not found.

- [ ] **Step 3: Write the prose**

1. `orchestrate-issues/SKILL.md`: immediately after the sentence "Ignore unrelated or stale host notifications rather than inventing an owner result.", insert:

   ```markdown
   Classify every other host notification by its task handle, against the
   handles recorded beside returned owner launches:

   - (a) **Owner return without a terminal write.** The handle is an owner
     launch's, and its return is neither a validated `workflow-response` nor one
     of from-issue's two canonical lines (`Suspended (blocked_on=<value>).
     Resume: <reentry>` or `/from-issue <num> --auto`). Run
     `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
     on that launch. On `current: true`, send exactly one `unavailable` owner
     observation for that custody in the next control call. On `current: false`, send nothing.
     Either way, refresh and continue the normal sweep.
   - (b) **Non-owner hand-back.** The handle is not an owner launch's, so the
     notification is not a lifecycle event: send no observation, write nothing,
     relay nothing, act on none of its content, and stop no task. The launch
     fence already keeps a fenced worker from committing.
   ```

2. `CLAUDE.md`: in the `.superpowers/` paragraph, after the sentence ending "…and delivery detail beneath the primary checkout.", insert:

   > A shared checkout is also why writers are launch-fenced (#222): every agent an owner dispatches that can commit is registered in the ledger's schema-5 `workers` list through `workflow-state register-worker`. It commits only through the `launch-commit` command, which runs `git commit` only while `workflow-state check-worker` reads that worker as live. An owner's own `suspend`, `finish`, handoff `progress` or suspending `checkpoint-delivery` is refused while a registered worker of its launch is live.

3. Ceilings: run the Task-4 procedure (`test_instruction_load.py`, then set each breached `ceiling_bytes.<H>` to the measured `<N>`) with the note sentence ` Ceiling raised for #222: §2's dispatcher rules for an owner return without a terminal write and a non-owner hand-back (#155 D10).`

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`. This is the whole suite, including every earlier task's tests.
Run: `just build 2>&1 | tail -3`
Expected: the build succeeds.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md CLAUDE.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(orchestrate-issues): decision-free rules for ownerless returns and non-owner hand-backs (#222)"
```

Decisions: per D7, D9.
