# Task 2: workflow-state validates in-process and starts no child

This task implements spec § Loading the module in-process (D2, with the resolved target per D7), § One invocation helper and its outcomes (D1, D4), § Documentation, and the second and third seams of § Test seams (D5). `workflow-state` loads `artifact_budget` once per process, from the resolved file the CLI runs, and both of its call sites run through one in-process helper. Each call site keeps its verdict mapping and its error texts. No validation starts a child process, and the installed layout no longer needs the `artifact-budget` wrapper.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/default.nix`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (Task 1): `artifact_budget.Outcome(exit_code: int, stdout: bytes, stderr: str)` and `artifact_budget.invoke(argv: Sequence[str], read_stdin: Callable[[int], bytes]) -> Outcome`. From the base: `WorkflowError`; `artifact_budget_paths()` and its inner `trusted_policy`; `artifact_budget_validate(command, input_path=None, *, boundary=None, input_bytes=None)`; `validate_durable_detail(repo_root, report_path)`; `phase_notes_maximum()`, which reads only the policy half of `artifact_budget_paths()`. In the tests: `LifecycleHarness` (`init_run`, `spawn`, `finish`, `merged_result`, `write_delivery_detail`, `read_state`, `state_path`, `root`), `ARTIFACT_BUDGET`, `BUDGET_POLICY` and `contextlib`.
- Produces:
  - `artifact_budget_paths() -> tuple[Path, Path | None]`: the module file and the resolved policy (or None). It never raises.
  - `_artifact_budget()`: the loaded module, else `WorkflowError("artifact-budget module: <cause>")`.
  - `artifact_budget_invoke(argv: list[str], input_bytes: bytes = b"") -> Any`, which returns an `Outcome`.
  - In the tests: `SPAWN_EVENTS`, `recorded_spawns()` and `InProcessArtifactBudgetTest`.

**Invariants:**
- No artifact-budget validation starts a process. `workflow-state.py` keeps exactly two `subprocess.run(` calls: the `resolve-project` run and `_worktree_git`.
- Every call site keeps the same accept/refuse decision, accepted value (the parsed canonical stdout, keys sorted), exit code and `workflow-state:` line (D1).
- The module loads at most once per process, lazily, from `artifact_budget_paths()[0].resolve(strict=True)`. It is registered as `sys.modules["_workflow_state_artifact_budget"]` before it executes and removed again if loading fails (D2, D7). That name differs from the `_artifact_budget_delivery_model` and `_workflow_delivery_model` names the module and the delivery runtime register.
- A load failure prints `workflow-state: artifact-budget module: <cause>` and exits 2. An `Exception` that escapes `invoke` becomes `Outcome(1, b"", <formatted traceback>)`. A `BaseException` that is not an `Exception` propagates (D4).
- `phase_notes_maximum()`, and every subcommand that never validates, never loads the module.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_state.py`, make three edits.

1. Directly before `class LifecycleHarness:`, after the `INPROCESS_CLI = load_source_module(...)` assignment, add:

```python
# The audit events that start a process (issue 498 D5).
SPAWN_EVENTS = frozenset({"subprocess.Popen", "os.posix_spawn", "os.exec", "os.fork",
                          "os.spawn", "os.system"})
# The open recording window's events, or None while no window is open. An audit
# hook cannot be removed, so one is added once per process and records only
# inside a window.
_SPAWN_WINDOW = None
_SPAWN_HOOKED = False


def _record_spawn(event, _arguments):
    if _SPAWN_WINDOW is not None and event in SPAWN_EVENTS:
        _SPAWN_WINDOW.append(event)


@contextlib.contextmanager
def recorded_spawns():
    """The process-creation audit events raised inside the block, in order."""
    global _SPAWN_WINDOW, _SPAWN_HOOKED
    if not _SPAWN_HOOKED:
        sys.addaudithook(_record_spawn)
        _SPAWN_HOOKED = True
    events = []
    _SPAWN_WINDOW = events
    try:
        yield events
    finally:
        _SPAWN_WINDOW = None
```

2. Replace the whole `ArtifactBudgetPolicyResolutionTest` class with the version below. The fixture no longer installs the wrapper. It links the module to a stand-in store file, and the probe records process-creation events while it validates.

```python
class ArtifactBudgetPolicyResolutionTest(unittest.TestCase):
    """Cover the installed layout, where the policy and the module are home-manager
    symlinks and no `artifact-budget` wrapper is installed (issue 498 D2, D5, D7)."""

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_installed_symlinked_policy_validates_a_terminal_result(self):
        scripts = Path(__file__).parents[1] / "scripts"
        policy = Path(__file__).parents[1] / "artifact-budget-policy.json"
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            binaries = home / ".agents/bin"
            library = home / ".agents/lib/python"
            share = home / ".agents/share"
            store = home / "store"
            for directory in (binaries, library, share, store):
                directory.mkdir(parents=True)
            installed_script = binaries / "workflow-state.py"
            installed_script.write_bytes((scripts / "workflow-state.py").read_bytes())
            # home-manager links the module to its store file (issue 498 D7).
            (store / "artifact_budget.py").write_bytes(
                (scripts / "artifact_budget.py").read_bytes()
            )
            (library / "artifact_budget.py").symlink_to(store / "artifact_budget.py")
            (library / "workflow_delivery.py").write_bytes(
                (scripts / "workflow_delivery.py").read_bytes()
            )
            shutil.copytree(scripts / "delivery_model", library / "delivery_model")
            # home-manager installs the policy as a store symlink, never a copy.
            (share / "artifact-budget-policy.json").symlink_to(policy)

            probe = (
                "import importlib.util, json, sys\n"
                f"SPAWN_EVENTS = {sorted(SPAWN_EVENTS)!r}\n"
                "spawned = []\n"
                "spec = importlib.util.spec_from_file_location('ws', sys.argv[1])\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "_, resolved = module.artifact_budget_paths()\n"
                "sys.addaudithook(lambda event, _: spawned.append(event)\n"
                "                 if event in SPAWN_EVENTS else None)\n"
                "summary = module.terminal_result(1320, 'stopped', 'attempt deadline expired')\n"
                "print(json.dumps({'policy': str(resolved), 'state': summary['state'],\n"
                "                  'spawned': spawned,\n"
                "                  'module': module._artifact_budget().__file__}))\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", probe, str(installed_script)],
                capture_output=True, text=True, check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = json.loads(completed.stdout)
            self.assertEqual(observed["state"], "stopped")
            # The explicit --policy argument must name the resolved regular file:
            # artifact-budget refuses a symlink passed as --policy.
            self.assertFalse(Path(observed["policy"]).is_symlink())
            self.assertEqual(
                Path(observed["policy"]).resolve(), policy.resolve()
            )
            # Validated in this process, from the link's store target: bytecode
            # is never cached under the link's own name (issue 498 D5, D7).
            self.assertEqual(observed["spawned"], [])
            self.assertEqual(Path(observed["module"]), (store / "artifact_budget.py").resolve())
            self.assertEqual(sorted((library / "__pycache__").glob("artifact_budget.*")), [])
```

3. Directly after that class, before `if DeliveredControlHarness is not None:`, add:

```python
class InProcessArtifactBudgetTest(LifecycleHarness, unittest.TestCase):
    """Issue 498 AC1, D1, D5: the legacy `finish` validates its result file, a
    `present` detail and an `unpublished` detail without starting a process, and
    reaches the CLI's verdict on the same bytes and policy."""

    def cli_exit(self, *argv, stdin=b""):
        """The exit code of the artifact-budget CLI, run as a child process outside
        any recording window, on `argv` and the source policy."""
        return subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), *map(str, argv),
             "--policy", str(BUDGET_POLICY.resolve())],
            input=stdin, capture_output=True, check=False).returncode

    def finish_without_spawning(self, attempt, result, *, ok):
        with recorded_spawns() as spawned:
            outcome = self.finish(attempt, result, ok=ok)
        self.assertEqual(spawned, [])
        return outcome

    def assert_refused(self, completed, line):
        self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                         (2, "", line))

    def test_a_result_file_is_validated_in_process_with_the_clis_verdict(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        accepted = self.merged_result()
        refused = {**accepted, "discussion_items": ["not durably moved"]}
        verdicts = [self.cli_exit("validate-report", "--boundary", "ship-summary", "--input", "-",
                                  stdin=json.dumps(result).encode("utf-8"))
                    for result in (refused, accepted)]
        self.assertEqual(verdicts, [2, 0])
        self.assert_refused(
            self.finish_without_spawning(attempt, refused, ok=False),
            "workflow-state: artifact-budget validate-report rejected the ship-summary boundary\n")
        self.finish_without_spawning(attempt, accepted, ok=True)
        self.assertEqual(self.read_state()["issues"]["14"]["outcome"], accepted)

    def test_a_present_detail_is_checked_in_process_with_the_clis_verdict(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        paths = (".superpowers/issue-delivery/14/run-1/ship-review-refused.json",
                 ".superpowers/issue-delivery/14/run-1/ship-review-a.json")
        self.write_delivery_detail(paths[0]).write_text("{}", encoding="utf-8")
        self.write_delivery_detail(paths[1])
        refused, accepted = ({**self.merged_result(), "detail_state": "present",
                              "report_path": path, "notes": f"details: {path}"}
                             for path in paths)
        verdicts = [self.cli_exit("check", "--kind", "review-package",
                                  "--root", self.root.resolve() / path, "--format", "json")
                    for path in paths]
        self.assertEqual(verdicts, [2, 0])
        self.assert_refused(
            self.finish_without_spawning(attempt, refused, ok=False),
            "workflow-state: durable detail is not a checker-valid review package\n")
        self.finish_without_spawning(attempt, accepted, ok=True)
        self.assertEqual(self.read_state()["issues"]["14"]["outcome"], accepted)

    def test_an_unpublished_detail_is_validated_in_process_with_the_clis_verdict(self):
        self.init_run()
        worktree = self.root / "wt-a"
        attempt = self.spawn(issue=14, worktree=worktree)["attempt"]
        relative = ".superpowers/ship-review/14/retained-detail.json"
        retained = worktree / relative
        retained.parent.mkdir(parents=True)
        refused = '{"interface_version":1,"findings":[]}'
        accepted = ('{"interface_version":1,"findings":[{"axis":"ship","ruling":null,'
                    '"severity":"Minor","status":"minor","text":"kept"}]}')
        result = {**self.merged_result(), "state": "stopped", "pr_url": None,
                  "merge_sha": None, "issue_closed": False,
                  "detail_state": "unpublished", "report_path": relative,
                  "notes": f"publication failed; retained: {relative}"}
        verdicts = []
        for payload in (refused, accepted):
            retained.write_text(payload, encoding="utf-8")
            verdicts.append(self.cli_exit("validate-detail-input", "--input",
                                          worktree.resolve() / relative))
        self.assertEqual(verdicts, [2, 0])
        retained.write_text(refused, encoding="utf-8")
        self.assert_refused(
            self.finish_without_spawning(attempt, result, ok=False),
            "workflow-state: artifact-budget validate-detail-input rejected the detail input\n")
        retained.write_text(accepted, encoding="utf-8")
        self.finish_without_spawning(attempt, result, ok=True)
        outcome = self.read_state()["issues"]["14"]["outcome"]
        self.assertEqual((outcome["state"], outcome["detail_state"], outcome["report_path"]),
                         ("stopped", "unpublished", relative))

    def test_an_exception_escaping_the_validator_is_refused_as_a_crashed_child_was(self):
        # A CLI child that crashed exited 1 with empty stdout, which the base mapped to
        # the boundary's refusal. No wire-bounded input crashes the validator on the
        # supported interpreters, so the seam is the loaded module's `invoke`
        # (issue 498 D4, D8).
        workflow = load_source_module(SCRIPT, "workflow_state_issue_498_crash")
        module = workflow._artifact_budget()
        wire = json.dumps(self.merged_result()).encode("utf-8")
        argv = ["validate-report", "--boundary", "ship-summary", "--input", "-"]
        with recorded_spawns() as spawned, \
                mock.patch.object(module, "invoke", side_effect=RecursionError("deep")):
            outcome = workflow.artifact_budget_invoke(argv, wire)
            with self.assertRaises(workflow.WorkflowError) as caught:
                workflow.artifact_budget_validate(
                    "validate-report", boundary="ship-summary", input_bytes=wire)
        self.assertEqual(spawned, [])
        self.assertEqual((outcome.exit_code, outcome.stdout), (1, b""))
        self.assertIn("RecursionError: deep", outcome.stderr)
        self.assertEqual(str(caught.exception),
                         "artifact-budget validate-report rejected the ship-summary boundary")
```

The fourth test pins D4's exception mapping, which the three `finish` cases never reach: removing the `except Exception` arm of `artifact_budget_invoke` turns it red. The legacy `finish` covers all three commands. A `present` detail is first validated at `ship-summary` and then checked. An `unpublished` `stopped` result runs `validate-detail-input` and then a second `ship-summary` validation. Before this change the validator was the only child that `finish` started. At plan time every assertion except the spawn check held against the base, so the spawn check is the test's only red.

- [ ] **Step 2: Run the tests and watch them fail**

Run the focused form (Global Constraints) on `test_workflow_state.py` with `-k InProcessArtifactBudgetTest -k ArtifactBudgetPolicyResolutionTest`.
Expected: `FAILED (failures=4, errors=1)`, 5 tests.
- Each of the three `finish` tests of `InProcessArtifactBudgetTest` fails with `Lists differ: ['subprocess.Popen', …] != []` on its refused finish.
- The exception-mapping test errors with `AttributeError`: the base has no `_artifact_budget`.
- The installed test fails with `AssertionError: 1 != 0`. Its probe's traceback ends in `FileNotFoundError` for `<home>/.agents/bin/artifact-budget`, because the base still runs the wrapper.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. Imports: add `import io` after `import importlib.util`, and `import traceback` after `import tempfile`. Keep `import subprocess`.

2. Replace `artifact_budget_paths`'s signature and docstring with the following. Keep `trusted_policy` and the source-layout test as they are.

```python
def artifact_budget_paths() -> tuple[Path, Path | None]:
    """The artifact-budget module file and the resolved policy (#337 D38; issue 498 D2).

    In the source layout (`artifact_budget.py` beside the resolved script, the
    policy in its parent directory) they are those two files. Otherwise the
    module is `~/.agents/lib/python/artifact_budget.py`, the file the installed
    `artifact-budget` wrapper runs, and the policy is
    `<script dir>/../share/artifact-budget-policy.json`, else
    `~/.agents/share/artifact-budget-policy.json` (None when neither exists):
    the store copy `workflow-state` runs from has neither beside it. The module
    file is not checked here; `_artifact_budget` refuses one it cannot load.
    """
```

   Then replace the code after the inner function with:

```python
    script_dir = Path(__file__).resolve().parent
    source_module = script_dir / "artifact_budget.py"
    source_policy = script_dir.parent / "artifact-budget-policy.json"
    if source_module.is_file() and source_policy.is_file():
        return source_module, trusted_policy(source_policy)
    installed_policy = Path(__file__).parent.parent / "share/artifact-budget-policy.json"
    if not installed_policy.is_file():
        installed_policy = Path.home() / ".agents/share/artifact-budget-policy.json"
    return Path.home() / ".agents/lib/python/artifact_budget.py", (
        trusted_policy(installed_policy) if installed_policy.is_file() else None
    )
```

3. Directly after `artifact_budget_paths`, add the loader and the helper. The resolution sits inside the loader's `try`, so a missing module is a load failure. `artifact_budget_paths` stays non-raising, so `phase_notes_maximum` still works without the module (D7).

```python
_ARTIFACT_BUDGET = None


def _artifact_budget():
    """The artifact-budget module, loaded on first use and kept for the process
    (issue 498 D2, D7).

    It is loaded from the resolved target of `artifact_budget_paths()`'s module
    file. Every Nix store file has mtime 1, so bytecode cached beside a
    home-manager link would be checked by size alone and could outlive a
    same-size edit; a store file's name changes with its content. The module is
    registered in `sys.modules` before it executes, as its dataclasses require,
    and unregistered if loading fails. Any failure is a `WorkflowError`.
    """
    global _ARTIFACT_BUDGET
    if _ARTIFACT_BUDGET is not None:
        return _ARTIFACT_BUDGET
    name = "_workflow_state_artifact_budget"
    try:
        entry = artifact_budget_paths()[0].resolve(strict=True)
        spec = importlib.util.spec_from_file_location(name, entry)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise WorkflowError(f"artifact-budget module: {exc}") from exc
    _ARTIFACT_BUDGET = module
    return module


def artifact_budget_invoke(argv: list[str], input_bytes: bytes = b"") -> Any:
    """Run one artifact-budget command in this process and return its `Outcome`
    (issue 498 D1, D4).

    `argv` is the command line without the program name; `--policy` is appended
    when a policy resolved. `input_bytes` is what `--input -` reads. An exception
    that escapes the validator becomes exit 1 with empty stdout and its traceback
    as stderr, as a crashed child process left it.
    """
    module = _artifact_budget()
    _, policy = artifact_budget_paths()
    if policy is not None:
        argv = [*argv, "--policy", str(policy)]
    try:
        return module.invoke(argv, io.BytesIO(input_bytes).read)
    except Exception:
        return module.Outcome(1, b"", traceback.format_exc())
```

4. In `artifact_budget_validate`, keep the exactly-one-input guard. Replace everything from `argv, policy = artifact_budget_paths()` through `canonical = json.loads(completed.stdout)` with the following. The two `returned …` refusals after it stay as they are.

```python
    argv = [command]
    if boundary is not None:
        argv.extend(("--boundary", boundary))
    argv.extend(("--input", "-" if input_bytes is not None else str(input_path)))
    outcome = artifact_budget_invoke(argv, b"" if input_bytes is None else input_bytes)
    if outcome.exit_code != 0 or not outcome.stdout:
        subject = "detail input" if boundary is None else f"{boundary} boundary"
        raise WorkflowError(f"artifact-budget {command} rejected the {subject}")
    try:
        canonical = json.loads(outcome.stdout)
```

5. In `validate_durable_detail`, keep the beneath-the-root check. Replace everything from `argv, policy = artifact_budget_paths()` through `canonical = json.loads(completed.stdout)` with the following. The `invalid canonical JSON` and `invalid review result` refusals after it stay as they are.

```python
    outcome = artifact_budget_invoke([
        "check", "--kind", "review-package", "--root", str(candidate), "--format", "json",
    ])
    if outcome.exit_code != 0:
        raise WorkflowError("durable detail is not a checker-valid review package")
    try:
        canonical = json.loads(outcome.stdout)
```

In `home/common/agent-skills/default.nix`, directly above `".agents/lib/python/artifact_budget.py".source = ./scripts/artifact_budget.py;`, add:

```nix
    # The artifact-budget module. The `artifact-budget` wrapper runs it, and
    # `workflow-state` loads the store file this link resolves to into its own
    # process (issue 498 D2, D7).
```

Change nothing else. `phase_notes_maximum`, the wrapper file and every other entry stay as they are. This shape was prototyped at plan time: the four tests passed with it. With `.resolve(strict=True)` removed, the installed test failed on the module path.

- [ ] **Step 4: Verify**

Run the focused form with `-k InProcessArtifactBudgetTest -k ArtifactBudgetPolicyResolutionTest`.
Expected: `OK`, 5 tests.

Confirm that the installed test pins D7. In a scratch copy of the tree only (never committed), drop `.resolve(strict=True)` from `_artifact_budget`'s `entry` line. Then run that copy's focused form with `-k ArtifactBudgetPolicyResolutionTest`.
Expected: it fails on `Path(observed["module"])`, the link path against its store target.

Run the three modules whose behaviour this task touches, in parallel (timeout 3600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 3 home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -6'`.
Expected: a `suite-runner: summary members=3 passed=3 failed=0 …` line, with exit 0. `test_delivered_control`'s exact-byte `rejected the workflow-response boundary` pin is part of this run.

Run `bash -c 'set -e; f=home/common/agent-skills/scripts/workflow-state.py; if grep -nE "subprocess\.run\(argv|installed_cli|\.agents/bin/artifact-budget" "$f"; then exit 1; fi; test "$(grep -c "subprocess\.run(" "$f")" = 2; echo spawn-free'`.
Expected: `spawn-free` and no other output. At base this gate prints the wrapper and `subprocess.run(argv` lines and exits 1.

Run `just build` (timeout 3600 s), because `default.nix` changed.
Expected: exit 0.

Run `git status --short`.
Expected: exactly ` M home/common/agent-skills/default.nix`, ` M home/common/agent-skills/scripts/workflow-state.py` and ` M home/common/agent-skills/tests/test_workflow_state.py`. The `result` link that `just build` leaves is ignored.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/default.nix
launch-commit … -- -m "perf(issue-498): validate artifact budgets in-process in workflow-state" -m "<session trailers>"
```

Verify: `git status --short -- home/common/agent-skills` prints nothing.
