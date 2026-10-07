# Task 2: `launch-scope exec` with its registry row and liveness check

**Files:**
- Create: `python/agent_tools/launch_scope.py`
- Modify: `lib/agent-tools.nix`. Add `"launch-scope"` to `commands`, right after `"launch-commit"`.
- Test: `tests/test_launch_scope.py`. Add a harness loader and the classes `ScopeHarness`, `ExecTest` and `CheckLaunchReplyTest`, all above the `if __name__` line.

**Interfaces:**
- Consumes, from Task 1's `agent_tools.launch_processes`: `MARKER_ENV`, `UnsupportedPlatform`, `ProcessTableError`, `require_supported_platform`, `process_table`, `read_marker` and `terminate`. From Task 1's test module: `UNMARKED_ENV`, `is_dead`, `wait_until` and `kill_quietly`. From `agent_tools.launch_commit`: `ask_worker`, `LaunchCommitError`, `LIVE`, `CHECK_WORKER_FAILED` and `MALFORMED_REPLY` (D4). From `agent_tools.agent_platform`: `write_atomically(target: Path, data: bytes)`. From `agent_tools.canonical`: `reject_duplicate_keys` and `reject_nonfinite_literal`.
- Produces, in `agent_tools.launch_scope`, for Task 3:
  - The constants `REGISTRY_DIR = "agent-launch"`, `SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._:-]+")`, `NONCE = re.compile(r"[0-9a-f]{32}")`, `ROW_KEYS = frozenset({"nonce", "pgid", "started_at", "argv0"})`, `CURRENT = "current"`, `CHECK_LAUNCH_FAILED = "check_launch_failed"`, `REFUSED_EXIT = 3` and `USAGE_EXIT = 2`
  - `class LaunchScopeError(Exception)`, which maps to exit 2
  - `safe_segment(value: str, label: str) -> str`. It returns the value when it fully matches `SAFE_SEGMENT` and is neither `.` nor `..`, and otherwise raises `LaunchScopeError` (D10).
  - `worker_action(worker_id: str) -> str`, which is `worker_id.rpartition(":w")[0]` (D2)
  - `registry_root(repo_root: str) -> Path`. It runs `git -C <repo_root> rev-parse --path-format=absolute --git-common-dir` and returns `Path(stdout.strip()) / REGISTRY_DIR`. An `OSError` or a non-zero exit raises `LaunchScopeError`.
  - `launch_directory(registry: Path, run_id: str, action_id: str) -> Path`, which checks both segments first
  - `launch_marker(run_id: str, action_id: str, nonce: str) -> str`, which returns `f"{run_id}/{action_id}/{nonce}"`
  - `check_launch_reply(stdout: bytes, action_id: str) -> str` and `ask_launch(repo_root: str, run_id: str, action_id: str) -> str`
  - `exec_scoped(repo_root: str, run_id: str, argv: Sequence[str], *, action_id: str | None = None, worker_id: str | None = None) -> tuple[int, dict | None]`
  - `main(argv: Sequence[str] | None = None) -> int`, which takes the subcommand `exec` (Task 3 adds `reap`)

**Invariants:**
- The order is fixed. First validate and resolve the registry (any failure exits 2 with empty stdout and no row). Then write the row with `pgid: null`, check liveness, spawn, rewrite the row with the pgid, wait, clean up and delete the row (spec **`exec` behaviour**, D3).
- Every exit after the row exists deletes the row. That covers a refusal, a helper `OSError` (exit 2), a spawn failure (126 or 127) and a clean return. The one exception is cleanup survivors (D5). Deleting a row that is already gone is not an error, because `reap` may have removed the directory first.
- `exec` deletes only its own `<nonce>.json` and never removes the action directory.
- A refusal prints exactly one line, `{"action_id": <the launch's action id>, "reason": <reason>, "started": false}`, and exits 3. Nothing is spawned.
- The child runs with `start_new_session=True` and `env={**os.environ, MARKER_ENV: marker}`, and it inherits stdin, stdout, stderr and cwd.
- `exec` waits with `os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)`, cleans up, and only then reaps through `child.wait()` (D11). It returns `rc` when `rc >= 0` and `128 - rc` otherwise.
- SIGINT, SIGTERM and SIGHUP are forwarded with `os.killpg(child_pid, signum)`, ignoring `ProcessLookupError` and `PermissionError`. The handlers are installed before the spawn. A signal that arrives before the pid is known is queued and forwarded right after the spawn. The previous handlers are restored on return.
- Cleanup passes `terminate(marked, [child_pid])`, where `marked` is every non-zombie pid whose `read_marker` equals this exec's exact marker. Survivors are named on stderr as `launch-scope: processes survived SIGKILL: <space-separated pids>`, the row stays, and the child's status is still returned (D5).

