# Task 5: In-process lifecycle CLI runner

Per D4 and D10. Hotspot H3: `LifecycleHarness.run_cli` and `LifecycleHarness.run_control_at_root` in `home/common/agent-skills/tests/test_workflow_state.py` launch `python3 workflow-state.py` once per call, about 1,400 launches in that module alone. Both methods move to a runner that executes the script inside the test process and returns the same `subprocess.CompletedProcess` shape. Every class that inherits `LifecycleHarness` gets the runner too: the ones in `test_host_admission.py` and `tests/test_launch_commit.py` (per D10). Every other workflow-state subprocess site stays a real process.

**Files:**
- Create: `home/common/agent-skills/tests/_inprocess_cli.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`: a module-level load of the runner after `load_source_module`, and the bodies of `run_cli` and `run_control_at_root` only

**Interfaces:**
- Consumes: `SCRIPT` and `load_source_module(path, name, *, package=False)`, both already in `test_workflow_state.py`, and `self.cli_env`, set in `LifecycleHarness.setUp`.
- Produces: `_inprocess_cli.run_script(script: Path, args: Iterable[object], *, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]`, with `args == [sys.executable, str(script), *map(str, args)]`, the `returncode`, and text `stdout`/`stderr`. In `test_workflow_state.py` it is the module global `INPROCESS_CLI`, loaded with `load_source_module(Path(__file__).with_name("_inprocess_cli.py"), "workflow_state_test_inprocess_cli")`. That is a by-path load, because `test_launch_commit` loads `test_workflow_state` by path, where a relative import cannot resolve (per D10).

**Invariants:**
- The script is compiled once per path per test process. Each call executes the code in a fresh `types.ModuleType("__main__")` whose `__file__` is `str(script)`, registered as `sys.modules["__main__"]` only for the duration of the call. The script's globals, including `_DELIVERY_RUNTIMES` and `_HOST_ADMISSION`, therefore never outlive one call.
- For the duration of the call only:
  - `os.environ` is exactly `env` (`mock.patch.dict(..., clear=True)`)
  - `sys.argv` is `[str(script), *map(str, args)]`, so argparse's `prog` is `workflow-state.py`
  - `sys.stdin`, `sys.stdout` and `sys.stderr` are `io.TextIOWrapper`s over `io.BytesIO` (UTF-8; stderr uses `errors="backslashreplace"`), so `.buffer` writes work
  - stdin is empty
  Everything is restored on every exit path.
- Exit mapping, as the interpreter does it:
  - normal completion → `0`
  - `SystemExit(None)` → `0`
  - `SystemExit(int)` → that int `& 0xFF`
  - `SystemExit(other)` → print `other` to the call's stderr, then `1`
  - any other `Exception` → its traceback on the call's stderr, then `1`
  A `BaseException` that is not `SystemExit` propagates.
- Output is decoded as UTF-8 with universal newlines (`\r\n` and `\r` become `\n`), matching `subprocess.run(text=True)`.
- `run_cli` keeps its signature `run_cli(self, *args, ok=True)` and its `self.fail(f"command failed with {completed.returncode}: {completed.stderr}")` behavior. `run_control_at_root` keeps writing `copied-control.json`, keeps its `assertEqual(completed.returncode, 0, completed.stderr)` and keeps its `_legacy_control` stdout rewrite. No other line of `test_workflow_state.py` changes. In particular, the `subprocess.Popen` race sites and the `validated = subprocess.run(` site stay real processes.

- [ ] **Step 1: Write the failing probe** (scratch only)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t5-probe.py" <<'PY'
import os, sys, unittest
sys.path.insert(0, os.getcwd())  # the worktree root, as `python -m unittest` has it
launches = []
sys.addaudithook(lambda e, a: e == "subprocess.Popen"
                 and any(str(x).endswith("workflow-state.py") for x in a[1]) and launches.append(a[1]))
