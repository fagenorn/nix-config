# Task 1: The clearing script and its proofs

**Files:**
- Create: `home/common/agent-skills/scripts/clear-library-bytecode` (mode 100755)
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (`DeliveryAdmissionTest.test_a_same_size_module_edit_runs_after_the_library_cache_is_cleared`, the new class `LibraryBytecodeClearTest`, and the unchanged `DeliveryAdmissionTest.test_a_second_init_run_compiles_nothing_into_its_bytecode_cache`)

Spec: `.agents/artifacts/specs/2026-11-03-issue-567-installed-module-bytecode-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/567.

**Interfaces:**
- Consumes: the installed layout that `workflow-state` reads when its script's directory is not named `scripts`. `_delivery()` loads `~/.agents/lib/python/workflow_delivery.py` by its link path and refuses with `WorkflowError("delivery runtime: interface")` unless `WORKFLOW_DELIVERY_INTERFACE_VERSION == 1`. `main` prints `workflow-state: <error>` on stderr and returns 2. `workflow_delivery.py` line 16 is `WORKFLOW_DELIVERY_INTERFACE_VERSION = 1`, the only line with that text. The module constants `ROOT`, `SCRIPTS`, `MODEL`, `POLICY`, `NOW` and the imports (`importlib.util`, `os`, `shutil`, `subprocess`, `sys`, `tempfile`, `unittest`, `mock`) already exist in the test module.
- Produces, for Task 2: the module constant `CLEAR_BYTECODE = SCRIPTS / "clear-library-bytecode"` and the class `LibraryBytecodeClearTest(unittest.TestCase)`, placed last before `if __name__ == "__main__":`. Also the script's argv contract (D7): `clear-library-bytecode LIBRARY`. With an argument count other than one it exits 2 with a usage line on stderr. With no `LIBRARY/__pycache__` (as a file, directory or link), or no `LIBRARY`, it exits 0 and creates nothing. Otherwise it runs `mktemp -d "LIBRARY/.pycache-clear.XXXXXX"`, then `mv` of the cache into that directory (one rename), then `rm -rf` of that directory, and exits 0. Any failing step exits with that command's status, and its own error is on stderr.

**Invariants:**
- No `LIBRARY` entry other than `__pycache__` is created, changed or removed, and nothing a link points at is touched (D5).
- The script uses only `mktemp -d <template>`, `mv --` and `rm -rf --`, in forms GNU and BSD share, with `set -eu`. Nothing is muted: no `|| true`, no `2>/dev/null` (D3).
- Every new test runs the script as `bash <CLEAR_BYTECODE> …`, never by its mode or a `PATH` lookup (D7).
- The seam-1 test's children inherit the test's environment minus `PYTHONPYCACHEPREFIX` and `PYTHONDONTWRITEBYTECODE`, so bytecode lands in the library's own `__pycache__`, as under the production `-I` launcher. Their `agent_tools` imports then cache beside the checkout's sources, which git ignores (spec § Test seams 1).
- The stale-load negative control comes before the clear, and the AC2 unchanged-cache check comes after it (D6).
- The existing tests, the recipe's member list and every loader stay unchanged (D1, D5, #499 D6).
- The script's header comment states that the activation runs it. Task 2 of this plan adds that wiring.

- [ ] **Step 1: Write the failing tests**

Add this constant directly after `ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"`:

```python
CLEAR_BYTECODE = SCRIPTS / "clear-library-bytecode"
```

Insert this method into `DeliveryAdmissionTest`, directly after `test_a_second_init_run_compiles_nothing_into_its_bytecode_cache`:

```python
    def test_a_same_size_module_edit_runs_after_the_library_cache_is_cleared(self):
        """Issue 567 AC1 and AC2 in the installed layout (D6). Every stand-in
        store file has modification time 1. A relink to a same-size variant of
        the delivery module still runs its cached old code (the negative
        control); after `clear-library-bytecode` the edited code runs, and a
        further load compiles nothing. The children inherit no bytecode prefix,
        so, like the production launcher, they cache in the library itself."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve(); home = base / "home"; store = base / "store"
            store.mkdir()
            for name in ("workflow-state.py", "workflow_delivery.py", "workflow_delivery_wire.py",
                         "workflow_delivery_build.py", "artifact_budget.py", "artifact-budget"):
                shutil.copy2(SCRIPTS / name, store / name)
            shutil.copy2(ROOT / "python/agent_tools/host_admission.py", store / "host_admission.py")
            shutil.copy2(POLICY, store / "artifact-budget-policy.json")
            shutil.copytree(MODEL.parent, store / "delivery_model")
            for path in store.rglob("*"):
                if path.is_file():
                    os.utime(path, (1, 1))
            binary = home / ".agents/bin"; library = home / ".agents/lib/python"
            share = home / ".agents/share"
            for directory in (binary, library, share): directory.mkdir(parents=True)
            cli = binary / "workflow-state"; cli.symlink_to(store / "workflow-state.py")
            (binary / "artifact-budget").symlink_to(store / "artifact-budget")
            links = ("artifact_budget.py", "workflow_delivery.py", "workflow_delivery_wire.py",
                     "workflow_delivery_build.py", "host_admission.py")
            for name in links:
                (library / name).symlink_to(store / name)
            (library / "delivery_model").symlink_to(store / "delivery_model", target_is_directory=True)
            (share / "artifact-budget-policy.json").symlink_to(store / "artifact-budget-policy.json")
            env = {key: value for key, value in os.environ.items()
                   if key not in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")}
            env["HOME"] = str(home)
            cache = library / "__pycache__"

            def init_run(name):
                repo = base / name; repo.mkdir()
                return subprocess.run([sys.executable, str(cli), "init-run",
                    "--repo-root", str(repo), "--creation-key", "bytecode", "--now", NOW],
                    capture_output=True, text=True, env=env, check=False)

            def cached():
                return {str(path.relative_to(cache)): (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in cache.rglob("*") if path.is_file()}

            with mock.patch.object(sys, "pycache_prefix", None):
                delivery = Path(importlib.util.cache_from_source(
                    str(library / "workflow_delivery.py")))
            first = init_run("first")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(delivery.is_file(), delivery)
            original = store / "workflow_delivery.py"; source = original.read_bytes()
            old = b"WORKFLOW_DELIVERY_INTERFACE_VERSION = 1\n"
            self.assertEqual(source.count(old), 1)
            variant = base / "next/workflow_delivery.py"; variant.parent.mkdir()
            variant.write_bytes(source.replace(old, b"WORKFLOW_DELIVERY_INTERFACE_VERSION = 2\n"))
            os.utime(variant, (1, 1))
            self.assertEqual((variant.stat().st_size, variant.stat().st_mtime),
                             (original.stat().st_size, 1))
            (library / "workflow_delivery.py").unlink()
            (library / "workflow_delivery.py").symlink_to(variant)
            stale = cached()
            control = init_run("control")
            self.assertEqual(control.returncode, 0, control.stderr)
            self.assertEqual(cached(), stale)
            cleared = subprocess.run(["bash", str(CLEAR_BYTECODE), str(library)],
                                     capture_output=True, text=True, check=False)
            self.assertEqual((cleared.returncode, cleared.stdout, cleared.stderr), (0, "", ""))
            self.assertEqual(sorted(path.name for path in library.iterdir()),
                             sorted((*links, "delivery_model")))
            edited = init_run("edited")
            self.assertEqual((edited.returncode, edited.stdout), (2, ""))
            self.assertIn("workflow-state: delivery runtime: interface", edited.stderr)
            self.assertTrue(delivery.is_file(), delivery)
            settled = cached()
            again = init_run("again")
            self.assertEqual(again.returncode, 2, again.stderr)
            self.assertEqual(cached(), settled)
```

Append this class after the module's last test class, with two blank lines before it and before `if __name__ == "__main__":`:

```python
class LibraryBytecodeClearTest(unittest.TestCase):
    """Issue 567: `clear-library-bytecode` on its own (D2, D3, D7)."""

    def clear(self, *args):
        return subprocess.run(["bash", str(CLEAR_BYTECODE), *map(str, args)],
                              capture_output=True, text=True, check=False)

    @staticmethod
    def entries(library):
        """The library's top-level entries other than `__pycache__`, by kind and content."""
        found = {}
        for path in library.iterdir():
            if path.name == "__pycache__":
                continue
            if path.is_symlink():
                found[path.name] = ("link", os.readlink(path))
            elif path.is_file():
                found[path.name] = ("file", path.read_bytes())
            else:
                found[path.name] = ("directory",)
        return found

    def test_the_clear_removes_the_library_cache_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); library = base / "lib"; package = base / "package"
            (package / "__pycache__").mkdir(parents=True)
            (package / "__init__.py").write_bytes(b"X = 1\n")
            (package / "__pycache__/__init__.cpython-313.pyc").write_bytes(b"kept")
            target = base / "module.py"; target.write_bytes(b"Y = 2\n")
            library.mkdir()
            (library / "module.py").symlink_to(target)
            (library / "package").symlink_to(package, target_is_directory=True)
            (library / "regular.py").write_bytes(b"Z = 3\n")
            cache = library / "__pycache__"; (cache / "nested").mkdir(parents=True)
            for name in ("module.cpython-313.pyc", "module.cpython-314.pyc", "nested/entry"):
                (cache / name).write_bytes(b"bytecode")
            before = self.entries(library)
            result = self.clear(library)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertFalse(os.path.lexists(cache))
            self.assertEqual(sorted(path.name for path in library.iterdir()),
                             ["module.py", "package", "regular.py"])
            self.assertEqual(self.entries(library), before)
            self.assertEqual((target.read_bytes(), (package / "__init__.py").read_bytes(),
                              (package / "__pycache__/__init__.cpython-313.pyc").read_bytes()),
                             (b"Y = 2\n", b"X = 1\n", b"kept"))

    def test_the_clear_without_a_cache_or_a_library_changes_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); library = base / "lib"; library.mkdir()
            (library / "module.py").symlink_to(base / "module.py")
            for target in (library, base / "missing"):
                with self.subTest(target=target.name):
                    result = self.clear(target)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(sorted(path.name for path in base.iterdir()), ["lib"])
            self.assertEqual(sorted(path.name for path in library.iterdir()), ["module.py"])

    @unittest.skipIf(os.geteuid() == 0, "file permissions do not bind root")
    def test_a_clear_that_cannot_write_fails_loud_and_keeps_the_cache(self):
        with tempfile.TemporaryDirectory() as raw:
            library = Path(raw) / "lib"; cache = library / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.cpython-313.pyc").write_bytes(b"bytecode")
            library.chmod(0o555)
            try:
                result = self.clear(library)
            finally:
                library.chmod(0o755)
            self.assertEqual((result.returncode, result.stdout), (1, ""))
            self.assertNotEqual(result.stderr, "")
            self.assertEqual(sorted(path.name for path in library.iterdir()), ["__pycache__"])
            self.assertEqual((cache / "module.cpython-313.pyc").read_bytes(), b"bytecode")

    def test_the_clear_takes_exactly_one_library(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            for args in ((), (base / "one", base / "two")):
                with self.subTest(count=len(args)):
                    result = self.clear(*args)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertNotEqual(result.stderr, "")
            self.assertEqual(list(base.iterdir()), [])
```

