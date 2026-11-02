# Test children reuse cached bytecode; workflow-state imports its delivery module — issue 499

Design for https://github.com/fagenorn/nix-config/issues/499 (parent
https://github.com/fagenorn/nix-config/issues/436). Base: `aabcd693`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#496 Dn", "#436 Dn" and
"#262 Dn" cite those issues' design specs.

## Triage

Input: `{"signals": {"contract_change": {"value": "no", "evidence": "workflow-state's CLI, installed file layout and DeliveryRuntime interface are unchanged; only how workflow_delivery.py is loaded changes"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "parallel suite members share one per-run PYTHONPYCACHEPREFIX directory; CPython writes .pyc files atomically, but concurrent writers into one cache is new"}, "open_design_questions": {"value": "no", "evidence": "the loader follows the existing spec_from_file_location precedent in workflow_delivery.py; the cache prefix location is fixed by the issue"}, "criteria_shape": {"value": "hit", "evidence": "the [evidence] criterion is a post-merge CI timing threshold no deterministic code check verifies"}}, "paths": ["python/agent_tools/suite_runner.py", "home/common/agent-skills/scripts/workflow-state.py", "tests/orchestrate_world.py", "home/common/agent-skills/tests/test_control_cutover.py", "home/common/agent-skills/tests/test_delivery_workflow.py", "tests/test_suite_runner.py"]}`
Verdict: `{"hits":["concurrency_or_persistence","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`just agent-workflow-tests` spends about 1,690 CPU seconds per hosted run: the
summary lines of the last two pushes to `main` read `cpu=1699.3s` and
`cpu=1688.1s`. A large share is Python start-up in the processes the tests
launch, above all `workflow-state`, and those processes cannot reuse compiled
bytecode:

- Six test sites that hand the test's environment to a Python child force
  `PYTHONDONTWRITEBYTECODE=1`: the orchestrate world, the control-cutover base
  generation, the delivery CLI helper, and three in-test children. Such a child
  compiles every module that no earlier process happened to cache, on every
  start.
- `workflow-state` loads its delivery module through `runpy.run_path`, which
  compiles the source and never reads or writes bytecode. Every start that needs
  the delivery runtime recompiles that 77 KB module, even with caching on.
  #262 D1 memoized the runtime within one process; the cost left is per process.
- A script's main file is never cached, so `workflow-state` itself compiles on
  every start whatever this issue does.

Measured on this host while designing (Python 3.13, scratch probe, median CPU
of `workflow-state init-run` in a fresh root): 467 ms with no bytecode written;
183 ms with a warm cache and today's loader; 159 ms with a warm cache and the
delivery module imported. With today's loader a warm cache holds bytecode for
the delivery module's builder and projection helpers but none for the module
itself.

The maintainer wants the suite's children to write and reuse bytecode in one
cache per run, the delivery module imported, a suite test that proves a second
invocation compiles nothing, and the suite's CPU on the hosted runner to fall
by at least 150 s.

## Solution

`agent_tools.suite_runner` creates one temporary directory per run and launches
every member with `PYTHONPYCACHEPREFIX` naming it and `PYTHONDONTWRITEBYTECODE`
removed. Every Python process that inherits a member's environment, at any
depth, then writes its bytecode into that directory, mirrored by source path,
and reads what an earlier process of the same run wrote instead of compiling
again. The runner removes the directory when the run ends. The test harnesses
that spread the test's environment into a child stop forcing
`PYTHONDONTWRITEBYTECODE=1`, so the runner's setting reaches those children.
`workflow-state` loads its delivery module through the import system, as it
already loads the host-admission library and as the delivery module loads its
own three dependencies, so that module's bytecode is cached like any import's.
Runner tests and one `workflow-state` test prove it, and the runner's README
contract states the cache, its reach and its limits.

## Decisions

**The per-run cache.** `run_suite` creates the cache directory in the default
temporary location, named with a `suite-runner-pycache-` prefix, before the
first member launches, and removes it however `run_suite` ends: after the
report, after an interrupted run has waited for its members, or on an error. A
removal error propagates rather than being ignored (D1). Each run, including
two concurrent runs on one host, owns its own directory. The members'
environment stays one importable pure function computed once per run:
`member_environment` takes the
cache directory as a second argument and, beside the git entries of #496 D2,
sets `PYTHONPYCACHEPREFIX` to that directory, replacing an inherited value, and
drops an inherited `PYTHONDONTWRITEBYTECODE`. Every other variable passes
unchanged, and the parent mapping is not modified (D1). Both launch sites keep
receiving the one mapping; `main`, `--jobs` and the CLI do not change.

**Sharing.** Every member of a run, and every descendant that inherits its
environment, shares the one directory. Parallel writers need nothing from the
runner: CPython creates missing cache directories while tolerating a concurrent
creator, writes each bytecode file under a temporary name and renames it into
place, so a reader sees a whole old or new file, and an unwritable cache only
skips the write. A prefix redirects every cache lookup, the standard library's
included, so the run's first process compiles the standard-library modules it
imports into the directory once (69 files for one `init-run` in the probe), and
later processes read them. Every run pays that once, the runner tests' inner
runs included: about 0.1 s of CPU for an inner run of two trivial unittest
members in a probe on this host.

**Reach and limits.** The cache reaches every process that inherits a member's
environment. It does not reach a child started with an environment built from
scratch, nor one run with `-I` or `-E`, which ignores both variables and keeps
today's behaviour, and a descendant still running after the run ends may
recreate part of the removed tree. CPython validates timestamp bytecode by its
source's modification second and size, so a test that rewrites an importable
source in place to the same size within one second and then imports it in a
new process can be served the earlier compile. Such a test gives that process
its own cache directory, which is the README's existing rule for shared state.
The one test found rewriting an importable source in place while designing,
the source-and-installed admission test, changes the size on every rewrite;
other tests that write Python sources write each into a fresh directory.
Outside the runner, as in a direct `python -m unittest` run, the edited
harnesses' children write bytecode beside
their sources, as the test process itself already does; the checkout ignores
`__pycache__/`. These limits are stated in the README contract, not closed (D2).

**Test harnesses.** Every test site that builds a child's environment by
spreading the test process's environment stops setting
`PYTHONDONTWRITEBYTECODE`: the orchestrate world; the control-cutover base
generation; the delivery CLI helper; the delivery workflow's contractless-output,
admission-layout and git-failure-probe children; and the delivered-control
isolated tree. The eval-case acceptance child keeps the setting. It is given
only `PATH`, so it never sees the runner's cache, and it runs inside the tracked
fixture tree, where writing would leave `__pycache__` beside the sources (D3).

**The delivery loader.** `_delivery()` builds a spec from the delivery module's
file location under the name `_workflow_delivery`, creates the module from that
spec and executes it through the spec's loader, the shape `_host_admission()`
uses, in both layouts. It registers nothing in `sys.modules`: nothing looks the
module up by name, and `runpy` left nothing registered either. Everything else
stays as it is: the entry path per layout (the `scripts` sibling in the source
layout, `~/.agents/lib/python/workflow_delivery.py` installed); a fresh module
for each load, as `runpy` gave; the interface check, now an attribute read that
must find `WORKFLOW_DELIVERY_INTERFACE_VERSION` equal to 1; the per-notes-limit
runtime cache; a failed load is not kept; and every failure, a spec that cannot
be made included, is raised as `WorkflowError("delivery runtime: …")`. The
script no longer imports `runpy` (D4).

**Installed layout.** Installed, the delivery module's bytecode is written into
`~/.agents/lib/python/__pycache__`, beside the bytecode that its builder and
projection dependencies and the host-admission and artifact-budget libraries
already write there. Store files carry a fixed modification time, so for these
modules only the size tells a stale cache file from a current one, and a
same-size edit could run stale bytecode after a switch until the size changes.
The hazard predates this issue for those modules; this issue adds the delivery
module to it and does not close it (D5).

**The README contract.** The runner paragraph's account of the members'
environment gains the cache: a per-run directory in `PYTHONPYCACHEPREFIX`,
`PYTHONDONTWRITEBYTECODE` removed, the directory removed when the run ends, and
the reach and same-size limits of D2.

## Test seams

The seams follow #496 D4 and #436 D9. Runner cases live in the existing runner
test module and drive `python -m agent_tools.suite_runner` end to end over
fixture members, or call `member_environment` directly. The `workflow-state`
case lives in the existing delivery-workflow test module and drives the CLI
from source. No suite member is added and the recipe does not change (D6).

These modules themselves run under the suite runner, so the test process
already carries the outer run's cache. Every environment a seam hands to an
inner runner therefore carries a sentinel `PYTHONPYCACHEPREFIX` of the test's
own and `PYTHONDONTWRITEBYTECODE=1`, and the `workflow-state` seam sets its own
fresh cache directory and removes `PYTHONDONTWRITEBYTECODE`, so no assertion
can pass on the outer run's cache.

1. **The composition, called directly.** Given a parent that carries a
   `GIT_CONFIG_PARAMETERS` value, a foreign `PYTHONPYCACHEPREFIX` and
   `PYTHONDONTWRITEBYTECODE=1`, the result names the given directory in
   `PYTHONPYCACHEPREFIX`, has no `PYTHONDONTWRITEBYTECODE`, keeps #496's git
   composition and every other variable, and leaves the parent unchanged. The
   existing case that only `GIT_CONFIG_PARAMETERS` changes widens to the three
   variables.
2. **Members share one per-run cache, at both launch sites.** Two fixture
   members run through the runner under the sentinel environment, once with
   `--jobs 1` and once with `--jobs 2`. From inside its run, each member records
   the cache directory it sees, whether its own module's bytecode exists at the
   path CPython derives for it there, whether bytecode writing is enabled, and
   whether a `__pycache__` directory exists beside its source. Each run exits 0;
   both members name the same cache directory, which is not the sentinel; each
   found its own bytecode there with writing enabled and no `__pycache__` beside
   it; and after the run the directory no longer exists. A runner that passes
   the inherited prefix through, keeps `PYTHONDONTWRITEBYTECODE`, gives members
   different directories, sets the cache at one launch site only, or leaves the
   directory behind fails a case. Against today's runner a probe of these
   members recorded the sentinel with writing off, so the case fails before the
   change.
3. **A second `workflow-state` invocation compiles nothing (AC1).** The test
   runs the source-layout `workflow-state init-run` twice, each in its own fresh
   repository root, under one fresh, empty cache directory with writing
   enabled, and both runs exit 0. After the first, the cache holds the delivery
   module's own bytecode at its source's mirrored path; with today's `runpy`
   loader it holds the builder's and projection's bytecode but not this file,
   as verified while designing. After the second, the cache's file set and
   every file's bytes and modification time are unchanged, since a module the
   import system loaded without a valid cache file would have been compiled and
   written. The main script, which no loader caches, lies outside this check,
   as the issue states.

No assertion depends on timing: the issue's demo, `workflow-state --help` timed
twice, is shown in the verification record, not asserted. Neither
`-X importtime` nor `python -v` is a seam. The first reports import time, which
does not tell a compile from a cache hit; the second's messages are diagnostic
text with no contract.

The harness edits carry no test of their own. Seam 2 proves the runner's
environment enables the cache for whatever inherits it, the full suite proves
every edited harness still passes, and the plan's acceptance checks that,
beside the runner tests' sentinel, the eval-case child is the only test child
still given `PYTHONDONTWRITEBYTECODE`.

**Acceptance.** AC1 [code] is seams 1 to 3 passing under
`just agent-workflow-tests` with the whole suite green (`failed=0`): seam 2
shows the suite hands its children one shared, writable cache, and seam 3 that
under such a cache a second `workflow-state` invocation compiles nothing. AC2
[evidence] is read after merge by the protocol of D7: the `cpu=` figure of the
`suite-runner: summary` line in the "Agent Workflow Tests (advisory)" job of
two push-triggered `ci.yaml` runs on `main`, the merge commit's and the last one
before it. Both must show `failed=0`, `jobs=4` and the same member count. The
criterion is met when the earlier run's `cpu=` minus the merge run's is at least
150.0 s, and the record quotes both summary lines with their run links. A merge
run that does not qualify is read from its re-run; a baseline that does not
qualify is replaced by the latest earlier push run that does, and the record
says why. The figure does not exist at ship, so the issue is held for
verification until the merge run is read; a miss is recorded with both figures
and leaves the issue open. The pull request's advisory run and a local run may
be quoted for information only.

## Out of scope

- **The main script's compile.** `workflow-state` itself, and every script run
  as a main file, still compiles on each start; a thin launcher that imports it
  is not asked for.
- **In-process `runpy` in tests.** The delivery and delivery-model test modules
  execute the delivery module through `runpy` inside their own process, once per
  class, which is not a child start.
- **The control-cutover base generation's loader.** The base helper is a pinned
  historical tree and keeps its `runpy` load; it gains only the cache for its
  imports.
- **Moving the delivery module into `agent_tools`** (agent-helpers rule 3's
  cluster move), and any change to the installed file layout or the
  home-manager wiring.
- **The installed-library stale-bytecode hazard** (D5). A follow-up that keys
  the installed library's bytecode to each store generation, for example by
  compiling it into the store at build time, is recommended to the issue owner
  for filing; it is not filed here.
- **The justfile recipe, the CI workflow and the Nix configuration.** The runner
  keeps `--jobs` as its only option, with no switch to turn the cache off
  (#436 D4).
- **Other `runpy` users** outside `workflow-state`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The runner owns one cache per run: `run_suite` creates a temporary directory before the first launch and removes it however it ends (report, interrupt or error), letting a removal error propagate; `member_environment(parent, cache)` sets `PYTHONPYCACHEPREFIX` to it, replacing an inherited value, and drops an inherited `PYTHONDONTWRITEBYTECODE`. | Issue ("points `PYTHONPYCACHEPREFIX` at a per-run temp directory"; children "write and reuse"); #496 D1 (one pure function, computed once, both launch sites); the-bar root causes (no muted error); CPython's cache writer tolerates concurrent directory creators and renames each file into place. | Setting it on the recipe line (a direct runner invocation misses it, nothing removes the directory, and the wiring test pins the line); keeping an inherited prefix (runs then share a cache, and no test can tell the runner set anything); keeping an inherited `PYTHONDONTWRITEBYTECODE` (a caller's shell silently turns the cache off); `ignore_cleanup_errors` (mutes a failure). |
| D2 | The cache reaches the members' inherited environment only. From-scratch environments, `-I` and `-E` children, a descendant outliving the run, and CPython's second-and-size validation are documented in the README contract, not closed; a test that rewrites an importable source in place to the same size within one second gives its child its own cache. | #496 D3 (reach limits documented, not closed); the README's rule that a test sharing state gets its own temporary location; the one in-place rewriter of an importable source found while designing changes size on every rewrite; CPython validates timestamp bytecode by whole-second modification time and size. | Hash-based bytecode (import writes timestamp bytecode, and switching needs compile-time tooling the suite does not run); one cache per member (forfeits the cross-member reuse the issue asks for). |
| D3 | The six sites that hand the test's environment to a Python child, plus the git-failure probe that spreads it into `git`, drop `PYTHONDONTWRITEBYTECODE`; the eval-case acceptance child, given only `PATH` and run inside the tracked fixture tree, keeps it. | Issue AC1 says "suite child processes", wider than the three harnesses its text names; the eval child never receives the runner's cache, so dropping its setting would write `__pycache__` into a tracked tree. | Only the three named harnesses (leaves three inheriting Python children compiling on every start); dropping the eval child's setting too (litter in a tracked tree for no speed); keeping it on the git probe (no Python runs there, so the variable misleads). |
| D4 | `_delivery()` loads the delivery module by a spec from its file location as `_workflow_delivery` and executes it through the spec's loader in both layouts, registering nothing in `sys.modules`; the entry paths, interface check, per-limit cache, failure-not-kept rule and `delivery runtime:` error prefix are unchanged. | Issue; `_host_admission()` and the delivery module's own three loaders (precedent); agent-helpers rule 3 binds a legacy flat script when its cluster moves, and `runpy.run_path` already loads by path; probe: 183 → 159 ms CPU per `init-run` with a warm cache. Revisits #262 D1's rejected alternative ("less gain"): memoization cannot reach the per-process cost this issue targets. | Moving the module into `agent_tools` (rule 3's cluster move, which changes the installed layout); putting its directory on `sys.path` and importing by name (rule 3 bans `sys.path` edits); importing in the source layout only (two loaders, and installed starts keep recompiling); registering it in `sys.modules` (no consumer, and `runpy` left nothing registered). |
| D5 | Installed, the delivery module's bytecode joins its dependencies' in `~/.agents/lib/python/__pycache__`, where the store's fixed modification time leaves size as the only staleness check; the hazard predates this issue, is recorded here and is recommended as a follow-up, not closed. | Host observation: store files stat at modification time 1, and that cache directory already holds the builder's, projection's, host-admission and artifact-budget bytecode; the issue's scope is the suite's children. | Loading from the resolved store path (the read-only store takes no cache file, which silently ends production caching for the three dependencies too, a behaviour change the issue does not ask for); keeping `runpy` for the installed layout (D4). |
| D6 | AC1 is proved by a `workflow-state` seam (two `init-run`s in fresh roots under a test-owned empty cache: the delivery module's own bytecode present after the first, the cache byte- and mtime-identical after the second) and by runner seams (the pure composition; two members in each launch mode share one existing cache directory that is not the inherited sentinel and hold their own bytecode there, and the directory is gone after the run). Inner environments carry a sentinel prefix and `PYTHONDONTWRITEBYTECODE=1`; no assertion is timed; no suite member is added. | Issue AC1 ("using the cache directory's contents"); the-bar tests that can fail (probes while designing: the presence check fails on today's loader, and today's runner hands members the sentinel with writing off); #496 D4 (strip the outer runner's setting, one case per launch site). | `-X importtime` (import time does not tell a compile from a cache hit); `python -v` messages (diagnostic text with no contract); timing the demo (host load decides it); a new test module (a recipe edit and one more process for three cases). |
| D7 | AC2 is read after merge from the `suite-runner: summary` `cpu=` of the "Agent Workflow Tests (advisory)" job in two push-triggered `ci.yaml` runs on `main`, the merge commit's and the last before it, both with `failed=0`, `jobs=4` and the same member count. It is met when the earlier run's figure minus the merge run's is at least 150.0 s; a non-qualifying merge run is read from its re-run and a non-qualifying baseline gives way to the latest earlier qualifying push run; it is pending at ship, so the issue is held for verification, and a miss leaves it open with both figures. | Issue AC2 ("Suite CPU work drops", "summed module seconds"); the runner contract (`cpu=` sums the members' CPU); the last two push runs read 1699.3 s and 1688.1 s, 11.2 s apart; #448's hold for a pending `[evidence]` row. | Summing the rows' wall times (contention moves wall time, not work); the pull request's run (not the run the criterion names); closing at merge (the evidence does not exist yet). |
