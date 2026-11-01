# Suite timing report shows child CPU time per module — issue 497

Design for https://github.com/fagenorn/nix-config/issues/497 (parent
https://github.com/fagenorn/nix-config/issues/436). Base: `8d0bbc25`
(`origin/main`). A bare "Dn" cites this spec's ledger; "436 Dn" cites the
ledger of `2026-10-26-issue-436-parallel-workflow-tests-design.md`.

## Triage

- input: {"signals": {"contract_change": {"value": "doubt", "evidence": "the documented suite-runner report lines (python/README.md, ship-cited summary line) gain a CPU column and a suite CPU total; no machine consumer beyond tests and ship's failed=0 grep"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "per-member CPU needs the child's rusage at reap time, which changes how the parallel worker threads and the serial loop wait on member processes; no persisted state"}, "open_design_questions": {"value": "no", "evidence": "measurement source (os.wait4 rusage per child) and column placement are settled by the issue text and codebase precedent; only test thresholds are self-answerable"}, "criteria_shape": {"value": "no", "evidence": "one acceptance criterion, verified by a deterministic runner test in tests/test_suite_runner.py"}}, "paths": ["python/agent_tools/suite_runner.py", "tests/test_suite_runner.py", "python/README.md"]}
- verdict: {"hits":["contract_change","concurrency_or_persistence"],"lane":"full","mode":"shadow"}
- ran: full (shadow)

## Problem

On the hosted 4-vCPU runner, the module times of a parallel
`just agent-workflow-tests` run add up to 2,033 s, against 1,092 s when the
same modules run one at a time: each module takes 1.86 times as long when four
run at once. The closing timing table shows wall time only, so a reader cannot
tell whether that stretch is CPU saturation (four CPU-bound modules and their
subprocesses sharing four vCPUs) or I/O wait (one class alone issues about
9.5k fsyncs). The two causes call for different next steps, cutting process
starts or moving temporary directories to tmpfs, so the next speed issue needs
the measurement first.

## Solution

The runner reads each member's CPU time at the moment it reaps the member:
`os.wait4` returns the resource usage of the member's process together with
every descendant reaped beneath it, and its user plus system seconds are the
member's **child CPU time**. Every row of the closing table prints that figure
next to the member's wall time, and the summary line ends with the suite total.
A member whose CPU is close to its wall time was computing; one far below it
was waiting, for I/O, a sleep or a CPU it could not get. The suite total set
against `wall × the CPUs the run could use` (the smaller of `--jobs` and the
host's CPUs) says which: near it, every slot was computing and the CPUs were
saturated; well below it, the members were waiting on something else. A
module whose CPU itself grows from a serial run to a parallel one ran on
slower, shared CPUs.

## Decisions

### Measurement (D1)

- `MemberResult` gains `cpu_seconds`, the `ru_utime + ru_stime` of the rusage
  that `os.wait4` returns for that member's pid. On Linux and macOS this covers
  the member's process and every descendant that it, or an intervening
  descendant, waited for: the `git`, `python -m agent_tools.…` and other
  subprocesses the suite's modules run. A descendant still running when the
  member exits, or never waited for, is not counted.
- Probe on darwin, Python 3.13: a member that waited on a grandchild spinning
  1.0 s of CPU was reported at 1.04 s, and a member sleeping 1.0 s at 0.02 s.
- A member that never launched has no process, so its CPU is `0.0`; its exit
  field stays `launch-error`.
- One function reaps a member, for both modes: a single `os.wait4(pid, 0)`, the
  status converted with `os.waitstatus_to_exitcode` (negative for a signal, as
  `exit=signal-<n>` needs today), stored as the `Popen`'s `returncode` so that
  nothing waits on it again, and returned with the CPU seconds. Nothing else
  waits on a member. Each member's `Popen` stays referenced until it is reaped,
  so `subprocess`'s own clean-up of abandoned children never polls it.
- Wall time is measured as before, from just before launch to just after the
  reap.

### Reaping and interrupts (D2)

- **Parallel mode.** A worker reads the member's merged output to its end,
  closes the pipe, then reaps the member. That is what `communicate()` does for
  one output pipe and no input, so capture is unchanged. Python runs signal
  handlers on the main thread only, so a worker's reap is never interrupted.
- **Serial mode** waits on the main thread, where a SIGINT raises
  `KeyboardInterrupt`. If that lands after `wait4` has reaped the member but
  before its result is bound, the status and the CPU are lost, and the
  interrupt path's second wait raises `ChildProcessError`. (Today, `Popen.wait`
  in the same window turns that `ECHILD` into exit 0: a false pass.) So:
  - every interruptible wait, the normal one and the interrupt path's, is
    `os.waitid(P_PID, pid, WEXITED | WNOWAIT)`, which returns once the member
    has exited and reaps nothing. A SIGINT there raises `KeyboardInterrupt`
    just as `Popen.wait` does today, so the interrupted line is still written
    while the member runs;
  - the reap that follows cannot block. It runs with SIGINT held by the
    existing `_HeldSigint`, which re-delivers a held interrupt only after the
    result is recorded, the pattern 436 D14 uses for launches. An interrupt
    path that finds the result already recorded writes the end line from it
    and does not wait again, so every started member still gets its end line.
  - Probe on darwin: a SIGINT interrupts `waitid(WNOWAIT)` with
    `KeyboardInterrupt` and leaves the member unreaped, and a second `waitid`
    then `wait4` reap it with its rusage. `os.waitid` and `WNOWAIT` have existed
    on Linux since Python 3.3.