The exit 1 in the unwritable case is `mktemp`'s own status, which GNU and BSD share and `set -e` passes through. Exit 127 (no script) or 0 fails the test.

- [ ] **Step 2: Run the tests and watch them fail**

Run from the worktree root (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k LibraryBytecodeClearTest -k test_a_same_size_module_edit 2>&1 | grep -E '^(FAIL|ERROR|Ran|OK|FAILED)|AssertionError'`
Expected: `Ran 5 tests`, `FAILED (failures=7)`, every failure showing exit 127 from `bash` (no script). The seam-1 failure is at the `cleared` tuple: its first `init-run`, the same-size relink and the negative control all passed, so the fixture reproduces the stale load. Planning saw exactly this at spec commit `8b36e8e2`.

- [ ] **Step 3: Write the script**

Create `home/common/agent-skills/scripts/clear-library-bytecode` with exactly this content, then `chmod 755` it. Its shape is the D3 decision and its argv is D7:

```bash
#!/usr/bin/env bash
# clear-library-bytecode LIBRARY
#
# Removes LIBRARY/__pycache__, the bytecode cache of the installed agent
# modules (issue 567). Home Manager's activation runs this file on
# ~/.agents/lib/python after linkGeneration, and the agent workflow tests run
# it too. The cache is renamed into a fresh private directory inside LIBRARY,
# and only then is that directory removed, so a process writing bytecode at
# that moment cannot make the removal fail. Without a cache, or without
# LIBRARY, nothing changes. No other entry of LIBRARY is touched. A failing
# step exits with that command's status and leaves its own error on stderr.
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: clear-library-bytecode LIBRARY" >&2
  exit 2
fi

library=$1
cache=$library/__pycache__
if [ ! -e "$cache" ] && [ ! -L "$cache" ]; then
  exit 0
fi

tomb=$(mktemp -d "$library/.pycache-clear.XXXXXX")
mv -- "$cache" "$tomb/"
rm -rf -- "$tomb"
```

- [ ] **Step 4: Verify**

1. Green, with the issue-499 test (timeout 600 s): the Step 2 command with `-k test_a_second_init_run_compiles_nothing` added.
   Expected: `Ran 6 tests` and `OK`. A failure or error means the task is incomplete. Planning ran this exact code: `OK` in 1.3 s.
2. BSD tools, on a darwin host only (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- env PATH=/usr/bin:/bin PYTHONPATH="$PWD/python" "$(command -v python3)" -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k LibraryBytecodeClearTest 2>&1 | tail -1`
   Expected: `OK`. With `/usr/bin` first, `mktemp`, `mv` and `rm` are the BSD ones. On Linux, skip this check, because step 1 already used GNU.
3. Whole module, so the existing tests stay green (timeout 1200 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -3`
   Expected: `Ran 93 tests` and `OK`. Planning ran it at `8b36e8e2`: `Ran 88 tests` and `OK` in 55 s.
4. Mode (instant): `git add home/common/agent-skills/scripts/clear-library-bytecode && test "$(git ls-files -s home/common/agent-skills/scripts/clear-library-bytecode | cut -c1-6)" = 100755`
   Expected: exit 0.

No `just build` is needed here: nothing the build evaluates references the new file yet.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/clear-library-bytecode home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(issue-567): clear the installed module bytecode cache by rename then remove" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | sort | tr '\n' ' ')" = "home/common/agent-skills/scripts/clear-library-bytecode home/common/agent-skills/tests/test_delivery_workflow.py "`
Expected: exit 0.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"eb331509a96961b6b6eba3188568e22f30b52a87","head":"60d72c83c6170925f7892fcceb23394ddc04befd"}],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":4,"record_bytes":4096,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1a","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/clear-library-bytecode"},{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":12,"record_bytes":20480,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"}]}}
```
