# Task 3: Scratch sentences, Self-reap and CLAUDE.md

Spec section **Adoption wiring** is normative; this task cites D1, D6 and D7 and #276 D9. It changes prose and contract tests only, never code.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the `launch-scope scratch --repo-root R --run-id I (--action-id A | --worker-id W)` verb (Task 1) and the reap behavior and `unattributed_worktrees` report member (Task 2). Existing test constants in `LaunchScopeWiringContractsTest`: `WORKER_LINE`, `WORKER_EXEC`, `OWNER_EXEC`, `REAP`, `COMMIT`, `RELEASE`, and the module's path constants `FROM_ISSUE`, `FROM_ISSUE_DIR`, `SDD`, `SDD_DIR`, `SHIP_ISSUE`, `AUTO`, `REPO_ROOT`.
- Produces: the two sentences below, byte-exact (after whitespace normalization) at every site.

`WORKER_SCRATCH`: Create every scratch directory or scratch worktree under the path that `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints.

`OWNER_SCRATCH`: Create every scratch directory or scratch worktree under the path that `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` prints.

**Invariants:**
- Each scratch sentence sits right after its `exec` sentence and before the next anchor the existing test already pins (D7).
- The **Leaf-agent clauses** paragraph of from-issue stays byte-identical and never names `launch-scope`; `test_the_leaf_clauses_do_not_name_launch_scope` stays unchanged (D7).
- Each `instruction-load.json` ceiling that this task's growth breaches is set to the measured hot bytes, and no other ceiling changes (#276 D9).

- [ ] **Step 1: Write the failing tests**

In `LaunchScopeWiringContractsTest`, add after `WORKER_EXEC` and `OWNER_EXEC`:

```python
    WORKER_SCRATCH = ("Create every scratch directory or scratch worktree under the path that "
                      "`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> "
                      "--worker-id <worker_id>` prints.")
    OWNER_SCRATCH = ("Create every scratch directory or scratch worktree under the path that "
                     "`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> "
                     "--action-id <action_id>` prints.")
```

Replace `test_the_owner_runs_long_commands_through_exec` and `test_the_worker_sentence_follows_every_composed_worker_line` with:

```python
    def test_the_owner_runs_long_commands_through_exec(self):
        self.assert_ordered(self.read(FROM_ISSUE), "## Lifecycle identity", self.OWNER_EXEC,
                            "a forge verb never goes through it", self.OWNER_SCRATCH,
                            "Every lifecycle call is one command",
                            "### Dispatcher-owned acquisition")

    def test_the_worker_sentence_follows_every_composed_worker_line(self):
        self.assert_ordered(self.read(FROM_ISSUE), "**Writing workers.**", self.WORKER_LINE,
                            self.WORKER_EXEC, self.WORKER_SCRATCH, "launch-commit",
                            "**Self-reap.**")
        self.assert_ordered(self.read(SDD), "### Lifecycle workers", self.WORKER_LINE,
                            self.WORKER_EXEC, self.WORKER_SCRATCH, self.RELEASE)
        self.assert_ordered(self.read(SDD_DIR / "implementer-prompt.md"),
                            "## Lifecycle Worker", self.COMMIT, "never run `git commit` directly",
                            self.WORKER_EXEC, self.WORKER_SCRATCH,
                            "only the most recent one governs", "## Report Format")
        handoff = self.read(FROM_ISSUE_DIR / "ship-handoff.md")
        self.assert_ordered(handoff, "## Ship-owner subagent prompt", self.WORKER_LINE,
                            "never inside the handoff", self.WORKER_EXEC, self.WORKER_SCRATCH,
                            "Your task:")
        self.assert_ordered(handoff, "## Remainder owner prompt", self.WORKER_LINE,
                            "never inside it", self.WORKER_EXEC, self.WORKER_SCRATCH,
                            "Your task:")
        self.assert_ordered(self.read(SHIP_ISSUE), "### Local commits", "--parent <worker_id>",
                            "`Lifecycle worker:`", self.WORKER_EXEC, self.WORKER_SCRATCH,
                            "## Doc-grounded escalations")
        self.assert_ordered(self.read(AUTO), "Both prompts must carry", "`Lifecycle worker:` line",
                            "the `launch-scope exec` and `scratch` sentences that follow it there",
                            "launch-commit")
