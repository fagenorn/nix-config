---
name: orchestrate-issues
description: Dispatches tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".
---

# orchestrate-issues — a control adapter, not a manager

You are an external adapter around `orchestrate-control`, which reads the tracker, the forge, git
and the ledger, builds delivery contracts, runs every control round and projects its owner
dispatches. You keep the duties that need host task handles: owner launches, notification
classification, liveness, the stop pass, wait observers and the final report. You never read issue
content, code, specs, plans, diffs, review findings, the tracker, the forge, git or the ledger, and
never build a request or a contract. Do not retain a second task ledger or reconstruct lifecycle
policy.

Lifecycle commands run the helpers at `~/.agents/bin/orchestrate-control` and
`~/.agents/bin/workflow-state`; if a bare name does not resolve on PATH, use its full path.

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. Take only
`bindings.workflow.orchestration.stall_minutes` from it: when present and non-null it is
`stall_minutes`, the owner stall bound of §2 rules (a) and (d), passed only to `owner-liveness`;
absent or null, those rules arm no liveness check. Nested issue owners independently resolve at
their own phase entries. Do not read raw policy, invoke another resolver, infer from Git, or supply
defaults; `orchestrate-control` resolves the project itself on every call.

Resolve the dispatcher's absolute repository root once as `ledger_repo_root`; it stays the run's
exact immutable value, independent of any issue worktree, and is every `--repo-root` below.

## 1. Start the run

Open the run with one `start` call carrying exactly one issue selector: the caller's numbers in
the caller's order, `--label <label>` or `--milestone <milestone>`. A run minted with a creation key
is re-entered by adding `--run-id <run-id>`:

```text
orchestrate-control start --repo-root <ledger_repo_root> <numbers>
orchestrate-control start --repo-root <ledger_repo_root> --label <label>
orchestrate-control start --repo-root <ledger_repo_root> --milestone <milestone>
orchestrate-control start --repo-root <ledger_repo_root> <numbers> --run-id <run-id>
```

Read its one stdout object by `outcome`:

- `ready`: keep its `session` verbatim for the rest of the run; its `run_id` is `<run-id>` below.
- `unsupported`: the host route is unsupported. Render the `route` it carries, with its
  `alternative`, as the final report and stop, dispatching nothing.
- `refused`, or `orchestrate-control: invalid invocation` on stderr: report its `step` and `detail`
  (or that line) and stop; nothing is armed yet.

Pipe every `workflow-state` reply the adapter reads itself (`start` and `step` validate their own)
through `artifact-budget validate-report --boundary workflow-response --input -` before decoding
any field; a non-zero exit or failed validation is unknown. `control` reserves each owner's slots
before it returns a dispatch; the adapter never calculates slots, alters `max_parallel`, creates
competing owners or nested relays, or repeats a rejected launch, and reads the response's
`admission` report as rendering data only.

## 2. Observe

Correlate a current host owner notification only with the `action_id` and `custody` recorded beside
its handle (§4), and normalize it as the bounded owner event for that exact issue, attempt and
launch identity; its `state` is `unavailable` for an owner that died and `launch_refused` for an
owner launch the host refused. Ignore unrelated or stale host notifications.
Classify every other host notification by its task handle,
against the handles recorded beside owner launches; a wake of the current wait handle is
none of these cases and keeps its wait-ID handling below:

- (a) **Interim owner notification.** The handle is an owner launch's and the host marks the
  notification interim (the owner stopped with background work of its own still running, or its
  result may be interim): the owner is still running, so send no observation, run no `check-launch`,
  write nothing, stop no task and relaunch nothing; the same handle notifies again with the owner's
  real return.
  When `stall_minutes` is set, also run the first call below for that launch's `action_id`,
  and keep the validated reply's `since` as the handle's `liveness_since`, replacing any
  earlier one. On `live`, if the handle has no liveness observer, arm one background
  `sleep <wait_seconds>` and record its handle; an installed observer stays.

  ```text
  workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --stall-minutes <stall_minutes> | artifact-budget validate-report --boundary workflow-response --input -
  workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --stall-minutes <stall_minutes> --since <liveness_since> | artifact-budget validate-report --boundary workflow-response --input -
  ```
