# Task 1: Move the delivery family into the package

Decisions: D1, D2, D4–D6, D8–D11, D14–D19; parent D2, D8, D12, D14–D16;
#177 D2, D3, D5, D13. Spec sections "What moves", "How each file changes",
"The budget policy", "Sibling calls", "Wiring", "Test re-points and
deletions", "The installed-layout test" and "Living documents". Work from the
worktree root. `PK` = `python/agent_tools`, `AS` = `home/common/agent-skills`,
`T` = `home/common/agent-skills/tests`.

This is one commit (D1): no smaller subset stays green. Line numbers are the
base's (`f6a48dcf`); locate each edit by its quoted text, because earlier
edits shift the lines below them. Inside a quoted old or new text, `` \` ``
stands for a literal backtick; the backslash is not written into the file.

**Files:**
- Move with `git mv` from `AS/scripts/` to `PK/`: `workflow-state.py` →
  `workflow_state.py`, `workflow_delivery.py`, `workflow_delivery_wire.py`,
  `workflow_delivery_build.py`, `delivery_model/` (its five files),
  `artifact_budget.py`. Delete: `AS/scripts/artifact-budget`.
- Modify: `PK/host_admission.py`, `PK/agent_platform.py`,
  `PK/attempt_delivery.py`, `PK/attempt_observations.py`,
  `lib/agent-tools.nix`, `AS/default.nix`, `.agents/project.json`,
  `CLAUDE.md`, `docs/standards/agent-helpers.md`, `AS/README.md`,
  `AS/skills/retro/SKILL.md`, `AS/evals/run-eval.sh`, `AS/evals/README.md`,
  `AS/evals/tests/test-run-eval-tree.sh`
- Modify (tests): `T/test_workflow_state.py`, `T/test_delivery_workflow.py`,
  `T/test_delivered_control.py`, `T/test_artifact_budget.py`,
  `T/test_delivery_model.py`, `T/test_workflow_delivery.py`,
  `T/test_admission_replay.py`, `T/test_host_admission.py`,
  `T/test_task_brief.py`, `T/test_eval_cases.py`, `T/test_review_package.py`,
  `T/test_verification_control.py`, `T/test_workflow_skill_contracts.py`,
  `T/test_control_cutover.py`, `T/test_attempt_migration.py`,
  `T/test_ship_delivery.py`, `tests/test_agent_tools_launchers.py`,
  `tests/orchestrate_world.py`, `tests/retained_review_test_support.py`,
  `tests/test_launch_commit.py`, `tests/test_launch_scope.py`,
  `tests/test_phase_budget.py`, `tests/test_review_feasibility.py`,
  `tests/test_sdd_gate.py`

**Interfaces:**
- Produces: the modules `agent_tools.{workflow_state, workflow_delivery,
  workflow_delivery_wire, workflow_delivery_build, artifact_budget}` and the
  subpackage `agent_tools.delivery_model` (D2), every existing public name
  kept except the deleted ones below.
- `agent_tools.workflow_state.artifact_budget_policy() -> Path | None`
  replaces `artifact_budget_paths()`. `_delivery()` and `_host_admission()`
  keep their names and call sites.
- `agent_tools.workflow_delivery.DeliveryRuntime(*, notes_max_characters: int)`;
  `__all__ == ("DeliveryRuntime",)`.
- In `T/test_workflow_state.py`: `link_budget_policy(home) -> None` and
  `setUpModule() -> None`; `SCRIPT` is `workflow_state`'s source file.
  `T/test_delivery_workflow.py` gains `policy_home() -> Path`. Task 3 uses
  `link_budget_policy`, `policy_home` and `DeliveredControlHarness`.
- `lib/agent-tools.nix` exports only `launchers`; `commands` gains
  `artifact-budget` (after `agent-model-matrix`) and `workflow-state` (last).

**Invariants:**
- Every reachable refusal keeps its text, exit code and stream; the deleted
  refusals are exactly the spec's D4 list. `--help` of both commands is
  byte-identical to the base.
- `artifact_budget_policy()` returns the strict resolution of
  `Path.home() / ".agents/share/artifact-budget-policy.json"` when that path
  `is_file()`, else `None`: today's installed branch (D5).
- `resolve_project_policy` keeps `timeout=60` and its three refusal texts.
- `SCHEMA_VERSION = 11`, `CONTROL_INTERFACE_VERSION = 4`, the two
  direct-owner versions and every wire kind are unchanged.
- No workflow-state run in a suite reads the developer's `HOME` (D5, D17).
- `git ls-files AS/scripts` is empty; the built home has no `.agents/lib/python`.

- [ ] **Step 0: Record the start and write the import checker**

Run `START=$(git rev-parse HEAD); B=$(mktemp -d "$(launch-scope scratch …)/t1.XXXX"); echo "$START $B"`
(with the run's three values) and substitute both printed values literally
below. Write `$B/unused.py`, which reports each top-level import no `Name` in
the file uses (a re-exported `setUpModule` is a fixture, not an unused name):

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
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for key, line in sorted(imported.items(), key=lambda kv: kv[1]):
        if key not in used and key != "setUpModule":
            found = True
            print(f"{name}:{line}: unused import {key}")
sys.exit(1 if found else 0)
```