- Launching, the start, begin, end and interrupted lines, the exit codes and the
  436 D14 launch hold do not change.
- A runner started with SIGCHLD ignored has its members reaped by the kernel,
  so no status exists to read. `wait4` then raises `ChildProcessError` and the
  run fails loudly, where `Popen` today reports exit 0 for every member.

### Report contract (D3)

```text
suite-runner: timings, slowest first
suite-runner: <wall>s wall <cpu>s cpu <passed|failed> <member>    # one row per member
suite-runner: failed <member>                                     # one per failed member, in list order
suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<seconds>s cpu=<seconds>s
```

- Both row figures are formatted `{:7.1f}`, so the two columns line up. Rows
  still sort on the wall figure shown, then on list position (436 D11).
- `cpu=` is the sum of the members' unrounded CPU seconds, printed to one
  decimal, so it can differ from the sum of the printed rows by rounding. It
  counts members only, never the runner's own CPU.
- The summary keeps every existing field in its order, and `cpu=` is appended,
  so a `suite-runner: summary members=… failed=0` prefix match (ship's
  citation, plan acceptance greps) still holds. No program parses the summary.
- The header, the failed lines and the start, begin and end lines do not
  change. A run cut off before its report has no CPU figures.

### Documentation

- The runner paragraph in `python/README.md` gains: each row's wall and child
  CPU time, with D1's definition (user plus system, the member and the
  descendants it waited for, read when the runner reaps it, unreaped
  descendants not counted); the summary's `cpu=` total; and how to read them,
  as in the Solution, including the comparison with the smaller of `--jobs`
  and the host's CPUs.
- The recipe comment and `CLAUDE.md` do not change: neither describes the
  report.

## Test seams

All in `tests/test_suite_runner.py`, at the two seams issue 436 established
(agent-helpers rule 5): the importable `report_lines`, and the runner run end
to end as `python -m agent_tools.suite_runner` over fixture members in a
temporary directory.

- **Report function, exact lines.** The existing ordering test gains CPU
  values and pins: the aligned two-figure rows, the launch-error member's
  `0.0`, and a `cpu=` total taken from unrounded values (three members at
  0.04 s each print rows of `0.0` and a total of `0.1`).
