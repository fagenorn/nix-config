# Task 2: Ship agent-model-matrix as a package launcher

Decisions: D1, D2, D3, D5, D6, D11, D12; parent D2, D11, D12, D14, D15; #175
D2, D5, D6, D14. Spec sections "How each file changes (D2–D5)", "The packaged
validator (D5)", "Wiring (D1, D6)" and "Test re-points (D6, D7)". Work from the
worktree root. `PK` = `python/agent_tools`, `AS` = `home/common/agent-skills`.

**Files:**
- Move: `AS/scripts/agent-model-matrix.py` → `PK/agent_model_matrix.py`, using
  `git mv` (the mode is already 100644)
- Modify: `PK/agent_model_drift_schema.py` (from Task 1)
- Modify: `lib/agent-tools.nix` (the `commands` list, L39)
- Modify: `AS/default.nix` (delete the `.agents/bin/agent-model-matrix` entry)
- Modify: `AS/tests/test_agent_model_matrix.py`
- Modify: `tests/agent_model_drift_test_support.py` (`matrix_fixture`)
- Modify: `justfile` (the `agent-model-matrix` recipe, L99–100)

**Interfaces:**
- Consumes: `agent_tools.canonical.reject_duplicate_keys`. Task 1's
  `agent_tools.agent_model_drift_schema`, whose `load_validated_matrix(root)`
  still loads the flat validator by path.
- Produces:
  - The module `agent_tools.agent_model_matrix`. It keeps every existing name
    except `_reject_duplicate_keys`, which it no longer defines. Its public
    functions `validate(root) -> list[str]`, `load_matrix(root) -> dict` and
    `trace(root, scenario) -> list[dict]` keep their signatures.
  - `commands` in `lib/agent-tools.nix` is now a list, one name per line:
    `"agent-evidence"`, `"agent-model-matrix"`. Tasks 3 and 4 add to it.
  - The built `~/.agents/bin/agent-model-matrix` is the generated launcher
    `exec <env>/bin/python3 -I -m agent_tools.agent_model_matrix "$@"`.

**Invariants:**
- The moved file differs from the original by exactly these edits (D2, D3):
  1. The shebang (L1) is deleted.
  2. `from agent_tools.canonical import reject_duplicate_keys` is added as its
     own import group, one blank line after `from typing import Any`. Two
     blank lines still precede `MATRIX_PATH`. `Any` stays, because it has other
     uses.
  3. `def _reject_duplicate_keys` (L68–74) and the two blank lines after it
     are deleted.
  4. `load_matrix` passes `object_pairs_hook=reject_duplicate_keys`. Its
     `except (OSError, json.JSONDecodeError, ValueError)` clause is untouched,
     so a duplicate key still reads `cannot load <path>: duplicate JSON key '<k>'`.
  5. `_parser` builds `argparse.ArgumentParser(prog="agent-model-matrix", description=__doc__)`.
     The module docstring is that description and is not edited.
