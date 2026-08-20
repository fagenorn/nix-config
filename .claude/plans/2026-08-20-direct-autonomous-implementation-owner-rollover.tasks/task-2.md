# Task 2: Resume and Materialize an Exact Absent Phase-0 Reservation

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `.claude/specs/2026-08-20-direct-autonomous-issue-durability-design.md`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: `_apply_one_issue_policy`'s validated `run_dir`, latest attempt, exact recorded worktree observation, handoff validation, and the direct-owner command's reserved run identity.
- Produces: the unchanged `direct-owner` `kind: owner` envelope with `launch_kind: resume` for an exact `absent` recorded reservation only at Phase 0; the existing Phase-1 `git worktree add -b issue-<num>-<slug> <exact-path> origin/main` adapter behavior.

**Invariants:**
- Per D5, the exception requires all of: reserved direct run, unexpired `handed_off`, completed phase `0`, valid durable handoff, exact recorded path, and observation state `absent`.
- Successful reacquisition preserves run, attempt, owner, worktree, started time, deadline, and handoff path; it appends exactly one resume launch and consumes no retry/new run.
- `workflow-state` performs no Git or filesystem materialization; Phase 1 creates only the exact envelope path from `origin/main`.
- Active-owner takeover, dispatcher-owned resume, handoff after Phase 0, mismatch, wrong-branch occupancy, missing recorded observation, wrong recorded path, and alternate candidate remain non-resumable and mutation-free.
- Existing `matching_issue_branch` resume remains unchanged.

- [ ] **Step 1: Write the failing exact-absent and negative CLI tests**

Add these complete methods to `WorkflowStateLifecycleTest`:

```python
def test_direct_phase_zero_handoff_resumes_its_exact_absent_reservation(self):
    owner = self.acquire_direct(issue=73)
    self.run_id = owner["run_id"]
    handoff = self.write_handoff(73)
    self.progress(
        issue=73, phase=0, now="2026-08-20T10:01:00Z",
        turn_count=118, context_tokens=20000,
        next_needs_context=True, artifacts_sufficient=False,
        handoff_path=handoff,
    )
    before = json.loads(self.direct_state_path(owner["run_id"]).read_text())
    resumed = self.direct_owner(
        issue=73, now="2026-08-20T10:02:00Z",
        worktree=self.worktree_fact(73, recorded={
            "path": owner["worktree"], "state": "absent",
        }),
    )
    self.assertEqual(resumed, {
        **owner, "action_id": "73:1:2", "launch_kind": "resume",
        "handoff_path": str(handoff),
    })
    after = json.loads(self.direct_state_path(owner["run_id"]).read_text())
    attempt = after["issues"]["73"]["attempts"][0]
    old_attempt = before["issues"]["73"]["attempts"][0]
    for field in ("issue", "attempt", "owner", "worktree", "started_at",
                  "deadline_at", "handoff_path"):
        self.assertEqual(attempt[field], old_attempt[field])
    self.assertEqual(attempt["state"], "active")
    self.assertEqual(attempt["launch_kind"], "resume")
    self.assertEqual(len(attempt["launches"]), 2)
    self.assertEqual(len(after["issues"]["73"]["attempts"]), 1)
    self.assertFalse(self.direct_state_path("direct-73-000002").exists())

def test_absent_resume_exception_rejects_every_adjacent_case_without_mutation(self):
    owner = self.acquire_direct(issue=74)
    self.run_id = owner["run_id"]
    handoff = self.write_handoff(74)
    self.progress(
        issue=74, phase=1, now="2026-08-20T10:01:00Z",
        turn_count=118, handoff_path=handoff,
    )
    path = self.direct_state_path(owner["run_id"])
    before = path.read_bytes()
    observed = self.direct_owner(
        issue=74, now="2026-08-20T10:02:00Z",
        worktree=self.worktree_fact(74, recorded={
            "path": owner["worktree"], "state": "absent",
        }),
    )
    self.assertEqual(observed["kind"], "observe")
    self.assertEqual(path.read_bytes(), before)

    active = self.acquire_direct(issue=75)
    active_path = self.direct_state_path(active["run_id"])
    before = active_path.read_bytes()
    observed = self.direct_owner(
        issue=75, now="2026-08-20T10:02:00Z", owner_unavailable=True,
        worktree=self.worktree_fact(75, recorded={
            "path": active["worktree"], "state": "absent",
        }),
    )
    self.assertEqual(observed["kind"], "observe")
    self.assertEqual(active_path.read_bytes(), before)

    owner = self.acquire_direct(issue=76)
    self.run_id = owner["run_id"]
    handoff = self.write_handoff(76)
    self.progress(
        issue=76, phase=0, now="2026-08-20T10:01:00Z",
        turn_count=118, handoff_path=handoff,
    )
    path = self.direct_state_path(owner["run_id"])
    before = path.read_bytes()
    replacement = os.path.abspath(self.root / "alternate-76")
    for recorded in (None, {
        "path": owner["worktree"], "state": "mismatch",
    }):
        with self.subTest(recorded=recorded):
            observed = self.direct_owner(
                issue=76, now="2026-08-20T10:02:00Z",
                worktree=self.worktree_fact(
                    76, recorded=recorded,
                    candidate={"path": replacement, "state": "absent"},
                ),
            )
            self.assertEqual(observed["kind"], "observe")
            self.assertEqual(observed["requirements"], [{
                "kind": "recorded_worktree", "path": owner["worktree"],
            }])
            self.assertEqual(path.read_bytes(), before)
    wrong = self.direct_owner_raw(
        issue=76, now="2026-08-20T10:02:00Z",
        worktree=self.worktree_fact(76, recorded={
            "path": os.path.abspath(self.root / "wrong-76"),
            "state": "absent",
        }), ok=False,
    )
    self.assertIn("recorded worktree path does not match ledger", wrong.stderr)
    self.assertEqual(path.read_bytes(), before)

    self.run_id = "dispatcher-phase-zero"
    self.init_run(now="2026-08-20T10:00:00Z")
    dispatched = self.spawn(
        issue=77, worktree=self.root / "dispatcher-77",
        now="2026-08-20T10:00:00Z",
    )
    handoff = self.write_handoff(77)
    self.progress(
        issue=77, phase=0, now="2026-08-20T10:01:00Z",
        turn_count=118, handoff_path=handoff,
    )
    before = self.state_path.read_bytes()
    rejected = self.control_raw(
        now="2026-08-20T10:02:00Z", issues=[77],
        tracker=[self.tracker_fact(77)],
        worktrees=[self.worktree_fact(77, recorded={
            "path": dispatched["worktree"], "state": "absent",
        })], max_parallel=1, ok=False,
    )
    self.assertIn("matching recorded worktree", rejected.stderr)
    self.assertEqual(self.state_path.read_bytes(), before)
```

