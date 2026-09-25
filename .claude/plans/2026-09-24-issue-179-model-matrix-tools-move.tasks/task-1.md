# Task 1: Move the drift family into the package

Decisions: D1, D2, D3, D4, D6, D7, D12; parent D1, D8, D11, D12, D14; #175 D2,
D6. Spec sections "What moves (D1)", "How each file changes (D2–D5)",
"Recipes" and "Test re-points (D6, D7)". Work from the worktree root.
`PK` = `python/agent_tools`.

**Files:**
- Move with `git mv` (every file is already mode 100644):
  - `scripts/agent-model-drift.py` → `PK/agent_model_drift.py`
  - `scripts/agent-model-drift-routing.py` → `PK/agent_model_drift_routing.py`
  - `scripts/agent-model-drift-scheduling.py` → `PK/agent_model_drift_scheduling.py`
  - `scripts/agent-model-drift-schema.py` → `PK/agent_model_drift_schema.py`
- Modify: `tests/agent_model_drift_test_support.py`
- Modify: `tests/test_agent_model_drift_schema.py`,
  `tests/test_agent_model_drift_routing.py`,
  `tests/test_agent_model_drift_scheduling.py`,
  `tests/test_agent_model_drift_producer_integration.py`
- Modify: `justfile` (the `agent-model-drift` recipe, L167)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest` and
  `agent_tools.canonical.reject_duplicate_keys` (#175). `agent-workflow-tests`
  already assigns `PYTHONPATH`.
- Produces:
  - Modules `agent_tools.agent_model_drift`, `agent_tools.agent_model_drift_routing`,
    `agent_tools.agent_model_drift_scheduling` and `agent_tools.agent_model_drift_schema`.
    Every existing name survives except `schema.canonical_digest`,
    `schema._duplicates` and `scheduling._digest`, which are deleted.
  - The reporter keeps the module aliases `schema`, `routing_logic` and
    `scheduling_logic`. Task 2 and the producer test rely on
    `agent_model_drift.schema`.
  - `agent_model_drift_schema.load_validated_matrix` is byte-identical to the
    base in this task. It still loads
    `<root>/home/common/agent-skills/scripts/agent-model-matrix.py` by path, and
    `matrix_fixture` still copies that file. Task 2 replaces both (D5, D12).
  - The justfile line
    `  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}`.

**Invariants:**
- Each moved file differs from its original by exactly the edits in Step 3.
- `just agent-model-drift --help` prints `usage: agent-model-drift ` first.
- A duplicate-key input still prints exactly `cannot load JSON input` and exits
  2, with empty stdout (D4).
- The drift suites keep every expected value and assertion. Only D7's recipe
  literal changes, and one test is added.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`. Shell
variables do not persist between tool calls, so substitute the two printed
values literally wherever later steps write `${START}` or `$B`.

- [ ] **Step 1: Re-point the suites and add the module run**

`tests/agent_model_drift_test_support.py`:
- Delete `import importlib.util` (L6),
  `SCRIPT = REPO_ROOT / "scripts/agent-model-drift.py"` (L18), and the two
  `_spec`/`agent_model_drift = …` loader lines (L20–21).
- Change `from agent_tools import agent_costs` to
  `from agent_tools import agent_costs, agent_model_drift`.
- Leave `REPO_ROOT`, `MATRIX`, `digest` and `matrix_fixture` unchanged. `digest`
  is the fixtures' independent oracle (D6).

In each of the four drift suites, delete the `sys.path.insert(…)` line. In the
same edit, turn `from agent_model_drift_test_support import (` into
`from .agent_model_drift_test_support import (` and leave its name list as it
is. The recipe loads these files as `tests.<module>`, so the relative import
resolves, following the precedent in `home/common/agent-skills/tests/test_artifact_budget.py`.
Then remove the imports that served only the insert:
- `test_agent_model_drift_schema.py`: delete `from pathlib import Path` (L5)
  and `import sys` (L6).
- `test_agent_model_drift_routing.py`: delete `from pathlib import Path` (L2)
  and `import sys` (L3), and keep the blank line before the support import.
- `test_agent_model_drift_producer_integration.py`: delete
  `from pathlib import Path` (L6), `import sys` (L9) and the blank line after
  the insert (L11). Also make `from test_agent_costs import (` into
  `from .test_agent_costs import (`. Do not re-align the continuation lines.
- `test_agent_model_drift_scheduling.py`: delete `from pathlib import Path` (L3).
  Keep `import sys`, and add `import subprocess` between `import json` and
  `import sys`.

In `test_agent_model_drift_schema.py`, inside
`test_corrupted_ids_duplicate_keys_and_observation_shapes_exit_two`, add this
line after the method's last line, at its indentation. It pins D4's message,
which the base already prints (D13):

```python
        self.assertEqual(stderr.getvalue(), "cannot load JSON input\n")
```

In `test_agent_model_drift_scheduling.py`, inside
`RepositoryWiringTest.test_justfile_wires_new_suite_without_dropping_issue_100_boundaries`,
replace the tuple member `"python3 scripts/agent-model-drift.py {{args}}"` with
`'PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}'`
(D7). Then append this method to `RepositoryWiringTest`, which is the file's
last class:

```python

    def test_the_module_run_reaches_main_under_the_command_name(self):
        # The recipe runs the reporter with `-m`; every other drift test calls
        # main() in process (#179 D6).
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_model_drift", "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: agent-model-drift "),
                        completed.stdout[:200])
```

