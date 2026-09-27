# Task 2: Move agent-costs into the package

Decisions: D1, D2, D3, D5 (`prog`), D6, D7; parent D14, D15. Spec sections
"How each file moves (D2)", "Recipes run the source package (D6)" and "Test
re-points (D7)". Work from the worktree root. `PK` = `python/agent_tools`.

**Files:**
- Move: `scripts/agent-costs.py` → `PK/agent_costs.py`, using `git mv`, with the
  mode changing from 100755 to 100644
- Modify: `tests/test_agent_costs.py`
- Modify: `tests/agent_model_drift_test_support.py` (only its `agent-costs` load)
- Modify: `justfile` (the `agent-costs` recipe)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest` and the justfile variable
  `agent_tools_path` (both from Task 1). `agent-workflow-tests` already assigns
  `PYTHONPATH`.
- Produces: the module `agent_tools.agent_costs`. It keeps every existing name
  except `canonical_digest`, which it no longer defines. `just agent-costs <args>`
  runs `python3 -m agent_tools.agent_costs <args>`.

**Invariants:**
- The moved file differs from the original by exactly these edits (D2), and by
  nothing else:
  1. Line 1 (`#!/usr/bin/env python3`) is deleted, and the mode becomes 100644.
  2. `import hashlib` is deleted. Its only use was the local digest.
  3. `from agent_tools.canonical import telemetry_digest` is added as its own
     import group, one blank line after `from pathlib import Path`.
  4. `def canonical_digest(body):` and its three body lines (L1064–1067) are
     deleted, together with one of the two blank-line pairs around them, so
     that two blank lines still separate the neighbouring definitions.
  5. The three call sites become `telemetry_digest(`: in `cohort_digest`
     (L1134), in `_validate_scheduling` (L1176) and at `record_id=` (L1650).
  6. `main` builds `argparse.ArgumentParser(prog="agent-costs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)`.
- The `if __name__ == "__main__":` block stays, since it is what `-m` runs.
- Rename detection pairs the two paths, reported as `R` with a similarity of 95
  or more.
- `tests/fixtures/agent_costs_text_golden.txt` and every existing assertion
  stay unchanged.

- [ ] **Step 1: Re-point the tests and add the entry-point run**

In `tests/test_agent_costs.py`:

- Change the docstring's first line to
  `"""Offline tests for agent_tools.agent_costs against tiny synthetic transcripts.`
  and its run line to `Run: just agent-workflow-tests`.
- In the import block, delete `import importlib.util`. Add `import subprocess`
  and `import sys` in alphabetical position within the existing stdlib group.
- Delete the block at L21–26 (`REPO = …`, `SCRIPT = …` and the three
  `_spec`/`agent_costs`/`exec_module` lines). Neither `REPO` nor `SCRIPT` is
  used anywhere else. Then add a new import group after
  `from unittest import mock`:

```python

from agent_tools import agent_costs
from agent_tools.canonical import telemetry_digest
```

- At L1380, change `slot_digest = agent_costs.canonical_digest(event_window)` to
  `slot_digest = telemetry_digest(event_window)`. At L1461, change
  `agent_costs.canonical_digest(body)` to `telemetry_digest(body)`.
- Directly above the final `if __name__ == "__main__":`, add:

```python
class ModuleEntryPointTest(unittest.TestCase):
    """The recipe runs the tool with `-m`; every other test calls main() in process."""

    def test_the_module_run_reaches_main_under_the_command_name(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: agent-costs "),
                        completed.stdout[:200])


```

In `tests/agent_model_drift_test_support.py`, delete
`COST_SCRIPT = REPO_ROOT / "scripts/agent-costs.py"` (L17) and the two
`_cost`/`agent_costs` lines (L21–22). Add `from agent_tools import agent_costs`
as its own import group, one blank line after `from pathlib import Path`
(L13). Its `agent-model-drift` loader and `importlib` import stay, because #179
owns them.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_costs.py 2>&1 | tail -3`
Expected: `FAILED (errors=1)`, from
`ModuleNotFoundError: No module named 'agent_tools.agent_costs'`.

- [ ] **Step 3: Move and edit**

```bash
git mv scripts/agent-costs.py python/agent_tools/agent_costs.py
chmod 644 python/agent_tools/agent_costs.py
```

Apply the six edits listed under Invariants, and nothing else. Then change the
recipe in `justfile` to:

```
agent-costs *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_costs {{args}}
```

Leave its comment line and the neighbouring `agent-model-drift` recipe as they
are.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_costs.py tests/test_agent_model_drift_schema.py tests/test_agent_model_drift_routing.py tests/test_agent_model_drift_scheduling.py tests/test_agent_model_drift_producer_integration.py 2>&1 | tail -3`
Expected: `OK`.

Run: `git add -A python/agent_tools/agent_costs.py scripts/agent-costs.py && git diff --cached -M --name-status -- scripts/agent-costs.py python/agent_tools/agent_costs.py`
Expected: one line, `R<NN>	scripts/agent-costs.py	python/agent_tools/agent_costs.py`, with `NN` ≥ 95.

Run: `git diff --cached -M --summary -- scripts/agent-costs.py python/agent_tools/agent_costs.py`
Expected: `rename scripts/agent-costs.py => python/agent_tools/agent_costs.py (NN%)`
and `mode change 100755 => 100644`. The pathspec must name both paths, or git
reports a create.

Run: `if grep -nE "canonical_digest|^#!|^import hashlib" python/agent_tools/agent_costs.py; then exit 1; fi; if grep -nE "canonical_digest|importlib|sys\.path" tests/test_agent_costs.py; then exit 1; fi; echo moved-clean`
Expected: `moved-clean`. At the starting commit the tests file still holds
`importlib`, so this check fails there.

Run: `just agent-costs --help 2>/dev/null | head -1`
Expected: a line starting `usage: agent-costs `.

This run is shown once, for the process pool under `-m`:
`E=$(mktemp); just agent-costs --days 1 --top 1 >/dev/null 2>"$E" || { cat "$E"; exit 1; }; if grep "Process pool unavailable" "$E"; then exit 1; fi; rm -f "$E"; echo pool-ok`
Expected: `pool-ok`. If the recipe still ran the old path, it would exit 2 and
the check would fail. The spawned workers re-import the tool by module name
through the recipe's `PYTHONPATH`. Workers start only when a transcript is
submitted, so the check proves nothing on an empty window: if the report lists
no session, rerun it with `--days 7`. If `~/.claude/projects` is absent on the
machine, say so and skip this check.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with one more test than after Task 1.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py scripts/agent-costs.py \
  tests/test_agent_costs.py tests/agent_model_drift_test_support.py justfile
git commit -m "refactor(agent-tools): move agent-costs into the package"
```

The message ends with the trailer lines named in the plan's Global Constraints.
