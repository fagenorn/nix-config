# Task 2: Reap removes the scratch root and reports unattributed worktrees

Spec sections **Reap** and **Unattributed worktrees** are normative; this task cites D4–D6, D8 and D9. Removing worktrees is destructive: nothing outside a valid recorded root is ever passed to `git worktree remove` or `shutil.rmtree`.

**Files:**
- Modify: `python/agent_tools/launch_scope.py`
- Test: `tests/test_launch_scope.py`

**Interfaces:**
- Consumes (from Task 1): `SCRATCH_RECORD`, `scratch_path(data: bytes) -> str | None`, the `scratch` verb, and the `ScopeHarness` helpers `self.tmpdir`, `scratch_(**identity)`, `record_path(action_id="14:1:1")`, `add_worktree(path) -> str`, `worktrees() -> set[str]`. Existing: `reap_launch`, `reap`, `_directory_files`, `_remove_proved`, `_launch_names`, `PROCESSES_SURVIVED`.
- Produces:
  - `SCRATCH_NOT_REMOVED = "scratch_not_removed"`
  - `class ReapOutcome(NamedTuple): signalled: int; skip_reason: str | None; scratch_removed: bool; worktrees_removed: tuple[str, ...]` (`skip_reason` is `None`, `PROCESSES_SURVIVED` or `SCRATCH_NOT_REMOVED`).
  - `def worktree_paths(repo_root: str) -> list[str]` — the real paths of `git -C repo_root worktree list --porcelain -z`, in porcelain order (the first is the main worktree). A git that cannot start, a non-zero exit, or an empty listing raises `LaunchScopeError`.
  - `def reap_launch(repo_root: str, registry: Path, run_id: str, action_id: str) -> ReapOutcome` (new first parameter; replaces the `(signalled, survived)` tuple).
  - `def recorded_roots(registry: Path) -> set[str]` and `def unattributed_worktrees(repo_root: str, registry: Path) -> list[str]`.
  - Report shape: `{"reaped": [{"action_id", "scratch_removed", "signalled", "worktrees_removed"}], "skipped": [{"action_id", "reason"}], "unattributed_worktrees": [<path>]}`, canonical, every list sorted.

**Invariants:**
- The scratch step runs only in a clean round (no survivor, snapshot unchanged, no live marked process), after those checks and before `_remove_proved` (D5).
- `git worktree remove --force --force` is run only on a listed, non-main worktree whose real path is the root or below it, and whose path still exists (`os.path.lexists`); `shutil.rmtree` only on the validated root (D4, D5).
- Any failed remove, rmtree or prune, or any registration still inside the root after the prune, returns `SCRATCH_NOT_REMOVED` and skips `_remove_proved`, so `scratch.json` and the rows stay (D5, D9).
- `unattributed_worktrees` never contains the main worktree, anything below it, or anything inside a root of a valid `scratch.json` in any run; it never changes the exit code (D6).
- Across reap rounds, `scratch_removed` is true if any round deleted the root, and `worktrees_removed` is the sorted union of every round's removals.

- [ ] **Step 1: Write the failing tests**

In `ReapTest`, replace `assert_report` and add `scratch_root`:

```python
    SCRATCH_UNTOUCHED = {"scratch_removed": False, "worktrees_removed": []}

    def assert_report(self, completed, status, reaped, skipped, unattributed=()):
        """`reaped` entries omit the scratch members when the reap touched no scratch root."""
        self.assertEqual(completed.returncode, status, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout), {
            "reaped": [{**self.SCRATCH_UNTOUCHED, **entry} for entry in reaped],
            "skipped": skipped, "unattributed_worktrees": list(unattributed)})

    def scratch_root(self, **identity):
        done = self.scratch_(**identity)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout[:-1]
```

In `test_a_registration_that_keeps_racing_the_reap_is_kept_for_the_next` and `test_a_survivor_keeps_the_registry_and_is_skipped`, add `"unattributed_worktrees": []` to the expected report dict. No other existing assertion changes.

Add these tests to `ReapTest`:

```python
    def test_a_reap_removes_the_root_and_the_worktrees_inside_it(self):  # AC2
        root = self.scratch_root()
        # Through the unresolved temp dir spelling: git records the real path (D4).
        inside = self.add_worktree(self.tmpdir / os.path.basename(root) / "tree")
        nested = self.add_worktree(Path(root) / "deep" / "tree")
        self.assertTrue({inside, nested} <= self.worktrees())
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0, [
            {"action_id": "14:1:1", "signalled": 0, "scratch_removed": True,
             "worktrees_removed": sorted([inside, nested])}], [])
        self.assertFalse(os.path.lexists(root))
        self.assertEqual(self.worktrees() & {inside, nested}, set())
        self.assertFalse((self.registry / "14:1:1").exists())
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0,
                           [{"action_id": "14:1:1", "signalled": 0}], [])

    def test_a_sweep_removes_a_superseded_launchs_root(self):  # AC2
        root = self.scratch_root()
        inside = self.add_worktree(Path(root) / "tree")
        self.assertEqual(self.resume(issue=14, worktree=str(self.root / "wt-14"), now=LATER,
                                     owner_unavailable=True)["id"], "14:1:2")
        self.assert_report(self.scope(*self.reap_args("--sweep")), 0, [
            {"action_id": "14:1:1", "signalled": 0, "scratch_removed": True,
             "worktrees_removed": [inside]}], [])
        self.assertFalse(os.path.lexists(root))
        self.assertNotIn(inside, self.worktrees())

    def test_a_worktree_whose_directory_is_gone_is_pruned(self):
        root = self.scratch_root()
        inside = self.add_worktree(Path(root) / "tree")
        shutil.rmtree(inside)
        self.assertIn(inside, self.worktrees())
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0, [
            {"action_id": "14:1:1", "signalled": 0, "scratch_removed": True,
             "worktrees_removed": [inside]}], [])
        self.assertNotIn(inside, self.worktrees())

    def test_worktrees_outside_every_root_are_reported_and_kept(self):  # AC3
        live_root = self.scratch_root()
        in_live = self.add_worktree(Path(live_root) / "tree")
        below_main = self.add_worktree(self.root / ".worktrees" / "issue-1")
        elsewhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
        stray = self.add_worktree(elsewhere / "stray")
        self.assert_report(self.scope(*self.reap_args("--sweep")), 0, [], [], [stray])
        self.assert_report(self.scope(*self.reap_args("--action-id", "99:1:1")), 0,
                           [{"action_id": "99:1:1", "signalled": 0}], [], [stray])
        for tree in (in_live, below_main, stray):
            with self.subTest(tree=tree):
                self.assertTrue(os.path.isdir(tree))
                self.assertIn(tree, self.worktrees())
        self.assertTrue(self.record_path().is_file())

    def test_a_failed_removal_keeps_the_record_for_the_next_reap(self):  # D5
        root = self.scratch_root()
        self.add_worktree(Path(root) / "tree")
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(launch_scope.shutil, "rmtree",
                                  side_effect=OSError("injected")):
            status, report = launch_scope.reap(str(self.root), self.run_id, action_id="14:1:1")
        self.assertEqual((status, report), (1, {"reaped": [], "skipped": [
            {"action_id": "14:1:1", "reason": "scratch_not_removed"}],
            "unattributed_worktrees": []}))
        self.assertTrue(self.record_path().is_file())
        self.assertTrue(os.path.isdir(root))
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0, [
            {"action_id": "14:1:1", "signalled": 0, "scratch_removed": True}], [])
        self.assertFalse(os.path.lexists(root))

    def test_an_invalid_record_skips_the_launch_and_deletes_nothing(self):  # D4
        root = self.scratch_root()
        parent = os.path.dirname(root)
        self.record_path().write_text(json.dumps({"path": parent}) + "\n")
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 1, [],
                           [{"action_id": "14:1:1", "reason": "scratch_not_removed"}])
        self.assertTrue(self.record_path().is_file())
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(os.path.isdir(parent))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests.test_launch_scope.ReapTest 2>&1 | tail -4`
Expected: FAILED — the reports lack `unattributed_worktrees` and the scratch members, and the scratch roots survive the reap.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/launch_scope.py` (`from typing import NamedTuple`):

1. `worktree_paths(repo_root)`: run `["git", "-C", repo_root, "worktree", "list", "--porcelain", "-z"]` with `capture_output=True`; split stdout on `b"\0"`; each field starting with `b"worktree "` yields `os.path.realpath(os.fsdecode(field[len(b"worktree "):]))`.
2. `_inside(path: str, root: str) -> bool`: `path == root or path.startswith(root + os.sep)`. Both arguments are real paths.
3. `_git_step(repo_root, *args) -> bool`: run `git -C repo_root <args>` with `capture_output=True`; `OSError` raises `LaunchScopeError`; returns `returncode == 0`.
4. `_remove_scratch(repo_root: str, snapshot: dict[str, bytes]) -> tuple[bool, tuple[str, ...]] | None` — `None` means skip with `SCRATCH_NOT_REMOVED`:
   1. `data = snapshot.get(SCRATCH_RECORD)`; `None` → `return False, ()`.
   2. `root = scratch_path(data)`; `None` → `return None` (D4).
   3. `listed = worktree_paths(repo_root)`; `before = sorted(p for p in listed[1:] if _inside(p, root))`.
   4. `failed = False`. For each `p` in `before` with `os.path.lexists(p)`: `failed |= not _git_step(repo_root, "worktree", "remove", "--force", "--force", p)`. A path that no longer exists is left for the prune.
   5. `removed_root = False`; if `os.path.lexists(root)`: `shutil.rmtree(root)` (through the module attribute, so the failure test can patch it); `removed_root = True`; an `OSError` sets `failed = True`.
   6. `failed |= not _git_step(repo_root, "worktree", "prune")`.
   7. `relisted = worktree_paths(repo_root)`; if `failed` or any `p` in `relisted[1:]` is `_inside(p, root)` → `return None` (a locked, missing registration lands here: D9).
   8. `return removed_root, tuple(p for p in before if p not in set(relisted))`.
5. `reap_launch(repo_root, registry, run_id, action_id) -> ReapOutcome`: keep the round loop. Hold `removed_root = False` and `removed: set[str]` across rounds. In the clean round, after the live-marked check and before `_remove_proved`: `scratch = _remove_scratch(repo_root, snapshot)`; `None` → `return ReapOutcome(signalled, SCRATCH_NOT_REMOVED, False, ())`; otherwise fold it into `removed_root`/`removed`. `_remove_proved(...)` true → `return ReapOutcome(signalled, None, removed_root, tuple(sorted(removed)))`. Survivors, or rounds exhausted → `ReapOutcome(signalled, PROCESSES_SURVIVED, False, ())`. Update its docstring with the scratch step.
6. `recorded_roots(registry)`: for each `run` in `_launch_names(registry)` and each `action` in `_launch_names(registry / run)`, read `registry / run / action / SCRATCH_RECORD` when it is a regular file (`is_file()` and not `is_symlink()`); `FileNotFoundError` → skip, other `OSError` → `LaunchScopeError`; add `scratch_path(data)` when not `None`.
7. `unattributed_worktrees(repo_root, registry)`: `listed = worktree_paths(repo_root)`; `main = listed[0]`; `roots = recorded_roots(registry)`; return `sorted(p for p in listed[1:] if not _inside(p, main) and not any(_inside(p, r) for r in roots))`.
8. `reap(...)`: call `reap_launch(repo_root, registry, run_id, name)`; a `skip_reason` appends `{"action_id", "reason"}` to `skipped`; otherwise append `{"action_id", "signalled", "scratch_removed", "worktrees_removed": list(...)}` to `reaped`. After the loop, add `"unattributed_worktrees": unattributed_worktrees(repo_root, registry)` to the report. The exit status stays `0 if not skipped else 1`.
9. Module docstring: replace the reap report line with the new shape; add the scratch step (clean round only, force-remove inside worktrees, rmtree, prune, re-list), the `unattributed_worktrees` rule (D6), `scratch_not_removed` under exit 1, and a git listing failure under exit 2. Write it from the code as implemented in this step.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests.test_launch_scope 2>&1 | tail -4`
Expected: `OK` — the six new `ReapTest` cases pass, and every existing case passes with the updated `assert_report`.

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests.test_agent_tools_canonical tests.test_launch_commit 2>&1 | tail -2`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/launch_scope.py tests/test_launch_scope.py
git commit -m "feat(launch-scope): reap removes the launch's scratch root and reports unattributed worktrees (#277)"
```
