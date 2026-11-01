# Turn off git background maintenance in the suite's children — issue 496

Design for https://github.com/fagenorn/nix-config/issues/496. Base: `8d0bbc25`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#436 Dn" cites
`2026-10-26-issue-436-parallel-workflow-tests-design.md`.

## Triage

Input: `{"signals": {"contract_change": {"value": "doubt", "evidence": "the suite runner's documented child environment (python/README.md) gains two git config entries; no public CLI, schema or helper contract changes"}, "concurrency_or_persistence": {"value": "no", "evidence": "the change sets git config through child environment variables; it adds no locking or persisted state, it removes a racing background process"}, "open_design_questions": {"value": "doubt", "evidence": "GIT_CONFIG_COUNT vs GIT_CONFIG_PARAMETERS, and how to coexist with tests that set their own GIT_CONFIG_COUNT, is phraseable with a defensible default"}, "criteria_shape": {"value": "no", "evidence": "two acceptance criteria, both checked deterministically: a trace2 unit test and the CI suite job"}}, "paths": ["python/agent_tools/suite_runner.py", "tests/test_suite_runner.py", "python/README.md"]}`
Verdict: `{"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`just agent-workflow-tests` runs its members in parallel (#436). Many tests
build throwaway git repositories and commit in them. Git's built-in default
makes every `git commit` (and a `fetch`, among other commands) start a
detached `git maintenance run --auto`, which briefly creates
`.git/objects/maintenance.lock` in that repository. Fixtures point global and
system config at `/dev/null`, which does not help: maintenance on commit needs
no config at all. Under parallel load the detached process runs late, and a
test that snapshots its repository meets a file that vanishes under it. That
happened as a `FileNotFoundError` on `maintenance.lock` in the
orchestrate-control refusal-table test during the #436 PR run.

The maintainer wants automatic maintenance and automatic gc off for every git
repository a test creates, set once for all suite children rather than fixture
by fixture, and a test that proves a commit under the runner starts no
maintenance child.

Measured on this host's git 2.51.2 while designing (scratch probes):

- A commit with global and system config nulled records a trace2
  `child_start` for `git maintenance run --auto --quiet --detach`, written by
  the committing process before it returns.
- `maintenance.auto=false` stops that spawn; `gc.auto=0` alone does not.
- Set through `GIT_CONFIG_COUNT`, the entries are lost for any child whose
  test sets its own `GIT_CONFIG_COUNT`: the count and key slots are replaced,
  and maintenance spawns again. `test_review_task7` commits under such a
  hostile count of 7 today. Set through `GIT_CONFIG_PARAMETERS`, they compose
  with a test's own `GIT_CONFIG_COUNT` and still stop the spawn.
- A push to a local repository spawns maintenance in the receiving
  repository under either variable: git removes every `GIT_CONFIG_*` variable
  from the receive-pack it starts on the far side of a local transport.

## Solution

`agent_tools.suite_runner` launches every member with the runner's own
environment plus two git configuration entries, `maintenance.auto=false` and
`gc.auto=0`, appended to `GIT_CONFIG_PARAMETERS` exactly as `git -c` would
append them. Every git command a member runs with its inherited environment
then behaves as if invoked with `git -c maintenance.auto=false -c gc.auto=0`,
so a commit in a fixture repository starts no maintenance process and no lock
appears. Fixtures need no edit. The runner's contract in the package README says what the members'
environment now carries and where it does not reach. A new runner test proves
the absence through git's own trace, against a positive control that shows
the same harness does record a maintenance child when the setting is absent.

## Decisions

**The members' environment.** The runner computes the members' environment
once per run from its own environment by one importable, pure function, and
passes that mapping explicitly as the environment of every member it launches
in serial and in parallel mode. The runner's own process environment is not
modified, and the function never mutates the mapping it is given. Every
inherited variable passes through unchanged except `GIT_CONFIG_PARAMETERS`
(D1).

**Composition.** The function appends `'maintenance.auto'='false'
'gc.auto'='0'`, the form `git -c` itself exports, to the inherited
`GIT_CONFIG_PARAMETERS`, joined by one space when the inherited value is
non-empty and standing alone otherwise; a leading space is a parse error for
git. The suite's entries come last, so they win over an inherited entry for
the same key, and because `GIT_CONFIG_PARAMETERS` outranks `GIT_CONFIG_COUNT`
and every config file, they also win over a test's own count entries and a
fixture's repository config. A test's own `GIT_CONFIG_COUNT` entries, and
`git -c` options any command adds, still apply alongside them (D2).

**Failure.** The runner does not parse or validate an inherited
`GIT_CONFIG_PARAMETERS`. A value git cannot parse already fails every git
call with exit 128 (`bogus format in GIT_CONFIG_PARAMETERS`) whether or not
the runner appends to it, so the run fails loudly in the members that use git,
and nothing passes silently.

**Reach.** The setting reaches every git process that inherits a member's
environment, at any depth. It does not reach a child a test launches with an
environment built from scratch or with its own `GIT_CONFIG_PARAMETERS`, nor
the receive-pack of a push to a local repository, which git starts with every
`GIT_CONFIG_*` variable removed, so the receiving repository still runs
automatic maintenance. These limits are stated in the runner's README
contract and are not closed here (D3).

**The README contract.** The runner paragraph's "with the recipe's
environment" becomes the recipe's environment plus the two entries, with one
sentence giving the reason (a detached maintenance run creates
`maintenance.lock` while a test reads its repository), the composition with
`GIT_CONFIG_COUNT` and `git -c`, and the reach limits above. The closing rule
on shared state (own temporary location, never a serial-exemption list, retry
or lock) stays as written.

## Test seams

The seams follow #436 D9: runner tests drive
`python -m agent_tools.suite_runner` end to end over fixture members written
into a temporary working directory, and import a pure function directly only
where its behaviour is the subject (as `report_lines` is). All of them live in
the existing runner test module, already a suite member; the recipe's member
list does not change (D4).

These tests themselves run under the suite runner, so the test process
already carries the suite's entries and would hand them to anything it
launches. Every environment these seams build therefore starts from the
test's own with all command-scope git configuration removed
(`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and its key and value
variables); otherwise a runner that adds nothing would still pass.