- **End to end, CPU against wall (D4).** Two new tests run a busy member and a
  sleeping member, in that list order, one with `--jobs 2` and one with
  `--jobs 1`, because D2 changes both reaping paths. Each is its own test so
  that each starts from a fresh barrier: a `done` marker left by the other run
  would let the sleeping member skip its wait.
  - The busy member runs a grandchild, `sys.executable -c`, whose loop spins
    until its own `time.process_time()` reaches 1.0 s. Around the grandchild
    it measures its own **share**, the change in `os.times()` user, system and
    children's time over the change in `time.monotonic()`. It writes the share
    under the barrier's `seen` directory, then its `done` marker.
  - The sleeping member waits, with a 60 s deadline and a 10 ms poll as the
    existing fixtures do, for the busy member's `done` marker, then sleeps
    1.0 s. In parallel mode its lifetime therefore contains the busy member's
    reap.
  - Assertions on the report rows:
    - the busy member's CPU is at least 1.0 s, because the grandchild alone
      spent that. This fails a runner that misses descendants, reports its own
      CPU, or reports user time only (the spin is about 57 % system time on
      darwin);
    - the busy member's CPU is at most its wall time plus 0.1 s of rounding,
      because one process at a time can never run longer than the wall clock;
    - the busy member's CPU is at least half of the share times its wall time.
      This is "close to wall", scaled by the CPU the host actually gave the
      member, so steady host load moves both sides together. On an
      idle darwin host the share was 0.85 to 0.95 and the runner's ratio 0.85
      to 0.91;
    - the sleeping member's CPU is at most a quarter of its wall time ("well
      below"). Its wall time is at least 1.0 s by construction, and its CPU is
      interpreter and unittest start-up, about 0.02 to 0.05 s. In parallel mode
      a runner that took `RUSAGE_CHILDREN` deltas would charge the busy
      member's 1.0 s to the sleeping member and fail here;
    - the summary's `cpu=` is at least 1.0 s and within 0.15 s of the two
      rows' sum, the rounding of three printed figures.
  - The two runs together take about 5 s of wall time and 2 CPU-s.
- **Existing tests.** The `ROW` and `SUMMARY` patterns gain the new fields; the
  report and cap tests are otherwise unchanged. The four interrupt tests
  already exercise the serial interruptible wait (D2) and must stay green
  unchanged.
- This test is the suite runner's only assertion on elapsed time (436 D9 kept
  them out), because the criterion is a CPU-to-wall comparison. No bound rests
  on how loaded the host is: the CPU floors are reached by spinning on CPU
  time, the sleeping member's ceiling only loosens as load stretches its wall,
  and the busy member's ratio floor scales with the share it measured itself,
  leaving a 2x margin for load that changes during its own start-up.
- The PR's CI run is the Linux check of D1: if Linux's `wait4` left the
  grandchild out, the busy member's 1.0 s floor fails there.

## Out of scope

- Acting on the measurement: tmpfs temporary directories, fewer process
  starts, fewer fsyncs, faster or split modules.
- Scheduling across agents or by host load, and an adaptive cap
  (`.agents/knowledge/rejections/host-contention-scheduling.md`).
- CPU on the end lines, a ratio or utilisation column, memory or I/O counters,
  and a machine-readable timing file.