Record the base count: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`
(timeout 3600 s) to `$B/base.log`; `NBASE` is the sum of its members'
`Ran N tests` lines (a planning run at `f6a48dcf` with an empty `HOME`
summed 3889 over 125 members, all passing, and wrote nothing into that `HOME`).

- [ ] **Step 1: Re-point the suites (D8, D16–D18)**

Rules, applied wherever the per-file list below names a site:

- **R1, child argv.** `[sys.executable, str(X), …]`, where `X` names a moved
  file, becomes `[sys.executable, "-m", "agent_tools.<module>", …]`. Where
  `str(SCRIPT)` is an argument to a `-c` wrapper that `execv`s it, pass
  `"-m", "agent_tools.workflow_state"` in its place.
- **R2, PATH shims.** A shell shim's `exec <python> <path> "$@"` becomes
  `exec <python> -m agent_tools.<module> "$@"`. A Python shim's
  `os.execv(sys.executable, [sys.executable, <path>, *sys.argv[1:]])` becomes
  `os.execv(sys.executable, [sys.executable, "-m", "agent_tools.<module>", *sys.argv[1:]])`.
  Shims inherit the env's `PYTHONPATH`.
- **R3, the wrapper and the library tree.** A link to `AS/scripts/artifact-budget`,
  a `PATH` entry for `AS/scripts`, or a fake `.agents/lib/python` becomes one
  file `<bin>/artifact-budget` (mode 0o755): `#!{sys.executable}`, then
  `import os, sys`, then R2's Python `execv` line. No shared helper (D8).
- **R4, imports.** A load of product code (`load_source_module`, `load`,
  `load_model`, `runpy.run_path`, `artifact_budget._delivery_model()`,
  `sys.path.insert` plus `import artifact_budget`) becomes a normal import
  from `agent_tools`, bound where the load result was. Loads of test files
  (`_inprocess_cli.py`, `_delivery_model_fixtures.py`, `test_workflow_state.py`)
  stay.
- **R5, the policy `HOME` (D5, D17).** Each `HOME` a workflow-state run gets,
  explicit or inherited, holds `.agents/share/artifact-budget-policy.json`
  linked to `AS/artifact-budget-policy.json`.
- **R6, pinned replays.** A path into an archived older commit stays that
  commit's literal (`home/common/agent-skills/scripts/…`).

`T/test_workflow_state.py`:
- Add `from agent_tools import artifact_budget, delivery_model, workflow_delivery_build, workflow_delivery_wire, workflow_state`
  as the line after `from agent_tools import attempt_identity, …`.
- `SCRIPT = Path(workflow_state.__file__)` (D15: the in-process runner runs
  the file the `-m` children import). Delete `MODEL`, `ARTIFACT_BUDGET`,
  `BUILDER`, `WIRE`.
- After `load_source_module`, add:

```python
def link_budget_policy(home):
    """Link the repository's budget policy into `home`'s share, where workflow-state reads it (#178)."""
    share = Path(home) / ".agents/share"
    share.mkdir(parents=True, exist_ok=True)
    (share / "artifact-budget-policy.json").symlink_to(BUDGET_POLICY)


def setUpModule():
    """Point this process's `HOME` at a home holding only the budget policy, so module calls
    and children that inherit the environment never read the developer's (#178)."""
    home = Path(tempfile.mkdtemp())
    unittest.addModuleCleanup(shutil.rmtree, home, True)
    link_budget_policy(home)
    unittest.enterModuleContext(mock.patch.dict(os.environ, {"HOME": str(home)}))
```

- `LifecycleHarness.setUpClass`: `cls.delivery_model = delivery_model`.
  `setUp`: `link_budget_policy(self.home)` directly after the declaration's
  `write_text`.
- R4: every `load_source_module(SCRIPT, …)` (15 sites) is `workflow_state`;
  `cls.builder`/`cls.wire` are `workflow_delivery_build`/`workflow_delivery_wire`.
- R1: the `ARTIFACT_BUDGET` argvs (`validated_response`, `cli_exit`,
  `test_the_boundary_refuses_a_mutated_reply`, the `:9090` one) and the three
  `-c` wrappers (`:1156`, `:4068`, `:4687`).
- `ArtifactBudgetPolicyResolutionTest` (re-home, D4): docstring
  `"""The installed policy, a home-manager symlink in HOME's share, reaches the validator as its
  resolved target, in process (issue 498 D2, D5; #178 D5)."""`. The test
  keeps `policy = …`, makes only `home / ".agents/share"`, links the policy
  there, and its probe becomes:

```python
            probe = (
                "import json, sys\n"
                "from agent_tools import workflow_state as module\n"
                f"SPAWN_EVENTS = {sorted(SPAWN_EVENTS)!r}\n"
                "spawned = []\n"
                "resolved = module.artifact_budget_policy()\n"
                "sys.addaudithook(lambda event, _: spawned.append(event)\n"
                "                 if event in SPAWN_EVENTS else None)\n"
                "summary = module.terminal_result(1320, 'stopped', 'attempt deadline expired')\n"
                "print(json.dumps({'policy': str(resolved), 'state': summary['state'],\n"
                "                  'spawned': spawned}))\n"
            )
```

  run as `[sys.executable, "-c", probe]` with the same `env`. Its `state`,
  not-a-symlink, resolved-equals and `spawned == []` assertions stay; the
  `module` and `__pycache__` assertions and the `scripts`, `binaries`,
  `library` and `store` lines go.
