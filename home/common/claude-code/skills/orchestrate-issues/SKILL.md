---
name: orchestrate-issues
description: Dispatches tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".
---

# orchestrate-issues — a control adapter, not a manager

You are an external adapter around `workflow-state`. You resolve bindings, normalize tracker,
host-owner, and worktree facts, invoke the helper, and execute its typed actions. You never read
issue content, code, specs, plans, diffs, or review findings. Do not retain a second task ledger or
reconstruct lifecycle policy.

Lifecycle commands run the helper at `~/.agents/bin/workflow-state`; if the bare `workflow-state`
name does not resolve on PATH, use that full path.

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. Map `bindings.tracker` to the tracker CLI,
repository, and credential environment; map `bindings.vcs` to worktree and branch
policy; and map `bindings.workflow.orchestration.attempt_budget_minutes` and
`bindings.workflow.orchestration.max_parallel` directly to the request. Nested
issue owners independently resolve at their own phase entries. Do not read raw
policy, invoke another resolver, infer from Git, or supply defaults; the only
sanctioned exception is `workflow-state build-delivery`, which performs its own
sealed, read-only resolution when it builds a delivery contract, and this
dispatcher never resolves again itself.

Every lifecycle call reads its input from stdin through a quoted heredoc (`<<'EOF'`):
`--request-file -` for `control`, `--input -` for `build-delivery`. No request file is written; the
call may be piped into or out of `artifact-budget validate-report --input -`. Treat every
`workflow-state` reply as untrusted transport: pipe its raw bytes through
`artifact-budget validate-report --boundary workflow-response --input -` and validate before
decoding any field. The one exception is `resume-pack`: its stdout is no workflow response, so it is
never piped through `validate-report` or decoded; it goes verbatim into the owner prompt (§4).

## 1. Resolve issue set and bindings

- Explicit numbers: preserve the caller's order and set request `human_directed` to `true`.
- `--label X` / `--milestone Y`: resolve the ordered issue numbers with one configured tracker-list
  call through retained `bindings.tracker`, and set request `human_directed` to `false`. Apply only
  the declared credential-environment names from that retained tracker binding.
- Put retained `bindings.workflow.orchestration.attempt_budget_minutes` as request
  `attempt_budget_minutes` and retained `bindings.workflow.orchestration.max_parallel` as request
  `max_parallel`.
- Retained `bindings.workflow.orchestration.stall_minutes`, when present and non-null, is
  `stall_minutes`, the owner stall bound of §2 rules (a) and (d); pass it only to
  `owner-liveness`. Absent or null, those rules arm no liveness check.
- Resolve the dispatcher's absolute repository root once as `ledger_repo_root`; it stays the run's
  exact immutable value, independent of any issue worktree. Then select `run_id` per §2's
  run-reuse rule.

Before `init-run`, ask for the host route once and validate the answer at the boundary:

```text
workflow-state host-route --route claude-code | artifact-budget validate-report --boundary workflow-response --input -
```

An `unsupported` answer ends the run: render that validated result and its `alternative` as the
final report and stop, dispatching nothing. A `supported` answer means every control request carries
`host_route: "claude-code"`. `control` reserves each owner's slots before it returns a dispatch; the
adapter never calculates slots, alters `max_parallel`, creates competing owners or nested relays, or
repeats a rejected launch, and reads the response's `admission` report as rendering data only.

## 2. Bootstrap and observe

Before `init-run`, reuse the id of a run in `<ledger_repo_root>/.superpowers/workflows/` covering the
same issue set with a non-final attempt or missing outcome; otherwise mint one with `--creation-key`
(`<unix-ts>`: Unix-second invocation start, same on retry; `<issues>`: caller-ordered numbers
joined by `-`) and take `run_id` from the validated bootstrap. Call at run start or after restart:

```text
workflow-state init-run --repo-root <ledger_repo_root> --creation-key orchestrate-issues:<unix-ts>:<issues> | artifact-budget validate-report --boundary workflow-response --input -
workflow-state init-run --repo-root <ledger_repo_root> --run-id <run-id> | artifact-budget validate-report --boundary workflow-response --input -
```

