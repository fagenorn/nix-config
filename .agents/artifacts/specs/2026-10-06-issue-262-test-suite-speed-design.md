# Issue 262 — halve `agent-workflow-tests` wall time without dropping coverage

## Problem

`just agent-workflow-tests` runs 68 modules serially in one `unittest`
process and takes 8–10 minutes on the 10-core mbp. Every implementer task,
the final gates and ship run it again, so it is the dominant fixed cost of an
issue run. Running the modules ten-wide was slower than serial, because the
machine saturates. The run has to get at least twice as fast serially. The
tests it runs and their assertions must not change.

## Measured profile (base `31be729`, relative only)

**Load caveat.** Other agent runs shared the machine. The load average was
10–25 during most module timings and 50–100 near the end, against 10 cores.
Absolute seconds are therefore inflated and noisy, sometimes by more than
2× between back-to-back runs. The evidence below rests on things that load
does not move: **process-spawn counts**, taken with an audit hook on
`subprocess.Popen` in the test process; **cProfile attribution** inside one
process; and **paired A/B runs** of one fixed test sample. Seconds come
paired with the load average at the time.

Per-module serial wall time, `python3 -m unittest <module>`, one module at a
time (load average in brackets):

| Module | Tests | Wall s | Spawns in test process |
|---|---|---|---|
| `test_workflow_state` | 187 | 333 [21] | 1558, of which 1402 are `python3 workflow-state.py` |
| `test_review_feasibility` | 39 | 486 [23] | ~35 per test; each `project` child spawns ~300 `git` |
| `test_delivery_workflow` | 70 | 123 [9] | workflow-state CLI subprocesses |
| `test_adopt_apply` | 45 | 73 [99] | — |
| `test_host_admission` | 28 | 45 [16] | 242, of which 228 are `python3` |
| `test_adopt_project` | 62 | 38 [46] | — |
| `test_review_package` | 36 | 37 [10] | — |
| `test_delivered_control` / `test_admission_replay` | 5 / 4 | 31 / 28 [9–14] | workflow-state CLI |
| the other 45 tail modules (contracts → branch protection) | — | 373 total, each < 25 [25–100] | — |

The review modules that use the issue-121 and issue-100 fixtures —
`test_review_projection_cases`, `issue121`, `compact121`, `issue100`,
`derivation`, `replay` and `witness` — could not be timed whole inside the
profiling window: `test_review_projection_cases` alone ran past 7 minutes at load ~100 before the run was stopped. A single `test_review_issue121` test,
`AncestryTest.test_clean_payload_validates_over_one_history`, took 38–67 s
and launched **3,794 subprocesses**, all but about 40 of them `git`.

### Hotspots and evidence

**H1 — the workflow-state CLI reloads its delivery runtime on every call.**
`_delivery()` in `workflow-state.py` runs `runpy.run_path` on
`workflow_delivery.py`. That recompiles the file from source, because
`run_path` keeps no bytecode cache. The constructor it calls then re-executes
the `delivery_model` package and the builder and projection modules. In a
cProfile of 40 lifecycle tests run in process, `_delivery()` ran **2,037
times across 235 CLI invocations**, about 9 per invocation. `compile` alone
took 19.2 s of the 42 s spent in the CLI. The runtime that `_delivery()`
builds sets its fields only in `__init__`, so reusing it within one process
is safe.

**H2 — the review Git authority spends most of its spawns re-authenticating.**
`review_git._closure` runs `_guard` before and after its object walk. Each
`_guard` launches six `git` processes: two `rev-parse` calls that could be
one, `rev-parse --is-shallow-repository`, `for-each-ref` once for each
replace namespace, `config --list` and `rev-parse --show-object-format`. With
`cat-file --batch` and `rev-list` added, every closure costs **14 spawns**.

In the issue-121 test above, the 268 closures made 536 guard calls, which
took 43 s of the 60 s spent in `subprocess`. That is about 76% of all spawns.
Callers also open several closures inside one operation:

- `review_forecast.edge_facts` runs `original_edge`, which opens one closure,
  then `history_commit` on the parent and again on the child, opening a
  closure each. That is three closures where one already holds both commits.
  The 40 edges in that test therefore took 120 closures.
- Paired lookups such as `(original_commit(repo, oid).tree for oid in (base,
  head))`, in `review_actual`, `review_issue100` and `review_issue121`, open
  two closures for one question.

Each `git` spawn costs 15–25 ms under this load, and an empty `true` costs as
much, so spawn count is the cost. A prototype that merged the guard's queries
cut that test's spawns from 3,794 to 2,722, a 28% drop. A cProfile of one
`review-feasibility project` child shows the same mix: 23 closures and about
300 spawns, which took 3.6 s of its 4.0 s.

**H3 — the lifecycle harness launches a fresh interpreter per CLI call.**
`LifecycleHarness.run_cli` in `test_workflow_state` launches
`python3 workflow-state.py`, about 0.1 s each even when idle. Bare
interpreter start-up is 0.02 s, and the 4,564-line script is recompiled on
every launch, which takes 25 ms.

A paired A/B run used the same 40 `WorkflowStateLifecycleTest` tests, all of
them passing in every mode. The load average was 50–95 and the order was
consecutive:

| Mode | Wall s |
|---|---|
| subprocess, base | 99.2 |
| subprocess, H1 memo | 51.3 |
| in-process, base | 67.0 |
| in-process, H1 memo | 24.0 |

**H4 — per-test rebuilds of derived fixtures.** `test_review_issue121`
`AncestryTest.setUp` builds a signed fixture repository, a Task-7 table and a
budget authority for every one of its 9 tests. It then runs
`classify` and `contribution_edges`, 11.7 s of the 67 s test. `Issue100Test`
(22 tests) and `Task7ModelTest` (22 tests) rebuild their repositories in
`setUp` too. Most other review classes already share their fixtures through
`setUpClass` or a cache, so H4 is secondary to H2.

**Not hotspots.** Building a fixture repository costs at most about 0.3 s per
test in `test_review_feasibility`. The transaction, contract and model suites
take under 2 s each.

## Solution

Fix the two root causes in production code first. Then remove the per-call
interpreter launch from the one harness that dominates. Share derived
fixtures per class only where a module still exceeds the gate. Every change
preserves behavior, and none of them adds a cache that spans what the review
authority treats as one API call.

1. **H1: one delivery runtime per process.** Loading the runtime once per
   process follows the existing `_HOST_ADMISSION` "loaded once" precedent.
   It is keyed by the notes limit that `phase_notes_maximum()` reads on each
   call, so the policy is still read on every call (per D1).
2. **H2: a cheaper guard and one closure per operation.** The guard runs the
   same checks, in the same order and with the same error codes, from three
   `git` processes instead of six (per D2). An operation that asks several
   questions about one set of commits answers them from a single
   authenticated closure, opened at its entry point (per D3).
3. **H3: an in-process lifecycle runner.** `LifecycleHarness.run_cli` and
   `run_control_at_root` in `test_workflow_state` run the CLI's
   `main` in the test process. They return the same
   `subprocess.CompletedProcess` shape, so no test body changes (per D4).
   Every other workflow-state subprocess site in the suite keeps launching a
   real process, and that is the launcher coverage that remains.
4. **H4: class-level templates, gated.** H4 applies only to a module that
   still exceeds 90 s after H1–H3. That class builds its fixture once in
   `setUpClass`, and each test gets its own `copytree` of the repository
   plus deep copies of the derived values (per D5).

## Decisions

### H1: delivery runtime memo

- `_delivery()` returns a process-lifetime `DeliveryRuntime`, held in a
  module-level dict keyed by `phase_notes_maximum()`. A load failure is not
  cached: it raises the same `WorkflowError` text it raises today, and the
  next call retries the load.