```

In `test_every_owner_exit_reaps_between_release_and_write`, insert the anchor `"then removes the launch's scratch root and every worktree inside it"` right after the first `self.REAP` (before `"the reap runs before the bookkeeper is dispatched"`).

In `LaunchScopeSweepContractsTest.test_claude_md_describes_launch_scope`, append three anchors after `"agent-launch/<run-id>/<action-id>/"`: `"`launch-scope scratch` (#277)"`, `"`scratch.json`"`, `"`unattributed_worktrees`"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchScope 2>&1 | tail -5`
Expected: FAILED (failures=4) — the owner, worker, self-reap and CLAUDE.md cases fail on the missing scratch anchors; the bookkeeper, leaf-clause and stop-pass cases pass.

- [ ] **Step 3: Edit the prose**

1. **from-issue `SKILL.md`, Lifecycle identity.** After "…and the lifecycle guard refuses one that sits behind another program." append, in the same paragraph, the `OWNER_SCRATCH` sentence.
2. **from-issue `SKILL.md`, Writing workers.** Change `followed by the sentence "Run each long command, … still in the foreground.", and it` to `followed by the sentences "Run each long command, … still in the foreground." and "<WORKER_SCRATCH>", and it`.
3. **from-issue `SKILL.md`, Self-reap.** Change "The reap kills every process that a `launch-scope exec` of this launch left behind." to "The reap kills every process that a `launch-scope exec` of this launch left behind, then removes the launch's scratch root and every worktree inside it."
4. **`AUTO.md`** Phase 2–4 prompt list: change "the `launch-scope exec` sentence that follows it there" to "the `launch-scope exec` and `scratch` sentences that follow it there".
5. **`ship-handoff.md`**, both prompts: change "followed by the sentence" (the one that introduces the `Run each long command` line) to "followed by the sentences", and add the `WORKER_SCRATCH` sentence as its own line right after the `Run each long command` line.
6. **sdd `SKILL.md`**, Lifecycle workers: change `followed by the sentence "Run … still in the foreground."` to `followed by the sentences "Run … still in the foreground." and "<WORKER_SCRATCH>"`, keeping "When that agent returns" as the next sentence.
7. **sdd `implementer-prompt.md`**: after the indented "still in the foreground." line, add the `WORKER_SCRATCH` sentence at the same indentation, hard-wrapped like its neighbors.
8. **ship-issue `SKILL.md`**, Local commits: change `followed by the sentence "Run … still in the foreground.", and is released` to `followed by the sentences "Run … still in the foreground." and "<WORKER_SCRATCH>", and is released`.
9. **`CLAUDE.md`**, Agent helper package paragraph: after "…so an orphaned group holding only such processes is never proved and survives a sweep." insert one sentence that states, from the code Tasks 1 and 2 shipped: `launch-scope scratch` (#277) prints the launch's one scratch root, a `launch-scope-*` directory under the system temp directory that the owner and its workers share, recorded as `scratch.json` in the launch's registry directory; once a reap finds the launch's processes gone it force-removes every worktree registered inside that root, present or missing, and deletes the root, never running a repository-wide `git worktree prune` (D10); and every reap reports the registered worktrees outside the main checkout and outside every recorded root as `unattributed_worktrees`, deleting none of them. Correct any clause the implemented code contradicts.
10. **`instruction-load.json`**: run `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "exceed ceiling|^(OK|FAILED)"`. For each `profile <id> on <host>: hot <N> bytes exceed ceiling` line, set that profile's `ceiling_bytes[<host>]` to `<N>`, and append to that profile's `note`: " Ceiling raised for #277: owners and writing workers create scratch under launch-scope scratch, and self-reap removes the scratch root (#155 D10)." Rerun until it prints `OK`. Raise only the profiles the test names.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchScope 2>&1 | tail -3`
Expected: `OK`, 7 tests.

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -2`
Expected: `OK` (the leaf-clause verbatim-once contract and every other phrase contract still hold).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md \
  home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/sdd/SKILL.md \
  home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/ship-issue/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): create scratch under launch-scope scratch; describe the scratch root and unattributed worktrees (#277)"
```
