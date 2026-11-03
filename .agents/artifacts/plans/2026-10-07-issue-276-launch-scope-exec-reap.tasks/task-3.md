# Task 3: `launch-scope reap` by `--action-id` and `--sweep`

**Files:**
- Modify: `python/agent_tools/launch_scope.py`
- Test: `tests/test_launch_scope.py`. Add `ReapTest` above the `if __name__` line.

**Interfaces:**
- Consumes, from Task 2's `agent_tools.launch_scope`: `REGISTRY_DIR`, `SAFE_SEGMENT`, `NONCE`, `ROW_KEYS`, `CURRENT`, `CHECK_LAUNCH_FAILED`, `MALFORMED_REPLY`, `LaunchScopeError`, `safe_segment`, `registry_root`, `launch_directory`, `ask_launch` and `main`, whose subcommand parser gains `reap`. From Task 1: `terminate`, `process_table`, `read_marker` and `require_supported_platform`. `launch_scope` must import `terminate` by name (`from agent_tools.launch_processes import terminate`) and call it bare, so that `mock.patch.object(launch_scope, "terminate", ...)` takes effect (D12). From the tests of Tasks 1 and 2: `ScopeHarness`, `UNMARKED_ENV`, `is_dead`, `wait_until`, `kill_quietly` and `LATER`.
- Produces:
  - `PROCESSES_SURVIVED = "processes_survived"`
  - `reap_launch(registry: Path, run_id: str, action_id: str) -> tuple[int, bool]`, which returns `(signalled, survived)`
  - `reap(repo_root: str, run_id: str, *, action_id: str | None = None, sweep: bool = False) -> tuple[int, dict]`, which returns `(exit status, report)`
  - The CLI form `launch-scope reap --repo-root R --run-id I (--action-id A | --sweep)`, through a required mutually exclusive group. A `--` separator in a `reap` invocation is a usage error.

**Invariants:**
- The report is exactly `{"reaped": [{"action_id", "signalled"}], "skipped": [{"action_id", "reason"}]}`, with both lists sorted by `action_id`. It is printed as one canonical line. The exit is 0 when `skipped` is empty and 1 otherwise. A usage or helper error exits 2 with empty stdout (D6).
- `--action-id` never asks the ledger. `--sweep` asks `ask_launch` once for each action directory under `<registry>/<run-id>/`, in sorted order. A directory whose name is not a safe segment is never visited, and neither is a non-directory entry. The reply decides what happens. `CURRENT` leaves the launch alone, and it appears in neither list. `CHECK_LAUNCH_FAILED` or `MALFORMED_REPLY` puts it in `skipped` with that reason. Any other reason is a negative answer, so the launch is reaped. A missing run directory yields `{"reaped": [], "skipped": []}`, exit 0.
- `reap_launch` proves before it signals (parent D4). A pid is marked when its `read_marker` fully matches `re.escape(f"{run_id}/{action_id}/") + "[0-9a-f]{32}"`. A row (`<nonce>.json`, strictly loaded, with keys exactly `ROW_KEYS`, the nonce matching `NONCE` and equal to the file stem, and `pgid` either `None` or an `int` that is not a `bool` and is greater than 0) proves its group only when a live marked pid carries exactly `f"{run_id}/{action_id}/{row nonce}"` and its table pgid equals the row's pgid. A row that is unreadable or malformed proves nothing. The call is `terminate(marked_pids, proved_groups)`.
- When there are no survivors, the action directory is removed with `shutil.rmtree`, and a directory that is already gone is fine. When there are survivors, the directory stays and the launch is listed in `skipped` with `processes_survived` (D5, D6). A repeated reap reports `signalled: 0` and exits 0.
- Both identities pass `safe_segment` before any path is built (D10).