- No change to `workflow_delivery.py`'s loaders, to interface-version checks
  or to the installed layout.

### H2: review Git authority

- **Guard.** Four queries collapse into one `git rev-parse
  --path-format=absolute --git-dir --git-common-dir --is-shallow-repository
  --show-object-format`. Both replace namespaces collapse into one
  `for-each-ref` that takes both patterns. `config --null --list` stays as
  it is. The results are then checked in today's order — routing environment,
  graft and shallow files, the shallow flag, replace refs, promisor
  configuration, object format — so each code still wins in the case it wins
  today. Both guards still run on every closure.
- **One closure per operation.** `original_edge` returns the parent and child
  `OriginalCommit` from the closure it already authenticates, and
  `edge_facts` takes both trees from that return. A new
  `original_commits(repo, oids)` returns several authenticated commits from
  one closure, and the paired base/head lookups switch to it. The plan makes
  a census of the remaining call sites and converts a site only when it
  repeats lookups within one function call over commits it already holds.
- **No cross-call cache.** The comment "every API boundary observes current
  metadata and objects" stays true. A later entry-point call still runs both
  guards, re-reads every object and re-runs the `rev-list` comparison.

### H3: in-process runner

- **Where the runner lives.** It is a function in a new support module under
  the agent-skills tests directory, next to `_delivery_model_fixtures.py`. It
  compiles the script once per test process. Each call executes that code in
  a fresh module namespace under `__name__ == "__main__"`, so the script's
  globals, including the H1 memo and `_HOST_ADMISSION`, never outlive one
  call, exactly as a process boundary would.
- **What each call patches.** For the duration of the call, the runner
  patches `os.environ` to the call's `env` with `clear=True`, sets
  `sys.argv`, and replaces `sys.stdin`, `sys.stdout` and `sys.stderr` with
  UTF-8 `TextIOWrapper`s over `BytesIO`, so `.buffer` writes work.
- **What it returns.** A `CompletedProcess` carrying the text or bytes the
  caller asked for. `SystemExit` maps to its code. An uncaught exception maps
  to exit 1, with the traceback written to stderr, as the interpreter does.
- **What stays a subprocess.** Every `Popen` concurrency or race case, every
  call that passes `cwd`, `timeout` or kill, and every workflow-state call
  outside these two harness methods.

### H4: fixture templates

- A class takes a template only when every one of its tests treats the
  shared values as input. The template is the repository directory plus the
  pins, table, authority and edges.
- The repository is copied per test with `shutil.copytree(symlinks=True)`, so
  objects, SHAs and the signing key are identical. Values reach each test
  through `copy.deepcopy`, which makes a test's mutation invisible to every
  other test.
- `RouteTest`, whose tests build different fixture shapes, keeps its
  per-test builds.

### Coverage preservation

The proof has two parts, both run at ship time and recorded in the PR.

- **Test IDs.** The sorted list of IDs that `unittest` collects from the
  recipe's module list is identical at base and head, and the recipe's
  `Ran N tests` line matches. No exact duplicate is removed (per D7).
- **Test bodies.** Every `test_*` method body is AST-equal at base and head.
  Differences may appear only in support modules, `setUp`/`setUpClass`
  methods and the harness methods named above. Every such difference is
  listed in the PR.

### Measurement for acceptance

These measurements are taken on mbp, at base and at head, back-to-back, on an
idle machine, with load average under 2 recorded before each run (per D6):

1. `time just agent-workflow-tests`, once at base and once at head.
2. A serial per-module loop, one `unittest` process per module over the
   recipe's own list, giving wall seconds and test count per module. Head
   must keep every module at or under 90 s.

Spawn counts per module, from the same audit hook, go beside the timings as
the load-independent proxy. The profile lives in the PR description and is
not committed, because it is a point-in-time record.

