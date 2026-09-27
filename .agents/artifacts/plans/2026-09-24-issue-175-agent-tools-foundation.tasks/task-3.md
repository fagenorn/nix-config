# Task 3: Move agent-gate-bundle into the package

Decisions: D1, D2, D3, D5 (`prog`), D6, D7; parent D11, D14, D15. Spec sections
"How each file moves (D2)", "The canonical module (D3)" (the composition table)
and "Test re-points (D7)". Work from the worktree root.
`PK` = `python/agent_tools`.

**Files:**
- Move: `scripts/agent-gate-bundle.py` → `PK/agent_gate_bundle.py`, using
  `git mv`, with the mode changing from 100755 to 100644
- Modify: `tests/test_agent_gate_bundle.py`
- Modify: `justfile` (the `agent-gate-bundle` recipe)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest`, `reject_duplicate_keys`
  and `reject_nonfinite_literal`, and the justfile variable `agent_tools_path`
  (all from Task 1).
- Produces: the module `agent_tools.agent_gate_bundle`. It keeps every existing
  name except `canonical_digest`, `_reject_duplicate_keys` and
  `_reject_constant`, which it no longer defines. `just agent-gate-bundle <args>`
  runs `python3 -m agent_tools.agent_gate_bundle <args>`.

**Invariants:**
- The moved file differs from the original by exactly these edits (D2), and by
  nothing else:
  1. Line 1 (`#!/usr/bin/env python3`) is deleted, and the mode becomes 100644.
  2. In the module docstring (L7), `` `agent-costs.py --format json` `` becomes
     `` `agent-costs --format json` ``.
  3. `import hashlib` is deleted. Its only use was the local digest.
  4. A new import group is added one blank line after `from pathlib import Path`:
     ```python
     from agent_tools.canonical import (reject_duplicate_keys, reject_nonfinite_literal,
                                        telemetry_digest)
     ```
  5. `def canonical_digest` (L96–99), `def _reject_duplicate_keys` (L118–124)
     and `def _reject_constant` (L127–128) are deleted. Two blank lines still
     separate the remaining definitions.
  6. `_parse` keeps its docstring, and its body becomes
     `return json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)`.
     It may wrap as the original did. This is D3's gate-bundle row: duplicate
     keys and the three non-finite literals are both still rejected.
  7. Both call sites become `telemetry_digest(`: at `digest =` (L510) and at
     `bundle_id=` (L921). The name has the same length, so continuation lines
     keep their alignment.
  8. `main` builds `argparse.ArgumentParser(prog="agent-gate-bundle", description=__doc__)`.
- `_parse`'s callers and their `except (json.JSONDecodeError, ValueError)`
  clauses stay untouched, so every diagnostic code and text stays as it is.
- The `if __name__ == "__main__":` block stays.
- Rename detection pairs the two paths, reported as `R` with a similarity of 95
  or more.
- The existing strict-parse pins stay green without edits:
  `test_duplicate_json_key_is_a_manifest_error` and the NaN/Infinity/-Infinity
  loop near L174.

- [ ] **Step 1: Re-point the tests and add the entry-point run**

In `tests/test_agent_gate_bundle.py`:

- Replace the docstring with:

```python
"""Offline tests for agent_tools.agent_gate_bundle.

Run: just agent-workflow-tests
"""
```

- In the import block, delete `import importlib.util`. Add `import subprocess`
  and `import sys` in alphabetical position within the existing stdlib group.
- Delete L16–21 (`REPO = …`, `SCRIPT = …` and the three `_spec`/`gate`/
  `exec_module` lines). Neither `REPO` nor `SCRIPT` is used anywhere else. Then
  add a new import group after `from pathlib import Path`:

```python

from agent_tools import agent_gate_bundle as gate
from agent_tools.canonical import telemetry_digest
```

- Change the five `gate.canonical_digest(` call sites (L56, L281, L304, L683 and
  L822) to `telemetry_digest(`, leaving the rest of each line as it is.
- Directly above the final `if __name__ == "__main__":`, add:

```python
class ModuleEntryPointTest(unittest.TestCase):
    """The recipe runs the tool with `-m`; every other test calls main() in process."""

    def test_the_module_run_reaches_main_under_the_command_name(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_gate_bundle", "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: agent-gate-bundle "),
                        completed.stdout[:200])


```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_gate_bundle.py 2>&1 | tail -3`
Expected: `FAILED (errors=1)`, from
`ModuleNotFoundError: No module named 'agent_tools.agent_gate_bundle'`.

- [ ] **Step 3: Move and edit**

```bash
git mv scripts/agent-gate-bundle.py python/agent_tools/agent_gate_bundle.py
chmod 644 python/agent_tools/agent_gate_bundle.py
```

Apply the eight edits listed under Invariants, and nothing else. Then change
the recipe in `justfile` to:

```
agent-gate-bundle *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_gate_bundle {{args}}
```

Leave its comment line as it is.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest -v tests/test_agent_gate_bundle.py 2>&1 | tail -3`
Expected: `OK`.

Run: `git add -A python/agent_tools/agent_gate_bundle.py scripts/agent-gate-bundle.py && git diff --cached -M --name-status -- scripts/agent-gate-bundle.py python/agent_tools/agent_gate_bundle.py`
Expected: one line, `R<NN>	scripts/agent-gate-bundle.py	python/agent_tools/agent_gate_bundle.py`, with `NN` ≥ 95.

Run: `if grep -nE "canonical_digest|_reject_duplicate_keys|_reject_constant|^#!|^import hashlib|agent-costs\.py" python/agent_tools/agent_gate_bundle.py; then exit 1; fi; if grep -nE "canonical_digest|importlib|sys\.path" tests/test_agent_gate_bundle.py; then exit 1; fi; echo moved-clean`
Expected: `moved-clean`. This check fails at the starting commit.

Run: `just agent-gate-bundle --help 2>/dev/null | head -1`
Expected: a line starting `usage: agent-gate-bundle `.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with one more test than after Task 2.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_gate_bundle.py scripts/agent-gate-bundle.py \
  tests/test_agent_gate_bundle.py justfile
git commit -m "refactor(agent-tools): move agent-gate-bundle into the package"
```

The message ends with the trailer lines named in the plan's Global Constraints.
