# Task 4: Owner exec, worker sentence and owner self-reap in the skills

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. Append the class `LaunchScopeWiringContractsTest` immediately before `if __name__ == "__main__":`.

**Interfaces:**
- Consumes: the CLI that Tasks 2 and 3 ship, `launch-scope exec --repo-root R --run-id I (--action-id A | --worker-id W) -- <argv>` and `launch-scope reap --repo-root R --run-id I --action-id A`. Its exit codes are 0 for a clean reap, 1 when it skipped a launch, and 2 for an error.
- Produces: the anchor strings below, which Task 5 does not reuse.

**Invariants:**
- The three leaf-agent clauses stay byte-identical in every carrier, and so does the remainder placeholder line (D8). `home/common/agent-skills/tests/test_dispatch_contracts.py` stays green without being edited.
- Every existing anchor in `LaunchFencedWorkerContractsTest` keeps holding, and its tests are not edited.
- The worker sentence is exactly the text of `WORKER_EXEC` below, and it comes right after each composed `Lifecycle worker:` line, or right after the rule that composes one (D8, D13).
- At each of from-issue's three exits, the order is: release every worker, then `reap --action-id`, then the exit write (parent D6).

- [ ] **Step 1: Write the failing test**

Append before `if __name__ == "__main__":`:

```python
class LaunchScopeWiringContractsTest(unittest.TestCase):
    """#276: owners and writing workers run long commands in a launch scope; owners self-reap."""

    WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id>")
    WORKER_EXEC = ("Run each long command, every verification command included, as "
                   "`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id> -- <argv>`, still in the foreground.")
    OWNER_EXEC = ("run each long command, every verification command included, as "
                  "`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> "
                  "--action-id <action_id> -- <argv>`, still in the foreground")
    REAP = ("launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> "
            "--action-id <action_id>")
    COMMIT = ("launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
              "--worker-id <worker_id> -- ")
    RELEASE = ("workflow-state release-worker --repo-root <ledger_repo_root> "
               "--run-id <run-id> --now <utc> --worker-id <worker_id> --event returned")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_the_owner_runs_long_commands_through_exec(self):
        self.assert_ordered(self.read(FROM_ISSUE), "## Lifecycle identity", self.OWNER_EXEC,
                            "a forge verb never goes through it",
                            "### Dispatcher-owned acquisition")

    def test_the_worker_sentence_follows_every_composed_worker_line(self):
        self.assert_ordered(self.read(FROM_ISSUE), "**Writing workers.**", self.WORKER_LINE,
                            self.WORKER_EXEC, "launch-commit", "**Self-reap.**")
        self.assert_ordered(self.read(SDD), "### Lifecycle workers", self.WORKER_LINE,
                            self.WORKER_EXEC, self.RELEASE)
        self.assert_ordered(self.read(SDD_DIR / "implementer-prompt.md"),
                            "## Lifecycle Worker", self.COMMIT, "never run `git commit` directly",
                            self.WORKER_EXEC, "only the most recent one governs",
                            "## Report Format")
        handoff = self.read(FROM_ISSUE_DIR / "ship-handoff.md")
        self.assert_ordered(handoff, "## Ship-owner subagent prompt", self.WORKER_LINE,
                            "never inside the handoff", self.WORKER_EXEC, "Your task:")
        self.assert_ordered(handoff, "## Remainder owner prompt", self.WORKER_LINE,
                            "never inside it", self.WORKER_EXEC, "Your task:")
        self.assert_ordered(self.read(SHIP_ISSUE), "### Local commits", "--parent <worker_id>",
                            "`Lifecycle worker:`", self.WORKER_EXEC,
                            "## Doc-grounded escalations")
        self.assert_ordered(self.read(AUTO), "Both prompts must carry", "`Lifecycle worker:` line",
                            "the `launch-scope exec` sentence that follows it there",
                            "launch-commit")

    def test_every_owner_exit_reaps_between_release_and_write(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "**Self-reap.**", self.REAP,
            "the reap runs before the bookkeeper is dispatched",
            "does not block the exit write",
            "A delegating owner does not reap",
            "**`handoff`** — first release every worker", self.REAP, "--handoff-path",
            "## Terminal return procedure", "release every worker", self.REAP,
            "workflow-state finish --repo-root",
            "## Suspension procedure", "release every worker", "live workers:", self.REAP,
            "workflow-state suspend --repo-root")

    def test_the_bookkeeper_route_reaps_before_dispatch(self):
        self.assert_ordered(self.read(AUTO), "ledger-only bookkeeper route",
                            "releases every worker it registered", self.REAP,
                            "The bookkeeper is never registered")

    def test_the_leaf_clauses_do_not_name_launch_scope(self):
        text = self.read(FROM_ISSUE)
        start = text.index("**Leaf-agent clauses.**")
        self.assertNotIn("launch-scope", text[start:text.index("**Writing workers.**", start)])
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchScopeWiring 2>&1 | tail -5`
Expected: FAIL. Four tests fail on a missing `launch-scope` anchor, and `test_the_leaf_clauses_do_not_name_launch_scope` passes.

- [ ] **Step 3: Write the minimal implementation**

Make each edit below as stated. Keep the surrounding hard-wrapped style, at about 80 columns.

1. **from-issue/SKILL.md, `## Lifecycle identity`.** Right after the paragraph that ends "pass it through verbatim and never recompute it.", add this paragraph: "With lifecycle identity, run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> -- <argv>`, still in the foreground; a forge verb never goes through it, and the lifecycle guard refuses one that sits behind another program."
2. **from-issue/SKILL.md, `**Writing workers.**`.** Replace "and it creates every commit through `launch-commit`." with: ", followed by the sentence "Run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`, still in the foreground.", and it creates every commit through `launch-commit`."
3. **from-issue/SKILL.md.** Add a new paragraph right after the `**Writing workers.**` paragraph and before `**Interim child results.**`: "**Self-reap.** With lifecycle identity, each exit that ends this owner's launch — the `handoff` action, the terminal return procedure and the suspension procedure — first releases every worker this owner registered, then runs `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` with this owner's own `action_id`, and only then makes the exit write. The reap kills every process that a `launch-scope exec` of this launch left behind. When the ledger-only bookkeeper makes the exit write, the reap runs before the bookkeeper is dispatched. A reap that exits non-zero does not block the exit write: name its exit code and its `skipped` launches in this owner's result. A delegating owner does not reap, because the fresh delegated owner adopts its launch and reaps it at its own exit."
4. **from-issue/SKILL.md, the `handoff` action.** Replace "first release every worker this owner registered (see **Writing workers**)." with "first release every worker this owner registered (see **Writing workers**), then run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` (see **Self-reap**)."
5. **from-issue/SKILL.md, `## Terminal return procedure`.** Replace "Before the terminal write, release every worker this owner registered (see **Writing workers**)." with "Before the terminal write, release every worker this owner registered (see **Writing workers**), then run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` (see **Self-reap**)."
6. **from-issue/SKILL.md, `## Suspension procedure`.** Replace "with `live workers: <ids>` and writing nothing. Then call:" with "with `live workers: <ids>` and writing nothing. Then run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` (see **Self-reap**), and then call:"
7. **from-issue/AUTO.md, the prompt list.** Replace "the `Lifecycle worker:` line from `SKILL.md`'s **Writing workers** rule, and the instruction to create every commit through `launch-commit` with its three values," with "the `Lifecycle worker:` line from `SKILL.md`'s **Writing workers** rule, the `launch-scope exec` sentence that follows it there, and the instruction to create every commit through `launch-commit` with its three values," (D13).
8. **from-issue/AUTO.md, the bookkeeper route.** Replace "Before dispatching it, the owner releases every worker it registered." with "Before dispatching it, the owner releases every worker it registered, then runs `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` with its own `action_id`."
9. **from-issue/ship-handoff.md, ship-owner prompt.** Replace the line "from from-issue's **Writing workers** rule — beside the handoff, never inside the handoff." with two lines: "from from-issue's **Writing workers** rule — beside the handoff, never inside the handoff — followed by the sentence" and "Run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`, still in the foreground."
10. **from-issue/ship-handoff.md, `## Remainder owner prompt`.** Replace "beside the remainder object, never inside it." with "beside the remainder object, never inside it, followed by the sentence", and then the same `Run each long command, …` line as in edit 9.
11. **sdd/SKILL.md, `### Lifecycle workers`.** Replace "`Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`." with "`Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`, followed by the sentence "Run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`, still in the foreground.""
12. **sdd/implementer-prompt.md, `## Lifecycle Worker`.** Right after "and never run `git commit` directly.", insert the sentence "Run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`, still in the foreground." It keeps the block's four-space indent and sits before "If you have been given more than one".
13. **ship-issue/SKILL.md, `### Local commits`.** Replace "gets its own `Lifecycle worker:`\nline, and is released when it returns." with "gets its own `Lifecycle worker:` line followed by the sentence "Run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`, still in the foreground.", and is released when it returns."
14. **instruction-load.json (D9).** Run `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "exceed ceiling|^(OK|FAILED)"`. For each `profile <id> on <host>: hot <N> bytes exceed ceiling` line, set that profile's `ceiling_bytes[<host>]` to `<N>`. Then append to that profile's `note`: " Ceiling raised for #276: owners and writing workers run long commands through launch-scope exec, and owners self-reap before every exit write (#155 D10)." Rerun until the command prints `OK`. The likely profiles are `from-issue-controller`, `orchestrated-issue-owner`, `implementation-owner` and `ship-owner`. Raise only the profiles that the test names.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3`
Expected: `OK`. The new class's five tests pass, `LaunchFencedWorkerContractsTest` and the leaf-clause contracts are unchanged and green, and no ceiling is breached.
Run: `if git diff -U0 HEAD -- home/common/agent-skills/skills | grep -E '^-.*Launch any subagent by type only'; then exit 1; fi`
Expected: exit 0, because no line of a leaf clause was removed.

- [ ] **Step 5: Commit**

Use `launch-commit` when your prompt carries a `Lifecycle worker:` line.

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): run long commands through launch-scope exec and self-reap before every exit write (#276)"
```
