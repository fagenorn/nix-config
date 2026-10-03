# Task 2: `workflow-state mark-progress` — marker rule, worktree probe and command

Lane: full (lifecycle code). Decisions: per D1, D2, D3, D5, D6, D7, D8, D10,
D12 and D13 of the spec's ledger. Read the spec's "New verb" section first; it
owns the outcome table and this task does not restate its rationale.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Test: `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes (from Task 1): `SCHEMA_VERSION == 6`; attempt field
  `progress_marker` (`None` or a full lowercase commit ID), required by
  `validate_attempt`; `LifecycleHarness._as_legacy` strips it below schema 6.
- Consumes (already in `workflow-state.py`): `launch_verdict(runtime, state,
  action_id) -> (current_action_id, reason)`, `read_state_unlocked`,
  `transact`, `parse_action_id`, `resolve_repo_root`, `require_regular_path`,
  `live_worktree_branch(path) -> str`, `_worktree_git(path, *args)`,
  `_git_failed(completed)`, `WorktreeBranchUnavailable`, `print_json`.
- Produces:
  - `record_progress_marker(attempt: dict[str, Any], *, head: str, marker_is_ancestor: bool) -> str`
    — placed directly after `suspend_attempt`. Returns one of `"baseline"`,
    `"unchanged"`, `"advanced"`, `"diverged"` and mutates `attempt` only for
    `baseline` and `advanced`.
  - `probe_progress_head(worktree: str, marker: str | None) -> tuple[str, bool]`
    — placed directly after `live_worktree_branch`. Returns
    `(head, marker_is_ancestor)`; raises `WorktreeBranchUnavailable`.
  - `command_mark_progress(args: argparse.Namespace) -> int` and the
    `mark-progress` subparser.
  - Test helpers on `LifecycleHarness`: `mark_progress(*, action_id, now,
    ok=True)`, `git(worktree, *args)`, `init_worktree(path, *, branch)`,
    `commit(worktree, message="work")`. Task 3 does not use them.

**Invariants:**
- The reset happens only on `advanced`, by setting `stalled_resumes` to `0`
  and `suspend_phase` to `None`; `baseline` writes only the marker.
- `unchanged`, `diverged` and every refusal leave a schema-6 `state.json`
  byte-identical.
- A refusal exits 2, prints nothing on stdout, and its stderr line contains
  `mark-progress refused: <reason>`.
- `mark-progress` never changes `phase`, `last_progress_at`, `phase_action`,
  `phase_inputs`, `deadline_at`, `state`, `launches` or `blocked_on`.
- No git process runs while the run lock is held (per D8).
- `suspend_attempt`, `resume_attempt` and `demote_expired_attempt` are
  byte-identical to the starting commit.

## Steps

- [ ] **Step 1: Add the harness helpers**

In `home/common/agent-skills/tests/test_workflow_state.py`, inside
`LifecycleHarness`, directly after `register_worker`:

```python
    def mark_progress(self, *, action_id, now, ok=True):
        completed = self.run_cli(
            "mark-progress", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--action-id", action_id, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    @staticmethod
    def git(worktree, *args):
        completed = subprocess.run(["git", "-C", str(worktree), *args], check=True,
                                   capture_output=True, text=True)
        return completed.stdout.strip()

    def init_worktree(self, path, *, branch):
        """A real git repository at `path` with one commit on `branch` (#250 D13).

        The fixture repository turns commit signing off for itself: it lives in a
        temporary directory and must not depend on the machine's signing key.
        """
        Path(path).mkdir(parents=True)
        self.git(path, "init", "--quiet", "--initial-branch", branch)
        for key, value in (("user.name", "Fixture"),
                           ("user.email", "fixture@example.test"),
                           ("commit.gpgsign", "false")):
            self.git(path, "config", key, value)
        return self.commit(path)

    def commit(self, worktree, message="work"):
        self.git(worktree, "commit", "--quiet", "--allow-empty", "--message", message)
        return self.git(worktree, "rev-parse", "HEAD")
```

- [ ] **Step 2: Write the failing tests**

Append to `home/common/agent-skills/tests/test_workflow_state.py`, directly
after `ProgressMarkerSchemaTest`. `contextlib` and `io` are new imports at the
top of the file.

```python
class ProgressMarkerTest(LifecycleHarness, unittest.TestCase):
    """#250: `mark-progress` records durable forward movement of the attempt worktree."""

    def setUp(self):
        super().setUp()
        self.seconds = 0
        self.init_run()
        self.worktree = self.root / "wt-16"
        self.base = self.init_worktree(self.worktree, branch="issue-16")
        self.spawn(issue=16, worktree=str(self.worktree), budget_minutes=10)

    def tick(self):
        self.seconds += 1
        return f"2026-08-13T20:{self.seconds // 60:02d}:{self.seconds % 60:02d}Z"

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def launch(self):
        return f"16:1:{len(self.attempt()['launches'])}"

    def mark(self):
        return self.mark_progress(action_id=self.launch(), now=self.tick())

    def park(self):
        return self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                            now=self.tick())

    def wake(self):
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())

    def advance(self):
        head = self.commit(self.worktree)
        self.assertEqual(self.mark(), {"action_id": self.launch(),
                                       "outcome": "advanced", "marker": head})
        return head

    def assert_refused(self, action_id, clause, *, now=None):
        before = self.state_path.read_bytes()
        refused = self.mark_progress(action_id=action_id, now=now or self.tick(),
                                     ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, self.state_path.read_bytes()),
            (2, "", before))
        self.assertIn("mark-progress refused: " + clause, refused.stderr)

    def assert_no_write(self, outcome, marker):
        before = self.state_path.read_bytes()
        self.assertEqual(self.mark(), {"action_id": self.launch(),
                                       "outcome": outcome, "marker": marker})
        self.assertEqual(self.state_path.read_bytes(), before)

    def assert_stalled(self, final):
        issue = self.read_state()["issues"]["16"]
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["result_source"]),
                         ("stopped", "stalled"))
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(issue["outcome"], attempt["result"])
        self.assertEqual(final, {
            "interface_version": 2, "kind": "terminal", "issue": 16,
            "run_id": self.run_id, "source": "lifecycle", "reason": "stopped",
            "blockers": [], "result": attempt["result"],
            "reentry": "/from-issue 16 --auto",
        })

    def stall_through(self, between):
        """Four suspensions, with `between()` run while each launch is active."""
        for _ in range(3):
            between()
            self.assertEqual(self.park()["kind"], "suspended")
            self.wake()
        between()
        self.assert_stalled(self.park())

    def test_outcomes_follow_the_ancestry_of_the_checked_out_commit(self):
        self.assertEqual(self.mark(), {"action_id": "16:1:1", "outcome": "baseline",
                                       "marker": self.base})
        self.assert_no_write("unchanged", self.base)
        second = self.advance()
        self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
        self.assert_no_write("diverged", second)
        self.commit(self.worktree, "sibling")
        self.assert_no_write("diverged", second)
        self.git(self.worktree, "reset", "--quiet", "--hard", second)
        self.assert_no_write("unchanged", second)

    def test_a_baseline_keeps_the_stall_count_and_an_advance_clears_it(self):
        for _ in range(2):
            self.park()
            self.wake()
        self.assertEqual(self.mark()["outcome"], "baseline")
        before = self.attempt()
        self.assertEqual((before["stalled_resumes"], before["suspend_phase"]), (1, 0))
        head = self.commit(self.worktree)
        now = self.tick()
        self.assertEqual(
            self.mark_progress(action_id="16:1:3", now=now),
            {"action_id": "16:1:3", "outcome": "advanced", "marker": head})
        state = self.read_state()
        after = state["issues"]["16"]["attempts"][-1]
        self.assertEqual(state["updated_at"], now)
        self.assertEqual(
            (after["progress_marker"], after["stalled_resumes"], after["suspend_phase"]),
            (head, 0, None))
        written = {"progress_marker", "stalled_resumes", "suspend_phase"}
        self.assertEqual({name: value for name, value in after.items()
                          if name not in written},
                         {name: value for name, value in before.items()
                          if name not in written})

    def test_new_commits_between_suspensions_never_stall(self):
        self.progress(issue=16, phase=6, now=self.tick())
        self.assertEqual(self.mark()["outcome"], "baseline")
        for _ in range(5):
            self.advance()
            self.assertEqual(self.park()["kind"], "suspended")
            attempt = self.attempt()
            self.assertEqual((attempt["suspend_phase"], attempt["stalled_resumes"]),
                             (6, 0))
            self.wake()
        self.assertEqual(self.attempt()["state"], "active")

    def test_a_baseline_alone_still_stalls_at_the_fourth_suspension(self):
        self.stall_through(self.mark)

    def test_a_replayed_marker_still_stalls_at_the_fourth_suspension(self):
        self.mark()
        head = self.advance()
        self.stall_through(lambda: self.assert_no_write("unchanged", head))

    def test_rewinding_and_re_advancing_still_stalls_at_the_fourth_suspension(self):
        self.mark()
        head = self.advance()

        def rewind_and_return():
            self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
            self.assert_no_write("diverged", head)
            self.git(self.worktree, "reset", "--quiet", "--hard", head)
            self.assert_no_write("unchanged", head)

        self.stall_through(rewind_and_return)

    def test_a_recording_refused_while_suspended_still_stalls(self):
        self.mark()
        for _ in range(3):
            self.assertEqual(self.park()["kind"], "suspended")
            self.commit(self.worktree)
            launch = self.launch()
            self.assert_refused(launch, f"launch {launch} is inactive_attempt")
            self.wake()
        self.assert_stalled(self.park())
        self.assert_refused("16:1:4", "launch 16:1:4 is inactive_attempt")
        self.assertEqual(self.attempt()["progress_marker"], self.base)

    def test_the_marker_survives_a_suspend_and_resume(self):
        self.mark()
        head = self.advance()
        self.park()
        self.assertEqual(self.attempt()["progress_marker"], head)
        # check-launch validates the stored ledger strictly on every read.
        self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                         "inactive_attempt")
        self.wake()
        self.assertEqual(self.attempt()["progress_marker"], head)
        self.assert_no_write("unchanged", head)

    def test_expiry_demotions_after_new_commits_never_stall(self):
        observed = [self.worktree_fact(16, recorded={
            "path": str(self.worktree), "state": "matching_issue_branch"})]
        self.mark_progress(action_id="16:1:1", now="2026-08-13T20:01:00Z")
        for index, (marked_at, expired_at) in enumerate((
            ("2026-08-13T20:05:00Z", "2026-08-13T20:10:00Z"),
            ("2026-08-13T20:35:00Z", "2026-08-13T20:40:00Z"),
            ("2026-08-13T21:05:00Z", "2026-08-13T21:10:00Z"),
            ("2026-08-13T21:35:00Z", "2026-08-13T21:40:00Z"),
            ("2026-08-13T22:05:00Z", "2026-08-13T22:10:00Z"),
        )):
            self.commit(self.worktree)
            marked = self.mark_progress(action_id=f"16:1:{index + 1}", now=marked_at)
            self.assertEqual(marked["outcome"], "advanced")
            swept = self.control(
                now=expired_at, issues=[16], max_parallel=2,
                attempt_budget_minutes=30, tracker=[self.tracker_fact(16)],
                worktrees=observed)
            self.assertEqual(self.dispatch_action(swept, "resume")["id"],
                             f"16:1:{index + 2}")
            self.assertEqual(self.attempt()["stalled_resumes"], 0)

    def test_identity_and_clock_refusals_write_nothing(self):
        self.mark()
        for action_id, clause in (
            ("16:1:9", "launch 16:1:9 is superseded_launch"),
            ("16:2:1", "launch 16:2:1 is unknown_attempt"),
            ("99:1:1", "launch 99:1:1 is unknown_issue"),
            ("16:r1:1", "a remainder launch keeps its own bound"),
        ):
            with self.subTest(action_id=action_id):
                self.assert_refused(action_id, clause)
        self.assert_refused("16:1:1", "time must not move backward",
                            now="2026-08-13T19:59:00Z")
        before = self.state_path.read_bytes()
        malformed = self.mark_progress(action_id="16:1", now=self.tick(), ok=False)
        self.assertEqual((malformed.returncode, self.state_path.read_bytes()),
                         (2, before))
        absent = self.run_cli(
            "mark-progress", "--repo-root", self.root, "--run-id", "issue-99-absent",
            "--now", self.tick(), "--action-id", "16:1:1", ok=False)
        self.assertEqual(absent.returncode, 2)
        self.assertIn("mark-progress refused: launch 16:1:1 is unknown_run",
                      absent.stderr)
        self.park()
        self.wake()
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_launch")

    def test_worktree_probe_refusals_write_nothing(self):
        self.mark()
        self.git(self.worktree, "checkout", "--quiet", "--detach")
        self.assert_refused("16:1:1", "its HEAD is detached")
        self.git(self.worktree, "checkout", "--quiet", "issue-16")
        state = self.read_state()
        state["issues"]["16"]["attempts"][0]["progress_marker"] = "0" * 40
        self.write_state(state)
        self.commit(self.worktree)
        self.assert_refused("16:1:1", "git failed")  # a marker git does not know
        shutil.rmtree(self.worktree)
        self.assert_refused("16:1:1", "the worktree is absent")
        self.worktree.mkdir()
        self.assert_refused("16:1:1", "git failed")  # not a git repository
        self.git(self.worktree, "init", "--quiet", "--initial-branch", "issue-16")
        self.assert_refused("16:1:1", "git failed")  # an unborn branch: no commit

    def test_a_schema_five_ledger_records_a_baseline_and_upgrades(self):
        self.write_state(self._as_legacy(self.read_state(), 5))
        self.assertEqual(self.mark(), {"action_id": "16:1:1", "outcome": "baseline",
                                       "marker": self.base})
        state = self.read_state()
        self.assertEqual(
            (state["schema_version"],
             state["issues"]["16"]["attempts"][0]["progress_marker"]),
            (6, self.base))

    def test_a_marker_recorded_during_the_probe_refuses_the_stale_write(self):
        # The only in-process case (#250 D13): a second recording lands between
        # this call's probe and its transaction, so the transaction must refuse.
        workflow = load_source_module(SCRIPT, "workflow_state_progress_race")
        probe = workflow.probe_progress_head

        def racing_probe(worktree, marker):
            observed = probe(worktree, marker)
            self.mark()
            return observed

        stderr = io.StringIO()
        with mock.patch.object(workflow, "probe_progress_head", racing_probe), \
                contextlib.redirect_stderr(stderr):
            code = workflow.main([
                "mark-progress", "--repo-root", str(self.root), "--run-id",
                self.run_id, "--now", "2026-08-13T20:09:00Z", "--action-id", "16:1:1"])
        self.assertEqual(code, 2)
        self.assertIn("mark-progress refused: the attempt changed during the probe",
                      stderr.getvalue())
        self.assertEqual(self.attempt()["progress_marker"], self.base)
