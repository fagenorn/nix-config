# Task 6: Live legacy owner and old-helper refusal

**Files:**
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py` (new `LegacyOwnerCompatibilityTest`)

Test-only task: it proves AC4 against the code Tasks 2–5 built. If a test can only pass by changing product code, stop and report BLOCKED with the failing assertion; that is a defect in an earlier task.

**Interfaces:**
- Consumes: `MigrationFixtures` (`install_legacy`, `tree_snapshot`, `store`, `store_root`), harness `init_run(creation_key=)`, `spawn(issue=, worktree=)`, `progress(..., ok=)`, `control(...)`, `run_cli`, `cli_env`, `read_state`, `SCRIPT`; `attempt_identity.legacy_key`.
- Produces: nothing.

**Invariants:**
- The legacy owner uses only the legacy handle `orchestrate-14`, the action id `14:1:1` and worker id `14:1:1:w1` — never the transaction id.
- The base generation is the real one: `git -C <repo root> archive eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7 home/common/agent-skills/scripts | tar -x -C <tmp>`; the commit's absence is a test **failure** (`self.fail`), never a skip (D13). `<repo root>` is `Path(__file__).resolve().parents[4]` (the checkout holding `home/`).
- The base helper runs as a subprocess `[sys.executable, <tmp>/home/common/agent-skills/scripts/workflow-state.py, ...]` with `env = {**self.cli_env, "PYTHONPATH": <repo root>/python}` (it imports `agent_tools.host_admission` from source in its `scripts` layout) and `cwd=<tmp>`.
- Every refusal leaves the `.superpowers` tree snapshot byte-identical.

- [ ] **Step 1: Write the tests**

```python
BASE_COMMIT = "eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7"
REPO = Path(__file__).resolve().parents[4]


class LegacyOwnerCompatibilityTest(MigrationFixtures, unittest.TestCase):
    def live_legacy_owner(self):
        """A schema-7 `orchestrate-14` ledger with an active owner on 14:1:1."""
        self.init_run(creation_key="fixture-14")
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.install_legacy(self.read_state(), "orchestrate-14")
        self.assertEqual(json.loads(self.state_path.read_text())["schema_version"], 7)

    def owner_lifecycle(self):
        """progress, register-worker, release-worker, suspend, then finish — legacy ids only."""
        worktree = self.root / "wt-14"
        self.progress(issue=14, phase=1, now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z")
        self.release_worker(worker_id="14:1:1:w1", event="returned",
                            now="2026-08-13T20:03:00Z")
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:04:00Z")
        self.resume(issue=14, worktree=worktree, now="2026-08-13T20:05:00Z")
        self.finish(1, self.merged_result(), now="2026-08-13T20:30:00Z")
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][-1]["state"], "merged")
        self.assertEqual(self.read_state()["run_id"], "orchestrate-14")

    def assert_bound(self):
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["run_id"]), (8, "orchestrate-14"))
        self.assertEqual(self.store().lookup(ai.legacy_key("orchestrate-14")),
                         state["transaction_id"])

    def test_control_migrates_under_a_live_owner(self):
        self.live_legacy_owner()
        self.control(now="2026-08-13T20:00:30Z", issues=[14],
                     tracker=[self.tracker_fact(14)], max_parallel=100)
        self.assert_bound()
        self.owner_lifecycle()

    def test_owner_write_is_the_migrating_write(self):
        self.live_legacy_owner()
        self.progress(issue=14, phase=1, now="2026-08-13T20:00:30Z")
        self.assert_bound()
        self.owner_lifecycle()

    def base_helper(self, scratch):
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            self.fail(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D13)")
        archive = subprocess.run(["git", "-C", str(REPO), "archive", BASE_COMMIT,
                                  "home/common/agent-skills/scripts"],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(scratch)], input=archive.stdout, check=True)
        return scratch / "home/common/agent-skills/scripts/workflow-state.py"

    def test_base_helper_refuses_schema_8_without_writing(self):
        self.live_legacy_owner()
        self.progress(issue=14, phase=1, now="2026-08-13T20:00:30Z")
        self.assert_bound()
        snapshot = self.tree_snapshot()
        with tempfile.TemporaryDirectory() as scratch:
            script = self.base_helper(Path(scratch))
            env = {**self.cli_env, "PYTHONPATH": str(REPO / "python")}
            for args in (("check-launch", "--action-id", "14:1:1"),
                         ("progress", "--issue", "14", "--attempt", "1", "--phase", "2",
                          "--next-needs-context", "true", "--artifacts-sufficient", "false",
                          "--remainder-self-contained", "false")):
                with self.subTest(command=args[0]):
                    completed = subprocess.run(
                        [sys.executable, str(script), args[0], "--repo-root", str(self.root),
                         "--run-id", "orchestrate-14", *args[1:]],
                        env=env, cwd=scratch, capture_output=True, text=True, timeout=120)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertEqual(self.tree_snapshot(), snapshot)
```

Add `import subprocess`, `import sys`, `import tempfile` and `from pathlib import Path` if Task 5 has not. The owner calls use the harness's existing `progress`, `register_worker`, `release_worker`, `suspend`, `resume` (a control sweep that returns the `resume` action), `finish` (the legacy result-file transport, which the harness drives on a schema-2 copy that `finish` itself migrates — still under `orchestrate-14`) and `merged_result`. If the control sweep in `test_control_migrates_under_a_live_owner` needs the worktree fact the harness's `resume` passes, pass the same `worktrees=[self.worktree_fact(14, recorded={...})]` it builds; the test's point is only that control's write is the migrating one.

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py -k LegacyOwnerCompatibility`
Expected: OK, 3 tests. These pin behaviour Tasks 2–5 already built; to see each can fail, temporarily change `assert_bound`'s expected schema to `7` and watch both owner tests fail, then revert (do not commit the change).

- [ ] **Step 3: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py`
Expected: OK, no skips (`grep -c "skipped"` on the captured output prints `0`).

- [ ] **Step 4: Commit**

Stage the test file, then `launch-commit … -- -m "test: live legacy owners and the base helper on schema 8 (#337)"` with the session trailers.
