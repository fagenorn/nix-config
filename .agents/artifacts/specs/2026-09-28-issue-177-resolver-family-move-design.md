# The resolver family moves into agent_tools

Design, 2026-09-28, for issue #177. This is a cluster slice of the accepted
parent design,
[One package for the agent workflow helpers](2026-09-24-agent-tools-package-design.md),
built on the foundation slice
[#175](2026-09-24-issue-175-agent-tools-foundation-design.md) and following the
shape of [#179](2026-09-24-issue-179-model-matrix-tools-move-design.md). Every
parent row, every #175 row and every #179 row binds. This spec cites them as
"parent D*n*", "#175 D*n*" and "#179 D*n*" and restates none of them. It was
written unattended, so each non-obvious call it makes is a row in the Decision
ledger below.

## Problem

The resolver family is still eleven flat scripts, and it carries three of the
four loader mechanisms the parent set out to delete:

- `resolve-project` puts `$HOME/.agents/lib/python` at the front of
  `sys.path`, imports `agent_platform`, and accepts it only if an origin check
  on the module's resolved `__file__` agrees and a member tuple is present.
- `adopt-project` repeats that bootstrap for `agent_platform` and again for
  its four adoption libraries. It then runs the resolver at the absolute path
  `$HOME/.agents/bin/resolve-project`.
- `conformance` loads its registry, its checks and the resolver through a
  `SourceFileLoader` helper derived from `__file__`. To make that work, Nix
  links two library modules into `~/.agents/bin` without the executable bit.
- The conformance checks module loads `host_admission` by file path, from the
  source directory or from `~/.agents/lib/python`, and checks its interface
  handshake.

The suites grew around this machinery. They build fake `$HOME/.agents/lib/python`
trees and copy scripts into fake `$HOME/.agents/bin` directories, and whole
test classes exist only to prove that the bootstrap refuses a missing, partial
or foreign library.

The user needs the move to be invisible. Command names, `~/.agents/bin` paths,
argv/stdin/stdout/exit contracts and the resolver's error shapes must not
change, and existing assertions must keep asserting what they assert today.
`workflow-state` stays outside the package until #178, yet it has to keep
finding the resolver and the admission library in both layouts.

## Solution

One PR delivers the following:

- It moves the eleven files in the D1 table into `python/agent_tools/` with
  `git mv`. Each gets only the edits listed in D2–D4.
- It adds three command-table rows, `adopt-project`, `conformance` and
  `resolve-project`. It deletes their hand-written `home.file` links, the two
  unexecutable conformance library links, and the `~/.agents/lib/python`
  entries for `agent_platform` and the four adoption libraries.
- It replaces every bootstrap, origin check, member tuple and file-path loader
  in the family with plain package imports.
- It adds the parent-D16 sibling-run helper, and `adopt-project` runs the
  resolver through it (D5).
- It gives `workflow-state` two transitional lookups, one for the resolver and
  one for the admission library, which #178 deletes (D6).
- It re-points the family's suites to import normally and run `-m`. It
  forwards the recipe's `PYTHONPATH` into the conformance suites' hermetic
  environment, and it deletes the tests that exist only to exercise the
  bootstrap (D7, D8).
- It extends the installed-layout test to the three new launchers (D9).
- It re-points the living documents (D10).

## Decisions

### What moves (D1)

| Today (`home/common/agent-skills/scripts/`) | Module | Launcher |
|---|---|---|
| `resolve-project.py` | `agent_tools.resolve_project` | `~/.agents/bin/resolve-project` |
| `agent_platform.py` | `agent_tools.agent_platform` | none (library) |
| `conformance.py` | `agent_tools.conformance` | `~/.agents/bin/conformance` |
| `conformance-registry.py` | `agent_tools.conformance_registry` | none (library) |
| `conformance-checks.py` | `agent_tools.conformance_checks` | none (library) |
| `adopt-project.py` | `agent_tools.adopt_project` | `~/.agents/bin/adopt-project` |
| `adopt_inspection.py`, `adopt_planning.py`, `adopt_apply.py`, `adopt_verify.py` | same names under `agent_tools` | none (libraries) |
| `host_admission.py` | `agent_tools.host_admission` | none (library) |

Module names follow parent D1: the command name with underscores, or the file
name with underscores for a library. The two conformance libraries take the
names their loader registers them under today. No name collides with an
existing package module.

`host_admission` is not named in the issue, but it moves here anyway. The
conformance checks module locates it by path. Parent D16 moves a caller and
the callee it locates by path in the same PR, and AC3 leaves no file-path
loader in the family's modules. Its other caller, `workflow-state`, gets a
transitional lookup (D6).

`workflow-state.py`, the delivery modules, `artifact_budget.py` and its
wrapper stay in `scripts/` for #178.

### How each file changes (D2–D4)

Every move follows #175 D2: the shebang and the executable bit go, absolute
`agent_tools` imports replace the machinery, imports left unused are removed,
and the `if __name__ == "__main__":` block stays. Each module docstring, and
each comment that describes the deleted mechanism or an install location,
gets its sentence rewritten to the package fact. Nothing else changes: no
split functions, no reformatting, and no renamed helpers beyond those listed
here. The three commands already pin `prog`, so their `--help` output stays
byte-identical (#175 D5).

- **`resolve_project`.** It imports `agent_platform` from the package at
  module scope. The following are deleted: `bootstrap_platform_library`,
  `loaded_from`, `PLATFORM_LIBRARY_MEMBERS`, `PLATFORM_LIBRARY_REPAIR_ID`, the
  module-level `agent_platform = None`, and `main`'s library refusal. The
  refusal `platform.library.missing` can no longer be reached, because the
  launcher's environment always contains the package (D3).
- **`agent_platform`.** `load_manifest` refuses an unset or empty `HOME` with
  its existing `platform.manifest.missing` violation before it touches the
  filesystem (D4). The docstring's rule that it never imports the resolver
  stays.
- **`conformance`.** `load_sibling`, the name-candidate tuples,
  `RESOLVER_MODULE_NAME`, `BOOTSTRAP_ERROR` and `main`'s re-raise of it are
  deleted. The module binds
  `from agent_tools import conformance_registry as registry`,
  `from agent_tools import conformance_checks as CHECKS_MODULE` and
  `from agent_tools import resolve_project`. Its named imports come from
  `agent_tools.conformance_registry` and `agent_tools.conformance_checks`.
  `load_resolver()` stays, and now returns `resolve_project`. The names stay
  (D2), so no call site in the engine changes, and neither does any test
  line that reads `module.registry`, `module.CHECKS_MODULE` or
  `module.load_resolver()`. `main` keeps its single `except Exception`
  boundary. The comment on `evaluator` loses its S3 fresh-instance rationale:
  there is now one module instance, and resolving through `CHECKS_MODULE` at
  call time stays correct.
- **`conformance_registry`.** Only the shebang and the docstring's loader
  sentence change. `host.admission.declaration` drops
  `("library_unavailable", "host.admission.declare")` from its reason codes
  (D3). The promotion literals and their comment are unchanged.
- **`conformance_checks`.** `from conformance_registry import (…)` becomes
  `from agent_tools.conformance_registry import (…)`. `load_host_admission`,
  `host_admission_path`, `_HOST_ADMISSION` and `importlib.util` are deleted.
  `check_admission_declaration` calls
  `from agent_tools import host_admission` directly, keeping its
  `DeclarationError` branch and its passed branch byte for byte, and loses
  its `library_unavailable` branch. In `check_contract_resolvable`, the
  platform stage deletes its
  `bootstrap_platform_library()`/`PLATFORM_LIBRARY_REPAIR_ID` step and
  starts at `require_platform_manifest()`.
- **`adopt_project`.** Both bootstraps, `library_dir`, `loaded_from`, the five
  member tuples, both library repair ids, the module-level `None` bindings,
  and `main`'s two library refusals are deleted. The module imports
  `agent_platform` and the four adoption libraries from the package.
  `resolver_path` is deleted. `run_resolver` builds its argv as
  `[*sibling_argv("resolve_project"), *args, "--repo-root", str(root)]`, and
  keeps its three refusals (`unavailable`, `unexpected_exit`, `unparseable`)
  and its timeout (D5).
- **`adopt_inspection`, `adopt_planning`, `adopt_apply`, `adopt_verify`.**
  `import agent_platform` becomes `from agent_tools import agent_platform`,
  and `from adopt_… import` becomes `from agent_tools.adopt_… import`, with
  every name list unchanged. Each docstring's "installed at
  `$HOME/.agents/lib/python/` behind the entry point's member guard" and
  "consumed at `$HOME/.agents/bin/resolve-project`" sentences are rewritten
  to the package facts.
- **`host_admission`.** A pure rename. This refines #150 D18's "source sibling
  or installed copy" home for the conformance evaluator. `workflow-state`
  keeps a transitional version of that home (D6).
  `HOST_ADMISSION_INTERFACE_VERSION` stays, because `workflow-state`'s
  installed-layout load still checks it until #178 (parent D12 deletes a
  handshake with the module that checks it).

**Refusals that become unreachable (D3).** `platform.library.missing`,
`adopt.library.missing` and the check's `library_unavailable` finding each
reported a defect in a separately installed library file. A launcher runs
`-I -m` from one store environment that contains every module, so a missing
or partial library cannot occur, and none of these codes can ever be emitted.
Keeping a code that no run can emit would be dead vocabulary with no test that
can fail. They are removed, the member tuples go with them, and so do the
tests that pinned them (D7). Every reachable refusal keeps its code,
`repair_id`, violations and exit code.

**Unset `HOME` (D4).** Today the resolver's bootstrap refuses a missing or
empty `HOME` as `platform.library.missing`. Once the bootstrap is gone,
`manifest_path()` would raise `KeyError`, which `main` would turn into
`resolver.internal`. The guard in `load_manifest` makes that input answer
`resolver_failure` / `platform.manifest.missing` on stdout, still with
exit 2. That is true: with no `HOME` there is no installed manifest. The same
guard serves the conformance ladder's platform stage. For `adopt-project`,
`plan` reads the manifest first, so the same guard makes it answer
`adopt.manifest.invalid`. `apply` and `verify` answer whatever their first
`HOME` read yields, for example `adopt.internal` from the state root. No suite
pins any of these, and #121 never documented them as a contract. These are the only observable deltas
of reachable input in this slice.

### The sibling-run helper (D5)

A new module, `agent_tools.siblings`, holds the one parent-D16 helper:

```python
def sibling_argv(module: str) -> list[str]:
    """argv that runs agent_tools.<module> under this interpreter, isolated iff we are."""
    return [sys.executable, *(["-I"] if sys.flags.isolated else []), "-m", f"agent_tools.{module}"]
```

- **Why it lives here.** `adopt_project` → `resolve_project` is the first
  packaged-to-packaged subprocess call. Shard rule 3 names "one shared
  package helper", and none exists yet.
- **Why the absolute path goes.** #121 D26's reason for it was that a stale
  generation earlier on `PATH` must never answer. In the installed layout,
  the helper binds the same store interpreter, and therefore the same
  package, that the calling launcher runs. That is stronger than the old path,
  so the rule is kept and the path is replaced.
- **What the child inherits.** The child inherits the caller's environment.
  The launcher has already cleared `NIX_PYTHON*` before `exec`, so those
  variables cannot reach it.
- **Under test.** The helper runs non-isolated, so the child resolves the
  source package through the recipe's `PYTHONPATH`.
- **What stays the same.** The resolver is still consumed only as a
  subprocess and is never imported, so #121 D26's contract-validation rule
  holds.

`promotion`, packaged before its callee, keeps running `resolve-project` by
name on `PATH`. Its suite injects resolver outputs through a `PATH` stub
(#127 D5), and the installed launcher on `PATH` answers it correctly.
Converting it to the helper would rewrite that suite's seam, which is outside
this cluster (Out of scope).

### workflow-state's transitional lookups (D6)

Both lookups use the idiom `workflow-state` already uses for its delivery
modules: `Path(__file__).parent.name == "scripts"` means the source layout.
#178 deletes both lookups when it moves `workflow-state`.

- **`resolve_project_argv()`.** In the source layout it returns
  `[sys.executable, "-m", "agent_tools.resolve_project"]`. Every suite that
  runs `workflow-state` passes an environment copied from `os.environ`, so
  the child reaches the source package through the recipe's `PYTHONPATH`.
  Otherwise it returns the `resolve-project` beside it, falling back to
  `~/.agents/bin/resolve-project`. That is today's installed branch,
  unchanged, and it now finds the launcher. The docstring names #177 D6 and
  #178.
- **`_host_admission()`.** In the source layout it imports
  `agent_tools.host_admission` normally. Otherwise it keeps today's lexical
  load of `~/.agents/lib/python/host_admission.py`, with its handshake. The
  interface check stays on both branches. Every failure still raises
  `WorkflowError("host admission library: …")`.
- **`home/common/agent-skills/default.nix`.** It keeps
  `.agents/lib/python/host_admission.py`, now sourced from
  `../../../python/agent_tools/host_admission.py`. A comment says the entry
  exists only for `workflow-state`'s transitional load and that #178 deletes
  it. The module imports only the standard library, so the lexical load of
  the store copy still works. AC2 names only the platform library, and
  `agent_platform` leaves `~/.agents/lib/python`.

### Wiring (D1)

- **Command table.** In `lib/agent-tools.nix`, `commands` becomes
  `adopt-project`, `agent-evidence`, `agent-model-matrix`, `conformance`,
  `context-map-lint`, `diff-scope`, `promotion`, `resolve-project`, one per
  line, sorted. The #175 D14 evaluation assertion checks the three new rows,
  and the recursive walk import-checks all twelve new modules (eleven moved,
  plus `siblings`).
- **Home.** Deleted from the literal set:
  - `.agents/bin/resolve-project`, `.agents/bin/conformance` and
    `.agents/bin/adopt-project`;
  - both `.agents/bin/conformance-registry` and `.agents/bin/conformance-checks`,
    with their comment;
  - `.agents/lib/python/agent_platform.py` and the four
    `.agents/lib/python/adopt_*.py` entries, with their comments.

  The manifest entry keeps its path (parent D15). Its comment loses "the
  shared platform library and". Under #175 D5, a leftover entry would be a
  conflicting definition and fail evaluation. No `nixfmt` run (#175 D13).
- **Recipe.** `agent-workflow-tests` gains `tests/test_agent_tools_siblings.py`,
  inserted after `tests/test_agent_tools_canonical.py`. No recipe line
  otherwise changes, because every family suite already runs under
  `PYTHONPATH`.

### Test re-points and deletions (D7, D8)

Test edits change only how code is located, as in #175 D7 and #179 D6. The
exceptions are the deletions, re-homings and literals listed here.

**Mechanics, all family suites.**
- Every `sys.path.insert` is deleted. Sibling-suite imports become relative:
  `from .test_resolve_project import (…)`, `from .test_adopt_project import (…)`
  and `from .conformance_test_support import (…)`. The name lists stay
  unchanged, minus any deleted name. This follows the precedent of
  `test_host_admission`'s `from .test_workflow_state import`.
- Script runs become `[sys.executable, "-m", "agent_tools.<module>", …]`.
- `load_module()` helpers become package imports and lose their
  `sys.modules` evictions:
  - `test_resolve_project.load_module` returns `agent_tools.resolve_project`;
  - `conformance_test_support.load_module` returns `agent_tools.conformance`.

  Every rebinding test already restores through `Rebinding`/`addCleanup`, so
  one shared instance couples nothing.
- The source-file constants (`SCRIPT`, `LIBRARY`, `RESOLVER`,
  `ADOPT_LIBRARIES`) are deleted or re-pointed to `python/agent_tools/…` where
  a source-text scan still reads them.
- Fake `HOME`s keep the manifest, the declaration and the registry
  (#147 D7 as refined by the parent). They no longer hold a library or a
  resolver copy. `install_home` loses its `library`, `library_suffix`,
  `adopt_libraries` and `adopt_suffix` parameters.
- `PlatformHome` keeps its `HOME` pin and drops the `agent_platform`
  eviction.

**Hermetic environment (parent D8).** `HERMETIC_ENV` gains
`"PYTHONPATH"`: the recipe's entries, made absolute, exactly as
`tests/promotion_test_support.make_env` builds it. `platform_env` inherits it.
Outside a recipe, the lookup raises at import, which is parent D8's intended
failure.

**Deleted, because each exercises only deleted machinery (parent D12, D3):**
- `test_resolve_platform.PlatformLibraryTest`, except its unset-`HOME` case,
  which is re-homed below;
- `test_resolve_project.library_members`;
- the `bootstrap_platform_library()` assertion in
  `SchemaReasonDispatchTest.setUp`;
- `test_conformance.BootstrapFailureTest` (the lone-entry-module run);
- the `library` subcase of
  `PlatformLadderTest.test_a_broken_installation_fails_resolvable_at_the_platform_stage`,
  while its `manifest` subcase stays;
- `AdmissionDeclarationCheckTest.deployed_run` and its two deployed-layout
  tests;
- `test_adopt_project.AdoptLibraryTest`, with `declared_members`;
- `test_adopt_project_boundaries.LibraryBindingTest`, with invariant 5 of its
  docstring (the list is renumbered);
- `test_conformance_registry.PromotionLiteralPinTest.test_no_installed_engine_file_names_the_package`.
  Its premise, #127 D27, was that the engine files are installed verbatim in
  `.agents/bin`. That premise is gone, and the modules now necessarily import
  `agent_tools`. Its sibling test pinning the literals stays.

**Re-homed (D7).**
- The unset-`HOME` case becomes a test in `test_resolve_platform`'s manifest
  class. It runs `-m agent_tools.resolve_project resolve` with `HOME` removed
  from the environment, and asserts exit 2, empty stderr, and the
  `resolver_failure` / `platform.manifest.missing` object (D4).
- `ForwardStepRefusalTest.test_ambiguous_forward_step_is_adopt_failure` needed
  a patched library, because the real one refuses two records for one
  `from_schema`. That is no longer possible, so the case moves to the
  module-interface seam. It calls `adopt_planning.select_forward_step` with a
  manifest carrying the two records and asserts that it raises `AdoptError`
  with code `adopt_failure` and repair id
  `adopt.manifest.forward_step_ambiguous`, the same pair the CLI case
  asserted.
- `test_adopt_project`'s generic-wrapper case imports
  `agent_tools.adopt_project` and patches `inspect_repository` on it, keeping
  its assertions.

**Outside the family's suites.**
- `test_delivery_workflow.test_public_source_and_installed_admission_fail_closed`:
  the source layout no longer copies `host_admission.py`. The
  deleted-library refusal is asserted in the installed layout only, where the
  lexical load remains, and the installed copy comes from the package path
  (D6). Its other assertions are unchanged.
- `test_workflow_skill_contracts`: the `LEGACY_MIGRATION_INPUTS` key
  `home/common/agent-skills/scripts/adopt_inspection.py` becomes
  `python/agent_tools/adopt_inspection.py`. The legacy scan's pathspec already
  covers `python`, and an entry that stops matching fails the scan. The
  policy-surface fixture copies `python/agent_tools/resolve_project.py` into
  its fake `.agents/bin/resolve-project`. It only checks that file's presence
  and executable bit.
- `test_shell_example_contracts.COMMAND_VOCABULARY` drops
  `conformance-checks` and `conformance-registry`. It is documented as "every
  `~/.agents/bin` helper plus common tools", and no fence names either one.

### The installed-layout test and the helper's test (D9)

`tests/test_agent_tools_launchers.py` keeps its structure and changes in two
places:

- `LAUNCHER_FLOOR` gains `adopt-project`, `conformance` and
  `resolve-project`, so it holds the seven commands that #175, #179 and #177
  accepted as launchers. It stays a floor, not the full set, which the
  command table owns (#175 D8), so `promotion` is still not listed. The
  comment names #177 beside #175 and #179.
- `setUp` also writes a top-level `agent_platform.py` into the hostile
  directory. That module writes the marker and exits 97, exactly as the fake
  package's `__init__` does. This makes the issue's demo ("a fake
  `agent_platform` on `PYTHONPATH` is not imported") a committed assertion:
  the existing check that the marker appears in neither stream now also
  covers a bare-name platform import. That was the old bootstrap's adversary.
  A leftover bare `import agent_platform` would already fail this run with an
  exit other than 0, because `-I` hides every channel. The file makes the
  demo's adversary concrete. It does not add a second guard.

All three new commands use argparse with a pinned `prog`, so the `--help`
probe needs no misuse entry.

`tests/test_agent_tools_siblings.py` is a seam-1 module-interface test. It
checks both branches of `sibling_argv` in process, with `sys.flags` patched to
an object whose `isolated` is 0 and then 1. It also makes one real run: it
executes `sibling_argv("resolve_project") + ["--help"]` and asserts exit 0 and
`usage: resolve-project `. The adopt suites exercise the non-isolated branch
end to end. The installed branch is shown by the demo (AC section).

### Living documents (D10)

- **`CLAUDE.md`.** "validated by `host_admission.py`" becomes "validated by
  `agent_tools.host_admission`". The "Agent helper package" paragraph stays
  true: the remaining flat helpers still live in `scripts/`.
- **`home/common/agent-skills/default.nix`.** Its comments are re-pointed as
  listed in the Wiring section.
- **Skill prose, the agent-skills README and the standards shard** name
  commands and `~/.agents/bin` paths, never these script paths. They need no
  edit.
- **Point-in-time records** keep their paths: the specs and plans under
  `.agents/artifacts` that cite `scripts/…` or D26/D27/D40.

### In-flight overlap (D11)

This was checked on 2026-09-28 against every worktree branch (#100, #127,
#152, #169, #207, and the control-delivered-candidate fix) and the open PRs,
of which there were none. No branch touches the moved files, their suites,
`python/`, `lib/agent-tools.nix` or the installed test, so parent D5's gate
holds. Edits to the shared wiring files stay local, with no reflow.

### Plan order (D12)

1. **The sibling helper and its test.**
2. **One atomic task** that moves all eleven files, with the wiring, both D6
   lookups, and every D7/D8 test edit. No smaller subset keeps the suites
   green:
   - `conformance` loads the resolver and `host_admission` by path;
   - the resolver and `adopt-project` bind the one shared `agent_platform`
     from one installed directory;
   - a flat `conformance_checks` could not import the package in the
     installed layout.
3. **The installed-layout floor** and the hostile `agent_platform`.
4. **The living documents.**

Every commit keeps `just build`, `just agent-workflow-tests` and
`just agent-installed-skill-tests` green.

### Acceptance criteria and how each is verified

- **AC1: the three commands are package launchers exercised by the
  installed-layout test.** `just agent-installed-skill-tests` shows the floor
  subtests, the hostile runs and the controls for `resolve-project`,
  `conformance` and `adopt-project`. `test_promotion_installed` still passes
  against the built `conformance` launcher.
- **AC2: no platform library under `~/.agents/lib/python`.** In the built
  `home-manager-files`, `.agents/lib/python` holds no `agent_platform.py` and
  no `adopt_*.py`. Its remaining entries are #178's delivery modules,
  `artifact_budget.py`, and D6's transitional `host_admission.py`.
- **AC3: no `sys.path` edit, origin check or file-path loader in the family's
  modules or tests.**
  - `git grep -nE "importlib|SourceFileLoader|spec_from|sys\.path|__file__|loaded_from" -- python/agent_tools`
    returns nothing.
  - The same pattern without `__file__` returns nothing over the family's
    suites and `conformance_test_support.py`. Their `REPO_ROOT` constants
    locate data files, not code.
- **AC4: no conformance library entries in `.agents/bin`.** The built tree's
  `.agents/bin` has no `conformance-registry` and no `conformance-checks`.
- **Regression floor.**
  - `just agent-workflow-tests` passes. Pre-existing assertions are unedited
    apart from the D7/D8 deletions, re-homings and location literals.
  - `just build` passes, import-checking all twelve new modules.
  - The built launchers' `--help` output is byte-identical to the base
    scripts run through a link named for the command.
- **Demo, shown during verification and not committed.** With `HOME` at the
  built tree:
  - `resolve-project resolve --repo-root <checkout>` and
    `conformance run --purpose doctor --repo-root <checkout>` answer;
  - `adopt-project verify --repo-root <checkout>` runs its resolver child
    through the isolated branch of `sibling_argv`.

## Test seams

This slice uses the parent's first two seams and adds no others:

1. **Command contract and module interface, from source.**
   - The family's existing suites run under the recipe's `PYTHONPATH`, and
     `HERMETIC_ENV` forwards it (parent D8).
   - The helper's test and the re-homed ambiguous-forward-step case are
     module-interface tests.
2. **Installed layout.** `tests/test_agent_tools_launchers.py`, with the
   extended floor and the hostile top-level `agent_platform` (D9).

Seam 3, the guard's registered hook, is untouched.

## Out of scope

- **`workflow-state` itself**, and deleting its two D6 lookups: #178. The
  same goes for the delivery family, `artifact-budget` with its wrapper,
  `review-package`, and emptying `~/.agents/lib/python`.
- **Converting `promotion`'s `PATH` call to `sibling_argv`.** It rewrites
  #127's `PATH`-stub seam. It is flagged for a follow-up issue owned by the
  shipping phase.
- **Replacing the conformance registry's promotion literals** with imports
  from `promotion_schema`. The #127 D10 pin still guards them.
- **Deleting `HOST_ADMISSION_INTERFACE_VERSION`**: #178, with the loader that
  reads it.
- **Changing any command's argv, help or error vocabulary** beyond D3's
  unreachable codes and D4's unset-`HOME` answer.
- **Splitting oversized functions**, relocating test files, or switching the
  recipe to discovery (parent Out of scope).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Move exactly eleven files: the ten the issue names plus `host_admission`, via `git mv`, to flat modules; three command-table rows; delete the family's bin links, both conformance library links, and the `agent_platform`/`adopt_*` lib entries | Parent D1, D12, D16 (caller and path-located callee move together); issue AC3; #179 D1 | Keeping `host_admission` flat with a transitional loader in `conformance_checks` breaks AC3's "no file-path loader in the family's modules" |
| D2 | Per-move edits follow #175 D2; `conformance` keeps `registry`, `CHECKS_MODULE` and `load_resolver()` as package-import aliases; docstrings and comments describing deleted machinery or install paths are rewritten | #179 D2 (aliases keep call sites and test lines unchanged); parent D14 rename pairing; the-bar Moves keep their history | Importing under module names rewrites every engine call site and test access |
| D3 | `platform.library.missing`, `adopt.library.missing`, the member tuples, and `host.admission.declaration`'s `library_unavailable` reason are removed as unreachable, along with their tests; `HOST_ADMISSION_INTERFACE_VERSION` stays for `workflow-state` | Parent D2 (one store env), D12; the-bar Production-grade, Tests that can fail; refines #150 D18: the library's home moves into the package, and conformance imports it rather than loading it | Keeping the codes declared leaves dead vocabulary that no test can fail on |
| D4 | `agent_platform.load_manifest` refuses an unset or empty `HOME` as `platform.manifest.missing`; this is the resolver's only reachable delta (formerly `platform.library.missing`, exit 2 either way). `adopt-project`'s unset-`HOME` repair id follows its first `HOME` read, and it is unpinned | Issue regression floor (error shapes, exit codes); the-bar Root causes (no `KeyError` leak into `resolver.internal`) | No guard: unset `HOME` becomes `resolver.internal`, a misleading internal failure. Keeping a `HOME` check that emits the library code names a file that no longer exists |
| D5 | New `agent_tools.siblings.sibling_argv(module)`, meaning `sys.executable`, `-I` iff the caller is isolated, then `-m`; `adopt_project.run_resolver` uses it instead of `$HOME/.agents/bin/resolve-project`; `promotion` keeps its `PATH` call | Parent D16; shard rule 3; #121 D26's intent (no stale generation answers) is held more strictly by the same store interpreter; #127 D5 `PATH`-stub seam | Keeping the absolute bin path means a packaged module locates a packaged sibling by path. Converting `promotion` now rewrites another cluster's test seam |
| D6 | `workflow-state` source layout (`parent.name == "scripts"`) runs `-m agent_tools.resolve_project` and imports `agent_tools.host_admission`; the installed layout keeps its bin-sibling resolver and its lexical `~/.agents/lib/python/host_admission.py` load, whose entry is now sourced from the package file; #178 deletes all of it | Parent D16 transitional lookup; `workflow-state`'s existing `scripts` idiom in `_delivery` | Loading `<repo>/python/agent_tools/host_admission.py` by path breaks the copied test layouts. Dropping the lib entry breaks installed `workflow-state` before #178 |
| D7 | Delete the bootstrap-only tests listed in the spec. The unset-`HOME` case is re-homed as a manifest refusal; the ambiguous-forward-step case moves to the module seam (`select_forward_step`); #127 D27's no-`agent_tools` pin is deleted (reverses #127 D27, whose installed-verbatim premise is gone) | Parent D9, D12; issue ("fake-`HOME` tests that existed only to exercise that bootstrap"); the-bar Tests that can fail | Keeping the ambiguous case at the CLI needs a patched library, which is impossible without a loader. Keeping the D27 pin forbids the package imports this slice requires |
| D8 | Suites use relative sibling imports and `-m`; `HERMETIC_ENV` forwards an absolute `PYTHONPATH` as `promotion_test_support` does; `test_delivery_workflow`'s deleted-library refusal is asserted only in the installed layout; the legacy-scan exemption key and the policy fixture's copy path are re-pointed; the vocabulary drops the two library names | Parent D8; #179 D6; `promotion_test_support.make_env` precedent; D6 (the source layout no longer reads a sibling file) | Absolute `from home.common…` imports add a second convention. Keeping the source-layout deletion assertion tests a lookup that no longer exists |
| D9 | The installed floor gains the three new commands and stays a floor (#175 D8); the hostile dir adds a top-level `agent_platform.py` marker; a new `tests/test_agent_tools_siblings.py` covers both helper branches in process plus one real `-m` run | Parent D9 seam 2; issue Demo; #175 D8, D14; the-bar Tests that can fail | Demo-only proof of the `agent_platform` adversary leaves nothing committed. Testing the helper only through the adopt suites leaves the `-I` branch untested |
| D10 | Re-point `CLAUDE.md`'s `host_admission.py` mention and the `default.nix` comments; skill prose and the standards shard are unchanged | the-bar Moves keep their history; parent D14 | Rewriting the "Agent helper package" paragraph is unneeded, because it stays true until #178 |
| D11 | Take the cluster now: no worktree branch or open PR touches its files | Parent D5; check on 2026-09-28 | Waiting has no blocker to wait on |
| D12 | Plan order: helper, then one atomic move of all eleven files with the wiring, D6 and the D7/D8 test edits, then the installed floor, then docs; every commit green | Parent D14; #179 D12 precedent; the path loaders and the shared `agent_platform` bind every subset together | Per-module moves need throwaway shims at every step, because conformance loads the resolver and `host_admission` by path, and the resolver and adopt share one installed platform directory |
| D13 | `tests/test_agent_tools_launchers.py` exempts `workflow-state`, by name, from "an `.agents/bin` entry naming `agent_tools` is a generated launcher" while it carries D6's lookups; the exemption lands with them and #178 deletes both | D6 puts the text `agent_tools` into the flat installed `workflow-state`, which the enumeration would otherwise reject; #175 D8; the-bar Tests that can fail | Selecting entries by the launcher pattern instead of the package bytes stops catching a hand-written entry that names the package. Spelling the module name so the bytes never appear hides the dependency |
| D14 | Prose the move makes false is corrected in the move's own commit: the registry's promotion-literal comment drops its "installed standalone, imports no package module" clause (refines D1's "comment unchanged"); `EvaluatorResolutionTest` drops its second `load_module()` and its fresh-instance docstring; `PromotionLiteralPinTest`'s docstring drops #127 D27 | the-bar Moves keep their history (living text stays true); D2, D7 | Leaving the sentences as they are keeps comments and test docstrings that describe a loader that no longer exists |
| D15 | Task 1's real `-m` run of `sibling_argv` targets the already-packaged `diff_scope`, not `resolve_project` (refines D9), so the helper's commit is green before the move; the adopt suites and the demo cover the resolver child | D12 (every commit green); D9 | Targeting `resolve_project` fails until the move lands, or ties the helper's test to the atomic move |
