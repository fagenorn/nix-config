# Task 2: Both launch sites pass the members' environment; a traced commit under the runner starts no maintenance child

Spec § Solution, § Decisions (**The members' environment**, **Reach**, **The README contract**), § Test seams items 2 and 3. Rests on D1, D3, D4 and D5. After this task every member, in serial and in parallel mode, runs with `member_environment(os.environ)` (Task 1), so a commit in a test's repository starts no `git maintenance` child. The runner's README paragraph states the entries, their composition and their reach.

**Files:**
- Modify: `python/agent_tools/suite_runner.py` (`run_suite`, `_run_serial`, `_run_parallel`)
- Modify: `python/README.md` (`## \`agent-workflow-tests\` runner`, its one paragraph)
- Test: `tests/test_suite_runner.py`

**Interfaces:**
- Consumes (Task 1): `suite_runner.member_environment(parent: Mapping[str, str]) -> dict[str, str]`, and the test module's `without_command_git_config(environ: Mapping[str, str]) -> dict[str, str]`. Unchanged: `RunnerCase` (`setUp`'s `self.work`, `member`, `environment(cap, total, extra)`, `run_suite(*args, cap, total, env)`).
- Produces: `_run_serial(members: Sequence[str], environment: Mapping[str, str], out: _Output) -> list[MemberResult]` and `_run_parallel(members: Sequence[str], jobs: int, environment: Mapping[str, str], out: _Output) -> list[MemberResult | None]`. `run_suite(members, *, jobs, out) -> int` and `main(argv)` keep their signatures (D5).

**Invariants:**
- `member_environment(os.environ)` is computed once per `run_suite` call, and both `subprocess.Popen` calls pass that one mapping as `env=` (D1). Nothing writes to `os.environ`.
- Every other `Popen` argument, the output format, the SIGINT handling and the exit statuses are unchanged; the 16 base cases keep passing unedited.
- The new end-to-end cases build every environment through `without_command_git_config`, so the outer runner's entries never reach their members (D4).
- No case asserts on `maintenance.lock` (D4).

- [ ] **Step 1: Write the failing tests**

In `tests/test_suite_runner.py`:

1. Add `import json` directly before `import os`.
2. Directly before `RUNNER_LINE = re.compile(`, add:

```python
# A shell member that commits once in a fresh repository of its own, with
# global and system git configuration nulled and a fixed identity. Only the
# commit is traced, to the absolute file $SUITE_RUNNER_TEST_TRACE (issue 496).
COMMIT_MEMBER = textwrap.dedent('''\
    set -eu
    export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    export GIT_AUTHOR_NAME=Suite GIT_AUTHOR_EMAIL=suite@example.invalid
    export GIT_COMMITTER_NAME=Suite GIT_COMMITTER_EMAIL=suite@example.invalid
    repo=$(mktemp -d)
    trap 'rm -rf "$repo"' EXIT
    cd "$repo"
    git init -q -b main
    echo probe > probe.txt
    git add probe.txt
    GIT_TRACE2_EVENT="$SUITE_RUNNER_TEST_TRACE" git commit -q -m probe
''')

```

