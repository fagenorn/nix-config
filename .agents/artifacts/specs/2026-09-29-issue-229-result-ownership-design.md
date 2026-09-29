# Transaction result ownership at external returns

Design for [#229](https://github.com/fagenorn/nix-config/issues/229), 2026-09-29,
against `6a8f8a2` (containing the issue baseline `3bb4d9d`). Decisions are autonomous
judgments within the delegated issue scope.

## Problem

An effect or observer may retain the dictionary it returns. The store currently
validates aliases in `inspect_action`, `invoke_action`, and `collect_obligation`,
then reads their fields later. In particular, post-invoke inspection can rewrite
the already validated invocation result, causing different facts to be persisted,
or clear it, causing a missing-key error and leaving a valid attempt open.

The transaction must retain the result the adapter returned. Recovery's existing
observation loop already copies before validation; this ownership rule should
apply consistently to every external result intake.

## Solution

Immediately capture an owned copy of each external return, validate that copy,
and use only that copy for subsequent decisions and history records. Centralize
this ordering in one private intake helper in `transaction_core` (D1). Keep the
external calls and operation-specific store protocols where they are (D2).

## Decisions

### Intake interface and ownership

The private helper takes the returned value, its existing violation function,
and the existing transaction/operation error context. Its implementation first
uses `copy.deepcopy`, then runs the supplied validator on that copy, raises
`EffectResultInvalid` with the existing context and violation on failure, and
otherwise returns the copy. There is no validator registry, new public method,
result wrapper, schema conversion, or catch around adapter exceptions.

Callers invoke this helper immediately around each external return. In
`invoke_action`, invocation capture and validation complete before calling
`effect.inspect`; that inspection is separately captured and validated before
the second fenced hold. An invalid invocation still prevents inspection.
`inspect_action` and `collect_obligation` capture before their second hold.
The recovery observation loop uses the same helper for each request before
making the next observation, preserving its current ownership behavior.

The helper sequences intake only. The invoke and inspect validators remain in
`transaction_invocation`; the proof validator still receives its obligation
entry so derived-reason restrictions hold; recovery keeps its check validator,
which delegates the shared closed observation shape to `transaction_proof`.
Pure rules and history validation stay in their existing modules. Accepted
result fields remain the current exact dictionary shapes and scalar values.

### Protocol compatibility

`TransactionStore`'s public interface, schema version, event shapes, outcome and
error vocabularies, and refusal precedence remain unchanged. Calls occur outside
locks. Durable invocation intent still precedes invoke, and an interval marker
still precedes interval proof collection. Effect and observer exceptions
propagate; malformed results still raise `EffectResultInvalid` and append no
completion facts. Already written intent or interval markers remain open.

Capturing a result grants no permission to append it. Standalone inspection
retains its action-history comparison; invocation retains its intent/history
validation; proof retains clock, admission and cohort checks; recovery retains
its revision comparison and zero-request fast path. Every operation retains its
second-hold terminal and custody checks. Do not replace these distinct rules
with a shared two-hold execution framework.

## Test seams

Use the existing public `TransactionStore` interface, temporary durable root,
injected fake clock, and fake effects/observers (D3). Assert both returned
transactions and a fresh store's `load`, including recorded fields and derived
action status. No tests call or patch the new helper, validators, locks, or
append methods.

Required invocation regressions use an effect that retains the actual dictionary
returned by invoke:

1. Invoke returns `{"result": "accepted", "error_class": null, "reference":
   "invoke:original"}`. Its subsequent inspect changes that dictionary to
   `rejected`, `provider_throttled`, and `inspect:changed`, while returning its
   own valid `satisfied` inspection with a distinct reference. Both snapshots
   must record the original accepted invocation and the inspection's own values;
   the action must be satisfied with its attempt closed.
2. The same inspect instead clears the retained invocation dictionary. The
   operation must still complete, persist the original invocation and valid
   inspection, close the attempt, and load successfully without a missing-key
   error.

Run both tests against the baseline implementation and demonstrate failure
before accepting the fix. Mutating only after `invoke_action` returns does not
exercise this defect.

Cover standalone inspection, post-invoke inspection, and proof collection by
having the fake adapter arm a one-shot callback on the injected clock. Its next
read mutates the retained reply after the external return and before recording;
the callback preserves the clock value. Assert that the original fields survive
in the returned and freshly loaded transactions. This uses an existing public
dependency without threads, sleeps, or private hooks.

Keep recovery's existing reused-dictionary refusal tests for anchor and
compatibility observations. For each of `verify_anchors` and `begin_recovery`,
add successful multi-result coverage with distinct references from a reused
dictionary, proving each unit retains its own reference in returned and freshly
loaded history. Existing malformed-result, exception,
stale-custody, history-change, interval, and cohort tests remain the compatibility
checks. The asserted sweep and neutrality checks continue unchanged.

## Out of scope

- Transaction document construction, snapshot ownership generally, requests,
  caller parameters, and late owner-result intake.
- New result shapes, serialization formats, schema versions, public interfaces,
  exception translation, or synchronization with adapter-owned threads while a
  copy itself is being made.
- Moving pure policy, changing retries or lifecycle rules, combining fenced
  protocols, or adding an adapter framework.
- New glossary or ADR records: no writable context route was supplied, and the
  local reversible helper introduces no separate architectural commitment.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Use one private core intake helper to deep-copy each external return before validating and retaining it; pass the existing operation validator. | #229 ownership scope; existing recovery `_observed` precedent; [#208 D26](2026-09-28-issue-208-recovery-plans-design.md#decision-ledger); the-bar DRY. | Copy at final event construction or after another call (too late); duplicate intake blocks or a new public result module (drift or unnecessary interface). |
| D2 | Share result intake across invocation, both inspection paths, proof collection, and recovery checks while preserving each operation's existing two-hold protocol and pure-rule homes. | [#206 D3/D11](2026-09-28-issue-206-administrative-protocol-design.md#decision-ledger); [#205 D33/D34](2026-09-28-issue-205-fenced-custody-design.md#decision-ledger); [#208 D20](2026-09-28-issue-208-recovery-plans-design.md#decision-ledger). | A generic call-and-commit framework (different history guards and durable pre-call records); invocation-only copying (leaves the same ownership rule inconsistent elsewhere). |
| D3 | Prove ownership at the public store seam with mutation before recording, baseline-failing invocation regressions, fresh loads, and recovery reuse coverage; use the injected clock for single-return paths. | #229 acceptance; [#206 D13](2026-09-28-issue-206-administrative-protocol-design.md#decision-ledger); [#208 D16](2026-09-28-issue-208-recovery-plans-design.md#decision-ledger); existing fake-world tests; the-bar tests that can fail. | Helper mocks or post-operation mutation alone (do not expose this aliasing window), concurrent timing tests (unnecessary nondeterminism), or result identity assertions (implementation-coupled). |