```

Append to `LaunchRefusalTest` in
`home/common/agent-skills/tests/test_host_admission.py`, directly after
`test_the_anti_zombie_bound_ends_a_launch_that_keeps_being_refused` (which is
the unchanged no-marker counterpart and must stay green):

```python
    def test_an_advanced_marker_spares_a_launch_that_is_refused_again(self):
        """#250: the host-capacity path honours the reset `mark-progress` wrote."""
        self.admitted_pair()
        worktree = self.root / "wt-14"
        self.init_worktree(worktree, branch="issue-14")
        self.assertEqual(
            self.mark_progress(action_id="14:1:1",
                               now="2026-08-13T20:00:30Z")["outcome"], "baseline")
        self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14), owners=[self.refused(14)])
        state = self.read_state()
        state["issues"]["14"]["attempts"][0]["stalled_resumes"] = 2  # two resumes spent
        self.write_state(state)
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:02:00Z")
        self.sweep("2026-08-13T20:03:00Z", recorded=(14,), unobserved=(12,))  # 14:1:2
        head = self.commit(worktree)
        self.assertEqual(
            self.mark_progress(action_id="14:1:2", now="2026-08-13T20:03:30Z"),
            {"action_id": "14:1:2", "outcome": "advanced", "marker": head})
        final = self.sweep("2026-08-13T20:04:00Z", recorded=(14,), unobserved=(12,),
                           owners=[self.refused(14, launch=2)])
        self.assertEqual(
            (self.summary(final, 14)["state"], self.summary(final, 14)["blocked_on"]),
            ("suspended", "host_capacity"))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["stalled_resumes"], attempt["progress_marker"]),
                         (0, head))
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ProgressMarkerTest 2>&1 | tail -8`

Expected: every test fails or errors; the CLI ones report
`invalid choice: 'mark-progress'` (argparse exits 2 before any handler runs).

- [ ] **Step 4: Implement the rule, the probe and the command**

All in `home/common/agent-skills/scripts/workflow-state.py`.

**4a. The rule** — directly after `suspend_attempt`. This is the one place
the outcome is decided (agent-helpers rule 2), and its body is the spec's
outcome table:

```python
def record_progress_marker(
    attempt: dict[str, Any], *, head: str, marker_is_ancestor: bool
) -> str:
    stored = attempt["progress_marker"]
    if stored is None:
        attempt["progress_marker"] = head
        return "baseline"
    if stored == head:
        return "unchanged"
    if not marker_is_ancestor:
        return "diverged"
    attempt["progress_marker"] = head
    attempt["suspend_phase"] = None
    attempt["stalled_resumes"] = 0
    return "advanced"