## Test seams

- **The existing suite is the seam.** The 68 modules in the recipe, run by
  `just agent-workflow-tests`, are the acceptance surface. No new test is
  added: a new one would change the count that acceptance criterion 2 holds
  fixed.
- **H2 behavior** is held by the existing adversarial review-history tests:
  graft, replace-ref, alternate replace base, shallow, routing variables,
  graft file and rehashed edges. Examples are `test_review_issue121`
  `test_virtualized_history_is_invalid_at_both_entry_points` and
  `test_review_history`. They must pass unchanged.
- **H1 behavior** is held by the lifecycle and delivery suites. The
  remaining workflow-state subprocess sites in `test_delivery_workflow`,
  `test_host_admission`, `test_admission_replay` and `test_delivered_control`
  run the memo across a real process boundary.
- **H3 fidelity** is held by the unchanged assertions on stdout, stderr and
  return code in `test_workflow_state`. A run of the whole module must stay
  green in both runner modes before the switch.

## Risks

- **`test_review_feasibility` may still exceed 90 s.** Its cost sits inside
  the `review-feasibility project` child process, which neither H3 nor H4
  reaches. The 90 s gate for it rests on D2 and D3 alone. If it still exceeds
  90 s, the plan extends the D3 census through `review_forecast._ownership`,
  where `full_commit` and `history_commit` run on one checkpoint and
  `ancestor` and `commit_range` run on one pair. Should that still fall
  short, the owner reports the gap. No test is weakened to meet it.
- **Error-code precedence under D3.** Once the closure behind `original_edge`
  is authenticated, the per-commit lookups that came after it could not fail
  differently on an unchanged repository. Folding them into that closure
  therefore changes no outcome that a test can produce deterministically.
  Only the interleaving with a concurrent writer changes, and every
  entry-point call still brackets its own walk with guards.
- **In-process fidelity.** If an in-process call leaked a file lock, the
  calls after it would block rather than pass silently. The script takes its
  `fcntl` locks in `with` blocks. A whole-module run of
  `test_workflow_state` must stay green in both modes before the switch.

## Out of scope

- Deleting, skipping, merging or weakening any test. There are no exact
  duplicates to remove.
- Parallel or sharded execution of the suite, and any host-load scheduling,
  which `.agents/knowledge/rejections/host-contention-scheduling.md` keeps
  out.
- Caching review history across entry-point calls, and reimplementing Git
  queries without `git`.
- Moving the workflow-state CLI's `artifact-budget validate-report`
  subprocess in process. That subprocess is the product's external-helper
  boundary.
- Migrating `workflow-state.py` into `agent_tools`, and changing any other
  recipe, the CI workflow or the installed launchers.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Memoize `_delivery()`'s `DeliveryRuntime` per process, keyed by the notes limit read on each call; failures are not cached. | H1: 2,037 loads in 235 calls, 19.2 s of 42 s compiling; the 40-test sample drops from 99.2 s to 51.3 s; `_HOST_ADMISSION` "loaded once (D18)" precedent; the runtime sets state only in `__init__`; the bar's Root causes rule. | Cache the bytecode via `importlib` for `workflow_delivery.py`: it changes the loader and the installed layout for less gain. |
