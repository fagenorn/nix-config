# workflow-state validates artifact budgets in-process — issue 498

Design for https://github.com/fagenorn/nix-config/issues/498 (parent
https://github.com/fagenorn/nix-config/issues/436). Base: `a731801d`
(`origin/main`). A bare "Dn" cites this spec's ledger; "pkg Dn" cites the
ledger of `2026-09-24-agent-tools-package-design.md`; "472 Dn" cites issue
472's.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "artifact-budget CLI and workflow-state argv, verdicts, exit codes and error text stay unchanged; only the internal call path moves in-process"}, "concurrency_or_persistence": {"value": "no", "evidence": "validation is a pure function of report bytes and policy; no ledger state shape or locking changes"}, "open_design_questions": {"value": "doubt", "evidence": "how workflow-state loads artifact_budget in-process (file-path load per existing _delivery/_host_admission precedent vs agent-helpers standard rule 3) and how the CLI main is split into a reusable core"}, "criteria_shape": {"value": "hit", "evidence": "AC2 is post-merge CI timing evidence that no deterministic code check verifies"}}, "paths": ["home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/artifact_budget.py", "home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_artifact_budget.py"]}

Verdict: {"hits":["open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}

ran: full (shadow)

## Problem

Every time `workflow-state` checks a report, a detail input or a review
package against the artifact budget, it starts the artifact-budget CLI as a
child Python process: a ship summary, a ship checkpoint, a terminal result, a
`control` reply before it commits, a retained or durable detail. Each child
pays interpreter start-up, re-imports its dependencies and recompiles the
~1,200-line validator, because a script run as `__main__` is never served from
the bytecode cache. One run of the agent workflow suite starts about 2,700 of
these children; in `test_workflow_state`'s lifecycle class alone they cost
27 s of 87 s. Production pays the same per call, only less often. The
validation itself is a pure function of the input bytes and the policy, so the
process boundary buys only crash isolation, which D4 keeps.

## Solution

`artifact_budget` gains one importable core, `invoke`, that does everything
the CLI does after it receives its arguments and returns the result as a value
instead of writing it to the process streams. The CLI's `main` becomes
`invoke` plus its two stream writes, so the CLI and every in-process caller share one
code path and cannot drift (D3).

`workflow-state` loads `artifact_budget` once per process, from the same file
the CLI would have run, and calls `invoke` with the argument list it used to
pass to the child (D2). Both of its call sites keep their verdict mapping and
error texts verbatim; only the transport changes (D1, D4).

A workflow-state validation now starts no child process. Verdicts, the values
accepted reports yield, exit codes and error text are unchanged, and the CLI
itself is unchanged for every other caller.

## Decisions

### The shared core (D3)

- **`Outcome`** is a frozen value with three members: `exit_code` (int),
  `stdout` (bytes) and `stderr` (text). It is exactly what one CLI run
  produces.
- **`invoke(argv, read_stdin) -> Outcome`** takes the argument list without
  the program name and a `read(size) -> bytes` function, called once and only
  for `--input -`, so a command that reads no stdin never touches it, as
  today. It holds everything `main` does today: argument parsing (whose errors already
  raise the module's own error type), the policy load and identity check,
  `describe`, `check` (exit 0 within budget, 3 over), the wire-bounded
  no-follow input read, the boundary validators, canonical output, and the
  refusal line `artifact-budget: <label>: <reason>` with exit 2 (472 D1, D2).
  It writes to no process stream and never exits. The one exception is
  argparse's `-h`/`--help` action, which prints and exits as it does today;
  `workflow-state` never builds it.
- `invoke` catches what `main` catches today, the module's own error type,
  and nothing more. Any other exception propagates out of it, so the CLI
  still exits 1 with a traceback where it does today.
- **`main(argv=None)`** calls `invoke` with `sys.argv[1:]` (or `argv`) and a
  function that reads the process's binary stdin when called, writes `stdout`
  bytes and `stderr` text, and returns `exit_code`. The refusal helper returns
  an `Outcome` instead of writing, and the input reader calls the function it
  is given rather than reading `sys.stdin`.
- The CLI's argv, exit codes, stdout bytes and stderr line are unchanged.

### Loading the module in-process (D2)

- The layout detection and policy resolution `workflow-state` uses today stay
  (#337 D38), including passing the policy's resolved target, because the
  validator refuses a symlinked `--policy`. What the resolver returns changes
  from the CLI's command line to the module file:
  - source layout (`artifact_budget.py` beside the resolved script and the
    policy in its parent): that `artifact_budget.py`;
  - otherwise `~/.agents/lib/python/artifact_budget.py`, the file the
    installed `artifact-budget` wrapper executes, by the same unresolved path,
    so the module's `__file__`-based choice of delivery model matches the
    wrapper's run. The lookup of a wrapper beside the script, else in
    `~/.agents/bin`, goes: `workflow-state` no longer runs the wrapper, and
    every wrapper ran that file.
- The module is loaded from that file under a private module name that is
  registered in `sys.modules` before the module executes and removed again if
  execution fails. Registration is required: the module defines dataclasses
  under postponed annotations, and loading it unregistered fails with an
  `AttributeError` at class creation. The loader is the bytecode-cached file
  loader: at most one compile per process, none once the cache is warm.
- It is loaded on the first validation and kept for the rest of the process;
  the suite's in-process harness re-executes `workflow-state` per invocation,
  so there it is once per invocation, from the cache. A subcommand that never
  validates never loads it, so a broken validator cannot break unrelated
  subcommands, as before.
- No interface-version handshake: in both layouts the module comes from the
  same tree or the same home-manager generation as `workflow-state`, so
  nothing can vary across a handshake (pkg D12), and agent-helpers rule 3
  forbids adding one.
- A load failure is a `WorkflowError` reading `artifact-budget module:
  <cause>`, exit 2, following the delivery runtime's and host admission
  library's loaders (D4).
- The module's own delivery-model loader now runs in `workflow-state`'s
  process. Its private module name differs from the one the delivery runtime
  registers for the same package, so the two never collide.

### One invocation helper and its outcomes (D1, D4)

- One `workflow-state` helper runs an artifact-budget invocation in-process:
  it appends `--policy <resolved target>` when a policy resolved, as the
  argv builders do today, calls `invoke` with a reader over the input bytes
  (over no bytes for a file input) and returns the `Outcome`.
- Both call sites use it in place of `subprocess.run` and keep their logic:
  - the report and detail-input validator still treats a non-zero exit or
    empty stdout as `artifact-budget <command> rejected the <boundary>
    boundary` (or `... the detail input`), then parses the canonical stdout
    and keeps its `invalid canonical JSON` and `non-object` refusals;
  - the durable-detail check still reads a non-zero exit as `durable detail is
    not a checker-valid review package`, then requires a `review-package`,
    `within_budget` result.
- An exception that escapes `invoke` becomes an `Outcome` with exit code 1,
  empty stdout and the formatted traceback as `stderr`: what the crashed child
  left in the captured result before. Each caller therefore reports the
  refusal text it reported then. `BaseException`s that are not `Exception`s
  (interrupts, exits) propagate. The child also kept a validator crash out of
  `workflow-state`; this mapping keeps that for exceptions, and the wire bound
  already caps what a report can make the validator do.
- The value an accepted report yields is still the parsed canonical stdout,
  with its keys sorted, not the caller's input object.

### What "same verdict and error text" means here (D1)

For the same bytes and policy:

1. `workflow-state` accepts exactly when the CLI exits 0 with non-empty
   stdout, and continues with that stdout parsed.
2. A refusal reaches the user with the exit code and `workflow-state:` line it
   produced before. That line never carried the CLI's refusal reason, and it
   still does not.
3. `invoke` returns the same exit code, stdout bytes and refusal line the CLI
   process prints.

The in-process path runs under `workflow-state`'s interpreter, not the
`python3` on `PATH` that the wrapper uses. The module is standard-library
only and its verdicts do not depend on the interpreter. Only a refusal
reason's wording could differ across Python versions (JSON decode messages),
and `workflow-state` never shows the reason. Python's recursion limits now
apply at a deeper stack; only input nested far deeper than any shape a
boundary accepts reaches them, and such input is refused either way, with the
same text.

### Documentation

The installed-file entry for `~/.agents/lib/python/artifact_budget.py` gains a
comment naming its second consumer, `workflow-state`'s in-process load, as
the host admission entry already names its own. No other living document says
`workflow-state` runs the CLI; the point-in-time package design keeps its
wording.

## Test seams

Three seams, all inside `just agent-workflow-tests` (D5).

- **The core against the CLI** (`test_artifact_budget.py`, beside its existing
  subprocess runs of the CLI). A table of argv and input pairs, one row per
  exit and label branch: an accepted report, a schema-refused report, a report
  over the wire bound, an unreadable detail input (`cannot read`), an argparse
  refusal (`invalid input`), and `check` within and over budget (exit 0 and
  3). For each row, `invoke` and a `sys.executable` run of the source script
  return the same exit code, stdout bytes and stderr text. A second test calls
  `invoke` while the process's stdout and stderr are redirected to buffers and
  asserts both stay empty: `workflow-state` prints its own reply after a
  validation.
- **workflow-state spawns nothing** (`test_workflow_state.py`, a new class on
  the lifecycle harness). A `sys.addaudithook` hook records the
  process-creation events (`subprocess.Popen`, `os.posix_spawn`, `os.exec`,
  `os.fork`, `os.spawn`, `os.system`). An audit hook cannot be removed, so it
  is installed once per test process and records only inside a test's
  recording window; it costs well under a millisecond per invocation (about
  700 events, each one flag check). Inside the window the harness drives the
  legacy `finish --result-file` subcommand, whose only child before this
  change was the validator and which issues all three commands: the result
  file at the `ship-summary` boundary, a `present` detail through `check`, and
  an `unpublished` detail through `validate-detail-input`. Each runs once with
  an input the validator accepts and once with one it refuses, reusing the
  fixtures of the existing present- and unpublished-detail tests. The test
  asserts no recorded event, and compares each outcome with the CLI's verdict
  on the same bytes and policy, which it computes outside the window. A
  refusal must carry the exact `workflow-state` text and exit code listed
  above; an acceptance must commit the finish.
- **Installed layout** (`ArtifactBudgetPolicyResolutionTest`). Its probe, a
  `sys.executable -c` child, gains the same hook and asserts no
  process-creation event while it validates a terminal result through the
  installed layout. The fixture stops installing
  the `artifact-budget` wrapper, so the test proves `workflow-state` needs
  only `~/.agents/lib/python`.

The existing exact-byte pins stay unchanged and act as the regression net: the
rejected `control` reply in `test_delivered_control`, and the lifecycle
classes' refusal texts.

## Acceptance and evidence

- **AC1 [code]** is met by the second and third seams (no child, verdict and
  text parity), with the first seam proving the core's parity with the CLI.
- **AC2 [evidence]** cannot be shown on the branch. Ship carries it: the
  suite runner's timing table on the merge commit's push to `main` (Agent
  Workflow Tests (advisory), hosted ubuntu-24.04, default worker cap), with
  summed module seconds at least 200 s below the last push to `main` before
  the merge (2,033 s on run 41314186007 when the issue was filed). The branch
  proves only the cause: no validator child is started. Locally, on a heavily
  loaded host, an in-process validation measured about a twentieth of a
  spawned one; that is direction, not acceptance (D6).

## Out of scope

- Moving `artifact_budget` or `workflow-state` into the `agent_tools`
  package. Their cluster move deletes this loader with the other legacy
  loaders, the wrapper and `~/.agents/lib/python` (pkg D12, D16).
- Other callers of the `artifact-budget` CLI (the orchestrate control loop,
  review budget, ship-delivery compile, the skills, and the CLI cases in
  `test_artifact_budget.py`). They keep spawning it.
- Any change to the CLI's argv, output, exit codes or refusal lines.
- Caching the delivery model or the argument parser across in-process calls,
  or changing the delivery-model loader's reload-per-call behaviour (D6).
- Surfacing the CLI's refusal reason in `workflow-state`'s messages.
- The notes-limit read of the policy, which is already in-process.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Every validator invocation `workflow-state` makes (`validate-report`, `validate-detail-input`, `check`) runs in-process. "Same verdict and error text" means: unchanged accept/refuse, accepted value, exit code and `workflow-state:` line, plus a core whose outcome is byte-equal to the CLI process | Issue 498 body ("verdicts, exit codes and error text are unchanged"); `workflow-state`'s refusal lines never carried the CLI reason | Only `validate-report`, the children the issue counted: it leaves the durable-detail check spawning on a second code path. Surfacing the CLI reason: changes the error text the issue fixes |
| D2 | Load the same file the CLI runs (source `artifact_budget.py` or `~/.agents/lib/python/artifact_budget.py`) through the bytecode-cached file loader, registered under a private `sys.modules` name, lazily, once per process, with no version handshake | Host-admission loader precedent; agent-helpers rule 3 binds a legacy script at its cluster move; pkg D12 (same-generation files, so skew is impossible); measured: an unregistered load fails on the dataclasses | Moving `artifact_budget` into `agent_tools` now: a cluster move (wrapper, lib copy, its own delivery-model loader, many CLI callers) beyond this issue. `runpy` as the delivery runtime uses it: recompiles the source on every load, the very cost removed here |
| D3 | The core is `invoke(argv, read_stdin) -> Outcome`, with stdin a lazily called reader, and `main` is `invoke` plus stream writes; `workflow-state` passes the argv it passed the child | Agent-helpers rule 2 (thin command shell over importable functions); DRY, so one dispatcher serves both paths and parity holds by construction | A typed per-operation API: a second dispatcher that must keep agreeing with `main`'s labels and exit codes, and it belongs to the cluster move's split. Calling `main` under patched `sys` streams: swaps the process-global streams `workflow-state` writes its own reply to |
| D4 | An exception escaping `invoke` becomes an outcome with exit 1 and empty stdout, so callers keep their texts. A load failure is a distinct `artifact-budget module: <cause>` (exit 2) | Issue: error text unchanged, since the crashed child read as a refusal; the bar's fail-loud and truthful-states rules; the `_delivery`/`_host_admission` load-error shape | Letting it propagate: `workflow-state` would print an `OSError` line or crash with exit 1, which changes exit code and text. Reporting a load failure as `rejected the … boundary`: presents an install fault as a report refusal |
| D5 | Prove "no child" with a process-creation audit hook: installed once in the test process and gated to a recording window around the legacy `finish` subcommand (all three commands, accepted and refused), and inside the installed-layout probe with no wrapper installed; plus an `invoke`-vs-CLI parity table | The bar's "tests that can fail" (observe the behaviour, not a call); the lifecycle harness and installed-layout probe are prior art; measured at about 700 audit events per invocation | Mocking `subprocess.Popen`: misses `os.posix_spawn` and the rest, and asserts a call. A canary `artifact-budget` on `PATH`: the source layout never ran it, so the test passes against the old code. A probe interpreter per case: it rebuilds the harness's ledger setup in a child for no stronger proof |
| D6 | AC2 is post-merge evidence that ship carries. The remaining per-call in-process costs (delivery-model reload, parser construction) stay | Issue AC2 wording; YAGNI, since a local measurement put in-process at about a twentieth of a spawn | Caching the delivery model or parser now: it changes the validator's reload semantics for every caller, for a saving the 200 s threshold does not need |
| D7 | Reverses D2's "same unresolved path": the loader loads the resolved target of the module file, resolving inside its own `try` so a missing file is a load failure while `artifact_budget_paths` stays non-raising. The installed-layout probe pins it with the module linked into a stand-in store: the loaded `__file__` is the target, and no `artifact_budget` bytecode appears in `~/.agents/lib/python/__pycache__` | Nix store files all have mtime 1, so CPython's timestamp bytecode check reduces to size; at plan time a same-size, mtime-1 swap behind a link served the old bytecode from the link's `__pycache__`, and `~/.agents/lib/python/__pycache__` already holds `artifact_budget` bytecode. A store file's name changes with its content, its directory is read-only, and its parent is never `scripts`, so the delivery model is still the installed one the wrapper uses | The unresolved link: after a same-size edit `workflow-state` would validate with the old code while the CLI runs the new, breaking AC1 parity. Compiling the source uncached in the installed layout: a second load path beside the cached loader. Resolving inside `artifact_budget_paths`: a missing module would break `phase_notes_maximum` and every subcommand that reads only the policy |
| D8 | Pin D4's exception mapping with a fourth in-process test that patches the loaded module's `invoke` to raise, asserting exit 1, empty stdout, the traceback on stderr, the boundary's refusal text and no process started | Phase-5 Codex plan review PR498-S1: the three `finish` cases never reach the `except Exception` arm, so removing it would stay green. Probed at review time: on Python 3.13 the CLI refuses an 8,000-deep JSON array as invalid JSON without a `RecursionError`, and the 8,192-byte report wire bound caps the depth | The reviewer's deeply nested JSON trigger: it does not crash the validator within the wire bound on the supported interpreters, so it would test nothing. Leaving the arm untested: a regression in crash parity would pass the suite |