- `test_an_exception_escaping_the_validator_is_refused_as_a_crashed_child_was`:
  `workflow = workflow_state`, `module = artifact_budget`.

`T/test_delivery_workflow.py`: add `from agent_tools import delivery_model, workflow_state`;
`WORKFLOW = Path(workflow_state.__file__)`; delete `SCRIPTS`, `MODEL`,
`ARTIFACT_BUDGET`. After the `_LIFECYCLE` lines add
`setUpModule = _LIFECYCLE.setUpModule` and:

```python
def policy_home():
    """`make_home()` with the budget policy linked into its share (#178)."""
    home = make_home()
    _LIFECYCLE.link_budget_policy(home)
    return home
```

Every `make_home()` call (ten, `:1222` to `:1661`) becomes `policy_home()`.
R4: `cls.workflow = workflow_state`; every `cls.model = load(MODEL, …)` is
`delivery_model`. R1: every `WORKFLOW` and `ARTIFACT_BUDGET` argv. Delete
`test_public_source_and_installed_admission_fail_closed` (D4). In
`test_a_second_init_run_compiles_nothing_into_its_bytecode_cache` (re-home):
`init_run` runs R1's `-m` argv; `_LIFECYCLE.link_budget_policy(home)` follows
`home.mkdir()`; the cached path is
`cache_from_source(str(Path(workflow_state.__file__).with_name("workflow_delivery.py")))`;
in the docstring "source-layout" becomes "`-m`" and the last sentence, "The
main script is never cached and lies outside the check.", goes (under `-m`
the main module is imported and cached like the rest).

`T/test_delivered_control.py`: the import keeps `HELD_COMMENT, HELD_RECORD,
NOW, POLICY, SOURCES, BuilderHarness`; add `from agent_tools import delivery_model`;
`cls.model = delivery_model`; R1 in `boundary`. Replace `isolated_workflow`
with:

```python
    def isolated_home(self, wire_max_bytes):
        """A copy of this test's HOME whose share holds a policy of its own, with
        `workflow_responses.wire_max_bytes` = ``wire_max_bytes`` (#178 D5)."""
        home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, home, True)
        shutil.copytree(self.home / ".agents", home / ".agents", symlinks=True)
        installed = home / ".agents/share/artifact-budget-policy.json"
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        policy["workflow_responses"]["wire_max_bytes"] = wire_max_bytes
        installed.unlink()
        installed.write_text(json.dumps(policy), encoding="utf-8")
        return home
```

and in `test_a_rejected_reply_leaves_the_ledger_byte_identical`:
`env = {**os.environ, "HOME": str(self.isolated_home(64))}`, both runs R1.

`T/test_artifact_budget.py`: replace the `sys.path.insert` and
`import artifact_budget` lines with `from agent_tools import artifact_budget, delivery_model, workflow_state`
placed before the relative imports; delete `SCRIPT`, `WORKFLOW_STATE` and the
`load_source_module` import; `workflow_state_subcommands` uses
`workflow_state.build_parser()`. R1 for every `str(SCRIPT)` argv (`:75` is
`[sys.executable, "-m", "agent_tools.artifact_budget"]`). The six
`artifact_budget._delivery_model()` are `delivery_model`; the two
`addCleanup(... "_artifact_budget_delivery_model" ...)` statements go. Delete
the five tests from `test_workflow_response_uses_source_and_lexical_installed_package`
through `test_successful_loader_does_not_cache_missing_private_member` (D4).

`T/test_delivery_model.py`: delete `SOURCE`, `DEFAULT_NIX` and `load_model`;
add `from agent_tools import delivery_model` and
`from agent_tools.workflow_delivery import DeliveryRuntime`. Every
`cls.model = load_model(SOURCE, …)` is `delivery_model`; the `runpy` line is
`DeliveryRuntime(notes_max_characters=10_000)`. Delete
`test_source_and_generated_installed_layout_load_same_model`. Rename
`test_nix_publication_and_managed_test_registration` to
`test_managed_test_registration`, keeping only its justfile assertion.
`test_import_is_pure_and_interface_is_exact` (re-home) imports in a fresh
process with `cwd=raw`:

```python
            done = subprocess.run(
                [sys.executable, "-c", "import json, agent_tools.delivery_model as m; "
                 "print(json.dumps([sorted(m.__all__), hasattr(m, 'main')]))"],
                cwd=raw, capture_output=True, text=True, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            names, has_main = json.loads(done.stdout)
```

then asserts `set(names)` is the old set less `MODEL_INTERFACE_VERSION`, the
cwd listing is unchanged and `has_main` is false; add `import json` and
`import subprocess`.

`T/test_workflow_delivery.py`: delete `ENTRY` and `import runpy`; add
`from agent_tools.workflow_delivery import DeliveryRuntime`; each
`runpy.run_path(str(ENTRY))["DeliveryRuntime"](` is `DeliveryRuntime(`.

