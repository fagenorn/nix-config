# Run the agent workflow tests in parallel, with per-module timings — issue 436

Design for https://github.com/fagenorn/nix-config/issues/436. Base: `ca6ba1ae`
(`origin/main`). A bare "Dn" cites this spec's ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "doubt", "evidence": "the `just agent-workflow-tests` recipe gains a worker-cap option and a serial mode; the project.json command id and CI invocation stay unchanged"}, "concurrency_or_persistence": {"value": "hit", "evidence": "the slice introduces concurrent execution of test modules under a worker cap and must remove cross-module shared filesystem state"}, "open_design_questions": {"value": "doubt", "evidence": "runner location, default cap value and the option spelling are open but phraseable and answerable from precedent"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria, one of them a CI-duration evidence criterion no deterministic code check verifies"}}, "paths": ["justfile", "python/agent_tools/test_suite_runner.py", "tests/test_test_suite_runner.py", "home/common/agent-skills/tests/test_sdd_workspace.py"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`just agent-workflow-tests` is the verification every ship of agent tooling
pays, locally (as the `agent-workflow-tests` verification id) and in the
advisory CI job. It runs 102 unittest modules one after another in a single
`python3 -m unittest -v` process, then the eval-tree shell test. On the hosted
4-vCPU runner that step takes about 17 to 18 minutes, and a developer sees no
per-module cost, so the next round of speed work cannot tell where the time
goes.

The maintainer wants the modules to run at the same time under a modest,
configurable worker cap, with pass/fail unchanged, each module's output kept in
one block, serial running kept for debugging, and a closing per-module timing
table, slowest first. Several agents may verify on one host at once; scheduling
across them stays deferred (`.agents/knowledge/rejections/host-contention-scheduling.md`),
so the only control is a per-run cap.

Two facts found while designing shape the slice:

- **The advisory job has not passed at `main` for some time.** CI run
  40263175321 at `ca6ba1ae` (and the issue's baseline run 40194721214) ended
  with 10 failures and 8 errors from two environmental causes that serial mode
  shares: the job checks out one commit, so the five modules that build
  fixtures from pinned ancestor commits fail as their design demands ("fetch
  it, do not skip"); and the adopt-verify fixture takes this repository's
  contract, whose review commands are not installed on the hosted runner, so
  four verdicts become `adopted_with_blockers`. Because the unittest process
  failed, the eval-tree script never ran there. AC4 is measured by that job, so
  the slice must make it green (D8).
- **No concurrency hazard surfaced at design time** (D7): three full parallel
  runs on the darwin dev host, at caps 4, 8 and 32, all passed and left the
  checkout, the real home's agent state and the temp directory without
  fixed-name residue.

## Solution

A new standard-library module, `agent_tools.suite_runner`, runs a list of suite
**members** (test files) as separate child processes, at most `--jobs` at a
time (default 4), and prints each member's whole output as one block when it
finishes, then a timing report. The `agent-workflow-tests` recipe keeps its
curated member list and hands it to the runner, with the eval-tree script as
one more member. `--jobs 1` is serial mode, streaming each member's output
live. The CI invocation, the `agent-workflow-tests` verification id and its
argv do not change. The advisory job's checkout fetches full history and the
adopt-verify fixture stops depending on the host's installed review commands,
so the CI job can report the suite truthfully.

## Decisions

### Runner placement and invocation (D1)

- Module `agent_tools.suite_runner`, a thin shell per agent-helpers rule 2:
  argparse with `prog="agent-workflow-tests"` (the recipe a person types, as
  `instruction_load` uses `agent-instruction-load`), and the scheduling, block
  formatting and report as importable functions.
- Run only by the recipe as `python3 -m agent_tools.suite_runner` under the
  recipe's `PYTHONPATH`; no row in the package's command table and no
  installed launcher. The package build still import-checks it, because it
  walks every module.
- Standard library only, and it must run on the hosted runner's Python 3.12 as
  well as the dev hosts' 3.13. Importing it has no side effects: the build's
  import check loads it, and only `main` starts processes.

### Members and the recipe (D2, D3)

- A member is a path relative to the runner's working directory (the
  justfile directory). The runner picks a member's command from its suffix,
  a closed set that fails loud on anything else:
  - `.py`: `sys.executable -m unittest -v <path>` (unittest maps the path to
    the same dotted name today's run imports, so the tests' relative imports
    behave as they do now).
  - `.sh`: `bash <path>`, run by name on `PATH`.
- Members start in the order given. Each member's process inherits the
  runner's environment (`PYTHONPATH`, `WORKFLOW_POLICY_SURFACE`) and working
  directory.
- The recipe becomes `agent-workflow-tests *args:`, running
  `PYTHONPATH=… python3 -m agent_tools.suite_runner {{args}} <members…>`. The
  102 existing paths stay in their current order and the eval-tree script
  becomes the last member; the new runner test module joins the list. The
  recipe's doc comment (what `just --list` shows) names the default cap and
  `--jobs 1`.
- Existing tests that check the justfile still names their module path (in
  `test_agent_model_drift_scheduling` and `test_delivery_model`) stay green,
  because every path stays in the recipe text.

### Interface (D4, D5)

- One option, `--jobs N`: an integer of at least 1, defaulting to the module
  constant `4`, which `--help` prints from the constant. A person runs
  `just agent-workflow-tests --jobs 1` for serial mode, or another `N` on a
  quieter or busier host. There is no environment variable.
- **Parallel mode** (`N` ≥ 2): each member's stdout and stderr go into one
  pipe, so their relative order survives, and its stdin is `/dev/null`.
- **Serial mode** (`N` = 1): one member at a time, its stdin, stdout and
  stderr passed straight through, so a hang shows where it is and
  `breakpoint()` works; the runner's framing lines still bracket it.
- **Usage errors exit 2 before any member starts**: a malformed or `< 1`
  `--jobs`, no members, a duplicate member (compared after path
  normalisation), a member that is not an existing file, a member outside the
  working directory (unittest cannot import it), or an unknown suffix.

### Output contract (D6)

Every line the runner writes starts with the fixed prefix `suite-runner:`, and
names the member by its path exactly as given. The planner may adjust the
wording of the lines below but keeps their fields and order.

```text
suite-runner: start <member>
suite-runner: begin <member>
<the member's output, byte for byte>
suite-runner: end <member> <passed|failed> exit=<code> <seconds>s
…
suite-runner: timings, slowest first
suite-runner: <seconds>s <passed|failed> <member>      # one row per member
suite-runner: failed <member>                          # one per failed member, in list order
suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<seconds>s
```

- The `start` line is written when a member launches, so a job that hits its
  time limit shows which members were still running.
- In parallel mode a member's `begin`, its captured output and its `end` are
  written as one write when it exits, in completion order, under the same
  lock as the `start` lines, so no runner line lands inside a block. A worker
  writes its block before it takes the next member, so the start/end sequence
  never shows more than `N` members open. In serial mode `begin` follows
  `start` at once and the output streams before `end`. The member's stdout
  stays inside the bracket, while its stderr streams to the runner's stderr
  in the same window.
- `<seconds>` is wall-clock from launch to exit, one decimal place. `exit=` is
  the child's exit code, or `signal <n>` for a child killed by a signal.
- A member **passes** only on exit 0. A non-zero exit fails it, including
  unittest's exit 5 for a module that ran no tests (Python ≥ 3.12), and so do a
  signal death and a launch failure (whose error text becomes the block's
  output).
- After a failure, every remaining member still runs. The report is the last
  thing every completed run prints: one row per member, slowest first, with
  ties in list order.
- **Exit codes**, a closed set:
  - `0` when every member passed;
  - `1` when any member failed;
  - `2` on a usage error;
  - `130` on a keyboard interrupt. The interrupt reaches the members too,
    since they share the runner's process group. The runner starts nothing
    more, waits for the running members and prints no summary, because an
    interrupted run is not a completed one.

### Concurrency hazards (D7)

- **How they are found.** The suite is run in parallel several times at the
  default cap and at a stress cap (at least `--jobs 16`), and in serial mode
  once. After each parallel run three things are checked:
  - `git status --porcelain --ignored` shows nothing new apart from bytecode
    caches;
  - nothing new appears under the real home's `.agents`, `.claude`,
    `.codex`, `.config` or `.cache`;
  - nothing with a fixed name appears in the system temp directory.
  The PR's CI run is the Linux check.
- **How they are fixed.** A module that fails only in parallel, or leaves
  shared residue, gets its own temporary location for the path, home or
  fixture directory it shares. The fix never uses a serial-exemption list, a
  retry or a cross-process lock.
- **Design-time result.** Runs at caps 4, 8 and 32 found no hazard, and a
  static search found no test writing relative to the repository root. The
  slice therefore plans no test changes for concurrency and owns any that the
  ship-time runs surface.

### CI truthfulness prerequisites (D8)

- The advisory job's `Checkout` step fetches full history (`fetch-depth: 0`,
  as Nix Eval, Flake Checker and Instruction Budget already do), and
  the workflow-shape tests pin it for that step. All three pinned
  base commits are ancestors of `main`, so a full checkout of a PR's merge ref
  or of a push reaches them. The longer clone lands in `Checkout`, not in the
  step that AC5 times. Nothing else in the job changes: name, step names and
  ids, `continue-on-error`, the `--command just agent-workflow-tests`
  invocation and the 45-minute limit stay.
