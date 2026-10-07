# Stop superseded owner handles before a post-expiry resume (#275)

Slice S1 of the [launch process reaping design](2026-10-06-launch-process-reaping-design.md).
That design's D1 (the adapter stops superseded owners) and D2 (the ledger and
`workflow-state` stay unchanged) are settled. This spec applies D1 without the
`launch-scope reap` sweep, which belongs to S2.

## Problem

When an attempt passes its deadline, the controller demotes it to a suspension
and resumes it under a new launch in the same sweep, in the same worktree. The
predecessor owner's host task keeps running. Then two owners share one worktree.
The #222 fences stop the stale owner from committing (`launch-commit`) and from
writing to the forge (`check-launch`). They do not stop its reads, builds,
scratch state or processes. orchestrate-issues is the only party that holds
host task handles, and today it never stops one.

## Solution

orchestrate-issues gains one stop pass, which needs no judgment:

1. For every recorded owner handle with no final return, run
   `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
   with the `action_id` recorded beside that handle.
2. Stop each handle that reads `current: false` through the host's task-stop.
   Then mark it stopped. A handle that is missing or has already exited counts
   as stopped.
3. Only after that, execute the response's actions in returned order.

The pass runs at two points. It runs before a control response's actions
whenever that response carries a dispatch action, and it runs at `finalize`
before the report is rendered. A stop failure, or a `check-launch`
answer the adapter cannot read, is named in the final report. It never blocks
dispatch.

## Decisions

- **Where the rule lives.** It goes in §4 *Execute control actions*, ahead of
  the dispatch prose. The `finalize` clause invokes it, and so does the
  `delivery_contract` case that ends the run "as `finalize` does". §2 rules
  (a), (b) and (c) are not edited (AC3).
- **The handle set.** A handle qualifies when the adapter recorded it beside an
  owner launch's `action_id` for a `spawn`, `resume`, `retry` or
  `delivery_remainder`, and the handle has produced no final return. An interim
  notification under rule (a) is not a final return. Handles that the current
  response is about to dispatch join the set only after they are dispatched. Neither the current wait handle
  nor any non-owner handle is ever in the set. The set is local to the adapter
  process, the same way the wait fields are.
- **What a stop writes.** Nothing. The pass sends no observation, makes no
  control call and writes nothing to the ledger. If a stopped handle notifies
  later, it falls under rule (b), unchanged: `check-launch` reads
  `current: false`, so the adapter sends nothing.
- **Failure handling.** A failed stop leaves the handle in the set, so the next
  pass tries it again. The failed stop is listed in the final report. A
  `check-launch` that exits non-zero, or whose output the adapter cannot parse,
  is treated the same way and never as `current: false`.
- **Final report.** §5 gains a short list of stop failures, kept apart from the
  per-issue table. These are facts local to the adapter, not fields of the
  finalize summary, so the rule against a second ledger read still holds.
- **Agents an owner spawned.** Stopping an owner ends the agents it spawned
  (#222 D8). Processes that a detached command reparented are left to S2.

## Test seams

- **`home/common/agent-skills/tests/test_workflow_skill_contracts.py`**, run by
  `just agent-workflow-tests`. Add one new test class over the normalized
  orchestrate-issues text, using the `assert_ordered` prior art of
  `InterimOwnerNotificationContractsTest`. It has two tests, and both must fail
  at base:
  - The order test (AC1) checks this sequence in §4: the stop-pass anchor,
    then the `check-launch` command, then `current: false`, then task-stop,
    then the dispatch prose. It also checks that the `finalize` clause names
    the pass.
  - The failure-semantics test (AC2) checks the missing-or-exited-as-stopped
    sentence, the sentence saying a stop failure does not block dispatch, and
    §5's stop-failure list.
- The existing rule (a), (b) and (c) assertions in the dispatcher-fence and
  interim-notification classes stay unchanged and green (AC3).
- No seam in this repository can exercise the host's task-stop itself
  (parent D10). The contract test is its only pin.

## Out of scope

- `launch-scope` and its `exec`, `scratch` and `reap` verbs, including the
  `reap --sweep` step that parent D1 places after the stops (S2 and S3).
- The guard's refusal of detaching words (S4).
- Any `workflow-state`, ledger schema or response-shape change (parent D2).
- Finding or adopting host tasks from before an adapter restart. Only handles
  recorded by this adapter process are checked.
- Codex parity, because the Codex stub has no adapter (parent D12).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The stop pass runs once per control response that carries a dispatch action (`spawn`, `resume`, `retry`, `delivery_remainder`), before its first action, and once at `finalize` (including the all-refused `delivery_contract` end), before the report | Parent D1 ("before any dispatch and at `finalize`"); the reaper resumes in the same sweep that expires, so the predecessor is superseded by the time the response arrives | Running before every response, wait-only ones included, costs a `check-launch` per wake with no dispatch to protect. Running it per dispatch action repeats the same checks within one response |
| D2 | The set is the owner handles this adapter process recorded with no final return. A rule (a) interim notice is not a return. Wait and non-owner handles are excluded, and nothing is discovered after a restart | §4 records the handle beside the action ID "only for later notification correlation"; the wait fields are already process-local | Enumerating host tasks would make the adapter depend on host introspection the contract does not define |
| D3 | A `check-launch` that exits non-zero or cannot be parsed counts as unknown. The handle is not stopped, the failure is reported, and the handle is retried on the next pass. A failed stop is likewise reported and retried, and neither blocks dispatch | Parent D1 (a stop failure does not block); the-bar fail loud. The #222 fences still hold for a stale owner | Stopping on uncertainty could kill the current owner, which is the irreversible direction. Blocking dispatch stalls the run on a host failure |
| D4 | The pass writes nothing and observes nothing. A later notification from a stopped handle stays under rule (b), unchanged | Parent D2; AC3; rule (b) already sends nothing on `current: false` | Sending an `unavailable` observation for a custody that is already non-current is stale input that control would have to discard |
| D5 | The rule sits in §4 and the stop failures in a separate §5 list. The seam is one new `assert_ordered` class in `test_workflow_skill_contracts.py` with an order test and a failure-semantics test | AC1–AC3; prior art in `InterimOwnerNotificationContractsTest`; parent D10 | Placing the rule in §2 next to rules (b) and (c) risks editing their text and breaking AC3 |
| D6 | §5's stop-failure list names only the handles the final stop pass still leaves unresolved (failed stop or unknown `check-launch`), each with its `action_id` and failure, and is omitted when empty | Spec "Final report" decision; D3's retry-on-next-pass makes an earlier failure that a later pass resolved no longer a fact | Listing every failure ever seen in the run reports handles that are already stopped, which reads as a live hazard |
| D7 | The `orchestration-dispatcher` instruction-load ceiling is raised to the edited SKILL.md's byte count in the same task, with a "Ceiling raised for #275" note | `instruction-load.json` precedent (#155 D10): the ceiling equals the file's size at base, so any added prose breaches it | Leaving `instruction-load.json` out of scope as the issue's target-file list does would turn `just agent-workflow-tests` red |