`T/test_admission_replay.py`: import `NOW, POLICY, SOURCES` only; add
`from agent_tools import delivery_model`; `cls.model = delivery_model`; R1 in
`validated`. `T/test_host_admission.py`: delete `SCRIPTS`, `WORKFLOW`,
`ARTIFACT_BUDGET`, and `SCRIPT` and `load_source_module` from its relative
import; R1 at `:42` and `:56`; `admitted` uses `workflow_state` from
`from agent_tools import workflow_state` (R4).
`T/test_task_brief.py`: delete `BUDGET` and `WRAPPER`; R3 in `make_repo`.
`T/test_eval_cases.py`: delete `BUDGET`; R1 in `assert_within_budget`.
`T/test_review_package.py`: delete `MODULE`; the stub's last line and the
`setup_repo` shim are R2's Python form (drop the `.replace(...)` call); the
`:66` assertion becomes `self.assertIn("agent_tools.artifact_budget", budget_path.read_text())`.
`T/test_verification_control.py`: import `BUDGET_POLICY` only;
`test_a_rejected_reply_commits_no_resolution` copies `self.home / ".agents"`
as `isolated_home` does, rewrites its policy with `wire_max_bytes` 64, and runs
R1 with `env={**self.cli_env, "HOME": str(<that home>)}`.
`T/test_workflow_skill_contracts.py`: `WORKFLOW_STATE = REPO_ROOT / "python/agent_tools/workflow_state.py"`;
R1 at `:2066`. `T/test_control_cutover.py` (R6): add
`BASE_HELPER = Path("home/common/agent-skills/scripts/workflow-state.py")` and
`BASE_BUDGET = Path("home/common/agent-skills/scripts/artifact_budget.py")`
below `REPO`; the base legs use `self.base / BASE_HELPER` and
`self.base / BASE_BUDGET`; import `POLICY` only.
`T/test_attempt_migration.py` (D16): `base_helper` also archives
`python/agent_tools`, and the replay's env is
`{**self.cli_env, "PYTHONPATH": str(Path(scratch) / "python")}`.
`T/test_ship_delivery.py`: the loop is `for name, module, extra in`
`(("workflow-state", "agent_tools.workflow_state", []),`
`("artifact-budget", "agent_tools.artifact_budget", ["--policy", str(POLICY)]))`
and the quoted argv is `[sys.executable, "-m", module]`; the import drops
`WORKFLOW` and `ARTIFACT_BUDGET`.

`tests/orchestrate_world.py`: delete `WORKFLOW` and `BUDGET`; the tool tuple
passes `"agent_tools.workflow_state"`/`"agent_tools.artifact_budget"` as
`script`; `REAL_TAIL` runs `[sys.executable, "-m", script, *argv]`; `ws` and
`validate` are R1. `tests/retained_review_test_support.py`,
`source_budget_env` (D18): no library tree (its share policy link stays); it writes
`<tmp>/budget-bin/artifact-budget` (R3), whose `execv` argv tail is
`"-m", "agent_tools.artifact_budget"` when
`(Path(source) / "python/agent_tools/artifact_budget.py").is_file()`, else
`str(Path(source) / "home/common/agent-skills/scripts/artifact_budget.py")`;
`PATH` is that bin first. Its docstring adds: "A source tree from before #178
runs its flat validator." `tests/test_launch_commit.py` (`:43`) and
`tests/test_launch_scope.py` (`:294`, `:613`): each shim is R2 and `WORKFLOW`
goes; test_launch_commit's docstring "runs the source workflow-state script"
becomes "runs the source `agent_tools.workflow_state` module". `tests/test_phase_budget.py`: the read
path is `python/agent_tools/workflow_state.py`. `tests/test_review_feasibility.py`
(two fixtures): R3 into `top / "tools"`. `tests/test_sdd_gate.py`: delete
`WORKFLOW` and `BUDGET_MODULE`; `setUp`'s `workflow-state` shim,
`BUDGET_SHIM` and `FAIL_RELEASE` are R2, and their `.format` calls drop
`module=`/`workflow=`; delete the `:87` policy link (the harness now makes
it); the docstring's "run the source `artifact-budget`, …" stays.

- [ ] **Step 2: Watch them fail**

Run (timeout 900 s): `PYTHONPATH=$PWD/python python3 -m agent_tools.suite_runner T/test_workflow_delivery.py T/test_delivery_model.py T/test_artifact_budget.py`
Expected: three members fail at import, each naming a moved module
(`ModuleNotFoundError: No module named 'agent_tools.workflow_delivery'`, or
`ImportError: cannot import name 'artifact_budget' from 'agent_tools'`).

- [ ] **Step 3: Move and edit the product code (D2, D4–D6, D9)**

`git mv` each file of **Files**; `git rm AS/scripts/artifact-budget`.
`PK/workflow_state.py` loses its first two lines (the shebang and the blank
line after it) and its executable bit (`git update-index --chmod=-x`);
`PK/artifact_budget.py` loses its shebang line. Every moved file ends 100644.