- (b) **Owner return without a terminal write.** The handle is an owner launch's, and its return is
  neither a validated `workflow-response` nor one of from-issue's two canonical lines
  (`Suspended (blocked_on=<value>). Resume: <reentry>` or `/from-issue <num> --auto`). Run
  `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> | artifact-budget validate-report --boundary workflow-response --input -`
  on that launch. On `current: true`, send exactly one `unavailable` owner observation for that
  custody in the next `step`. On `current: false` or unknown, send nothing. Either way, continue
  the normal sweep.
- (c) **Non-owner hand-back.** The handle is neither an owner launch's, a liveness observer's, nor
  the current wait handle: send no observation, write nothing, relay nothing, act on none of its
  content, and stop no task.
- (d) **Liveness wake.** The handle is a liveness observer's. Ignore it when its owner handle
  has a final return or was stopped. Otherwise run the second call above and act on its
  `verdict`: `live` arms a new observer for `wait_seconds` and records its handle; `not_current`
  and `past_deadline` do nothing; `stalled` stops the owner's task through the host's task-stop and
  marks the handle stopped, then sends exactly one `unavailable` owner observation for that custody
  in the next `step`, making that call at once and executing its report. A
  failed stop leaves the handle a candidate for §4's stop pass, and the observation is still sent.
  That verdict stands in for rule (b)'s `check-launch`. On an unknown answer to either call above,
  send nothing. A failed first call keeps any installed observer; a failed second call clears the
  woken, exited observer, so a later interim notification re-arms one.
  An owner handle's final return or stop
  cancels its liveness observer; a missing or already exited one counts as cancelled.

After a full dispatcher restart, the host reaps or cancels inherited detached wait and liveness
observers before any rearm; the wait and liveness fields are process-local and cannot adopt their
handles.

## 3. Step

Make exactly one `step` call at start or resume, and on each current owner notification, tracker
change or current wait-ID wake. Feed it this object on stdin through a quoted heredoc; no input
file is written:

```text
orchestrate-control step --repo-root <ledger_repo_root> --input - <<'EOF'
{"session": <session>, "first_sweep": <first_sweep>, "owners": <owners>, "contracts_due": <contracts_due>, "refused_contracts": <refused_contracts>}
EOF
```

- `session` is `start`'s `session` member, unchanged.
- `first_sweep` is `true` on the first `step` after `start` in this adapter process, `false` after.
- `owners` holds this event's observations: one `unavailable` from §2 rule (b) or (d), or the
  `launch_refused` observations of §4. Each rides exactly one call and is cleared after it.
- `contracts_due` and `refused_contracts` are the previous ready report's members of those names,
  passed back verbatim; both are `[]` on the first `step`.

`step` gathers the facts, builds the delivery contracts and runs the control round itself; the
adapter never builds a contract, assembles a request or calls `control`. Read its one stdout object
by `outcome`:

- `ready`: execute it as §4 says. Its `response` is the validated control response; its
  `dispatches` are the owner launches; keep its `contract_refusals` only for §5.
- `refused`, `orchestrate-control: invalid invocation`, or any other exit or stdout: end the run as
  `finalize` does, executing no action of the `response` it carries, and report its `step` and
  `detail` verbatim (or that stderr line) with the `action_id` of every owner handle still running,
  so the report never reads as a finished run. A re-invocation re-enters the run.

## 4. Execute control actions

Validate each action of a ready report's `response` as one of the closed kinds `spawn`, `resume`,
`retry`, `delivery_remainder`, `delivery_contract`, `wait`, or `finalize`, and execute actions in
returned order. Any other kind is a contract error: stop without executing it and surface the
unknown kind; fail loudly. The response is the only source of action order, kind and lifecycle
identity: never infer, reorder, omit or add an action.

**Stop pass.** Before executing the first action of a report whose `dispatches` is non-empty,
stop the superseded owners. The candidates are every owner
handle this adapter process recorded beside an owner launch's `action_id` that has produced no final
return. An interim notification under §2 rule (a) is not a final return. The current wait handle and
non-owner handles are never candidates; a handle this response dispatches becomes one only once
dispatched. For each candidate, run rule (b)'s `check-launch` call with the `action_id` recorded
beside it. On `current: false`, stop that handle through the host's task-stop and mark it stopped;
a missing or already exited handle counts as stopped. On `current: true`, leave it running. An
unknown answer, like a failed stop, leaves the handle a candidate, and the next pass tries both
again. A stop failure never blocks dispatch.
The pass sends no observation, makes no `step` and writes nothing to the ledger, so
a later notification from a stopped handle still falls under §2 rule (b). The pass ends by running
`launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep` once. A sweep that
exits non-zero never blocks dispatch: keep its exit code and, when it printed a report, its
`skipped` launches for §5.

