# Launch-scope exec and reap (#276)

Slice S2 of the [launch process reaping design](2026-10-06-launch-process-reaping-design.md)
(cited below as "parent Dn"). The parent settles the mechanism: one
`launch-scope` command (parent D3), a host-local registry (parent D2),
proof before signalling (parent D4), a row written before the liveness check
(parent D5), owner self-reap and adapter sweep (parent D6), and adoption through
a sentence beside the `Lifecycle worker:` line (parent D7). This spec pins the
concrete interface S2 ships.

## Problem

A lifecycle agent that is stopped, superseded or expired mid-command leaves its
background processes running. They are reparented to PID 1, the host's
task-stop never reaches them, and nothing in the pipeline knows they exist. The
superseded-owner stop pass (#275) ends the agent but not its processes.

## Solution

1. **`launch-scope exec`** runs one long command in a new session whose
   processes carry the launch's marker, records the group in the registry, and
   kills whatever the command left behind when it returns.
2. **`launch-scope reap`** kills every process a launch left, by `--action-id`
   (the owner, on itself) or `--sweep` (the adapter, for every non-current
   launch of the run).
3. **Skill wiring.** from-issue owners run long commands through `exec` and
   reap themselves before every exit write. Writing workers get one sentence
   after their `Lifecycle worker:` line. The orchestrate-issues stop pass ends
   with a sweep.

`scratch` is not part of this slice (D1).

## Decisions

### Command surface

The module is `agent_tools.launch_scope`, with one command-table row,
`launch-scope`. It reaches `workflow-state`, `git` and `ps` by name on `PATH`.
Both verbs take `--repo-root <ledger_repo_root> --run-id <run-id>`.

```text
launch-scope exec --repo-root R --run-id I (--action-id A | --worker-id W) -- <argv>
launch-scope reap --repo-root R --run-id I (--action-id A | --sweep)
```

`exec` takes exactly one identity (D2). `--worker-id` asks `check-worker`, and
the launch's action ID is the worker ID without its `:w<n>` suffix, the same
derivation `launch-commit` already checks. `--action-id` asks `check-launch`.

Before any path is built, the run ID and the action ID must each be one safe
path segment: `[A-Za-z0-9._:-]+`, and neither `.` nor `..`. Anything else
exits 2 (D10). The identity grammar stays with `workflow-state`, which refuses a
malformed ID when it is checked.

### Registry

The registry root is `<git common dir of R>/agent-launch/<run-id>/<action-id>/`.
The git common dir comes from `git -C R rev-parse --path-format=absolute
--git-common-dir`, and an R that git cannot answer for exits 2. Each `exec` owns
one row file, `<nonce>.json`, holding `{"nonce", "pgid", "started_at", "argv0"}`.
The nonce is 32 lowercase hex characters, and `pgid` is `null` until the child
has been spawned (D3). Rows are written through the package's single atomic
writer. `exec` deletes only its own row. The action directory is removed only by
`reap`, so a concurrent `exec` can never lose its directory.

### `exec` behaviour

1. Validate the arguments and resolve the registry. A usage error, or a
   `workflow-state` or `git` that cannot be started, exits 2 with nothing on
   stdout.
2. Write the row with `pgid: null`.
3. Check liveness. Only a reply with exactly the helper's keys and a positive
   verdict for this identity is believed. `launch-commit`'s parser covers the
   worker reply, and a sibling parser covers `check-launch`'s
   `{action_id, current, current_action_id, reason}` (D4). On any other answer,
   delete the row, start nothing, print one canonical JSON line
   `{"action_id", "started": false, "reason"}` and exit 3. The reason is the
   helper's own reason, or `check_launch_failed`, `check_worker_failed` or
   `malformed_reply`.
4. Spawn the argv in a new session, with its environment plus
   `AGENT_LAUNCH_SCOPE=<run-id>/<action-id>/<nonce>`, then rewrite the row
   with the child's pgid. Standard streams and the working directory are
   inherited. An argv that cannot be executed deletes the row and exits 127
   when the program is not found, or 126 when it cannot be run, as a shell does.
5. Forward SIGINT, SIGTERM and SIGHUP to the child's group, so that a host
   timeout's SIGTERM reaches the command in its new session, and wait for the
   child.
6. Clean up (see **Signalling**) every process that carries this exact marker,
   plus the child's group. Another `exec` of the same launch has a different
   nonce, so it is untouched. Then delete the row and exit with the child's status.
   A child killed by a signal exits 128 plus the signal number. If a process
   survives SIGKILL, the row stays for `reap`, `exec` names the survivors on
   stderr, and it still exits with the child's status (D5).

### `reap` behaviour

- `--action-id A` reaps launch A without asking the ledger, because the caller
  asserts that A is ending.
- `--sweep` lists the action directories under the run's registry root and asks
  `check-launch` about each one. It leaves current launches alone, reaps the
  launches whose reply reads `current: false`, and marks a failed or malformed
  check as skipped with `check_launch_failed` or `malformed_reply`. A launch
  that has no registry directory is never visited by a sweep. One exists for
  every launch that ever ran `exec`.
- To reap a launch, the reaper signals every process whose marker starts with
  `<run-id>/<action-id>/` followed by a well-formed nonce, plus every recorded
  group that a live member's exact marker proves. It then deletes the launch's
  registry directory. When a process survives, the directory stays and the
  launch is listed as skipped with `processes_survived`.
- The reaper prints one canonical JSON line:
  `{"reaped": [{"action_id", "signalled"}], "skipped": [{"action_id", "reason"}]}`.
  Both lists are sorted by `action_id`, and `signalled` is the count of distinct
  pids that were sent SIGTERM. The exit is 0 when `skipped` is empty, 1 when it
  is not, and 2 on a usage or helper error, with nothing on stdout (D6).
  Repeating a reap is a no-op that reports `signalled: 0`.

### Signalling

The process table is `ps -A -o pid=,ppid=,pgid=`. The reaper reads each pid's
environment through one platform seam (D7): `/proc/<pid>/environ` on Linux, and
`sysctl` `{CTL_KERN, KERN_PROCARGS2, pid}` through `ctypes` on darwin. On darwin
the buffer holds an int32 argc, the exec path, NUL padding, argc argument
strings, and then the environment strings. Any other platform exits 2. An
unreadable environment, a zombie or a vanished pid is not a proof.

- The target set is the marker-proved pids plus the members of every proved
  group. The reaper and every one of its ancestors are removed from that set.
  When a proved group contains the reaper or an ancestor, its members are
  signalled one by one instead of through `killpg`.
- Send SIGTERM, poll until the targets are gone, for at most 5 seconds, then
  send SIGKILL and poll for at most 1 second more. A target that is still alive
  after that is a survivor.

### Skill wiring

- **Owner commands.** from-issue's lifecycle identity rule gains one sentence.
  With lifecycle identity, the owner runs each long command, every verification
  command included, as
  `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> -- <argv>`,
  still in the foreground. Forge verbs are short and never go through `exec`.
  The guard already refuses a guarded verb that sits behind another program, so
  `exec` cannot carry a push.
- **Worker sentence** (D8). Wherever a prompt is composed with a
  `Lifecycle worker:` line, the next sentence reads:
  "Run each long command, every verification command included, as
  `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
  still in the foreground."
  The sites are from-issue's **Writing workers** rule, sdd's lifecycle-worker
  rule and implementer prompt, both prompts in `ship-handoff.md`, and the rule
  ship-issue uses for its own registered children. The three leaf-agent
  clauses stay byte-identical.
- **Owner exit order** (parent D6). At the handoff action, at the terminal
  return procedure and at the suspension procedure, the order is:
  release every worker, then
  `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`,
  then the exit write (`progress --handoff-path`, `finish`, `suspend`). When a
  ledger-only bookkeeper makes that write, the reap runs before the bookkeeper
  is dispatched. A reap that exits non-zero is named in the owner's result and
  does not block the exit write. A delegating controller does not reap, because
  the fresh owner adopts its launch and reaps it at its own exit.
- **Adapter sweep.** The orchestrate-issues stop pass ends by running
  `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep`
  once, after its stops and before the response's first action. That covers
  `finalize` too, which already runs the stop pass. A sweep that exits non-zero
  never blocks dispatch. The last one is listed under §5 **Stop failures** with
  its exit code and skipped launches.
- **Load ceilings** (D9). Each `instruction-load.json` profile whose files grow
  has its ceiling raised to the new byte count in the same change, with a
  "Ceiling raised for #276" note.
- **CLAUDE.md** gets one sentence about `launch-scope` in its agent-helper
  paragraph. `docs/standards/agent-helpers.md` lists no commands, so it does not
  change.

## Test seams

- **`python -m agent_tools.launch_scope`**, exercised by a new
  `tests/test_launch_scope.py` listed in `agent-workflow-tests`. The file
  follows `tests/test_launch_commit.py`. A `PATH` shim runs the source
  `workflow-state`. `LifecycleHarness` drives the ledger, and its root is made a
  git repository so the registry resolves. A superseded launch is produced the
  way the `launch-commit` suite does it: `resume(owner_unavailable=True)`. Cases
  use real processes. A child writes the pids it spawned to a file, and the test
  checks liveness with `kill(pid, 0)`, treating a zombie as dead, under a
  bounded poll. The cases cover parent S2 AC1–AC3 (AC3 uses a Python `os.setsid`
  escapee, because darwin has no `setsid` binary), worker identity and
  `released`, malformed and failed checks, a sweep that leaves the current
  launch alone, an idempotent repeat reap, and exit 127.
- **`test_workflow_skill_contracts.py`.** `assert_ordered` checks from-issue's
  three exit sites (release, `reap --action-id`, exit write), the stop pass
  (stops, `reap --sweep`, then actions), the owner `exec` sentence, and the worker
  sentence after each composed `Lifecycle worker:` line.
- **`tests/test_agent_tools_launchers.py`** covers the new row unchanged, and
  `just build` import-checks the module.

## Out of scope

- The `scratch` verb, scratch roots, worktree removal and
  `unattributed_worktrees` (S3).
- Guard refusal of `nohup`, `setsid` and `disown` (S4).
- Any `workflow-state` or ledger schema change. The registry is invisible to the
  ledger.
- Removing existing leaked processes or worktrees, Codex adapter parity (parent
  D12), and allowlisting `launch-scope` in the Claude settings.
- Detachers that scrub their environment and leave the group (parent D11).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | S2 ships `exec` and `reap` only. There is no `scratch` verb, and the reap report carries no worktree or scratch members until S3 adds them | Issue scope; parent slices S2/S3; the-bar production-grade (no placeholder fields) and YAGNI | Emitting `scratch_removed: false` and `worktrees_removed: []` now ships placeholder fields. Listing `unattributed_worktrees` without scratch roots would flag every issue worktree |
| D2 | `exec` takes `--action-id` or `--worker-id`, exactly one. A worker's action is its ID without the `:w<n>` suffix, so the worker sentence repeats the `Lifecycle worker:` line's own arguments | the-bar token economy (fewest parameters); `launch-commit` already derives the action from the worker ID | Parent's `--action-id` plus an optional `--worker-id` makes a worker emit a value it can derive and opens a mismatch case |
| D3 | The row is written with `pgid: null` before the check and rewritten with the pgid after spawn. The marker is the proof, and the pgid only adds group members that scrubbed their environment | Parent D5 needs the row before the check, but a pgid exists only after spawn; parent D4 proof rule | Spawning stopped and then checking starts a process for a refused launch, which AC1 forbids. Writing the row after the check reopens the race parent D5 closed |
| D4 | The worker check reuses `launch-commit`'s reply parser. A sibling strict parser in `launch_scope` covers `check-launch` and is shared by `exec` and `--sweep`. Refusal reasons are the helper's own, plus `check_launch_failed`, `check_worker_failed` and `malformed_reply` | agent-helpers rule 2 (policy in importable functions); #222 D12 reason vocabulary | A new shared fence module moves `launch-commit` code with no second consumer of its own. Trusting a loose reply is the fail-open direction |
| D5 | When a process survives SIGKILL after the child returns, `exec` keeps its row, names the survivors on stderr and still exits with the child's status | The command's result is the child's. The registry row makes the survivor the reaper's job (parent D6) | Exiting 2 would hide a passing or failing verification behind a cleanup fact the reap already owns |
| D6 | `reap` exits 0 only when `skipped` is empty, 1 when its JSON lists skips (failed check or survivors), and 2 on a usage or helper error with empty stdout. Both callers treat non-zero as named and non-blocking | the-bar truthful terminal states; parent D1 and D6 (reap failure never blocks) | Exit 0 with skips presents a partial reap as success. Reusing 2 for skips conflates a run that worked with one that could not start |
| D7 | The environment is read from `/proc/<pid>/environ` on Linux and from `KERN_PROCARGS2` through `ctypes` on darwin. Any other platform fails loud with exit 2. An unreadable environment is no proof | Parent D4; probed on this darwin host (2026-10-07): a same-user setsid child's marker is readable, and pid 1 returns EINVAL; the-bar fail loud | `ps eww` output is truncated and quoting-ambiguous. psutil is a dependency the standard-library package does not take |
| D8 | The worker rule is a separate sentence placed right after every composed `Lifecycle worker:` line. The owner rule is one sentence in from-issue's lifecycle identity. The three leaf-agent clauses, their 13 carriers and the remainder placeholder stay unchanged. Issue AC4's "leaf clause names `launch-scope exec`" is met by these lifecycle-identity sentences | Parent D7 ("beside #222's `Lifecycle worker:` line"; nothing changes without identity); `test_dispatch_contracts.py` verbatim-once contract | Appending to the `own-commands` clause would spend tokens in every reviewer prompt and agent definition, none of which ever holds a lifecycle identity |
| D9 | Profiles in `instruction-load.json` whose files grow get their ceilings raised in the same change | #275 D7 / #155 D10 precedent | Leaving the ceilings alone turns `agent-workflow-tests` red |
| D10 | `launch-scope` checks only that the run and action IDs are safe single path segments before it builds the registry path. The identity grammar is still enforced by `check-launch` and `check-worker` | Grill: `reap --action-id ../..` would otherwise delete outside the registry. The grammar has one home in `workflow-state` (its `parse_action_id`), which agent-helpers rule 3 bars importing | Copying `ACTION_ID_PATTERN` into the package makes a second grammar home. Asking `check-launch` only to validate a reap costs a helper call on every self-reap |
| D11 | `exec` waits for its child with `waitid(..., WEXITED \| WNOWAIT)` and cleans up while the exited child is still an unreaped zombie, so the child's pid and group id cannot be reused until cleanup ends. The process table adds a `stat=` column (`ps -A -o pid=,ppid=,pgid=,stat=`): a zombie counts as gone, and a pid whose group changed during the poll is treated as reused and never sent SIGKILL. A signal that fails with `ESRCH` or `EPERM` is ignored | Probed on this darwin host (2026-10-07): `waitid` with `WNOWAIT` leaves the child reapable, `ps` lists a zombie leader under its own group id, and `killpg` on a group whose only member is a zombie fails with `EPERM`. Parent D4 says never signal what is not proved | Reaping the child first and then calling `killpg` leaves a window in which the group id can be reused. Without `stat`, an unreaped zombie looks alive and is reported as `processes_survived` |
| D12 | `launch_processes.terminate(pids, groups, *, read_table, send, send_group, term_seconds, kill_seconds)` takes injectable callables, with defaults for real use. Unit tests use them to cover the survivor branch and the never-self guard without signalling real processes, and a reap test patches `launch_scope.terminate` to cover `processes_survived`. Every other case uses real processes | the-bar: tests that can fail; spec D5 and D6 survivor semantics; the `CheckReplyTest` precedent of in-process function tests in the same suite | An unprivileged test cannot create a process that survives SIGKILL, so the D5 and D6 branches would go untested. A test that really signals its own group could kill the test runner and the pipeline around it |
| D13 | AUTO.md's Phase 2–4 prompt list also carries the worker `exec` sentence. The orchestrate-issues stop pass "writes nothing to the ledger", because the sweep removes host-local registry directories. The pass's last sweep that exited non-zero joins §5 **Stop failures** | Spec **Skill wiring**: "wherever a prompt is composed with a `Lifecycle worker:` line"; the-bar truthful prose | Leaving out AUTO.md means design and plan subagents run their builds outside any scope. Keeping "writes nothing" would be false once the sweep deletes directories |