`PK/workflow_state.py`:
- Imports: delete `import importlib.util`; the line
  `from agent_tools import attempt_observations, attempt_store, phase_budget, verification_blocker`
  becomes the first block below, and the second goes after the
  `transaction_storage` import. `_delivery()` becomes the function below (the
  cache, the `try` and the `delivery runtime: …` wrapping are today's):

```python
from agent_tools import (
    artifact_budget, attempt_observations, attempt_store, host_admission, phase_budget,
    verification_blocker)
```

```python
from agent_tools.siblings import sibling_argv
from agent_tools.workflow_delivery import DeliveryRuntime
```

```python
def _delivery():
    """The delivery runtime, built once per process for each notes limit (#262 D1).

    The notes limit is read from the artifact-budget policy on every call. A
    construction that fails is not kept, so the next call builds again.
    """
    try:
        if _DELIVERY_RUNTIMES:
            runtime = _DELIVERY_RUNTIMES.get(phase_notes_maximum())
            if runtime is not None:
                return runtime
        maximum = phase_notes_maximum()
        runtime = DeliveryRuntime(notes_max_characters=maximum)
    except Exception as exc:
        raise WorkflowError(f"delivery runtime: {exc}") from exc
    _DELIVERY_RUNTIMES[maximum] = runtime
    return runtime
```
- `_host_admission()`: delete `_HOST_ADMISSION`; the body is
  `return host_admission` under the docstring `"""The host admission library, \`agent_tools.host_admission\` (D18)."""`.
- Delete `artifact_budget_paths`, `_ARTIFACT_BUDGET` and `_artifact_budget`;
  in their place:

```python
def artifact_budget_policy() -> Path | None:
    """The installed budget policy, resolved, or None (#178; issue 498 D2).

    It is read only at `$HOME/.agents/share/artifact-budget-policy.json`, a
    home-manager store symlink. artifact-budget refuses a symlinked explicit
    `--policy` through its `O_NOFOLLOW` read, so callers pass this target.
    """
    policy = Path.home() / ".agents/share/artifact-budget-policy.json"
    if not policy.is_file():
        return None
    try:
        return policy.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
```

- `artifact_budget_invoke`: `policy = artifact_budget_policy()`;
  `artifact_budget.invoke(...)`; `artifact_budget.Outcome(1, b"", ...)`.
  `phase_notes_maximum`: `policy_path = artifact_budget_policy()`.
- Delete `resolve_project_argv`; `resolve_project_policy` runs
  `[*sibling_argv("resolve_project"), "resolve", "--repo-root", root]`.

`PK/workflow_delivery.py`: delete `import importlib.util`,
`WORKFLOW_DELIVERY_INTERFACE_VERSION = 1` with one blank line after it, and
the three static `_load_*` methods; add `from agent_tools import delivery_model`,
`from agent_tools.workflow_delivery_build import DeliveryBuilder` and
`from agent_tools.workflow_delivery_wire import DeliveryProjection` beside the
`attempt_custody` import; `__init__` binds `self._model = delivery_model`,
`self._builder = DeliveryBuilder(delivery_model, notes_max_characters=notes_max_characters)`,
`self._projection = DeliveryProjection()`; `__all__ = ("DeliveryRuntime",)`.
`PK/workflow_delivery_wire.py`, `PK/workflow_delivery_build.py`: delete the
`WORKFLOW_DELIVERY_*_INTERFACE_VERSION = 1` line and the blank line after it.
`PK/delivery_model/_canonical.py`: delete `MODEL_INTERFACE_VERSION = 1`;
`__init__.py` drops it from the import and `__all__`.

`PK/artifact_budget.py`: delete `import importlib.util` and `_delivery_model`
(through its two following blank lines); add `from agent_tools import delivery_model`
one blank line after `from typing import …`; both validators bind
`model = delivery_model`; delete the four-line pre-decode probe in `invoke`
(`if args.command == "validate-report" and args.boundary in {` …
`_delivery_model()`); the `SUMMARY_KEYS` comment becomes
`# Restated from \`agent_tools.review_gate\`: the authority does not import the gate whose output it validates.`

`PK/host_admission.py`: delete `HOST_ADMISSION_INTERFACE_VERSION = 1`;
"stays in \`workflow-state.py\`" becomes "stays in \`agent_tools.workflow_state\`".
`PK/agent_platform.py`: "the pattern \`workflow-state.py\` establishes" becomes
"the pattern \`agent_tools.workflow_state\` establishes".
`PK/attempt_delivery.py` (D19): in the docstring's first paragraph, "and
nothing from the skill scripts is imported: the delivery model lives there,
so a caller passes" becomes "and nothing from `agent_tools.delivery_model` is
imported: a caller passes"; reflow only the lines of that sentence.
`PK/attempt_observations.py`: "nothing imported from the skill scripts"
becomes "nothing imported from `agent_tools.workflow_delivery_build`".

Run `python3 $B/unused.py` over `PK/workflow_state.py`, `PK/workflow_delivery.py`,
`PK/artifact_budget.py` and every Step-1 test file, and delete each import it
reports, except the base's three, which stay: `STALL_LIMIT` in
`PK/workflow_state.py` (a re-export), `re` in `PK/workflow_delivery.py` and
`Path` in `T/test_ship_delivery.py`.

- [ ] **Step 4: Wire the commands and the installed floor (D1, D10)**

`lib/agent-tools.nix`: the header's first four lines become the two below,
followed by the existing `` # `commands` is the only … `` lines; insert
`"artifact-budget"` after `"agent-model-matrix"` and `"workflow-state"` after
`"verified-tree"`; delete `scriptLauncher` with its comment and
`inherit scriptLauncher;`.

```nix
# The agent_tools package (python/): one interpreter environment, a build-time
# import of every module, and one isolated launcher per command-table row.
```

`AS/default.nix`: delete the `.agents/bin/workflow-state` and
`.agents/bin/artifact-budget` entries, the artifact-budget module comment and
the five `.agents/lib/python/…` entries above the share lines, and
`.agents/lib/python/host_admission.py`; the comment above the host
declaration becomes the block below. The `.agents/share` entries and
`home.packages` stay.

```nix
    # The host declaration: authored host policy -- per route, whether it is
    # supported and how many agent slots one root session may hold -- read by
    # `workflow-state` and the conformance check through the host admission
    # library, `agent_tools.host_admission` (D2, D18).
```

`tests/test_agent_tools_launchers.py`: delete `SCRIPT_LAUNCHER`,
`NOT_LAUNCHERS` with its comment, the `NOT_LAUNCHERS` branch in `launchers()`,
`workflow_state_launcher`, `test_workflow_state_ignores_a_hostile_agent_tools`,
`or SCRIPT_LAUNCHER.fullmatch(data)` and `or entry.name == "workflow-state"`;
the module docstring drops ", other than \`NOT_LAUNCHERS\`,"; `LAUNCHER_FLOOR`
gains `"artifact-budget"` (after `"agent-model-matrix"`) and
`"workflow-state"` (last), its comment naming "#424 and #178";
`dependency_env` drops `bins` and the `python3` link (no other reader), and
its `PATH` starts at `.agents/bin`; append to
`test_the_command_table_generates_each_deployed_command`:
`self.assertFalse(os.path.lexists(self.root / ".agents/lib/python"), "the built home installs a library tree")`.
In `test_review_source_and_built_canonical_actual_parity`, the source branch
keeps its share link, drops `lib`, and writes R3's shim into
`top / "source-tools"`, which is its `bins`.

- [ ] **Step 5: Re-point the living documents (D11, D19)**

- `CLAUDE.md`: "Agent-workflow Python is moving into one standard-library
  package" becomes "Agent-workflow Python is one standard-library package";
  "The remaining Python helpers are still flat scripts under
  \`home/common/agent-skills/scripts/\`, and move in cluster by cluster, while
  \`docs/standards/agent-helpers.md\` sends all new helper code to the
  package." becomes "\`docs/standards/agent-helpers.md\` sends all helper code
  to the package."
- `docs/standards/agent-helpers.md`: the intro becomes "Deltas for
  agent-workflow Python in this repository."; delete rule 1's " Each legacy
  script moves in with its cluster's PR."
- `AS/README.md` `:184`: "runs as \`PYTHONPATH=<checkout>/python python3 <checkout>/home/common/agent-skills/scripts/workflow-state.py\`,"
  becomes "runs as \`PYTHONPATH=<checkout>/python python3 -m agent_tools.workflow_state\`,
  which reads the installed \`~/.agents/share/artifact-budget-policy.json\`," (D14).
- `AS/skills/retro/SKILL.md`: "and \`home/common/agent-skills/scripts/\`" becomes
  "and the sdd skill's \`scripts/\`".
- `AS/evals/run-eval.sh`: delete the `workflow-state` block (its two comment
  lines through its `chmod`); the header's "for its agent_tools commands and
  for workflow-state ahead" becomes "for its agent_tools commands ahead".
  `AS/evals/README.md`: delete "\`bin/workflow-state\` is one more shim, running
  the tree's \`home/common/agent-skills/scripts/workflow-state.py\`, and the
  root also holds" in favour of "The root also holds"; "the remaining flat
  helpers (\`artifact-budget\`, \`sdd-workspace\`)" becomes "the remaining flat
  helper (\`sdd-workspace\`)". `AS/evals/tests/test-run-eval-tree.sh`: the
  "it runs the tree's script" check greps `-- '-m agent_tools.workflow_state'`
  (D19).
- `.agents/project.json` `workflow.light_lane.risk_paths`: the three entries
  become `python/agent_tools/workflow_state.py`,
  `python/agent_tools/delivery_model/*` and
  `python/agent_tools/workflow_delivery*.py`, in place.

- [ ] **Step 6: Verify**

Each gate exits as stated; any other outcome means the task is incomplete.

1. `git add -A`, then `just build` (timeout 3600 s): exit 0; the build
   import-checks every new module and `agent_tools.delivery_model._*`.
2. Focused (timeout 1800 s): `PYTHONPATH=$PWD/python python3 -m agent_tools.suite_runner`
   over the Step-1 files that `just agent-workflow-tests` lists (all but
   `tests/test_agent_tools_launchers.py`, `tests/retained_review_test_support.py`
   and `tests/orchestrate_world.py`, which run inside other members): exit 0.
3. `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests` (3600 s): exit 0,
   its `Ran N tests` lines sum to `NBASE-7` (D4 deletes five artifact-budget,
   one delivery-model and one delivery-workflow test; the launcher case is
   installed-only).
4. `HOME=$(mktemp -d) WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`
   (3600 s): exit 0, as at the base. A failure naming
   `artifact-budget policy is unavailable` is a site R5 missed: give that
   `HOME` the link, or import `setUpModule` from `.test_workflow_state`, and
   rerun gates 3 and 4.
5. `just agent-installed-skill-tests` (3600 s): exit 0, with
   `test_the_command_table_generates_each_deployed_command` and both hostile
   loops `ok`.
6. `if git grep -nE "MODEL_INTERFACE_VERSION|WORKFLOW_DELIVERY(_WIRE|_BUILD)?_INTERFACE_VERSION|HOST_ADMISSION_INTERFACE_VERSION|spec_from_file_location|module_from_spec|SourceFileLoader|sys\.path" -- python; then exit 1; fi`;
   `git grep -n importlib -- python/agent_tools` lists only `review_witness.py`;
   `git grep -n "__file__" -- python/agent_tools` lists only `adopt_references.py`;
   `test -z "$(git ls-files home/common/agent-skills/scripts)"`;
   `if git grep -n "lib/python" -- home/common/agent-skills/default.nix lib; then exit 1; fi`;
   `python3 $B/unused.py` over the same files reports only the base's three names.
7. `--help` identity: `mkdir $B/base && git archive f6a48dcf python/agent_tools home/common/agent-skills/scripts | tar -x -C $B/base`;
   `H` is the one path `nix-store --query --requisites ./result | grep -- '-home-manager-files$'`
   prints. With `COLUMNS=80`, `cmp` holds between `$H/.agents/bin/workflow-state --help`
   and `PYTHONPATH=$B/base/python python3 $B/base/home/common/agent-skills/scripts/workflow-state.py --help`,
   and between `$H/.agents/bin/artifact-budget --help` and
   `python3 $B/base/home/common/agent-skills/scripts/artifact_budget.py --help`.
8. `git diff --stat -M $START -- python home` pairs every moved file with
   `=>`; only `artifact-budget` is a plain deletion.
9. `just agent-instruction-budget` (timeout 600 s): exit 0.

- [ ] **Step 7: Commit**

One commit through `launch-commit`, subject
`refactor(issue-178): move the delivery family into agent_tools`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":1,"records":[{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":6089,"record_bytes":308224,"support":{"covers":["a01"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a01","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":6089,"boundary":"all","deleted_lines":0,"record_bytes":308224,"support":{"covers":["a02"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a02","last_task":2,"owner":1,"path":"python/agent_tools/workflow_state.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":1488,"record_bytes":83968,"support":{"covers":["a03"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a03","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/workflow_delivery.py"},{"bounds":[{"added_lines":1488,"boundary":"all","deleted_lines":0,"record_bytes":83968,"support":{"covers":["a04"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a04","last_task":2,"owner":1,"path":"python/agent_tools/workflow_delivery.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":460,"record_bytes":28672,"support":{"covers":["a05"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a05","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/workflow_delivery_wire.py"},{"bounds":[{"added_lines":460,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["a06"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a06","last_task":1,"owner":1,"path":"python/agent_tools/workflow_delivery_wire.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":710,"record_bytes":41984,"support":{"covers":["a07"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a07","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/workflow_delivery_build.py"},{"bounds":[{"added_lines":710,"boundary":"all","deleted_lines":0,"record_bytes":41984,"support":{"covers":["a08"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a08","last_task":2,"owner":1,"path":"python/agent_tools/workflow_delivery_build.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":13,"record_bytes":2048,"support":{"covers":["a09"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a09","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/delivery_model/__init__.py"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["a10"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a10","last_task":2,"owner":1,"path":"python/agent_tools/delivery_model/__init__.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":126,"record_bytes":6144,"support":{"covers":["a11"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a11","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/delivery_model/_canonical.py"},{"bounds":[{"added_lines":126,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["a12"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a12","last_task":2,"owner":1,"path":"python/agent_tools/delivery_model/_canonical.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":654,"record_bytes":47104,"support":{"covers":["a13"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a13","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/delivery_model/_objects.py"},{"bounds":[{"added_lines":654,"boundary":"all","deleted_lines":0,"record_bytes":47104,"support":{"covers":["a14"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a14","last_task":2,"owner":1,"path":"python/agent_tools/delivery_model/_objects.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":274,"record_bytes":22528,"support":{"covers":["a15"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a15","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/delivery_model/_reconcile.py"},{"bounds":[{"added_lines":274,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["a16"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a16","last_task":2,"owner":1,"path":"python/agent_tools/delivery_model/_reconcile.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":707,"record_bytes":53248,"support":{"covers":["a17"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a17","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/delivery_model/_wire.py"},{"bounds":[{"added_lines":707,"boundary":"all","deleted_lines":0,"record_bytes":53248,"support":{"covers":["a18"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a18","last_task":2,"owner":1,"path":"python/agent_tools/delivery_model/_wire.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":1372,"record_bytes":72704,"support":{"covers":["a19"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a19","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/artifact_budget.py"},{"bounds":[{"added_lines":1372,"boundary":"all","deleted_lines":0,"record_bytes":72704,"support":{"covers":["a20"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a20","last_task":1,"owner":1,"path":"python/agent_tools/artifact_budget.py"},{"bounds":[{"added_lines":0,"boundary":"all","deleted_lines":2,"record_bytes":1024,"support":{"covers":["a21"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"a21","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/artifact-budget"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["a22"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a22","last_task":1,"owner":1,"path":"python/agent_tools/host_admission.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":3072,"support":{"covers":["a23"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a23","last_task":1,"owner":1,"path":"python/agent_tools/agent_platform.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["a24"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a24","last_task":1,"owner":1,"path":"python/agent_tools/attempt_delivery.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":3072,"support":{"covers":["a25"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a25","last_task":1,"owner":1,"path":"python/agent_tools/attempt_observations.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":16,"record_bytes":8192,"support":{"covers":["a26"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a26","last_task":1,"owner":1,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":30,"record_bytes":8192,"support":{"covers":["a27"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a27","last_task":1,"owner":1,"path":"home/common/agent-skills/default.nix"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["a28"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a28","last_task":1,"owner":1,"path":".agents/project.json"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":24576,"support":{"covers":["a29"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a29","last_task":1,"owner":1,"path":"CLAUDE.md"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":3,"record_bytes":12288,"support":{"covers":["a30"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a30","last_task":1,"owner":1,"path":"docs/standards/agent-helpers.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":32768,"support":{"covers":["a31"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a31","last_task":1,"owner":1,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":6144,"support":{"covers":["a32"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a32","last_task":1,"owner":1,"path":"home/common/agent-skills/skills/retro/SKILL.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":13,"record_bytes":8192,"support":{"covers":["a33"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a33","last_task":1,"owner":1,"path":"home/common/agent-skills/evals/run-eval.sh"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":4,"record_bytes":12288,"support":{"covers":["a34"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a34","last_task":1,"owner":1,"path":"home/common/agent-skills/evals/README.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":6144,"support":{"covers":["a35"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a35","last_task":1,"owner":1,"path":"home/common/agent-skills/evals/tests/test-run-eval-tree.sh"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":60,"record_bytes":36864,"support":{"covers":["a36"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a36","last_task":1,"owner":1,"path":"tests/test_agent_tools_launchers.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":10,"record_bytes":12288,"support":{"covers":["a37"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a37","last_task":1,"owner":1,"path":"tests/orchestrate_world.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":8,"record_bytes":8192,"support":{"covers":["a38"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a38","last_task":1,"owner":1,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":6,"record_bytes":10240,"support":{"covers":["a39"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a39","last_task":1,"owner":1,"path":"tests/test_launch_commit.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":6,"record_bytes":12288,"support":{"covers":["a40"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a40","last_task":1,"owner":1,"path":"tests/test_launch_scope.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["a41"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a41","last_task":1,"owner":1,"path":"tests/test_phase_budget.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":12,"record_bytes":12288,"support":{"covers":["a42"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a42","last_task":1,"owner":1,"path":"tests/test_review_feasibility.py"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":12,"record_bytes":16384,"support":{"covers":["a43"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a43","last_task":1,"owner":1,"path":"tests/test_sdd_gate.py"},{"bounds":[{"added_lines":90,"boundary":"all","deleted_lines":110,"record_bytes":98304,"support":{"covers":["a44"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a44","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_state.py"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":170,"record_bytes":98304,"support":{"covers":["a45"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a45","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":22,"boundary":"all","deleted_lines":22,"record_bytes":16384,"support":{"covers":["a46"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a46","last_task":3,"owner":1,"path":"home/common/agent-skills/tests/test_delivered_control.py"},{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":140,"record_bytes":73728,"support":{"covers":["a47"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a47","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_artifact_budget.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":60,"record_bytes":32768,"support":{"covers":["a48"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a48","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_delivery_model.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":10,"record_bytes":14336,"support":{"covers":["a49"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a49","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_delivery.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":8192,"support":{"covers":["a50"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a50","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_admission_replay.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":8,"record_bytes":10240,"support":{"covers":["a51"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a51","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_host_admission.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":8,"record_bytes":6144,"support":{"covers":["a52"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a52","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_task_brief.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":3,"record_bytes":6144,"support":{"covers":["a53"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a53","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_eval_cases.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":6,"record_bytes":14336,"support":{"covers":["a54"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a54","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_review_package.py"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":12,"record_bytes":10240,"support":{"covers":["a55"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a55","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_verification_control.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":10240,"support":{"covers":["a56"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a56","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":4,"record_bytes":10240,"support":{"covers":["a57"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a57","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_control_cutover.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":2,"record_bytes":6144,"support":{"covers":["a58"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a58","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_attempt_migration.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":5,"record_bytes":8192,"support":{"covers":["a59"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"a59","last_task":2,"owner":1,"path":"home/common/agent-skills/tests/test_ship_delivery.py"}]}}
```
