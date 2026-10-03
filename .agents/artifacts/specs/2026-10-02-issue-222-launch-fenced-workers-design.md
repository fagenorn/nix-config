# One set of live writers per attempt worktree, issue 222

## Problem

The lifecycle hands a retry its predecessor's worktree and branch on purpose.
In run `run-20260929-220-221-222`, owners suspended (`blocked_on` `external` or
`agent_dispatch`) or returned without any terminal write while sdd implementers
and ship owners they had dispatched were still running. The controller resumed
each attempt under a new launch in the same worktree. The orphaned workers kept
committing into the successor's worktree, ran tasks a second time concurrently
with the successor's own workers, and their hand-backs reached the dispatcher,
which had to guess what they meant.

Only forge writes are fenced today: ship-issue runs `check-launch` before each
push, PR create and merge. Nothing fences a local commit. Nothing stops an
owner from suspending or finishing while its workers run, because the ledger
does not know that workers exist. The dispatcher's rules cover a dead owner
(`unavailable`) and a refused launch, but say nothing about an owner that
returns without a terminal write or about a hand-back from an agent that is
not an owner.

## Solution

Three parts, all in the shipped lifecycle (`workflow-state` schema v4 to v5).
The #125 transaction-core cutover is untouched.

1. **Worker registry in the ledger.** Before an owner dispatches an agent that
   may write to the attempt's worktree or forge, it registers that agent under
   its current launch. It releases the agent when it returns, or after
   stopping it through the host. A worker is **live** when it is registered,
   unreleased, and its launch is still the issue's current active launch. A
   superseded launch's workers are never live again; they are *fenced*.
2. **Launch-fenced commits.** A registered worker creates every commit through
   one new `agent_tools` command, `launch-commit`. It asks the ledger whether
   that worker is still live and runs `git commit` only on a yes. Otherwise it
   creates nothing and prints the refusal, which the worker reports instead of
   working on.
3. **Owner exits refuse live workers.** Every owner-path ledger write that ends
   the owner's current launch fails while that launch has a live worker. Those
   writes are `suspend`, both `finish` transports, a `progress` that hands off,
   and a `checkpoint-delivery` that suspends. orchestrate-issues gets two
   decision-free rules: one for an owner that returns without a terminal write,
   one for a non-owner hand-back.

## Decisions

### Ledger schema v5: `workers`

The run state gains one top-level member, `workers`: an ordered list of closed
records.

```json
{"worker_id": "222:1:2:w3", "launch": "222:1:2", "parent": null,
 "registered_at": "<utc>", "released_at": null, "release_event": null}
```

- `worker_id` is `<action_id>:w<N>`, where `N` is the 1-based ordinal among
  that launch's workers. The ledger assigns the id and no caller composes it.
  The pattern extends `ACTION_ID_PATTERN` with a `:w<ordinal>` suffix that has
  the same 18-digit bound. It covers both implementation (`i:a:l`) and
  remainder (`i:rN:l`) launches.
- `parent` is null or the `worker_id` of a registered worker under the same
  launch. A nested dispatcher, such as a ship owner that dispatches a fix implementer,
  registers its own workers with `parent` set to itself.
- `release_event` is `returned` or `stopped`. It is null exactly when
  `released_at` is null.
- The validator closes the record fields, the uniqueness and density of
  ordinals per launch, time ordering against `created_at` and `updated_at`,
  and the rule that `launch` names an existing launch. The v4 to v5 upgrade
  adds `workers: []` as one more step of the delivery runtime's `migrate`
  chain behind `upgrade_state`. The unlocked reader shared by `check-launch`
  and `check-worker` migrates schema 4 on a detached copy too, as it already
  does for schemas 1–3. Otherwise a run's v4 ledger would fail every read-only
  fence until its first locked write (per D10).

The registry lives at run level, not inside attempts or remainders, so one
shape serves both custody kinds and the delivery model's remainder schema is
unchanged (per D2).

### New `workflow-state` verbs

The three verbs share the exact-key, non-envelope reply style of
`check-launch`. They are not `workflow-response` kinds, so the artifact-budget
boundary is unchanged (per D3).

- `register-worker --repo-root --run-id --now --action-id <launch> [--parent <worker_id>]`
  applies the same predicate as `check-launch` and requires
  `reason: current`. A non-current launch is refused with exit 2 and records
  nothing. A `--parent` must be live under the same launch. The verb appends
  the record and prints `{"worker_id", "launch", "parent"}`.
