# Ledger clock (#309)

`workflow-state` reads the time from the system clock. Agents stop typing
timestamps into lifecycle calls, and stop writing wait loops.

## Problem

Every ledger-writing `workflow-state` call needs a time today: a required
`--now` flag, or a required `now` member in a request. Agents type that time by
hand. In nodocom run `orch-1838-1840-1841-1850-1851-1857` a ship worker typed a
time about 15 minutes ahead of the clock into four `checkpoint-delivery` calls.
The helper stored it as the run's `updated_at`. Another owner's correctly timed
`release-worker` was then refused with `release-worker time must not move
backward`. Nothing told that owner how long to wait, so it wrote a wait loop
that never ended. The loop held a dispatch slot for about 2.5 hours and blocked
another issue. A second worker in the same run typed a time 53 minutes ahead.

There are two faults. The ledger trusts a time no agent can be relied on to
produce, and the refusal gives no exit an agent can act on.

## Solution

1. **One clock seam.** `workflow-state` gets one function that returns "now":
   the system clock in UTC, truncated to whole seconds. Every time the helper
   uses comes from that function or from a validated supplied value (D1, D2).
2. **`now` is optional everywhere it is accepted.** The `--now` flag of the
   eight ledger-writing commands, the `now` member of the `control` and
   `direct-owner` requests, and the `now` member of the `build-delivery --kind
   contract` input may all be omitted. An omitted time is the seam's value
   (D3, D4, D5).
3. **Future times are refused.** A supplied time more than 60 seconds ahead of
   the seam's value is refused before the ledger lock is taken. The message
   names the lead in seconds. Nothing is written, so the run's `updated_at` is
   unchanged. A supplied time in the past is still accepted (D6, D7).
4. **Backward refusals give the wait.** Each "must not move backward" refusal
   names the stored time it ran into and the whole seconds until the write
   would succeed (D8).
5. **One test-only override.** The environment variable
   `WORKFLOW_STATE_TEST_CLOCK` pins the seam's value for tests. Only the seam
   reads it, and an override later than the real clock is refused, so it can
   never make a future write possible (D2).
6. **Skill text.** No skill or prompt template passes `--now` or a `now`
   member. Every dispatch carrier gains one clause against wait loops (D9, D10).

## Decisions

### The clock seam

- One function in `workflow-state` returns the current time. With
  `WORKFLOW_STATE_TEST_CLOCK` unset it returns the system clock in UTC,
  truncated to whole seconds. The delivery model only accepts
  `YYYY-MM-DDTHH:MM:SSZ`, so the value must be in that form.
- With the variable set, the value must parse as an RFC3339 UTC timestamp and
  must not be later than the real clock. Otherwise the command exits 2 with
  `workflow-state: invalid WORKFLOW_STATE_TEST_CLOCK: …`. An empty value counts
  as unset.
- No other code in `workflow-state` or its delivery modules reads the clock or
  that variable. The delivery modules receive times as arguments, as they do
  today.
- One shared resolver turns an optional supplied value and a label (`--now`,
  `control now`, `direct owner now`, `contract now`) into the time a command
  uses. Each command reads the seam at most once (D7):
  - A **supplied** time is checked against the skew rule at argument or request
    validation, before `transact` takes the lock.
  - An **omitted** time is read inside the `transact` mutation, under the ledger
    lock. Two clock-stamped writers that race for the lock therefore stamp in
    lock order. If the time were read before the lock, the loser could hold an
    earlier time than the winner's `updated_at` and be refused for moving
    backward.

  A refusal raised in either place happens before `commit_state`, so the run
  file is not written.

### Where `now` becomes optional

- **Flags.** `add_run_arguments` drops `required=True` from `--now`. That
  covers `init-run`, `finish` (both the ledger and the delivery-summary forms),
  `checkpoint-delivery`, `suspend`, `progress`, `register-worker`,
  `mark-progress` and `release-worker`. The read-only commands (`check-launch`,
  `current-launch`, `check-worker`, `resume-pack`, `host-route`) take no time
  and are unchanged.
- **Requests.** The `control` (interface_version 3) and `direct-owner`
  (interface_version 2) requests accept `now` as an optional member. Every other
  member stays required, and an unknown member is still refused. A present
  `now` must be a string, as today; `null` is refused. Making a member optional
  accepts every request that was valid before, so neither interface version
  changes. The control response still echoes the `now` it used, so the caller
  can see the stamped time.
- **Contract input.** `build-delivery --kind contract` accepts an input without
  `now`. The command fills the missing member from the resolver before it calls
  the builder, and a supplied member gets the same skew check. The builder stays
  a pure function of its input. The command now reads the clock for that one
  case, so the "no lock, clock or write" statement in its description becomes
  "no lock or write; it reads the clock only to stamp a contract input that
  omits `now`" (D5). The other kinds do not read the clock.

### Skew rule

- The bound is a constant of 60 seconds. It cannot be configured.
- The rule is: refuse when `supplied − clock > 60 s`. A time exactly 60 seconds
  ahead is accepted, and a past time of any age is accepted. A past time still
  meets every existing ordering check, so it cannot rewind the ledger.