- Exception safety after the spawn (per D14). Everything from step 5 through step 7 below runs inside one `try`/`finally`. On any exception after `Popen` returns (a failed row rewrite through `write_atomically`, a `ProcessTableError`, an `OSError` from `waitid`): the `finally` still runs cleanup, sending `os.killpg(child.pid, SIGTERM)` and then the same `terminate` call when the table is readable, and `os.killpg(child.pid, SIGKILL)` when it is not; it reaps the child with `child.wait()`, and restores the previous signal handlers unconditionally. When that cleanup cannot prove the group is gone, the row stays (so a later `reap` still finds the launch) and the error maps to exit 2 with `launch-scope: <error>` on stderr. A test injects a failing `write_atomically` (or `process_table`) after the spawn and asserts that the child's group is dead, the handlers are restored and the exit is 2.

- [ ] **Step 1: Write the failing test**

Add these imports to the top of `tests/test_launch_scope.py`: `importlib.util`, `json`, `re`, `shlex` and `shutil`, plus `from agent_tools.launch_scope import check_launch_reply`. Then add the following above the `if __name__` line:

```python
ROOT = Path(__file__).parents[1]
HARNESS_SOURCE = ROOT / "home/common/agent-skills/tests/test_workflow_state.py"
WORKFLOW = ROOT / "home/common/agent-skills/scripts/workflow-state.py"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
LATER = "2026-08-13T20:06:00Z"


def _harness():
    spec = importlib.util.spec_from_file_location("launch_scope_harness", HARNESS_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LifecycleHarness


LifecycleHarness = _harness()


class ScopeHarness(LifecycleHarness):
    """A ledger with launch 14:1:1 current, a git root for the registry, a PATH shim."""

    def setUp(self):
        super().setUp()
        self.shims = self.root / "shims"
        self.shims.mkdir()
        self.write_shim(f"exec {shlex.quote(sys.executable)} {shlex.quote(str(WORKFLOW))} \"$@\"")
        self.env = {**{k: v for k, v in self.cli_env.items() if k != MARKER_ENV}, **HERMETIC_GIT,
                    "PATH": f"{self.shims}{os.pathsep}{os.environ['PATH']}"}
        subprocess.run(["git", "init", "-q", str(self.root)], env=self.env, check=True)
        common = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--path-format=absolute",
             "--git-common-dir"], env=self.env, check=True, capture_output=True, text=True)
        self.registry = Path(common.stdout.strip()) / "agent-launch" / self.run_id
        self.init_run()
        self.assertEqual(self.spawn(issue=14, worktree=str(self.root / "wt-14"))["id"], "14:1:1")

    def write_shim(self, body):
        shim = self.shims / "workflow-state"
        shim.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        shim.chmod(0o755)

    def argv(self, *args):
        return [sys.executable, "-m", "agent_tools.launch_scope", *args]

    def scope(self, *args, env=None):
        return subprocess.run(self.argv(*args), cwd=self.root, capture_output=True, text=True,
                              check=False, env=self.env if env is None else env, timeout=120)

    def exec_args(self, *command, action_id="14:1:1", worker_id=None):
        identity = ["--worker-id", worker_id] if worker_id else ["--action-id", action_id]
        return ["exec", "--repo-root", str(self.root), "--run-id", self.run_id, *identity,
                "--", *command]

    def exec_(self, *command, **identity):
        return self.scope(*self.exec_args(*command, **identity))

    def background_exec(self, *command, **identity):
        supervisor = subprocess.Popen(self.argv(*self.exec_args(*command, **identity)),
                                      cwd=self.root, env=self.env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(supervisor.wait)
        self.addCleanup(kill_quietly, supervisor.pid)
        return supervisor

    def pid_from(self, path):
        self.assertTrue(wait_until(path.exists), path)
        pids = [int(word) for word in path.read_text().split()]
        for pid in pids:
            self.addCleanup(kill_quietly, pid)
        return pids

    def rows(self, action_id):
        directory = self.registry / action_id
        return sorted(p.name for p in directory.glob("*.json")) if directory.is_dir() else []

    def assert_refused(self, completed, action_id, reason):
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout),
                         {"action_id": action_id, "started": False, "reason": reason})


BACKGROUND_SLEEP = ('sleep 300 & echo $! > "$1.tmp" && mv "$1.tmp" "$1"; wait')


class ExecTest(ScopeHarness, unittest.TestCase):
    def test_a_superseded_launch_starts_nothing_and_leaves_no_row(self):
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"), now=LATER,
                              owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        witness = self.root / "started"
        done = self.exec_(sys.executable, "-c",
                          "import sys; open(sys.argv[1], 'w').close()", str(witness))
        self.assert_refused(done, "14:1:1", "superseded_launch")
        self.assertFalse(witness.exists())
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_backgrounded_sleep_does_not_outlive_exec(self):
        pidfile = self.root / "sleep.pid"
        done = self.exec_("sh", "-c", 'sleep 300 & echo $! > "$1"', "sh", str(pidfile))
        self.assertEqual(done.returncode, 0, done.stderr)
        (pid,) = self.pid_from(pidfile)
        self.assertTrue(wait_until(lambda: is_dead(pid), 2.0))
        self.assertEqual(self.rows("14:1:1"), [])

    def test_the_child_carries_the_marker_and_its_status_passes_through(self):
        seen = self.root / "marker"
        done = self.exec_("sh", "-c", 'printf %s "$AGENT_LAUNCH_SCOPE" > "$1"; exit 7',
                          "sh", str(seen))
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertRegex(seen.read_text(),
                         rf"\A{re.escape(self.run_id)}/14:1:1/[0-9a-f]{{32}}\Z")
        self.assertEqual(self.exec_("sh", "-c", "kill -TERM $$").returncode,
                         128 + signal.SIGTERM)

    def test_a_term_to_exec_reaches_the_command_group(self):
        pidfile = self.root / "sleep.pid"
        supervisor = self.background_exec("sh", "-c", BACKGROUND_SLEEP, "sh", str(pidfile))
        (pid,) = self.pid_from(pidfile)
        supervisor.send_signal(signal.SIGTERM)
        self.assertEqual(supervisor.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertTrue(is_dead(pid))
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_concurrent_exec_of_the_same_launch_is_untouched(self):
        pidfile = self.root / "sleep.pid"
        first = self.background_exec("sh", "-c", BACKGROUND_SLEEP, "sh", str(pidfile))
        (pid,) = self.pid_from(pidfile)
        second = self.exec_("true")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(is_dead(pid))
        self.assertEqual(len(self.rows("14:1:1")), 1)
        first.send_signal(signal.SIGTERM)
        first.wait(timeout=30)
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_worker_runs_while_live_and_is_refused_once_released(self):
        worker = self.register_worker(action_id="14:1:1",
                                      now="2026-08-13T20:01:00Z")["worker_id"]
        self.assertEqual(self.exec_("true", worker_id=worker).returncode, 0)
        self.release_worker(worker_id=worker, event="returned", now="2026-08-13T20:02:00Z")
        self.assert_refused(self.exec_("true", worker_id=worker), "14:1:1", "released")

    def test_a_failed_or_malformed_check_starts_nothing(self):
        worker = self.register_worker(action_id="14:1:1",
                                      now="2026-08-13T20:01:00Z")["worker_id"]
        self.write_shim("exit 2")
        self.assert_refused(self.exec_("true"), "14:1:1", "check_launch_failed")
        self.assert_refused(self.exec_("true", worker_id=worker), "14:1:1",
                            "check_worker_failed")
        good = {"action_id": "14:1:1", "current": True, "current_action_id": "14:1:1",
                "reason": "current"}
        for reply in ("not json", json.dumps({**good, "current": "yes"}),
                      json.dumps({**good, "action_id": "14:1:2"})):
            with self.subTest(reply=reply):
                self.write_shim(f"echo {shlex.quote(reply)}")
                self.assert_refused(self.exec_("true"), "14:1:1", "malformed_reply")
        self.assertEqual(self.rows("14:1:1"), [])

    def test_a_program_that_cannot_run_exits_as_a_shell_does(self):
        self.assertEqual(self.exec_("no-such-program-276").returncode, 127)
        plain = self.root / "plain"
        plain.write_text("x\n")
        plain.chmod(0o644)
        self.assertEqual(self.exec_(str(plain)).returncode, 126)
        self.assertEqual(self.rows("14:1:1"), [])

    def test_usage_and_helper_errors_exit_two_with_empty_stdout(self):
        not_git = Path(self.enterContext(tempfile.TemporaryDirectory()))
        git_only = self.root / "git-only"
        git_only.mkdir()
        (git_only / "git").symlink_to(shutil.which("git", path=self.env["PATH"]))
        base = ["exec", "--repo-root", str(self.root), "--run-id", self.run_id]
        cases = {
            "no separator": ([*base, "--action-id", "14:1:1", "true"], None),
            "no identity": ([*base, "--", "true"], None),
            "two identities": ([*base, "--action-id", "14:1:1", "--worker-id", "14:1:1:w1",
                                "--", "true"], None),
            "empty argv": ([*base, "--action-id", "14:1:1", "--"], None),
            "unsafe action": ([*base, "--action-id", "..", "--", "true"], None),
            "unsafe worker": ([*base, "--worker-id", "w1", "--", "true"], None),
            "unsafe run": (["exec", "--repo-root", str(self.root), "--run-id", "../x",
                            "--action-id", "14:1:1", "--", "true"], None),
            "not a repository": (["exec", "--repo-root", str(not_git), "--run-id",
                                  self.run_id, "--action-id", "14:1:1", "--", "true"], None),
            "no workflow-state": ([*base, "--action-id", "14:1:1", "--", "true"],
                                  {**self.env, "PATH": str(git_only)}),
        }
        for label, (args, env) in cases.items():
            with self.subTest(case=label):
                done = self.scope(*args, env=env)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertEqual(self.rows("14:1:1"), [])


class CheckLaunchReplyTest(unittest.TestCase):
    def test_only_an_exact_reply_is_believed(self):
        good = {"action_id": "1:1:1", "current": True, "current_action_id": "1:1:1",
                "reason": "current"}
        stale = {**good, "current": False, "current_action_id": "1:1:2",
                 "reason": "superseded_launch"}
        cases = {
            b"not json": "malformed_reply",
            json.dumps([good]).encode(): "malformed_reply",
            json.dumps({**good, "extra": 1}).encode(): "malformed_reply",
            json.dumps({**good, "current": 1}).encode(): "malformed_reply",
            json.dumps({**good, "action_id": "1:1:2"}).encode(): "malformed_reply",
            json.dumps({**good, "reason": "superseded_launch"}).encode(): "malformed_reply",
            json.dumps({**good, "current_action_id": "1:1:2"}).encode(): "malformed_reply",
            json.dumps({**good, "current_action_id": None}).encode(): "malformed_reply",
            json.dumps({**stale, "current_action_id": 7}).encode(): "malformed_reply",
            json.dumps({**stale, "reason": 3}).encode(): "malformed_reply",
            b'{"action_id":"1:1:1","action_id":"1:1:1","current":true,'
            b'"current_action_id":"1:1:1","reason":"current"}': "malformed_reply",
            b'{"action_id":"1:1:1","current":true,"current_action_id":NaN,'
            b'"reason":"current"}': "malformed_reply",
            json.dumps(good).encode(): "current",
            json.dumps(stale).encode(): "superseded_launch",
            json.dumps({**stale, "current_action_id": None,
                        "reason": "unknown_run"}).encode(): "unknown_run",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(check_launch_reply(raw, "1:1:1"), expected)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_scope.py 2>&1 | tail -5`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_tools.launch_scope'`.