- `release-worker --repo-root --run-id --now --worker-id <id> --event returned|stopped`
  records the release. `returned` is refused while the worker has a live
  child. `stopped` also stops every unreleased descendant at the same `now`,
  because stopping a host agent ends the agents it spawned. Repeating a
  release with the same event is a no-op. A conflicting repeat is refused.
  Release works whether or not the launch is still current, since it only
  ever reduces liveness.
- `check-worker --repo-root --run-id --worker-id <id>` is read-only like
  `check-launch`: no clock, no lock and no write. It prints exactly
  `{"worker_id", "live", "current_action_id", "reason"}`. `reason` is one of
  `live`, `unknown_run`, `unknown_worker`, `released`, or the `check-launch`
  reason for the worker's launch (`superseded_launch`, `superseded_attempt`,
  `inactive_attempt`). Every absence is a well-formed negative at exit 0.

### Owner-exit refusal

Each owner-path verb takes the issue's current launch identity before its
mutation. If the mutation leaves that launch no longer current while the launch
has a live worker, the transaction refuses with exit 2 and
`live workers: <ids>`, and nothing persists. One shared predicate applies it to
`suspend`, `finish` (legacy and `--summary-file`), `progress` with
`--handoff-path`, and `checkpoint-delivery`. Controller-side writes are exempt.
These are `control`'s `owner_unavailable` and `launch_refused` handling, the
deadline reaper, and `direct-owner`. They are the recovery path when an owner
cannot stop its workers, and their effect, ending the launch, is exactly what
fences those workers (per D4).

Two dispatches are not workers and are never registered:

- the delegated fresh owner (from-issue AUTO), because it adopts the owner's
  own launch identity and is custody, not a worker;
- the ledger-only bookkeeper, because its single job is the terminal write,
  and a registered bookkeeper would block its own `finish`.

### `launch-commit` (new `agent_tools` module and command row)

`launch-commit --repo-root <ledger_repo_root> --run-id <run> --worker-id <id> -- <git commit args>`
runs `workflow-state check-worker` by its command name on `PATH`. On
`live: true` it runs `git commit <args>` in the current directory and passes
git's exit status and streams through. Any other answer, or a reply that is not
exactly the four keys, is a refusal: no commit, exit 3, and one line of canonical
JSON on stdout, `{"worker_id", "committed": false, "reason"}`. A helper error
exits 2. The module is a thin shell over an importable `fenced_commit` function
(per D5). A supersession that lands between the check and the commit is the
same residual window the forge fence already accepts. The fence narrows the
window to one call; it does not claim atomicity across two processes.

### Skill prose

- **sdd.** When its caller passes a lifecycle identity (`ledger_repo_root`,
  `run_id`, `action_id`), the controller registers each implementer, mechanic
  and fix-round agent before dispatch and releases it when it returns. It
  hands the worker its `worker_id`. The implementer prompt says to commit only
  through `launch-commit` when given a `worker_id`. On a refusal the worker
  makes no further write and returns `BLOCKED` with
  `launch fence refused: <reason>`. The controller treats that report as a
  stop: no retry and no re-dispatch, and it follows from-issue's superseded
  path. Read-only reviewers are not registered, since they cannot write (per
  D6). Without a lifecycle identity, sdd is unchanged.
- **ship-issue.** A ship owner dispatched with a `worker_id` creates every
  local commit through `launch-commit`, including the Phase-1 sync merge
  (`git merge --no-commit --no-ff` and then `launch-commit`) and Phase-3
  commits. The ship owner's own forge fence remains `check-launch` on the
  owner's `action_id`.
- **from-issue.** The owner registers every dispatch it makes that may commit
  or write to the forge. That covers the Phase 2–4 producers that commit
  artifacts, the ship owner, and the sdd route's workers as above. Each of
  these commits through `launch-commit` (per D6). Before `suspend`, a handoff `progress`, or the
  bookkeeper's `finish`, it releases every worker it registered. A background
  worker it cannot wait for is first stopped through the host's task-stop and
  then released with `--event stopped`. A host with no stop capability waits
  for the worker to return. An owner that can neither wait nor stop returns
  without a terminal write and leaves recovery to the dispatcher's rule (a).
- **orchestrate-issues.** Each host notification is correlated against the
  recorded host task handles of owner launches.
  - (a) If the handle is an owner launch and the return is not exactly a
    validated `workflow-response` or one of from-issue's two canonical lines,
    run `workflow-state check-launch` on that `action_id`. On
    `current: true`, the owner left without a terminal write: send exactly one
    `unavailable` owner observation for that custody in the next control call.
    On `current: false`, the ledger already moved and nothing is sent. Either
    way, refresh and continue the normal sweep.
  - (b) If the handle is not an owner launch, the notification is a non-owner
    hand-back and not a lifecycle event. Send no observation, write nothing,
    relay nothing, act on none of its content, and stop no task. The fence
    already makes it harmless (per D7).