- The adopt-verify fixture makes the review capability resolvable
  independent of the host, the same way it already opts out of release, so its
  verdicts do not depend on what is installed. Test semantics do not change:
  a case expecting `adopted` still demands `adopted`.
- A further failure that appears only on CI is fixed in this slice when it
  has one of these two causes (missing history, a fixture that depends on the
  host). Any other cause goes back to the caller.

### Default cap and AC5 (D5, D10)

- **Measured on the darwin dev host** (36 logical CPUs). The suite is
  CPU-bound: at cap 8 the members used 1,559 CPU-seconds in 1,687
  wall-seconds. Cap 4 took 354 s of wall time, cap 8 228 s and cap 32 190 s.
- **Measured on CI** (serial, from log timestamps of run 40263175321). The
  unittest part took 1,015 s. The slowest modules took 118 s
  (`test_delivery_workflow`) and 114 s (`test_workflow_state`).
- **Estimate.** With D8, the history modules and the eval-tree script add
  roughly 85 s, so CI work is about 1,100 s. A list-order schedule over four
  workers simulates at 282 s, against 277 s for longest-first. The step should
  therefore land at about 280 to 370 s if the runner's 4 vCPUs give 3 to 4
  times serial throughput. It will be slower if they are SMT siblings.
- **Evidence** (collected by ship, from
  `gh run view <run> --json jobs`, the `startedAt`/`completedAt` of the step
  "Run agent workflow tests" in "Agent Workflow Tests (advisory)"):
  - the PR's CI run gives a pre-merge reading, cited in the PR;
  - the push run of the merge commit is the AC5 measurement, recorded on the
    issue together with that run's timing report.
- **If a reading exceeds 360 s at the default**, the owner records the
  reading and the CI timing report and returns to the caller. It does not
  raise the default above 4 or speed up modules in this slice.

### Documentation

- The package README gains a short `suite-runner` section covering the member
  kinds, `--jobs` with its default and the reason for it, serial mode, the
  output contract and exit codes, and the no-exemption rule for shared state.
- The recipe's comment carries the one-line summary.
- `CLAUDE.md` is unchanged: it names neither the recipe's options nor the
  runner.

## Test seams

All runner tests live in a new `tests/test_suite_runner.py` (in the suite),
following agent-helpers rule 5. They drive `python -m agent_tools.suite_runner`
as a subprocess, with its working directory in a temporary directory, over
fixture member files the test writes there. No assertion depends on how long
anything took (D9).

