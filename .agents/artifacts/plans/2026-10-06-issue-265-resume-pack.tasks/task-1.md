# Task 1: `resume-pack` verb — launch gate, ledger, worktree and commits

Lane: full (lifecycle helper, new public interface). Decisions: per D1, D3,
D4, D6, D7, D11, D12 and D13 of the spec's ledger. Read the spec's "The verb",
"The pack" and "Next action" sections first; this task does not restate their
rationale. In this task `sdd` is always `null`; Task 2 fills it.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (already in `workflow-state.py`, unedited): `launch_verdict(runtime,
  state, action_id) -> (current_action_id, reason)`, `read_state_unlocked`,
  `parse_action_id`, `resolve_repo_root`, `require_regular_path`,
  `RUN_ID_PATTERN`, `live_worktree_branch(path) -> str`,
  `probe_progress_head(worktree, marker) -> (head, marker_is_ancestor)`,
  `_worktree_git(path, *args)`, `_git_failed(completed)`,
  `WorktreeBranchUnavailable`, `print_json`, `_delivery()`.
- Consumes (test harness, unedited): `LifecycleHarness` with `run_cli`,
  `init_run`, `spawn`, `resume`, `retry`, `suspend`, `progress`,
  `write_handoff`, `fail_owner`, `mark_progress`, `git`, `init_worktree`,
  `commit`, `read_state`, `state_path`.
- Produces (Task 2 extends these; keep the names exact):
  - Constants `RESUME_PACK_COMMITS = 20`, `RESUME_PACK_SUBJECT_CHARS = 100`.
  - `resume_pack_attempt(runtime: Any, state: dict[str, Any] | None, action_id: str) -> tuple[dict[str, Any], bool]`
    — the latest attempt and `current`; raises `WorkflowError` with the D12
    clause.
  - `probe_resume_worktree(worktree: str, marker: str | None) -> tuple[dict[str, Any], dict[str, Any]]`
    — `(worktree_section, commits_since_marker_section)`; raises
    `WorktreeBranchUnavailable`.
  - `resume_next_action(*, phase: int, phase_action: str | None, handoff_path: str | None, relation: str) -> dict[str, Any]`.
  - `command_resume_pack(args: argparse.Namespace) -> int` and the
    `resume-pack` subparser (`--repo-root`, `--run-id`, `--action-id`, all
    required).
  - Test mixin `ResumePackHarness(LifecycleHarness)` (no `TestCase` base, so
    its helpers never run as tests twice) with `setUp`, the overridable
    `make_worktree()` hook (sets `self.worktree` and `self.base`), `tick()`,
    `attempt()`, `pack_raw(action_id, *, run_id=None)`, `pack(action_id)`,
    `assert_refused(action_id, clause, *, run_id=None)` and
    `expected_ledger()`; and the test class
    `ResumePackTest(ResumePackHarness, unittest.TestCase)`. Task 2 adds a
    sibling `TestCase` on the same mixin.

**Invariants:**
- The pack is exactly the spec's shape with the nested object keyed `ledger`
  (per D11): top-level keys `kind`, `version`, `run_id`, `issue`, `attempt`,
  `action_id`, `current`, `ledger`, `worktree`, `commits_since_marker`, `sdd`,
  `next_action`; `ledger` keys `state`, `phase`, `launch_kind`, `launches`
  (the count), `deadline_at`, `blocked_on`, `handoff_path`,
  `progress_marker`; `worktree` keys `path`, `branch`, `head`, `dirty_paths`;
  `commits_since_marker` keys `base`, `relation`, `count`, `commits`,
  `truncated`.
- The pack's ledger values are copied as stored. `blocked_on`,
  `progress_marker` and `phase_action` are read with `.get(...)` because the
  unlocked reader returns a pre-schema-6 document as stored.
- Gate (per D3, D12): `launch_verdict` `current` serves `current: true`; an
  `inactive_attempt` verdict whose latest attempt is `suspended` or
  `handed_off` serves `current: false` only when the id's launch ordinal equals
  `len(attempt["launches"])`, and otherwise refuses as `superseded_launch`;
  every other verdict refuses as `launch <id> is <reason>`. A remainder id
  (`:r` in the id) refuses before the ledger is read.
- Commits are listed only for `ahead`: newest first, at most 20, each
  `{"sha": <first 12 hex>, "subject": <first 100 characters>}`; `count` is the
  full `rev-list --count` of `<marker>..<head>`; `truncated` is
  `count > len(commits)`. For `none`, `same` and `diverged`, `count` is 0 and
  `commits` is `[]`; `base` is the stored marker (null for `none`).
