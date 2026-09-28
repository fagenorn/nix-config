# Transaction core 3/6: administrative protocol — write intent, inspect before retry, retry budget

Design for [#206](https://github.com/fagenorn/nix-config/issues/206), slice 3 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-28, against main `ce33847`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's delegated
scope, recorded in the decision ledger, not a human answer.

## Problem

Slices 1 and 2 (#204, #205) give a transaction a closed lifecycle and fenced custody, but the
transaction still cannot touch the outside world safely. Whoever publishes or activates calls a
provider directly, and the core never learns that a call was about to happen, happened, or failed.
The settled decisions need that knowledge before any consumer can be trusted with a side effect:

- #82 requires a durable intent — stable action and attempt identity, idempotency key and fence —
  before every external call, so a runner that dies mid-call leaves something to reconcile rather
  than a blind duplicate on resume. Re-entry must inspect first and classify the effect as
  `absent | in_progress | satisfied | diverged | unknown`; only proven `absent` may be retried.
- #82 bounds automatic retries: one initial try plus at most two automatic retries, all within
  fifteen minutes of the first retryable failure, and only for a retry-safe error class.
- #85 makes the core, not the workflow, own scheduling and retry over an adapter seam of
  `inspect` and `invoke`, and requires the core to inspect after every invoke.
- #117 keeps these invocation retry ordinals separate from workflow attempt ordinals, and #205
  D19 hands slice 3 #92's exception: custody is never quiesced while an issued call is still
  being observed.

The prototype (`prototype-release-transactions/` at `dc98ba9`) ran the `throttled_retry` and
`resume_after_crash` scenarios with in-memory attempt records that no crash could survive. This
slice makes them durable.

## Solution

Add an **administrative protocol** to the transaction core: two fenced store operations through
which a custody holder inspects and invokes a named action. The caller passes an **effect** — an
object with `inspect` and `invoke` — and the core makes the calls itself, so no external call
through the core can precede its recorded intent. The protocol's facts are four new event types in
the transaction's own history. A per-action view is derived from them on every load, so there is
no second ledger (D2).

One invocation writes `state.json` twice. The first write records the intent under the lock. The
lock is then released and the effect is invoked and inspected. The second write records the
return and the post-inspection, again under the lock. A crash between the two writes leaves an
open intent. The next holder must inspect before any retry, and a recorded `satisfied` inspection
settles the action without another call.

Three options were weighed for who makes the external call (D3):

- **The core calls the effect it is handed (chosen).** Intent-before-call is structural, #85's
  post-invoke inspection cannot be skipped, and retry eligibility is decided where the history is.
- **Record-only operations the caller brackets around its own call.** The core could not tell a
  call made without an intent from one never made, so the first acceptance criterion would rest
  on caller discipline.
- **The core calls while holding the transaction lock.** The lock is non-blocking, so a slow call
  would turn the holder's own `renew` into `TransactionBusy` and let the lease lapse mid-call.

## Decisions

### Modules

A new pure module, `agent_tools.transaction_invocation`, owns the protocol's document rules (D1):
the vocabularies, the retry constants, action-id derivation, the effect-result shape checks, the
fold that validates action events and builds the per-action view, and the retry-eligibility
judgment over integer milliseconds. It reads no file, lock or clock. `transaction_history`'s
validator and snapshot fold call it, and `transaction_core` gains the two store operations and
re-exports the new public names. The import order becomes core → history → invocation → custody →
storage. The new module is standard-library only, has no command-table row, is covered by the Nix
build's recursive import check, and joins the neutrality check.

### Interface

```python
action_id(transaction_id: str, name: str, parameters: dict) -> str

TransactionStore.inspect_action(custody, *, name, parameters, effect) -> Transaction
TransactionStore.invoke_action(custody, *, name, parameters, effect) -> Transaction
```

- **Action identity.** `action_id` is `act_` followed by the first 32 hex digits of
  `telemetry_digest([transaction_id, name, parameters])`. Re-deriving it from the same inputs gives
  the same id, whatever the key order of `parameters`. `name` is a non-empty string, and
  `parameters` is a strict, secret-free JSON object under the rule a created `subject` already
  follows. The action id is also the idempotency key the effect receives; there is no separate key
  (D4). Both operations derive the id themselves, so a caller never presents one.
- **Attempts.** Each action's attempts are numbered 1, 2, 3 in order. The pair of action id and
  attempt number is the attempt id, and it increases monotonically across runners, custody spans
  and crashes, because the next number is folded from history (D4).
- **Effect.** An effect is any object with `inspect(request)` and `invoke(request)`. The request is
  a read-only mapping of `transaction_id`, `action_id`, `name`, `parameters`, `fence` and
  `attempt`. For `invoke`, `attempt` is the attempt being made; for `inspect`, it is the latest
  attempt, or 0 before any. `inspect` returns `{"outcome", "reference"}`, where the outcome is one
  of `absent`, `in_progress`, `satisfied`, `diverged` or `unknown` (#82, #85). `invoke` returns
  `{"result", "error_class", "reference"}` with `result` one of `accepted`, `rejected` or
  `unknown`. `error_class` is null exactly when the result is `accepted`, and otherwise comes from
  the closed set `transient_transport`, `provider_throttled`, `provider_unavailable`,
  `invalid_input`, `authorization_denied`, `precondition_failed` and `unsupported_operation`; only
  the first three are **retry-safe** (#82). `reference` is a non-empty, secret-free string. Any
  other shape is `EffectResultInvalid`, and nothing from that call is recorded (D11).
- **`inspect_action`** is fenced and runs in any nonterminal state while custody is held,
  including a parking, so a resuming holder can reconcile before it moves the lifecycle. Under the
  lock it performs the fenced check and releases the lock. It then calls `effect.inspect` and
  re-takes the lock. A second fenced check follows, which a lapse in between turns into
  `StaleCustody` with nothing recorded. On success it appends `action_declared` if this is the
  action's first event, then `action_inspected` stamped with the held fence. While the action's
  latest attempt is open under the **held** fence, `inspect_action` is refused
  `attempt_in_flight` before any call (D14).
- **`invoke_action`** is fenced and runs only in `publishing` or `activating`, the lifecycle's
  effect states; a parked transaction cannot invoke (D8). When the action's latest inspection is
  `satisfied`, it returns the unchanged snapshot without calling or writing: the protocol records
  success instead of calling again. Otherwise the retry rules below must admit the attempt. The
  first write appends `invocation_intended` for attempt *n*, and the lock is released. The core
  then calls `effect.invoke` and `effect.inspect` and re-takes the lock. After a second fenced
  check, the second write appends `invocation_returned` and the post-invoke `action_inspected` (D3).

**Closing an open attempt takes a new custody span (D14).** Within one span, only
`invoke_action`'s own second write closes the attempt it opened. The core cannot tell a dead
runner from a slow one, because the credential is an ordering token that any process may rebuild
(#205). Only a fence change proves the old call's runner lost custody. A runner that stays alive
after an effect raised therefore releases and reacquires, or lets the lease lapse, before it
inspects. A late landing of the old call on the provider side is the remaining race. The
idempotency key is stable across attempts, so the provider sees the same key, and fence
enforcement on the mutation route belongs to the adapter slice (#117 seam 3).

The core catches nothing an effect raises. An exception from `invoke` or `inspect` propagates to
the caller, and the intent stays open. That uncaught exception is also the crash seam: an effect
that raises before touching its world is a runner dying between intent and call (D3, D12).

### Inspect before retry and the retry budget

An attempt is **open** from its `invocation_intended` until an `action_inspected` for that action
follows it. `invoke_action` first refuses `state_not_effectful` outside the effect states, then
returns a satisfied action unchanged, then admits attempt *n* only when all of these hold, checked
in this order under the lock on one clock reading (D5, D6):

1. The action's latest event is an `action_inspected` with outcome `absent` whose fence equals the
   held fence. For attempt 1 this is the no-clobber pre-inspection; for a retry it is the
   inspection that closed attempt *n − 1*: the post-invoke one, or a resuming holder's. A
   reacquisition changes the fence, so an inspection from an earlier span never licenses a call.
   Failure: `inspection_required`, when no inspection follows the latest attempt or when one
   exists under an older fence; `not_absent`, when the latest inspection's outcome is anything but
   `absent` or `satisfied`.
2. For a retry (*n* > 1), attempt *n − 1* was retry-safe. It is retry-safe when it returned
   `rejected` or `unknown` with a retry-safe class, or when it is **interrupted**: no
   `invocation_returned` was ever recorded for it, and rule 1 has since proved it `absent`. An
   `accepted` attempt that now reads `absent`, or any other class, is `not_retryable`.
3. *n* ≤ `MAX_ATTEMPTS` (3), else `budget_exhausted`. That is a fourth automatic try.
4. For a retry, the clock is at most `RETRY_WINDOW_MS` (900 000) past the **first retryable
   failure**: the `at` of the first `absent` inspection after attempt 1. Otherwise it is
   `window_closed`.

Every refusal is `InvocationRefused`, carrying one `reason` from that closed set, plus
`state_not_effectful` for an invoke outside the effect states and `attempt_in_flight` for an
inspection of an attempt still open under the held fence. It is raised before any write and
before any effect call (D7). The protocol never moves the lifecycle itself: the caller parks, as
every other advance in slices 1–2 is caller-driven, and the refusal reason is the typed attention
cause #82 names (`retry_exhausted` is `budget_exhausted` here). Every retry through
`invoke_action` is automatic. The #82 authorized extra attempt, profile-lowered limits, backoff
schedules and observation deadlines are out of scope (D10).

The validator re-checks everything in the history that does not depend on a clock. Attempts are
numbered consecutively from 1 and never exceed 3. Each intent follows an `absent` inspection of
that action under the same fence. At most one `invocation_returned` follows each intent, before
the attempt's closing inspection, and under the intent's fence. An inspection that closes an
attempt with no return carries a fence other than the intent's. Each retry follows a retry-safe
predecessor. `action_declared` precedes every other event of its id, and its id re-derives from
its `name` and `parameters`. Every fenced action event sits inside an open custody span whose fence
it equals. The fifteen-minute window is enforced only at invoke time on the store clock, because
event `at` is not monotonic by contract (#205 D3) (D6).

### Transaction state `transaction-state/v3`

The event vocabulary grows, so the schema string moves to `transaction-state/v3`. A v2 document
fails closed with `StateInvalid` naming its version. The module still has no caller, so no v2
state exists outside tests, which is #205 D9's reasoning applied again (D2). The top-level key set
is unchanged. New event types, each a closed object with `seq`, `type` and `at` plus:

| Type | Fields |
|---|---|
| `action_declared` | `action_id`, `name`, `parameters` |
| `action_inspected` | `action_id`, `outcome`, `reference`, `fence` |
| `invocation_intended` | `action_id`, `attempt`, `fence` |
| `invocation_returned` | `action_id`, `attempt`, `result`, `error_class`, `reference`, `fence` |

`Transaction` gains `actions`: one read-only entry per declared action, in declaration order,
derived on every load and never stored (#205 D20). Each entry carries these fields:

- `action_id`, `name` and `attempts` (the latest attempt number, 0 before any).
- `status`: `declared` with no inspection yet; `open` while the latest attempt awaits inspection;
  otherwise the latest inspection's outcome.
- `last_error_class`, or null.
- `retry_eligible`: whether rules 2 and 3 admit the next attempt now that the latest inspection is
  `absent`.
- `retry_deadline_at`, the first retryable failure's `at` plus the window, or null.

Rule 4 needs the clock, so the view states the deadline rather than a verdict.

### Interaction with custody and the lifecycle

- **Quiesce exception (#92, #205 D19).** While the transaction is parked past
  `PARKED_CUSTODY_WINDOW_MS`, `renew` keeps extending instead of quiescing when any action is
  **observed**: `open`, or with latest inspection `in_progress`. Once nothing is observed, the
  existing quiesce applies. `unknown` and `diverged` are not observations in flight, so they do
  not hold custody (D9).
- **No terminal over unresolved reality (#82).** `advance` into a terminal is `TransitionRefused`
  while any action is `open`, `in_progress` or `unknown`. The caller's `external_state="known"`
  cannot outvote the history (D9).
- Refusal precedence follows #205 D27. Argument-shape `StateInvalid` comes first, before any lock,
  as in slices 1–2. Under the lock a terminal refuses both operations with `TransitionRefused`,
  then the fenced check runs, then `InvocationRefused` in the order above.

### Errors

Two refusals join the hierarchy under `TransactionError` (D7):

- `InvocationRefused`, with `reason` in `inspection_required`, `not_absent`, `not_retryable`,
  `budget_exhausted`, `window_closed`, `state_not_effectful` and `attempt_in_flight`.
- `EffectResultInvalid`, for an effect result outside the closed shapes.

`transaction_core` re-exports both.

### Sweep fixture

The world fixture counts `invoke` calls per action id, so a row can assert what the provider saw.
It also gains a `crash_before_invoke` fault: once armed, the next `invoke` raises a fixture-only
`ExecutorCrash` before touching the world. The executor's `run_phase` now drives each node through
the core. It calls `inspect_action` on the node, which is the pre-inspection, and skips a
satisfied node. It then calls `invoke_action` until the node is satisfied or refused, parking on
any other outcome or refusal. Before each retry it moves the world clock 30 seconds, so the window
arithmetic runs on the world clock (D12). Two scenarios join `SCENARIOS`, each with a row for all
four shapes:

- `throttled_retry`, ported from `dc98ba9`. Under the `throttle_once` fault every action's first
  invoke is rejected `provider_throttled` and its inspection reads `absent`, and one automatic
  retry succeeds. The row lands on `succeeded` along the success path, with the success row's
  custody events. Every action has two attempts: attempt 1 returned `rejected` with
  `provider_throttled`, and attempt 2 returned `accepted` with a `satisfied` inspection. The world
  counts two invokes per action.
- `resume_after_crash`, ported from `dc98ba9` with the crash moved to between intent and call, as
  #206 demands. The first publication action's attempt 1 raises `ExecutorCrash`, and the executor
  is gone with its lease. The world clock passes the TTL, and the reaper parks the transaction.
  A second executor reacquires, which moves the fence to epoch 2, and advances back to
  `publishing`. Its blind `invoke_action` on the crashed action is refused `inspection_required`
  with nothing written. It then resumes `run_phase`, whose `inspect_action` records `absent`, and
  the retry is attempt 2. The row lands on `succeeded` with
  `attention_required, publishing` inserted after `publishing`, and its custody events are those of
  `lease_lapse`. The crashed action's history reads intent 1, no return, inspection `absent` under
  the new fence, then intent 2, and the world counts exactly one invoke for it.

The asserted table grows a fourth column, the expected attempts per action, and the earlier
`success`, `lease_renewal` and `lease_lapse` rows keep their landings with one attempt per action.
The test still asserts against a reloaded store.

### Documentation

CLAUDE.md's sentence on `agent_tools.transaction_core` names slice 3's protocol and the new
sibling module, still caller-less until #125. The new test file joins `just agent-workflow-tests`.
The #204 and #205 specs are point-in-time records and stay unedited.

## Test seams

The slice keeps the three seams of #204 and #205 and adds none (D13):

1. **Store interface plus documented layout**, under a temporary root with an injected fake clock
   and **fake effects**: small in-memory worlds whose recorded effects and invoke counts are the
   external side's observable state, never a mock's call log. This seam carries every acceptance
   criterion:
   - A simulated crash, an effect raising before it touches its world, leaves `state.json` holding
     an open intent and the world unchanged. `invoke_action` then refuses `inspection_required`, and
     after `inspect_action` reads `absent` it retries as attempt 2.
   - An effect that applies the change and then raises leaves `inspect_action` refused
     `attempt_in_flight` under the same span. After a reacquisition, `inspect_action` reads
     `satisfied`, `invoke_action` returns without a call, and the world count stays 1.
   - A fourth automatic try is refused `budget_exhausted`, and a retry 900 001 ms after the first
     retryable failure is refused `window_closed`, while one at exactly 900 000 ms is admitted.
   - A non-retry-safe class is refused `not_retryable`, and an inspection from before a
     reacquisition is refused `inspection_required`.
   - `action_id` is stable under re-derivation and parameter key order and differs with any input,
     and attempt numbers increase across a crash and a reacquisition.
   - Each refusal leaves `state.json` byte-identical and the world untouched, a malformed effect
     result is `EffectResultInvalid`, the quiesce exception and the terminal refusal hold, the v3
     validator's new rules are checked by hand-edited documents, and v2 is refused.
2. **Fixture executor against the store**: the asserted sweep table, now five scenarios by four
   shapes.
3. **Neutrality checker** over all five transaction modules.

Protocol tests live in a new test file beside the custody tests. Earlier test files change only
where the schema string and the new required pre-inspection demand it.

## Out of scope

- The #82 authorized extra attempt after exhaustion (#84 authorization).
- Profile-lowered retry limits, backoff schedules, `Retry-After` handling, invocation timeouts and
  observation deadlines (#124 profiles).
- Adapter `describe`, adapter identity and conformance, and provider-side precondition and fence
  enforcement on the mutation route (#85 adapter slice, #117 seam 3).
- Proof plans, obligations and gating `published`/`succeeded` on the action set (slice 4, #207).
- Recovery actions and invoking from `recovering` (slice 5, #208).
- Terminal receipts (slice 6, #209).
- Recording a return that arrives after custody lapsed; the next holder's inspection covers it.
- The attempts cutover (#125), any command-table row, Nix or host change, and state cleanup.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A new pure `agent_tools.transaction_invocation` holds vocabularies, retry constants, action-id derivation, effect-result checks, the action fold and eligibility over integer ms; the two store operations join `TransactionStore` in the core; import order core → history → invocation → custody → storage; the neutrality check covers the new module. | the-bar single responsibility; #205 D33/D34 (pure model outside the core, the core's review-budget cap); agent-helpers rule 1. | Growing the core or history past their caps, or a mixin carrying store operations (#205 D33 rejected it: one class across modules, no second user). |
| D2 | The schema becomes `transaction-state/v3` with four new event types, v2 fails closed without migration, the top-level key set is unchanged, and the per-action view is derived on load, never stored. | #205 D9, D20; #82 unknown schemas fail closed; #206 "no second ledger". | Additive events under v2 (a v2 reader's closed dispatch would meet unknown types, and the schema string would no longer name the vocabulary) or a stored `actions` projection (a second truth). |
| D3 | The core makes the external calls through an `effect` passed per call, holds no lock across a call, writes the intent before the call and the return plus post-inspection after it, and lets every effect exception propagate so the intent stays open. | #82 durable intent before every call; #85 core owns scheduling and always inspects after invoke; #205 D25 non-blocking locks; the-bar root causes (no muting catch). | Record-only operations around a caller's own call (intent-before-call becomes caller discipline) or calling under the lock (the holder's `renew` goes busy and the lease lapses mid-call). |
| D4 | `action_id` = `act_` + first 32 hex of `telemetry_digest([transaction_id, name, parameters])`, which is also the idempotency key; attempts are per-action ordinals folded from history, so the (action id, attempt) attempt id increases monotonically across runners and crashes. | #82 deterministic action ids, monotonic attempt ids, stable idempotency key; agent-helpers rule 4 (one digest home); #117 invocation ordinals separate from workflow attempts. | A caller-chosen id (no re-derivation guarantee), a separate idempotency key (two identities that must agree), or a transaction-global attempt counter (couples unrelated actions' budgets). |
| D5 | Every invoke, the first included, needs the action's latest event to be an `absent` inspection under the held fence; the post-invoke inspection closes an attempt, and a reacquisition voids an older inspection. | #82 re-entry inspects first, only proven absent retries; prototype pre-inspection (no-clobber); #92/#205 snapshot evidence voided by an epoch change. | An implicit inspect inside `invoke_action` (the "retry without inspect is refused" criterion becomes untestable) or accepting an inspection from an earlier custody span. |
| D6 | A retry needs a retry-safe predecessor — `rejected`/`unknown` with `transient_transport`, `provider_throttled` or `provider_unavailable`, or an interrupted attempt with no recorded return, now proved `absent` — at most 3 attempts, and a clock at most 900 000 ms past the `at` of the first `absent` inspection after attempt 1 (inclusive); the window is judged at invoke time, and the validator checks the rest. | #82 budget and retry-safe classes; #206 demo "resumes through inspect"; prototype `<=` window; #205 D3 (`at` not monotonic). | Interrupted attempts not retryable (a crash before the call could never resume, contradicting #206) or validating the window from stored `at` (a clock step would invalidate honest history). |
| D7 | Protocol refusals are one `InvocationRefused` with a closed `reason` (`inspection_required`, `not_absent`, `not_retryable`, `budget_exhausted`, `window_closed`, `state_not_effectful`, `attempt_in_flight` per D14) raised before any write or call; a malformed effect result is `EffectResultInvalid`; invoking a satisfied action is a no-op that returns the snapshot. | #204 D9/#205 D21 typed refusals before any write; the-bar fail loud and token economy; #206 "records success instead of calling again". | One error class per reason (six classes for one decision point) or refusing a satisfied invoke (callers re-running after resume would have to special-case success). |
| D8 | The protocol never moves the lifecycle; the caller parks with the refusal reason as the typed cause; `invoke_action` runs only in `publishing`/`activating`, `inspect_action` in any nonterminal state with custody. | Slices 1–2: every transition but `reap`'s is caller-driven; #82 lease loss and attention stop effects; #117 resume reconciles before resuming. | Auto-parking inside the protocol (a second transition authority beside `advance`) or invoking from a parking (a parked transaction would still cause effects). |
| D9 | `renew` does not quiesce a parked transaction while any action is `open` or `in_progress`; `advance` into a terminal is refused while any action is `open`, `in_progress` or `unknown`. | #205 D19 hands slice 3 #92's exception; #117 "observe an issued call before release"; #82 "unknown external reality is never terminal". | Deferring the exception (custody could drop while a call is in flight) or trusting the caller's `external_state` over the history. |
| D10 | Only automatic retries are in scope; the #82 authorized extra attempt, profile-lowered limits, backoff and observation deadlines are deferred. | #206 scope (retry budget 1 + 2 in fifteen minutes); #84 owns authorization, #124 profiles; YAGNI. | Shipping the extra-attempt grant now (needs #84 grant scopes that do not exist yet). |
| D11 | Effect results are closed: inspect `outcome` of five values, invoke `result` of three, and `error_class` null exactly when accepted, otherwise one of seven classes, of which three are retry-safe; only a secret-free `reference` string is recorded. | #82 and #85 vocabularies and non-retryable classes; #72 secret-free state; the-bar fail loud. | Free-form error classes (a typo would silently be non-retryable) or recording raw provider payloads (#85 keeps them in their owning facility). |
| D12 | The sweep adds `throttled_retry` (every action throttled once, one automatic retry) and `resume_after_crash` (crash between intent and call on the first publication action, reap, reacquire, refused invoke, inspect, retry) for all four shapes; the world counts invokes and gains `crash_before_invoke`; the table gains an attempts column. | #206 demo and acceptance; prototype `dc98ba9` scenarios; #205 D22 (the executor grows with the core). | Porting the prototype's crash-after-invoke (#206 names the intent-to-call gap) or a single-shape fixture. |
| D13 | Keep the three seams; fake effects are in-memory worlds asserted by their effects and invoke counts, never by a call log. | #205 D23; the-bar tests assert observable behavior. | Unit tests over the invocation module's internals (they bind the tests to the module split). |
| D14 | Grill: within one custody span only `invoke_action`'s own post-invoke write closes the attempt it opened; `inspect_action` on an attempt open under the held fence is refused `attempt_in_flight`, so an interrupted attempt is closed only under a new fence, and the validator requires that of any return-less closing inspection. | Grill scenario: the same credential inspects mid-flight, reads `absent`, and D6's interrupted rule admits a duplicate while call 1 is still landing; #92 fencing is the only proof a runner lost custody; #205 the credential is a rebuildable ordering token. | Letting any holder inspect an open attempt (a live runner's own in-flight call becomes retryable) or a same-span in-flight marker (a process-local fact the core cannot persist truthfully). |