1. **The composition function, observed through git.** Each case builds a
   parent mapping, calls the function, and asks git (`git config --get` in a
   scratch directory with global and system config nulled) what it reads
   under the returned environment. Each case fails for one wrong composition:
   with no inherited value, `maintenance.auto` is `false` and `gc.auto` is
   `0`; with an inherited non-empty value, its own entry still reads (fails
   an overwrite); with an inherited empty value, git parses the result (fails
   a bare space join); with an inherited `maintenance.auto=true`, the suite's
   `false` wins (fails a prepend); with a test-style `GIT_CONFIG_COUNT` entry
   laid over the returned environment, as `test_review_task7` does, the
   suite's entries still read (fails a count-based composition). Every other
   variable comes back unchanged and the parent mapping is unmodified.
2. **A commit under the runner starts no maintenance child (AC1).** A
   fixture member creates a repository in its own temporary directory, with
   global and system config nulled and a fixed identity, and commits with
   `GIT_TRACE2_EVENT` set to an absolute file the test names. The test runs it
   through the runner once with `--jobs 1` and once with `--jobs 2`, so each
   launch site is covered by a test that fails only for that site. Each run
   must exit 0, its trace must hold the commit's own `start` event (the trace
   was written by that commit, so the negative is not vacuous), and no trace
   event's argv may hold the element `maintenance`.
3. **Positive control.** The test runs the same member file directly, not
   through the runner, with `maintenance.autoDetach=false` added to the
   stripped environment, and requires a `child_start` event whose argv
   begins `git maintenance run --auto`. With detach off the maintenance run
   finishes before the commit returns, so no process outlives the member and
   writes into a directory being removed. Seams 2 and 3 differ only by the
   runner, and the control fails on a git that does not run maintenance on
   commit, in which case seam 2 would prove nothing.

No test asserts that `maintenance.lock` is absent after the commit: the lock
exists only while maintenance runs, so a post-hoc check passes whether or not
maintenance ran. The trace is the measurement AC1 names.

**AC2** is the advisory Agent Workflow Tests job at the PR head, read per
#436 D15: the run's observation record with suite `success` and the
`failed=0` summary line, not the job's colour.

## Out of scope

- **Per-fixture edits.** No fixture, test-support helper or hostile-config
  test changes; `test_review_task7` and `test_review_history` keep their own
  `GIT_CONFIG_COUNT` and compose with the suite's entries (D2).
- **The receive-pack of a local push** and children given a from-scratch
  environment (D3). If a test that reads a repository after pushing into it
  ever races, that fixture gives the receiving repository its own
  configuration; no such failure is known.