- `dirty_paths` is the number of non-empty lines of
  `git --no-optional-locks status --porcelain`.
- Next action, first match wins: `read_handoff` `{path}` when `handoff_path`
  is non-null and `phase_action == "handoff"`; `reorient`
  `{reason: "diverged_marker"}` when the relation is `diverged`; `reorient`
  `{reason: "delivery_phases_complete"}` when `phase >= 7`; otherwise
  `start_phase` `{phase: phase + 1}` (per D6, D13).
- Read-only: the ledger file's bytes, the set of paths under the test root and
  the worktree's `.git/index` bytes are unchanged by any call, success or
  refusal; no `transact`, `workflow_paths` or lock call is reachable from
  `command_resume_pack`.

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_workflow_state.py`, directly
after `ProgressMarkerTest` (before `OwnerExitFenceTest`):

```python
class ResumePackHarness(LifecycleHarness):
    """Issue 16's attempt on a real git worktree, and the `resume-pack` runners."""

    def setUp(self):
        super().setUp()
        self.seconds = 0
        self.init_run()
        self.make_worktree()
        self.spawn(issue=16, worktree=str(self.worktree), budget_minutes=10)

    def make_worktree(self):
        """Set `self.worktree` and its first commit `self.base`; Task 2 overrides it."""
        self.worktree = self.root / "wt-16"
        self.base = self.init_worktree(self.worktree, branch="issue-16")

    def tick(self):
        self.seconds += 1
        return f"2026-08-13T20:{self.seconds // 60:02d}:{self.seconds % 60:02d}Z"

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def pack_raw(self, action_id, *, run_id=None):
        return self.run_cli(
            "resume-pack", "--repo-root", self.root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--action-id", action_id, ok=False)

    def pack(self, action_id):
        completed = self.pack_raw(action_id)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return json.loads(completed.stdout)

    def assert_refused(self, action_id, clause, *, run_id=None):
        before = self.state_path.read_bytes()
        refused = self.pack_raw(action_id, run_id=run_id)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertIn("workflow-state: resume-pack refused: " + clause, refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def expected_ledger(self):
        attempt = self.attempt()
        return {"state": attempt["state"], "phase": attempt["phase"],
                "launch_kind": attempt["launch_kind"],
                "launches": len(attempt["launches"]),
                "deadline_at": attempt["deadline_at"],
                "blocked_on": attempt["blocked_on"],
                "handoff_path": attempt["handoff_path"],
                "progress_marker": attempt["progress_marker"]}


class ResumePackTest(ResumePackHarness, unittest.TestCase):
    """#265: `resume-pack` summarises one launch for its relaunched owner."""

    def test_an_active_current_launch_packs_ledger_worktree_and_commits_ahead(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        first = self.commit(self.worktree, "first task")
        second = self.commit(self.worktree, "second task")
        self.assertEqual(self.pack("16:1:1"), {
            "kind": "resume_pack", "version": 1, "run_id": self.run_id,
            "issue": 16, "attempt": 1, "action_id": "16:1:1", "current": True,
            "ledger": self.expected_ledger(),
            "worktree": {"path": self.attempt()["worktree"], "branch": "issue-16",
                         "head": second, "dirty_paths": 0},
            "commits_since_marker": {
                "base": self.base, "relation": "ahead", "count": 2,
                "commits": [{"sha": second[:12], "subject": "second task"},
                            {"sha": first[:12], "subject": "first task"}],
                "truncated": False},
            "sdd": None,
            "next_action": {"kind": "start_phase", "phase": 1},
        })
        self.assertEqual(self.expected_ledger()["progress_marker"], self.base)

    def test_relations_none_same_and_diverged(self):
        empty = {"count": 0, "commits": [], "truncated": False}
        pack = self.pack("16:1:1")
        self.assertEqual(pack["commits_since_marker"],
                         {"base": None, "relation": "none", **empty})
        self.mark_progress(action_id="16:1:1", now=self.tick())
        self.assertEqual(self.pack("16:1:1")["commits_since_marker"],
                         {"base": self.base, "relation": "same", **empty})
        moved = self.commit(self.worktree)
        self.mark_progress(action_id="16:1:1", now=self.tick())
        self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["commits_since_marker"],
                         {"base": moved, "relation": "diverged", **empty})
        self.assertEqual(pack["next_action"],
                         {"kind": "reorient", "reason": "diverged_marker"})

    def test_dirty_paths_count_uncommitted_entries(self):
        (self.worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.worktree / "b.txt").write_text("b\n", encoding="utf-8")
        self.assertEqual(self.pack("16:1:1")["worktree"]["dirty_paths"], 2)

    def test_a_suspended_attempt_previews_its_last_launch(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        work = self.commit(self.worktree, "task one")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit", now=self.tick())
        pack = self.pack("16:1:1")
        self.assertEqual((pack["current"], pack["ledger"]),
                         (False, self.expected_ledger()))
        self.assertEqual((pack["ledger"]["state"], pack["ledger"]["blocked_on"]),
                         ("suspended", "usage_limit"))
        self.assertEqual(pack["commits_since_marker"]["commits"],
                         [{"sha": work[:12], "subject": "task one"}])
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 1})
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())
        resumed = self.pack("16:1:2")
        self.assertEqual((resumed["current"], resumed["action_id"],
                          resumed["ledger"]["launch_kind"], resumed["ledger"]["launches"]),
                         (True, "16:1:2", "resume", 2))
        self.assertEqual(resumed["commits_since_marker"], pack["commits_since_marker"])
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_launch")

    def test_a_handoff_gate_points_at_its_handoff_until_the_next_gate(self):
        handoff = self.write_handoff(16)
        self.progress(issue=16, phase=1, now=self.tick(), turn_count=118,
                      handoff_path=handoff)
        stored = self.attempt()["handoff_path"]
        preview = self.pack("16:1:1")
        self.assertEqual((preview["current"], preview["ledger"]["state"]),
                         (False, "handed_off"))
        self.assertEqual(preview["next_action"], {"kind": "read_handoff", "path": stored})
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())
        self.assertEqual(self.pack("16:1:2")["next_action"],
                         {"kind": "read_handoff", "path": stored})
        self.progress(issue=16, phase=2, now=self.tick())
        pack = self.pack("16:1:2")
        self.assertEqual(pack["ledger"]["handoff_path"], stored)
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 3})

    def test_a_completed_phase_7_reorients(self):
        self.progress(issue=16, phase=7, now=self.tick())
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "reorient", "reason": "delivery_phases_complete"})

    def test_non_current_launches_are_refused_with_empty_stdout(self):
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        self.assert_refused("16:2:1", "launch 16:2:1 is unknown_attempt")
        self.assert_refused("17:1:1", "launch 17:1:1 is unknown_issue")
        self.assert_refused("16:r1:1", "a remainder launch has no resume pack")
        self.assert_refused("16:1:1", "launch 16:1:1 is unknown_run",
                            run_id="issue-99-absent")
        malformed = self.pack_raw("16:1")
        self.assertEqual((malformed.returncode, malformed.stdout), (2, ""))
        self.assertIn("invalid action_id", malformed.stderr)
        self.fail_owner(issue=16, attempt=1, now=self.tick())
        self.assert_refused("16:1:1", "launch 16:1:1 is inactive_attempt")
        self.retry(issue=16, worktree=str(self.worktree), now=self.tick())
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_attempt")
        retried = self.pack("16:2:1")
        self.assertEqual((retried["attempt"], retried["current"]), (2, True))

    def test_an_unreadable_worktree_is_refused(self):
        self.git(self.worktree, "checkout", "--quiet", "--detach")
        self.assert_refused("16:1:1", "its HEAD is detached")
        shutil.rmtree(self.worktree)
        self.assert_refused("16:1:1", "the worktree is absent")

    def test_resume_pack_writes_nothing(self):
        tracked = self.worktree / "tracked.txt"
        tracked.write_text("one\n", encoding="utf-8")
        self.git(self.worktree, "add", "tracked.txt")
        self.commit(self.worktree, "tracked")
        tracked.write_text("two\n", encoding="utf-8")
        index = self.worktree / ".git" / "index"
        before = (self.state_path.read_bytes(), index.read_bytes(),
                  sorted(path.relative_to(self.root) for path in self.root.rglob("*")))
        self.assertEqual(self.pack("16:1:1")["worktree"]["dirty_paths"], 1)
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        after = (self.state_path.read_bytes(), index.read_bytes(),
                 sorted(path.relative_to(self.root) for path in self.root.rglob("*")))
        self.assertEqual(after, before)
        self.assertFalse((self.worktree / ".superpowers").exists())

    def test_the_commit_list_is_bounded(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        for number in range(25):
            self.commit(self.worktree, f"{number:02d} " + "x" * 150)
        completed = self.pack_raw("16:1:1")
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        section = json.loads(completed.stdout)["commits_since_marker"]
        self.assertEqual((section["count"], len(section["commits"]), section["truncated"]),
                         (25, 20, True))
        self.assertTrue(section["commits"][0]["subject"].startswith("24 "))
        self.assertEqual({len(commit["subject"]) for commit in section["commits"]}, {100})
        self.assertEqual({len(commit["sha"]) for commit in section["commits"]}, {12})
```

`shutil` and `json` are already imported at the top of the file.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ResumePackTest 2>&1 | tail -3`
Expected: non-zero exit and `FAILED` over the 10 cases — argparse rejects
`resume-pack` as an invalid choice.

- [ ] **Step 3: Implement the verb**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. Directly after `probe_progress_head`, add the constants and
   `probe_resume_worktree(worktree, marker)`:
   - `branch = live_worktree_branch(worktree)`, then
     `head, marker_is_ancestor = probe_progress_head(worktree, marker)` (an
     unknown marker therefore refuses exactly as in `mark-progress`, per D4).
   - `_worktree_git(worktree, "--no-optional-locks", "status", "--porcelain")`;
     non-zero → `raise _git_failed(...)`; `dirty_paths` counts its non-empty
     decoded lines.
   - relation: `none` when `marker is None`, `same` when `marker == head`,
     `ahead` when `marker_is_ancestor`, else `diverged`.
   - For `ahead` only: `_worktree_git(worktree, "rev-list", "--count",
     f"{marker}..{head}")` for `count`, and `_worktree_git(worktree, "log",
     f"--max-count={RESUME_PACK_COMMITS}", "--format=%H%x1f%s",
     f"{marker}..{head}")` for the list; each non-zero exit raises
     `_git_failed`. Decode with `"utf-8", "replace"`, split each line once on
     `"\x1f"`, keep `sha[:12]` and `subject[:RESUME_PACK_SUBJECT_CHARS]`.
   - Return `({"path": worktree, "branch": branch, "head": head,
     "dirty_paths": dirty}, {"base": marker, "relation": relation, "count":
     count, "commits": commits, "truncated": count > len(commits)})`.
   - Docstring: read-only, git by name with the shared 60-second timeout, no
     optional index lock (#265 D4, D7).
2. Directly after `launch_verdict`, add `resume_pack_attempt(runtime, state,
   action_id)` implementing the gate invariant above; its refusal is
   `WorkflowError(f"resume-pack refused: launch {action_id} is {reason}")`.
3. Add `resume_next_action(*, phase, phase_action, handoff_path, relation)`
   implementing the next-action invariant above, each branch a separate
   `if ... return` (Task 2 adds an `ambiguous_sdd_workspace` branch directly
   before `diverged_marker`, and `resume_task` / `finish_phase` branches
   directly before `start_phase`).
4. Add `command_resume_pack(args)` directly after `command_mark_progress`:
   validate `RUN_ID_PATTERN` (`invalid run_id`), `parse_action_id`, refuse
   `":r" in args.action_id` with `resume-pack refused: a remainder launch has
   no resume pack`, read the state exactly as `command_check_launch` does
   (missing file → `None`), call `resume_pack_attempt`, then
   `probe_resume_worktree(attempt["worktree"], attempt.get("progress_marker"))`
   mapping `WorktreeBranchUnavailable` to
   `WorkflowError(f"resume-pack refused: {unavailable}")`, assemble the pack
   (`"sdd": None`), and `print_json` it; return 0. Docstring: read-only
   exactly as `check-launch` is — no clock, no lock, neither `transact` nor
   `workflow_paths` — and the pack is advisory (#265 D2, D3).
5. In `build_parser`, directly after the `mark-progress` subparser, add the
   `resume-pack` subparser with the three required arguments and
   `set_defaults(handler=command_resume_pack)`.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ResumePackTest 2>&1 | tail -3`
Expected: `OK`, 10 tests.

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3`
Expected: `OK` (no pre-existing test regresses).

Run:
```bash
if git diff -U0 HEAD -- home/common/agent-skills/scripts/workflow-state.py | grep -E '^-' | grep -vE '^---' | grep -q .; then exit 1; fi
```
Expected: exit 0 — the change only adds lines (no existing function is edited).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): add read-only resume-pack verb (#265)"
```