- Refusal text, one stderr line, exit 2:
  `workflow-state: <label> <supplied> is <N> seconds ahead of the clock
  <clock>; a supplied time may lead it by at most 60 seconds — omit it to use
  the clock`.

### Backward refusals

The eight existing refusal sites keep their current prefix, so the existing
assertions still match. Each gains one suffix that names the stored time and
the remaining seconds, rounded up to whole seconds:

`<cmd> time must not move backward: <now> is before the <field> <stored>; it
would succeed in <N> seconds`

`<field>` is `run updated_at` for `control`, `direct-owner`, `register-worker`,
`mark-progress` and `release-worker`, and `attempt last_progress_at` for
`progress`, `suspend` and `finish`. Once every write is clock-stamped and the
skew rule holds, `N` is at most 60 on a ledger written after this change. A
ledger already carrying a future `updated_at` reports its real lead, and the
agent waits that long, once (D8).

`checkpoint-delivery` and the delivery `finish` have no ordering check of their
own today. Their stamp is bounded by the skew rule, and the ledger validator's
existing `launch at ≤ updated_at` invariants are unchanged.

### Skill and prompt text

- Every `workflow-state` example in the shared, Claude-only and Codex skill
  trees drops `--now <utc>` / `--now <RFC3339-now>`. Every request or builder
  JSON example drops its `now` member, and from-issue's sentence "Resolve a
  fresh current RFC3339 UTC instant for every request" is deleted. The
  orchestrate-issues "exact 18-key" wording becomes the 17 required keys.
- `test_dispatch_contracts` gains a fourth clause id, `no-wait-loops`, in its
  one authoritative `CONTRACTS` table:

  > Never write an `until` or `while` loop around `sleep` to wait for
  > something: if a wait is truly needed, run one bounded foreground `sleep N`,
  > then check once.

  Every skill carrier holds it through the default `contracts` tuple. The
  remainder placeholder in ship-handoff becomes "the four leaf-agent clauses".
  The four agent definitions keep only `own-commands` (D10).
- **Living docs, same PR.** CLAUDE.md's `mark-progress` example drops
  `--now <utc>`. Its build-delivery sentence "It is read-only — no lock, clock
  or write" gains the contract-stamp exception from D5. The #171, #181 and #192
  specs are point-in-time records and stay unedited (the-bar: moves keep their
  history). This repo passes no context or ADR paths, so there is no glossary
  or ADR to update.
- The Instruction Budget gate measures the change. The deleted `--now` tokens,
  `now` lines and from-issue sentence are expected to outweigh the added clause
  copies. If they do not, the PR asks for the raise label rather than editing
  the gate.

## Test seams

All new tests drive the CLI from source, as `test_delivery_workflow.py`
already does (agent-helpers rule 5). The override reaches both its
subprocess runs and the in-process `run_script` path through the `env` mapping
each one already passes.

1. **Skew refusal** (`test_delivery_workflow.py`). Pin the clock with the
   override. Supply a time 15 minutes ahead to `checkpoint-delivery`,
   `release-worker`, `finish` and `control`. Each one exits 2 with the skew
   text, and the run file's bytes are unchanged. A time 60 seconds ahead is
   accepted.
2. **Default clock** (`test_delivery_workflow.py`). With no override, each of
   the eight commands, `control` and `direct-owner` succeeds without a time, and
   the recorded stamp is within 5 seconds of `datetime.now(timezone.utc)` read
   by the test. A second case pins the override and asserts the exact stamp.
3. **Backward text** (`test_delivery_workflow.py`). Record a write at T, then
   supply T−37s. The refusal names T and "37 seconds".
4. **Seam** (`test_workflow_state.py`). An override later than the real clock
   and a malformed override are both refused. A source scan of the
   `workflow-state` scripts finds the override name and a clock call in exactly
   one function. This is the AC's "single sanctioned seam".
5. **Skill pins** (`test_workflow_skill_contracts.py`). No document in the
   three skill trees has a `--now` token in a `workflow-state` argv, and no
   request or builder example has a `now` key. Existing argv and key-set pins
   are updated to the new forms. `test_shell_example_contracts`' checkpoint
   fixture drops `--now`, and its substitution and backtick cases move to
   another argument. `test_dispatch_contracts` enforces `no-wait-loops`. Under
   agent-helpers rule 6, every pin is on argv, key sets or carrier clauses,
   never on prose.

The existing suite keeps its explicit past fixture times. Under D6 a past time
is valid, so no fixture changes are needed to make it pass.

## Out of scope

- Ledger schema, the deadline and reaper model, and attempt budgets. The
  reaper's comparisons use the resolved time without change.
- Repairing ledgers already carrying a future `updated_at`. D8's message gives
  the wait.
- `observed_at` and other fact timestamps inside builder inputs for
  observations and authority observations. They record when a fact was seen,
  not when the ledger is written.
