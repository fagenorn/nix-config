# Task 2: Move the resolver family into the package

Decisions: D1–D8, D10, D12, D13, D14; parent D2, D8, D12, D14, D15, D16; #175
D2, D5, D7, D13, D14; #179 D2, D6. Spec sections "What moves (D1)", "How each
file changes (D2–D4)", "The sibling-run helper (D5)", "workflow-state's
transitional lookups (D6)", "Wiring (D1)" and "Test re-points and deletions
(D7, D8)". Work from the worktree root. `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`, `T` = `home/common/agent-skills/tests`.

This is one commit (D12). Line numbers are the base's. Locate each edit by
its quoted text, because earlier edits shift the lines below them. Inside a
quoted old or new text, `\`` stands for a literal backtick and `\n` for a line
break at the file's existing indentation. Neither escape is written into the
file.

**Files:**
- Move, with `git mv`, from `AS/scripts/` to `PK/`:
  `resolve-project.py` → `resolve_project.py`, `agent_platform.py`,
  `conformance.py`, `conformance-registry.py` → `conformance_registry.py`,
  `conformance-checks.py` → `conformance_checks.py`,
  `adopt-project.py` → `adopt_project.py`, `adopt_inspection.py`,
  `adopt_planning.py`, `adopt_apply.py`, `adopt_verify.py`, `host_admission.py`
- Modify: `AS/scripts/workflow-state.py`, `lib/agent-tools.nix`, `AS/default.nix`
- Modify (tests): `T/test_resolve_project.py`, `T/test_resolve_platform.py`,
  `T/test_resolve_platform_status.py`, `T/conformance_test_support.py`,
  `T/test_conformance.py`, `T/test_conformance_checks.py`,
  `T/test_conformance_registry.py`, `T/test_adopt_project.py`,
  `T/test_adopt_project_boundaries.py`, `T/test_adopt_apply.py`,
  `T/test_adopt_verify.py`, `T/test_delivery_workflow.py`,
  `T/test_workflow_skill_contracts.py`, `T/test_shell_example_contracts.py`,
  `tests/test_agent_tools_launchers.py`

**Interfaces:**
- Consumes: Task 1's `agent_tools.siblings.sibling_argv(module: str) -> list[str]`.
- Produces:
  - The modules `agent_tools.{resolve_project, agent_platform, conformance,
    conformance_registry, conformance_checks, adopt_project, adopt_inspection,
    adopt_planning, adopt_apply, adopt_verify, host_admission}`. They keep
    every existing public name except the ones deleted below.
  - `agent_tools.conformance` keeps the names `registry` (bound to
    `agent_tools.conformance_registry`), `CHECKS_MODULE` (bound to
    `agent_tools.conformance_checks`) and `load_resolver()` (which returns
    `agent_tools.resolve_project`) (D2).
  - `lib/agent-tools.nix` `commands` holds eight rows, sorted:
    `adopt-project`, `agent-evidence`, `agent-model-matrix`, `conformance`,
    `context-map-lint`, `diff-scope`, `promotion`, `resolve-project`.
  - In `T/test_resolve_project.py`: `install_home(home, manifest=COMMITTED, *, declaration=COMMITTED)`
    and `make_home(manifest=COMMITTED)`. `load_module()` returns
    `agent_tools.resolve_project`.
  - In `T/conformance_test_support.py`:
    `platform_env(tmp, manifest=COMMITTED, *, declaration=COMMITTED)` and
    `run(*args, env=None, cwd=None)`. `load_module()` returns
    `agent_tools.conformance`, and `HERMETIC_ENV["PYTHONPATH"]` is set.
  - In `T/test_adopt_project.py`: `install_home(home, manifest=COMMITTED)` and
    `make_home(manifest=COMMITTED)`.
  - `tests/test_agent_tools_launchers.py`: `NOT_LAUNCHERS = ("workflow-state",)`
    (D13). Task 3 extends this file.

**Invariants:**
- Every reachable refusal keeps its code, `repair_id`, violations and exit
  code. `adopt_project.run_resolver` keeps its three refusal texts
  byte for byte, and its `timeout=300` (D5).
- With `HOME` unset, `resolve-project <any subcommand>` exits 2. It prints
  `{"error":{"code":"resolver_failure","repair_id":"platform.manifest.missing","violations":[{"message":"the installed platform manifest was not found","pointer":""}]}}`
  and writes nothing to stderr (D4).
- `platform.library.missing`, `adopt.library.missing` and `library_unavailable`
  appear nowhere outside `.agents/artifacts` (D3).
- `HOST_ADMISSION_INTERFACE_VERSION = 1` stays in `agent_tools.host_admission`
  (D3).
- The installed `resolve-project`, `conformance` and `adopt-project`
  `--help` output is byte-identical to the base scripts (parent D15).
