# Task 4: Ship context-map-lint as a package launcher

Decisions: D1, D2, D6, D7, D8, D10, D11, D12; parent D2, D6, D9, D14, D15;
#175 D5, D8. Spec sections "How each file changes (D2–D5)", "Wiring (D1, D6)",
"Test re-points (D6, D7)", "The installed-layout test (D8)" and "Living
documents (D10)". Work from the worktree root. `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`.

**Files:**
- Move: `scripts/context-map-lint.py` → `PK/context_map_lint.py`, using
  `git mv` (the mode is already 100644). It is the last tracked file in
  `scripts/`.
- Modify: `lib/agent-tools.nix` (one comment line and one row)
- Modify: `AS/default.nix` (delete the `.agents/bin/context-map-lint` entry)
- Modify: `tests/test_context_map_lint.py`
- Modify: `AS/tests/test_workflow_skill_contracts.py` (L399 and L497)
- Modify: `tests/test_agent_tools_launchers.py`
- Modify: `justfile` (the `agent-workflow-tests` list)
- Modify: `CLAUDE.md` (one sentence in the "Agent helper package" paragraph, L46)

**Interfaces:**
- Consumes: the `commands` list after Task 3, which holds `"agent-evidence"`,
  `"agent-model-matrix"` and `"diff-scope"`.
- Produces:
  - The module `agent_tools.context_map_lint`, with every existing name
    unchanged. `main(argv)` still checks a fixed argv shape by hand, because
    D8 keeps it off argparse.
  - The built `~/.agents/bin/context-map-lint` is the generated launcher
    `exec <env>/bin/python3 -I -m agent_tools.context_map_lint "$@"`, at the
    same path other projects' CIs call.
  - In `tests/test_agent_tools_launchers.py`, the module constant
    `MISUSE_USAGE: dict[str, str]`. It maps a launcher name to a line that only
    its module docstring prints. Task 5 adds `LAUNCHER_FLOOR` beside it.

**Invariants:**
- The moved file differs from the original only by its deleted shebang (L1).
  The docstring is the misuse output, so it stays byte-identical (D2).
- Installed `context-map-lint --help` answers the way the base script answers
  under that name: exit 2, empty stdout, and byte-identical stderr (parent D15).
- The hostile run keeps its argparse expectation (exit 0, stdout starting with
  `usage: <name> `) for every launcher outside `MISUSE_USAGE`. Every launcher
  still asserts that the marker appears in neither stream.
- The legacy-surface scan covers all of `python/` (D7).

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`. Keep the braces in `${START}:`.

- [ ] **Step 1: Re-point the lint suite and put it in the recipe**

`tests/test_context_map_lint.py`:
- Add `import sys` after `import subprocess`.
- Change `LINTER` to `REPO_ROOT / "python/agent_tools/context_map_lint.py"`.
  Only `test_source_has_no_policy_discovery` still reads it.
- At the three run sites (`run_lint`, the `relative` run and the `missing` run),
  replace `"python3", str(LINTER),` with
  `sys.executable, "-m", "agent_tools.context_map_lint",`.

`justfile`: in `agent-workflow-tests`, add the line
`    tests/test_context_map_lint.py \` directly before
`    tests/test_branch_protection.py`. Change no other line.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_context_map_lint.py 2>&1 | tail -3`
Expected: `FAILED`. The children exit 1 with
`No module named agent_tools.context_map_lint`, and the source scan cannot find
its file.

- [ ] **Step 2: Move the module and re-point the contracts test**

```bash
git mv scripts/context-map-lint.py python/agent_tools/context_map_lint.py
```

Delete the shebang line, and make no other edit.

In `AS/tests/test_workflow_skill_contracts.py` (D7):
- In `test_living_source_has_no_legacy_policy_surface`, the pathspec member
  `"scripts/context-map-lint.py"` becomes `"python"`. The scan then covers all
  seven moved sources, and every `python/` file is free of legacy tokens today.
- In `_install_policy_surface_fixture`, the copy source
  `REPO_ROOT / "scripts/context-map-lint.py"` becomes
  `REPO_ROOT / "python/agent_tools/context_map_lint.py"`.
  `test_installed_policy_surface_matches_source_contract` is unchanged. After a
  switch, the installed linter is the launcher: a regular executable file with
  no legacy token.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_context_map_lint.py 2>&1 | tail -3`
Expected: `Ran 4 tests` and `OK`.

- [ ] **Step 3: Deploy the launcher and watch the installed test fail**

`lib/agent-tools.nix`: directly under
`  # A command's module is its name with each "-" replaced by "_".`, add this
line:

```nix
  # context-map-lint is a stable path other projects' CIs call without vendoring it (parent D15).
```

Then insert `    "context-map-lint"` between `    "agent-model-matrix"` and
`    "diff-scope"`.