| D2 | Collapse `_guard` from 6 to 3 `git` spawns, with the same checks in the same order, and keep both guards on every closure. | H2: guards are ~76% of the spawns; prototype cuts 3,794 spawns to 2,722; the `review_git` comment that every boundary observes current metadata; #233 D4. | Drop the post-walk guard, or read refs and config without `git`: that weakens the authentication or reimplements Git. |
| D3 | One authenticated closure per operation: `original_edge` returns both commits, and `original_commits` serves paired lookups. There is no cache across entry-point calls. | H2: `edge_facts` costs 3 closures per edge (120 of 268 in the sample); #233 D4, which authenticates once at the shared boundary and reuses that authority across ranges and edges. | A process-wide verified-object cache: it breaks "observes current ... objects" and saves only the one `cat-file` spawn per closure. |
| D4 | Run `LifecycleHarness.run_cli` and `run_control_at_root` in process, through a compile-once, fresh-namespace runner; every other workflow-state subprocess site stays a real process. | H3: the sample drops from 51.3 s to 24.0 s on top of D1; the script mutates no process-global state beyond stdio; the issue allows in-process calls where the module is the subject and asks to keep the existing launcher coverage. | A fork server: fork without exec is unsafe on macOS, which is why the stack shard notes that macOS spawns. Converting every workflow-state site: a larger diff, and it would remove the launcher coverage. |
| D5 | H4 class templates (per-test `copytree` plus `deepcopy`) only for a module still above 90 s after D1–D4, chosen by the plan from that measurement. | H4 is secondary to H2; the issue allows per-class caching only with immutability guards; YAGNI. | Share one mutable fixture per class: tests such as the virtualization attacks mutate the repository. |
| D6 | Accept on idle-machine back-to-back wall time; carry spawn counts and paired A/B samples as load-independent evidence; the profile goes in the PR, not into a committed tool or recipe. | Issue acceptance criteria 1–3; load reached 100 on 10 cores during profiling; the bar's Verify before claiming done rule; the issue keeps other recipes' semantics fixed. | A committed profiling recipe or script: new surface that nothing else needs. |
| D7 | Prove coverage by identical collected test IDs and AST-equal `test_*` bodies, and remove no duplicates. | Issue decision that no test is deleted or weakened; the bar's Tests that can fail rule. | Remove suspected duplicates: each needs verification and a PR listing, and profiling found no duplicate among the hotspots. |
| D8 | Add no parallel or sharded execution. | The issue measured ten-wide as slower; the spawn-bound profile means parallel runs contend for the same process-creation cost; the host-contention rejection. | Bounded two-wide sharding: profiling shows no win, and it reintroduces the load sensitivity. |
| D9 | D3's census converts a site that repeats single-commit lookups over commits it already holds within one function call: the paired and looped `original_commit`/`history_commit` sites in `review_actual`, `review_issue100`, `review_issue121`, `review_forecast._ownership` and `review_projection.reconstruct_owned`. A site whose own shape check precedes `edge_facts` (`contribution_edges`) prefetches its commits instead of reusing the edge's return, so its error precedence holds. `ancestor`/`commit_range` combinations and `_prerequisite`'s deliberate re-run of `_ownership` stay as they are. | D3's census rule; the `_prerequisite` comment "Evidence can outlive a plan load"; the spec's Risks, which have the owner report a `test_review_feasibility` shortfall rather than widen scope. | A combined ancestor-and-range API: a new interface for a gain nobody measured. |
| D10 | The in-process runner reaches every class that inherits `LifecycleHarness`, including those in `test_host_admission` and `test_launch_commit`. `test_workflow_state` loads the runner by file path, because `test_launch_commit` loads `test_workflow_state` by path, where a relative import cannot resolve. | D4 names the harness methods, not one module; the `load_source_module` precedent in `test_workflow_state`; the modules that inherit the harness still have their own real-process workflow-state and launcher sites. | Override `run_cli` back to a subprocess in the modules that inherit it: a second harness path that adds no coverage. |
| D11 | D5's gate is decided on Task 6's serial measurement taken at whatever load the machine has: a candidate module above 90 s gets the template even when the load is high, because load only inflates times and over-applying a behavior-preserving template is the safe direction. The template copies the whole per-class fixture directory. A class keeps its per-test build when any derived value holds an absolute path inside that directory. | D5; D6 puts the idle measurement at ship time, after every code change; the load reached 100 during profiling. | Wait for an idle machine before deciding: the plan cannot schedule one, and under-applying fails the 90 s gate at ship. |