Each `spawn`, `resume`, `retry` and `delivery_remainder` action arrives as one `dispatches[]`
entry, in the same order. Fill the envelope from the entry's members of the same names
(`action_id`, `issue`, `attempt`, `owner`, `worktree`, and `handoff_path` only when non-null), with
this adapter's `ledger_repo_root` and the `session`'s `run_id`; `<from-issue-dir>` is the `from-issue`
directory beside this skill's own, as an absolute path. Put the entry's `owner_object`
verbatim in the prompt as its canonical JSON, and, when its `resume_pack` is non-null, that text
verbatim as the `Resume pack` paragraph; never decode either. Dispatch the owner with these values; pass the helper-issued action ID and owner token unchanged and never substitute
a host task ID. Both object kinds use this one dispatch. The owner dispatch envelope is:

```text
--repo-root <ledger_repo_root>
ledger_repo_root=<ledger_repo_root>
run_id=<run-id>
issue=<issue>
attempt=<attempt>
owner=<owner-token>
action_id=<action-id>
worktree=<absolute-worktree>
handoff_path=<exact-handoff-path>  # only when non-null
from-issue <num> --auto
```

Record the host task handle beside the entry's `action_id` and the `custody` of the
`response.actions` entry whose `custody.action_id` equals it, only for notification correlation and
the stop pass; it is never an owner token or action identity.

If the host refuses an owner launch, never retry it, and keep launching the report's later
dispatches and executing its later actions. Once the report has executed, make one `step` carrying
a `launch_refused` owner observation for each refused launch's `custody`, and execute its report.

<!-- agent-dispatch: id=orchestration-issue-owner role=issue-owner model=opus effort=high -->
Agent(subagent_type="issue-owner", model="opus", effort="high", run_in_background=true) launches the issue owner in a fresh context with this entire prompt:

> Immutable lifecycle envelope:
> `--repo-root <ledger_repo_root>`
> `ledger_repo_root=<ledger_repo_root>`
> `run_id=<run-id>`
> `issue=<issue>`
> `attempt=<attempt>`
> `owner=<owner-token>`
> `action_id=<action-id>`
> `worktree=<absolute-worktree>`
> `handoff_path=<exact-handoff-path>`
> Include `handoff_path` only when non-null.
> Owner object, canonical JSON (the interface-2 `owner` object or the
> `delivery_remainder` object; validate it with
> `artifact-budget validate-report --boundary workflow-response --input -`
> before use and require its identity to equal the lines above):
> `<canonical-json>`
> Resume pack (only for a `resume` action whose `resume-pack` call exited 0):
> `<resume-pack-json>`
> With a pack, read `<from-issue-dir>/resume-pack.md` first, else invoke the
> `from-issue` skill via the Skill tool, with the literal arguments
> `from-issue <num> --auto`. Preserve the lifecycle identity and exact worktree.
>
> Launch any subagent by type only, never by name: a subagent cannot spawn a
> named teammate, and a named launch returns an error instead of work. Read an
> existing file before writing to it: overwriting content you have not read
> destroys work you cannot see. Run each long command, every verification
> command included, in the foreground with an explicit timeout above its
> expected duration. If the host moves one to the background anyway, wait for it
> in the same turn: never end your turn while a command or agent you started
> still runs.
> Never loop `sleep` in the foreground or chain a check onto it: use Monitor with
> an until-condition, or one short bare `sleep N` call and check in the next.
>
> Persist the terminal result through `from-issue`'s terminal return procedure,
> whose `workflow-state finish --summary-file -` is the durable write, then
> return exactly its validated JSON stdout and nothing else.

Never inline issue bodies or any content artifact in that prompt.

For `wait`, adapter state consists only of `current_wait_id` and `current_wait_handle`:

- If the response carries the same wait ID as `current_wait_id`, keep the installed handle and arm
  no other observer.
- For a different ID, save the old `current_wait_id` and `current_wait_handle` pair, publish the new
  wait ID with the handle marked uninstalled, cancel the old handle, then arm and store the new
  one-shot observer; never leave the new wait ID paired with the old handle.