- [ ] **Step 2: Watch the suites fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_model_drift_schema.py 2>&1 | tail -3`
Expected: an import error for `agent_tools.agent_model_drift`, then `FAILED`.

- [ ] **Step 3: Move the modules and make the listed edits**

```bash
git mv scripts/agent-model-drift.py python/agent_tools/agent_model_drift.py
git mv scripts/agent-model-drift-routing.py python/agent_tools/agent_model_drift_routing.py
git mv scripts/agent-model-drift-scheduling.py python/agent_tools/agent_model_drift_scheduling.py
git mv scripts/agent-model-drift-schema.py python/agent_tools/agent_model_drift_schema.py
```

`PK/agent_model_drift_routing.py`: no edit. It is a pure rename.

`PK/agent_model_drift_scheduling.py` (D3):
1. Replace `import hashlib`, `import json`, the blank line and
   `from agent_model_drift_schema import SCHEDULING_METRICS` (L4–7) with these
   two lines:
   `from agent_tools.agent_model_drift_schema import SCHEDULING_METRICS` and
   `from agent_tools.canonical import telemetry_digest`.
2. Delete `def _digest` (L10–13) and the two blank lines after it.
3. In `_validate_pairs` and `_aggregate_metric`, `_digest(` becomes
   `telemetry_digest(` at both call sites.

`PK/agent_model_drift_schema.py` (D3, D4):
1. Delete `import hashlib` (L4). Keep `import importlib.machinery` and
   `import sys`, because `load_validated_matrix` still uses them until Task 2.
2. After `from pathlib import Path`, add one blank line and then
   `from agent_tools.canonical import reject_duplicate_keys, telemetry_digest`.
   One blank line still precedes `_DIGEST`.
3. Delete `def _duplicates` (L30–36) and the two blank lines after it.
4. In `load_json`, pass `object_pairs_hook=reject_duplicate_keys`, and change
   the clause to `except (OSError, ValueError) as error:`. Every member of the
   old tuple except `OSError` is a `ValueError`, and canonical's hook raises a
   plain `ValueError`.
5. Delete `def canonical_digest` (L47–49) and the two blank lines after it.
   Its two call sites, the record check (`… != value["record_id"]`) and the
   baseline check (`… != value["baseline_id"]`), call `telemetry_digest(body)`.
6. Leave `load_validated_matrix` byte-identical (D12).

`PK/agent_model_drift.py` (D2, D3):
1. Delete the shebang (L1), `import importlib.machinery`,
   `import importlib.util` and `from pathlib import Path`.
2. Replace the three loader blocks (L11–29) with these four lines, keeping the
   blank line above them and the two below:
   ```python
   from agent_tools import agent_model_drift_routing as routing_logic
   from agent_tools import agent_model_drift_scheduling as scheduling_logic
   from agent_tools import agent_model_drift_schema as schema
   from agent_tools.canonical import telemetry_digest
   ```
3. In `main`, write `parser = argparse.ArgumentParser(prog="agent-model-drift")`
   and `matrix_digest = telemetry_digest(matrix)`. The rest of `evaluate` and
   `main` does not change.

`justfile`: the `agent-model-drift *args:` body becomes
`  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_model_drift_schema.py tests/test_agent_model_drift_routing.py tests/test_agent_model_drift_scheduling.py tests/test_agent_model_drift_producer_integration.py tests/test_agent_costs.py 2>&1 | tail -3`
Expected: `Ran 138 tests` and `OK`. The same command ran 137 at `$START`.

Run: `git add python/agent_tools && git diff --cached -M --name-status -- scripts python/agent_tools`
The `add` stages the edits, because `git mv` staged only the original content.
Expected: four `R` lines pairing each old path with its module. The reporter
pairs at 75 or more, and the others at 90 or more.

Run the no-loader and no-copy checks. Each of them fails at `$START`:

```bash
set -e
if git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path|__file__|hashlib" -- \
  python/agent_tools/agent_model_drift.py python/agent_tools/agent_model_drift_routing.py \
  python/agent_tools/agent_model_drift_scheduling.py; then exit 1; fi
if git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path" -- \
  tests/agent_model_drift_test_support.py 'tests/test_agent_model_drift_*.py'; then exit 1; fi
if grep -nE "hashlib|def _duplicates|def canonical_digest|canonical_digest\(" \
  python/agent_tools/agent_model_drift_schema.py; then exit 1; fi
diff <(git show "${START}:scripts/agent-model-drift-schema.py" | sed -n '/^def load_validated_matrix/,/^def validate_baseline/p') \
     <(sed -n '/^def load_validated_matrix/,/^def validate_baseline/p' python/agent_tools/agent_model_drift_schema.py)
echo drift-clean
```

Expected: `drift-clean`.

Check the recipe and D4's message:

```bash
just agent-model-drift --help 2>/dev/null | head -1
printf '{"schema_version":1,"schema_version":1}' > "$B/dup.json"
PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_model_drift --record "$B/dup.json" \
  --baseline "$B/dup.json" --matrix-root . --now 2026-09-20T12:00:00Z > "$B/out" 2> "$B/err"; echo "exit=$?"
cat "$B/err"; wc -c < "$B/out"
```

Expected: `usage: agent-model-drift [-h] --record RECORD …`, then `exit=2`,
`cannot load JSON input` and `0`. If the clause is not widened, stderr reads
`duplicate JSON key 'schema_version'` instead.

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line. The imports check now imports the
four new modules.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | tail -3`
Expected: `Ran 1223 tests` and `OK (skipped=2)`. At `$START` it reported
`Ran 1222 tests`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools tests/agent_model_drift_test_support.py \
  tests/test_agent_model_drift_schema.py tests/test_agent_model_drift_routing.py \
  tests/test_agent_model_drift_scheduling.py tests/test_agent_model_drift_producer_integration.py \
  justfile
git commit -m "refactor(agent-tools): move the model-drift family into the package"
```

The `git mv` deletions are already staged. The message ends with the plan's
trailer lines. Run: `git status --porcelain`. Expected: no output.