`AS/default.nix`: delete the comment
`# Stable path project CIs can call without vendoring the script.`, the
four-line `".agents/bin/context-map-lint" = { … };` entry under it, and the
blank line after it. Touch no other line.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR):|AssertionError|^Ran |^OK|FAILED" | head -6`
Expected: `FAIL: test_a_hostile_agent_tools_on_every_channel_is_ignored … (launcher='context-map-lint')`
with `AssertionError: 2 != 0`, then `FAILED`. The linter answers `--help` as
misuse, which is what Step 4's map pins.

- [ ] **Step 4: Pin the misuse answer in the installed test**

In `tests/test_agent_tools_launchers.py`:
- In the module docstring's first line, change `(#175 D8, D11; parent D9)` to
  `(#175 D8, D11; #179 D8; parent D9)`.
- After `TIMEOUT_SECONDS = 60`, add:

```python
# Commands without an argparse parser answer `--help` as misuse, with the
# module docstring on stderr and exit 2. Their CLI is promised unchanged
# (parent D15), so the probe pins that answer by a line only the module's own
# docstring prints.
MISUSE_USAGE = {"context-map-lint": "Usage: context-map-lint --repo-root "}
```

- In `test_a_hostile_agent_tools_on_every_channel_is_ignored`, replace the
  body's three assertions after `completed = self.run_child(…)` with the
  following. An import failure prints a traceback, never that docstring line,
  so the mapped assertion still proves the module's own argument handling ran:

```python
                if name in MISUSE_USAGE:
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn(MISUSE_USAGE[name], completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertTrue(completed.stdout.startswith(f"usage: {name} "),
                                    completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)
```

The controls need no change. The fake package's `__init__` exits 97 before any
command code runs, so they hold for every launcher.

- [ ] **Step 5: Re-point the architecture note**

In `CLAUDE.md` L46, replace only this sentence:

> The other helpers are still flat scripts under `scripts/` and `home/common/agent-skills/scripts/` and move in cluster by cluster, while `docs/standards/agent-helpers.md` sends all new helper code to the package.

with:

> The remaining Python helpers are still flat scripts under `home/common/agent-skills/scripts/`, plus the sdd skill's `review-package`, and move in cluster by cluster, while `docs/standards/agent-helpers.md` sends all new helper code to the package.

Keep the paragraph on its one line. `docs/standards/` is unchanged: its
`scripts/**` glob still catches a new flat script (D10).

- [ ] **Step 6: Verify**

Run: `git add python/agent_tools && git diff --cached -M --name-status -- scripts/context-map-lint.py python/agent_tools/context_map_lint.py`
Expected: one line, `R<NN>`, with `NN` ≥ 95.

Run these checks. Each of them fails at `$START`:

```bash
set -e
test -z "$(git ls-files scripts)"
if git grep -n "context-map-lint\.py" -- ':!.claude/specs' ':!.claude/plans'; then exit 1; fi
if git grep -nE "importlib|spec_from_file_location|sys\.path|\"python3\"" -- tests/test_context_map_lint.py; then exit 1; fi
if grep -n "^#!" python/agent_tools/context_map_lint.py; then exit 1; fi
if grep -n 'flat scripts under `scripts/`' CLAUDE.md; then exit 1; fi
grep -q 'plus the sdd skill.s `review-package`' CLAUDE.md
echo lint-clean
```

Expected: `lint-clean`.

Run: `WORKFLOW_POLICY_SURFACE=source PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `Ran 153 tests`, `OK (skipped=1)`.

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line.

Check the installed command against the base script, run under the launcher's
interpreter through a file named for the command:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
L="$H/.agents/bin/context-map-lint"; cat "$L"
PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L")
git show "${START}:scripts/context-map-lint.py" > "$B/context-map-lint"
"$PY" "$B/context-map-lint" --help > "$B/out.before" 2> "$B/err.before"; echo "before=$?"
"$L" --help > "$B/out.after" 2> "$B/err.after"; echo "after=$?"
cmp "$B/err.before" "$B/err.after" && cmp "$B/out.before" "$B/out.after" && echo misuse-identical
T=$(mktemp -d); touch "$T/main.py"
printf -- '---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n' > "$T/area.md"
printf '## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n' > "$T/CONTEXT-MAP.md"
"$L" --repo-root "$T" --context-map "$T/CONTEXT-MAP.md"; echo "lint=$?"
```

Expected: `cat` shows `exec /nix/store/…/bin/python3 -I -m agent_tools.context_map_lint "$@"`,
then `before=2`, `after=2` and `misuse-identical`. Last come
`context-map-lint: <resolved root> OK` and `lint=0`.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`, where Step 3 showed a failure.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | tail -3`
Expected: `Ran 1227 tests`, `OK (skipped=2)`. The 4 added tests are the lint
suite.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/context_map_lint.py lib/agent-tools.nix \
  home/common/agent-skills/default.nix tests/test_context_map_lint.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  tests/test_agent_tools_launchers.py justfile CLAUDE.md
git commit -m "feat(agent-tools): ship context-map-lint as a package launcher"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
