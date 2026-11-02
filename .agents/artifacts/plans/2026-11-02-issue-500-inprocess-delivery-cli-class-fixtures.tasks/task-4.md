# Task 4: The orchestrate fixture project is built once per test class

This task implements spec § The orchestrate world (D5, D9) and test seam 4 (D6). Today, every `OrchestrateWorld` builds its committed fixture project from scratch: `git init`, the contract and instruction source, the bound directories, a `resolve-project write-projections` child, then a commit. After this task, an unmutated world copies the project from a template that the first such world in its concrete test class builds. HOME, `bin/` and its shims, `state/`, `cwd/` and `env` are still made per world, and a mutated world still builds its own project. The guard test passes before and after the change by design (D10). This task's falsifiable checks are therefore the scratch build counter and a scratch mutation. This task also owns AC1's combined check.

**Files:**
- Modify: `tests/orchestrate_world.py`
- Modify: `tests/test_orchestrate_control.py`

**Interfaces:**
- Consumes (base): `OrchestrateWorld.__init__(self, case, *, mutate=None, claude_code="supported")`, `_commit_project(self, mutate)` and `git(self, *args) -> str` (`git -C <root>`, `check=True`, `env=self.env`, returns stdout).
- Produces:
  - `OrchestrateWorld(case, *, mutate=None, claude_code="supported")`, with the same signature and attributes (`root`, `home`, `bin`, `state`, `cwd`, `env`, `case`).
  - `git(self, *args) -> str`, unchanged behaviour.
  - Private: `_git_in(self, root: Path, *args) -> str`, `_commit_project(self, root: Path, mutate) -> None` (the same steps, aimed at `root`), `_template(self) -> Path`, and the module-level `_TEMPLATES: dict[type, Path]` keyed by the concrete test class (D9).