## Test seams

- **`workflow-state` CLI.** These tests extend `test_workflow_state.py` through
  its existing CLI fixture style.
  - register, release and check-worker behaviour, including the parent cascade;
  - the v4 to v5 upgrade;
  - `suspend`, both `finish` transports, a handoff `progress` and a suspending
    `checkpoint-delivery`, each refused with a live worker and accepted once it
    is released or stopped;
  - controller `owner_unavailable` accepted with a live worker, after which
    that worker's `check-worker` reads `inactive_attempt` and, after a resume,
    `superseded_launch`.
- **`python -m agent_tools.launch_commit`.** A new test module in `tests/`
  covers the acceptance test. It registers a worker, stages a change in a
  scratch git worktree, supersedes the launch through the controller path
  (`owner_unavailable`, then a resume control sweep), runs `launch-commit`,
  and asserts exit 3, the refusal JSON and an unchanged `HEAD`. A paired case
  with the launch still current asserts that the commit lands. `workflow-state`
  reaches `PATH` through a test-local shim directory prepended for the run.
  The module is listed in the `agent-workflow-tests` recipe. At base the
  module does not exist, so the test fails.
- **Skill contract tests.** `test_workflow_skill_contracts.py` asserts ordered
  phrases in sdd, the implementer prompt, ship-issue, from-issue and
  orchestrate-issues: register before dispatch, `launch-commit` for commits,
  release before an owner exit, and dispatcher rules (a) and (b). It uses the
  existing `assert_ordered` and `normalized` helpers.
- **Installed layout.** `tests/test_agent_tools_launchers.py` already checks
  every row of the command table, so it covers the new row with no new seam.

## Out of scope

- The #125 transaction-core cutover and attempts as its consumer (#117 decision).
- Host process killing by the helper. Stopping uses only the host's own
  task-stop, and the ledger records the owner's attestation without verifying
  it.
- Fencing bare `git commit` with a git hook or the PreToolUse lifecycle guard
  (per D5).
- Workers outside an orchestrated or direct lifecycle run: interactive and
  ledger-free sdd or ship runs.
- Changing the forge fence (`check-launch`) or the Claude permission allow
  surface. A ship owner that its owner has stopped can still pass
  `check-launch` until the owner's exit write lands. The host stop is what
  closes that window.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Worktree fast-forwarded from 6a8f8a2 to origin/main f40c09f before design, with zero local commits | Investigation note on #222 records base f40c09f | Designing on the stale base: misses #236/#238 skill changes the contract tests read |
