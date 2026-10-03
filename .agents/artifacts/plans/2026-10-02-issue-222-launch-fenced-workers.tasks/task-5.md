# Task 5: from-issue and ship-issue register, fence and release before exit

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (`## Dispatch, phase-budget and attempt-budget rules`, `## Suspension procedure`, `## Terminal return procedure`)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (the Phases 2–4 prompt requirements list and the bookkeeper paragraph)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (the ship-owner prompt)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (`## Remainder owner prompt`)
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## Launch guard`, `## Phase 1 — Sync from the integration branch`, `## Delivery loop` and `## Remainder mode`)
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md` (`## Post-selection sync`, steps 1 and 3)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (methods added to `LaunchFencedWorkerContractsTest`)

**Interfaces:**
- Consumes (Tasks 1–4): the `register-worker`, `release-worker` and `launch-commit` CLIs, `checkpoint-delivery --worker-id`, the `Lifecycle worker:` prompt line, and the class constants `WORKER_LINE`, `REGISTER`, `RELEASE` and `COMMIT` of `LaunchFencedWorkerContractsTest`.
- Produces: owner-exit prose matching Task 2's refusal (`live workers: <ids>`).

**Invariants:**
- Registered: the Phase 2–4 subagents that commit artifacts, the Phase-7 ship owner, and the ship owner's own writing children (`--parent <its worker_id>`). Never registered: the fresh delegated owner (it adopts this owner's launch) and the ledger-only bookkeeper (per D6).
- `worker_id` reaches a worker only as the `Lifecycle worker:` prompt line, never inside `ship-handoff/v2` (per D13).
- Before `suspend`, a handoff `progress`, or the bookkeeper's `finish`, the owner releases every worker it registered. A background worker it cannot wait for is first stopped through the host's task-stop and released with `--event stopped`. A host with no stop capability waits for the worker. An owner that can neither wait nor stop returns without a terminal write.
- The ship owner adds `--worker-id <worker_id>` to every `checkpoint-delivery` it writes while it holds one (per D11).
- The remainder ship owner (launched from `ship-handoff.md`'s `## Remainder owner prompt`) is a registered writing worker too: it can commit a post-selection sync. Because it writes its own `finish`, it releases every child it registered and then itself (`release-worker --worker-id <worker_id> --event returned`) after its last commit and immediately before that `finish`; a `delivery_stalled` or denial checkpoint it writes carries `--worker-id <worker_id>` instead. The launching owner's later `--event returned` release of the same id is the documented no-op repeat (per D11, D12, D13).
- Every instruction that creates a merge or amend commit from the integration branch is fenced: Phase 1's `git merge origin/<integration>` sentence is rewritten to the fenced form, and CI-MERGE.md's post-selection sync merge (step 1) and its review amends (step 3) run through `launch-commit` (`-- --amend --no-edit` for an amend). An already-up-to-date merge creates no commit and needs no `launch-commit`.
- The stale sentence "Phase 1's merge from the integration branch and Phase 3's local commits are not forge writes and are not guarded." is replaced. No other ship-issue guard text changes.

- [ ] **Step 1: Write the failing tests**

Add these methods to `LaunchFencedWorkerContractsTest`:

```python
    def test_from_issue_registers_writers_and_releases_before_every_exit(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "## Dispatch, phase-budget and attempt-budget rules",
            "**Writing workers.**", self.REGISTER, self.WORKER_LINE,
            "the fresh delegated owner", "the ledger-only bookkeeper",
            "--event stopped", "return without a terminal write",
            "## Terminal return procedure", "release every worker",
            "## Suspension procedure", "release every worker", "live workers:")

    def test_auto_subagents_commit_through_launch_commit_and_the_bookkeeper_is_unregistered(self):
        text = self.read(FROM_ISSUE_DIR / "AUTO.md")
        self.assert_ordered(text, "Both prompts must carry", "`Lifecycle worker:` line",
                            "launch-commit")
        self.assert_ordered(text, "ledger-only bookkeeper route",
                            "releases every worker it registered",
                            "The bookkeeper is never registered")

    def test_the_ship_prompt_carries_the_worker_line_outside_the_handoff(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Ship-owner subagent prompt",
            self.WORKER_LINE, "never inside the handoff")

    def test_ship_issue_fences_local_commits_and_registers_its_children(self):
        text = self.read(SHIP_ISSUE)
        self.assert_ordered(
            text, "## Launch guard", "### Local commits", self.COMMIT,
            "git merge --no-commit --no-ff origin/<integration>", "--parent <worker_id>",
            "## Phase 1 — Sync from the integration branch")
        self.assertNotIn("Phase 3's local commits are not forge writes", text)
        self.assertNotIn("Otherwise `git merge origin/<integration>`; commit the merge", text)
        self.assert_ordered(text, "## Phase 1 — Sync from the integration branch",
                            "git merge --no-commit --no-ff origin/<integration>",
                            "Already up to date")
        self.assert_ordered(text, "## Remainder mode", self.RELEASE, "finish")
        self.assert_ordered(self.read(SHIP_ISSUE.parent / "CI-MERGE.md"),
                            "## Post-selection sync", "launch-commit", "--amend --no-edit")

    def test_the_remainder_prompt_releases_itself_before_its_finish(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Remainder owner prompt",
            self.WORKER_LINE, self.RELEASE,
            "workflow-state finish --summary-file -")
        self.assert_ordered(text, "## Delivery loop", "--worker-id <worker_id>")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchFencedWorker 2>&1 | tail -3`
Expected: FAIL. `**Writing workers.**` is not found.

- [ ] **Step 3: Write the prose**

1. `from-issue/SKILL.md`, `## Dispatch, phase-budget and attempt-budget rules`: append this paragraph after **Leaf-agent clauses**:

   ```markdown
   **Writing workers.** With lifecycle identity, every agent this owner
   dispatches that may commit or write to the forge — a Phase 2–4 subagent that
   commits artifacts, sdd's writing agents (Phase 6) and the Phase-7 ship owner —
   is registered first:
   `workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`.
   Its prompt carries the printed id as the single line
   `Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`,
   and it creates every commit through `launch-commit`. Release it with
   `--event returned` when it returns. Two dispatches are never registered:
   the fresh delegated owner, which adopts this owner's own launch, and the
   ledger-only bookkeeper, whose only job is the terminal write. A background
   worker this owner cannot wait for is first stopped through the host's
   task-stop and then released with `--event stopped`. On a host with no stop
   capability, wait for it to return. An owner that can neither wait nor stop
   must return without a terminal write and leave recovery to the dispatcher.
   ```

2. `## Terminal return procedure`: before its first `workflow-state finish` instruction, add `Before the terminal write, release every worker this owner registered (see **Writing workers**).` `## Suspension procedure`: immediately before the `workflow-state suspend` code block, add `Before suspending, release every worker this owner registered (see **Writing workers**): the helper refuses a suspend, a handoff \`progress\` or a \`finish\` that ends this launch while a registered worker is live, exiting 2 with \`live workers: <ids>\` and writing nothing.`

3. `AUTO.md`, the "Both prompts must carry" list: add a bullet after the worktree bullet: ``- with lifecycle identity, the `Lifecycle worker:` line from `SKILL.md`'s **Writing workers** rule, and the instruction to create every commit through `launch-commit` with its three values,``. In the bookkeeper paragraph, before "Give the bookkeeper an exact two-command sequence", insert: `Before dispatching it, the owner releases every worker it registered. The bookkeeper is never registered: a registered bookkeeper would block its own finish.`

4. `ship-handoff.md`, `## Ship-owner subagent prompt`: after the handoff-validation paragraph and before `Your task:`, add this to the prompt template: `With lifecycle identity, the prompt also carries the single line Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> from from-issue's **Writing workers** rule — beside the handoff, never inside the handoff.` (Keep the `Lifecycle worker:` text as written, with no backticks inside the line.)

5. `ship-issue/SKILL.md`, `## Launch guard`: replace the sentence "Phase 1's merge from the integration branch and Phase 3's local commits are not forge writes and are not guarded." with `Local commits are fenced separately (### Local commits).` Then insert this subsection right before the `Without lifecycle identity — a standalone` paragraph:

   ```markdown
   ### Local commits

   When the prompt carries a `Lifecycle worker:` line, this run is a
   registered worker, and it creates every local commit as
   `launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`.
   That includes Phase 1's sync, run as
   `git merge --no-commit --no-ff origin/<integration>` followed by
   `launch-commit`, and Phase 3's commits. Exit 3 is a refusal like
   `check-launch`'s: stop with the same no-write rule. An agent this run
   dispatches that can write is registered with
   `--parent <worker_id>` added to `workflow-state register-worker` (this
   handoff's `action_id` as `--action-id`), gets its own `Lifecycle worker:`
   line, and is released when it returns. Without the line, commit with plain
   `git`.
   ```

5a. `ship-issue/SKILL.md`, `## Phase 1 — Sync from the integration branch`: replace the sentence ``Otherwise `git merge origin/<integration>`; commit the merge with the configured merge-commit message. Don't squash.`` with ``Otherwise run `git merge --no-commit --no-ff origin/<integration>`; when it reports `Already up to date` there is nothing to commit, otherwise commit the merge with the configured merge-commit message through `launch-commit` when this run holds a `Lifecycle worker:` line (### Local commits), or plain `git commit` without one. Don't squash.``

5b. `ship-issue/CI-MERGE.md`, `## Post-selection sync`: in step 1 add ``With a `Lifecycle worker:` line, make that merge as `git merge --no-commit --no-ff origin/<integration>` and commit it through `launch-commit` (SKILL.md's ### Local commits).`` In step 3, after "amending the unpushed merge commit", add ``(through `launch-commit … -- --amend --no-edit` when this run holds a `Lifecycle worker:` line)``.

5c. `ship-issue/SKILL.md`, `## Remainder mode`: add ``A remainder owner whose prompt carries a `Lifecycle worker:` line releases every worker it registered and then itself with `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --worker-id <worker_id> --event returned` after its last commit and immediately before its own `finish`; after that release it creates no commit.``

5d. `ship-handoff.md`, `## Remainder owner prompt`: before `Your task:` in the template add ``With lifecycle identity, the prompt also carries the single line Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> beside the remainder object, never inside it.`` and, in the task paragraph before "your own `workflow-state finish --summary-file -`", add ``release your children and then yourself with `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --worker-id <worker_id> --event returned`, then write``. The from-issue owner registers this remainder owner like the Phase-7 ship owner.

6. `ship-issue/SKILL.md`, `## Delivery loop`: right after the `checkpoint-delivery` code block, add: `When this run holds a \`Lifecycle worker:\` line, append \`--worker-id <worker_id>\` to every \`checkpoint-delivery\`: it excuses this run alone when its own checkpoint suspends the launch.`

7. Ceilings: run the Task-4 procedure (`test_instruction_load.py`, then set each breached `ceiling_bytes.<H>` to the measured `<N>`) with the note sentence ` Ceiling raised for #222: from-issue and ship-issue register writing workers, fence local commits and release before exit (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(from-issue,ship-issue): register writers, fence local commits, release before exit (#222)"
```

Decisions: per D4, D6, D11, D13, D15.