- [ ] **Step 3: Write the minimal implementation**

Write `python/agent_tools/launch_scope.py`. It is a thin shell (agent-helpers rule 2): the policy lives in the functions above, and `main` parses, calls and maps errors to exit codes. Its module docstring states the command surface, the exit codes from the root's Global Constraints, and the residual: a process that leaves its session and scrubs its environment is outside the scope (parent D11).

- `check_launch_reply`: load strictly with both canonical hooks, and treat a `ValueError` as `MALFORMED_REPLY`. The reply must be a dict whose keys are exactly `{"action_id", "current", "current_action_id", "reason"}`. `type(current) is bool`. `action_id` equals the queried id. `reason` is a `str`. `current_action_id` is `None` or a `str`. `current is (reason == CURRENT)`. When `current`, `current_action_id == action_id`. Anything else returns `MALFORMED_REPLY`. Otherwise return `reason`.
- `ask_launch`: run `["workflow-state", "check-launch", "--repo-root", R, "--run-id", I, "--action-id", A]` with `capture_output=True, check=False`. An `OSError` raises `LaunchScopeError`. A non-zero exit returns `CHECK_LAUNCH_FAILED`. Otherwise return `check_launch_reply(stdout, A)`.
- `exec_scoped`, in this order:
  1. Call `require_supported_platform()`. Work out the action as `action_id`, or as `worker_action(worker_id)` for a worker. Check both segments, then resolve `directory = launch_directory(registry_root(R), I, action)`. An empty `argv` raises `LaunchScopeError`.
  2. Set `nonce = secrets.token_hex(16)` and `row = directory / f"{nonce}.json"`. Write `{"argv0": argv[0], "nonce": nonce, "pgid": None, "started_at": <UTC now as %Y-%m-%dT%H:%M:%SZ>}` through `write_atomically`, as canonical bytes plus a newline.
  3. Run the check inside a `try` that deletes the row on any exception. For an action, `ask_launch(...) == CURRENT` is positive. For a worker, `ask_worker(R, I, worker_id) == LIVE` is positive, and its `LaunchCommitError` becomes `LaunchScopeError`. A negative answer deletes the row and returns `(3, {"action_id": action, "started": False, "reason": reason})`.
  4. Install the forwarding handlers, then spawn with `subprocess.Popen(list(argv), start_new_session=True, env=...)`. `FileNotFoundError` deletes the row, prints `launch-scope: cannot run <argv0>: <error>` to stderr and returns `(127, None)`. Any other `OSError` does the same with `(126, None)`.
  5. Rewrite the row with `pgid = child.pid`, forward any queued signals, then call `os.waitid(..., WNOWAIT)`.
  6. Read `table = process_table()`. `marked` is every non-zombie pid in `table` with `read_marker(pid) == marker`. Call `survivors = terminate(marked, [child.pid])[1]`, then `rc = child.wait()` and restore the handlers.
  7. With survivors, print the stderr line from the invariants and keep the row. Without them, delete the row. Return `(rc if rc >= 0 else 128 - rc, None)`.