- **Rendezvous.** Fixture members coordinate through a temporary directory
  that the test names in the runner's environment, which every member
  inherits:
  - each member creates a live token and records how many live tokens it saw;
  - it waits, with a generous deadline that fails it loudly, until the live
    count reaches `min(cap, members not yet done)`;
  - it then writes its output while its token is still live, removes the
    token and marks itself done.

  A correct runner always satisfies the barrier. A runner that never overlaps
  members fails it.
- **AC1, failure isolation.** A failing member and a passing peer each write
  markers to stdout and stderr in several flushed writes while both are
  running. The test asserts exit 1, and that every one of the failing member's
  markers lies between its `begin` and `end` lines with no other runner line
  or peer marker in that span. The failing member's `end` line says `failed`,
  and every member still appears in the report.
- **AC2, cap.** With `--jobs 2` over five members, and again with no `--jobs`
  over six members against a barrier of 4, the test checks two things:
  - the start/end sequence never has more than the cap open, and reaches the
    cap;
  - no member recorded more live tokens than the cap.

  The second run shows the default is 4. A `--jobs 1` run, against a barrier
  of 1, checks serial mode the same way, and checks the brackets on stdout
  markers only.
- **AC3, report.** End to end: the report is the run's last output, has
  exactly one row per member, prints non-increasing durations and lists the
  failed members. The ordering rule (slowest first, ties in list order) is
  tested on the importable report function with constructed durations.
- **Usage.** Each D4 usage error exits 2 and starts no member, which the test
  sees as no fixture token or marker written.
- **CI shape.** The existing workflow-shape tests in
  `tests/test_branch_protection.py` gain the advisory checkout's full-history
  pin (D8).
- **AC4 and AC5** are evidence rather than unit tests:
  - AC4 is the green advisory job on the PR and on the merge push, plus one
    `just agent-workflow-tests --jobs 1` run at the head, cited in the PR by
    its summary line;
  - AC5 is the step duration per D10.

## Out of scope

- Scheduling across agents or hosts, or adapting the cap to load (the
  rejection record stands); a cap derived from the CPU count.
- Making any slow module faster, splitting modules, or running at test-class
  granularity. Ordering members by recorded timings is also out.
- Per-member timeouts, retries, a JSON or file timing output, and a
  serial-exemption list.
- Any CI change beyond the advisory checkout's history depth. In particular
  the job's invocation, its advisory status and the required checks stay.
- The seven test files outside the suite: the installed and retained tiers
  (`agent-installed-skill-tests`, `agent-retained-tests`), the lifecycle
  guard's table and the oMLX tests.
- The temporary directories some fixtures leave behind (their names are
  unique, so they do not collide).
- The path-conditional verification of
  https://github.com/fagenorn/nix-config/issues/437.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The runner is a new stdlib module `agent_tools.suite_runner` (prog `agent-workflow-tests`) run only by the recipe via `python3 -m`, with no command-table row or launcher. | agent-helpers rules 1–3, 5; precedent `agent_costs`, `agent_model_drift`, `agent_gate_bundle`, `instruction_load` run from the justfile with no row; YAGNI (no installed caller). | `xargs -P`/shell in the recipe (no contiguous blocks or report without a hand-rolled script, and no test seam); pytest-xdist or similar (not stdlib, changes the runner semantics, and the runner's Python has no packages); an installed launcher (no caller). |
