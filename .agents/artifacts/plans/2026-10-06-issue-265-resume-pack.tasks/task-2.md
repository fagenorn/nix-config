# Task 2: SDD position and the task-level next actions

Lane: full (lifecycle helper, public pack shape). Decisions: per D5, D6, D7,
D12 and D13 of the spec's ledger. Read the spec's "SDD position" and "Next
action" sections first.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (Task 1, on this branch): `command_resume_pack`,
  `resume_next_action(*, phase, phase_action, handoff_path, relation)`,
  `probe_resume_worktree`, and in the tests `ResumePackHarness` (its `setUp`,
  the `make_worktree()` hook, `tick`, `attempt`, `pack_raw`, `pack`,
  `assert_refused`) and `ResumePackTest`.
- Consumes (already in `workflow-state.py`): `_worktree_git`, `_non_symlink(path,
  kind)`, `stat`, `WorktreeBranchUnavailable`, `WorkflowError`.
- Produces:
  - Patterns `SDD_LEDGER_HEADER = re.compile(r"# SDD ledger — plan: (.+)")`
    (U+2014 em dash, exactly as sdd's SKILL.md writes it),
    `SDD_TASK_LINE = re.compile(r"Task ([1-9][0-9]*): ")`,
    `SDD_TASK_MEMBER = re.compile(r"task-([1-9][0-9]*)\.md")`; constants
    `RESUME_PACK_ENTRY_CHARS = 400`, `RESUME_PACK_COMPLETED = 32`,
    `RESUME_PACK_AMBIGUOUS = 8`.
  - `sdd_workspace_bucket(worktree: str) -> Path` — the
    `<primary>/.superpowers/sdd/<bucket>` directory path (not created).
  - `read_sdd_position(bucket: Path, worktree: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]`
    — `(sdd_section, resume_point)`, where `resume_point` is `None` or
    `{"task": int | None, "mid_fix_loop": bool}` and `task` is `None` only
    when every task in `1..task_count` is complete.
  - `resume_next_action` gains keyword arguments `sdd` and `resume_point`.
  - Test helper `ResumePackHarness.sdd_ledger(plan, entries, *, tasks=None) -> str`
    and the test class `ResumePackSddTest(ResumePackHarness, unittest.TestCase)`.

**Invariants:**
- The bucket is derived exactly as `sdd-workspace` derives it (per D5): from
  one `git rev-parse --path-format=absolute --git-dir --git-common-dir
  --show-toplevel` in the worktree; equal git dir and common dir → primary is
  the toplevel, bucket `primary`; otherwise the git dir must be
  `<common>/worktrees/<name>` with `<name>` one component other than `.`/`..`,
  the common dir's basename must be `.git`, the primary is its parent, and
  `git -C <primary> rev-parse --path-format=absolute --show-toplevel` must
  print the primary, a non-symlink directory; bucket `wt-<name>`. Any other
  outcome, a git failure included, refuses with `resume-pack refused: the SDD
  workspace cannot be resolved` (per D12).
- `read_sdd_position` creates nothing. A missing `.superpowers`, `sdd` or
  bucket component means `(None, None)`; an existing component that is a
  symlink or not a directory refuses with the same D12 clause.
- A candidate ledger is a non-symlink directory directly under the bucket
  holding a non-symlink regular `progress.md` whose first line fully matches
  `SDD_LEDGER_HEADER`; candidates are taken in sorted name order. Zero → `(None,
  None)`; two or more → `({"ambiguous": [<first 8 sorted names, each cut to
  100 characters>]}, None)`.
- One ledger: `plan` is the header's path verbatim; the members directory is
  `<plan dir>/<plan name without a trailing .md>.tasks`, with the plan path
  taken as is when absolute and joined to the worktree otherwise;
  `task_count` counts non-symlink regular files in it fully matching
  `SDD_TASK_MEMBER`, or is `None` when that directory is not a non-symlink
  directory; `completed` is the sorted distinct `N` of lines starting
  `Task <N>: complete`, cut to the 32 lowest (per D13); `last_entry` is the
  last non-empty line, right-stripped, cut to 400 characters.
- Resume point (SDD's own rule): the first `N` in `1..task_count` without a
  `complete` line, or with `task_count` `None` the smallest positive `N`
  without one; `mid_fix_loop` is true only when the last line starting
  `Task <N>: ` for that `N` starts `Task <N>: fix round`.
- Next action order, first match wins (per D6, D13): `read_handoff`;
  `reorient` `ambiguous_sdd_workspace`; `reorient` `diverged_marker`;
  `reorient` `delivery_phases_complete`; when `phase == 5` and a resume point
  exists: `finish_phase` `{phase: 6}` if its `task` is `None`, else
  `resume_task` `{phase: 6, task, mid_fix_loop}`; otherwise `start_phase`.
- The read-only invariants of Task 1 still hold: with no SDD ledger, no
  `.superpowers` directory appears in the primary.

## Steps

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_state.py`, add near the top
beside `SCRIPT`:

```python
SDD_WORKSPACE = Path(__file__).parents[1] / "skills" / "sdd" / "scripts" / "sdd-workspace"
```

Add this method to `ResumePackHarness`, after `expected_ledger`:

```python
    def sdd_ledger(self, plan, entries, *, tasks=None):
        """Write a plan and its SDD ledger where `sdd-workspace` puts it (#265 D5)."""
        plan_path = Path(plan) if Path(plan).is_absolute() else self.worktree / plan
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("# plan\n", encoding="utf-8")
        if tasks is not None:
            members = plan_path.parent / f"{plan_path.stem}.tasks"
            members.mkdir()
            for number in range(1, tasks + 1):
                (members / f"task-{number}.md").write_text("task\n", encoding="utf-8")
        workspace = subprocess.run(
            [str(SDD_WORKSPACE), plan], cwd=self.worktree, check=True,
            capture_output=True, text=True).stdout.strip()
        Path(workspace, "progress.md").write_text(
            "\n".join([f"# SDD ledger — plan: {plan}", *entries]) + "\n",
            encoding="utf-8")
        return workspace
```

Append to `ResumePackTest`:

```python
    def test_a_primary_checkout_reads_the_primary_bucket(self):
        workspace = self.sdd_ledger("plans/p.md", ["Task 1: complete (review clean)"])
        self.assertEqual(Path(workspace).parent.name, "primary")
        self.assertEqual(self.pack("16:1:1")["sdd"]["workspace"], workspace)
```

Append after `ResumePackTest`:

```python
class ResumePackSddTest(ResumePackHarness, unittest.TestCase):
    """#265: the pack reads the attempt worktree's SDD bucket by sdd-workspace's rule."""

    COMPLETE = "Task {}: complete (commits aaaaaaa..bbbbbbb, review clean)"
    FIX = "Task {}: fix round 1/5 (1 addressed, 0 open — x; commits ccccccc..ddddddd)"

    def make_worktree(self):
        self.primary = self.root / "primary"
        self.init_worktree(self.primary, branch="main")
        self.worktree = self.primary / ".worktrees" / "wt-16"
        self.git(self.primary, "worktree", "add", "--quiet", "-b", "issue-16",
                 str(self.worktree))
        self.base = self.git(self.worktree, "rev-parse", "HEAD")

    def at_phase(self, phase):
        self.progress(issue=16, phase=phase, now=self.tick())

    def test_phase_5_with_a_task_mid_fix_loop_resumes_it(self):
        self.at_phase(5)
        entries = [self.COMPLETE.format(1), self.FIX.format(2)]
        workspace = self.sdd_ledger("plans/p.md", entries, tasks=3)
        self.assertEqual(Path(workspace).parent.name, "wt-wt-16")
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"], {"workspace": workspace, "plan": "plans/p.md",
                                       "task_count": 3, "completed": [1],
                                       "last_entry": self.FIX.format(2)})
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 2, "mid_fix_loop": True})

    def test_a_task_with_no_lines_starts_fresh(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.FIX.format(1), self.COMPLETE.format(1)],
                        tasks=2)
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "resume_task", "phase": 6, "task": 2,
                          "mid_fix_loop": False})

    def test_every_task_complete_finishes_phase_6(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(2), self.COMPLETE.format(1)],
                        tasks=2)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"]["completed"], [1, 2])
        self.assertEqual(pack["next_action"], {"kind": "finish_phase", "phase": 6})

    def test_an_unknown_task_count_never_finishes(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1), self.COMPLETE.format(2)])
        pack = self.pack("16:1:1")
        self.assertIsNone(pack["sdd"]["task_count"])
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 3, "mid_fix_loop": False})

    def test_an_absolute_plan_path_is_used_as_is(self):
        self.at_phase(5)
        plan = str(self.worktree / "plans" / "p.md")
        self.sdd_ledger(plan, [self.COMPLETE.format(1)], tasks=1)
        pack = self.pack("16:1:1")
        self.assertEqual((pack["sdd"]["plan"], pack["sdd"]["task_count"]), (plan, 1))
        self.assertEqual(pack["next_action"], {"kind": "finish_phase", "phase": 6})

    def test_sdd_position_outside_phase_5_does_not_steer(self):
        self.sdd_ledger("plans/p.md", [self.FIX.format(1)], tasks=2)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"]["completed"], [])
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 1})

    def test_two_plan_ledgers_are_ambiguous(self):
        self.at_phase(5)
        self.sdd_ledger("plans/b.md", [self.COMPLETE.format(1)])
        self.sdd_ledger("plans/a.md", [self.COMPLETE.format(1)])
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"], {"ambiguous": ["a", "b"]})
        self.assertEqual(pack["next_action"],
                         {"kind": "reorient", "reason": "ambiguous_sdd_workspace"})

    def test_a_ledger_naming_no_plan_is_not_a_ledger(self):
        workspace = self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1)])
        Path(workspace, "progress.md").write_text("# notes\n", encoding="utf-8")
        self.assertIsNone(self.pack("16:1:1")["sdd"])

    def test_a_symlinked_bucket_is_refused(self):
        bucket = Path(self.sdd_ledger("plans/p.md", [])).parent
        shutil.rmtree(bucket)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        bucket.symlink_to(elsewhere, target_is_directory=True)
        self.assert_refused("16:1:1", "the SDD workspace cannot be resolved")

    def test_the_last_entry_is_bounded(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        for number in range(25):
            self.commit(self.worktree, f"{number:02d} " + "x" * 150)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1), "y" * 600], tasks=1)
        completed = self.pack_raw("16:1:1")
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        self.assertEqual(json.loads(completed.stdout)["sdd"]["last_entry"], "y" * 400)

    def test_no_ledger_reads_create_nothing(self):
        self.assertIsNone(self.pack("16:1:1")["sdd"])
        self.assertFalse((self.primary / ".superpowers").exists())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ResumePack 2>&1 | tail -3`
Expected: non-zero exit, `FAILED` — every case that expects an `sdd` object,
a `resume_task`, `finish_phase` or ambiguity, or the symlink refusal fails
because `sdd` is still `null`.

- [ ] **Step 3: Implement**

In `home/common/agent-skills/scripts/workflow-state.py`, directly after
`probe_resume_worktree`:

1. Add the patterns and constants listed under Produces.
2. Add `sdd_workspace_bucket(worktree)` implementing the bucket invariant.
   Map `WorktreeBranchUnavailable` and every rule failure to the one
   `WorkflowError`. Docstring: mirrors `sdd-workspace`'s checkout-identity
   rule without creating anything; a test runs `sdd-workspace` against the
   same worktree (#265 D5).
3. Add `read_sdd_position(bucket, worktree)` implementing the component,
   candidate, single-ledger and resume-point invariants. Read
   `progress.md` with `read_text(encoding="utf-8", errors="replace")` and
   `splitlines()`. An `OSError` while listing or reading refuses with the D12
   clause.
4. Extend `resume_next_action` with keyword-only `sdd: dict[str, Any] | None`
   and `resume_point: dict[str, Any] | None`, inserting the
   `ambiguous_sdd_workspace` branch directly before `diverged_marker` and the
   `finish_phase` / `resume_task` branches directly before `start_phase`, per
   the order invariant.
5. In `command_resume_pack`, after `probe_resume_worktree`, compute
   `sdd, resume_point = read_sdd_position(sdd_workspace_bucket(worktree),
   worktree)`, put `sdd` in the pack and pass both to `resume_next_action`.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ResumePack 2>&1 | tail -3`
Expected: `OK`, 22 tests.

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_sdd_workspace.py 2>&1 | tail -3`
Expected: `OK`.

Run:
```bash
if git diff HEAD -- home/common/agent-skills/skills/sdd/scripts/sdd-workspace | grep -q .; then exit 1; fi
```
Expected: exit 0 (`sdd-workspace` is untouched; the pack mirrors it).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): read SDD position into the resume pack (#265)"
```