3. Directly before `class RecipeWiringTest(unittest.TestCase):` (after Task 1's `MemberEnvironmentTest`), add:

```python
class GitMaintenanceTest(RunnerCase):
    """A commit under the runner starts no `git maintenance` child (issue 496),
    against a control that shows the same commit outside the runner does."""

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return without_command_git_config(super().environment(cap, total, extra))

    def trace_events(self) -> list[dict]:
        return [json.loads(line)
                for line in self.trace.read_text(encoding="utf-8").splitlines() if line]

    def setUp(self) -> None:
        super().setUp()
        self.trace = self.work.parent / "trace.jsonl"
        self.commit = self.member("commit.sh", COMMIT_MEMBER)

    def commit_under_the_runner(self, jobs: str) -> None:
        result = self.run_suite("--jobs", jobs, self.commit,
                                env={"SUITE_RUNNER_TEST_TRACE": str(self.trace)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.trace_events()
        self.assertTrue(any(event["event"] == "start" and "commit" in event["argv"]
                            for event in events), events)
        self.assertEqual([event["argv"] for event in events
                          if "maintenance" in event.get("argv", [])], [])

    def test_a_commit_in_serial_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("1")

    def test_a_commit_in_parallel_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("2")

    def test_the_same_commit_outside_the_runner_starts_a_maintenance_child(self):
        # maintenance.autoDetach=false runs the maintenance child in the
        # foreground, so it has finished when the commit returns.
        environment = {**self.environment(1, 1, {"SUITE_RUNNER_TEST_TRACE": str(self.trace)}),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "maintenance.autoDetach",
                       "GIT_CONFIG_VALUE_0": "false"}
        result = subprocess.run(
            ["bash", self.commit], cwd=self.work, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        children = [event["argv"] for event in self.trace_events()
                    if event["event"] == "child_start"]
        self.assertTrue(any(argv[:4] == ["git", "maintenance", "run", "--auto"]
                            for argv in children), children)


```

`--jobs 2` with one member takes the parallel launch site, so each commit case fails only for its own site.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py -k GitMaintenanceTest 2>&1 | grep -E "^(FAIL|ERROR):|^Ran|^OK|^FAILED|maintenance"'`
Expected: `Ran 3 tests` and `FAILED (failures=2)`. The two failures are the serial and parallel commit cases, each listing an argv that begins `['git', 'maintenance', 'run', '--auto'` (on git 2.51 it ends `'--quiet', '--detach']`). The control passes.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/suite_runner.py`:

1. Add `import os` directly after `import argparse`.
2. `_run_serial` gains the parameter `environment: Mapping[str, str]` between `members` and `out`, and its launch becomes `subprocess.Popen(member_command(member), env=environment)`.
3. `_run_parallel` gains `environment: Mapping[str, str]` between `jobs` and `out`, and its `subprocess.Popen(...)` call gains `env=environment` (its `stdin`, `stdout` and `stderr` arguments stay as they are).
4. In `run_suite`, append to the docstring's last paragraph the sentence `Every member runs with \`member_environment(os.environ)\`, computed once.`, compute `environment = member_environment(os.environ)` directly after `output = _Output(out)`, and pass it: `_run_serial(members, environment, output)` and `_run_parallel(members, jobs, environment, output)`.

In `python/README.md`, in the `agent-workflow-tests` runner paragraph, replace exactly this sentence:

```text
The runner runs each member in its own process from its working directory, with the recipe's environment: a `.py` member as `python -m unittest -v <path>`, and a `.sh` member as `bash <path>`.
```

with exactly this text, keeping it inside the same paragraph:

```text
The runner runs each member in its own process from its working directory, with the recipe's environment plus two git configuration entries: a `.py` member as `python -m unittest -v <path>`, and a `.sh` member as `bash <path>`. The entries, `maintenance.auto=false` and `gc.auto=0` (issue 496), are appended to `GIT_CONFIG_PARAMETERS` in the form `git -c` exports (`member_environment`), because otherwise a commit or a fetch in a test's repository starts a detached `git maintenance run --auto`, which creates `.git/objects/maintenance.lock` while the test reads that repository. Every git command that inherits a member's environment, at any depth, reads them as if given `git -c maintenance.auto=false -c gc.auto=0`: they win over an inherited entry, a test's own `GIT_CONFIG_COUNT` entry and any config file for the same key, a test's other count entries still apply, and a `git -c` option a command adds comes after them and wins. They do not reach a process started with an environment built from scratch or with its own `GIT_CONFIG_PARAMETERS`, nor the receive-pack of a push to a local repository, which git starts with every `GIT_CONFIG_*` variable removed, so that receiving repository still runs automatic maintenance.
```

Every other sentence of the paragraph, the closing shared-state rule included, stays as written.

- [ ] **Step 4: Verify**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py -k GitMaintenanceTest -k MemberEnvironmentTest 2>&1 | tail -4'`
Expected: `Ran 9 tests` and `OK`.

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py 2>&1 | tail -4'`
Expected: `Ran 25 tests` and `OK`.

Run the module as a suite member, so its own process carries the suite's entries and the strip is load-bearing (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 2 tests/test_suite_runner.py 2>&1 | tail -1'`
Expected: `suite-runner: summary members=1 passed=1 failed=0 jobs=2 wall=…`.

Run:

```bash
python3 - <<'EOF'
from pathlib import Path
text = Path("python/README.md").read_text(encoding="utf-8")
assert "with the recipe's environment:" not in text, "old sentence still present"
assert text.count("with the recipe's environment plus two git configuration entries:") == 1
assert text.count("(`member_environment`)") == 1
assert text.count("never by a serial-exemption list, a retry or a lock.") == 1
print("readme-ok")
EOF
```

Expected: `readme-ok`.

AC2 is read from CI at the PR head; sdd's final gate runs `just agent-workflow-tests` on the final head.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py python/README.md tests/test_suite_runner.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(suite-runner): run members with git maintenance off (issue 496)" -m "<session trailer lines>"
```
