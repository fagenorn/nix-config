# Transaction result ownership Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Preserve each effect or observer result as it was returned, through
validation, later external calls, and durable transaction recording.

**Architecture:** Add one private copy-then-validate intake helper in
`transaction_core` and use it at every effect/observer return. Keep the existing
pure validators and each operation's fenced protocol in their current homes,
per [spec D1–D2](../specs/2026-09-29-issue-229-result-ownership-design.md#decision-ledger).

**Tech stack:** Python standard library, `copy.deepcopy`, `unittest`, existing
`TransactionStore` and durable JSON history; source-only `just` test recipe.

## Global Constraints

- `TransactionStore`'s public interface, schema version, event shapes, outcome and error vocabularies, and refusal precedence remain unchanged.
- Calls occur outside locks.
- Durable invocation intent still precedes invoke, and an interval marker still precedes interval proof collection.
- Effect and observer exceptions propagate; malformed results still raise `EffectResultInvalid` and append no completion facts.
- Already written intent or interval markers remain open.
- Every operation retains its second-hold terminal and custody checks.
- Do not replace these distinct rules with a shared two-hold execution framework.
- Accepted result fields remain the current exact dictionary shapes and scalar values.
- Document construction, request/parameter ownership, late owner results, and synchronization against adapter threads during copying remain outside scope.
- Follow the machine-global bar/Python shard and `docs/standards/agent-helpers.md`; introduce no dependency, launcher, public module, or new serialization rule.

## Test seams

- Public store operations, temporary durable roots, injected fake clock, and fake effects/observers only, per spec D3.
- Assert both returned transactions and a fresh `TransactionStore(root).load`; no calls or patches to the intake helper, validators, locks, or append methods.
- Invocation's inspect mutates or clears its retained invoke reply before recording; single-return paths arm a one-shot mutation at the next injected clock read without advancing time.
- Keep recovery refusal tests and add successful multi-result reuse for both recovery entry points.

## Delivery estimate and boundaries

Estimate: five modified code/test files, comprising one core file, one shared
fake-clock fixture, and three operation test modules. Estimated production
change is under 60 lines; estimated test growth is 150–230 lines. These are
planning estimates, not final artifact measurements. The helper and its call
sites form one independently testable slice. Regression code is the main
growth risk; no package or subsystem split is expected.

File responsibilities: `transaction_core.py` owns intake and orchestration;
`test_transaction_custody.py` owns the existing fake clock;
`test_transaction_invocation.py` covers invocation and inspection ownership;
`test_transaction_proof.py` covers proof result ownership;
`test_transaction_recovery.py` covers per-unit recovery references.

Baseline: implementation base `3bf2936` contains the signed design and unchanged
core from `6a8f8a2`. The owner ran command ID `agent-workflow-tests` (`just
agent-workflow-tests`): 1,731 tests, OK, three skipped, in 544.998 seconds.
Planning also executed the seven exact regression snippets in memory against
that unchanged core: the rewrite and three clock-mutation cases failed, clearing
raised `KeyError: 'result'`, and both recovery cases passed. No repository code
or tests were modified by this probe.

## Task index

Task 1 — Own every external result before validation and recording — python/agent_tools/transaction_core.py, tests/test_transaction_custody.py, tests/test_transaction_invocation.py, tests/test_transaction_proof.py, tests/test_transaction_recovery.py — full — [task-1.md](2026-09-29-issue-229-result-ownership.tasks/task-1.md)

## Decisions

The [spec's single decision ledger](../specs/2026-09-29-issue-229-result-ownership-design.md#decision-ledger)
owns the choices: D1 governs the narrow intake helper, D2 preserves protocol and
validator boundaries, and D3 governs public-seam evidence and mutation timing.
Task 1 implements all three; planning introduces no additional behavioral choice.

---