- `main`: split argv at the first `--` before parsing, as `launch_commit.main` does. The parser is `argparse.ArgumentParser(prog="launch-scope", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)`, with a required subparser `exec`. `exec` takes `--repo-root` and `--run-id` (both required), plus a required mutually exclusive group of `--action-id` and `--worker-id`. Calling `exec` without a separator is `parser.error(...)`. Catch `LaunchScopeError`, `LaunchCommitError`, `UnsupportedPlatform` and `ProcessTableError`, print `launch-scope: <error>` to stderr and return 2. Print a refusal as one canonical line. `launch-scope --help` must exit 0 with stdout starting `usage: launch-scope `, which `tests/test_agent_tools_launchers.py` asserts for every launcher.

Add `"launch-scope"` to `commands` in `lib/agent-tools.nix`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_scope.py 2>&1 | tail -5`
Expected: `OK`, with 21 tests.
Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_commit.py 2>&1 | tail -3`
Expected: `OK`. `launch_commit` is consumed, not changed.
Run: `timeout 3600 just agent-installed-skill-tests 2>&1 | tail -8`. It builds first, which import-checks the new module, and then runs `tests/test_agent_tools_launchers.py` over the new `launch-scope` launcher.
Expected: the build succeeds and the output ends `OK`. A missing row or a `--help` that does not print `usage: launch-scope ` fails it.

- [ ] **Step 5: Commit**

Use `launch-commit` when your prompt carries a `Lifecycle worker:` line.

```bash
git add python/agent_tools/launch_scope.py lib/agent-tools.nix tests/test_launch_scope.py
git commit -m "feat(launch-scope): exec a launch's command in a scoped session and reap its leftovers (#276)"
```
