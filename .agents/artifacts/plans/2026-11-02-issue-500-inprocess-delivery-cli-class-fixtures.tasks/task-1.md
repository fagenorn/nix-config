# Task 1: The in-process runner honours stdin, cwd and bytes

This task implements spec § The in-process runner (D2, D3, D7) and test seam 1 (D6). `run_script` gains `subprocess.run`'s `input`, `cwd` and `text` keywords. With `text=True` (the default) every existing lifecycle-harness call is unchanged. A new suite member, `test_inprocess_cli`, compares the runner with a real child process. No caller passes the new keywords until Task 2.

**Files:**
- Modify: `home/common/agent-skills/tests/_inprocess_cli.py`
- Create: `home/common/agent-skills/tests/test_inprocess_cli.py`
- Modify: `justfile` (one recipe member line)

**Interfaces:**
- Consumes (base): `run_script(script, args, *, env)`, the compile cache `_CODE`, and `_text(stream)` in `_inprocess_cli.py`. The by-path load of this file in `test_workflow_state.py` (`INPROCESS_CLI`, 262 D10) stays as it is.
- Produces (Task 2 relies on this exact signature):
  - `run_script(script, args, *, env, input=None, cwd=None, text=True) -> subprocess.CompletedProcess`. `stdout` and `stderr` are `str` when `text`, else `bytes`. `args` is `[sys.executable, script, *args]`, as today.
  - Private: `_captured(stream: io.TextIOWrapper, text: bool) -> str | bytes` replaces `_text`.

