# Superseded launches and orphaned processes

## Problem

A launch whose attempt passed its deadline keeps running after the controller
reaps it. The reaper demotes the attempt to a suspension, and the same sweep
resumes it under a new launch in the same worktree. The predecessor owner's
host task is never stopped. The result is two owners on one worktree. Launch
fencing from #222 only fences commits (`launch-commit`) and forge writes
(`check-launch`). It does not fence reads, builds, scratch state or processes.

Processes started with `nohup … &` are reparented to PID 1. The host's task-stop
does not reach them, so they outlive the stopped agent. In the #262 run, one of
these leaked a scratch baseline worktree under `$TMPDIR` (`issue262-accept/base`),
and nothing in the pipeline knew that it existed. The user chose to keep that
worktree. This design must not remove it.

The leaf-agent clause already says to run long commands in the foreground and
never end a turn while one runs. That is prose. Nothing checks it, and nothing
cleans up after an agent that was stopped mid-command.

## Solution

There are four parts. The lifecycle ledger and `workflow-state` stay unchanged.

1. **Stop superseded owners (adapter).** Before orchestrate-issues executes a
   control response's dispatch actions, and again at `finalize`, it runs
   `check-launch` on every owner handle it recorded that has not yet returned.
   It stops each handle that reads `current: false` through the host's
   task-stop. The adapter is where this rule belongs, because it is the only
   party that holds host task handles.
2. **`launch-scope exec` (new `agent_tools` command).** A lifecycle agent runs
   each long command inside a launch-owned process session. The session's
   processes carry a launch marker in their environment and are recorded in a
   host-local launch registry. Leftovers in that session die when the command
   returns. Anything still alive when the launch ends is reaped.
3. **`launch-scope scratch` / `reap`.** Scratch directories and scratch
   worktrees live only under a launch's own scratch root. The reaper removes
   that root, the processes in it and its git worktree registrations. It removes
   nothing else. Unattributed worktrees are only reported.
4. **Guard refuses detaching words.** The `PreToolUse` lifecycle guard refuses
   `nohup`, `setsid` and `disown` at command position. That is the fast failure
   with a useful message. Part 2 is the correctness mechanism behind it,
   following defense in depth (the-bar).

## Decisions

### Stopping superseded owner handles (per D1)

orchestrate-issues gains one decision-free rule:

- For every recorded owner handle with no final return, run
  `workflow-state check-launch` on its `action_id`.
- On `current: false`, stop the handle through the host's task-stop, then mark
  it stopped. A missing or already-exited handle counts as stopped.
