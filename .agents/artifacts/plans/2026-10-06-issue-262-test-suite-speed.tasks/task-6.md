# Task 6: Class fixture templates for modules still over 90 s

Per D5 and D11. Hotspot H4: three classes rebuild a signed fixture repository and its derived values in `setUp`, once for every test. For a module that still measures above 90 s after Tasks 1–5, each listed class builds its fixture once in `setUpClass`. Every test then gets a private `copytree` of the fixture directory and `copy.deepcopy` copies of the derived values. Only the candidates below are in scope. `RouteTest` and every other class keep their per-test builds.

| Module | Class | Builder (module global) | Values set in `setUp` today |
|---|---|---|---|
| `tests/test_review_issue121.py` | `AncestryTest` | `linear_fixture`, through `Fixture.build` | `repo, pins, task7_pins, table, authority`, then `edges = list(contribution_edges(repo, pins, classify(repo, pins)))` |
| `tests/test_review_issue100.py` | `Issue100Test` | `issue100_fixture` | `repo, live, archive, pins`, then `limits` (built under `patch.dict(os.environ, source_budget_env(tmp), clear=True)`) |
| `tests/test_review_task7.py` | `Task7ModelTest` | `fixture_pins` | `repo, pins` |

**Files (each only when its module qualifies in Step 1):**
- Modify: `tests/test_review_issue121.py` (`AncestryTest.setUp` → `setUpClass` + `setUp`)
- Modify: `tests/test_review_issue100.py` (`Issue100Test.setUp` → `setUpClass` + `setUp`)
- Modify: `tests/test_review_task7.py` (`Task7ModelTest.setUp` → `setUpClass` + `setUp`)

**Interfaces:**
- Consumes: the module builders named in the table, unchanged, and `Fixture.build(self, tmp, **shape)`. `build` uses nothing from `self`, so `setUpClass` calls it as `Fixture.build(cls, template)`.
- Produces: no new public name. Each converted class keeps every attribute its tests read (`self.tmp`, plus the table's values), with the same types.

**Invariants:**
- After `setUp`, each test sees the same values the per-test build gave it: `self.tmp` is a fresh directory holding a full copy of the template (`shutil.copytree(template, self.tmp, symlinks=True, dirs_exist_ok=True)`). Each `Path` value under the template is rebased to `self.tmp / value.relative_to(template)`, and every other value is `copy.deepcopy` of the template's. Git object IDs and signatures are therefore identical, and no test's mutation of its repository or its values reaches another test.
- Exclusion (per D11): a class keeps its per-test build when either check finds the template directory's absolute path. The first check covers the non-`Path` template values, walked recursively through dataclass fields, mappings, sequences, sets, `str`, `bytes` and `Path`. The second is `git -C <each repo/live> config --list` output.
- `test_*` bodies do not change. Only `setUp`/`setUpClass` change, plus imports such as `copy` where a module lacks one.
- The template directory is removed by `cls.addClassCleanup(shutil.rmtree, template)`.

- [ ] **Step 1: Measure, then pick the classes**

Write the root's timing driver to `${TMPDIR:-/tmp}/issue262-timing.py`. Then run:

`PYTHONPATH=python timeout 5400 python3 "${TMPDIR:-/tmp}/issue262-timing.py" . tests/test_review_task7.py tests/test_review_issue121.py tests/test_review_issue100.py | tee "${TMPDIR:-/tmp}/issue262-t6-before.tsv"`

A module qualifies when its `wall_s` is above 90, at any `load1_before` (per D11). Record the TSV and the qualifying list in the task report. If none qualifies, make no change, skip to Step 5's coverage gate, and report "no module over 90 s; H4 not applied".

- [ ] **Step 2: Write the failing probe** (scratch only)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t6-probe.py" <<'PY'
import importlib, os, sys, traceback, unittest
from unittest import mock
sys.path.insert(0, os.getcwd())
CASES = {"AncestryTest": ("tests.test_review_issue121", "linear_fixture"),
         "Issue100Test": ("tests.test_review_issue100", "issue100_fixture"),
         "Task7ModelTest": ("tests.test_review_task7", "fixture_pins")}
for name in sys.argv[1:]:
    module_name, builder = CASES[name]
    module = importlib.import_module(module_name)
    real, origins = getattr(module, builder), []
    def spy(*args, **kwargs):
        frames = [f.name for f in traceback.extract_stack()]
        origins.append("setUp" if "setUp" in frames else "setUpClass" if "setUpClass" in frames else "body")
        return real(*args, **kwargs)
    with mock.patch.object(module, builder, spy):
        result = unittest.TextTestRunner(verbosity=0).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(getattr(module, name)))
    assert result.wasSuccessful(), f"{name} failed"
    assert origins.count("setUp") == 0 and origins.count("setUpClass") == 1, f"{name}: {origins}"
print("T6-PROBE-OK")
PY
```

Run, from the worktree root with `timeout 3600`: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t6-probe.py" <qualifying classes>`. Expected before the change: `AssertionError: <class>: ['setUp', 'setUp', ...]`.

- [ ] **Step 3: Check exclusion, then implement each qualifying class**

Move the old `setUp` build into `setUpClass`, writing into a `template = Path(tempfile.mkdtemp())` in place of `self.tmp`. Then apply D11's exclusion scan, as the Invariants define it, in a scratch script. A class the scan flags is reverted to its `BASE` `setUp` and reported as excluded. For each class that remains, store `cls._template = (template, values)`, where `values` maps attribute names to the built values. In `setUp`, create `self.tmp` exactly as today (`Path(tempfile.mkdtemp())` with `self.addCleanup(shutil.rmtree, self.tmp)`), then apply the copy, rebase and deepcopy rule from the Invariants.

- [ ] **Step 4: Verify**

1. Run the Step 2 probe on the converted classes. Expect `T6-PROBE-OK`.
2. Run each modified module whole, logging to `${TMPDIR:-/tmp}/issue262-t6-<name>.log` with `timeout 3600`. Each must end `OK`.
3. Re-run Step 1's timing on the modified modules into `${TMPDIR:-/tmp}/issue262-t6-after.tsv`, and report both TSVs' rows.

- [ ] **Step 5: Coverage gate and commit**

Run the root's coverage gate. Expect `COVERAGE-GATE-OK 2077 test ids`.

```bash
git add <the modified test modules only>
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "test(review): share per-class fixture templates (#262)" -m "<trailer lines>"
```