**Invariants:**
- An unmutated world's project is a full copy of its class's template: `shutil.copytree(template, self.root, symlinks=True, dirs_exist_ok=True)` (262 H4). No test receives a path into the template.
- The template is built at most once per concrete test class per class run, by exactly the steps `_commit_project` runs today, in a class-scoped temporary directory. Its class cleanups (the directory's removal and `_TEMPLATES.pop(owner, None)`) are registered before the build starts. A failed build caches nothing, and the next world tries again (D5, D9).
- A world with `mutate` builds its own project in `self.root` exactly as today. `claude_code` changes only HOME, so an unmutated world with `claude_code="unsupported"` uses the template.
- The template holds no absolute path, and the environment of the world that builds it leaves no trace in it (spec § The orchestrate world). Shims, HOME, `state/` and `env`, which embed per-world paths, are never shared.
- `PYTHONDONTWRITEBYTECODE` in `self.env` stays exactly as found (D8). `test_admission_replay.py` is unchanged: it always passes `mutate`.

**Scratch build counter.** Write this to `$SCRATCH/count-world-builds.py` and never commit it (262 D6, D10). Run it from the worktree root. It prints `WORLDS <w> BUILDS <b> EXPECTED <e>`, where `<e>` is the number of test classes that build an unmutated world plus the number of mutated worlds. It exits non-zero when a test fails or `<b> != <e>`.

```python
"""Scratch only (262 D6): run test_orchestrate_control and count fixture-project builds."""
import importlib, os, sys, unittest
sys.path.insert(0, os.getcwd())  # run from the tree root
world = importlib.import_module("tests.orchestrate_world").OrchestrateWorld
builds, worlds, init = [], [], world.__init__
sys.addaudithook(lambda event, args: event == "subprocess.Popen"
                 and "write-projections" in map(str, args[1]) and builds.append(1))
def recording(self, case, *, mutate=None, **kwargs):
    worlds.append((type(case).__name__, mutate is None))
    init(self, case, mutate=mutate, **kwargs)
world.__init__ = recording
program = unittest.main(module=None, exit=False, argv=["unittest", "tests/test_orchestrate_control.py"])
expected = len({name for name, plain in worlds if plain}) + sum(not plain for _, plain in worlds)
print(f"WORLDS {len(worlds)} BUILDS {len(builds)} EXPECTED {expected}", file=sys.stderr)
sys.exit(0 if program.result.wasSuccessful() and len(builds) == expected else 1)
```

Counter command (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 "$SCRATCH/count-world-builds.py" 2>&1 | grep -E "^Ran |^OK|^FAILED|^WORLDS"'`

- [ ] **Step 1: Write the guard test**

In `tests/test_orchestrate_control.py`, add this method as the last method of `class WorktreeTest(unittest.TestCase):`, directly before `class StepInputTest(unittest.TestCase):`, with two blank lines before that class:

```python
    def test_a_world_never_sees_another_worlds_git_changes(self):
        """Issue 500 D5, D6: each world's project is its own copy of the fixture commit."""
        first = OrchestrateWorld(self)
        (first.root / "first-only.txt").write_text("first world\n", "utf-8")
        first.git("add", "first-only.txt")
        first.git("commit", "--quiet", "-m", "first world only")
        first.git("branch", "first-only")
        first.git("config", "fixture.owner", "first")
        second = OrchestrateWorld(self)
        self.assertNotEqual(second.root, first.root)
        self.assertEqual(second.git("log", "--format=%s").splitlines(), ["fixture"])
        self.assertFalse((second.root / "first-only.txt").exists())
        self.assertEqual(second.git("branch", "--list", "first-only"), "")
        self.assertNotIn("fixture.owner", second.git("config", "--local", "--list"))
        self.assertEqual(second.git("status", "--porcelain"), "")
```

The second world is built after the first is mutated, so the test also fails if the template were a live world's tree. Every assertion holds for a freshly built world too, so it proves isolation and never sharing (D6).

- [ ] **Step 2: Run the guard and the counter before the change**

1. Focused test form (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py -k test_a_world_never_sees 2>&1 | tail -6'`. Expected: `OK` (a guard, D10).
2. The counter command. Expected: `Ran 48 tests`, `OK`, `WORLDS 56 BUILDS 56 EXPECTED 16`, and a non-zero exit. This is the observation Step 4 must change.

- [ ] **Step 3: Write the minimal implementation**

In `tests/orchestrate_world.py`:
1. Add `import shutil` between `import os` and `import stat`.
2. Directly after the `TOKENS = (...)` line, add:

```python
# The committed unmutated fixture project per concrete test class (issue 500 D5, D9).
_TEMPLATES: dict[type, Path] = {}
```

3. Replace the last line of `__init__`, `self._commit_project(mutate)`, with:

```python
        if mutate is None:
            shutil.copytree(self._template(), self.root, symlinks=True, dirs_exist_ok=True)
        else:
            self._commit_project(self.root, mutate)
```

`self.root` already exists (the `mkdir` loop above creates it empty), which is why `dirs_exist_ok=True` is needed.

4. Add this method between `__init__` and `_commit_project`:

```python
    def _template(self) -> Path:
        """The test class's unmutated committed project, built by its first world (issue 500 D5).

        The class cleanup that removes the directory and the cache entry is registered
        before the build, so a failed build leaves nothing behind and caches nothing.
        """
        owner = type(self.case)
        template = _TEMPLATES.get(owner)
        if template is None:
            tmp = tempfile.TemporaryDirectory()
            owner.addClassCleanup(tmp.cleanup)
            owner.addClassCleanup(_TEMPLATES.pop, owner, None)
            template = Path(tmp.name).resolve() / "project"
            template.mkdir()
            self._commit_project(template, None)
            _TEMPLATES[owner] = template
        return template
```

5. Change `_commit_project(self, mutate)` to `_commit_project(self, root: Path, mutate) -> None`. In its body, every `self.root` becomes `root`, the `write-projections` argument becomes `"--repo-root", str(root)`, and every `self.git(...)` becomes `self._git_in(root, ...)`. Re-indent the continuation of the `project.json` `write_text` call to align under its opening parenthesis. The steps and their order do not change.
6. Split `git` into a public wrapper and a root-taking helper:

```python
    def git(self, *args) -> str:
        return self._git_in(self.root, *args)

    def _git_in(self, root: Path, *args) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, check=True, env=self.env).stdout
```

- [ ] **Step 4: Verify**

All from the worktree root, through `launch-scope exec`:
1. The counter command. Expected: `Ran 48 tests`, `OK`, `WORLDS 56 BUILDS 16 EXPECTED 16`, and exit 0. `RefusalTableTest.test_no_file_is_created_under_the_ledger_root_or_working_directory`, which snapshots the copied project tree, is among the 48.
2. The mutated-world consumer is unchanged (focused test form): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -6'`. Expected: `OK`.
3. Mutation check, never committed. Temporarily replace the `shutil.copytree(...)` line in `__init__` with `self.root = self._template()`, so worlds share the template. Run the Step 2 guard command. Expected: `FAILED (failures=1)`. Then restore the file, and confirm with `git diff --stat -- tests/orchestrate_world.py` that only the Step 3 changes remain.
4. AC1's combined check, all four seams in one run (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_inprocess_cli.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_attempt_migration.py tests/test_orchestrate_control.py -k InProcessRunnerTest -k BuilderTransportTest -k test_each_delivered_207_call_is_the_callers_own_copy -k test_a_world_never_sees_another_worlds_git_changes 2>&1 | tail -6'`. Expected: `Ran 5 tests` and `OK`.
5. The Coverage gate (Global Constraints). Expected: `COVERAGE-GATE-OK base 3575 head 3580 test ids`.

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrate_world.py tests/test_orchestrate_control.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(issue-500): build the orchestrate fixture project once per class" -m "<the session's trailer lines>"
```
