# Issue 500: the builder CLI helper in-process, heavy fixtures once per class

Design for https://github.com/fagenorn/nix-config/issues/500 (parent
https://github.com/fagenorn/nix-config/issues/436). Base: `0a25b807`
(`origin/main`). A bare "Dn" cites this spec's ledger. "262 Dn" cites the ledger of
`2026-10-06-issue-262-test-suite-speed-design.md`, and "498 Dn" cites the ledger of
`2026-11-01-issue-498-inprocess-artifact-budget-design.md`.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "Test-only change: the in-process CLI runner is a private test helper and no product CLI, schema or public interface changes."}, "concurrency_or_persistence": {"value": "doubt", "evidence": "Per-class fixtures share on-disk ledger/git state that must be copied per test so no test observes another's mutations; in-process cwd changes are process-global."}, "open_design_questions": {"value": "doubt", "evidence": "How to deep-copy on-disk fixture state (paths embedded in ledgers) and how the in-process runner honours stdin bytes and cwd are open."}, "criteria_shape": {"value": "hit", "evidence": "The evidence criterion is CI timing on the merge commit's push to main, which no deterministic code check verifies before merge."}}, "paths": ["home/common/agent-skills/tests/_inprocess_cli.py", "home/common/agent-skills/tests/test_delivery_workflow.py", "home/common/agent-skills/tests/test_attempt_migration.py", "tests/orchestrate_world.py", "tests/test_orchestrate_control.py", "home/common/agent-skills/tests/test_workflow_state.py"]}