- Then run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id>`
  once, in sweep mode.
- Only after that, execute the response's dispatch actions in order.

A stop failure is named in the final report but does not block the dispatch.
The fences still hold, and a host failure must not stall the run. Stopping an
owner ends the agents it spawned, as #222 D8 records. This rule does not
change rule (c) for non-owner hand-backs, and it does not change rule (b),
whose `unavailable` observation makes the launch non-current. The next sweep
then stops that handle and reaps it.

### `launch-scope`: one command, three verbs (per D3)

The module is `agent_tools.launch_scope` with one command-table row. It is a
thin shell over importable functions, following agent-helpers rules 1–3. It
reaches `workflow-state` by command name on `PATH`, as `launch-commit` does.
Every verb takes `--repo-root <ledger_repo_root> --run-id <run-id>`.

- `exec --action-id <launch> [--worker-id <id>] -- <argv>`
  1. Writes a registry row for the new process group.
  2. Requires the launch to be live: `check-worker` when it has a worker id,
     otherwise `check-launch`. A negative answer, or a reply that is not the
     exact keys, removes the row and exits 3. In that case nothing is
     started, and stdout carries one canonical JSON line
     `{"action_id", "started": false, "reason"}`, using `launch-commit`'s
     reason vocabulary (#222 D12).
  3. Spawns the argv in a new session and process group (`setsid`, which is
     POSIX on darwin and Linux). The child's environment carries
     `AGENT_LAUNCH_SCOPE=<run-id>/<action-id>/<group-nonce>`.
  4. Forwards SIGINT, SIGTERM and SIGHUP to the group, and waits.
  5. When the child exits, signals what remains of its group, then removes
     the row and exits with the child's status.

  A usage error, or a helper that cannot be started, exits 2. The check runs
  after the row is written, so any reap that follows a supersession sees the
  row (per D5).
- `scratch --action-id <launch>` prints the launch's scratch root, creating it
  with `mkdtemp` under the system temp directory and recording its path in the
  registry. Repeat calls print the same path.
- `reap (--action-id <launch> | --sweep)`
  - With `--action-id`, the caller asserts that this launch is ending. The
    owner uses this mode on itself.
  - `--sweep` reaps every registered launch of the run whose `check-launch`
    reads non-current. A launch whose check fails is skipped and named in the
    report.
  - For each launch, the reaper signals the process groups it can prove and
    every marker-carrying process of the user (per D4). It then removes the
    scratch root, forcing removal of each git worktree registered inside it,
    and runs `git worktree prune`. Last, it deletes the launch's registry
    directory.
  - It prints one canonical JSON object:
    `{"reaped": [{"action_id", "signalled", "worktrees_removed", "scratch_removed"}], "skipped": [{"action_id", "reason"}], "unattributed_worktrees": [<path>]}`.
  - It exits 0 when every selected launch was reaped and exits 2 on a helper
    error. A launch with nothing left is reaped trivially, so repeating a reap
    is a no-op.

### Launch registry (per D2)

The registry is host-local process fact, not lifecycle state. It lives under
the ledger repository's git common directory at
`agent-launch/<run-id>/<action-id>/`. Every caller can derive that path from
the inputs it already holds. It is never in a working tree, so it can never be
committed. A group row is `{"pgid", "nonce", "started_at", "argv0"}`. The scratch
record is `{"path"}`. A reboot leaves stale rows, which fail the proof in D4
and are dropped. The ledger, `workflow-state` and the #125 transaction core
know nothing about this registry.

### Proof before signalling (per D4)

The reaper never signals by pgid alone, because a pgid whose leader is gone can
be recycled. It lists processes with `ps -A -o pid=,pgid=`, which is the same
on both platforms, and reads each process's environment through one platform
seam: `/proc/<pid>/environ` on Linux, and `sysctl` `KERN_PROCARGS2` through
`ctypes` on darwin.

- A recorded group is signalled with `killpg` only when at least one live
  member carries that row's exact marker.
- A process that carries the launch's marker outside its recorded group is
  signalled individually. That covers a program that called `setsid` itself
  and kept its environment.
- Signals go as SIGTERM, then a fixed 5-second grace period, then SIGKILL.
- The reaper never signals itself or any of its ancestors.
- An unreadable environment is not a proof.

### Owner self-reap (per D6)

Under a lifecycle identity, from-issue's exit order becomes:

1. release or stop every worker (#222, unchanged);
2. `launch-scope reap --action-id <action_id>`;
3. the exit write (`suspend`, handoff `progress`, the bookkeeper's `finish`).

A reap that exits non-zero is named in the owner's result but does not block
the exit write, because the adapter's sweep retries it. Workers do not reap,
because their processes belong to the launch and their owner's reap covers
them.

### Adoption rule (per D7)

The leaf-agent clause gains one sentence for prompts that carry a lifecycle
identity. Each long command, every verification command included, runs as
`launch-scope exec --repo-root … --run-id … --action-id … [--worker-id …] -- <argv>`,
and every scratch directory or scratch worktree is created under the path that
`launch-scope scratch` prints. The owner passes these values as one prompt
line, beside #222's `Lifecycle worker:` line. Without a lifecycle identity,
nothing changes.

### Guard: detaching words (per D9)

`nohup` leaves `COMMAND_WRAPPERS`. A segment where `nohup`, `setsid` or `disown`
stands at a command position is refused. The refusal message names the Bash
tool's background mode and `launch-scope exec`. A command position is anywhere
the existing tokeniser already opens one: after `(`, `{`, `` ` ``, `$(`, a
keyword, or a wrapper. In a segment handed to an evaluator (`eval`, `sh -c`),
any occurrence of the three words is refused, the same fail-closed treatment
the four guarded verbs get. A quoted mention, a heredoc body, a comment or an
argument position (`grep nohup log`) is not refused. A trailing `&` is not
refused. The guard stays standard-library-only and policy-free for this rule.

## Test seams

- **`python -m agent_tools.launch_scope`.** A new `tests/test_launch_scope.py`,
  listed in `agent-workflow-tests`, runs on darwin locally and on Linux in CI.
  It follows `tests/test_launch_commit.py`: a `PATH` shim runs the source
  `workflow-state`, and the ledger comes from `LifecycleHarness` (#222 D14).
  The cases use real processes and assert on observable pids, never on mocks.
- **`tests/test_claude_permission_guard.py` adversarial table.** It gets rows
  for each detaching word at each command-position class and behind each
  wrapper, inside `sh -c` and `eval`, and the negative rows: a quoted mention,
  a heredoc, a comment, an argument position and `&`.
- **`home/common/agent-skills/tests/test_workflow_skill_contracts.py`.** Using
  `assert_ordered`, it checks the order in orchestrate-issues (check-launch,
  task-stop, `reap --sweep`, then dispatch), in from-issue (release workers,
  `reap --action-id`, then the exit write), and the leaf clause's
  `launch-scope exec` and `scratch` sentence.
- **Installed layout.** `tests/test_agent_tools_launchers.py` already covers
  every command-table row, so it covers this one with no new seam.

The host task-stop itself cannot be tested by any seam in this repository. Its
effect is pinned only by the contract test.

## Out of scope

- Host-load scheduling of any kind: no CPU, memory, nix-daemon or test-host
  admission (`.agents/knowledge/rejections/host-contention-scheduling.md`).
  This design ends processes when a launch ends. It never schedules or
  throttles them.
- Any `workflow-state` or ledger schema change, and the #125 cutover.
- Removing the leaked `issue262-accept/base` worktree, or any existing leftover.
  These appear only in `unattributed_worktrees`.
- Reaping the attempt's issue worktree. The successor reuses it by design, and
  ship-issue's cleanup owns it.
- Detachers other than the three words (`tmux`, `screen`, `launchctl`,
  `systemd-run`, `at`), programs that daemonize after scrubbing their
  environment, and a stale `index.lock` left by a stopped agent (per D11).
- Codex parity for parts 1 and 4, since Codex has neither an orchestrate
  adapter nor a `PreToolUse` guard (per D12).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The adapter stops every recorded unreturned owner handle that `check-launch` reads non-current, then sweeps reap, before any dispatch and at `finalize`. A stop failure is reported, not blocking | orchestrate-issues: host task IDs are correlation data outside the lifecycle contract; only the adapter holds them. The reaper resumes in the same sweep (`demote_expired_attempt`) | The helper naming superseded launches in the response widens the interface for something `check-launch` already derives. Blocking the resume until the stop succeeds stalls the run on a host failure while the fences already hold |
| D2 | Process and scratch facts live in a host-local registry under the ledger repo's git common dir, not in the ledger | #222 out of scope: no host process killing by the helper; #222 D8. verified-tree precedent: machine-local state in the git dir | A ledger v7 field mixes host-local, reboot-volatile facts into lifecycle state that the #125 cutover must carry |
| D3 | One `agent_tools` command `launch-scope` with verbs `exec`, `scratch`, `reap`, reaching `workflow-state` by `PATH` | agent-helpers rules 1–3; the-bar token economy; the `launch-commit` precedent | Three commands triple the surface. Extending `launch-commit` would mix commit fencing with process ownership |
| D4 | Containment is a new session per `exec` plus an environment marker. Signal a group only with a marker-proved live member, signal stray marker carriers individually, use TERM, 5 s, KILL, and never signal self or ancestors. The environment is read via `/proc` on Linux and `KERN_PROCARGS2` on darwin | Must work on darwin and Linux; `setsid` and `killpg` are POSIX on both. The incident is reparented processes that a tree walk misses | pgid alone risks pid reuse once the leader is gone. cgroups and `PR_SET_CHILD_SUBREAPER` are Linux-only. The host tree-kill misses reparented processes, which is the observed failure |
| D5 | `exec` writes its row, then checks liveness and refuses non-live launches with exit 3 and `launch-commit`'s reasons. It reaps its own group when the command returns | #222 D5/D12 fence vocabulary. Row before check makes every post-supersession reap see it | Checking before writing the row lets a reap race past an unregistered group. Keeping leftovers until the launch ends lets test daemons pile up across commands |
| D6 | Reap triggers: the owner self-reaps after releasing workers and before every exit write; the adapter sweeps non-current launches. There is no reap from `workflow-state`, and a failed self-reap does not block the exit | Proposal 2 named suspend, finish and expiry. Expiry and `unavailable` surface only to the adapter as non-current launches | Reap on finish only (proposal 4) leaks on every suspension and expiry. A helper-side reap at the transition reintroduces host killing in the helper |
| D7 | Adoption: under a lifecycle identity, the leaf clause routes long commands through `launch-scope exec` and scratch through `launch-scope scratch` | The leaf clause already scopes "long command"; #222's `Lifecycle worker:` line precedent | Wrapping every Bash call costs tokens with no gain on short commands. Hook-injected wrapping is Claude-only and needs `agent_tools` in the guard, which agent-helpers forbids |
| D8 | Reap deletes only inside recorded scratch roots. Other worktrees, including the leaked #262 baseline, are only reported, permanently, never auto-deleted | The user declined removing `issue262-accept/base`; the lifecycle hands a retry its predecessor's worktree on purpose | Reaping all registered worktrees on finish (proposal 4) would delete the successor's worktree and retained evidence. Auto-deleting unattributed trees is irreversible |
| D9 | The guard refuses `nohup`, `setsid` and `disown` at command position globally, in every Claude session and repo, and anywhere inside evaluator source. A trailing `&` is allowed | The guard's fail-closed tokeniser and adversarial table; the-bar defense in depth (guard is the outer check, D4 the inner) | Scoping the refusal to lifecycle sessions is impossible because the hook cannot tell sessions apart. Refusing `&` breaks `a & b & wait`. Prose alone is what failed |
| D10 | Test seams: new `tests/test_launch_scope.py` with real processes on both OSes, the guard adversarial table, skill contract ordering, and the existing launcher test | #222 test seams; agent-helpers rule 5 | A host-stop integration test is impossible here because the host is outside the repo |
| D11 | Accepted residuals: a check-to-spawn window in `exec`, environment-scrubbing daemons, other detachers, and a stale `index.lock` after a stop | #222 accepts the same check-then-act window for `launch-commit` | Tombstone handshakes or detacher enumeration cost complexity with no observed incident |
| D12 | Codex gets `launch-scope` through the shared skills only, with no adapter stop and no guard | CLAUDE.md: the Codex orchestrate stub routes to `/from-issue` per issue; the guard is Claude-only | Building Codex parity now is YAGNI with no observed Codex leak |

## Proposed slices

**S1 — Stop superseded owner handles before resume.** Autonomous. Blocked by
nothing. Prose only, in orchestrate-issues (D1, without the reap sweep).
- AC1: orchestrate-issues orders `check-launch` on unreturned owner handles,
  then task-stop on `current: false`, then dispatch. Measured by
  `test_workflow_skill_contracts.py` with `assert_ordered`, which fails at base.
- AC2: the rule treats a missing or exited handle as stopped and reports a
  stop failure without blocking dispatch. Measured by the same contract test.
- AC3: rules (b) and (c) are textually unchanged. Measured by the existing
  contract assertions staying green.

**S2 — `launch-scope exec` and `reap`, wired into owner exit and adapter
sweep.** Autonomous. Blocked by S1.
- AC1: `exec` under a superseded launch exits 3 with
  `{"action_id","started":false,"reason":"superseded_launch"}`, starts nothing
  and leaves no registry row. Measured by `tests/test_launch_scope.py`.
- AC2: a command that backgrounds `sleep 300` and exits leaves no live process
  once `exec` returns. Measured by a pid liveness check in the same file.
- AC3: after SIGKILL of both the `exec` supervisor and the child leader,
  `reap --sweep` kills the surviving reparented grandchild and a `setsid`
  escapee that carries the marker, while an unmarked sibling process survives.
  Measured in the same file, on darwin and Linux.
- AC4: from-issue orders release workers, `reap --action-id`, then the exit
  write; orchestrate-issues runs `reap --sweep` after stops; the leaf clause
  names `launch-scope exec`. Measured by `test_workflow_skill_contracts.py`.
- AC5: `just build` import-checks the new module, and the launcher test passes
  for the new row. Measured by `just build` and
  `tests/test_agent_tools_launchers.py`.

**S3 — Launch scratch roots.** Autonomous. Blocked by S2.
- AC1: `scratch` prints the same path on repeat calls, and that path is
  recorded in the registry. Measured by `tests/test_launch_scope.py`.
- AC2: a git worktree added inside the scratch root is gone from
  `git worktree list` and the disk after `reap`. Measured in the same file.
- AC3: a worktree outside every scratch root appears in
  `unattributed_worktrees` and still exists after `reap`. Measured in the same
  file.
- AC4: the leaf clause routes scratch through `launch-scope scratch`. Measured
  by `test_workflow_skill_contracts.py`.

**S4 — Guard refuses detaching words.** Autonomous (D9 settled: the 2026-10-06 leak was a `nohup` orphan surviving `TaskStop`). Blocked by
nothing.
- AC1: `nohup x &`, `(setsid x)`, `env nohup x`, `$(disown)` and `sh -c 'nohup x'`
  exit 2 with the refusal naming the background mode. Measured by
  `tests/test_claude_permission_guard.py` adversarial rows.
- AC2: `echo "nohup"`, `grep nohup log`, a heredoc body, a comment and
  `a & b & wait` pass. Measured by the same table.
- AC3: `nohup git push origin main` is still refused, now for detaching.
  Measured by the same table.
- AC4: the guard still imports nothing from `agent_tools`, and the guard suite
  is green. Measured by `just build` and the guard suite.
