# Task 3: `launch-commit` command and acceptance test

**Files:**
- Create: `python/agent_tools/launch_commit.py`
- Modify: `lib/agent-tools.nix` (add the `"launch-commit"` row to `commands`, alphabetically after `"diff-scope"`)
- Modify: `justfile` (add `tests/test_launch_commit.py` to the `agent-workflow-tests` list, after `tests/test_agent_tools_siblings.py`)
- Test: `tests/test_launch_commit.py`

**Interfaces:**
- Consumes (Task 1): `workflow-state check-worker --repo-root R --run-id I --worker-id W` printing exactly `{"worker_id", "live", "current_action_id", "reason"}` at exit 0. Also the harness helpers `LifecycleHarness.register_worker`, `release_worker`, `spawn`, `resume` and `init_run`.
- Produces:
  - CLI: `launch-commit --repo-root <ledger_repo_root> --run-id <run> --worker-id <id> -- <git commit args>` (`prog="launch-commit"`).
  - `check_reply(stdout: bytes, worker_id: str) -> str` returns the reply's `reason` when `live` is false, `"live"` when it is true, or `"malformed_reply"`.
  - `ask_worker(repo_root: str, run_id: str, worker_id: str) -> str` runs `workflow-state check-worker` by command name on `PATH` and returns `"check_worker_failed"` on a non-zero exit, otherwise `check_reply(...)`. If the command cannot be started (`OSError`), it raises `LaunchCommitError`.
  - `fenced_commit(repo_root, run_id, worker_id, git_args: Sequence[str]) -> tuple[int, dict | None]` returns `(git_returncode, None)` after running `git commit *git_args` in the current directory with inherited stdio. When the reason is not `"live"` it returns `(3, {"worker_id": worker_id, "committed": False, "reason": reason})` without running git.
  - `main(argv) -> int` prints a refusal as one line of `json.dumps(value, sort_keys=True, separators=(",", ":"))` on stdout. A `LaunchCommitError` exits 2 with one stderr line.

**Invariants:**
- No `git` process runs unless `check-worker` answered `live: true` for this exact `worker_id` (per D5, D12).
- A strict reply load composes `agent_tools.canonical.reject_duplicate_keys` (as `object_pairs_hook`) and `agent_tools.canonical.reject_nonfinite_literal` (as `parse_constant`), so `NaN`, `Infinity` and `-Infinity` anywhere in the reply make it `malformed_reply`. A reply counts as well-formed only when it is a JSON object with exactly the four keys, a boolean `live` (`type(...) is bool`), `worker_id` equal to the asked id, a string `reason`, `current_action_id` that is `None` or a `str`, and `live is (reason == "live")`. The tests add malformed **positive** replies (`"live": true, "reason": "live"` with `"current_action_id": NaN`, with `"current_action_id": 7`, and with a duplicated key) to the `check_reply` cases and assert `malformed_reply` and, through `fenced_commit`, that no commit is created.
- argv is split at the **first** `--`: everything before it goes to argparse, and everything after it goes verbatim to `git commit`. A missing `--` is a usage error (exit 2). `--help` works without `--`.
- The module never edits `sys.path`, never uses `importlib` and never reads `__file__` (agent-helpers rule 3).
- The module docstring states the residual window: a supersession landing between the check and the commit is not caught, and the fence narrows the window to one call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launch_commit.py`:

```python
"""launch-commit: a registered worker commits only while its launch is live (#222).

The ledger is driven through the lifecycle suites' harness, loaded from its
source file (per D14). A PATH shim runs the source workflow-state script, which
is how the command finds `workflow-state` by name.
"""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

from agent_tools.launch_commit import check_reply

ROOT = Path(__file__).parents[1]
HARNESS_SOURCE = ROOT / "home/common/agent-skills/tests/test_workflow_state.py"
WORKFLOW = ROOT / "home/common/agent-skills/scripts/workflow-state.py"


