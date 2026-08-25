# Task 3: Expired handoffs resume in place with a validated document

Rests on spec rows D5, D1, D2.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes, from Task 1: the reaper demotes an expired `handed_off` attempt to
  `suspended(unknown)` before the predicates are derived, so `handed_off` is
  already `False` by the time the resume lane runs.
- Produces: the resume lane's handoff-document validation is keyed on the
  attempt's **data**, not its state —
  `if latest["handoff_path"] is not None: validate_handoff_path(run_dir, latest["handoff_path"])`.
  No signature changes; `validate_handoff_path(run_dir, path_value)` keeps its
  existing contract.

**Invariants:**
- A resumed handoff keeps the same attempt number, the same worktree and the
  same `handoff_path`; the document file still exists afterwards.
- The dispatch action and the direct-owner envelope publish `handoff_path` only
  after that path has been validated on this very call — including the second
  and later resumes of one handoff, where the attempt's state is `suspended`.
- Validation failure aborts the whole sweep with a non-zero exit and leaves the
  ledger byte-identical (the mutation is discarded with the transaction).

---

- [ ] **Step 1: Write the failing test**

Add at the end of `WorkflowStateLifecycleTest`, after the tests Task 2 added:

```python
    def test_expired_handoff_resumes_the_same_attempt_and_revalidates_its_document(self):
        # Before this change an expired handoff entered the retry lane and got
        # an attempt 2 whose `handoff_path` was null — the document was silently
        # abandoned (per D5).
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000,
                      handoff_path=handoff_path)
        observed = [self.worktree_fact(14, recorded={
            "path": os.path.abspath(worktree), "state": "matching_issue_branch"})]

        response = self.control(
            now="2026-08-13T20:31:00Z", issues=[14], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)], worktrees=observed,
        )
        self.assertEqual([delta["kind"] for delta in response["deltas"]],
                         ["expired", "resumed"])
        action = self.dispatch_action(response, "resume")
        self.assertEqual(
            (action["id"], action["attempt"], action["worktree"],
             action["handoff_path"], action["deadline_at"]),
            ("14:1:2", 1, os.path.abspath(worktree), str(handoff_path),
             "2026-08-13T21:01:00Z"),
        )
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            (attempts[0]["state"], attempts[0]["handoff_path"]),
            ("active", str(handoff_path)),
        )
        self.assertTrue(handoff_path.is_file())

        # The second resume of one handoff is where the state-keyed guard used
        # to hand out an unvalidated path: the attempt is `suspended`, not
        # `handed_off`, yet the response is about to publish `handoff_path`.
        handoff_path.unlink()
        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now="2026-08-13T21:01:00Z", issues=[14], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)], worktrees=observed,
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn("Traceback", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
```

- [ ] **Step 2: Run the test and watch it fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -20
```
Expected: one failure, on the second half — the sweep whose handoff document has
been deleted exits 0 and hands the dead path out, because the resume lane only
validates while the attempt's state is still `handed_off`. The first half
already passes at this commit: Task 1's reaper routes the expired handoff into
the suspension lane.

- [ ] **Step 3: Key the validation on the attempt's data**

In `_apply_one_issue_policy`'s resume lane, replace

```python
        if handed_off:
            validate_handoff_path(run_dir, latest["handoff_path"])
```

with

```python
        if latest["handoff_path"] is not None:
            # Verify the document exactly when the response is about to publish
            # it. `handoff_path` survives `resume_attempt` and is never cleared,
            # so a state-keyed guard checks only the first resume (per D5).
            validate_handoff_path(run_dir, latest["handoff_path"])
```

Nothing else changes: `validate_handoff_path` already rejects a missing,
non-regular or escaping path, `control`'s dispatch action and
`direct_owner_response` already carry `handoff_path`, and the orchestrator prose
already says to pass it through on a `resume`.

- [ ] **Step 4: Verify**

```sh
set -o pipefail
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -5
```
Expected: `OK`, zero failures and zero errors — including
`test_control_suspends_unresumed_handoff_without_losing_it` and
`test_handoff_symlink_escape_is_rejected_without_state_change`, both untouched.

Then pin the guard:

```sh
S=home/common/agent-skills/scripts/workflow-state.py
if ! grep -q 'if latest\["handoff_path"\] is not None:' "$S"; then
  echo "the handoff guard is still keyed on the attempt state"; exit 1
fi
if grep -q '^        if handed_off:$' "$S"; then
  echo "the state-keyed handoff guard survived"; exit 1
fi
```
Expected: no output, exit 0. Both checks fail at the commit this task starts from.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
        home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(issue-133): resume an expired handoff in place, validating its document"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