- Group-proof discrimination tests (per D14), beside the sweep test below: (a) a stale row whose `pgid` names a live group with no marked member (an unmarked `sleep 300` started with `start_new_session=True`) — that group must survive the reap; (b) a proved group, recorded in a row and holding one marked member, that also holds an unmarked member (a child started with the marker stripped from its environment but inside the same group) — the unmarked member must die with its group. Together they fail both "ignore recorded groups" and "signal every recorded group without proof".

- [ ] **Step 1: Write the failing test**

Add `from agent_tools import launch_scope` to the imports, and add this class above the `if __name__` line:

```python
LEADER = """
import os, subprocess, sys, time
grandchild = subprocess.Popen(["sleep", "300"])
escapee = subprocess.Popen(["sleep", "300"], start_new_session=True)
with open(sys.argv[1] + ".tmp", "w") as handle:
    handle.write(f"{os.getpid()} {grandchild.pid} {escapee.pid}")
os.replace(sys.argv[1] + ".tmp", sys.argv[1])
time.sleep(300)
"""


class ReapTest(ScopeHarness, unittest.TestCase):
    def reap_args(self, *selector, run_id=None):
        return ["reap", "--repo-root", str(self.root),
                "--run-id", self.run_id if run_id is None else run_id, *selector]

    def assert_report(self, completed, status, reaped, skipped):
        self.assertEqual(completed.returncode, status, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout), {"reaped": reaped, "skipped": skipped})

    def test_a_sweep_kills_orphans_after_the_supervisor_and_leader_die(self):
        pidfile = self.root / "pids"
        supervisor = self.background_exec(sys.executable, "-c", LEADER, str(pidfile))
        leader, grandchild, escapee = self.pid_from(pidfile)
        sibling = subprocess.Popen(["sleep", "300"], env=UNMARKED_ENV, start_new_session=True)
        self.addCleanup(sibling.wait)
        self.addCleanup(kill_quietly, sibling.pid)
        supervisor.kill()
        supervisor.wait(timeout=30)
        os.kill(leader, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: is_dead(leader)))
        self.assertEqual(self.resume(issue=14, worktree=str(self.root / "wt-14"), now=LATER,
                                     owner_unavailable=True)["id"], "14:1:2")
        swept = self.scope(*self.reap_args("--sweep"))
        self.assert_report(swept, 0, [{"action_id": "14:1:1", "signalled": 2}], [])
        self.assertTrue(wait_until(lambda: is_dead(grandchild), 2.0))
        self.assertTrue(wait_until(lambda: is_dead(escapee), 2.0))
        self.assertFalse(is_dead(sibling.pid))
        self.assertFalse((self.registry / "14:1:1").exists())

    def test_a_sweep_leaves_the_current_launch_alone_and_a_self_reap_ends_it(self):
        pidfile = self.root / "pids"
        supervisor = self.background_exec(
            sys.executable, "-c",
            "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); "
            "time.sleep(300)", str(pidfile))
        (child,) = self.pid_from(pidfile)
        self.assert_report(self.scope(*self.reap_args("--sweep")), 0, [], [])
        self.assertFalse(is_dead(child))
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0,
                           [{"action_id": "14:1:1", "signalled": 1}], [])
        self.assertEqual(supervisor.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertTrue(is_dead(child))
        self.assert_report(self.scope(*self.reap_args("--action-id", "14:1:1")), 0,
                           [{"action_id": "14:1:1", "signalled": 0}], [])
        self.assertFalse((self.registry / "14:1:1").exists())

    def test_a_sweep_with_no_registry_reaps_nothing(self):
        self.assert_report(self.scope(*self.reap_args("--sweep")), 0, [], [])

    def test_a_sweep_skips_a_launch_whose_check_fails_or_is_malformed(self):
        self.assertEqual(self.exec_("true").returncode, 0)
        for body, reason in (("exit 2", "check_launch_failed"),
                             ("echo not-json", "malformed_reply")):
            with self.subTest(reason=reason):
                self.write_shim(body)
                self.assert_report(self.scope(*self.reap_args("--sweep")), 1, [],
                                   [{"action_id": "14:1:1", "reason": reason}])
        self.assertTrue((self.registry / "14:1:1").is_dir())

    def test_a_survivor_keeps_the_registry_and_is_skipped(self):  # D12
        self.assertEqual(self.exec_("true").returncode, 0)
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(launch_scope, "terminate",
                                  return_value=(1, frozenset({4242424}))):
            status, report = launch_scope.reap(str(self.root), self.run_id, action_id="14:1:1")
        self.assertEqual((status, report), (1, {"reaped": [], "skipped": [
            {"action_id": "14:1:1", "reason": "processes_survived"}]}))
        self.assertTrue((self.registry / "14:1:1").is_dir())

    def test_unsafe_ids_and_usage_errors_exit_two_and_delete_nothing(self):
        keep = self.registry.parent / "keep"
        keep.mkdir(parents=True)
        cases = [self.reap_args("--action-id", action) for action in ("..", ".", "../keep", "a/b")]
        cases += [self.reap_args("--action-id", "keep", run_id=".."),
                  self.reap_args(), self.reap_args("--sweep", "--action-id", "14:1:1"),
                  [*self.reap_args("--sweep"), "--", "true"]]
        for args in cases:
            with self.subTest(args=args):
                done = self.scope(*args)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertTrue(keep.is_dir())
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests.test_launch_scope.ReapTest 2>&1 | tail -5`
Expected: FAIL. `launch-scope` rejects the `reap` subcommand with exit 2, and `launch_scope.reap` does not exist.