- **The justfile recipe, the Nix configuration, the command table and the CI
  workflow.** The runner has no command-table row (#436 D1), and the recipe,
  its pinned first line and its member list stay as they are.
- **A runner option or environment variable** to turn the setting off. The
  runner keeps `--jobs` as its only option (#436 D4).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The runner sets the entries for every member at both launch sites, through one importable pure function of its environment whose result it passes as each member's environment; it leaves its own `os.environ` alone. | Issue ("set once for all suite children rather than per fixture"); agent-helpers rule 2 (policy in importable functions); #436 D1 and D4 (the runner owns member launch, no environment knob). | Setting variables in the recipe line (a direct `python -m agent_tools.suite_runner` run misses them, appending to an inherited value is not expressible there, and the line is pinned by the recipe-wiring test); mutating `os.environ` in `main` (a side effect no unit seam observes); a per-fixture helper (what the issue rules out). |
| D2 | Append `'maintenance.auto'='false' 'gc.auto'='0'` to `GIT_CONFIG_PARAMETERS` as `git -c` does (one space only after a non-empty inherited value), suite entries last; `maintenance.auto=false` is the entry that stops the spawn and `gc.auto=0` is the issue's auto-gc ask. | Probes on git 2.51.2: suite entries in `GIT_CONFIG_COUNT` are replaced by a test's own count and maintenance spawns (`test_review_task7` commits under a count of 7), while `GIT_CONFIG_PARAMETERS` composes with it; `git -c` exports this exact form; `gc.auto=0` alone does not stop the spawn. | `GIT_CONFIG_COUNT` appended after an inherited count (git-config(1) documents it for scripts, but any test setting its own count silently drops the suite's entries for that child, and appending needs an inherited count parsed and validated); overwriting `GIT_CONFIG_PARAMETERS` (discards a caller's `-c` configuration). Accepted cost: `GIT_CONFIG_PARAMETERS` is git's undocumented `-c` transport, and a format git stopped reading would fail every git call loudly, never silently. |
| D3 | The setting's reach is the members' inherited environment; a from-scratch environment, a test's own `GIT_CONFIG_PARAMETERS` and the receive-pack of a local push stay outside it, documented in the README contract rather than closed. | Probe: a push to a local bare repository spawns maintenance in the receiving repository under either variable, because git strips `GIT_CONFIG_*` for that receive-pack; AC1 measures a commit; the issue's mechanism is environment config. | A suite-wide `GIT_TEMPLATE_DIR` carrying the config (replaces git's default template directory in every fixture repository, gives the runner a directory to create and remove, and still misses `--template` and copied repositories); editing each pushing fixture now (per fixture, and no race is known there). |
| D4 | AC1 is proved end to end per launch mode: a fixture member commits with `GIT_TRACE2_EVENT`, the trace must hold the commit's `start` event and no event naming `maintenance`, beside a positive control that runs the same member outside the runner with `maintenance.autoDetach=false`; every environment the tests build has command-scope git config removed first, because the test process already runs under the suite runner; the composition function is tested by asking git what it reads; no lock-file assertion. | The-bar "tests that can fail" and observable behaviour; #436 D9 (end-to-end over fixture members) and D15 (evidence must be able to fail); the issue's AC1 measurement. | Inheriting the test's environment unstripped (the outer runner's entries reach the member, so a runner that adds nothing still passes); asserting the exact `GIT_CONFIG_PARAMETERS` string (pins a format, not what git reads); one mode only (the other launch site could drop the environment unnoticed); checking that `maintenance.lock` is absent afterwards (passes whether or not maintenance ran); a detached control (leaves maintenance writing into a directory the test is removing, the race itself). |
| D5 | (Plan.) `member_environment(parent: Mapping[str, str]) -> dict[str, str]` beside a `SUITE_GIT_CONFIG` constant holds the composition; `run_suite` computes it once from `os.environ` and passes it to `_run_serial` and `_run_parallel`, so `run_suite`, `main` and the CLI keep their signatures. The new end-to-end cases strip command-scope git config through an `environment` override on their own `RunnerCase` subclass, using one module-level helper the composition cases share; the existing runner cases keep their environment. | D1 (computed once from the runner's own environment); #436 D4 (`--jobs` the only option); D4 (strip first); planning trial at `0518859a`: each wrong composition failed only its case, dropping `env=` at one launch site failed only that site's case, and without the override the control failed under the runner. | An `environment` parameter on `run_suite` (a second way to set the members' environment that no caller needs); stripping in `RunnerCase.environment` for every case (changes the environment of cases that never run git, for no assertion). |
