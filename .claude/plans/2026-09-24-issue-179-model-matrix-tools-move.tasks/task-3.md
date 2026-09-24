# Task 3: Ship diff-scope as a package launcher

Decisions: D1, D2, D6, D7, D10, D11, D12; parent D2, D14, D15; #175 D2, D5,
D14. Spec sections "How each file changes (D2–D5)", "Wiring (D1, D6)", "Test
re-points (D6, D7)" and "Living documents (D10)". Work from the worktree root.
`PK` = `python/agent_tools`, `AS` = `home/common/agent-skills`.

**Files:**
- Move: `AS/scripts/diff-scope.py` → `PK/diff_scope.py`, using `git mv` (the
  mode is already 100644)
- Modify: `lib/agent-tools.nix` (the `commands` list)
- Modify: `AS/default.nix` (delete the `.agents/bin/diff-scope` entry)
- Modify: `AS/tests/test_diff_scope.py`
- Modify: `AS/tests/test_workflow_skill_contracts.py` (one comment, L2488)

**Interfaces:**
- Consumes: Task 2's multi-line `commands` list in `lib/agent-tools.nix`,
  which holds `"agent-evidence"` and `"agent-model-matrix"`.
- Produces:
  - The module `agent_tools.diff_scope`, with every existing name unchanged.
  - `commands` gains `"diff-scope"` as its last line.
  - The built `~/.agents/bin/diff-scope` is the generated launcher
    `exec <env>/bin/python3 -I -m agent_tools.diff_scope "$@"`. Skills keep
    calling it by bare name, and ship-issue's size gate does too.

**Invariants:**
- The moved file differs from the original only by its deleted shebang (L1).
  It already pins `prog="diff-scope"`, and its docstring is its `--help`
  description.
- Installed `diff-scope --help` is byte-identical to the base script run through
  a file named `diff-scope` (parent D15).
- The suite keeps every expected value and assertion. Only its code-locating
  lines and its module docstring change.
- `git_env()` copies `os.environ`, so the absolute `PYTHONPATH` reaches children
  that run in scratch repositories.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`. Keep the braces in `${START}:`.

- [ ] **Step 1: Re-point the suite**

In `AS/tests/test_diff_scope.py`:
- Replace the module docstring's body, L3–9, with exactly these lines. The
  first and last docstring lines stay:

```
Two layers, per the design's Test seams section. The classifier layer imports
`agent_tools.diff_scope` and drives the pure classifier over synthetic
rows shaped the way the git layer actually emits them -- a binary row carrying
absent counts rather than zeros, a rename row already reduced to its
destination path. The CLI layer (added with the git layer) runs the module with
`python -m` as a subprocess against scratch git repositories under a
TemporaryDirectory; it talks to no network and touches no repository but its
own.
```

- Delete `import importlib.util` (L14).
- Delete `REPO_ROOT` and `SCRIPT` (L27–28), which have no other use, and
  `def load_module` with its docstring (L31–47). Add
  `from agent_tools import diff_scope` as its own group after
  `import unittest.mock`, with one blank line before it and two after it, so
  `class DiffScopeClassifierTest` follows. The package import registers the
  module in `sys.modules`, which its dataclasses need.
- Make the three `load_module()` calls `diff_scope`. They are
  `cls.module = …` in two `setUpClass` methods and `self.module = …` in one
  `setUp`.
- In `run_helper`, make the argv
  `[sys.executable, "-m", "agent_tools.diff_scope", *arguments]`. In
  `test_a_root_outside_a_work_tree_exits_one`, make it
  `[sys.executable, "-m", "agent_tools.diff_scope", self.range, "--root", outside]`.

In `AS/tests/test_workflow_skill_contracts.py` L2488, change only the comment
line (D10). Its indentation stays. Before and after:

```
        # lives in diff-scope.py and is not restated here.
        # lives in `agent_tools.diff_scope` and is not restated here.
```

- [ ] **Step 2: Watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -3`
Expected: `ImportError: cannot import name 'diff_scope'`, then `FAILED`.

- [ ] **Step 3: Move the module and deploy the launcher**

```bash
git mv home/common/agent-skills/scripts/diff-scope.py python/agent_tools/diff_scope.py
```

Delete the shebang line, and make no other edit.

`lib/agent-tools.nix`: add `    "diff-scope"` as the last line inside
`commands = [ … ];`.

`AS/default.nix`: delete the four-line `".agents/bin/diff-scope" = { … };`
entry and the blank line after it. Touch no other line.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -3`
Expected: `Ran 55 tests` and `OK`. The `PYTHONPATH` must be absolute, because
`run_helper` runs its children in scratch repositories.

Run: `git add python/agent_tools && git diff --cached -M --name-status -- home/common/agent-skills/scripts/diff-scope.py python/agent_tools/diff_scope.py`
Expected: one line, `R<NN>`, with `NN` ≥ 95.

Run these checks. Each of them fails at `$START`:

```bash
set -e
if git grep -nE "importlib|spec_from_file_location|sys\.path|SCRIPT|REPO_ROOT" -- home/common/agent-skills/tests/test_diff_scope.py; then exit 1; fi
if grep -n "^#!" python/agent_tools/diff_scope.py; then exit 1; fi
if git grep -n "diff-scope\.py" -- ':!.claude/specs' ':!.claude/plans'; then exit 1; fi
echo diff-scope-clean
```

Expected: `diff-scope-clean`.

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line.

Check the installed command:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
L="$H/.agents/bin/diff-scope"; cat "$L"
PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L")
git show "${START}:home/common/agent-skills/scripts/diff-scope.py" > "$B/diff-scope"
COLUMNS=80 "$PY" "$B/diff-scope" --help > "$B/help.before"
COLUMNS=80 "$L" --help | cmp - "$B/help.before" && echo help-identical
"$L" "${START}~1..${START}" --root "$PWD" --format json | head -c 120; echo
```

Expected: `cat` shows `exec /nix/store/…/bin/python3 -I -m agent_tools.diff_scope "$@"`,
then `help-identical`, then the start of a JSON object. At `$START` the entry
is the flat script instead.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`. The hostile run and the controls now include `diff-scope`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | tail -3`
Expected: `Ran 1223 tests`, `OK (skipped=2)`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/diff_scope.py lib/agent-tools.nix \
  home/common/agent-skills/default.nix home/common/agent-skills/tests/test_diff_scope.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(agent-tools): ship diff-scope as a package launcher"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