- [ ] **Step 2: Run the CLI cases and watch exact-absent reacquisition fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_state.py WorkflowStateLifecycleTest.test_direct_phase_zero_handoff_resumes_its_exact_absent_reservation WorkflowStateLifecycleTest.test_absent_resume_exception_rejects_every_adjacent_case_without_mutation -v`

Expected: FAIL because the base direct-owner policy returns `kind: observe` for the exact absent Phase-0 reservation; negative cases remain mutation-free.

- [ ] **Step 3: Admit only the direct Phase-0 exact-absent resume fact**

In `_apply_one_issue_policy`, keep exact recorded-path validation first. In the active/handed-off resume branch, accept `recorded["state"] == "absent"` as resume-ready only when the latest attempt is `handed_off`, its `phase == 0`, and `run_dir.name` matches `DIRECT_RUN_ID_PATTERN`. All other cases continue to require `matching_issue_branch` and produce their existing observe/error behavior. Do not select a candidate path in the resume branch.

Use the existing resume mutation unchanged: validate the handoff, restore `active`, set latest `launch_kind` to `resume`, append one resume launch with the same owner/worktree, and preserve every other attempt field. Append an issue-74 amendment marker after issue 73's matching-worktree acquisition rule, naming this exact pre-worktree exception and retaining every other requirement.

- [ ] **Step 4: Add the real Git materialization test**

Add this complete method to `WorkflowStateLifecycleTest`:

```python
def test_absent_direct_handoff_materializes_exact_worktree_then_records_phase_one(self):
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        origin = root / "origin.git"
        repo = root / "repo"
        worktree = root / "worktree-issue-73"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"],
                       check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email",
                        "fixture@example.test"], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"],
                       check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "fixture"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"],
                       check=True, capture_output=True, text=True)

        original_root, original_run_id = self.root, self.run_id
        self.root = repo
        self.addCleanup(setattr, self, "root", original_root)
        self.addCleanup(setattr, self, "run_id", original_run_id)
        owner = self.acquire_direct(issue=73, worktree=worktree)
        self.run_id = owner["run_id"]
        handoff = self.write_handoff(73)
        self.progress(
            issue=73, phase=0, now="2026-08-20T10:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        self.assertFalse(worktree.exists())
        resumed = self.direct_owner(
            issue=73, now="2026-08-20T10:02:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": str(worktree), "state": "absent",
            }),
        )
        self.assertEqual(resumed["worktree"], str(worktree))
        self.assertEqual(resumed["launch_kind"], "resume")
        self.assertFalse(worktree.exists())

        subprocess.run([
            "git", "-C", str(repo), "worktree", "add", "-b", "issue-73-fixture",
            str(worktree), "origin/main",
        ], check=True, capture_output=True, text=True)
        branch = subprocess.run([
            "git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD",
        ], check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "issue-73-fixture")
        progressed = self.progress(
            issue=73, phase=1, now="2026-08-20T10:03:00Z",
            turn_count=10, context_tokens=20000,
        )
        self.assertEqual(progressed["phase"], 1)
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        attempts = state["issues"]["73"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(attempts[0]["launches"]), 2)
        self.assertEqual(attempts[0]["worktree"], str(worktree))
        runs = sorted(path.name for path in self.workflows_dir.glob("direct-73-*"))
        self.assertEqual(runs, [owner["run_id"]])
```

- [ ] **Step 5: Verify the scoped reacquisition and filesystem contract**

Run: `python3 home/common/agent-skills/tests/test_workflow_state.py WorkflowStateLifecycleTest.test_direct_phase_zero_handoff_resumes_its_exact_absent_reservation WorkflowStateLifecycleTest.test_absent_resume_exception_rejects_every_adjacent_case_without_mutation WorkflowStateLifecycleTest.test_absent_direct_handoff_materializes_exact_worktree_then_records_phase_one WorkflowStateLifecycleTest.test_direct_owner_automatically_resumes_handoff_with_fixed_identity WorkflowStateLifecycleTest.test_control_requires_matching_recorded_state_for_resume_atomically -v`

Expected: PASS; the real-filesystem test creates the exact reserved path only after a persisted resume, and the existing matching/direct and dispatcher tests remain green.

Run: `git diff --check -- home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py .claude/specs/2026-08-20-direct-autonomous-issue-durability-design.md`

Expected: exit 0 with no output; any whitespace error or edit outside these owned files leaves the task incomplete.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py .claude/specs/2026-08-20-direct-autonomous-issue-durability-design.md
git commit -m "feat(issue-74): resume absent direct phase-zero reservations" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