- In the built home, `.agents/lib/python` holds exactly `artifact_budget.py`,
  `delivery_model`, `host_admission.py`, `workflow_delivery.py`,
  `workflow_delivery_build.py` and `workflow_delivery_wire.py`.
  `.agents/bin` holds no `conformance-registry` and no `conformance-checks`.

- [ ] **Step 0: Record the starting commit and the import checker**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`. Keep the braces in `${START}:`, because in zsh `$START:h…` applies a
modifier.

Write `$B/unused.py`. It reports each absolute top-level import that no
`Name` in the file uses:

```python
import ast, sys
found = False
for name in sys.argv[1:]:
    tree = ast.parse(open(name, encoding="utf-8").read())
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[a.asname or a.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module != "__future__":
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for key, line in sorted(imported.items(), key=lambda kv: kv[1]):
        if key not in used:
            found = True
            print(f"{name}:{line}: unused import {key}")
sys.exit(1 if found else 0)
```

- [ ] **Step 1: Re-point the resolver suites (D7, D8)**

In each of the following, "relative import" means changing
`from test_X import (` to `from .test_X import (`, or
`from conformance_test_support import (` to
`from .conformance_test_support import (`. Delete the `# noqa: E402` marker,
keep the name list, and drop only the names this task deletes. "Drop the path
insert" means deleting the `sys.path.insert(0, str(Path(__file__).resolve().parent))`
line and the comment block directly above it that explains it. Delete an
import only when Step 10's checker reports it.

`T/test_resolve_project.py`:
- Docstring line 1 becomes `"""Contract tests for \`resolve-project\` (\`agent_tools.resolve_project\`).`
- Delete `SCRIPT = …` and `LIBRARY = …` (L34–35). Add
  `from agent_tools import resolve_project` as its own group, one blank line
  after `from pathlib import Path`.
- `install_home`: delete the `library: bool = True,` parameter, keeping
  `declaration` keyword-only, and delete the five lines from
  `library_dir = home / ".agents" / "lib" / "python"` through
  `shutil.copy(LIBRARY, installed_library)`. In its docstring, the second
  paragraph becomes `Every invocation in this suite runs under a temporary \`HOME\`,
  so the manifest has to be materialized there: the resolver loads it from
  \`$HOME/.agents/share\`, with no fallback path.` Delete the sentence
  beginning `` `library=False` leaves the library uninstalled``.
- `make_home(manifest: object = COMMITTED) -> Path` returns
  `install_home(Path(tempfile.mkdtemp()).resolve(), manifest)`.
- Delete `def library_members` and the two blank lines after it.
- The three `[sys.executable, str(SCRIPT), …]` argvs (in `run`,
  `DiscoveryTest.resolve_from` and `run_with_path`) become
  `[sys.executable, "-m", "agent_tools.resolve_project", …]`.
- `load_module` becomes:

```python
def load_module():
    """The resolver module, `agent_tools.resolve_project`.

    Reserved for the seams no subprocess run can reach: the generic failure
    wrapper, and the emit-side guard that the parse-side guard keeps unreachable
    from any authored contract.
    """
    return resolve_project
```

- In `InProcessTestCase`'s docstring, `because both the load-time library
  import and the manifest load inside \`main\` read it directly` becomes
  `because the manifest load inside \`main\` reads it directly`.

`T/test_resolve_platform.py`:
- Docstring: `The\nplatform installation — the manifest under \`$HOME/.agents/share\` and the\nlibrary under \`$HOME/.agents/lib/python\` — has to be present` becomes
  `The\nplatform installation — the manifest under \`$HOME/.agents/share\` — has\nto be present`.
- Drop the path insert. Use a relative import, dropping `LIBRARY`, `SCRIPT`
  and `library_members`.
- Delete `class PlatformLibraryTest` whole (L414–547) and the two blank lines
  after it.
- In `SchemaReasonDispatchTest.setUp`, delete
  `self.assertTrue(self.module.bootstrap_platform_library())`.
- Append to `ManifestGateTest` (D4, D7):

```python

    def test_an_unset_home_refuses_as_a_missing_manifest(self):
        """#177 D4: with no `HOME` there is no installed manifest to load."""
        env = {key: value for key, value in os.environ.items() if key != "HOME"}
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.resolve_project", "resolve",
             "--repo-root", str(self.make_root())],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(json.loads(proc.stdout), {"error": {
            "code": "resolver_failure",
            "repair_id": "platform.manifest.missing",
            "violations": [{"pointer": "", "message":
                            "the installed platform manifest was not found"}]}})
```

`T/test_resolve_platform_status.py`: drop the path insert, and use a relative
import.

- [ ] **Step 2: Re-point the conformance suites (D7, D8, D14)**

`T/conformance_test_support.py`:
- Delete `SCRIPT = …` (L34). Add `from agent_tools import conformance` as its
  own group after `from unittest import mock`.
- Delete the path insert line only. The comment block above it keeps its
  first two sentences and loses its last, `The\n# directory has to be importable
  however this module was reached.` Use `from .test_resolve_project import (`.
- `HERMETIC_ENV` gains, after `"LANG": "C",`:

```python
    # Absolute, so an engine child with its own `cwd` still imports the
    # package under test (parent D8). Outside a recipe this raises at import.
    "PYTHONPATH": os.pathsep.join(os.path.abspath(entry) for entry
                                  in os.environ["PYTHONPATH"].split(os.pathsep)),
```

- `run(*args, env=None, cwd=None)`: delete the `script` parameter. Its
  docstring becomes `"""One S1 subprocess run of the engine."""`, and its
  argv becomes `[sys.executable, "-m", "agent_tools.conformance", *args]`.
- `load_module` becomes:

```python
def load_module():
    """The engine module, `agent_tools.conformance`, for the S3 seams."""
    return conformance
```

- `platform_env`: delete `library: bool = True,` and `library=library,`. In
  its docstring, `\`manifest\`, \`library\` and \`declaration\`` becomes
  `\`manifest\` and \`declaration\``, and `, and \`library=False\` leaves the
  library uninstalled` is deleted.
- `PlatformHome`: delete the last two lines of `setUp` (the `agent_platform`
  eviction). Its docstring body becomes `In process the ladder loads the
  platform manifest from this process's own\n\`$HOME/.agents/share\`. Pinned to the hermetic installation, a case's\noutcome no longer depends on whether the machine has switched to a\ngeneration that installs the platform.`
- Module docstring: `the S3 module\nloader` becomes `the S3 module\naccessor`.
  `— the committed manifest and library,` becomes
  `— the committed manifest and host declaration,`. `A case that needs another
  manifest, or\nno library, runs under \`platform_env\` instead.` becomes
  `A case that needs another\nmanifest or declaration runs under \`platform_env\` instead. HERMETIC_ENV's\nPYTHONPATH is the recipe's, made absolute.`

`T/test_conformance.py`:
- Drop the path insert and use a relative import, dropping `SCRIPT`.
- In `PlatformLadderTest.test_a_broken_installation_fails_resolvable_at_the_platform_stage`,
  `cases` becomes `(("manifest", None, "platform.manifest.missing"),)`, the
  loop becomes `for missing, manifest, repair_id in cases:`, and the
  environment becomes `platform_env(tmp, manifest)`. Every assertion is
  unchanged.
- `EvaluatorResolutionTest` (D14): the docstring becomes
  `"""S3: an evaluator is resolved through the checks module at call time.\n\n    \`evaluator\` looks each check's function up on \`CHECKS_MODULE\` when it\n    runs, so a rebind made on that module under test is the function\n    \`evaluate\` calls.\n    """`. Delete the line
  `load_module()  # a second instance now owns the shared sys.modules name`.
- Delete `class BootstrapFailureTest` whole and the two blank lines after it.
- In `AdmissionDeclarationCheckTest`, delete `deployed_run`,
  `test_the_installed_library_is_loaded_from_a_deployed_layout` and
  `test_an_unusable_installed_library_fails_only_this_check`.

`T/test_conformance_checks.py`: drop the path insert and use a relative import.

`T/test_conformance_registry.py`: drop the path insert and use a relative
import. Delete `test_no_installed_engine_file_names_the_package` (D7). The
`PromotionLiteralPinTest` docstring becomes
`"""#127 D10: the engine's promotion literals are the package's constants."""`
(D14).

- [ ] **Step 3: Re-point the adoption suites (D7, D8)**

`T/test_adopt_project.py`:
- The module docstring becomes:

```python
"""Contract tests for `adopt-project` (`agent_tools.adopt_project`).

Runs `adopt-project` as `python -m agent_tools.adopt_project` under a temporary
`HOME` holding a fixture manifest. The command consumes the resolver only as a
child process of its own interpreter, `agent_tools.resolve_project` run through
`agent_tools.siblings.sibling_argv` (D26, #177 D5).

Fixture repositories are real `git init` checkouts with a hermetic identity and
`commit.gpgsign=false` in the fixture's own local config; nothing here touches
the developer's git configuration or the machine's `~/.agents`.

Two cases import package modules in process: the generic failure wrapper, which
no subprocess run can drive (D23), and the ambiguous forward step, which the
platform library refuses before the router would see it (#177 D7).
"""
```

- Delete `import importlib.util`, and delete `SCRIPT`, `RESOLVER`, `LIBRARY`
  and `ADOPT_LIBRARIES` (L33–45). Add
  `from agent_tools import adopt_planning, adopt_project` as its own group
  after `from unittest import mock`.
- `install_home(home: Path, manifest: object = COMMITTED) -> Path`: the
  docstring becomes `"""Populate \`home\` with the platform manifest
  \`adopt-project\` reads."""`. Delete the body from
  `library_dir = home / ".agents" / "lib" / "python"` through
  `resolver.chmod(0o755)`. The `share` block and `return home` stay.
- `make_home(manifest: object = COMMITTED) -> Path` returns
  `install_home(Path(tempfile.mkdtemp()).resolve(), manifest)`.
- Delete `def declared_members` and the two blank lines after it.
- In `run`, the argv becomes
  `[sys.executable, "-m", "agent_tools.adopt_project", *args]`. The
  `write-projections` run near L255 becomes
  `[sys.executable, "-m", "agent_tools.resolve_project", "write-projections", …]`.
- Replace `ForwardStepRefusalTest.test_ambiguous_forward_step_is_adopt_failure` with:

```python
    def test_ambiguous_forward_step_is_adopt_failure(self):
        # The platform library refuses two records for one `from_schema`, so
        # the router's own refusal is reached at the module seam (#177 D7).
        manifest = manifest_with([1, 2], [
            {"id": "a", "from_schema": 1, "to_schema": 2},
            {"id": "b", "from_schema": 1, "to_schema": 2},
        ])
        with self.assertRaises(adopt_planning.AdoptError) as caught:
            adopt_planning.select_forward_step(manifest, 1)
        self.assertEqual(caught.exception.code, "adopt_failure")
        self.assertEqual(caught.exception.repair_id,
                         "adopt.manifest.forward_step_ambiguous")
```

- `AdoptFailureWrapperTest`: the docstring's second paragraph becomes
  `Importing \`agent_tools.adopt_project\` and making the inspection entry
  point\n    raise is the one monkeypatch this suite is allowed.` Delete
  `def load`. In the test, delete `module = self.load()` and patch
  `adopt_project` instead of `module`: `mock.patch.object(adopt_project,
  "inspect_repository", …)` and `code = adopt_project.main([...])`. Every
  assertion is unchanged.
- Delete `class AdoptLibraryTest` whole and the two blank lines after it.

`T/test_adopt_project_boundaries.py`:
- Docstring: delete invariant `5.` (two lines), and renumber `6.` to `5.`.
- Drop the path insert. Use a relative import, dropping `ADOPT_LIBRARIES`,
  `LIBRARY`, `SCRIPT` and `declared_members`.
- Delete `class LibraryBindingTest` whole, and leave two blank lines before
  `if __name__`.

`T/test_adopt_apply.py`: drop the path insert, and use a relative import.

`T/test_adopt_verify.py`: drop the path insert. Use relative imports for both
`test_adopt_project` (dropping `RESOLVER`) and `test_adopt_apply`. In `fleet`
the argv becomes
`[sys.executable, "-m", "agent_tools.resolve_project", "platform-status", "--fleet"]`.
In `test_two_concurrent_registrations_both_survive` it becomes
`[sys.executable, "-m", "agent_tools.adopt_project", "verify", "--repo-root", str(root), "--register"]`.

- [ ] **Step 4: Re-point the suites outside the family (D8, D13)**

`T/test_delivery_workflow.py`, in `test_public_source_and_installed_admission_fail_closed`:
- Replace `shutil.copy2(SCRIPTS / "host_admission.py", store / "host_admission.py")` with:

```python
                if layout == "installed":
                    shutil.copy2(ROOT / "python/agent_tools/host_admission.py",
                                 store / "host_admission.py")
```

- Wrap the final block, from `library_file = store / "host_admission.py"`
  through `library_file.write_bytes(library_bytes)`, in
  `if layout == "installed":`, indenting it one level. The block is otherwise
  unchanged.

`T/test_workflow_skill_contracts.py`: the `LEGACY_MIGRATION_INPUTS` key
`"home/common/agent-skills/scripts/adopt_inspection.py"` becomes
`"python/agent_tools/adopt_inspection.py"`. In
`_install_policy_surface_fixture`, the copy source becomes
`REPO_ROOT / "python/agent_tools/resolve_project.py"`.

`T/test_shell_example_contracts.py`: in `COMMAND_VOCABULARY`, delete the two
tokens in place. Line 50 ends `"codex", "conformance",`, and line 51 begins
`    "context-map-lint",`.

`tests/test_agent_tools_launchers.py` (D13): after `MARKER = …`/`HOSTILE_EXIT`/
`TIMEOUT_SECONDS`, add:

```python
# Flat installed scripts that name the package without being launchers: only
# `workflow-state`, whose transitional lookups run `agent_tools.resolve_project`
# and import `agent_tools.host_admission` from source (#177 D6, D13). #178
# deletes this entry with them.
NOT_LAUNCHERS = ("workflow-state",)
```

In `launchers()`, directly after `data = entry.read_bytes()`, insert:

```python
            if entry.name in NOT_LAUNCHERS:
                self.assertIsNone(LAUNCHER.fullmatch(data),
                                  f"{entry} is a generated launcher; drop it from NOT_LAUNCHERS")
                continue
```

In the module docstring, `Every\n\`.agents/bin\` entry that names the package must be a generated launcher`
becomes `Every\n\`.agents/bin\` entry that names the package, other than \`NOT_LAUNCHERS\`, must be a\ngenerated launcher`.

- [ ] **Step 5: Watch the suites fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_adopt_project_boundaries.py 2>&1 | tail -3`
Expected: `FAILED`. Each suite fails to import with an `ImportError` naming
`resolve_project`, `conformance` or `adopt_planning` under `agent_tools`,
because nothing has moved yet.

- [ ] **Step 6: Move the eleven files**

```bash
S=home/common/agent-skills/scripts; P=python/agent_tools
git mv $S/resolve-project.py $P/resolve_project.py
git mv $S/agent_platform.py $P/agent_platform.py
git mv $S/conformance.py $P/conformance.py
git mv $S/conformance-registry.py $P/conformance_registry.py
git mv $S/conformance-checks.py $P/conformance_checks.py
git mv $S/adopt-project.py $P/adopt_project.py
for f in adopt_inspection adopt_planning adopt_apply adopt_verify host_admission; do git mv $S/$f.py $P/$f.py; done
chmod 644 $P/resolve_project.py $P/conformance.py $P/adopt_project.py
```

Then, in each moved file that starts with `#!/usr/bin/env python3`, delete
that line: `resolve_project`, `conformance`, `conformance_registry`,
`conformance_checks` and `adopt_project`. `host_admission` is a pure rename.

- [ ] **Step 7: Edit the production modules (D2–D5, D14)**

`PK/resolve_project.py` (D2, D3):
- Add `from agent_tools import agent_platform` as its own group, after
  `import sys`.
- Delete from the comment `# The shared platform library, bound by
  \`bootstrap_platform_library\`` through the end of `bootstrap_platform_library`
  (`return True`), that is `agent_platform = None`,
  `PLATFORM_LIBRARY_MEMBERS`, `PLATFORM_LIBRARY_REPAIR_ID`, `loaded_from` and
  `bootstrap_platform_library`. Keep exactly two blank lines before
  `CAPABILITY_NAMES`.
- In `main`, delete the comment beginning `# After argparse` and the whole
  `if not bootstrap_platform_library():` block. `main` goes from
  `args = parser.parse_args(argv)` straight to `try:`.

`PK/agent_platform.py` (D4):
- Its docstring's `\`adopt-project\`\nmust not import \`resolve-project.py\` (D26)`
  becomes `\`adopt-project\`\nmust not import \`agent_tools.resolve_project\` (D26)`.
- In `load_manifest`, insert before `path = manifest_path()`:

```python
    if not os.environ.get("HOME"):
        raise _refuse([_violation(
            "", "the installed platform manifest was not found",
            "platform.manifest.missing")])
```

- Append to its docstring: `An unset or empty \`HOME\` names no installed
  manifest, so it refuses as\n    \`platform.manifest.missing\` before any
  filesystem read (#177 D4).`

`PK/conformance.py` (D2, D14):
- Docstring: replace the paragraph `The engine ships as three co-located
  modules, …` (through `…rather than a traceback (D15).`) with:
  `The engine is three modules of the \`agent_tools\` package: the vocabulary
  and\nthe registry in \`agent_tools.conformance_registry\`, the evaluators in\n\`agent_tools.conformance_checks\`, and this entry module, which imports both\nand the resolver \`agent_tools.resolve_project\` by name (#177 D1, D2).`
- Delete `import importlib.util` and
  `from importlib.machinery import SourceFileLoader`.
- Replace everything from the banner `# The siblings, in process` (with its
  surrounding `# ----` rules) through the end of the `try:/except` bootstrap
  (`BOOTSTRAP_ERROR = error`) with:

```python
from agent_tools import conformance_checks as CHECKS_MODULE
from agent_tools import conformance_registry as registry
from agent_tools import resolve_project
from agent_tools.conformance_checks import bounded_run
from agent_tools.conformance_registry import (
    CHECK_MEMBERS, Check, Context, DOMAINS, FORBIDDEN_MEMBER_NAMES,
    HEX_DIGITS, MAX_FACT_KEYS, MAX_FACT_LIST, MAX_FACT_STRING,
    OPERATION_MEMBERS, OUTCOME_MEMBERS, OUTCOME_STATUSES, Outcome,
    PLATFORM_MEMBERS, PURPOSES, REGISTRY, REGISTRY_BY_ID, REPAIRS,
    REPAIR_MEMBERS, REPAIR_MODULES, REPORT_MEMBERS, REQUEST_MEMBERS,
    REQUIREMENTS, REVISION_LENGTH, SAFETY_CLASSES, SCHEMA_VERSION,
    STATUSES, SUBJECT_KINDS, SUBJECT_MEMBERS, select,
)


def load_resolver():
    """Contract: the resolver module, `agent_tools.resolve_project` (D2)."""
    return resolve_project
```

  Place the five imports as their own group directly after `import sys`, and
  put `load_resolver` where the deleted block was. `ENGINE_FAILURE_MESSAGE`
  stays where it is, above that block. The name list is the base's list,
  unchanged.
- `evaluator`'s docstring becomes `"""The evaluator a check declares, resolved
  through the checks module.\n\n    Looked up on \`CHECKS_MODULE\` at call time
  rather than bound at import, so a\n    rebind made on that module under test
  is the function \`evaluate\` calls. The\n    name is shouted because three
  functions here bind a local \`checks\` holding\n    a list of check objects.\n    """`.
- `main`: delete `if BOOTSTRAP_ERROR is not None:` and `raise BOOTSTRAP_ERROR`.
  Its docstring becomes `"""The engine's one exception boundary (D15, D29).\n\n    Parser construction and dispatch both sit inside it. The violation is the\n    fixed sentence, never the exception text, which can name a path. The one\n    declared exception is the ladder's own catch (D17).\n    """`.

`PK/conformance_registry.py` (D3, D14):
- Docstring: `\`conformance-registry\` -> \`conformance-checks\` -> \`conformance\``
  becomes `\`conformance_registry\` -> \`conformance_checks\` -> \`conformance\``.
- In the promotion comment, the lines `# to it by test_conformance_registry:
  the engine is installed standalone and\n# imports no package module, so it
  restates them rather than importing them.` become
  `# to it by test_conformance_registry.`.
- In `host.admission.declaration`'s findings, delete
  `("library_unavailable", "host.admission.declare")`, so the tuple ends
  `("declaration_invalid", "host.admission.declare")),`.

`PK/conformance_checks.py` (D3):
- Docstring: `\`conformance\` loads this module through its \`SourceFileLoader\`
  helper, having\nregistered \`conformance_registry\` in \`sys.modules\` first,
  which is what the\n\`from conformance_registry import\` below resolves against
  (D2, D40).` becomes `\`agent_tools.conformance\` imports this module as
  \`CHECKS_MODULE\`; its vocabulary\ncomes from \`agent_tools.conformance_registry\`
  (D2, D40).`
- Delete `import importlib.util`. `from conformance_registry import (` becomes
  `from agent_tools.conformance_registry import (`. Directly above that line,
  add `from agent_tools import host_admission`, in the same group.
- `check_contract_resolvable`: delete the three lines
  `if not resolver.bootstrap_platform_library():` … `resolver.PLATFORM_LIBRARY_REPAIR_ID)`.
  In the docstring, `bind the\n    platform library and manifest` becomes
  `load the\n    platform manifest`.
- Delete `_HOST_ADMISSION = None`, `load_host_admission` and
  `host_admission_path`, with their blank lines.
- `check_admission_declaration`: delete the first `try:/except` block, which
  calls `load_host_admission()`. Rename `library.` to `host_admission.` in the
  three remaining uses: `load_declaration`, `DeclarationError` and
  `declaration_path`. Delete the docstring's last sentence, `A library that is
  absent, … fail the whole run.`, so that the docstring ends
  `…never reads or writes a ledger or a claim (#150 D13, D24)."""`.

`PK/adopt_project.py` (D2, D3, D5):
- Docstring: the paragraph `The resolver is consumed **only** as a subprocess
  …` becomes:
  `The resolver is consumed **only** as a child process, never imported (D26):\n\`run_resolver\` runs \`agent_tools.resolve_project\` under this process's own\ninterpreter through \`agent_tools.siblings.sibling_argv\` (#177 D5), so\ncontract validation has one home and an installed run is answered by the\nresolver of its own store environment. The shared platform library\n\`agent_platform\` is imported directly — it is the one home for the manifest\nloader, the state root and the atomic writer (D37).`
- Delete `import os`. Add this group after `import sys`:

```python
from agent_tools import adopt_apply, adopt_inspection, adopt_planning, adopt_verify, agent_platform
from agent_tools.siblings import sibling_argv
```

- Delete everything from the comment `# The shared platform library, bound by
  \`bootstrap_platform_library\`` through `bootstrap_adopt_libraries`'s
  `return True`. Keep two blank lines before the `# Output` banner.
- Delete `resolver_path` and its two trailing blank lines. In `run_resolver`,
  delete `binary = resolver_path()`, and the argv becomes
  `[*sibling_argv("resolve_project"), *args, "--repo-root", str(root)]`.
- `main`: delete both `if not bootstrap_…():` blocks and the two-line comment
  between them. `main` goes from `args = parser.parse_args(argv)` to `try:`.

`PK/adopt_inspection.py`: `It\ndoes not import \`resolve-project.py\`` becomes
`It\ndoes not import \`agent_tools.resolve_project\``. The paragraph
`Installed beside \`agent_platform.py\` …` becomes `A module of the
\`agent_tools\` package, imported by \`agent_tools.adopt_project\` and\nits
sibling adoption modules.` In the comment near L356,
`import of \`resolve-project.py\` (D26)` becomes
`import of \`agent_tools.resolve_project\` (D26)`.

`PK/adopt_planning.py`: `, and is\ninstalled at \`$HOME/.agents/lib/python/\`
behind the entry point's member guard.` becomes `, and is\na module of the
\`agent_tools\` package.` `import agent_platform` becomes
`from agent_tools import agent_platform`, and `from adopt_inspection import (`
becomes `from agent_tools.adopt_inspection import (`.

`PK/adopt_apply.py` and `PK/adopt_verify.py`: `at the absolute path\n\`$HOME/.agents/bin/resolve-project\`, never imported (D26)` becomes
`through\n\`agent_tools.siblings.sibling_argv\`, never imported (D26)`. The
sentence from `It is installed at \`$HOME/.agents/lib/python/\`` through
`rather than as an \`AttributeError\`.` becomes, in `adopt_apply`:
`It is a module of the \`agent_tools\` package, and every name it reads from its
two sibling\nmodules is named in the \`from\` imports below.` In `adopt_verify`
it becomes `It is a module of the \`agent_tools\` package, and every name it
reads from\n\`adopt_inspection\` is named in the \`from\` import below.` `import agent_platform` becomes `from agent_tools import agent_platform`,
and each `from adopt_X import (` becomes `from agent_tools.adopt_X import (`.
The name lists are unchanged.

- [ ] **Step 8: workflow-state's transitional lookups (D6)**

In `AS/scripts/workflow-state.py`, replace `resolve_project_argv` with:

```python
def resolve_project_argv() -> list[str]:
    """How this script runs resolve-project (#177 D6; #178 deletes this lookup).

    From the repository's `scripts` directory it runs `agent_tools.resolve_project`
    under this interpreter, which finds the package on the caller's `PYTHONPATH`.
    Installed, it runs the `resolve-project` launcher beside it, else the one in
    `~/.agents/bin`.
    """
    if Path(__file__).parent.name == "scripts":
        return [sys.executable, "-m", "agent_tools.resolve_project"]
    installed = Path(__file__).parent / "resolve-project"
    if not installed.is_file():
        installed = Path.home() / ".agents/bin/resolve-project"
    return [str(installed)]
```

Replace `_host_admission` with:

```python
def _host_admission():
    """The host admission library, loaded once (D18; #177 D6, deleted by #178).

    From the repository's `scripts` directory it is `agent_tools.host_admission`,
    imported from the caller's `PYTHONPATH`. Installed, it is the copy at
    `~/.agents/lib/python/host_admission.py`. Either must declare interface 1.
    """
    global _HOST_ADMISSION
    if _HOST_ADMISSION is not None:
        return _HOST_ADMISSION
    try:
        if Path(__file__).parent.name == "scripts":
            from agent_tools import host_admission as module
        else:
            entry = Path.home() / ".agents/lib/python/host_admission.py"
            spec = importlib.util.spec_from_file_location("_workflow_host_admission", entry)
            if spec is None or spec.loader is None:
                raise ValueError(f"cannot load {entry}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        if getattr(module, "HOST_ADMISSION_INTERFACE_VERSION", None) != 1:
            raise ValueError("interface")
    except Exception as exc:
        raise WorkflowError(f"host admission library: {exc}") from exc
    _HOST_ADMISSION = module
    return module
```

Nothing else in `workflow-state.py` changes.

- [ ] **Step 9: Wiring (D1, D6)**

`lib/agent-tools.nix`: `commands` becomes, one row per line:
`"adopt-project"`, `"agent-evidence"`, `"agent-model-matrix"`,
`"conformance"`, `"context-map-lint"`, `"diff-scope"`, `"promotion"`,
`"resolve-project"`. The comment above it is unchanged.

`AS/default.nix`:
- Delete the `.agents/bin/resolve-project`, `.agents/bin/conformance` and
  `.agents/bin/adopt-project` entries, and the
  `.agents/bin/conformance-registry` and `.agents/bin/conformance-checks`
  entries with their three-line comment. Delete each entry's trailing blank
  line.
- The comment `# The shared platform library and the manifest it reads. …`
  (four lines) and the `.agents/lib/python/agent_platform.py` line become:

```nix
    # The platform manifest: authored data with nothing templated, so this
    # store copy is byte-identical to the repository's (D1).
```
- The host-admission comment (five lines) and its library entry become:

```nix
    # The host admission library and the host declaration it reads. The
    # declaration is authored host policy -- per route, whether it is supported
    # and how many agent slots one root session may hold -- read by
    # `workflow-state` and the conformance check through that library (D2, D18).
    # The library lives in the agent_tools package; this copy serves only
    # `workflow-state`'s transitional installed-layout load, and #178 deletes it
    # (#177 D6).
    ".agents/lib/python/host_admission.py".source = ../../../python/agent_tools/host_admission.py;
```
- Delete the adoption-library comment (five lines) and the four
  `.agents/lib/python/adopt_*.py` lines, with the blank line after them.

- [ ] **Step 10: Verify**

Run: `git add -A python home/common/agent-skills lib tests && python3 "$B/unused.py" python/agent_tools/{resolve_project,agent_platform,conformance,conformance_registry,conformance_checks,adopt_project,adopt_inspection,adopt_planning,adopt_apply,adopt_verify,host_admission}.py home/common/agent-skills/tests/{test_resolve_project,test_resolve_platform,test_resolve_platform_status,conformance_test_support,test_conformance,test_conformance_checks,test_conformance_registry,test_adopt_project,test_adopt_project_boundaries,test_adopt_apply,test_adopt_verify,test_delivery_workflow}.py`
Expected: exactly one line,
`home/common/agent-skills/tests/test_adopt_apply.py:25: unused import subprocess`.
That line predates this task. Remove any other import the checker names, then
re-run the checker.

Run these checks. At `$START` the second, third and fourth fail. The first
and fifth guard the moved modules, and the sixth guards D3's kept constant:

```bash
set -e
T=home/common/agent-skills/tests
if git grep -nE "importlib|SourceFileLoader|spec_from|sys\.path|__file__|loaded_from" -- python/agent_tools; then exit 1; fi
if git grep -nE "importlib|SourceFileLoader|spec_from|sys\.path|loaded_from" -- $T/test_resolve_project.py $T/test_resolve_platform.py $T/test_resolve_platform_status.py $T/conformance_test_support.py $T/test_conformance.py $T/test_conformance_checks.py $T/test_conformance_registry.py $T/test_adopt_project.py $T/test_adopt_project_boundaries.py $T/test_adopt_apply.py $T/test_adopt_verify.py; then exit 1; fi
if git grep -nE "platform\.library\.missing|adopt\.library\.missing|library_unavailable|bootstrap_platform_library|PLATFORM_LIBRARY" -- ':!.agents/artifacts'; then exit 1; fi
if git grep -nE "scripts/(resolve-project|agent_platform|conformance|adopt|host_admission)" -- ':!.agents/artifacts'; then exit 1; fi
if grep -l '^#!' python/agent_tools/*.py; then exit 1; fi
grep -q 'HOST_ADMISSION_INTERFACE_VERSION = 1' python/agent_tools/host_admission.py
echo family-clean
```

Expected: `family-clean`.

Run: `git diff --cached -M --name-status "$START" -- home/common/agent-skills/scripts python/agent_tools | grep '^R'`
Expected: eleven `R<NN>` lines, with `adopt_project` at 65 or more and every
other file at 85 or more.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_resolve_platform_status.py home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py > "$B/family.log" 2>&1; tail -3 "$B/family.log"`
Expected: `OK`. The unset-`HOME` test and the re-homed ambiguous case are
among the tests run.

Run: `just build 2>&1 | tail -3`
Expected: success. The import check covers all eleven moved modules.

Check the built tree, including `--help` byte identity against the base
scripts laid out as the old installation:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
ls "$H/.agents/lib/python"
if ls "$H/.agents/bin" | grep -E '^conformance-(registry|checks)$'; then echo LEFTOVER; fi
mkdir -p "$B/old/bin" && git archive "${START}" home/common/agent-skills/scripts | tar -x -C "$B/old"
for c in resolve-project conformance conformance-registry conformance-checks adopt-project; do
  ln -s "$B/old/home/common/agent-skills/scripts/$c.py" "$B/old/bin/$c"; done
for c in resolve-project conformance adopt-project; do
  L="$H/.agents/bin/$c"; PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L")
  COLUMNS=80 "$PY" "$B/old/bin/$c" --help > "$B/$c.before"
  COLUMNS=80 "$L" --help | cmp - "$B/$c.before" && echo "$c help-identical"; done
```

Expected: the listing is exactly `artifact_budget.py delivery_model
host_admission.py workflow_delivery.py workflow_delivery_build.py
workflow_delivery_wire.py`. No `LEFTOVER` line appears. The old commands
run through links named for the command, beside their siblings, which is the
layout they were installed in. Then three
`help-identical` lines. At `$START` the listing also shows `agent_platform.py`
and four `adopt_*.py` files.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`. The hostile run and the controls now include `adopt-project`,
`conformance` and `resolve-project`, and `workflow-state` passes through
`NOT_LAUNCHERS`. Without Step 4's exemption this run fails with
`…/workflow-state names agent_tools but is not a generated launcher`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > "$B/t2.log" 2>&1; tail -3 "$B/t2.log"`
Expected: `Ran NBASE-17 tests` and `OK (skipped=2)`. Twenty-one tests are
deleted and one is added.

- [ ] **Step 11: Commit**

```bash
git add -A python/agent_tools home/common/agent-skills/scripts home/common/agent-skills/tests \
  home/common/agent-skills/default.nix lib/agent-tools.nix tests/test_agent_tools_launchers.py
git commit -m "refactor(agent-tools): move the resolver family into the package"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