- Counting descendants that a member never waited for.
- CI changes, and recording a CPU baseline from CI, which belongs to the
  follow-up speed issue.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A member's CPU is `ru_utime + ru_stime` from one `os.wait4` on its pid, made by the single reap function both modes use; it covers the member and every descendant reaped beneath it, a never-launched member reports `0.0`, and descendants never waited for are not counted. | The issue asks for user plus system with children included; the suite's modules run their work in subprocesses; darwin probe (grandchild's 1.0 s counted); standard-library-only package (agent-helpers). | `RUSAGE_CHILDREN` deltas around each member (charge concurrent members to each other in parallel mode); `psutil` (not standard library); `/proc` sampling (Linux-only, misses exited descendants). |
| D2 | Parallel workers read output to its end, then reap. Serial mode waits with `os.waitid(WEXITED \| WNOWAIT)`, which reaps nothing, and reaps after with SIGINT held by `_HeldSigint`, so an interrupt can never lose a member's status or CPU. | 436 D12/D14 SIGINT discipline; signals reach the main thread only; darwin probe (`waitid` interrupted with the member unreaped, then reaped with its rusage); the-bar truthful terminal states. | `wait4` as the interruptible wait (an interrupt after the reap loses the status, and the re-wait raises `ChildProcessError`); running serial mode on worker threads (restructures the serial path and its interrupt tests for a reporting change); `RUSAGE_CHILDREN` deltas in serial mode only (two homes for one measurement). |
| D3 | Rows become `<wall>s wall <cpu>s cpu <state> <member>`, both `{:7.1f}`, still sorted by wall; the summary appends `cpu=<total>s`, the sum of unrounded member CPU; header, failed and end lines unchanged. This amends the 436 D6 contract by one field on the row and one on the summary. | The issue's "CPU column next to wall" and "suite total"; no program parses the summary, and prefix greps for `failed=0` keep matching; YAGNI. | Labels in the header only (a grepped row loses its meaning); CPU after the member path (not a column); CPU on end lines or a ratio column (not asked, derivable); a separate total line (a second closing line to cite). |
| D4 | The AC test runs a busy member (grandchild spinning to 1.0 s of its own CPU) and a sleeping member (waits for the busy one, then sleeps 1.0 s) in both modes and asserts: busy CPU at least 1.0 s, at most wall plus 0.1 s, and at least half of its self-measured share times wall; sleeper CPU at most a quarter of wall; `cpu=` within rounding of the rows. | AC ("sleeps … well below", "busy-loops … close to wall"); the-bar tests that can fail; host load is not scheduled (rejection record, recorded load 71 on 10 cores), so no bound may depend on it. | A fixed ratio threshold (fails on an oversubscribed host); a wall-clock spin (under load its CPU falls below any fixed target); mocking `os.wait4` (asserts calls, not behaviour); one mode only (both reaping paths change). |
| D5 | D2's serial reap hold gets its own interrupt test: a `python -c` wrapper replaces `os.wait4` with one that raises SIGINT right after the first real reap, and a serial run whose first member exits 3 must exit 130 with that member's `failed exit=3` end line. So the runner calls `os.wait4` and `os.waitid` as `os` attributes, and the checks in `InterruptTest.finish_interrupted` move to an `interrupted_lines` helper that returns the lines. | the-bar tests that can fail: none of the four interrupt tests lands a SIGINT between reap and record, so a runner without the hold passes them; plan-phase prototype (without the hold this test fails with `ChildProcessError`, exit 1); the 436 D14 wrappers `STARTUP_INTERRUPT` and `SERIAL_LAUNCH_INTERRUPT`. | Relying on the four existing tests (cannot fail on the window); a SIGINT sent by the test on a timer (races the reap). |
| D6 | In the serial interrupt path one hold spans the reap, when one is still needed, and the end line, so a second SIGINT held there is re-delivered only after the end line is written. A second SIGINT during that path's `waitid` still stops the runner at once, as `Popen.wait` does today. | D2: the hold "re-delivers a held interrupt only after the result is recorded", and "every started member still gets its end line"; on the interrupt path the end line is the record. | Releasing before the end line (a held second SIGINT then drops it, so the hold protects nothing); no hold on the interrupt path (contradicts D2's held reap). |
| D7 | D6's interrupt-path hold gets its own test: a `python -c` wrapper raises SIGINT after the first real `os.waitid` (member exited, unreaped) and again after the interrupt path's real `os.wait4`; the run must exit 130 with the member's `failed exit=3` end line and no report. | Phase-5 Codex plan review PR-01: no existing or planned test sends a second SIGINT, so removing D6's hold, or releasing it before the end line, passes every test; the-bar tests that can fail. | Relying on D5's single-interrupt test (it binds the result before the interrupt path, so it never exercises that hold); a timer-driven second SIGINT (races the reap). |