```

Give it a docstring written from this body: what each outcome means, that
only `advanced` starts a fresh stall count and does so through the same two
fields a phase advance leaves `suspend_attempt` to compare (#250 D5), and
that a `baseline` proves no movement and so resets nothing (#250 D6). Do not
edit `suspend_attempt`.

**4b. The probe** — directly after `live_worktree_branch`:

`probe_progress_head(worktree: str, marker: str | None) -> tuple[str, bool]`

1. Call `live_worktree_branch(worktree)` and discard the branch name. It
   already refuses an absent path, a non-directory, a path that is not the top
   level of a git worktree, and a detached `HEAD`.
2. `head = _worktree_git(worktree, "rev-parse", "--verify", "HEAD^{commit}")`.
   On a non-zero return code raise `_git_failed(head)`. Decode stdout, strip
   the trailing newline, and raise
   `WorktreeBranchUnavailable("git failed: HEAD is not a full commit id")`
   unless it matches `PROGRESS_MARKER_PATTERN.fullmatch`.
3. If `marker is None` or `marker == head`, return `(head, False)` — no
   ancestry question exists.
4. Otherwise `_worktree_git(worktree, "merge-base", "--is-ancestor", marker, head)`:
   return code `0` → `(head, True)`; `1` → `(head, False)`; anything else
   (git answers 128 for an object it does not know) → raise `_git_failed(...)`.

Its docstring states that it is read-only, runs git by name with the shared
timeout and takes no lock (#250 D8).

**4c. The command** — `command_mark_progress`, placed after
`command_register_worker`, in this order:

1. `RUN_ID_PATTERN.fullmatch(args.run_id)` else `WorkflowError("invalid run_id")`;
   `issue, _, _ = parse_action_id(args.action_id)`; parse `--now` exactly as
   `command_register_worker` does (`now_value`, `now`).
2. If `":r" in args.action_id`, raise
   `WorkflowError("mark-progress refused: a remainder launch keeps its own bound")`.
3. Resolve the ledger path as `command_check_launch` does
   (`resolve_repo_root`, then `.superpowers/workflows/<run-id>/state.json`) and
   read it with `read_state_unlocked` when `require_regular_path(...,
   allow_missing=True)` says it exists, else `state = None`.
4. `_, reason = launch_verdict(runtime, state, args.action_id)`; unless
   `reason == "current"`, raise
   `WorkflowError(f"mark-progress refused: launch {args.action_id} is {reason}")`.
5. Take the latest attempt of that issue. Remember `worktree =
   attempt["worktree"]` and `stored = attempt.get("progress_marker")`. The
   `.get` is deliberate and needs a one-line comment: the unlocked reader
   returns a pre-schema-6 document as stored, where the key is absent and the
   migration will make it `None` (#250 D12).
6. `head, marker_is_ancestor = probe_progress_head(worktree, stored)`; convert
   a `WorktreeBranchUnavailable` into
   `WorkflowError(f"mark-progress refused: {unavailable}")` with `from`.
7. Call `transact(args.repo_root, args.run_id, record)` where `record(state)`:
   - re-runs `launch_verdict` and refuses with the step-4 message if not
     `current`;
   - takes the latest attempt again and raises
     `WorkflowError("mark-progress refused: the attempt changed during the probe")`
     unless `attempt["worktree"] == worktree and attempt["progress_marker"] == stored`;
   - raises `WorkflowError("mark-progress refused: time must not move backward")`
     when `now_value < parse_utc(state["updated_at"], "run update time")`;
   - `outcome = record_progress_marker(attempt, head=head, marker_is_ancestor=marker_is_ancestor)`;
     `changed = outcome in {"baseline", "advanced"}`; when changed, set
     `state["updated_at"] = now`;
   - returns `({"action_id": args.action_id, "outcome": outcome, "marker": attempt["progress_marker"]}, changed)`.
8. `print_json(...)` the transaction's result and return `0`. `transact`
   commits before it returns, so the reply is printed only after the write.

Do not wrap the mutation in `fence_owner_exit`: the verb ends no launch. The
docstring says so, cites #250 D1/D7/D8, and notes one consequence of
`transact`: on a pre-schema-6 ledger even a no-write outcome persists the
migration (#250 D12).

**4d. The parser** — after the `register_worker` subparser:

```python
    mark_progress = subparsers.add_parser("mark-progress")
    add_run_arguments(mark_progress)
    mark_progress.add_argument("--action-id", required=True)
    mark_progress.set_defaults(handler=command_mark_progress)
```

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ProgressMarker 2>&1 | tail -4`
Expected: `Ran 17 tests`, `OK` (13 here plus Task 1's 4).

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_host_admission.py -k LaunchRefusalTest 2>&1 | tail -4`
Expected: `OK`, including both anti-zombie cases.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k stalled -k expiry 2>&1 | tail -4`
Expected: `OK` — the pre-existing no-marker stall tests are unchanged and green.

Run (the suspension arithmetic is untouched; `<base>` is this task's starting commit):
```bash
git diff <base> -- home/common/agent-skills/scripts/workflow-state.py \
  | grep -E '^[-+]' | grep -E 'STALL_LIMIT|stalled without phase progress' ; test $? -eq 1
```
Expected: no output, exit 0.

Run: `just agent-workflow-tests 2>&1 | tail -6`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_host_admission.py
git commit -m "feat(workflow-state): mark-progress resets the stall count on durable forward movement (#250)"
```

The message ends with the co-author trailer from the plan's Global Constraints.
