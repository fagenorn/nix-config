# Task 2: Every activation clears the library cache, documented

**Files:**
- Modify: `home/common/agent-skills/default.nix`
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Modify: `home/common/agent-skills/README.md`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (two docstrings, no code)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (`LibraryBytecodeClearTest.test_every_activation_runs_the_clear_after_link_generation`)

Spec: `.agents/artifacts/specs/2026-11-03-issue-567-installed-module-bytecode-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/567.

**Interfaces:**
- Consumes (Task 1): `home/common/agent-skills/scripts/clear-library-bytecode LIBRARY`. It exits 0 when it cleared or had nothing to clear. Otherwise it exits non-zero, and its own error is on stderr. Also the test constant `CLEAR_BYTECODE = SCRIPTS / "clear-library-bytecode"` and the class `LibraryBytecodeClearTest(unittest.TestCase)`, the module's last class. From Home Manager's activation library: `run CMD…` runs the command, but under `DRY_RUN` it only prints it. `errorEcho TEXT` prints a colored line on stdout and does not exit. The activation script runs under `set -eu -o pipefail`.
- Produces: the activation entry `home.activation.clearAgentModuleBytecode`, and the README section `## Installed module library` that both docstrings point to. No later task consumes them.

**Invariants:**
- The entry is `lib.hm.dag.entryAfter [ "linkGeneration" ]`, and it runs unconditionally on every activation (D1).
- It runs the script's store copy as `${pkgs.runtimeShell} ${./scripts/clear-library-bytecode} "$HOME/.agents/lib/python"`, through `run` (D7). A failure goes to `|| errorEcho …`, so the switch continues and nothing is muted (D4).
- The script gets no `home.file` entry and no `~/.agents/bin` row (D7). No loader code changes. In `workflow-state.py` only the `_delivery()` and `_artifact_budget()` docstrings change (D5).
- `CLAUDE.md` and `python/README.md` are unchanged. The agent-skills README is the one home for this contract (spec § Documentation).

- [ ] **Step 1: Write the failing test**

Add this method as the last method of `LibraryBytecodeClearTest`:

```python
    def test_every_activation_runs_the_clear_after_link_generation(self):
        nix = (ROOT / "home/common/agent-skills/default.nix").read_text(encoding="utf-8")
        header = ('home.activation.clearAgentModuleBytecode = '
                  'lib.hm.dag.entryAfter [ "linkGeneration" ] \'\'\n')
        self.assertEqual(nix.count(header), 1)
        body = nix.split(header, 1)[1].split("\n  '';\n", 1)[0]
        command = ('run ${pkgs.runtimeShell} ${./scripts/clear-library-bytecode} '
                   '"$HOME/.agents/lib/python"')
        self.assertEqual(body.count(command), 1)
        self.assertIn("|| errorEcho ", body.split(command, 1)[1])
        self.assertTrue(CLEAR_BYTECODE.is_file())
```

- [ ] **Step 2: Run the test and watch it fail**