| D2 | One child process per test file (`python -m unittest -v <path>`). The eval-tree script joins as a `.sh` member run by `bash`. The member kind is a closed suffix set that fails loud. | Issue asks for per-module timing, and AC3 for a report ending the run that covers every module; on CI the trailing script never ran after a unittest failure. | Test-class or test-case granularity (loses per-module timing, repeats class setup); keeping the script as a trailing recipe line (the run would end after the report and skip the script on failure). |
| D3 | The curated member list stays in the recipe, in today's order, as the runner's arguments, and members start in list order. | Seven test files are deliberately outside the suite (installed, retained, guard and oMLX tests); DRY keeps one home; a list-order schedule simulates within 2% of longest-first at cap 4. | Glob discovery with an exclusion list (silently enrols new installed-tier tests); a separate manifest file (a second home for the same list); longest-first from stored timings (new state, YAGNI). |
| D4 | The only option is `--jobs N` (≥ 1), passed through `just agent-workflow-tests *args`. `--jobs 1` is serial mode, with stdio passed through and live output. Parallel members get stdin `/dev/null` and one merged output pipe. There is no environment variable, and the verification id, its argv and the CI invocation are unchanged. | The-bar token economy (one knob for one axis); precedent `agent-instruction-budget *args`; the issue keeps serial "for debugging"; `tests/test_branch_protection.py` pins `--command just agent-workflow-tests`. | A separate `--serial` flag (two knobs for one axis); an env var (a second channel with no caller); the old single-process run as serial mode (a second execution path with different cross-module state). |
| D5 | The default cap is the fixed constant 4, documented in `--help`, the recipe comment and `python/README.md`. | AC2 requires a fixed value. The suite is CPU-bound (1,559 CPU-s over 1,687 wall-s), so throughput saturates at the hosted runner's 4 vCPUs, and 4 is modest beside the recorded load 71 on 10 cores. | `os.cpu_count()` (36 on the dev host: neither fixed nor modest); 8 (no gain on 4 vCPUs, double the contention on shared hosts); 2 (cannot approach 360 s from about 1,100 s of work). |
| D6 | Output contract: prefixed `start` lines at launch; each member's merged output is one locked `begin`/output/`end` block in completion order; every member runs after a failure; a closing report (rows slowest-first with ties in list order, `failed` lines, then `summary`). Exits: 0 all passed, 1 any member failed (non-zero exit including unittest exit 5, a signal, or a launch failure), 2 usage error before any start, 130 interrupted (no summary). | The issue (contiguous blocks, report, pass/fail unchanged); the-bar truthful terminal states and "the log stream is the debugger" (start lines name in-flight members on a timed-out job). | Blocks in list order (holds finished output behind slower modules); stopping at the first failure (hides later failures, as today's recipe hides the script). |
| D7 | Hazards are found by repeated parallel runs at the default and at `--jobs 16`+, each followed by a residue audit, plus the PR CI run. Each is fixed by giving the test its own temporary location, never by an exemption list, retry or lock. None were found at design time (caps 4, 8 and 32). | The-bar root causes ("no sleep to paper over a race"); issue scope says shared-state tests are made independent. | A must-run-serially member list (masks the defect, YAGNI); a cross-process lock (keeps the shared state). |
| D8 | In scope because AC4 is measured by the advisory job: its `Checkout` gains `fetch-depth: 0`, pinned in `tests/test_branch_protection.py`, and the adopt-verify fixture resolves review commands independent of the host. Further CI-only failures are fixed here only when they come from those two causes, and otherwise return to the caller. | CI run 40263175321 at `ca6ba1ae`: all 10 failures and 8 errors come from those two causes, and the tests say "fetch it, do not skip"; the sibling jobs already use `fetch-depth: 0`; the fixture already opts out of release for host independence. | Leaving them (AC4 could not be met); skipping the cases on CI (they forbid skipping, and it would weaken semantics); a wider CI restructure (out of scope). |
| D9 | Runner tests run `python -m agent_tools.suite_runner` end to end over generated fixture members that meet at a filesystem barrier (`min(cap, not done)`, with a bounded deadline). The cap is checked by the start/end sequence and by member-observed live counts, contiguity by markers written while a peer writes, and report ordering on the importable report function. No assertion uses an elapsed duration. | agent-helpers rule 5; the-bar tests that can fail (a never-overlapping runner fails the barrier, an over-subscribing one fails the counts); the issue asks for runner tests in the suite. | Mocking `subprocess` (asserts calls, not behaviour); fixed sleeps to force overlap (flaky, and they paper over a race); asserting real durations (timing-dependent). |
| D10 | AC5 evidence: the PR's CI step duration is the pre-merge reading and the merge commit's push run is the measurement, both read from `gh run view --json jobs` step timestamps. A reading over 360 s at the default is reported with the CI timing table and returned to the caller, never answered by raising the default or speeding modules here. | The issue's AC5 (merge push, default cap); the estimate of about 280 to 370 s rests on the runner's unknown SMT layout; scope keeps module speed-ups out. | Raising the default until CI passes (breaks "modest" and the meaning of AC2); claiming AC5 from local runs (wrong host class). |
| D11 | Output details left to the planner (D6): a death by signal shows `exit=signal-<n>` and a member that never launched shows `exit=launch-error` (its `OSError` text is the block's output). Report rows are `{seconds:7.1f}s`, sorted on the one-decimal value shown, then list position. A parallel block gains a newline before `end` only when the output lacks one. An interrupt prints `suite-runner: interrupted, waiting for running members` before the wait. | D6 lets the planner adjust wording while keeping fields and order; the-bar "the log stream is the debugger"; a test needs an observable handshake rather than a sleep. | `exit=signal <n>` (two tokens break a one-pattern parse of the end line); sorting on the raw float (two rows printing the same value could break list order); a silent wait on interrupt (nothing tells a person, or a test, that the runner is waiting). |
| D12 | Exit 130 has end-to-end tests in both modes: SIGINT goes to the runner process alone, and the held members are released only after the interrupt line appears. The test installs a caught SIGINT handler for its duration, so the runner child starts with the default disposition. The runner's main thread waits on a `threading.Condition` that counts running workers, never on `Thread.join()`. | D6's closed exit set; the-bar truthful terminal states and tests that can fail. Seen in planning: on Python 3.12 (the hosted runner's version) a KeyboardInterrupt during `join()` marks the running thread stopped, so the process exited before that worker wrote its block. | Leaving 130 untested (a runner that swallows the interrupt and prints a report stays green); signalling the whole process group in the test (the members' exit races the runner's handler, so "starts nothing more" cannot be asserted deterministically); `Thread.join()` (the 3.12 trap above). |
| D13 | Refines D8. The three adoption fixture sites that already opt out of release (`adopted_repo`, `verifiable_repo` and the diverged-branch case) share one helper, `host_independent` in `test_adopt_project.py`. It keeps the release opt-out and rebinds the two commands that `workflow.review` names to `true`, so review resolves `available` on every host. | CI run 40263175321: the eight verdict failures are `review.plan`/`review.code` `command_missing`, reproduced locally with `codex-companion` off `PATH`. `test_adopt_apply.apply_repo` already binds review to `true`. DRY: the opt-out had three copies. | Declaring review `unsupported` (changes the capability state every host exercises from `available` to `unsupported`); editing `fixture_contract` itself (the base of every adoption fixture, including the one that models this repository's real shape); touching `apply_repo` or the boundaries fixtures (they pass on CI). |
| D14 | Refines D12. While the parallel runner starts its worker threads, SIGINT is held by a temporary handler and re-delivered with `signal.raise_signal` inside the `try` that handles an interrupt during the wait, so the stop flag is always set and the waited-on worker count equals the workers started. An end-to-end test raises SIGINT right after the first worker starts. | Phase-5 Codex review PR-01: an interrupt during startup reached `main` without setting the stop flag, and a count set before the threads started could wait forever; D6's interrupt contract (start nothing more, wait for running members). | Starting the threads inside the handled `try` with the count fixed in advance (an interrupt mid-start leaves the count above the started workers, and the wait never ends); counting each thread after `start()` returns (an interrupt between the two loses a started worker, and the count can go negative). |
| D15 | Evidence must be able to fail. The serial-mode test reads a member's marker from the runner's stdout before releasing that member, so a runner that holds output until exit fails at the member's deadline. AC4's CI evidence is each run's observation record with `raw.suite` `success` and the `failed=0` summary line, not the job's colour. | Phase-5 Codex review PR-02 and PR-03; D4 (serial output is live, for debugging); `.github/workflows/ci.yaml` marks the suite step `continue-on-error: true`; the-bar tests that can fail. | Checking serial output only after the run (a buffering runner passes); citing the advisory job's green status (it is green even when the suite fails). |
