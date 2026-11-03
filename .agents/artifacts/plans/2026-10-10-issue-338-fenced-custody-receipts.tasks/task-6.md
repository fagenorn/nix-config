# Task 6: Compatibility: the base helper and the launch projections

Two regression pins for AC6: the real previous helper generation refuses a schema-9 ledger without writing, and the launch projections of https://github.com/fagenorn/nix-config/issues/132 and https://github.com/fagenorn/nix-config/issues/133 print the same bytes across the bind. Read the root's Global Constraints first. Decisions: D4, D14.

**Files:**
- Modify: `home/common/agent-skills/tests/test_attempt_custody.py` (add)

**Interfaces:**
- Consumes: `LifecycleCustody` (Task 3) with `spawn_14`, `tree`, `install_legacy(…, version=8)`; the `check-launch` and `current-launch` commands; `git archive` of the pinned base commit.
- Produces: `CompatibilityTest`; no product code.

**Invariants:**
- The helper under test is the base generation in full: `workflow-state.py`, its sibling scripts and the `agent_tools` package are all extracted from `5bd914e199f3e57217780596beefe69838f4efd4`, and `PYTHONPATH` points at the extracted package, never at the worktree's.
- A missing base commit fails the test; it never skips.
- The base helper reads the schema-8 fixture (the positive control), then exits 2 on the same ledger at schema 9, for an unlocked read and for a locked write, with the `.superpowers` tree unchanged.
- `check-launch` and `current-launch` print identical bytes before and after the 8 → 9 bind for the current launch, a launch that does not exist and a remainder launch.

- [ ] **Step 1: Write the tests**

In `home/common/agent-skills/tests/test_attempt_custody.py`, add `import subprocess`, `import sys` and `import tempfile` to the imports, and after them:

```python
REPO = Path(__file__).resolve().parents[4]
BASE_COMMIT = "5bd914e199f3e57217780596beefe69838f4efd4"
```

Add this class before the `__main__` guard:

```python
class CompatibilityTest(LifecycleCustody, unittest.TestCase):
    def base_helper(self, scratch):
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            self.fail(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D14)")
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             "home/common/agent-skills/scripts",
             "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(scratch)], input=archive.stdout, check=True)
        script = scratch / "home/common/agent-skills/scripts/workflow-state.py"
        env = {**self.cli_env, "PYTHONPATH": str(scratch / "python")}
        return lambda command, *rest: subprocess.run(
            [sys.executable, str(script), command, "--repo-root", str(self.root),
             "--run-id", self.run_id, "--action-id", "14:1:1", *rest],
            env=env, cwd=scratch, capture_output=True, text=True, timeout=120)

    def test_ac6_the_base_helper_refuses_a_schema_9_ledger_without_writing(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        with tempfile.TemporaryDirectory() as scratch:
            base = self.base_helper(Path(scratch))
            control = base("check-launch")  # positive control: it reads schema 8
            self.assertEqual((control.returncode, json.loads(control.stdout)["reason"]),
                             (0, "current"), control.stderr)
            self.register_worker(action_id="14:1:1", now=T(1))
            self.assertEqual(self.read_state()["schema_version"], 9)
            before = self.tree()
            for command, rest in (("check-launch", ()),
                                  ("register-worker", ("--now", T(2)))):
                with self.subTest(command=command):
                    refused = base(command, *rest)
                    self.assertEqual(refused.returncode, 2, refused.stdout)
                    self.assertIn("unknown_schema", refused.stderr)
                    self.assertEqual(self.tree(), before)

    def test_ac6_launch_projections_print_the_same_bytes_across_the_bind(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)

        def projections():
            return [self.run_cli(command, "--repo-root", self.root, "--run-id", self.run_id,
                                 "--action-id", action).stdout
                    for command in ("check-launch", "current-launch")
                    for action in ("14:1:1", "14:1:2", "14:r1:1")]

        before = projections()
        self.register_worker(action_id="14:1:1", now=T(1))
        self.assertEqual(self.read_state()["schema_version"], 9)
        self.assertEqual(projections(), before)
```

- [ ] **Step 2: Run them**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py -k CompatibilityTest`
Expected: `OK`, 2 tests. They pin behaviour Tasks 3 to 5 delivered, so they pass when written.

- [ ] **Step 3: Show that each can fail**

Change `BASE_COMMIT` to forty zeros and rerun: `test_ac6_the_base_helper_refuses_a_schema_9_ledger_without_writing` must fail with `is missing; fetch it, do not skip`. Restore it. Then temporarily delete the `register_worker` line of `test_ac6_launch_projections_print_the_same_bytes_across_the_bind` and confirm its `schema_version` assertion fails: the test really crosses the bind. Restore it; `git diff` shows neither change.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_admission_replay.py`
Expected: `OK`.

Run: `git diff --stat 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- home/common/agent-skills/tests/fixtures`
Expected: empty output: the committed admission-replay baseline is unchanged.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_attempt_custody.py
launch-commit … -- -m "test(attempt-custody): pin the base helper's refusal and the launch projections (#338)"
```