Run from the worktree root (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k test_every_activation_runs_the_clear 2>&1 | grep -E 'AssertionError|^Ran|^FAILED|^OK'`
Expected: `AssertionError: 0 != 1`, `Ran 1 test`, `FAILED (failures=1)`, because there is no activation entry yet. Planning confirmed this on a scratch copy of the planned Task 1 tree.

- [ ] **Step 3: Add the activation entry**

In `home/common/agent-skills/default.nix`, insert this block directly after the `home.activation.reportRetiredSkills` entry's closing `'';`, with one blank line before and after it:

```nix
  # Installed agent modules are links into the store, where every file has
  # modification time 1, so bytecode cached beside a link could outlive a
  # same-size edit. Once the links are updated, every activation removes the
  # library's bytecode cache; a failure is reported and the switch goes on
  # (issue 567; README § Installed module library).
  home.activation.clearAgentModuleBytecode = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    run ${pkgs.runtimeShell} ${./scripts/clear-library-bytecode} "$HOME/.agents/lib/python" \
      || errorEcho "Clearing $HOME/.agents/lib/python/__pycache__ failed (see the error above). While it remains, an installed agent module may run stale bytecode: remove it and any .pycache-clear.* directory beside it by hand."
  '';
```

Planning evaluated this exact block. It ran under stand-ins for `run` and `errorEcho` with `set -eu -o pipefail`. With a writable library the cache was gone. With a read-only library, `mktemp`'s error came first, then the error line, then the following step ran. With `DRY_RUN` set, it printed the command and the cache stayed.

- [ ] **Step 4: Document it**

1. In `home/common/agent-skills/README.md`, insert this section between `## Retired skills` (its paragraph) and `## Claude-only skills and the Codex stub`, with one blank line around each part:

```markdown
## Installed module library

`~/.agents/lib/python/` holds the installed agent modules as links into the Nix store, where every file has modification time 1: five file links (`artifact_budget.py`, `host_admission.py`, `workflow_delivery.py`, `workflow_delivery_build.py`, `workflow_delivery_wire.py`) and the whole-directory link `delivery_model` (`recursive = false`). A module imported through a file link caches its bytecode in the library's own `__pycache__`, named after the link, and CPython's default check compares only the source's modification time and size, so after a switch that repoints a link at a same-size edit the old bytecode would keep running. The activation step `clearAgentModuleBytecode` therefore runs `home/common/agent-skills/scripts/clear-library-bytecode` on the library on every activation, after `linkGeneration` has updated the links (a dry run only prints the command). The first load after a switch compiles its module's source and caches it where it always has, and later loads read that cache. The script renames `__pycache__` into a fresh `.pycache-clear.XXXXXX` directory inside the library and only then removes that directory, so a process writing bytecode at that moment cannot make the removal fail: CPython writes each bytecode file by path, through a temporary name and a rename, and skips a write it cannot make. When a step fails, its own error is followed by an activation error line naming the cache, the stale-bytecode risk while it remains and the manual remedy (remove it and any `.pycache-clear.*` directory beside it), and the switch goes on. Only the top-level cache is cleared, on the premise that every library entry is a file link or a whole-directory link: a whole-directory link's cache would resolve into the read-only store, where nothing is written, so an entry of another shape, such as a `recursive = true` directory, would need its own clear. `workflow-state`'s `_artifact_budget()` loads its module's resolved store file instead (issue 498 D7). Three gaps stay open: a load that starts compiling a module before the links change and writes its bytecode after the clear can leave one file compiled from the old source, stale after a same-size edit until the next switch (issue 567 D3); rolling back to a generation older than this step runs no clear; and a process that imported a module before a switch keeps the old code until it exits.
```

Before committing, check every claim in the paragraph against the committed script and the Nix entry, and correct any that does not hold.

2. In `home/common/agent-skills/scripts/workflow-state.py`, the `_delivery()` docstring's second paragraph becomes:

```text
    The delivery module is imported from its file through the import system, so
    its bytecode is cached like any import's (issue 499): the `scripts` sibling
    in the source layout, `~/.agents/lib/python/workflow_delivery.py`
    installed. Installed, the production launcher caches it in
    `~/.agents/lib/python/__pycache__`, which every Home Manager activation
    clears once the links are updated (issue 567; the agent-skills README,
    § Installed module library). Each load executes a fresh module that is
    registered nowhere in `sys.modules`. The notes limit is read from the
    artifact-budget policy on every call. A load that fails is not kept, so the
    next call loads again.
```

3. The `_artifact_budget()` docstring's second paragraph becomes:

```text
    It is loaded from the resolved target of `artifact_budget_paths()`'s module
    file; installed, that is a store file whose name changes with its content
    (issue 498 D7). Modules loaded through a `~/.agents/lib/python` link rely
    instead on every Home Manager activation clearing that directory's bytecode
    cache (issue 567; the agent-skills README, § Installed module library). The
    module is registered in `sys.modules` before it executes, as its
    dataclasses require, and unregistered if loading fails. Any failure is a
    `WorkflowError`.
```

The first line and the closing `"""` of each docstring do not change, and no other line of `workflow-state.py` does either.

- [ ] **Step 5: Verify**

1. Green (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k LibraryBytecodeClearTest -k test_a_same_size_module_edit -k test_a_second_init_run_compiles_nothing 2>&1 | tail -3`
   Expected: `Ran 7 tests` and `OK`.
2. Docs gates (instant), run from the worktree root. Any non-zero exit means the docs are incomplete:
   `R=home/common/agent-skills/README.md; W=home/common/agent-skills/scripts/workflow-state.py; test "$(grep -c '^## Installed module library$' $R)" = 1 && test "$(grep '^## ' $R | grep -A1 -x '## Retired skills' | tail -1)" = '## Installed module library' && grep -q clearAgentModuleBytecode $R && test "$(grep -c '§ Installed module library' $W)" = 2 && test "$(grep -c 'could outlive a' $W)" = 0 && test "$(git diff --numstat HEAD -- $W | cut -f2)" -le 12`
3. Build (timeout 3600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- just build`
   Expected: exit 0. Then (instant): `gen=$(nix-store --query --requisites ./result | grep -- '-home-manager-generation$') && test "$(printf '%s\n' "$gen" | wc -l)" -eq 1 && awk '/"Activating %s" "linkGeneration"/{l=NR} /"Activating %s" "clearAgentModuleBytecode"/{c=NR} END{exit !(l && c > l)}' "$gen/activate" && grep -c 'clear-library-bytecode' "$gen/activate"`
   Expected: prints `1` and exits 0. That shows the built activation runs the script, after `linkGeneration`.

Do not run `just switch` (CLAUDE.md: switch only when asked).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/default.nix home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/README.md home/common/agent-skills/scripts/workflow-state.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(issue-567): clear installed module bytecode on every activation" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | sort | tr '\n' ' ')" = "home/common/agent-skills/README.md home/common/agent-skills/default.nix home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py "`
Expected: exit 0.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"a0426b122da534e51e0ad43af82cc6ac990431d4","head":"f7142588eb523f60d5b56dea833feca47801d3d8"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":4,"record_bytes":4096,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"home/common/agent-skills/default.nix"},{"bounds":[{"added_lines":225,"boundary":"all","deleted_lines":16,"record_bytes":24576,"support":{"covers":["r1b","r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":2,"record_bytes":16384,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":14,"record_bytes":8192,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":2,"owner":2,"path":"home/common/agent-skills/scripts/workflow-state.py"}]}}
```