def _harness():
    spec = importlib.util.spec_from_file_location("launch_commit_harness", HARNESS_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LifecycleHarness


LifecycleHarness = _harness()
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


class LaunchCommitTest(LifecycleHarness, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.shims = self.root / "shims"
        self.shims.mkdir()
        self.write_shim(f"exec {shlex.quote(sys.executable)} "
                        f"{shlex.quote(str(WORKFLOW))} \"$@\"")
        self.env = {**self.cli_env, **HERMETIC_GIT,
                    "PATH": f"{self.shims}{os.pathsep}{os.environ['PATH']}"}
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", "base.txt")
        self.git("commit", "-q", "-m", "base")

    def write_shim(self, body):
        shim = self.shims / "workflow-state"
        shim.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        shim.chmod(0o755)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              text=True, check=True, env=self.env).stdout.strip()

    def launch_commit(self, worker_id, *git_args, run_id=None, env=None, separator=True):
        argv = [sys.executable, "-m", "agent_tools.launch_commit",
                "--repo-root", str(self.root),
                "--run-id", self.run_id if run_id is None else run_id,
                "--worker-id", worker_id, *(["--"] if separator else []), *git_args]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True,
                              check=False, env=self.env if env is None else env)

    def stage(self, name):
        (self.repo / name).write_text(name + "\n")
        self.git("add", name)

    def spawn_worker(self):
        self.init_run()
        self.assertEqual(self.spawn(issue=14, worktree=str(self.root / "wt-14"))["id"],
                         "14:1:1")
        return self.register_worker(action_id="14:1:1",
                                    now="2026-08-13T20:01:00Z")["worker_id"]

    def assert_refused(self, completed, worker, reason, head):
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout),
                         {"worker_id": worker, "committed": False, "reason": reason})
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_a_worker_superseded_between_dispatch_and_commit_commits_nothing(self):
        worker = self.spawn_worker()
        self.stage("orphan.txt")
        head = self.git("rev-parse", "HEAD")
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"),
                              now="2026-08-13T20:06:00Z", owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        self.assert_refused(self.launch_commit(worker, "-q", "-m", "orphan work"),
                            worker, "superseded_launch", head)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "orphan.txt")

    def test_a_live_worker_commits_through_git(self):
        worker = self.spawn_worker()
        self.stage("work.txt")
        head = self.git("rev-parse", "HEAD")
        landed = self.launch_commit(worker, "-q", "-m", "live work")
        self.assertEqual(landed.returncode, 0, landed.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD^"), head)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "live work")

    def test_git_failure_passes_through(self):
        worker = self.spawn_worker()
        nothing = self.launch_commit(worker, "-q", "-m", "empty")
        self.assertNotIn(nothing.returncode, (0, 3))

    def test_released_and_unknown_run_are_refusals(self):
        worker = self.spawn_worker()
        self.stage("late.txt")
        head = self.git("rev-parse", "HEAD")
        self.assert_refused(self.launch_commit(worker, "-m", "x", run_id="no-such-run"),
                            worker, "unknown_run", head)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:02:00Z")
        self.assert_refused(self.launch_commit(worker, "-m", "x"), worker, "released", head)

    def test_a_failed_or_malformed_check_refuses(self):
        worker = self.spawn_worker()
        self.stage("x.txt")
        head = self.git("rev-parse", "HEAD")
        self.write_shim("exit 2")
        self.assert_refused(self.launch_commit(worker, "-m", "x"), worker,
                            "check_worker_failed", head)
        self.write_shim(f"echo '{{\"worker_id\":\"{worker}\",\"live\":true}}'")
        self.assert_refused(self.launch_commit(worker, "-m", "x"), worker,
                            "malformed_reply", head)

    def test_usage_errors_and_a_missing_helper_exit_two(self):
        worker = self.spawn_worker()
        self.stage("y.txt")
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.launch_commit(worker, separator=False).returncode, 2)
        empty = self.root / "empty-path"
        empty.mkdir()
        missing = self.launch_commit(worker, "-m", "x",
                                     env={**self.env, "PATH": str(empty)})
        self.assertEqual((missing.returncode, missing.stdout), (2, ""))
        self.assertEqual(self.git("rev-parse", "HEAD"), head)


class CheckReplyTest(unittest.TestCase):
    def test_only_an_exact_reply_is_believed(self):
        good = {"worker_id": "1:1:1:w1", "live": True, "current_action_id": "1:1:1",
                "reason": "live"}
        cases = {
            b"not json": "malformed_reply",
            json.dumps({**good, "extra": 1}).encode(): "malformed_reply",
            json.dumps({**good, "live": 1}).encode(): "malformed_reply",
            json.dumps({**good, "worker_id": "1:1:1:w2"}).encode(): "malformed_reply",
            json.dumps({**good, "reason": "released"}).encode(): "malformed_reply",
            b'{"worker_id":"1:1:1:w1","worker_id":"1:1:1:w1","live":true,'
            b'"current_action_id":"1:1:1","reason":"live"}': "malformed_reply",
            b'{"worker_id":"1:1:1:w1","live":true,"current_action_id":NaN,'
            b'"reason":"live"}': "malformed_reply",
            json.dumps({**good, "current_action_id": 7}).encode(): "malformed_reply",
            json.dumps(good).encode(): "live",
            json.dumps({**good, "live": False, "reason": "superseded_launch"}).encode():
                "superseded_launch",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(check_reply(raw, "1:1:1:w1"), expected)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launch_commit.py 2>&1 | tail -3`
Expected: FAIL. `ModuleNotFoundError: No module named 'agent_tools.launch_commit'` (this is the acceptance criterion's failure at base).

- [ ] **Step 3: Implement**

Write `python/agent_tools/launch_commit.py` with the interfaces above. `ask_worker` runs `subprocess.run(["workflow-state", "check-worker", "--repo-root", repo_root, "--run-id", run_id, "--worker-id", worker_id], capture_output=True, check=False)`. `fenced_commit` runs `subprocess.run(["git", "commit", *git_args], check=False).returncode` with no capture. `main` splits argv at the first `"--"`, parses the head with `argparse.ArgumentParser(prog="launch-commit", description=__doc__)` (all three options required), and calls `parser.error(...)` when there is no `--`. Add `"launch-commit"` to `commands` in `lib/agent-tools.nix`, and the test file to the `justfile` recipe.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launch_commit.py tests/test_agent_tools_siblings.py 2>&1 | tail -3`
Expected: `OK`.
Run: `just build 2>&1 | tail -3`
Expected: success, with the `pythonImportsCheck` of the new module passing and the command row evaluating. Optionally run `just agent-installed-skill-tests` when the installed layout is available.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/launch_commit.py lib/agent-tools.nix justfile tests/test_launch_commit.py
git commit -m "feat(agent-tools): launch-commit fences worker commits on check-worker (#222)"
```

Decisions: per D5, D9, D12, D14.