Verdict: {"hits":["concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}

ran: full (shadow)

## Problem

Three modules take 419.7 s of the agent workflow suite's CI time between them
(run 41314186007: `test_delivery_workflow` 196.9 s, `test_orchestrate_control`
113.2 s, `test_attempt_migration` 109.6 s). Every ship and every local
verification pays that cost again. Most of it goes to work that is repeated, not
to the behaviour under test:

- **The builder harness starts a Python child for every workflow-state call.**
  `BuilderHarness.cli` launches `python workflow-state.py` per call. The lifecycle
  harness has run the same script in-process since issue 262. This helper could not,
  because the in-process runner has no stdin, no working directory and no bytes
  mode.
- **The attempt-migration fixture re-runs a whole delivery per test.** Ten tests
  each drive the issue-207 delivery to its remainder (43 child processes, 6–15 s)
  only to read the finished ledger.
- **Every orchestrate test builds its world from scratch:** `git init`, a
  `resolve-project write-projections` child and a commit, then the per-test parts.

Test isolation must not weaken: no test may observe another's mutations.

## Requirements

- **R1.** Every call through `BuilderHarness.cli` runs workflow-state in the test
  process. Its stdin bytes and its working directory are honoured. It returns the
  same exit code, stdout bytes and stderr bytes a child process would, except for
  the runner's own frame in the traceback of an uncaught exception.
- **R2.** The in-process runner leaves the process as it found it after every
  call: the working directory, environment, `sys` streams, `sys.argv` and
  `__main__`. That holds whether or not a `cwd` was given, and whether the script
  exits normally, exits non-zero, raises, or is never entered.
- **R3.** The attempt-migration delivery runs at most once per test class, and each
  call hands the test its own copy.
- **R4.** An unmutated orchestrate world's committed project is built at most once
  per test class, and each world gets its own copy.
- **R5.** No existing test is deleted, skipped or weakened. Added tests prove R1–R4,
  and every module that inherits the helper stays green.

## Measured profile (local, relative only)

Measured on mbp (10 cores) on 2026-11-02 with the load average between 14 and 45, so
seconds give direction only. Each prototype patched the harness methods from a
scratch runner without editing the tree. Spawn counts come from a
`subprocess.Popen` audit hook in the test process and do not depend on load.

| Module | Base | Prototype | Load-independent change |
|---|---|---|---|
| `test_delivery_workflow` | 182.2 s | 95.2 s | `workflow-state.py` children 720 → 135 |
| `test_attempt_migration` | 116.6 s | 21.2 s | driver runs 10 → 2; `workflow-state.py` children 324 → 4 |
| `test_orchestrate_control` | 132.9 s | 127.5 s (paired) | world project builds ~50 → 13 |
| `test_control_cutover` | 62.0 s | 32.4 s (paired) | `workflow-state.py` children 234 → 32 |

Every module that inherits the helper passed under the in-process prototype:
`test_delivery_workflow` (86), `test_attempt_custody` (33), `test_delivered_control`
(6), `test_ship_delivery` (12), `test_control_cutover` (20), `test_control_decisions`
(19), `test_delivery_sealing` (7), `test_attempt_migration` (26), and the
helper-backed classes of `test_artifact_budget` (3) and `test_workflow_state` (4).
The orchestrate template passed 47 of 47, including the test that snapshots the
project tree. An orchestrate world costs 0.35 s to build and 0.05 s to copy, so its
template's share of the target is small. The remaining 135 children in
`test_delivery_workflow` come from `DeliveryAdmissionTest`'s direct process
runs, which D1 keeps.

## Solution

1. **Extend the in-process runner, then route the builder helper through it.** The
   runner gains subprocess.run's `input`, `cwd` and `text` parameters (D2, D3).
   `BuilderHarness.cli` calls it in bytes mode with the stdin and working directory
   it already accepts and the environment it already builds. Every class that
   inherits the helper changes transport with it, and nothing else changes (D1).
2. **Deliver issue 207 once per class.** `delivered_207()` runs the driver the
   first time a test class asks for it and keeps the finished ledger as text. It
   removes the driver's directories at once and returns a fresh parse on every
   call (D4).
3. **Build the orchestrate project once per class.** An unmutated
   `OrchestrateWorld` copies its committed project from a template that is built
   the first time its test class needs one. HOME, the shims, the call log and the
   environment are still made per world (D5).
4. **Prove isolation and parity with added tests** at the runner, the helper and
   both fixtures (D6).

## Decisions

### The in-process runner (D2, D3, D7)

- `run_script(script, args, *, env, input=None, cwd=None, text=True)` keeps its
  name, its fresh `__main__` namespace per call and its compile-once code cache
  (262 D4). The new keywords mean what they mean to `subprocess.run`:
  - `input` becomes the script's stdin bytes: bytes in bytes mode, UTF-8-encoded
    text in text mode. `None` is empty stdin, as today. `sys.stdin.buffer.read()`
    returns those bytes exactly.
  - `text=True` returns today's decoded, newline-normalised strings, so every
    lifecycle-harness call is unchanged. `text=False` returns the raw captured
    stdout and stderr bytes, with no decoding and no newline translation.
  - `cwd` is entered before the script runs. `cwd=None` enters nothing, as a
    child inherits its parent's directory. In both cases the runner records the
    process directory before the call and restores it in a `finally`, on every
    outcome.
- A `cwd` that cannot be entered raises its `OSError` out of `run_script` before
  the script starts, with the process directory unchanged. `subprocess.run` raises
  on the same input, and the runner never reports it as an exit code.
- Exit mapping is unchanged: `SystemExit` gives its code, a non-integer code is
  printed and gives 1, and an uncaught exception prints its traceback and gives 1.
- The runner stays single-threaded and process-global, as before. The suite
  runner gives each module its own process (issue 436), so a fault cannot reach
  another module.
- **Process-wide library state (D7).** Modules the script imports, such as
  `agent_tools`, stay imported across calls, together with their caches. This is
  already true for the lifecycle harness. The runner purges nothing. A test that
  varies an input a library caches per process must reset that cache itself, as
  the phase-budget defaults test does for `AGENT_PHASE_BUDGET`. No class that
  inherits the builder helper varies one. A check found that workflow-state, its
  delivery modules and `agent_tools` read no environment variable, home or
  working directory at import time.

### The builder CLI helper (D1)

- `BuilderHarness.cli(*args, stdin=None, ok=True, cwd=None)` keeps its signature
  and return shape: a `CompletedProcess` with bytes `stdout` and `stderr`, and
  `ok` asserting exit 0 with the decoded stderr as the message. It now calls
  `run_script(WORKFLOW, args, env=…, input=stdin, cwd=cwd, text=False)` and passes
  the environment it builds today, unchanged.
- The test module reaches the runner by a package-relative import. The lifecycle
  harness keeps its by-path load (262 D10), which agent-helpers rule 3 leaves
  alone until its cluster moves.
- The change reaches every class that inherits the helper: the builder, loop,
  contract and worktree classes, ship delivery, delivered control and its custody
  and cutover descendants (the head generation only), the migration driver, and
  the helper-backed artifact-budget and workflow-state classes (262 D10's reach
  rule).

### The attempt-migration fixture (D4)

- `delivered_207()` keeps its name and its return value: the issue-207 ledger's
  parsed state, freshly built for the caller.
- The first call in a concrete test class runs the driver as today: its own root
  and HOME, `setUpClass`, then `deliver_through_remainder()`. It reads the ledger
  as text, then runs the driver's cleanups at once. The text is kept per test
  class, and every call returns `json.loads` of it.
- A run that fails keeps nothing, and its directories are still removed. The next
  call runs the driver again and fails in the same way, out loud.
- Only an immutable string is shared, so no test can observe another's mutation.
  The ledger names paths in the removed driver root. Before this change, those
  paths existed while each test ran. The prototype ran the whole module with the
  root removed before any test read the ledger, and all 26 tests passed. Only the
  parsed state ever crossed, as the class docstring already says.

### The orchestrate world (D5)

- `OrchestrateWorld(case, *, mutate=None, claude_code=…)` keeps its signature and
  attributes. Per world, it still makes the temporary directory, HOME (the manifest,
  the policy link and the host declaration, so `claude_code` still applies),
  `bin/` with shims that embed this world's state path, `state/`, `cwd/` and
  `env`.
- **Unmutated worlds.** The project comes from a template keyed by the concrete
  test class, `type(case)`. The template is built the first time that class needs
  one, by the steps `_commit_project` runs today: `git init`, the contract and
  instruction source, the bound directories, `write-projections`, then the commit.
  It is built in a class-scoped temporary directory, and the class cleanup removes
  the directory and its cache entry. The cleanup is registered before the build
  starts, so a build that fails still has its directory removed. A failed build
  caches nothing, and the next world tries again. Each world copies the template
  into its own project directory with `shutil.copytree(symlinks=True)` (262 H4).
- The template holds no absolute path, as checked: a built project names its
  temporary root nowhere, and its local git config holds only core settings and
  `commit.gpgsign`. It is therefore valid at any destination, and the environment
  of the world that builds it leaves no trace in it.
- **Mutated worlds** build their own project, as today. `mutate` is an arbitrary
  callable, often a closure defined in the test body. `test_admission_replay`
  always passes one, so that module is unchanged.
- Each world's git repository is a full copy, not a link. Only the template
  directory is shared across tests, and no test receives a path into it.

### What stays a real process (D1)

These sites keep their real launches, and they are the launcher coverage that
remains: `DeliveryAdmissionTest`'s direct `workflow-state.py` runs, the
orchestrate world's shims and its `ws`, `run` and `validate` children, the
cutover base generation, the migration lock-wait `Popen`, the base-helper
extraction test, and every test-side `artifact_budget.py` validation.

## Options considered

- **Transport.** (a) Chosen: the builder helper alone moves in-process, through the
  extended runner. (b) Converting every `workflow-state` launch in these modules
  as well would remove the launcher coverage, for about 135 more children. (c) A
  second, bytes-only runner would duplicate the patching and exit mapping (D1, D2).
- **Migration sharing.** (a) Chosen: per-class immutable ledger text, parsed on
  every call, with the driver removed at once. (b) `copy.deepcopy` of a shared
  dict, with the driver kept until class cleanup, would leave a mutable object and
  a mutable tree shared for nothing. (c) `setUpClass` in the two consuming classes
  would be a second place that tracks which classes deliver (D4).
- **World sharing.** (a) Chosen: a per-class template of the committed project
  only, copied per world. (b) Copying the whole world and rewriting the embedded
  shim, HOME and state paths would mean fragile rewriting to save writes that cost
  milliseconds. (c) Keying the template by `mutate` would make each closure a new
  object, so nothing is reused and the identity is unsound (D5).

## Test seams (D6)

All four seams are inside `just agent-workflow-tests`. Coverage preservation
follows 262 D7: every existing test ID is still collected, and every existing
`test_*` body is AST-equal at base and head. Changes stay inside the runner, the
helper, `delivered_207` and the world's constructor, and the new tests are
additions.

1. **The runner against a real child** (a new `test_inprocess_cli` module, listed
   in the recipe beside `test_delivery_workflow`). The test writes a probe script
   that reports its working directory, the length and SHA-256 of its stdin bytes,
   and one environment variable. It also writes a text line to stdout, flushes,
   writes raw bytes, writes a line to stderr, and exits with a code taken from its
   argv. The raw bytes include a non-UTF-8 byte only in the bytes-mode rows, so no
   row tests decoding or buffering order. One table row covers each new dimension:
   - bytes `input` in bytes mode;
   - `str` input in text mode;
   - `cwd` set and `cwd=None`;
   - exits 0 and 3, and `sys.exit("message")`.

   For each row, `run_script` and `subprocess.run([sys.executable, probe, …])`,
   given the same `input`, `cwd`, `env` and `text`, return equal
   `(returncode, stdout, stderr)`. A second test checks that the process directory
   is the same before and after a run that exits non-zero, a run that raises
   (exit 1, with the exception line last on stderr), and a run with a `cwd` that
   does not exist. That run raises `FileNotFoundError` in both transports.
2. **The helper starts no process and honours cwd and stdin** (one class in
   `test_delivery_workflow`, inside the `recorded_spawns()` window of 498 D5). The
   window comes from the lifecycle-harness module this file already loads by path,
   because a package import of `test_workflow_state` from here would be circular.
   The test runs `init-run` with `--repo-root` set to the project root's bare
   name and `cwd` set to the root's parent. It then sends a malformed
   `build-delivery --input -` stdin. Neither command starts a child of its own,
   which the prototype confirmed. The test asserts four things:
   - no process-creation event;
   - the minted run's ledger exists under the project root;
   - the refusal is exactly `workflow-state: invalid builder input JSON: <the
     decoder's message for the same bytes>`;
   - the process directory is unchanged.

   If the helper dropped `cwd`, the relative root would resolve under the test
   process's directory, where it does not exist. The CLI would then refuse
   without writing into the checkout. At base, the helper's `Popen` fails this
   test.
3. **A migration copy is the caller's own** (`test_attempt_migration`). The test
   sits in a class that already delivers, so it adds no driver run, and it makes
   three `delivered_207()` calls. It serialises the first,
   mutates the second at the top level and in nested objects, and asserts that the
   third serialises equal to the first. A shared object would fail this.
4. **A world copy is the caller's own** (`test_orchestrate_control`). The test
   sits in a class whose other tests also build unmutated worlds, and it builds
   two worlds. On the first, it adds and commits a file,
   creates a branch and sets a local git config key. The second world's root
   differs. Its history is the single fixture commit, it has none of the file, the
   branch or the key, and `git status --porcelain` is empty. Every assertion also
   holds for a world built fresh, so the test proves isolation and never sharing.

**Regression net.** The existing tests already pin the helper's forwarding. The
custody fence tests in `test_attempt_custody` are refused only when the session
stands in another attempt's worktree, so they fail if `cwd` is dropped. Every
`build-delivery --input -` test fails if stdin is dropped. Byte-exact stderr pins
fail if bytes mode drifts.

## Acceptance criteria mapping

- **AC1 [code]** is met by seams 1 and 2 (in-process, stdin and working directory
  honoured) and by seams 3 and 4 (a test that mutates its copy leaves the next copy
  unchanged). Per the issue body, AC1's "delivery-workflow CLI calls" are the
  calls through the module's CLI helper. The module's direct process runs stay, as
  D1 decides. The regression net, and a green run of every module that inherits
  the helper, show that nothing else moved.
- **AC2 [evidence]** cannot be shown on the branch (D8). Ship carries it: the
  suite runner's timing table on the merge commit's push to `main` (Agent
  Workflow Tests (advisory), hosted ubuntu-24.04, default worker cap). There,
  `test_delivery_workflow` + `test_attempt_migration` + `test_orchestrate_control`
  must sum to at least 120 s below the same three on the last push to `main`
  before the merge (419.7 s on run 41314186007 when the issue was filed). The
  branch carries the load-independent cause: the spawn counts above, re-measured
  at head in final verification by an audit-hook runner in scratch that is never
  committed (262 D6), with paired local timings as direction only.

## Risks

- **A baseline that moves before the merge.** Sibling #499 (bytecode caching, in
  flight) makes each child cheaper and so narrows the in-process saving. It does
  not touch the eight driver runs that D4 removes, which on their own come to
  roughly 80–90 s of CI time. If the merge push falls short, ship reports the
  gap. No test is weakened to close it.
- **Overlap with #499.** Both issues edit the helper's environment line and the
  world's environment. This issue leaves `PYTHONDONTWRITEBYTECODE` exactly as it
  finds it, because that is #499's decision. Whichever issue merges second keeps
  both edits (D8).
- **In-process blast radius.** A call that leaked process state would reach later
  tests in the same module. R2 and seam 1 cover the directory, and the patches
  restore the rest. One failure mode is new: a test that held an `flock` across a
  helper call would now deadlock instead of blocking a child. As checked, no class
  that inherits the helper does this, and none calls the helper from a thread.
  The migration lock-wait test uses its own `Popen`, which D1 keeps.
- **Copied git index.** A copied index carries the template's stat data, so a
  command that refreshes the index rewrites it in the copy. The one test that
  snapshots the project tree passed under the template. Nothing refreshes it ahead
  of time, because no test needs that (YAGNI).

## Out of scope

- Any product code change: workflow-state, `orchestrate_control`, the
  artifact-budget CLI, the suite runner and its worker cap.
- Editing any other module's files. The modules that inherit the helper change
  transport with it and are otherwise untouched (D1).
- `DeliveryAdmissionTest`'s direct runs, the orchestrate world's real children, the
  test-side `artifact_budget.py` validations, and every other module's own process
  sites (D1).
- Templates for mutated worlds, including `test_admission_replay`'s. Sharing across
  classes or modules. Refreshing a copied git index.
- Bytecode caching and `PYTHONDONTWRITEBYTECODE`, which belong to #499.
- Host-load scheduling (`.agents/knowledge/rejections/host-contention-scheduling.md`).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Only `BuilderHarness.cli` moves in-process, reaching every class that inherits it (10 modules); every other launch in these modules stays a real process as the remaining launcher coverage | Issue body ("the CLI helper goes through the in-process CLI runner"); 262 D4 and D10; prototype: every inheriting module green, 720 → 135 children in `test_delivery_workflow` | Converting `DeliveryAdmissionTest`'s direct runs too: removes launcher coverage for ~135 children the threshold does not need. Overriding `cli` back to a subprocess in other modules: 262 D10's rejected second harness path |
| D2 | `run_script` gains subprocess.run's `input`, `cwd` and `text` keywords; `text=True` stays the default; bytes mode returns raw captured bytes; consumers import it by package-relative import | Q1 (agent-choose); 262 H3 ("the text or bytes the caller asked for"); builder callers compare bytes; agent-helpers rule 3 | A second bytes-only runner: duplicates the patch and exit mapping (DRY). An always-bytes runner: changes the type of ~1,400 lifecycle-harness results. Reusing `test_workflow_state`'s by-path copy of the runner: couples the builder harness to another module's private load when a plain import works. The runner imports no test module, unlike D6's audit window, whose package import would be circular |
| D3 | `cwd` is entered for the call and restored in a `finally` on every outcome; an unenterable `cwd` raises its `OSError` before the script runs, with nothing changed; `cwd=None` leaves the process directory. This extends 262 D4, which kept `cwd` calls as subprocesses | The custody fence reads `os.getcwd()` (`test_attempt_custody` passes `cwd`); `subprocess.run` raises on a bad `cwd`; the bar's fail-loud rule; one process per suite member (issue 436) | Keeping `cwd` calls as subprocesses: two transports behind one helper. Rewriting relative paths instead of entering the directory: the CLI reads its directory itself |
| D4 | `delivered_207()` runs the driver once per concrete test class, keeps the ledger as text, removes the driver's directories at once, and returns a fresh parse per call; a failed run caches nothing | Issue body ("once per class … a deep copy"); the class docstring (only parsed state crosses); prototype: 26/26 green with 2 driver runs and no driver tree present; 262 D1 (failures not cached) | `copy.deepcopy` of a shared dict with the driver kept to class cleanup: shares a mutable object and tree that no test needs. `setUpClass` in the two consuming classes: a second record of which classes deliver. A module-wide memo: it would save one more driver run, but it goes past the per-class granularity the issue names, and the threshold does not need it |
| D5 | An unmutated `OrchestrateWorld` copies its committed project from a lazily built per-test-class template (`copytree(symlinks=True)`, removed with its cache entry by the class cleanup); HOME, shims, state, `cwd` and `env` stay per world; a mutated world builds as today | Issue body; checked: the project holds no absolute path, while the shims and `env` do; build 0.35 s vs copy 0.05 s; 47/47 green; 262 H4 and D11 | Keying templates by `mutate`: closures are new objects per call, so nothing is reused. Copying the whole world and rewriting embedded paths: fragile, for writes that cost milliseconds. A module-wide template: it goes past the per-class granularity the issue names, to save about 12 builds (~4 s locally) |
| D6 | Four added seams: runner parity with a real child plus directory restoration; the helper inside `recorded_spawns()` (taken from the lifecycle module this file already loads) with a relative `--repo-root` under `cwd` and a malformed stdin; a three-call migration copy check; a two-world isolation check that holds for fresh builds too. The runner seam is a new recipe member, `test_inprocess_cli` | The bar ("tests that can fail", no call-count assertions); 498 D5's audit hook; 262 D7's coverage proof; prototype: both helper commands start no child; a package import of `test_workflow_state` from `test_delivery_workflow` is circular through `test_delivered_control` | `--repo-root .`: a dropped `cwd` would mint a run into the checkout's own `.superpowers`. Asserting driver or template build counts: a call-count assertion. Cross-test ordering proofs: pass vacuously when one test runs alone. Folding the runner tests into `test_delivery_workflow`: the runner serves both harnesses (single responsibility) |
| D7 | Library modules and their per-process caches persist across in-process calls; the runner purges nothing, and a test that varies a cached input resets it itself | `phase_budget.current` is `functools.cache`d over `AGENT_PHASE_BUDGET`, and the phase-budget defaults test already clears it; no class that inherits the helper varies one; 262 D4 | Re-importing `agent_tools` per call: brings the start-up cost back. Clearing named caches in the runner: couples a generic test runner to product modules |
| D8 | AC2 is post-merge evidence that ship carries; the branch carries spawn counts and paired local timings as direction. `PYTHONDONTWRITEBYTECODE` in the helper and world environments stays as found, and whichever of #499 and #500 merges second keeps both edits | Issue AC2 wording; 498 D6; issue 499 owns bytecode caching; local load was 14–45 on 10 cores | A pre-merge timing gate: cannot observe the merge push. Removing `PYTHONDONTWRITEBYTECODE` here: pre-empts #499 and conflicts with it |
| D9 | Both per-class caches (the 207 ledger text, the world template) are module-level dicts keyed by the concrete class `type(case)`; the entry's class cleanup, registered through `addClassCleanup` on that class, pops it (and, for the template, removes its directory) | D4, D5 ("per concrete test class"); 262 H4 (class-scoped fixtures with class cleanups); unittest runs a class's cleanups at class teardown even when a test registered them | A class attribute set on `type(self)`: attribute lookup inherits it, so a derived test class would reuse its parent's entry. No cleanup for the ledger text: a stale entry would survive a second run of the class in one process |
| D10 | Seams 3 and 4 pass before their change by design, so Tasks 3 and 4 are made falsifiable by scratch-only checks: a mutation (a shared parsed dict, a shared template path) that each seam must fail, and uncommitted counters (driver runs per module, project builds against classes plus mutated worlds). The final gate times the three modules paired base/head in a detached scratch worktree at the base, because `test_attempt_migration`'s base-helper test reads the repository's git history | The bar (tests that can fail; no call-count assertions); 262 D6 (scratch measurement never committed); D6, D8 | Committing driver or build counters: the call-count assertions D6 rejects. A `git archive` base tree for timing: its base-helper test fails without the repository's history. Comparing local timings with CI's 419.7 s: a different host, not paired |