**Invariants:**
- For the same `args`, `env`, `input`, `cwd` and `text`, `run_script` returns the `(returncode, stdout, stderr)` that `subprocess.run([sys.executable, script, *args], …, capture_output=True)` returns. The one exception is the traceback of an uncaught exception, which also shows the runner's own frame (R1).
- `input=None` is an empty stdin. In bytes mode, `input` is the stdin bytes. In text mode, it is encoded as UTF-8. `sys.stdin.buffer.read()` returns exactly those bytes.
- `text=False` returns the raw captured bytes, with no decoding and no newline translation. `text=True` returns today's decoded, newline-normalised strings.
- The process directory is recorded before the call and restored in a `finally` on every outcome: exit 0, a non-zero exit, `sys.exit("message")`, an uncaught exception, and `cwd=None` (R2, D3). The environment, `sys.argv`, the `sys` streams and `__main__` are restored as today.
- A `cwd` that cannot be entered raises its `OSError` (for a missing directory, `FileNotFoundError`) out of `run_script` before the script starts, with the process directory unchanged (D3). It is never mapped to an exit code.
- Exit mapping, the compile-once cache and the fresh `__main__` per call are unchanged (262 D4). The runner imports no test module and purges no library cache (D7).

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_inprocess_cli.py` with exactly this content:

```python
"""The in-process CLI runner against a real child process (issue 500 D2, D3, D6).

Run: just agent-workflow-tests
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ._inprocess_cli import run_script


# Reports its working directory, its stdin bytes and one environment variable, then
# writes raw bytes (non-UTF-8 only in bytes mode) and a stderr line, and exits as
# argv[1] says: a number, `raise`, or any other text as the `sys.exit` message.
PROBE = r'''import hashlib, os, sys
data = sys.stdin.buffer.read()
sys.stdout.write(f"cwd={os.getcwd()}\nstdin={len(data)}:{hashlib.sha256(data).hexdigest()}\n"
                 f"probe={os.environ.get('PROBE_VALUE')}\n")
sys.stdout.flush()
sys.stdout.buffer.write(b"raw:\xff\x00\n" if sys.argv[2] == "bytes" else "raw:é\n".encode())
sys.stderr.write("probe: stderr line\n")
outcome = sys.argv[1]
if outcome == "raise":
    raise RuntimeError("probe failure")
sys.exit(int(outcome) if outcome.isdigit() else outcome)
'''


class InProcessRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.probe = self.directory / "probe.py"
        self.probe.write_text(PROBE, encoding="utf-8")
        self.env = {**os.environ, "PROBE_VALUE": "issue-500"}

    def child(self, args, *, input, cwd, text):
        """The same call as a real child: `None` input is an empty stdin, as in-process."""
        stdin = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
        done = subprocess.run([sys.executable, str(self.probe), *args], cwd=cwd,
                              env=self.env, capture_output=True, text=text, check=False,
                              **stdin)
        return done.returncode, done.stdout, done.stderr

    def test_a_run_returns_exactly_what_a_child_process_returns(self):
        rows = (
            ("bytes stdin, bytes mode", ("0", "bytes"), b"\x00\xffstdin\n", None, False),
            ("text stdin, text mode", ("0", "text"), "héllo\n", None, True),
            ("cwd set, bytes mode", ("0", "bytes"), None, self.directory, False),
            ("cwd set, text mode", ("0", "text"), None, self.directory, True),
            ("exit 3", ("3", "bytes"), b"", None, False),
            ("sys.exit message", ("stopped by probe", "text"), None, None, True),
        )
        for name, args, input, cwd, text in rows:
            with self.subTest(name):
                done = run_script(self.probe, args, env=self.env, input=input, cwd=cwd,
                                  text=text)
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 self.child(args, input=input, cwd=cwd, text=text))

    def test_the_process_is_restored_on_every_outcome(self):
        def state():
            return (os.getcwd(), dict(os.environ), list(sys.argv), sys.stdin, sys.stdout,
                    sys.stderr, sys.modules.get("__main__"))

        before = state()
        failed = run_script(self.probe, ("3", "bytes"), env=self.env, cwd=self.directory,
                            text=False)
        self.assertEqual(failed.returncode, 3)
        self.assertEqual(state(), before)
        raised = run_script(self.probe, ("raise", "text"), env=self.env, cwd=self.directory)
        self.assertEqual(raised.returncode, 1)
        self.assertEqual(raised.stderr.splitlines()[-1], "RuntimeError: probe failure")
        self.assertEqual(state(), before)
        missing = self.directory / "missing"
        with self.assertRaises(FileNotFoundError):
            run_script(self.probe, ("0", "bytes"), env=self.env, cwd=missing, text=False)
        self.assertEqual(state(), before)
        with self.assertRaises(FileNotFoundError):
            self.child(("0", "bytes"), input=None, cwd=missing, text=False)


if __name__ == "__main__":
    unittest.main()
```

In `justfile`, recipe `agent-workflow-tests *args:`, add this member line directly after `    home/common/agent-skills/tests/test_delivery_workflow.py \`, with the same four-space indent and trailing ` \`:

```
    home/common/agent-skills/tests/test_inprocess_cli.py \
```

- [ ] **Step 2: Run the test and watch it fail**

Run (focused test form, timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_inprocess_cli.py 2>&1 | tail -6'`
Expected: `FAILED (errors=7)`. Six subtests raise `TypeError: run_script() got an unexpected keyword argument 'input'`, and the restoration test raises the same error for `'cwd'`.

- [ ] **Step 3: Write the minimal implementation**

Replace the body of `_inprocess_cli.py` below its imports with the code that follows. Keep the imports, which are all still used. The order is the decision (D3): record the directory, enter `cwd` outside every patch (so a bad `cwd` raises before anything is patched), and restore the directory in an outer `finally` that also covers `cwd=None`.

```python
_CODE: dict[str, types.CodeType] = {}


def _captured(stream: io.TextIOWrapper, text: bool) -> str | bytes:
    stream.flush()
    raw = stream.buffer.getvalue()
    if not text:
        return raw
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def run_script(script, args, *, env, input=None, cwd=None, text=True):
    """`subprocess.run([sys.executable, script, *args], input=input, cwd=cwd, env=env,
    capture_output=True, text=text)`, in process.

    The process directory, environment, `sys` streams, `sys.argv` and `__main__` are
    restored on every outcome; a `cwd` that cannot be entered raises its `OSError`
    before the script starts (issue 500 D3).
    """
    path = str(script)
    code = _CODE.get(path)
    if code is None:
        code = _CODE[path] = compile(Path(path).read_bytes(), path, "exec")
    argv = [path, *map(str, args)]
    if input is None:
        data = b""
    elif text:
        data = input.encode("utf-8")
    else:
        data = bytes(input)
    module = types.ModuleType("__main__")
    module.__file__ = path
    stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="backslashreplace")
    saved = sys.modules.get("__main__")
    returncode = 0
    directory = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
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
    finally:
        os.chdir(directory)
    return subprocess.CompletedProcess([sys.executable, *argv], returncode,
                                       _captured(stdout, text), _captured(stderr, text))
```

Set the module docstring to these two paragraphs:

```python
"""Run a Python CLI script inside the test process, shaped like subprocess.run (#262 D4).

`input`, `cwd` and `text` mean what they mean to `subprocess.run` (issue 500 D2, D3).
"""
```

- [ ] **Step 4: Verify**

All from the worktree root, through `launch-scope exec`:
1. The Step 2 command. Expected: `Ran 2 tests` and `OK`.
2. The text-mode consumers are unchanged (focused test form): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k InProcessArtifactBudgetTest -k PhaseBudgetDefaultsTest 2>&1 | tail -6'`. Expected: `Ran 8 tests` and `OK`.
3. The recipe still parses: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py -k RecipeWiringTest 2>&1 | tail -4'`. Expected: `OK`.
4. The Coverage gate (Global Constraints). Expected: `COVERAGE-GATE-OK base 3575 head 3577 test ids`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/_inprocess_cli.py home/common/agent-skills/tests/test_inprocess_cli.py justfile
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(issue-500): run scripts in-process with stdin, cwd and bytes" -m "<the session's trailer lines>"
```
