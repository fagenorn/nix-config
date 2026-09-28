# Task 1: Add the sibling-run helper

Decisions: D5, D9, D12, D15; parent D8, D16. Spec sections "The sibling-run
helper (D5)" and "The installed-layout test and the helper's test (D9)". Work
from the worktree root. `PK` = `python/agent_tools`.

**Files:**
- Create: `PK/siblings.py`
- Create: `tests/test_agent_tools_siblings.py`
- Modify: `justfile` (the `agent-workflow-tests` file list)

**Interfaces:**
- Consumes: nothing new. `agent_tools.diff_scope` already exists, and its
  argparse `prog` is `diff-scope`.
- Produces: `agent_tools.siblings.sibling_argv(module: str) -> list[str]`,
  which returns
  `[sys.executable, "-I", "-m", f"agent_tools.{module}"]` when
  `sys.flags.isolated` is truthy, and otherwise the same list without `"-I"`.
  Task 2's `agent_tools.adopt_project.run_resolver` calls
  `sibling_argv("resolve_project")`.

**Invariants:**
- The helper reads `sys.flags` and `sys.executable` at call time, never at
  import time, so a caller's patch of `sys.flags` is observed.
- The helper takes an unqualified module name. It prefixes `agent_tools.`
  itself, so no caller spells the package.
- The module imports only `sys`. It starts no process and reads no file.

- [ ] **Step 0: Record the starting commit and the base test count**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > "$B/base.log" 2>&1; tail -3 "$B/base.log"`
Expected: `Ran NBASE tests` and `OK (skipped=2)`. Record `NBASE`. The plan's
Global Constraints derive every later count from it. Report it in this
task's handback.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_tools_siblings.py` with exactly:

```python
"""Module-interface seam for agent_tools.siblings (#177 D5, D9, D15)."""

import subprocess
import sys
import types
import unittest
from unittest import mock

from agent_tools import siblings


class SiblingArgvTest(unittest.TestCase):
    def argv_under(self, isolated):
        with mock.patch.object(siblings.sys, "flags",
                               types.SimpleNamespace(isolated=isolated)):
            return siblings.sibling_argv("resolve_project")

    def test_a_non_isolated_caller_runs_its_sibling_without_isolation(self):
        self.assertEqual(self.argv_under(0),
                         [sys.executable, "-m", "agent_tools.resolve_project"])

    def test_an_isolated_caller_runs_its_sibling_isolated(self):
        self.assertEqual(self.argv_under(1),
                         [sys.executable, "-I", "-m", "agent_tools.resolve_project"])

    def test_the_argv_runs_the_named_package_module(self):
        completed = subprocess.run(
            [*siblings.sibling_argv("diff_scope"), "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: diff-scope "),
                        completed.stdout[:200])


if __name__ == "__main__":
    unittest.main()
```

The real run inherits this process's environment, so under the recipe the
child finds the package through `PYTHONPATH` (D15).

- [ ] **Step 2: Watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_tools_siblings.py 2>&1 | tail -3`
Expected: `ImportError: cannot import name 'siblings'`, then `FAILED`.

- [ ] **Step 3: Write the helper**

Create `PK/siblings.py` with exactly:

```python
"""Running one agent_tools module from another as a child process (parent D16).

A packaged module that runs a packaged sibling builds that child's argv here
and nowhere else. The child runs under this process's own interpreter, so an
installed launcher's child uses the same store environment, and therefore the
same package, as its parent.
"""

import sys


def sibling_argv(module: str) -> list[str]:
    """argv that runs agent_tools.<module> under this interpreter, isolated iff we are."""
    return [sys.executable, *(["-I"] if sys.flags.isolated else []), "-m", f"agent_tools.{module}"]
```

In `justfile`'s `agent-workflow-tests`, insert this line directly after
`    tests/test_agent_tools_canonical.py \`:

```
    tests/test_agent_tools_siblings.py \
```

Touch no other recipe line.

- [ ] **Step 4: Verify**

Run: `git add python/agent_tools/siblings.py tests/test_agent_tools_siblings.py && PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_agent_tools_siblings.py 2>&1 | tail -3`
Expected: `Ran 3 tests` and `OK`.

Run: `grep -c "tests/test_agent_tools_siblings.py" justfile`
Expected: `1`. At `$START` it prints `0`.

Run: `just build 2>&1 | tail -3`
Expected: success with no `error:` line. The build's `pythonImportsCheck` now
includes `agent_tools.siblings`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > "$B/t1.log" 2>&1; tail -3 "$B/t1.log"`
Expected: `Ran NBASE+3 tests` and `OK (skipped=2)`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/siblings.py tests/test_agent_tools_siblings.py justfile
git commit -m "feat(agent-tools): add the sibling-run helper"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