- Installed `agent-model-matrix --help` is byte-identical to the base script run
  through a file named `agent-model-matrix` (parent D15, #175 D5).
- The matrix root supplies data only. `load_validated_matrix` never reads a
  Python file under the root (D5).
- No test mutates `agent_model_matrix` state, so all tests share the one import.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`. Keep the braces in `${START}:`, because in zsh `$START:h…` applies
the `:h` modifier.

- [ ] **Step 1: Re-point the matrix suite and drop the fixture's script copy**

`AS/tests/test_agent_model_matrix.py`:
- Delete `import importlib.util` (L3), `SCRIPT = …` (L13) and `def load_module`
  (L292–298) with the two blank lines after it.
- Add `from agent_tools import agent_model_matrix` as its own group, with one
  blank line after `import unittest` and two before `REPO_ROOT`.
- Replace all 15 occurrences of `module = load_module()` with
  `module = agent_model_matrix`.
- In the CLI test near L670, make the argv
  `[sys.executable, "-m", "agent_tools.agent_model_matrix", "validate", "--root", str(root)]`.

`tests/agent_model_drift_test_support.py`: in `matrix_fixture`, delete the list
member `Path("home/common/agent-skills/scripts/agent-model-matrix.py")`, so the
list starts `paths=[Path("home/common/agent-skills/model-matrix.json")]+[…`. Its
only reader was the file-path load that Step 3 deletes (D5).

- [ ] **Step 2: Watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py 2>&1 | tail -3`
Expected: `ImportError: cannot import name 'agent_model_matrix'`, then `FAILED`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_model_drift_schema.py 2>&1 | tail -3`
Expected: `FAILED`. The fixture root now has no validator script, so the
reporter answers `matrix validation failed` with exit 2 where tests expect a
report.

- [ ] **Step 3: Move the validator and take over the drift load**

```bash
git mv home/common/agent-skills/scripts/agent-model-matrix.py python/agent_tools/agent_model_matrix.py
```

Apply the five edits under Invariants, and nothing else.

In `PK/agent_model_drift_schema.py` (D5):
1. Delete `import importlib.machinery` and `import sys`. Nothing else in the
   module uses them.
2. Add `from agent_tools import agent_model_matrix` directly above
   `from agent_tools.canonical import reject_duplicate_keys, telemetry_digest`.
3. Replace `load_validated_matrix` with exactly this. The `sys.modules` save and
   restore go with the loader:

```python
def load_validated_matrix(root):
    root = Path(root)
    try:
        errors = agent_model_matrix.validate(root)
        if errors:
            raise InputError("matrix validation failed")
        return agent_model_matrix.load_matrix(root)
    except Exception as error:
        raise InputError("matrix validation failed") from error
```

- [ ] **Step 4: Deploy the launcher and switch the recipe**

`lib/agent-tools.nix`: replace `  commands = [ "agent-evidence" ];` with

```nix
  commands = [
    "agent-evidence"
    "agent-model-matrix"
  ];
```

`AS/default.nix`: delete the four-line `".agents/bin/agent-model-matrix" = { … };`
entry and the blank line after it. Touch no other line. A leftover entry would
be a conflicting definition beside the launcher (#175 D5).

`justfile`: the `agent-model-matrix:` body becomes these two lines:

```
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix validate
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix trace representative
```

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py tests/test_agent_model_drift_schema.py tests/test_agent_model_drift_routing.py tests/test_agent_model_drift_scheduling.py tests/test_agent_model_drift_producer_integration.py 2>&1 | tail -3`
Expected: `Ran 76 tests` and `OK`. Every drift CLI test now runs against a root
with no validator script, which exercises D5.

Run: `git add python/agent_tools && git diff --cached -M --name-status -- home/common/agent-skills/scripts/agent-model-matrix.py python/agent_tools/agent_model_matrix.py`
Expected: one line, `R<NN>`, with `NN` ≥ 95.

Run these checks. Each of them fails at `$START`:

```bash
set -e
if git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path|__file__" -- python/agent_tools; then exit 1; fi
if git grep -nE "importlib|spec_from_file_location|sys\.path|agent-model-matrix\.py" -- \
  home/common/agent-skills/tests/test_agent_model_matrix.py tests/agent_model_drift_test_support.py; then exit 1; fi
if grep -nE "_reject_duplicate_keys|^#!" python/agent_tools/agent_model_matrix.py; then exit 1; fi
if git grep -n "agent-model-matrix\.py" -- ':!.claude/specs' ':!.claude/plans'; then exit 1; fi
echo matrix-clean
```

Expected: `matrix-clean`.

Run: `just agent-model-matrix 2>/dev/null | head -2`
Expected: `agent model matrix: valid`, then the first representative trace line
(`{"dispatch":"orchestration-issue-owner",…}`).

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line.

Check the installed command. Compare it with the base script run under the
launcher's own interpreter, through a file named for the command:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
L="$H/.agents/bin/agent-model-matrix"; cat "$L"
PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L")
git show "${START}:home/common/agent-skills/scripts/agent-model-matrix.py" > "$B/agent-model-matrix"
COLUMNS=80 "$PY" "$B/agent-model-matrix" --help > "$B/help.before"
COLUMNS=80 "$L" --help | cmp - "$B/help.before" && echo help-identical
"$L" validate --root "$PWD"
```

Expected: `cat` shows `unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE`
and `exec /nix/store/…/bin/python3 -I -m agent_tools.agent_model_matrix "$@"`.
Then `help-identical`, then `agent model matrix: valid`. At `$START` the
entry is the flat script instead.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`. The hostile run and the controls now include
`agent-model-matrix`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | tail -3`
Expected: `Ran 1223 tests`, `OK (skipped=2)`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_model_matrix.py python/agent_tools/agent_model_drift_schema.py \
  lib/agent-tools.nix home/common/agent-skills/default.nix \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  tests/agent_model_drift_test_support.py justfile
git commit -m "feat(agent-tools): ship agent-model-matrix as a package launcher"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