name = ("home.common.agent-skills.tests.test_workflow_state.WorkflowStateLifecycleTest."
        "test_public_cli_exposes_direct_owner_but_not_retired_commands")
result = unittest.main(module=None, argv=["probe", name], exit=False).result
assert result.wasSuccessful() and result.testsRun == 1, "probe test did not pass"
assert not launches, f"{len(launches)} workflow-state launches"
print("T5-PROBE-OK")
PY
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t5-probe.py"` from the worktree root.
Expected at the start commit: `AssertionError: 3 workflow-state launches`.

- [ ] **Step 3: Implement**

Write `_inprocess_cli.py`. Its module docstring, verbatim: `"""Run a Python CLI script inside the test process, shaped like subprocess.run (#262 D4)."""`. It imports `io`, `os`, `pathlib.Path`, `subprocess`, `sys`, `traceback`, `types` and `unittest.mock`, and nothing from the repository. Then:

```python
_CODE: dict[str, types.CodeType] = {}


def _text(stream: io.TextIOWrapper) -> str:
    stream.flush()
    return stream.buffer.getvalue().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def run_script(script, args, *, env):
    """`subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=env)`, in process."""
    path = str(script)
    code = _CODE.get(path)
    if code is None:
        code = _CODE[path] = compile(Path(path).read_bytes(), path, "exec")
    argv = [path, *map(str, args)]
    module = types.ModuleType("__main__")
    module.__file__ = path
    stdin = io.TextIOWrapper(io.BytesIO(b""), encoding="utf-8")
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="backslashreplace")
    saved = sys.modules.get("__main__")
    returncode = 0
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
            mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
            mock.patch.object(sys, "stderr", stderr):
        sys.modules["__main__"] = module
        try:
            exec(code, module.__dict__)
        except SystemExit as exit_:
            if exit_.code is None:
                returncode = 0
            elif isinstance(exit_.code, int):
                returncode = exit_.code & 0xFF
            else:
                print(exit_.code, file=stderr)
                returncode = 1
        except Exception:
            traceback.print_exc(file=stderr)
            returncode = 1
        finally:
            if saved is None:
                sys.modules.pop("__main__", None)
            else:
                sys.modules["__main__"] = saved
    return subprocess.CompletedProcess([sys.executable, *argv], returncode, _text(stdout), _text(stderr))
```

Then, in `test_workflow_state.py`:
- add `INPROCESS_CLI = load_source_module(...)` as in Interfaces
- `run_cli` builds `completed = INPROCESS_CLI.run_script(SCRIPT, args, env=self.cli_env)`
- `run_control_at_root` builds `completed = INPROCESS_CLI.run_script(SCRIPT, ["control", "--repo-root", root, "--run-id", self.run_id, "--request-file", request_path], env=self.cli_env)`

If a whole-module run then fails only because the script imports a sibling from its own directory, `run_script` also prepends `str(Path(path).parent)` to `sys.path` for the call and restores it afterwards, as a real script launch would. Add nothing else.

- [ ] **Step 4: Verify**

1. Run the probe. Expect `T5-PROBE-OK`.
2. Run these modules, logging to `${TMPDIR:-/tmp}/issue262-t5-<name>.log` and reporting the tail only. Each must end `OK`, which shows that the stdout/stderr/return-code assertions hold in process:
   - `home/common/agent-skills/tests/test_workflow_state.py` (`timeout 1200`)
   - `home/common/agent-skills/tests/test_host_admission.py` (`timeout 600`)
   - `tests/test_launch_commit.py` (`timeout 600`)
3. Run `grep -c "subprocess.Popen(" home/common/agent-skills/tests/test_workflow_state.py`. Expect `3`, the same as at `BASE`.
4. Run the root's coverage gate. Expect `COVERAGE-GATE-OK 2077 test ids`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/_inprocess_cli.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "test(workflow-state): run the lifecycle CLI in process (#262)" -m "<trailer lines>"
```
