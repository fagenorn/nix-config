# Task 2: The builder CLI helper runs workflow-state in-process

This task implements spec § The builder CLI helper (D1, D2) and test seam 2 (D6). `BuilderHarness.cli` keeps its signature and return shape, but it calls Task 1's `run_script` in bytes mode instead of starting `python workflow-state.py`. Every class that inherits the helper changes transport with it: the builder, loop, contract and worktree classes, ship delivery, delivered control and its custody and cutover descendants (the head generation only), the migration driver, and the helper-backed artifact-budget and workflow-state classes. None of those modules' files change. The other process launches in these modules stay real processes (D1).

**Files:**
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`

**Interfaces:**
- Consumes: Task 1's `run_script(script, args, *, env, input=None, cwd=None, text=True)` from `home/common/agent-skills/tests/_inprocess_cli.py`. Also `recorded_spawns()`, a context manager that yields the list of process-creation audit events raised inside its block, defined in `test_workflow_state.py` (498 D5). This file already loads that module by path as `delivery_workflow_lifecycle_harness`, and a package import of `test_workflow_state` from here would be circular (D6).
- Produces: `BuilderHarness.cli(*args, stdin=None, ok=True, cwd=None) -> subprocess.CompletedProcess`, unchanged. Its `stdout` and `stderr` are bytes, and `ok` asserts exit 0 with the decoded stderr as the message. The module-level name `LifecycleHarness` stays importable, and `recorded_spawns` becomes a module-level name.

**Invariants:**
- No call through `BuilderHarness.cli` starts a process for workflow-state itself.
- `stdin` reaches the script as its exact stdin bytes, and `cwd`, when given, is the script's working directory. The process directory is the same after the call.
- The environment the helper passes is byte-for-byte today's: `{**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}`. `PYTHONDONTWRITEBYTECODE` stays exactly as found (D8).
- `DeliveryAdmissionTest`'s direct `workflow-state.py` runs, `Cutover.cli`'s base generation and every `artifact_budget.py` validation stay real processes (D1). `test_control_cutover.py` and every other module except this one are unchanged.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_delivery_workflow.py`, replace the two lines that load the lifecycle harness:

```python
LifecycleHarness = load(Path(__file__).with_name("test_workflow_state.py"),
                        "delivery_workflow_lifecycle_harness").LifecycleHarness
```

with:

```python
_LIFECYCLE = load(Path(__file__).with_name("test_workflow_state.py"),
                  "delivery_workflow_lifecycle_harness")
LifecycleHarness, recorded_spawns = _LIFECYCLE.LifecycleHarness, _LIFECYCLE.recorded_spawns
```

Then insert this class directly before `class DeliveryBuilderTest(BuilderHarness, unittest.TestCase):`:

```python
class BuilderTransportTest(BuilderHarness, unittest.TestCase):
    """Issue 500 D1, D6: the builder helper runs workflow-state in this process, in the
    working directory and with the stdin bytes it is given."""

    def test_the_helper_starts_no_process_and_honours_cwd_and_stdin(self):
        self.project()
        directory = os.getcwd()
        malformed = b'{"issue": 171,'
        try:
            json.loads(malformed.decode("utf-8"))
        except json.JSONDecodeError as error:
            decoder = str(error)
        with recorded_spawns() as spawns:
            minted = self.cli("init-run", "--repo-root", self.root.name, "--creation-key",
                              "issue-500-transport", "--now", NOW, cwd=self.root.parent)
            refused = self.cli("build-delivery", "--repo-root", self.root, "--kind",
                               "contract", "--input", "-", stdin=malformed, ok=False)
        self.assertEqual(spawns, [])
        run_id = json.loads(minted.stdout)["run_id"]
        self.assertTrue((self.root / ".superpowers/workflows" / run_id / "state.json").is_file())
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, b"", f"workflow-state: invalid builder input JSON: {decoder}\n".encode()))
        self.assertEqual(os.getcwd(), directory)
```

Why each argument (keep them): `init-run` gets the root's bare name with `cwd` set to the root's parent. If `cwd` were dropped, the name would resolve under the test process's directory, where it does not exist, and the CLI would refuse (`repository root does not exist`) without writing into the checkout (D6). `build-delivery` refuses a relative `--repo-root` before it reads stdin, so it gets the absolute root. The malformed bytes are a truncated JSON object, so a dropped stdin produces a different decoder message.

- [ ] **Step 2: Run the test and watch it fail**

Run (focused test form, timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k BuilderTransportTest 2>&1 | tail -6'`
Expected: `FAILED (failures=1)` with `AssertionError: Lists differ: ['subprocess.Popen', 'subprocess.Popen'] != []`, because the base helper starts one child per call.

- [ ] **Step 3: Write the minimal implementation**

1. Add `from ._inprocess_cli import run_script` to the package-relative imports, directly before `from .test_resolve_project import git, make_home, make_project_root, run as run_resolver, source_contract`. This is a plain package import, not a by-path load (agent-helpers rule 3, D2).
2. In `BuilderHarness.cli`, replace the `subprocess.run(...)` call with:

```python
        completed = run_script(
            WORKFLOW, args, input=stdin, cwd=cwd, text=False,
            env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})
```

Keep the `if ok:` assertion and the `return completed` exactly as they are. Keep the module's `subprocess` and `sys` imports, which `DeliveryAdmissionTest` and others still use. Change nothing else in the file.

- [ ] **Step 4: Verify**

All from the worktree root, through `launch-scope exec`:
1. The Step 2 command. Expected: `Ran 1 test` and `OK`.
2. The regression net, which pins the forwarding (focused test form): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py -k test_ac3_a_session_in_another_attempts_worktree_is_refused_before_any_write 2>&1 | tail -6'`. Expected: `OK`. This fence reads `os.getcwd()`, so it fails if `cwd` is dropped.
3. Every module that inherits the helper (timeout 3600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_ship_delivery.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_control_decisions.py home/common/agent-skills/tests/test_delivery_sealing.py home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -16'`. Expected: a final line `suite-runner: summary members=10 passed=10 failed=0 …`. If a module fails, read its `end` line and its log, and fix the cause in this task's file. Never edit the failing module (D1).
4. The Coverage gate (Global Constraints). Expected: `COVERAGE-GATE-OK base 3575 head 3578 test ids`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(issue-500): run the builder CLI helper in-process" -m "<the session's trailer lines>"
```