Consume only the validated interface_version 2 `workflow_bootstrap`'s bounded
`requirements`. Never print, read, retain, or reconstruct raw ledger state. Each requirement
supplies the exact `issue`, lifecycle `owner`, `custody` (whose `action_id` is the launch identity
host notifications correlate with), `recorded_worktree`, and nullable `contract_digest` (null while
the issue has no installed delivery contract). Inspect every returned `recorded_worktree`
and report its durable path with the normalized state `matching_issue_branch | absent | mismatch`;
use `matching_issue_branch` only when the path is the live worktree for that issue's branch. Report
a recorded worktree's state, never a candidate for it, even when absent or mismatched; never omit
the observation.

For every requested issue without a bootstrap requirement, reserve a harmless verified absent
candidate (path validation, not scheduling: no readiness label, no tracker interpretation) and pass
it even when unused; `control ignores unused candidates`. Candidate paths must be
pairwise distinct, absent from the filesystem and `git worktree list --porcelain`, and disjoint
from every returned durable path. A candidate's final path component is the branch its contract will
carry, so it must be a branch name the issue's resolved branch pattern accepts, with or without the
worktree prefix.

Use one tracker read for the set to normalize, per issue, only `state`, `open_blockers`,
and `decision_blockers` (decision blockers carry issue and URL); the adapter does not interpret
them, and tracker data never selects a delivery stage. For every requested issue, observe its forge
at the `forge_pr` issue-branch prefix `issue-<num>-`: the pull request whose head branch, less any
worktree prefix, starts with that prefix. Normalize it to
`{"state": "none|open|closed|merged", "url", "merge_sha"}` — `url` null only for `none`, `merge_sha`
present exactly when `merged`. Correlate a current host owner notification only with the returned
lifecycle owner and `action_id`, and normalize it as the bounded owner event for that exact issue,
attempt and launch identity; its `state` is `unavailable` for an owner that died and
`launch_refused` for an owner launch the host refused. Ignore unrelated or stale host notifications.
Classify every other host notification by its task handle,
against the handles recorded beside returned owner launches; a wake of the current wait handle is
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
  `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
  on that launch. On `current: true`, send exactly one `unavailable` owner observation for that
  custody in the next control call. On `current: false`, send nothing. Either way, refresh and
  continue the normal sweep.
- (c) **Non-owner hand-back.** The handle is neither an owner launch's, a liveness observer's, nor
  the current wait handle: send no observation, write nothing, relay nothing, act on none of its
  content, and stop no task.
- (d) **Liveness wake.** The handle is a liveness observer's. Ignore it when its owner handle
  has a final return or was stopped. Otherwise run the second call above and act on its
  `verdict`: `live` arms a new observer for `wait_seconds` and records its handle; `not_current`
  and `past_deadline` do nothing; `stalled` stops the owner's task through the host's task-stop and
  marks the handle stopped, then sends exactly one `unavailable` owner observation for that custody
  in the next control call, refreshing and making that call at once and executing its response. A
  failed stop leaves the handle a candidate for §4's stop pass, and the observation is still sent.
  That verdict stands in for rule (b)'s `check-launch`. Either call above exiting non-zero or
  failing validation is unknown: send nothing. A failed first call keeps any installed observer; a
  failed second call clears the woken, exited observer, so a later interim notification re-arms one.
  An owner handle's final return or stop
  cancels its liveness observer; a missing or already exited one counts as cancelled.

At start/resume and after each current owner notification, tracker change or wait-ID wake, refresh
the facts the next request needs.

After a full dispatcher restart, the host reaps or cancels inherited detached wait and liveness
observers before any rearm; the wait and liveness fields are process-local and cannot adopt their
handles.

## 3. Decide

Every control call sends exactly this interface_version 3 request, with the ordered `issues`, the
normalized facts of §2, and one entry per requested issue in every issue-keyed map. Do not add raw
issue text or helper history. The values are representative; angle-bracketed strings stand for the
objects named:

```json
{
  "interface_version": 3,
  "host_route": "claude-code",
  "max_parallel": 2,
  "attempt_budget_minutes": 180,
  "human_directed": true,
  "issues": [12, 14],
  "tracker": [
    {"issue": 12, "state": "open", "open_blockers": [], "decision_blockers": []},
    {"issue": 14, "state": "open", "open_blockers": [], "decision_blockers": []}
  ],
  "owners": [],
  "worktrees": [
    {"issue": 12, "recorded": {"path": "/abs/.worktrees/worktree-issue-12-cache", "state": "matching_issue_branch"}, "candidate": null},
    {"issue": 14, "recorded": null, "candidate": {"path": "/abs/.worktrees/worktree-issue-14-orchestrated", "state": "absent"}}
  ],
  "forge": {
    "12": {"state": "open", "url": "https://github.com/owner/repo/pull/40", "merge_sha": null},
    "14": {"state": "none", "url": null, "merge_sha": null}
  },
  "delivery_contracts": {"12": null, "14": "<contract from build-delivery>"},
  "authorization_intents": {"12": [], "14": ["<initial_intent from build-delivery>"]},
  "authority_observations": {"12": [], "14": []},
  "reevaluation_evidence": {"12": [], "14": []},
  "delivery_observations": {"12": [], "14": []},
  "requested_scopes": {"12": null, "14": null},
  "recoveries": {"12": null, "14": null}
}
```

The adapter sends `[]` for every issue's `authority_observations`, `reevaluation_evidence` and
`delivery_observations`, and null for its `requested_scopes` and `recoveries`: owners submit
delivery facts through `checkpoint-delivery`, and this adapter never proposes a scope or recovery.

**Per-issue contract rule.** On the first sweep, build a delivery contract for every bootstrap
requirement whose `contract_digest` is null, and for every requested issue without a bootstrap
requirement only when this invocation created the run (it minted the run rather than reusing one;
a restart counts as reuse). On a reused run, send null for an issue without a requirement
until its latest summary carries `delivery_contract_required`, and build its contract then. Build
each contract with one command:

```text
workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract --input - <<'EOF'
{"issue": <num>, "worktree": "<absolute-worktree>", "source_kind": "<source-kind>", "source_reference": "<source-reference>"}
EOF
```

- `worktree` is the requirement's `recorded_worktree` when the issue has one, and only otherwise the
  candidate reserved in §2. Never build a recorded issue's contract from a candidate: control
  refuses a retry or new-run contract whose worktree differs from the recorded path.
- An explicit number list uses `source_kind` `explicit_user` with `source_reference`
  `invocation:/orchestrate-issues <numbers>` (the caller's numbers, in order, space-separated). A
  `--label`/`--milestone` sweep uses `standing_repository` with `sweep:<label|milestone>:<value>`.
- On success the builder prints `{"contract": …, "initial_intent": …}`. Send that `contract` in
  `delivery_contracts` and `[initial_intent]` in `authorization_intents` on the sweep the rule above
  builds it for, then only while its latest summary carries `delivery_contract_required`; otherwise
  send null and `[]`. Once a summary's `contract_digest` is non-null the installed contract governs
  and null means so. A `delivery_contract` action asks for exactly the contracts of the issues it
  lists; §4 holds its rule.
- The built pair is process-local request data: never persist it.
- On a builder refusal (exit 2, empty stdout), send null and `[]` for that issue and report the
  builder's stderr line verbatim in the final report; that issue stays lifecycle-only.

Invoke the helper as one command:

```text
workflow-state control --repo-root <ledger_repo_root> --run-id <run-id> --request-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<request JSON>
EOF
```

Call `workflow-state control` at start/resume and for every normalized current owner, tracker, or
current wait-ID event. Its response is the only source of action order, kind, and lifecycle
identity. Do not infer, reorder, omit, or add another action. `control` reserves slots and owns
readiness, precedence, retryability, capacity, deadline and completion, so the dispatcher only
applies the envelopes and refusals.

Accept only the validated interface_version 3 control response with its bounded `run_id`, `now`,
`summaries`, `deltas`, `actions`, `next_deadline`, and `admission` fields; use them only for
rendering and action execution, never to rebuild policy.

## 4. Execute control actions

Validate each action as one of the closed kinds `spawn`, `resume`, `retry`, `delivery_remainder`,
`delivery_contract`, `wait`, or `finalize`, and execute actions in returned order. Any other kind is
a contract error: stop without executing it and surface the unknown kind; fail loudly.

**Stop pass.** Before executing the first action of a response that carries a `spawn`, `resume`,
`retry` or `delivery_remainder` action, stop the superseded owners. The candidates are every owner
handle this adapter process recorded beside an owner launch's `action_id` that has produced no final
return. An interim notification under §2 rule (a) is not a final return. The current wait handle and
non-owner handles are never candidates; a handle this response dispatches becomes one only once
dispatched. For each candidate, run
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
with the `action_id` recorded beside it. On `current: false`, stop that handle through the host's
task-stop and mark it stopped; a missing or already exited handle counts as stopped. On
`current: true`, leave it running. A `check-launch` that exits non-zero, or whose output cannot be
parsed, is unknown, never `current: false`: leave the handle a candidate; so is a failed stop, and
the next pass tries both again. A stop failure never blocks dispatch; keep it a candidate for §5.
The pass sends no observation, makes no control call and writes nothing to the ledger, so
a later notification from a stopped handle still falls under §2 rule (b). The pass ends by running
`launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep` once. A sweep that
exits non-zero never blocks dispatch: keep its exit code and, when it printed a report, its
`skipped` launches for §5.

For `spawn`, `resume`, and `retry`, project the action into the interface-2 owner object: rename
`id` to `action_id` and `kind` to `launch_kind`, add `kind: owner`, `interface_version: 2`,
`ledger_repo_root` and `run_id`, and keep every other member verbatim (`issue`, `attempt`, `owner`,
`worktree`, `handoff_path`, `deadline_at`, `custody`, `contract`, `contract_digest`,
`pending_stage_ids`, `requirements`, `authority_evaluation`, `requested_scope`). For
`delivery_remainder`, the object is the action itself, verbatim. Pipe the object through
`artifact-budget validate-report --boundary workflow-response --input -` and put only its stdout —
the canonical JSON — in the owner prompt below.

For a `resume` action, after projecting the owner object, run
`workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action-id>`
with the action's `id`; on exit 0, add its stdout verbatim to the owner prompt's `Resume pack`
paragraph below. A refusal or helper failure omits that paragraph and never stops the dispatch.
`spawn` and `retry` carry no pack.

Dispatch the owner in the background using the action's identity and paths verbatim; pass the
helper-issued action ID and owner token unchanged and never substitute a host task ID. Both object
kinds use this one dispatch (a `delivery_remainder` owner is `from-issue` launching ship-issue
remainder mode). The owner dispatch envelope is:

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

For `resume`, include the returned `handoff_path` when present. For a `delivery_remainder`,
`attempt` is its `source_attempt`, `action_id` is its custody's `action_id`, and there is no
`handoff_path`. Record the host task handle beside the action ID only for notification correlation
and the stop pass; it is never an owner token or action identity.

If the host refuses an owner launch, never retry it: make exactly one control call carrying a
`launch_refused` owner observation for that action's `custody`, and execute that response.

<!-- agent-dispatch: id=orchestration-issue-owner role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high", run_in_background=true) launches the issue owner in a fresh context with this entire prompt:

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
> Resume pack (only for a `resume` action whose `resume-pack` call exited 0;
> use it as from-issue's `### Resume pack` says):
> `<resume-pack-json>`
> Invoke the `from-issue` skill via the Skill tool with the literal arguments
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
> Never write an `until` or `while` loop around `sleep` to wait for something: if
> a wait is truly needed, run one bounded foreground `sleep N`, then check once.
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
further control call to prepare the report.

