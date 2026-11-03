# Installed agent modules never run stale bytecode — issue 567

Design for https://github.com/fagenorn/nix-config/issues/567 (raised as
https://github.com/fagenorn/nix-config/issues/499 spec D5). Base: `fc13636d`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#498 Dn" and "#499 Dn"
cite those issues' design specs.

## Triage

Input: `{"signals": {"contract_change": {"value": "no", "evidence": "No schema, CLI or loader interface changes; installed module names and interfaces stay the same."}, "concurrency_or_persistence": {"value": "doubt", "evidence": "The fix invalidates a persisted on-disk bytecode cache that running workflow-state processes may be reading or writing during a switch."}, "open_design_questions": {"value": "hit", "evidence": "The issue offers three remedies (resolved store path, hash-checked pycs, activation clear); which one is chosen is open."}, "criteria_shape": {"value": "no", "evidence": "Two acceptance criteria, both verified by deterministic tests in the agent workflow suite."}}, "paths": ["home/common/agent-skills/default.nix", "home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/workflow_delivery.py", "home/common/agent-skills/tests/test_delivery_workflow.py", "home/common/agent-skills/README.md", "justfile"]}`
Verdict: `{"hits":["concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

The agent modules Home Manager installs in `~/.agents/lib/python/` are links
into the Nix store, and every store file has modification time 1. Four of them
are loaded through their link path, so CPython caches their bytecode in the
writable `~/.agents/lib/python/__pycache__/`, named after the link:
`workflow-state` loads the delivery module and the host-admission library that
way, and the delivery module loads its builder and projection helpers as its
own siblings. CPython's default bytecode check compares only the source's
modification time and size. A switch repoints a link at new content but the
time stays 1, so after an edit that keeps the byte size (a constant changed
from 30 to 60) the old compiled code keeps running, silently, until the size
changes or someone clears the cache.

Reproduced on this host while designing (scratch probe, the launcher's
Python 3.13 with `-I`): a module loaded through a link to a time-1 store file
printed 30; after the link was repointed at a same-size time-1 file holding 60
it still printed 30; after the cache directory was moved aside and removed it
printed 60, and a further load rewrote nothing. The live cache today also holds
bytecode from a second interpreter (`cpython-314`) and for modules no longer
installed (`adopt_*`, `agent_platform`), so not every writer is one of the four
loaders.

The maintainer wants bytecode for installed agent modules never to outlive a
change to their source, for every module loaded from that directory, while a
second load of an unchanged module still compiles nothing (#499's guarantee).

## Solution

Every Home Manager activation, after its links are updated, removes
`~/.agents/lib/python/__pycache__` (D1). The removal is a small shell script of
the agent-skills module that takes the library directory as its only argument;
the activation runs that exact file and the test suite runs it too (D2). The
script first renames the cache directory into a fresh private directory inside
the library and then deletes that, so a process writing bytecode at that moment
cannot make the removal fail (D3). If the script fails, the activation prints an
error naming the cache directory and the manual remedy and the switch goes on
(D4). No loader changes: the first load after a switch compiles the new source
and caches it where it always has, and later loads read that cache.

## Decisions

- **The activation step.** One Home Manager activation entry of the
  agent-skills module, ordered after `linkGeneration`, runs the clearing script
  on `$HOME/.agents/lib/python` through the activation's `run` helper, so a dry
  run only prints it. It runs on every activation, whether or not a module
  changed (D1).
- **The clearing script's contract.** Argument: the library directory. With no
  `__pycache__` entry there (or no library), it exits 0 and changes nothing.
  Otherwise it creates a fresh private directory inside the library
  (`mktemp -d` on the template `.pycache-clear.XXXXXX`), moves `__pycache__`
  into it in one rename, removes that directory recursively and exits 0. Library entries other than `__pycache__` are never touched. Any
  failing step exits non-zero with the failing command's own error on stderr;
  nothing is muted (D3). It uses only commands present both on the activation's
  `PATH` and on a test host (`mktemp`, `mv`, `rm`), in forms GNU and BSD share.
- **Failure reporting.** The activation step runs the script as
  `run … || errorEcho …`. The error line follows the script's own stderr and
  says that clearing `~/.agents/lib/python/__pycache__` failed, that while it
  remains an installed agent module may run stale bytecode, and to remove it and
  any `.pycache-clear.*` directory beside it by hand. Once the rename has
  happened the old cache is no longer consulted, so a failed removal leaves only
  that inert directory (D4).
- **What is cleared.** Only the library's top-level cache, with every
  interpreter's and every module name's bytecode in it. That covers every
  module loaded from the library because each installed entry is either a file
  link, whose bytecode lands in that cache, or a whole-directory link
  (`recursive = false`), whose cache would resolve into the read-only store
  (D5).
- **Unchanged loaders.** `_delivery()`, `_host_admission()`, the delivery
  module's sibling loaders, the delivery-model loads and `_artifact_budget()`'s
  resolved-target load (#498 D7) keep their code. The `_artifact_budget()`
  docstring, which calls bytecode beside a link stale-prone, is re-pointed to
  the README section below so it no longer describes the hazard as open; the
  `_delivery()` docstring gains the same pointer (D5).
- **Concurrency residual.** A load that starts compiling a module (cache miss)
  before the links change and writes its bytecode after the clear can leave one
  file compiled from the old source; with a same-size edit that file is stale
  until the next switch clears it. It needs a cold compile spanning the
  interval between `linkGeneration` and this step, and it is documented, not
  closed (D3).
- **Documentation.** The agent-skills README gains one section on the installed
  module library: the store-time hazard, the activation clear (ordering, the
  rename-then-remove shape and why, failure reporting), the layout premise of
  D5, the D3 residual, and that rolling back to a generation older than this
  change runs no clear. It is the one home for this contract; CLAUDE.md is not
  changed.

## Test seams

All tests are added to existing suite members, so the recipe's member list is
unchanged (#499 D6).

1. **Same-size edit after a switch (AC1, AC2 installed).** In
   `test_delivery_workflow.py`, beside the installed-layout harness of
   `test_public_source_and_installed_admission_fail_closed` (prior art), a test
   lays out a stand-in store whose files all have modification time 1 and
   links them under a temporary `HOME` as the harness does. Its `workflow-state`
   children inherit the test's environment without `PYTHONPYCACHEPREFIX` and
   `PYTHONDONTWRITEBYTECODE`, so their bytecode lands where the production
   launcher's `-I` interpreter puts it: the library's own `__pycache__` (an
   inherited prefix would redirect it, and the clear would miss it). Their
   `agent_tools` imports then cache beside the checkout's sources, which git
   ignores, as in a direct `python -m unittest` run. Each run uses a fresh
   repository root. Steps:
   - an `init-run` succeeds and leaves the delivery module's bytecode at the
     path `importlib.util.cache_from_source` derives for its link with
     `sys.pycache_prefix` patched to `None` (#499 D9; the runner sets a prefix
     in the test process itself);
   - the delivery module's link is repointed at a second store file, the
     original with `WORKFLOW_DELIVERY_INTERFACE_VERSION = 1` changed to `= 2`,
     asserted same size, modification time 1 — what a switch does;
   - negative control: an `init-run` still succeeds, so the fixture reproduces
     the stale load (D6);
   - the clearing script, run from the repository by `bash` on the library,
     exits 0;
   - an `init-run` now refuses with exit 2 and
     `workflow-state: delivery runtime: interface` on stderr: the edited code
     ran (AC1);
   - with the library's `__pycache__` now holding the delivery module's
     bytecode again, a further `init-run` leaves every file there with its bytes and modification time unchanged: the cache still works
     after a clear (AC2, installed layout).
2. **The script on its own.** Against a temporary library holding links, a
   regular file and a `__pycache__` with bytecode from two cache tags and a
   nested entry: exit 0, `__pycache__` gone, no leftover private directory, every
   other entry byte- and link-identical. With no `__pycache__`, and with no
   library: exit 0, nothing created. With a library the script cannot write to
   (skipped when the test runs as root, where permissions do not bind): non-zero
   exit, non-empty stderr, the cache still in place.
3. **The wiring.** A text pin on the agent-skills module's Nix file asserts an
   activation entry ordered after `linkGeneration` that runs the clearing
   script's file on `$HOME/.agents/lib/python` with an `errorEcho` fallback,
   following the Nix text pin in `test_delivery_model.py`. It is what turns red
   if the activation stops running the script.
4. **AC2, source layout.** `test_a_second_init_run_compiles_nothing_into_its_bytecode_cache`
   (#499) stays as it is and must stay green; no loader it covers changes.

Verification: `just build` (the darwin configurations are not built in CI) and
`just agent-workflow-tests`. Activation itself is exercised only by a switch,
which this design does not require (CLAUDE.md: switch only when asked).

## Out of scope

- Moving the installed modules into `agent_tools`
  (https://github.com/fagenorn/nix-config/issues/178), and any change to a
  loader or its interface, including returning `_artifact_budget()` to the
  link path to regain production caching for that module.
- The suite runner and its per-run cache contract (the issue-499 paragraph of
  `python/README.md` is unchanged).
- Closing the D3 straddle window, and a rollback to a generation older than
  this change (its activation has no clear).
- Code already loaded into a running process: a process that imported a module
  before a switch keeps the old code until it exits.
- Nested writable caches under the library: none exist (D5).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Remedy: an unconditional activation step after `linkGeneration` removes `~/.agents/lib/python/__pycache__` on every switch; no loader changes | Issue's third remedy and "cover every module loaded from that directory"; host cache also holds `cpython-314` and retired-module bytecode; #499 D5; agent-helpers rule 3 (no new import machinery); scratch probe: clear restores the edited code and the next load caches again | Resolved store path (#498 D7): each store file lives alone, so the delivery module's sibling lookups break, and the read-only store ends production caching (#499 D5). Checked-hash bytecode (loader-written or seeded by `compileall` at activation): import machinery in four loaders against rule 3, or activation tied to the launcher's exact interpreter; misses ad-hoc and other-interpreter loads. A Home Manager `onChange` hook per entry: every future library entry must carry it, to save one recompile per switch |
| D2 | The clearing logic is one shell script of the agent-skills module taking the library directory as its only argument; the activation runs that file and the suite runs the same file | Issue AC1 ("a test added to the agent workflow test suite"); the-bar tests that can fail; the `artifact-budget` wrapper is likewise one file both installed and copied by tests | Inline activation shell: a test could only regex-extract it or evaluate Nix. A Python script: needs an interpreter at activation for a rename and a remove. An `agent_tools` command: it is no agent-workflow command and needs no `PATH` row |
| D3 | The script renames `__pycache__` into a fresh `mktemp -d` directory inside the library, then removes that directory; the straddle residual (a cold compile spanning the relink and the clear can reseed one stale file until the next switch) is documented, not closed | Triage `concurrency_or_persistence`; CPython writes bytecode by path through a temporary file and a rename and skips a write it cannot make, so nothing can add entries to the renamed directory; #499 D2 (reach limits documented, not closed) | Plain `rm -rf`: a writer adding an entry mid-removal fails it with "Directory not empty", a spurious failure on a busy host. Closing the straddle: only checked-hash bytecode written by every writer does that (rejected in D1) |
| D4 | A failed clear is reported by an `errorEcho` line naming the cache, the hazard while it remains and the manual remedy (including a leftover `.pycache-clear.*` directory); the switch continues | Post-`linkGeneration` precedent: `claudeGuardPolicy` and `reportRetiredSkills` report and never abort; the-bar root causes (nothing muted) | Aborting the activation: the links already point at the new sources, so it restores no safety and skips the later steps. `\|\| true`: mutes the failure the issue is about |
| D5 | Clear only the top-level cache, on the premise (stated in the README) that every library entry is a file link or a whole-directory link; all loaders, including `_artifact_budget()`'s resolved load, stay as they are, with docstrings re-pointed | Host layout: five file links and one `recursive = false` directory link whose cache resolves into the read-only store; YAGNI; issue scope excludes loader interfaces | Clearing every nested `__pycache__`: no nested writable cache exists. Returning `_artifact_budget()` to the link path: a production-caching gain the issue does not ask for |
| D6 | AC1 is proved through the production loader in the installed layout (real `init-run`, a relink to a same-size, time-1 variant of the delivery module), with a negative control showing the stale load before the clear and the AC2 check after it; script and wiring get their own seams | Issue AC1/AC2 wording; #499 D6 and D9 (cache contents, `cache_from_source`); the-bar tests that can fail (the negative control proves the fixture reproduces the hazard; the wiring pin turns red if the activation stops running the script) | A synthetic loader child: not the code path production runs. No negative control: a fixture whose swap changed size or time would pass vacuously. A new test module: a recipe edit and one more process (#499 D6) |