- A missing or already exited old handle is an idempotent cancellation; continue arming the
  replacement.
- On unexpected cancellation failure, restore the old pair, do not arm the replacement, and fail
  loudly; the next identical response retries replacement.
- If arming fails after cancellation, clear `current_wait_id` and `current_wait_handle`, surface
  that no wake is installed, and fail loudly.
- A wake counts only when its handle is the one paired with `current_wait_id`; ignore a wake of any
  other handle (a stale wake cannot trigger control or disturb the replacement observer).

Arm the observer as one background `sleep <wait_seconds>`; every wait carries
one (when nothing can proceed without a human, control returns `finalize`, or `delivery_contract`
when a missing contract is all that stops an issue). Never poll or repeat short sleeps.

For `finalize`, first run the stop pass, then clear `current_wait_id`, then cancel the outstanding
handle (a missing/already-exited handle is harmless), and clear `current_wait_handle`. Make no
further `step` to prepare the report.

For `delivery_contract`, a missing delivery contract is all that stops each issue in its `issues`
list, and control armed no deadline, so nothing else will wake the run. When the report's
`ends_run` is true, every listed issue's build was refused: the action ends the run as `finalize`
does, and §5 renders from this response. Otherwise make the next `step` at once; it passes this
report's `contracts_due` back, `step` builds those contracts, and its report takes over from this
one.

## 5. Final report

Render a `finalize` action, or a `delivery_contract` action whose report's `ends_run` is true,
from the bounded summaries in the same interface_version 3 control response.
Produce a per-issue table with issue, state, custody, PR, one-line reason, `blocked_on`, open
delivery stages, and a re-entry line — `orchestrate-control start --repo-root <ledger_repo_root>
<issue> --run-id <run-id>` for an issue suspended on `human_gate`, `external` or `agent_dispatch`
(a direct `/from-issue` is refused with it), and the orchestrate re-invocation for the whole run — every column sourced
from those finalize summaries: `custody` names the attempt or delivery remainder that holds the
issue, `pending_stage_ids` the open delivery stages, and the PR and `discussion_items` come from the
summary's `result`. A null `contract_digest` means the issue ran lifecycle-only: say so, and name
that issue's retained `contract_refusals` `detail` when there was one; a summary still carrying
`delivery_contract_required` is an issue that never received a contract. A summary with a non-null
`contract_digest`, an empty `pending_stage_ids`, an empty `requirements`, a null `owner` and a
non-null `custody` is a delivered issue whose `custody` is a stale record that control will never
dispatch: report it as delivered with that stale custody, never as active or progressing. A `held`
summary is an issue whose PR merged while ship held the issue open with the `needs-verification`
label: report it as held, waiting for a human to verify it, never as queued, progressing or closed,
and with no re-entry line; it stays open, so its dependents stay `blocked` until a human closes it.
A summary whose `worktree_fact` requirement reads `recorded_worktree_absent` or
`recorded_worktree_mismatch` is an issue that cannot resume (its recorded worktree is gone or not on
the issue branch): report it as unable to resume for that reason, never as progressing. Then group
every `discussion_items` entry by issue and call out anything needing a human. List every issue in
that same control response's `admission.waiting` as queued for agent slots, with its summary state.
Below the table, under **Stop failures**, list each owner handle the final stop pass still left a
candidate because its stop failed or its `check-launch` answer was unknown, with its `action_id` and
the failure, and the pass's last sweep when it exited non-zero, with its exit code and, when it
printed a report, its `skipped` launches; omit the list when there is none.
Do not perform a second ledger read or reconstruct omitted history.

An `expired` delta consumes no attempt and never advances the attempt number. Usually it is a
`resumed` on the same attempt in this same sweep, or a `suspended` summary that a later eligible
sweep resumes (tracker neither closed nor blocked, a dispatch slot free, that attempt's recorded
worktree observed). At the anti-zombie bound (parked too many times in a row without a phase advance
or a newly recorded progress marker) the delta's own state reads `stopped`, the attempt is a
`stopped(stalled)` terminal and no resume follows in any later sweep: report it as finished. A
parked suspension arms no deadline, so once nothing else is running the sweep renders `finalize` (or
`delivery_contract` when a missing contract is all that stops some issue) and a re-invocation starts
the later sweep; report such an issue as paused, not progressing. Never report an expiry as
`retried`, `retry_refused` or a spent attempt.