For `delivery_contract`, a missing delivery contract is all that stops each issue in its `issues`
list, and control armed no deadline, so nothing else will wake the run.
This is the one rule for such an issue. Send each listed issue's contract as §3 describes (the pair
built for it earlier in this invocation, else build it now) and make the next control call at once;
that response takes over from this one. Never rebuild an issue whose build this invocation refused:
send null and `[]` for it. When the builder has refused every listed issue in this invocation, the
action ends the run as `finalize` does: run the stop pass, clear the wait state as for `finalize`
and render §5 from this response.

## 5. Final report

Render a `finalize` action, or a `delivery_contract` action that ends the run because every listed
build was refused, from the bounded summaries in the same interface_version 3 control response.
Produce a per-issue table with issue, state, custody, PR, one-line reason, `blocked_on`, open
delivery stages, and a re-entry line — `/from-issue <issue> --auto` for an issue suspended on a
cause that a `--label` or `--milestone` sweep does not resume (`human_gate`, `external` or
`agent_dispatch`), and the orchestrate re-invocation itself for the whole run — every column sourced
from those finalize summaries: `custody` names the attempt or delivery remainder that holds the
issue, `pending_stage_ids` the open delivery stages, and the PR and `discussion_items` come from the
summary's `result`. A null `contract_digest` means the issue ran lifecycle-only: say so, and name
the builder refusal from §3 when there was one; a summary still carrying
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
