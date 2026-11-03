# The delivery family moves into agent_tools

Design, 2026-11-03, for issue https://github.com/fagenorn/nix-config/issues/178.
It is the last cluster slice of the accepted parent design,
[One package for the agent workflow helpers](2026-09-24-agent-tools-package-design.md),
and follows the shape of the resolver slice,
[#177](2026-09-28-issue-177-resolver-family-move-design.md). Every parent row
and every #177 row binds. This spec cites them as "parent D*n*" and
"#177 D*n*" and restates none of them. It was written unattended
(`from-issue --auto`), so each non-obvious call it makes is a row in the
Decision ledger below.

## Problem

The delivery family is the last agent-workflow Python left as flat files in
the agent-skills `scripts` directory: `workflow-state`, the delivery runtime
with its wire and builder modules, the delivery model package, and the
artifact-budget validator with its bash wrapper. It carries the last loader
mechanisms the parent set out to delete:

- `workflow-state` loads the delivery runtime, the budget validator and the
  host admission library by file location, checks two module-load version
  handshakes, and finds the budget policy and `resolve-project` from its own
  `__file__`. Two of those lookups are #177's transitional ones (#177 D6).
- The delivery runtime loads the delivery model, the wire module and the
  builder by file location, each behind its own version handshake.
- The budget validator loads the delivery model by file location, behind the
  model's handshake.

Nix installs these modules a second time under `~/.agents/lib/python` so that
the installed copies can find each other. `workflow-state` is the one "script
launcher" in the command build, and `artifact-budget` is a bash wrapper that
runs whichever `python3` is first on `PATH`, without `-I`, so a `PYTHONPATH`
can shadow the standard library inside the budget authority (issue 259's
record, B4-I1, tracked to this issue). The delivery model's public
`canonical_bytes`/`canonical_digest` are a format of their own, but the name
`canonical_bytes` is also exported by two other package modules with
different formats. The suites grew around the machinery: fake
`~/.agents/lib/python` trees, copies of the whole `scripts` tree made only to
give the helper a different policy, and tests that exist only to prove a
handshake refuses.

The user needs the move to be invisible. Command names, `~/.agents/bin` and
`~/.agents/share` paths, argv/stdin/stdout/exit contracts, sealed delivery
digests and stored ledgers must not change. A ledger the installed (base)
helper wrote must validate and progress under the moved one, because that is
the state on disk at the moment of the switch.

## Solution

One PR delivers the following:

- It moves ten files into `python/agent_tools/` with `git mv` (D1, D2): the
  four flat modules, the five-file delivery model package, and the budget
  validator. It deletes the `artifact-budget` wrapper.
- It replaces every file-location loader, `__file__` lookup and module-load
  handshake in the family with plain package imports, and deletes the
  refusals that become unreachable along with the tests that pinned them (D4).
- `workflow-state` reads the budget policy only from the installed share path
  (D5), and runs the resolver through `agent_tools.siblings.sibling_argv`,
  which deletes #177's two transitional lookups (D6).
- It adds the `artifact-budget` and `workflow-state` command-table rows,
  deletes the script launcher, and deletes every `~/.agents/lib/python` entry,
  so the built home has no such tree (D1).
- In a later commit of the same PR, the delivery model's public format
  functions are renamed to `delivery_bytes` and `delivery_digest` (D3).
- It re-points the suites to import normally and run `-m` (D8). It extends the
  installed-layout test (D10) and adds one committed regression test that
  drives a base-written ledger and compares base and moved delivery output
  (D7).
- It re-points the living documents and the light-lane risk paths (D11).

## Decisions

### What moves (D1, D2)

| Today (agent-skills `scripts/`) | Module | Launcher |
|---|---|---|
| `workflow-state.py` | `agent_tools.workflow_state` | `~/.agents/bin/workflow-state` |
| `workflow_delivery.py` | `agent_tools.workflow_delivery` | none (library) |
| `workflow_delivery_wire.py` | `agent_tools.workflow_delivery_wire` | none (library) |
| `workflow_delivery_build.py` | `agent_tools.workflow_delivery_build` | none (library) |
| `delivery_model/` (`__init__`, `_canonical`, `_objects`, `_reconcile`, `_wire`) | `agent_tools.delivery_model` (subpackage) | none (library) |
| `artifact_budget.py` | `agent_tools.artifact_budget` | `~/.agents/bin/artifact-budget` |
| `artifact-budget` (bash wrapper) | deleted | replaced by the launcher |

Module names follow parent D1. The delivery model becomes the package's first
subpackage and keeps its private submodules (D2). The module-tree walk in the
Nix build names it `agent_tools.delivery_model` and import-checks each
submodule. The `pyproject.toml` package discovery already includes
`agent_tools*`. After the move, the agent-skills `scripts` directory is gone.

The review packaging the issue also names (`review-package`, `review-pack`,
`review-feasibility`) already lives in the package. Its issue items are
already true at base, so it gets no edit (D6).

### How each file changes (D4)

Every move follows #177's per-file rule: the shebang and the executable bit
go, absolute `agent_tools` imports replace the machinery, imports left unused
are removed, and the `__main__` block stays. Each docstring or comment that
describes a deleted mechanism or an install location is rewritten to the
package fact. Nothing else changes: no split functions, no reformatting, and
no renamed helper beyond those named here and in D3. Both commands already
pin `prog`, so their `--help` output stays byte-identical.

- **`workflow_state`.**
  - It imports `artifact_budget`, `host_admission`, `DeliveryRuntime` and
    `sibling_argv` from the package at module scope.
  - `_delivery()` keeps its name, its per-notes-limit runtime cache and its
    `delivery runtime: …` wrapping of construction errors. It constructs
    `DeliveryRuntime` directly, and its file load and handshake are deleted.
  - `_host_admission()` keeps its name and its call sites, and returns the
    imported module (#177 D2's accessor rule). Its cache, both layout
    branches and its handshake are deleted.
  - `_artifact_budget()` and `artifact_budget_paths()` are deleted.
    `artifact_budget_policy()` returns the resolved policy path, or `None`
    (D5). `artifact_budget_invoke` calls the imported validator's `invoke`
    and appends `--policy` exactly as today. `phase_notes_maximum` reads the
    same path, and its three refusal texts are unchanged.
  - `resolve_project_argv()` is deleted. `resolve_project_policy` runs
    `[*sibling_argv("resolve_project"), "resolve", "--repo-root", root]`, and
    keeps its timeout and its refusal texts (D6).
- **`workflow_delivery`.**
  - `_load_model`, `_load_projection`, `_load_builder` and
    `WORKFLOW_DELIVERY_INTERFACE_VERSION` (in `__all__` too) are deleted.
  - `DeliveryRuntime.__init__` binds the imported delivery model,
    `DeliveryBuilder(model, notes_max_characters=…)` and
    `DeliveryProjection()`. Its notes-limit `ValueError` stays.
  - The builder keeps its model injection.
- **`workflow_delivery_wire`, `workflow_delivery_build`.** Only their
  handshake constants and the docstring sentences about lexical loading
  change.
- **`delivery_model`.** `MODEL_INTERFACE_VERSION` leaves `_canonical` and
  `__all__`. The D3 rename lands in its own later commit.
- **`artifact_budget`.**
  - `_delivery_model()` and `importlib.util` are deleted, and the module
    imports `delivery_model` from the package. The two delivery validators
    bind that module.
  - The pre-decode availability probe for the four delivery boundaries goes,
    because it can no longer fail.
  - The local strict-load hooks and the restated summary and recommendation
    key sets stay (D9). The key sets' comment drops "which this flat script
    does not import" and states the real reason: the authority does not
    import the gate whose output it validates.
- **`host_admission`** (already packaged). `HOST_ADMISSION_INTERFACE_VERSION`
  is deleted, because its only reader goes (#177 Out of scope). The docstring
  naming `workflow-state.py` is re-pointed.

**Refusals that become unreachable (D4).** The following each reported a
missing, foreign or skewed module file. One isolated store environment holds
every module (parent D2), so none of them can be emitted any more: the
validator's `delivery model is unavailable` and `unsupported delivery model
interface`, the runtime's `… is unavailable` and `unsupported … interface`
pair for the model, the wire module and the builder, and `workflow-state`'s
`host admission library: …` and `artifact-budget module: …`. They are removed
with their tests (#177 D3). Every reachable refusal keeps its text, its exit
code and its stream.

### The budget policy (D5)

Today `workflow-state` uses the repository's policy file beside the `scripts`
directory in the source layout. Installed, it uses
`~/.agents/share/artifact-budget-policy.json`, resolved to its target. It
passes that target as `--policy`, because the validator refuses a symlinked
explicit policy.

After the move there is one rule for both layouts: today's installed branch.
`artifact_budget_policy()` resolves `$HOME/.agents/share/artifact-budget-policy.json`
strictly, or returns `None`. The never-existing `<script dir>/../share`
candidate and the source branch go. For the installed layout this is
byte-for-byte today's behaviour.

Suites that ran `workflow-state` from source now hold the policy in their test
`HOME`'s share directory, as a symlink to the repository's policy. This is
what the orchestrate world and the review-package suite already do. The
lifecycle harness's `HOME` gains that one link. A suite that copied the whole
`scripts` tree only to run against a policy of its own, such as the
delivered-control suite's `isolated_workflow`, instead writes that policy into
a `HOME` share of its own and runs `-m`.

A source run outside the suites (the agent-skills README's
`PYTHONPATH=<checkout>/python` instruction) therefore validates against the
installed share policy, not the checkout's (D14). That is already what every
`artifact-budget` it reaches by name on `PATH` does. A change to the policy's
shape fails such a run loudly with the validator's policy refusal, and is
exercised from source the way the suites do it, with `HOME`'s share pointing
at the checkout's policy.

### Sibling calls and the review packaging (D6)

- **`workflow-state`'s calls.** It runs the resolver through `sibling_argv`.
  It keeps running the budget validator in process (issue 498), now through a
  plain import. It keeps running `git` by name. These are its only child
  processes.
- **The review packaging.** The issue's items for it are already true at
  base: `review-package` is a launcher on the installed floor, nothing in the
  package edits `sys.path`, and it runs `sdd-workspace` and `artifact-budget`
  by command name on `PATH` (#152).
- **Callers packaged ahead of their callee.** These modules run
  `artifact-budget` or `workflow-state` by command name on `PATH`:
  `review_budget`, through which `review-package`, `review-feasibility`,
  `review_gate` and `sdd-gate` reach `artifact-budget`;
  `orchestrate_control` and `ship_delivery_compile`, which run both; and
  `sdd_gate`, which runs `workflow-state`. After this move those commands are
  packaged siblings, so shard rule 3 would route them through the helper.
  They keep their calls in this slice, exactly as `promotion` kept its
  resolver call in #177 (#177 D5). Their suites inject faults at that `PATH`
  boundary, and `review_budget` is being edited right now on the in-flight
  #559 branch (D12).
- **What closes the hazard.** The name on `PATH` now resolves to an isolated
  `-I` launcher, which closes B4-I1.
- **Follow-up.** Converting those callers, or refining rule 3 for
  deployed-command boundaries that a suite fault-injects at, is one follow-up
  issue for the shipping phase to file (Out of scope). This narrows the
  issue's "`review-package` runs its packaged siblings through the package
  helper" clause.

### Wiring (D1)

- **Command table.** `lib/agent-tools.nix` gains `artifact-budget` and
  `workflow-state`, inserted in sorted order, one per line. `scriptLauncher`
  and its export are deleted, and the header comment drops the script
  launcher. The evaluation assertion that every row has a module covers both
  new rows.
- **Home.** These entries are deleted: the hand-written
  `.agents/bin/workflow-state` and `.agents/bin/artifact-budget`, and every
  `.agents/lib/python/*` entry (`artifact_budget.py`, the three
  `workflow_delivery*` files, `delivery_model`, and the transitional
  `host_admission.py`), each with its comment. The `.agents/share` entries keep
  their paths and sources (parent D15). The host-admission comment is
  re-pointed to the package. `home.packages`' `python3` stays, because
  `task-brief`'s heredocs use it. No `nixfmt` run.
- **Contract delta.** The installed `artifact-budget` now runs `-I` under the
  package environment, so `PYTHONPATH` and the `PATH` `python3` no longer
  reach it. Its argv, streams and exit codes are unchanged.

### Test re-points and deletions (D4, D8)

Test edits change only how code is located, except for the deletions,
re-homings and the D3 rename listed here.

**Mechanics.**
- Subprocess runs of a moved file by path become
  `[sys.executable, "-m", "agent_tools.<module>", …]`. Every `PATH` shim that
  ran a moved file by path (the launch-commit and launch-scope shims, the
  orchestrate world's, and the sdd-gate and ship-delivery shims) runs
  `sys.executable -m agent_tools.<module>` under the inherited `PYTHONPATH`.
- Suites that linked the deleted wrapper or built a fake
  `~/.agents/lib/python` (task-brief, review-package, review-feasibility, the
  retained-review support's `source_budget_env`) write such a shim and drop the
  library tree. There is no shared shim helper.
- Path loads of moved product code become normal imports:
  `load_source_module`/`load` of the model, builder and wire, `load_model`,
  and `runpy.run_path` of the runtime.
- Source-text scans re-point their constants to the package files: the clock
  scan over `workflow_delivery*` and `delivery_model`, the moved-gate check,
  and the skill-contract constants reader.
- The in-process runner (`_inprocess_cli.run_script`) keeps its contract,
  its compiled-code cache and its parity test, and is given
  `workflow_state`'s package source file (D8, D15). It changes no `sys.path`
  and uses no `importlib`, and the code it runs is the code the `-m` child
  runs.
- **Unchanged:** base-helper replays pinned to older commits, which archive
  those commits' `scripts` paths; the retained full tier's pinned-blob staging
  `HOME`; and test-module loads of test files.

**Deleted, because each exercises only deleted machinery (parent D12):**
- the artifact-budget suite's five lexical-loader cases, from
  `test_workflow_response_uses_source_and_lexical_installed_package` through
  `test_successful_loader_does_not_cache_missing_private_member`;
- the delivery-model suite's
  `test_source_and_generated_installed_layout_load_same_model`, and the three
  Nix-publication assertions of
  `test_nix_publication_and_managed_test_registration`, whose justfile
  registration assertion stays;
- the delivery-workflow suite's
  `test_public_source_and_installed_admission_fail_closed`;
- the launcher test's workflow-state special cases (D10).

**Re-homed.**
- `ArtifactBudgetPolicyResolutionTest` keeps its assertions that the
  installed symlinked policy reaches the validator as its resolved target and
  that no process is spawned. It now runs against the imported module with a
  `HOME` share symlink. Its library-file and library-bytecode assertions go.
- The issue-499 bytecode case runs `-m`, and points at the package's delivery
  module.
- The delivery-model `__all__` assertion loses `MODEL_INTERFACE_VERSION`
  (D4) and takes the D3 names.

### The installed-layout test (D10)

`tests/test_agent_tools_launchers.py` keeps its structure, with these
changes:

- `LAUNCHER_FLOOR` gains `artifact-budget` and `workflow-state`.
  `review-package` is already on it. The comment names #178.
- `NOT_LAUNCHERS`, `SCRIPT_LAUNCHER`, `workflow_state_launcher()`,
  `test_workflow_state_ignores_a_hostile_agent_tools`, the closure check's
  script-launcher branch and the `workflow-state` exception in the
  one-environment test are deleted (#177 D13: "#178 deletes both"). The
  generic hostile-channel loop and its controls now cover both new launchers.
  Both answer `--help` with exit 0 and `usage: <name> `.
- One assertion is added to an existing test: the installed home has no
  `.agents/lib/python`.
- `dependency_env`'s `python3` link served only the wrapper. It goes unless
  the plan finds another reader.
- The source side of the canonical-actual parity case gets the `-m` shim
  instead of the `scripts` directory and the library tree.
- `test_installed_workflow_state_mints_a_run_against_the_store_core` stays as
  it is.

### The ledger and digest regression test (D7)

One committed test class joins the delivered-control suite, beside the harness
that already builds contracts. It follows the base-helper replay pattern four
suites use: `git archive` the pinned base commit
`f6a48dcf66fbb2171f66920c32afd4f9e5056a93` (its `python/agent_tools`, its
agent-skills `scripts` and its policy), and run that commit's
`workflow-state.py` under that commit's `PYTHONPATH`. A missing commit fails,
and is never skipped. In one fixture project and `HOME`:

1. The base helper runs `init-run` and one `control` round that spawns an
   attempt. It then runs `build-delivery --kind contract` for a fixture
   input.
2. The moved helper (`-m agent_tools.workflow_state`) runs `register-worker`
   for the attempt the base helper spawned, then the next `control` round
   against that ledger. Each must exit 0, the control reply must pass
   `validate-report --boundary workflow-response`, and the ledger must keep
   `schema_version` 11 and hold the registered worker.
3. The moved helper runs the same `build-delivery` input. Its stdout must be
   byte-identical to the base helper's: sealed digests are unchanged.
4. The base helper then runs one more `control` round on the ledger the moved
   helper wrote, and must exit 0. A generation rollback after the switch puts
   the base helper back in front of those ledgers (D13).

### Living documents (D11)

- **`CLAUDE.md`.** The "Agent helper package" paragraph now says that all
  agent-workflow Python is the `agent_tools` package, and drops "is moving"
  and the flat-scripts sentence. The edit is net non-growing (the Instruction
  Budget gate).
- **The standards shard.** It drops its legacy-flat-script clauses: the
  intro's "a legacy flat script meets them…" and rule 1's "Each legacy script
  moves in with its cluster's PR." The index's globs stay, so a new flat
  script still loads the rule that forbids it (parent D6).
- **The agent-skills README.** Its source-run instruction (`workflow-state`
  as `python3 <checkout>/…/workflow-state.py`) becomes
  `PYTHONPATH=<checkout>/python python3 -m agent_tools.workflow_state`, and
  says the run reads the installed share policy (D14).
- **The retro skill.** Its helper-source line stops naming the deleted
  `scripts` directory.
- **The eval runner.** `workflow-state` and `artifact-budget` are now table
  commands, so the runner's dedicated `workflow-state` shim block goes. Its
  README's "one more shim" sentence goes, and the flat-helpers sentence
  narrows to `sdd-workspace`. The runner's shell test drops its
  `workflow-state` shim check.
- **Docstrings in already-packaged modules** that name `workflow-state.py`
  (`agent_platform`, `host_admission`) are re-pointed.
- **The light-lane risk paths.** The three delivery entries (the
  `workflow-state` file, the `delivery_model` glob and the
  `workflow_delivery*` glob) are re-pointed to their `python/agent_tools`
  paths, as #177 did for the resolver.
- **Point-in-time records** under `.agents/artifacts` keep their paths.

### In-flight overlap (D12)

Checked on 2026-11-03: there are no open PRs. The active
`worktree-issue-559-helper-self-describing` branch edits `review_budget`,
`review_feasibility`, their suite and `python/README.md`. This slice leaves
both modules and `python/README.md` alone, and edits only the budget-fixture
lines of `tests/test_review_feasibility.py`. A conflict there is a local
fixture merge. `worktree-fix-control-delivered-candidate` touches the moved
files, but it is untouched since 2026-09-24 and has no PR. If it is revived,
git's rename detection carries its hunks.

### Plan order

1. One atomic move: all ten files, the wrapper deletion, D4–D6, the wiring,
   and every D8 re-point and deletion, together with the D10 floor and
   deletions, and the living documents and risk paths that name the moved
   paths (the-bar, Moves keep their history). No smaller subset stays green.
   The runtime, the validator and `workflow-state` each load the delivery
   model or each other by path from the one `scripts` directory, and the
   installed home links one shared library tree.
2. The D3 rename, alone, so that both the move's renames and the rename's
   diff stay pure.
3. The D7 regression test, which then covers the move and the rename
   together.

Every commit keeps `just build`, `just agent-workflow-tests` and
`just agent-installed-skill-tests` green.

### Acceptance criteria and how each is verified

- **AC1: package launchers exercised by the installed-layout test.**
  - In the built home, `.agents/bin/workflow-state`, `artifact-budget` and
    `review-package` each fully match the `-m` launcher pattern.
  - `just agent-installed-skill-tests` passes, with all three on the floor and
    in the hostile-channel loop and its controls.
- **AC2: no `~/.agents/lib/python`.**
  - The built `home-manager-files` has no `.agents/lib/python`, which is the
    D10 assertion.
  - `git grep -n "lib/python" -- home/common/agent-skills/default.nix lib`
    returns nothing.
- **AC3: no handshake, file-location loader or `sys.path` edit in the
  package.**
  - `git grep -nE "MODEL_INTERFACE_VERSION|WORKFLOW_DELIVERY(_WIRE|_BUILD)?_INTERFACE_VERSION|HOST_ADMISSION_INTERFACE_VERSION|spec_from_file_location|module_from_spec|SourceFileLoader|sys\.path" -- python`
    returns nothing.
  - `git grep -n importlib -- python/agent_tools` lists only
    `review_witness`'s `importlib.resources`.
  - Data versions are untouched: `SCHEMA_VERSION = 11`,
    `CONTROL_INTERFACE_VERSION = 4`, the two direct-owner versions, and wire
    kinds.
- **AC4: the delivery and telemetry digest functions do not share a name.**
  - `telemetry_digest` is defined only in `agent_tools.canonical`, and
    `delivery_digest`/`delivery_bytes` only in `agent_tools.delivery_model`.
  - `git grep -nwE "canonical_digest|canonical_bytes" -- python/agent_tools/delivery_model python/agent_tools/workflow_state.py python/agent_tools/workflow_delivery.py python/agent_tools/workflow_delivery_build.py python/agent_tools/artifact_budget.py home/common/agent-skills/tests`
    returns nothing. Every use there today is a delivery-model use; the
    `canonical_bytes` of `review_forecast` and `verification_blocker` keep
    their names.
- **AC5: nothing in the package locates code from `__file__`.**
  - `git grep -n "__file__" -- python/agent_tools` lists only
    `adopt_references`, which matches the text `__file__` in scanned files as
    data.
  - `git ls-files home/common/agent-skills/scripts` is empty.
- **Regression floor.**
  - `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests` passes.
    Pre-existing assertions are unedited apart from the D4 deletions and
    re-homings, the D3 rename and location literals.
  - `just build` passes, and import-checks every new module, including the
    subpackage's submodules.
  - The D7 test passes: a base-written ledger progresses under the moved
    helper, the base helper accepts the ledger the moved one wrote, and
    `build-delivery` output is byte-identical.
  - The built `workflow-state --help` and `artifact-budget --help` match the
    base installed commands byte for byte.
  - The task-brief suite passes with `artifact-budget` reached on `PATH` and
    the policy at its share path.
- **Demo, shown during verification and not committed.** With a scratch
  `HOME` whose `.agents` links the built tree, and a ledger the base helper
  wrote:
  - the built `workflow-state init-run` and `control` answer exit 0 against
    that ledger;
  - `test ! -e <built home>/.agents/lib/python` holds.

## Test seams

This slice uses the parent's first two seams and adds no others:

1. **Command contract and module interface, from source.**
   - The family's suites run under the recipe's `PYTHONPATH`, through `-m`
     children, `-m` `PATH` shims, normal imports, and the in-process runner
     given the package source file.
   - The D7 base-helper replay follows the pattern of the attempt-custody,
     attempt-migration, control-cutover and verification-suspension suites.
2. **Installed layout.** `tests/test_agent_tools_launchers.py`, with the
   extended floor and the absent-library assertion (D10).

Seam 3, the guard's registered hook, is untouched.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "the installed layout changes: ~/.agents/lib/python is removed, artifact-budget becomes a package launcher, and the delivery model's digest function is renamed"}, "concurrency_or_persistence": {"value": "hit", "evidence": "workflow-state owns the persisted lifecycle ledger; ledgers written before the move must validate and progress unchanged"}, "open_design_questions": {"value": "doubt", "evidence": "the issue fixes D2-D16, but the delivery digest's new name and the test-loading seam are still to be chosen"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria plus a demo, more than four"}}, "paths": ["home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/workflow_delivery.py", "home/common/agent-skills/scripts/workflow_delivery_wire.py", "home/common/agent-skills/scripts/workflow_delivery_build.py", "home/common/agent-skills/scripts/delivery_model/_canonical.py", "home/common/agent-skills/scripts/artifact_budget.py", "home/common/agent-skills/scripts/artifact-budget", "python/agent_tools/workflow_state.py", "python/agent_tools/review_package.py", "home/common/agent-skills/default.nix", "lib/agent-tools.nix", "tests/test_agent_tools_launchers.py", "home/common/agent-skills/tests/test_workflow_state.py"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)
base f6a48dcf66fbb2171f66920c32afd4f9e5056a93

## Out of scope

- **Converting the packaged-ahead callers** (`promotion` → `resolve-project`;
  `review_budget`, `ship_delivery_compile`, `orchestrate_control` →
  `artifact-budget`; `orchestrate_control`, `ship_delivery_compile`,
  `sdd_gate` → `workflow-state`) to `sibling_argv`, or refining shard rule 3
  for deployed-command boundaries. That is one follow-up issue, owned by the
  shipping phase (D6).
- **Adopting `agent_tools.canonical`'s strict-load hooks** in
  `artifact_budget`, and de-duplicating its restated review key sets (D9).
- **Splitting `workflow_state`'s oversized functions**, owned by #117 and
  #125 (parent Out of scope).
- **Any change** to a command's argv, help or refusal vocabulary beyond D4's
  unreachable refusals, to a data-format version, or to the policy file.
- **The shell scripts** `sdd-workspace` and `task-brief`, their heredocs, and
  `home.packages`' `python3`.
- **Point-in-time records**, the base-helper replays pinned to older commits,
  the retained review evidence and its pinned-blob staging, relocating test
  files, and the test-file loads of test modules.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Move the ten files of the family via `git mv`; delete the `artifact-budget` wrapper; add the `artifact-budget` and `workflow-state` command-table rows; delete `scriptLauncher` and every `~/.agents/lib/python` entry; the move lands as one atomic task | Parent D1, D2, D12, D14; #177 D1, D12; issue AC1, AC2 | Per-module moves need throwaway shims, because the runtime, the validator and `workflow-state` load the model and each other by path from one directory, and the installed home shares one library tree |
| D2 | The delivery model becomes the subpackage `agent_tools.delivery_model`, keeping its private submodules and its facade | Parent D14 rename pairing; the Nix module walk and `pyproject` discovery already take subpackages | Flattening it into one module rewrites about 1,800 lines and loses rename pairing |
| D3 | The model's public `canonical_bytes`/`canonical_digest` become `delivery_bytes`/`delivery_digest`, with bytes unchanged; every caller and test is updated in one later commit; no alias; the private `_canonical` file keeps its name | Parent D11; the issue's What to build; AC4 is already true at base (`telemetry_digest`), but `canonical_bytes` is also exported by `review_forecast` and `verification_blocker` with other formats | Keeping the names, because AC4 holds, ignores D11's explicit rename. An alias keeps the old name alive for no caller (YAGNI) |
| D4 | Delete every file-location loader, `__file__` lookup and module-load handshake (`MODEL_`, the three `WORKFLOW_DELIVERY_`, `HOST_ADMISSION_`), the refusals they made unreachable, and the tests that only exercise them; `_delivery()`/`_host_admission()` keep their names as accessors; the policy-resolution and bytecode tests are re-homed | Parent D2, D12; #177 D2, D3, D7; the-bar Tests that can fail | Keeping the handshakes or refusals as defense in depth: nothing can vary across one store environment, and no test could fail on them |
| D5 | `workflow-state` resolves the budget policy only at `$HOME/.agents/share/artifact-budget-policy.json` (today's installed branch, passed as its resolved target); source-run suites link the repository policy into their test `HOME`, and copied-`scripts`-tree fixtures become `HOME` share fixtures | Parent D15, D16 (no `__file__`); the orchestrate-world and review-package fixture precedent | Package data read through `importlib.resources` gives the policy a second home. A new flag or environment variable changes the CLI contract |
| D6 | `workflow-state` runs the resolver through `sibling_argv` (deleting #177 D6's lookups) and imports the validator, the admission library and the runtime; the review packaging needs no edit (already true at base); the packaged-ahead callers that run `artifact-budget`/`workflow-state` by name on `PATH` keep doing so, and a follow-up is filed, which narrows the issue's review-package clause | Parent D16; #177 D5 (`promotion` precedent); the #152, #353 and orchestrate-control suites fault-inject at `PATH`; #559 is in flight on `review_budget`; the isolated launcher closes B4-I1 | Converting `review_budget` now rewrites the validator-fault seams of four suites, makes their refusal cases unreachable, and collides with #559 |
| D7 | One committed base-helper replay in the delivered-control suite, pinned to the base commit: the base helper writes a ledger and a contract; the moved helper progresses the ledger (exit 0, boundary-valid reply, schema unchanged) and builds byte-identical output | The issue's regression floor; the base-helper replays of four suites ("fetch it, do not skip"); the-bar Tests that can fail | A demo-only check commits nothing that fails if a later change breaks reading a pre-move ledger |
| D8 | Tests locate moved code by `-m` children, `-m` `PATH` shims (one per suite, no shared helper) and normal imports; the in-process runner keeps its file contract and is given `workflow_state`'s package source | Parent D8; standards shard rule 5; the issue-500 runner and its parity test; the launch-suite shim precedent | A `runpy.run_module` runner, because its parity probe would need a module importable by name, so a `sys.path` edit or a probe inside the package |
| D9 | `artifact_budget` keeps its local `_pairs_no_duplicates`/`_reject_constant` hooks and its restated review key sets; the key sets' comment states that the authority does not import the gate it validates | #177 D16 precedent; #179's note that the hook is #178's to adopt; the canonical hooks' wording differs (`duplicate JSON key 'k'` against `duplicate key "k"`); the-bar Defense in depth | Composing the canonical hooks changes the refusal detail or needs a translating local hook. Importing `review_gate`'s keys pulls the review stack, including the module that runs this command, into the authority |
| D10 | The installed floor gains `artifact-budget` and `workflow-state`; the workflow-state script-launcher special cases go; one assertion that the built home has no `.agents/lib/python` is added; the wrapper-only `python3` link goes | Parent D9 seam 2; #177 D13; issue AC1, AC2 | A demo-only check of AC2 leaves nothing committed that can fail |
| D11 | Re-point the living documents (`CLAUDE.md` with no net growth, the standards shard's legacy clauses, the agent-skills README, the retro skill, the eval runner and its README and test, docstrings) and the three light-lane risk paths in the move's commit; the standards index globs stay | The-bar Moves keep their history; parent D6, D14; #177 D10 and its resolver risk-path re-point; the Instruction Budget gate | Leaving the risk paths on deleted files silently drops the light lane's risk hits for the delivery family |
| D12 | Take the cluster now: #559 shares no moved file, and the delivered-candidate worktree has been stale since 2026-09-24 with no PR | Parent D5; the check made on 2026-11-03 | Waiting for #559: it shares only fixture lines, which merge locally |
| D13 | (grill) D7 also proves the rollback direction: the base helper accepts and progresses a ledger the moved helper wrote | A generation rollback after `just switch` puts the base helper in front of ledgers written since; the issue's regression floor ("stored ledger stays valid") | Proving only base-to-moved leaves a rollback untested, even though nothing in this slice should change the bytes |
| D14 | (grill; refines D5) A source run outside the suites reads the installed share policy; the agent-skills README says so; a policy-shape change is exercised from source by pointing `HOME`'s share at the checkout policy | D5; `artifact-budget` reached by name on `PATH` already reads the installed policy in such runs; the-bar Fail loud (a shape mismatch is a policy refusal, not a silent use) | Shipping the policy as package data so source runs read the checkout copy gives the policy a second home and changes the suites' `HOME`-policy seam |
| D15 | (grill; refines D8) The in-process runner keeps its file contract and compiled-code cache; this is the one in-process path, it edits no `sys.path`, uses no `importlib`, and runs the code the `-m` child runs; shard rule 5 is left unchanged | Issue-500 runner and its parity test; issue 497's suite CPU budget; standards shard rules 3 and 5 | A `runpy.run_module` runner re-reads the module on every one of the suites' in-process runs, and needs a rewritten parity probe that is importable by name. Amending rule 5 for one test helper is a policy change this slice does not need |
| D16 | (plan; refines "Unchanged" base-helper replays) The attempt-migration replay archives its pinned commit's `python/agent_tools` too and runs under that `PYTHONPATH`, as the custody, cutover and suspension replays already do; every replay that locates a file inside its archive keeps that commit's `scripts` literal | `eca16cd`'s helper validates each ledger through `_host_admission()`, which refuses a package `host_admission` without `HOST_ADMISSION_INTERFACE_VERSION` (D4), and today that replay runs against the current package; the cutover legs derive their archive paths from the moved constants | Keeping the constant for that replay contradicts D4 and AC3. Leaving the replay on the current package makes its positive control fail |
| D17 | (plan; extends D5) Every suite `HOME` a workflow-state run gets holds the policy link: the lifecycle and builder harness homes and each `make_home()` of the delivery-workflow suite gain it, and the two suites that call the module in process or spawn children that inherit `os.environ` point the process `HOME` at a policy-only home for the module (`setUpModule`); `HOME=<empty> just agent-workflow-tests` is a gate | A planning run at the base passed all 125 members with an empty `HOME` and wrote nothing there, so the suites never needed the developer's home; `validate_state` reaches `_delivery()`, which reads the policy; the-bar Tests that can fail | Patching `artifact_budget_policy` in tests replaces the seam under test. Leaving inherited runs on the real `HOME` passes only where a home is activated, and silently tests the installed policy |
| D18 | (plan; refines D8) `source_budget_env` writes an `artifact-budget` shim that runs the source tree's validator by its layout: `-m agent_tools.artifact_budget` when the tree has the module, else that tree's flat `scripts/artifact_budget.py` | The retained reproduction case clones `TOOL_COMMIT` (`7213928f`, flat layout) and calls `source_budget_env(…, clone)`; the derivation it runs calls `artifact-budget` by name | A package-only shim breaks that pinned reproduction. Re-pinning `TOOL_COMMIT` re-derives committed evidence, which is out of scope |
| D19 | (plan; extends D11) Also re-pointed in the move's commit: the `attempt_delivery` and `attempt_observations` docstrings ("the skill scripts"), the launcher test's module docstring (`NOT_LAUNCHERS`), and the eval tree test's script-path check, which now greps the table shim's `-m agent_tools.workflow_state` instead of being dropped | The-bar Moves keep their history; the regression floor allows location literals | Dropping the eval check loses the one assertion that the command-table loop now shims `workflow-state` |
| D20 | (plan) The review forecast models each moved file as a `delete` of its old path plus an `add` of its new path, with whole-file record sizes, in one boundary `all` | The record policy pairs only exact renames (`--find-renames=100%`), the forecast refuses `rename` (`projection_unavailable`), and issue 439 D2 keeps an edited move's oversized add half at exit 3; D1 makes the move one task | Sizing the moves as small rename records undercounts what `review-package` measures, breaking the conservative-bound rule. A pure-rename task is not green on its own (D1) |