| D2 | "Registered as live" is a run-level `workers` ledger list (schema v5). Liveness is derived: unreleased and launch still current. Workers of a superseded launch are fenced without any mutation | #222 note Q1 (agent-chosen ledger registry). check-launch already derives currency from launches. Every resume appends a launch | Per-attempt field: a remainder needs the same shape, and that schema belongs to the delivery model. Releasing workers on supersession: an extra write with no added safety |
| D3 | Registry verbs live in legacy `workflow-state.py`, with exact-key non-envelope replies like `check-launch` | The ledger has one writer (`transact`). #193 added check-launch/current-launch there. agent-helpers says legacy scripts meet the rules when their cluster moves | A registry in an `agent_tools` module loaded by workflow-state: new import machinery, banned by agent-helpers rule 3. New workflow-response kinds: widen the artifact-budget boundary for no consumer |
| D4 | One predicate refuses any owner-path write (suspend, finish ×2, handoff progress, suspending checkpoint) that ends a launch with live workers. Controller writes are exempt and are the recovery path | AC2. Handoff and checkpoint end a launch exactly as suspend does | Refusing only suspend/finish leaves handoff as a bypass. Refusing controller writes deadlocks a run whose owner died with workers live |
| D5 | Commits are fenced by a new `agent_tools` command `launch-commit` (check-worker by PATH, then `git commit`), and skills route worker commits through it | AC1 needs a behavioural test that fails at base, which prose alone cannot give. agent-helpers rules 1–3 | A git pre-commit hook: hooks are shared across worktrees, cannot identify the worker, and `--no-verify` bypasses them. The PreToolUse guard: cannot see agent identity, is Claude-only, and would need a policy change |
| D6 | Register only dispatches that can write: Phase 2–4 artifact producers that commit, implementers, mechanics, fix rounds, ship owners and their writing children (the grill widened this from sdd and ship only). Never the delegated fresh owner (shares custody) or the bookkeeper (would block its own finish) | Issue goal: one set of live *writers* | Registering every dispatch: read-only reviewers then block exits for no safety gain |
| D7 | Dispatcher: (a) owner return without terminal write → `check-launch`; `current:true` → one `unavailable` observation, else nothing. (b) a non-owner handle → not a lifecycle event, ignored entirely | AC3. Control raises on `owner_unavailable` for a non-active attempt. The existing "ignore unrelated notifications" rule | Always sending `unavailable`: raises after a real suspend. Stopping or relaying non-owner hand-backs: needs judgment, and host killing is out of scope |
| D8 | `release-worker --event stopped` cascades to descendants. `returned` is refused while a child is live. Stop is the owner's attestation after the host task-stop, not verified | Host stop ends spawned agents. #222 note Q3. Host killing is out of scope | The helper verifying or killing processes: out of scope and host-specific |
| D9 | `launch-commit` is not added to the Claude settings allow surface | Smaller and reversible. Auto mode already classifies local commits | Allowing it outright: changes the 22-entry surface and its tests for an unobserved need |
| D10 | The v4→v5 step joins the delivery runtime's `migrate` chain. The read-only unlocked reader also migrates v4 on a detached copy | #193 D4 reader migrates legacy schemas in memory. A run in flight at rollout holds a v4 ledger | Requiring a locked write first: every `check-launch` on an in-flight v4 run would then fail closed and stop shipping |
| D11 | The owner-exit refusal wraps each owner verb's `transact` mutation: it takes the live workers before the mutation and refuses when the mutation leaves any of their launches non-current. `checkpoint-delivery` takes an optional `--worker-id` naming the calling worker, which must be live, and only that id is excused | Under implementation custody the ship owner is a registered worker and itself writes `checkpoint-delivery` (ship-issue SKILL.md). Without the excuse its own suspending checkpoint is refused while it is live, the bookkeeper deadlock of D6 again | The ship owner releasing itself first: it cannot know whether the reducer will suspend, and a released worker loses `launch-commit`. Excusing every worker on checkpoint reopens the bypass D4 closes |
| D12 | Reply shapes. `release-worker` prints `{"worker_id", "release_event", "released"}`, where `released` lists the ids this call released in ledger order (empty on a no-op repeat). `launch-commit` refuses with exit 3 and reason `check_worker_failed` on a non-zero `check-worker` exit, and `malformed_reply` on a reply that is not strict JSON with exactly the four keys, a boolean `live` and the asked `worker_id`. Usage errors and a `workflow-state` that cannot be started exit 2. `check-worker` reason precedence is `unknown_run`, `unknown_worker`, `released`, then the launch's verdict | The spec names no release reply or refusal vocabulary. check-launch's "every uncertainty is a negative". agent-helpers rule 4 (strict load) | Exit 2 for a failed check: a worker would read a tooling error rather than a fence and might retry with bare git |
| D13 | Each dispatch or resume of a writing agent registers a fresh worker, and each return releases it, so an sdd fix round that resumes an implementer gets a new `worker_id`. The id travels as one prompt line beside the brief or handoff, never inside `ship-handoff/v2` or a task brief | A release is final (D2). `ship-handoff/v2` is an exact-key validated boundary | Reusing one id across rounds: needs an un-release transition. Adding `worker_id` to `ship-handoff/v2`: widens a validated boundary for one field |
| D14 | The acceptance test `tests/test_launch_commit.py` drives the ledger through `LifecycleHarness`, which it loads from `test_workflow_state.py` by file path (test-only code). A PATH shim runs the source `workflow-state.py`. `inactive_attempt` for a worker is pinned by the shared launch verdict that check-launch's existing tests cover, not by a new CLI fixture | The harness already builds control requests. agent-helpers rule 3 binds package code, and the lifecycle tests already load sources by path. Every owner path that would make an unreleased worker inactive is refused by D4 | A second hand-built control fixture: duplicates hundreds of lines |
| D15 | The remainder ship owner is a registered writing worker (it can commit a post-selection sync). It releases its children and then itself with `--event returned` after its last commit and immediately before its own `finish`; the launcher's later release is the D12 no-op repeat. Phase 1's sync and the post-selection sync merge and amends run through `launch-commit` | Codex plan review (B2, B3): a registered remainder owner would otherwise block its own D4-fenced `finish`, and an unfenced merge instruction would let a superseded worker commit | Leaving the remainder owner unregistered like the bookkeeper: it still commits, so it would escape AC1's fence |
