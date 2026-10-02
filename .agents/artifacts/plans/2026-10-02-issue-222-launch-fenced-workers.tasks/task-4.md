# Task 4: sdd registers writing workers and fences their commits

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/fix-loop.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (`## Phase 6 — Execute` only)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Tasks 1–3): `workflow-state register-worker --repo-root R --run-id I --now T --action-id A [--parent W]`, which prints `{"worker_id", "launch", "parent"}`; `workflow-state release-worker --repo-root R --run-id I --now T --worker-id W --event returned|stopped`; and `launch-commit --repo-root R --run-id I --worker-id W -- <git commit args>`, which exits 3 with `{"worker_id", "committed": false, "reason"}` on a refusal.
- Produces, for Task 5: the worker prompt line, exactly `Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` (per D13), and the refusal report `BLOCKED` with `launch fence refused: <reason>`.

**Invariants:**
- Without a lifecycle identity, sdd's behavior and prose for ledger-free runs are unchanged.
- Only agents that can write are registered: the implementer, the mechanic, and each fix-round implementer. Reviewers, re-reviewers and the Codex rescue transport are not (per D6).
- Each dispatch or resume registers a fresh worker, and each return releases it with `--event returned` (per D13).
- A `launch fence refused` report stops the task loop, with no retry and no re-dispatch.
- Every new sentence describes behavior that Tasks 1–3 implement. Nothing here names a flag or reply those tasks do not ship.

- [ ] **Step 1: Write the failing test**

Append this class to `test_workflow_skill_contracts.py`, before `class CodebaseDesignSkillContractsTest`. Tasks 5 and 6 add methods to it:

```python
class LaunchFencedWorkerContractsTest(unittest.TestCase):
    """#222: writing dispatches register, commit through launch-commit, release."""

    WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id>")
    REGISTER = ("workflow-state register-worker --repo-root <ledger_repo_root> "
                "--run-id <run-id> --now <utc> --action-id <action_id>")
    RELEASE = ("workflow-state release-worker --repo-root <ledger_repo_root> "
               "--run-id <run-id> --now <utc> --worker-id <worker_id> --event returned")
    COMMIT = ("launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
              "--worker-id <worker_id> -- ")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_sdd_registers_writing_workers_and_stops_on_a_fence_refusal(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.REGISTER, self.WORKER_LINE,
            self.RELEASE, "Read-only reviewers are not registered.",
            "launch fence refused: <reason>", "no retry and no re-dispatch",
            "### 1. Dispatch the implementer")

    def test_the_implementer_commits_only_through_launch_commit(self):
        self.assert_ordered(
            self.read(SDD_DIR / "implementer-prompt.md"), "## Lifecycle Worker",
            "Lifecycle worker:", self.COMMIT, "never run `git commit` directly",
            "launch fence refused: <reason>", "## Report Format")

    def test_each_fix_round_registers_afresh(self):
        self.assert_ordered(
            self.read(SDD_DIR / "fix-loop.md"), "Lifecycle workers",
            "fresh `worker_id`", "release")

    def test_from_issue_phase_6_hands_sdd_its_lifecycle_identity(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute",
            "`ledger_repo_root`, `run_id` and `action_id`", "### Lifecycle workers",
            "register-worker", "## Phase 7 — Ship")
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaunchFencedWorker 2>&1 | tail -3`
Expected: FAIL. `### Lifecycle workers` is not found in sdd's SKILL.md.

- [ ] **Step 3: Write the prose**

1. In `sdd/SKILL.md`, insert a new subsection immediately before `### 1. Dispatch the implementer`:

   ```markdown
   ### Lifecycle workers

   When the caller runs this skill under a lifecycle identity — its
   `ledger_repo_root`, `run_id` and `action_id` — every agent this skill
   dispatches or resumes that can write (the implementer, the mechanic and each
   fix-round implementer) is a registered worker of that launch. Immediately
   before the dispatch or resume, run
   `workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`
   and put its printed `worker_id` into the prompt as the single line
   `Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`.
   When that agent returns, run
   `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --worker-id <worker_id> --event returned`.
   A resumed agent is registered again and gets a fresh `worker_id`.
   Read-only reviewers are not registered.

   A report of `BLOCKED` with `launch fence refused: <reason>` means this
   launch was superseded: release that worker, make no retry and no re-dispatch,
   and follow from-issue's superseded route — write nothing more, print
   `/from-issue <num> --auto` on its own line, and stop. Without a lifecycle
   identity none of this applies and workers commit with plain `git`.
   ```

2. In `sdd/implementer-prompt.md` (inside the indented template), insert this section before `    ## Report Format`, indented to match:

   ```markdown
   ## Lifecycle Worker

   Only when this prompt carries a `Lifecycle worker:` line: create every
   commit as
   `launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`
   with the three values from that line, and never run `git commit` directly.
   If it exits 3, it printed one JSON line whose `reason` names why your
   launch is no longer live: make no further change, commit or push, and
   report status BLOCKED with `launch fence refused: <reason>`.
   ```

3. In `sdd/fix-loop.md`, append this paragraph after the `Every round:` paragraph:

   ```markdown
   **Lifecycle workers.** Under a lifecycle identity, every fix round's
   implementer — resumed or fresh — is registered as SKILL.md's
   `### Lifecycle workers` says before the round and gets a fresh `worker_id`
   in its prompt. Run the release when it returns. A `launch fence refused`
   report ends the loop.
   ```

4. In `from-issue/SKILL.md` `## Phase 6 — Execute`, after the first paragraph ("Invoke `sdd`: …"), add:

   ```markdown
   With lifecycle identity, invoke `sdd` with this owner's
   `ledger_repo_root`, `run_id` and `action_id` as its lifecycle identity, so
   sdd's `### Lifecycle workers` registers each writing agent under this
   launch. The mechanical route's mechanic is registered the same way:
   run `workflow-state register-worker` before dispatching it, put the
   `Lifecycle worker:` line in its prompt, and release it when it returns.
   ```

5. Ceilings: run `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "exceed ceiling|^OK|FAILED"`. For each `profile <P> on <H>: hot <N> bytes exceed ceiling <C>` line, set that profile's `ceiling_bytes.<H>` to `<N>` and append ` Ceiling raised for #222: sdd and from-issue Phase 6 register writing workers and fence their commits (#155 D10).` to its `note`, once per profile.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/fix-loop.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(sdd): register writing workers and commit through launch-commit (#222)"
```

Decisions: per D5, D6, D13.