- Moving `workflow-state` into the `agent_tools` package (agent-helpers rule 1
  binds it when its cluster moves).
- `artifact-budget`, `launch-scope` and every other helper.
- Blocking `WORKFLOW_STATE_TEST_CLOCK` in the lifecycle guard. Under D2 the
  override cannot reach the future, so it grants nothing that a supplied
  past `--now` does not already grant.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One clock function in `workflow-state` and one resolver every command calls once before the lock. The delivery modules keep receiving times as arguments | the-bar DRY and Defense in depth; the AC's "single sanctioned seam"; no clock read exists in the scripts today | Reading the clock in each command or in the delivery modules spreads the seam and makes "never read except through the seam" impossible to scan for |
| D2 | Test override `WORKFLOW_STATE_TEST_CLOCK` is an env var, read only by the seam. It is refused when later than the real clock, so it can only pin the present or the past | Tests run the CLI both as subprocesses and through `run_script(env=…)`; only the environment reaches both. The incident's harm is future time only | An in-process monkeypatch cannot reach subprocess runs. An unbounded env override would let an agent bypass the skew rule. A wrapper that scrubs the variable does not exist, because the script is installed raw |
| D3 | `now` becomes optional for all eight `--now` commands and for the `control` and `direct-owner` requests, with no interface-version bump | Issue body; the-bar Token economy ("let defaults absorb the common case so it need emit nothing at all"); optionality accepts every request that was valid before | Removing `now` outright breaks existing callers and the deterministic test fixtures. Keeping it required with a `null` sentinel still makes agents emit a member |
| D4 | The clock value is truncated to whole seconds | The delivery model and builder accept only `YYYY-MM-DDTHH:MM:SSZ` | Microsecond stamps would be refused downstream of the ledger write |
| D5 | `build-delivery --kind contract` fills an omitted `now` from the resolver, and a supplied one gets the skew check. The builder stays pure, and only the command shell reads the clock. This updates the "reads no clock" statement from #171, #181 and #192 for that one case | AC: no template may carry a literal timestamp, and the contract input example does. A future `created_at` becomes the initial intent's `issued_at`, which reconcile treats as not yet valid — the same bug class | Leaving the contract `now` required keeps a hand-typed time in from-issue and orchestrate-issues and fails the AC |
| D6 | Skew bound: a constant of 60 seconds, inclusive, and not configurable. Past times stay accepted | Issue ("about 60s"); the-bar YAGNI; every existing test fixture is a past time | A configurable bound has no caller. Refusing past times breaks the suite and the reaper tests, and adds no safety, because ordering checks already stop rewinds |
| D7 | A supplied time is skew-checked before the lock. An omitted time is read from the seam inside the `transact` mutation, under the lock. Both refusal points come before `commit_state` | AC: "the run's `updated_at` is unchanged"; `transact` commits only after the mutation returns. Concurrent owners and workers share one run file | Reading the clock before the lock lets two clock-stamped writers commit out of order, so the later one is refused for moving backward — the incident's symptom, with no agent at fault |
| D8 | Backward refusals keep their prefix and append the stored time and the whole seconds until the write would succeed, rounded up. There is no clamping or auto-wait | Issue ("says how long until it would succeed"); the-bar Fail loud; existing assertions match the prefix | Clamping `now` up to `updated_at` silently stamps a false time. Sleeping inside the helper hides the wait from the agent |
| D9 | No skill, reference or prompt template carries `--now` or a `now` member. The pin is structural, on argv and JSON keys across all three skill trees | AC pin; agent-helpers rule 6 allows argv and key-set pins | Leaving examples that pass `--now "$(date -u …)"` still hand-builds a time and is refused by the shell-example contract |
| D10 | The wait-loop rule is a fourth dispatch-contract clause, `no-wait-loops`, held by every skill carrier but not by the agent definitions | Rule 6 allows carrier-clause pins but not English-phrase pins. The incident was a dispatched owner, and every owner and worker prompt is a carrier | A prose rule in one SKILL.md would need a phrase pin, which rule 6 forbids. Global AGENTS.md costs hot bytes in every session. Adding it to the agent definitions too has no incident behind it |
| D11 | Refines D1 and D7. The seam is `ledger_clock()`, the only function holding the override literal and a clock call. A supplied time is checked first, before any input file is read. `direct-owner`, which has no `transact`, reads an omitted time right after its issue lock and every existing direct run's state lock are held. `control` binds its command-scope `now` inside the mutation, so its closures and response echo use the stamped value | AC "single sanctioned seam" (scanned by function); D7's lock-order argument applies to `direct-owner`'s own locks | A module-level override constant makes the scan count two sites. Stamping `direct-owner` before its run locks reopens D7's out-of-order race |
| D12 | `build-delivery --kind contract` skew-checks a supplied `now` only when it parses. A malformed or non-string value reaches the builder unchanged, so its refusal text does not change. The existing "missing `now` is refused" case becomes a missing `issue` | D5; the builder's own validation owns malformed input (#171) | Parsing every `now` in the command would replace the builder's refusal text for malformed input with a second, different message |