- [ ] **Step 3: Write the minimal implementation**

In `reap_launch(registry, run_id, action_id)`:
1. Set `directory = launch_directory(registry, run_id, action_id)` and `table = process_table()`.
2. `marked` maps pid to marker, for every non-zombie pid whose `read_marker` fully matches the launch pattern.
3. Load the rows as the invariants say. `proved` is the set of pgids from valid rows that a marked pid proves.
4. Call `signalled, survivors = terminate(marked, proved)`.
5. When `survivors` is empty, remove the directory (`shutil.rmtree`, catching `FileNotFoundError`). Return `(signalled, bool(survivors))`.

In `reap(repo_root, run_id, *, action_id, sweep)`: call `require_supported_platform()` and `safe_segment` on each id, then resolve `registry_root(repo_root)`.
- With `action_id`, the launch is `[action_id]`.
- With `sweep`, list the sorted child directories with safe names under `registry / run_id`. For each one, read `ask_launch(repo_root, run_id, name)`, and either skip the launch, leave it alone, or reap it, as the invariants say.
- For each launch to reap, call `reap_launch`. A survivor puts it in `skipped` with `PROCESSES_SURVIVED`. Otherwise it goes in `reaped` with `{"action_id": a, "signalled": n}`.
- Return `(0 if not skipped else 1, {"reaped": sorted(...), "skipped": sorted(...)})`.

In `main`, add the `reap` subparser. It takes the required `--repo-root` and `--run-id`, plus a required mutually exclusive group of `--action-id` and `--sweep` (`store_true`). A `--` in a reap argv is `parser.error`. Print the report as one canonical line and return its status. Errors map to exit 2 exactly as they do for `exec`. Update the module docstring to cover `reap` and its exit codes.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_scope.py 2>&1 | tail -5`
Expected: `OK`, with 27 tests, on darwin. The Linux run comes from CI's advisory `just agent-workflow-tests`, and ship records the darwin output in the PR.
Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests.test_launch_scope.ReapTest.test_a_sweep_kills_orphans_after_the_supervisor_and_leader_die 2>&1 | tail -3`
Expected: `OK`. At the start commit this test fails.

- [ ] **Step 5: Commit**

Use `launch-commit` when your prompt carries a `Lifecycle worker:` line.

```bash
git add python/agent_tools/launch_scope.py tests/test_launch_scope.py
git commit -m "feat(launch-scope): reap a launch by action id or sweep a run's non-current launches (#276)"
```
